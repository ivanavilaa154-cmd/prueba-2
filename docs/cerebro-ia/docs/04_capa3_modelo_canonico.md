# 04 — Capa 3b: Modelo canónico (el contrato)

> Todas las fuentes se traducen a estas tablas (vía `mapping.yml`, docs/05) y todos los KPIs se calculan solo desde acá.
> El modelo es **agnóstico**: no contiene campos, códigos ni valores de ningún sistema, proveedor o país. Lo específico entra por el mapeo y por los catálogos de referencia.
> Cambiar una columna requiere: migración, actualización de este doc, del catálogo de requisitos (`kpis/src/requisitos.yml`) y regenerar KPIs.

## 0. Convenciones

| Regla | Detalle |
|---|---|
| Columnas técnicas (todas las tablas `core`) | `tenant_id uuid`, `source_id text` (fuente configurada), `source_key text` (id en origen), `_cargado_at timestamptz`, `_actualizado_at timestamptz` |
| PK | `<entidad>_id text` = `md5(tenant_id‖'|'‖source_id‖'|'‖source_key)`; dims con identidad unificada usan el ID de `core.xref_entidad` (§6) |
| Unicidad | `unique (tenant_id, source_id, source_key)` |
| Montos | `numeric(18,2)`; cantidades `numeric(18,4)`; ratios nunca se guardan (se calculan en la capa semántica) |
| Moneda | sin sufijo = moneda base del tenant; `*_orig` = moneda original; con `moneda_orig char(3)` (ISO 4217) y `tc_aplicado` |
| Impuestos | `importe_neto*` **sin** impuesto indirecto; `importe_impuesto` = impuesto indirecto al consumo; `importe_otros_impuestos` = percepciones/tasas; `importe_total` = lo que se paga/cobra |
| Fechas | `fecha_*` = `date` en zona del tenant; `*_at` = `timestamptz` UTC |
| Categóricas | valor del **catálogo canónico** (`seeds/ref_valores_canonicos.csv`, dominio indicado en cada columna); `*_origen` guarda el valor crudo |
| Signo | Ventas/comprobantes: importes positivos + `signo smallint` (1 / −1). Tesorería y stock: importes/cantidades **con signo** |
| Desconocidos | FK desconocida → miembro `'-1'` ("Sin asignar") de la dim; nunca NULL |

Macros de la plataforma (`warehouse/dbt/macros/`), usadas por el SQL que genera el compilador de mapeos:

| Macro | Qué hace |
|---|---|
| `canonical_id(source_id, source_key)` | ID canónico |
| `to_base_currency(importe, moneda, fecha)` | convierte con `ref.tipo_cambio` (serie por defecto del tenant) a la fecha del hecho; si moneda = base → 1; si falta TC → null + DQ |
| `sin_impuesto(importe, tasa)` | `importe / (1 + tasa/100)` |
| `local_date(ts)` / `local_ts(ts)` | fecha/hora en zona del tenant |
| `hash_pii(x)` | sha256(normalizado ‖ sal del tenant) |
| `normalize_sku(x)` | mayúsculas, sin espacios ni separadores configurables |
| `normalize_tax_id(x)` | solo alfanuméricos, mayúsculas |
| `real_amount(importe, fecha, periodo_base)` | `importe × indice(periodo_base) / indice(mes(fecha))` con la serie del tenant |
| `pedido_valido()` | filtro estándar de pedidos (§7.3) |

---

## 1. Referencias (`ref`)

```sql
create table ref.fecha (                       -- calendario base (global)
  fecha date primary key, anio int, trimestre int, mes int, semana_iso int, anio_iso int,
  dia_mes int, dia_semana int,                -- 1 = lunes
  inicio_semana date, inicio_mes date, fin_mes date, inicio_trimestre date, es_fin_de_semana boolean
);
create table ref.feriado (
  fecha date, pais char(2), jurisdiccion text default 'nacional', descripcion text, tipo text,
  primary key (fecha, pais, jurisdiccion)
);
create view ref.fecha_tenant as                -- calendario por tenant (hábiles según su país + feriados propios en ops.tenant_config_kpi)
  select t.tenant_id, f.*, (f.fecha in (select fecha from ref.feriado where pais = t.pais)) es_feriado,
         (not f.es_fin_de_semana and f.fecha not in (…)) es_habil,
         evento_comercial                       -- texto libre cargado por tenant (fechas especiales que no deben usarse como base)
  from ops.tenant t cross join ref.fecha f;

create table ref.tipo_cambio (
  fecha date, moneda_origen char(3), moneda_destino char(3),
  serie text,                                  -- nombre libre de la serie (ej. 'oficial_venta', 'mercado'); el tenant elige la suya
  valor numeric(18,8) not null, source_id text,
  primary key (fecha, moneda_origen, moneda_destino, serie)
);
-- Días sin cotización → última cotización anterior (forward fill en ref.tipo_cambio_diario).

create table ref.indice_precios (
  serie text, periodo date,                   -- primer día del mes
  indice numeric(18,6) not null, variacion_mensual numeric(10,6),
  es_estimado boolean default false,          -- último mes sin publicar → estimado y marcado
  source_id text, primary key (serie, periodo)
);

create table ref.valores_canonicos (           -- seed: TODOS los dominios categóricos del modelo
  dominio text, valor text, descripcion text, orden int, atributos jsonb,   -- ej. {"signo": -1} para nota_credito
  primary key (dominio, valor)
);

create table ref.plan_cuentas_estandar (       -- seed: plan de cuentas estándar de gestión (docs §1.1)
  codigo_estandar text primary key, nombre text,
  tipo text,        -- activo, pasivo, patrimonio, ingreso, costo, gasto
  subtipo text,     -- caja_bancos, cxc, inventario, otros_activos_corrientes, bienes_uso, cxp, deudas_fiscales, deudas_sociales, prestamos, otras_deudas, patrimonio, ventas, descuentos_devoluciones, cmv, gasto_comercial, gasto_administrativo, gasto_personal, amortizaciones, resultado_financiero, otros_resultados, impuesto_renta
  eerr_linea text, eerr_orden int, es_corriente boolean, naturaleza char(1),
  es_variable boolean                         -- para punto de equilibrio (FIN-20); configurable por tenant
);
```

### 1.1 Líneas del Estado de Resultados (`eerr_linea`)

| orden | eerr_linea | Cálculo |
|---|---|---|
| 10 | `ventas_brutas` | + |
| 20 | `descuentos_devoluciones` | − |
| 30 | **ventas_netas** | 10 − 20 |
| 40 | `cmv` | − |
| 50 | **margen_bruto** | 30 − 40 |
| 60 | `gastos_comercializacion` | − (comisiones de venta y de canales, fletes de venta, publicidad, impuestos sobre ventas brutas, comisiones de medios de cobro) |
| 70 | `gastos_administracion` | − |
| 80 | `gastos_personal` | − |
| 90 | **ebitda** | 50 − 60 − 70 − 80 |
| 100 | `amortizaciones` | − |
| 110 | **ebit** | 90 − 100 |
| 120 | `resultado_financiero` | ± (intereses, gastos bancarios, impuestos sobre movimientos bancarios, diferencias de cambio, ajuste por inflación contable si existe) |
| 130 | `otros_resultados` | ± |
| 140 | **resultado_antes_impuestos** | 110 ± 120 ± 130 |
| 150 | `impuesto_renta` | − |
| 160 | **resultado_neto** | 140 − 150 |

---

## 2. Traducciones por tenant

```sql
create table core.map_cuenta_contable (        -- plan de cuentas del cliente → estándar (se completa en onboarding, asistido)
  tenant_id uuid, source_id text, codigo_cuenta_origen text,
  codigo_estandar text references ref.plan_cuentas_estandar,
  validado_por text, validado_at timestamptz,
  primary key (tenant_id, source_id, codigo_cuenta_origen)
);
```

El resto de las traducciones de valores (estados, canales, medios de pago, motivos, tipos de movimiento, etc.) **no son tablas**: se declaran en los `value_maps` del `mapping.yml` de cada fuente (docs/05 §5). Los valores sin traducir van a `ops.valores_sin_mapear` y a `'otro'`.

---

## 3. Dimensiones (`core.dim_*`)

Todas incluyen las columnas técnicas y un miembro `'-1'` por tenant.

```sql
create table core.dim_cliente (
  cliente_id text primary key,
  nombre text,
  tipo_persona text,             -- dominio tipo_persona: 'juridica','fisica','desconocida'
  tipo_cliente text,             -- dominio tipo_cliente: 'empresa','consumidor'
  identificador_fiscal text,     -- solo personas jurídicas (normalize_tax_id); null para personas físicas
  documento_hash text,           -- hash_pii del documento de personas físicas
  condicion_fiscal text,         -- dominio condicion_fiscal: 'contribuyente_general','contribuyente_simplificado','exento','consumidor_final','exterior','desconocida'
  email_hash text, telefono_hash text,
  pais char(2), region text, ciudad text, codigo_postal text,    -- region = primer nivel administrativo, normalizado con ref.region si existe
  vendedor_id text, lista_precios text,
  limite_credito numeric(18,2), condicion_pago_dias int,         -- 0 = contado
  canal_adquisicion text,        -- canal_marketing del primer pedido (calculado)
  fecha_alta date, fecha_primera_compra date, fecha_ultima_compra date,   -- calculadas desde fct_pedido
  activo boolean
);

create table core.dim_producto (
  producto_id text primary key,
  sku text, codigo_barras text, nombre text,
  producto_padre_id text, variante_descripcion text,   -- agrupa variantes bajo un modelo
  categoria_n1 text, categoria_n2 text, categoria_n3 text, marca text, temporada text,
  proveedor_principal_id text,
  unidad_medida text,            -- dominio unidad_medida
  es_servicio boolean default false, es_kit boolean default false, gestiona_stock boolean default true,
  costo_estandar numeric(18,4), costo_estandar_orig numeric(18,4), moneda_costo char(3),   -- costo de reposición vigente
  precio_lista numeric(18,4),    -- sin impuesto
  tasa_impuesto numeric(6,3),
  peso_kg numeric(10,3), volumen_m3 numeric(10,5),
  clasificacion_abc text,        -- calculada (INV-12)
  estado_surtido text,           -- dominio estado_surtido: 'activo','a_discontinuar','discontinuado','estacional_fuera_temporada'
  es_perecedero boolean default false, vida_util_dias int,
  dias_retiro_antes_vencimiento int,   -- política de retiro de exhibición (default por categoría en ops.politica_producto)
  unidades_por_bulto numeric(18,4),    -- para redondear pedidos
  fecha_alta date, activo boolean
);

create table core.dim_deposito (
  deposito_id text primary key, nombre text,
  tipo text,                     -- dominio tipo_deposito: 'propio','sucursal','fulfillment_tercero','operador_logistico','transito','virtual','consignacion'
  sucursal_id text, region text,
  es_vendible boolean, incluir_en_kpis boolean default true
);

create table core.dim_sucursal (
  sucursal_id text primary key, nombre text,
  tipo text,                     -- dominio tipo_sucursal: 'local','deposito','oficina','online'
  pais char(2), region text, ciudad text,
  puntos_emision text[],         -- para asignar documentos fiscales a la sucursal
  metros_cuadrados numeric(10,2), fecha_apertura date, activa boolean
);

create table core.dim_vendedor (vendedor_id text primary key, nombre text, equipo text, sucursal_id text, email_hash text, fecha_ingreso date, activo boolean);

create table core.dim_proveedor (
  proveedor_id text primary key, nombre text, identificador_fiscal text, condicion_fiscal text, pais char(2),
  categoria_proveedor text,      -- dominio categoria_gasto
  condicion_pago_dias int, lead_time_dias_estandar int,
  monto_minimo_pedido numeric(18,2), dias_pedido int[],          -- días de semana en que se le pide (1 = lunes)
  acepta_devolucion_vencidos boolean, dias_aviso_devolucion int,
  activo boolean
);

create table core.dim_cuenta_contable (
  cuenta_id text primary key, codigo text, nombre text,
  codigo_estandar text,          -- vía core.map_cuenta_contable; '-1' si falta (DQ-08)
  tipo text, subtipo text, eerr_linea text, imputable boolean
);

create table core.dim_centro_costo (centro_costo_id text primary key, nombre text, area text, sucursal_id text);   -- area: dominio area_empresa

create table core.dim_cuenta_tesoreria (
  cuenta_tesoreria_id text primary key, nombre text,
  tipo text,                     -- dominio tipo_cuenta_tesoreria: 'banco_corriente','banco_ahorro','caja','billetera_digital','inversion_liquida','plazo_fijo','tarjeta_credito'
  entidad text,                  -- nombre de la institución (dato del cliente, no del modelo)
  moneda char(3), numero_hash text, es_disponible boolean, activa boolean
);

create table core.dim_transportista (
  transportista_id text primary key, nombre text,
  tipo text,                     -- dominio tipo_transportista: 'correo','mensajeria','flota_propia','logistica_de_marketplace','operador_logistico','retiro'
  servicio text                  -- dominio servicio_envio: 'estandar','express','mismo_dia','a_sucursal','a_domicilio'
);

create table core.dim_campana (
  campana_id text primary key,
  plataforma text,               -- nombre de la plataforma publicitaria tal como lo define el operador en el mapping (texto libre normalizado en minúsculas)
  cuenta_ads_id text, nombre text,
  objetivo text,                 -- dominio objetivo_campana: 'ventas','leads','trafico','alcance','interaccion','app','retargeting','otro'
  tipo_campana text,             -- dominio tipo_campana: 'busqueda','shopping_catalogo','display','video','social','marketplace','email','otro'
  canal_marketing text,          -- dominio canal_marketing
  estado text, fecha_inicio date, fecha_fin date, presupuesto_diario numeric(18,2),
  utm_campaign_normalizada text  -- clave de unión con analítica web y pedidos
);
```

---

## 4. Hechos (`core.fct_*`)

### 4.1 Ventas

```sql
create table core.fct_pedido (
  pedido_id text primary key,
  numero text,
  origen_externo_source_id text, origen_externo_key text,   -- si el pedido fue replicado desde otra fuente (docs/05 §6)
  es_fuente_verdad boolean not null,
  fecha_pedido date not null, pedido_at timestamptz,
  fecha_confirmacion date, confirmado_at timestamptz,
  fecha_facturacion date, fecha_entrega date, fecha_cancelacion date,
  estado text not null,          -- dominio estado_pedido: 'borrador','pendiente_pago','confirmado','en_preparacion','despachado','entregado','cancelado','devuelto_total'
  estado_origen text,
  estado_pago text,              -- dominio estado_pago: 'pendiente','aprobado','parcial','rechazado','reembolsado','contracargo'
  cliente_id text, vendedor_id text, canal_id text, sucursal_id text, deposito_id text,
  moneda_orig char(3), tc_aplicado numeric(18,8),
  importe_bruto numeric(18,2),         -- Σ precio lista × cantidad, sin impuesto
  importe_descuento numeric(18,2),     -- sin impuesto
  importe_neto numeric(18,2),          -- bruto − descuento; sin impuesto; SIN envío
  importe_impuesto numeric(18,2),
  importe_envio_cobrado numeric(18,2), -- sin impuesto
  importe_total numeric(18,2),         -- lo que pagó el cliente
  importe_neto_orig numeric(18,2),
  costo_mercaderia numeric(18,2),      -- Σ líneas
  comision_canal numeric(18,2),        -- comisión cobrada por el canal de venta (marketplace, plataforma), sin impuesto
  costo_financiacion numeric(18,2),    -- costo de cuotas/financiación absorbido por el vendedor
  costo_envio_vendedor numeric(18,2),  -- costo de envío a cargo del vendedor informado por el canal
  cantidad_unidades numeric(18,4), cantidad_lineas int,
  es_primera_compra boolean,           -- calculado
  cupon text,
  utm_source text, utm_medium text, utm_campaign text, landing_url text, referrer text,
  canal_marketing text,                -- dominio canal_marketing (docs/kpis/marketing §0.3)
  medio_pago text,                     -- dominio medio_pago
  cuotas int
);

create table core.fct_pedido_linea (
  pedido_linea_id text primary key, pedido_id text not null, producto_id text not null, fecha_pedido date,
  cantidad numeric(18,4),
  precio_unitario_lista numeric(18,4), precio_unitario_neto numeric(18,4),   -- sin impuesto
  importe_descuento numeric(18,2),     -- incluye prorrateo de descuentos de cabecera
  importe_neto numeric(18,2), tasa_impuesto numeric(6,3),
  costo_unitario numeric(18,4), costo_total numeric(18,2),
  cantidad_entregada numeric(18,4), cantidad_facturada numeric(18,4), cantidad_devuelta numeric(18,4),
  promocion_id text,                   -- promoción aplicada a la línea (mapping o detección por precio/vigencia, §4.6)
  importe_descuento_promocion numeric(18,2)
);

create table core.fct_comprobante (   -- documentos de venta y de compra
  comprobante_id text primary key,
  circuito text not null,              -- dominio circuito: 'venta','compra'
  clase text not null,                 -- dominio clase_comprobante: 'factura','nota_credito','nota_debito','ticket','recibo','no_fiscal'
  tipo_documento_origen text,          -- código/nombre del tipo en origen (auditoría)
  serie text, punto_emision text, numero text, numero_completo text,
  codigo_autorizacion_fiscal text,
  fecha_emision date not null, fecha_vencimiento date,
  cliente_id text, proveedor_id text,
  identificador_fiscal_contraparte text, condicion_fiscal_contraparte text,
  pedido_id text, orden_compra_id text, canal_id text, sucursal_id text, vendedor_id text,
  categoria_gasto text,                -- solo compras; dominio categoria_gasto
  moneda_orig char(3), tc_aplicado numeric(18,8),
  importe_neto_gravado numeric(18,2), importe_no_gravado numeric(18,2), importe_exento numeric(18,2),
  importe_neto numeric(18,2),          -- gravado + no gravado + exento
  importe_impuesto numeric(18,2), importe_otros_impuestos numeric(18,2),
  importe_total numeric(18,2), importe_total_orig numeric(18,2),
  signo smallint not null,             -- de ref.valores_canonicos(clase_comprobante).atributos.signo
  estado text,                         -- dominio estado_comprobante: 'emitido','anulado'
  computa_venta boolean,               -- false para recibos/no fiscales
  conciliado_fiscal boolean            -- FIN-18
);

create table core.fct_comprobante_linea (
  comprobante_linea_id text primary key, comprobante_id text not null, producto_id text, cuenta_id text, centro_costo_id text,
  descripcion text, cantidad numeric(18,4), precio_unitario_neto numeric(18,4),
  importe_neto numeric(18,2), tasa_impuesto numeric(6,3), importe_impuesto numeric(18,2),
  costo_unitario numeric(18,4), costo_total numeric(18,2)
);

create table core.fct_devolucion (
  devolucion_id text primary key, pedido_id text, pedido_linea_id text, comprobante_id text,
  producto_id text, cliente_id text, canal_id text,
  fecha_solicitud date, fecha_recepcion date, fecha_reintegro date,
  cantidad numeric(18,4), importe_neto numeric(18,2),
  motivo text,                         -- dominio motivo_devolucion: 'defecto_calidad','no_coincide_descripcion','talle_modelo','arrepentimiento','error_preparacion','danado_transporte','no_entregado','otro'
  motivo_origen text,
  estado text,                         -- dominio estado_devolucion: 'solicitada','en_transito','recibida','reintegrada','rechazada'
  reingresa_stock boolean
);

create table core.fct_oportunidad (
  oportunidad_id text primary key, nombre text, cliente_id text, vendedor_id text, lead_id text,
  pipeline text, etapa_origen text,
  etapa text,                          -- dominio etapa_oportunidad: 'prospecto','calificado','propuesta','negociacion','ganada','perdida'
  orden_etapa int, probabilidad numeric(5,2),
  importe numeric(18,2), importe_orig numeric(18,2), moneda_orig char(3), tc_aplicado numeric(18,8),
  fecha_creacion date, fecha_cierre_esperada date, fecha_cierre date,
  esta_cerrada boolean, esta_ganada boolean,
  motivo_perdida text,                 -- dominio motivo_perdida
  origen text,                         -- dominio canal_marketing
  pedido_id text
);
create table core.fct_oportunidad_historial_etapa (tenant_id uuid, oportunidad_id text, etapa text, entrada_at timestamptz, salida_at timestamptz, source_id text, source_key text, _cargado_at timestamptz, _actualizado_at timestamptz);

create table core.fct_presupuesto (
  presupuesto_id text primary key, version text, periodo date not null,
  concepto text not null,              -- dominio concepto_presupuesto: 'venta_neta','unidades','margen_bruto','eerr_linea','gasto_marketing','cuota_vendedor'
  eerr_linea text, codigo_estandar text,
  canal_id text, sucursal_id text, vendedor_id text, categoria_n1 text, plataforma text,
  importe numeric(18,2), cantidad numeric(18,4)
);
```

### 4.2 Finanzas

```sql
create table core.fct_asiento_linea (
  asiento_linea_id text primary key, asiento_id text, numero_asiento text, diario text,
  fecha_contable date not null, cuenta_id text not null, centro_costo_id text,
  cliente_id text, proveedor_id text, sucursal_id text, comprobante_id text, descripcion text,
  debe numeric(18,2) default 0, haber numeric(18,2) default 0, saldo numeric(18,2),   -- debe − haber
  importe_orig numeric(18,2), moneda_orig char(3), tc_aplicado numeric(18,8),
  estado text,                         -- dominio estado_asiento: 'publicado','borrador','anulado'
  es_cierre boolean default false
);

create table core.fct_documento_cxc (
  documento_cxc_id text primary key, comprobante_id text, cliente_id text not null, vendedor_id text,
  fecha_emision date, fecha_vencimiento date, fecha_vencimiento_estimada boolean,
  importe_original numeric(18,2),      -- total con impuestos, con signo
  saldo_pendiente numeric(18,2), importe_original_orig numeric(18,2), moneda_orig char(3),
  estado text,                         -- dominio estado_documento: 'pendiente','parcial','cancelado','anulado'
  fecha_cancelacion date
);
create table core.fct_documento_cxp (   -- idéntica estructura con proveedor_id y categoria_gasto
  documento_cxp_id text primary key, comprobante_id text, proveedor_id text not null, categoria_gasto text,
  fecha_emision date, fecha_vencimiento date, fecha_vencimiento_estimada boolean,
  importe_original numeric(18,2), saldo_pendiente numeric(18,2), importe_original_orig numeric(18,2), moneda_orig char(3),
  estado text, fecha_cancelacion date
);

create table core.fct_cobro (
  cobro_id text primary key, fecha_cobro date not null, fecha_acreditacion date,
  cliente_id text, cuenta_tesoreria_id text,
  medio_pago text,                     -- dominio medio_pago
  importe numeric(18,2), importe_orig numeric(18,2), moneda_orig char(3), tc_aplicado numeric(18,8),
  importe_retenciones numeric(18,2),   -- retenciones impositivas sufridas (pagos a cuenta, no costo)
  estado text                          -- dominio estado_movimiento: 'confirmado','anulado','rechazado'
);
create table core.fct_aplicacion_cobro (tenant_id uuid, cobro_id text, documento_cxc_id text, fecha_aplicacion date, importe_aplicado numeric(18,2), source_id text, source_key text, _cargado_at timestamptz, _actualizado_at timestamptz, primary key (tenant_id, cobro_id, documento_cxc_id));

create table core.fct_pago (
  pago_id text primary key, fecha_pago date not null, proveedor_id text, cuenta_tesoreria_id text,
  medio_pago text, importe numeric(18,2), importe_orig numeric(18,2), moneda_orig char(3), tc_aplicado numeric(18,8),
  importe_retenciones numeric(18,2), categoria_gasto text, estado text
);
create table core.fct_aplicacion_pago (tenant_id uuid, pago_id text, documento_cxp_id text, fecha_aplicacion date, importe_aplicado numeric(18,2), source_id text, source_key text, _cargado_at timestamptz, _actualizado_at timestamptz, primary key (tenant_id, pago_id, documento_cxp_id));

create table core.fct_movimiento_tesoreria (
  movimiento_tesoreria_id text primary key, cuenta_tesoreria_id text not null,
  fecha date not null, fecha_valor date,
  importe numeric(18,2) not null,      -- CON SIGNO (+ ingreso, − egreso), moneda base
  importe_orig numeric(18,2), moneda_orig char(3), tc_aplicado numeric(18,8),
  saldo_informado numeric(18,2),       -- saldo posterior si el origen lo informa (control de continuidad)
  tipo text not null,                  -- dominio tipo_mov_tesoreria (§4.2.1)
  actividad text,                      -- derivado del tipo: 'operativa','inversion','financiacion','interna'
  descripcion text, referencia text, contraparte_identificador_fiscal text,
  cliente_id text, proveedor_id text, cobro_id text, pago_id text, conciliado boolean
);

create table core.fct_liquidacion_pasarela (   -- cobros electrónicos y liquidaciones de cualquier procesador o billetera
  liquidacion_id text primary key, pasarela text,   -- nombre libre normalizado (dato del cliente)
  pedido_id text, cobro_id text,
  fecha_operacion date, fecha_acreditacion date, medio_pago text, cuotas int,
  importe_bruto numeric(18,2), comision numeric(18,2), costo_financiacion numeric(18,2),
  retenciones numeric(18,2), impuesto_sobre_comision numeric(18,2), importe_neto numeric(18,2),
  estado text                          -- dominio estado_liquidacion: 'aprobado','pendiente','acreditado','rechazado','reembolsado','contracargo'
);
```

Regla anti doble conteo: la comisión de un **canal de venta** va en `fct_pedido.comision_canal`; `fct_liquidacion_pasarela.comision` es solo la del **procesador de pago**. Si una misma fuente cobra ambas, el mapping las separa o carga todo en una sola de las dos (nunca en ambas).

#### 4.2.1 Dominio `tipo_mov_tesoreria`

| tipo | actividad | Cómo se detecta (reglas del `mapping.yml`, no del modelo) |
|---|---|---|
| `cobro_cliente` | operativa | identificador fiscal de cliente conocido, acreditación de pasarela, depósito |
| `liquidacion_tarjeta` | operativa | patrones de liquidación de procesadores |
| `pago_proveedor` | operativa | identificador fiscal de proveedor conocido |
| `sueldos_cargas` | operativa | patrones de nómina y seguridad social |
| `impuestos` | operativa | patrones de organismos recaudadores |
| `impuesto_movimientos_bancarios` | financiacion | impuestos sobre débitos/créditos bancarios, donde existan |
| `comisiones_bancarias` | financiacion | comisiones, mantenimiento |
| `intereses` | financiacion | |
| `prestamo_ingreso` / `prestamo_pago` | financiacion | |
| `inversion_constitucion` / `inversion_rescate` | inversion | |
| `compra_bien_uso` | inversion | |
| `retiro_socios` / `aporte_socios` | financiacion | |
| `transferencia_interna` | interna | detectada por modelo genérico: par de signos opuestos, mismo importe, cuentas del mismo tenant, Δ ≤ 1 día → se excluye de flujos |
| `otros` | operativa | sin regla |

Las reglas de detección (patrones de texto, identificadores fiscales) se declaran por fuente en `mapping.yml` → `reglas_clasificacion` (docs/05 §5.3), y a nivel tenant en `ops.tenant_config_kpi(FIN, reglas_tesoreria)`.

### 4.3 Inventario

```sql
create table core.fct_movimiento_stock (
  movimiento_stock_id text primary key, fecha date not null, movimiento_at timestamptz,
  producto_id text not null, deposito_id text not null,
  tipo_movimiento text not null,       -- dominio tipo_mov_stock (§4.3.1)
  cantidad numeric(18,4) not null,     -- CON SIGNO respecto de deposito_id
  costo_unitario numeric(18,4), costo_total numeric(18,2),
  documento_tipo text, documento_key text, pedido_id text, orden_compra_id text,
  lote text, fecha_vencimiento date,
  motivo_ajuste text                   -- dominio motivo_ajuste: 'rotura','vencimiento','faltante','error_carga','conteo','muestra','otro'
);

create table core.fct_stock_diario (   -- snapshot diario producto × depósito
  tenant_id uuid, fecha date, producto_id text, deposito_id text,
  stock_fisico numeric(18,4), stock_reservado numeric(18,4), stock_disponible numeric(18,4), stock_en_transito numeric(18,4),
  costo_unitario numeric(18,4), valor_stock numeric(18,2), valor_stock_precio_venta numeric(18,2),
  fecha_ultima_venta date, fecha_ultimo_ingreso date, dias_sin_venta int,
  metodo text,                         -- 'foto_fuente' | 'calculado_movimientos'
  source_id text, _cargado_at timestamptz,
  primary key (tenant_id, fecha, producto_id, deposito_id)
);
-- Si una fuente expone stock actual → foto diaria al cierre (hora tenant). Fechas sin foto:
-- stock(d) = stock(foto siguiente) − Σ movimientos (d, foto] con metodo='calculado_movimientos'.

create table core.fct_orden_compra (
  orden_compra_id text primary key, numero text, proveedor_id text, deposito_id text,
  fecha_emision date, fecha_aprobacion date, fecha_entrega_prometida date, fecha_recepcion_completa date,
  estado text,                         -- dominio estado_oc: 'borrador','enviada','confirmada','recibida_parcial','recibida','cancelada'
  estado_origen text, importe_neto numeric(18,2), importe_neto_orig numeric(18,2), moneda_orig char(3), tc_aplicado numeric(18,8)
);
create table core.fct_orden_compra_linea (
  orden_compra_linea_id text primary key, orden_compra_id text, producto_id text,
  cantidad_pedida numeric(18,4), cantidad_recibida numeric(18,4), cantidad_facturada numeric(18,4),
  precio_unitario numeric(18,4), precio_unitario_orig numeric(18,4),
  fecha_entrega_prometida date, fecha_primera_recepcion date, fecha_ultima_recepcion date
);
create table core.fct_recepcion (
  recepcion_id text primary key, orden_compra_id text, orden_compra_linea_id text, proveedor_id text, producto_id text, deposito_id text,
  fecha_recepcion date, cantidad_recibida numeric(18,4), cantidad_rechazada numeric(18,4),
  lote text, fecha_vencimiento date
);
create table core.fct_conteo_inventario (
  conteo_id text primary key, fecha date, producto_id text, deposito_id text,
  cantidad_sistema numeric(18,4), cantidad_contada numeric(18,4), diferencia numeric(18,4), valor_diferencia numeric(18,2)
);
create table core.parametro_reposicion (
  tenant_id uuid, producto_id text, deposito_id text,
  stock_minimo numeric(18,4), stock_maximo numeric(18,4), punto_pedido numeric(18,4),
  lead_time_dias int, stock_seguridad numeric(18,4), multiplo_compra numeric(18,4),
  source_id text, _actualizado_at timestamptz, primary key (tenant_id, producto_id, deposito_id)
);
```

#### 4.3.1 Dominio `tipo_mov_stock`

| valor | signo típico | cuenta como venta | cuenta como compra | es ajuste |
|---|---|---|---|---|
| `compra_recepcion` | + | | ✔ | |
| `venta_despacho` | − | ✔ | | |
| `devolucion_cliente` | + | resta | | |
| `devolucion_proveedor` | − | | resta | |
| `transferencia_salida` / `transferencia_entrada` | − / + | | | |
| `ajuste_positivo` / `ajuste_negativo` | + / − | | | ✔ |
| `merma` | − | | | ✔ |
| `produccion_consumo` / `produccion_alta` | − / + | | | |
| `inventario_inicial` | + | (excluido de KPIs de flujo) | | |

Regla genérica: un movimiento entre dos depósitos del tenant genera **dos filas** (salida y entrada).

### 4.4 Logística

```sql
create table core.fct_envio (
  envio_id text primary key, pedido_id text, numero_seguimiento text, transportista_id text,
  modalidad text,                      -- dominio modalidad_envio: 'flota_propia','transportista_tercero','fulfillment_tercero','logistica_del_canal','operador_logistico','retiro_en_tienda'
  es_controlable boolean,              -- false si preparación y despacho los hace un tercero (se excluye de KPIs de preparación/despacho)
  deposito_origen_id text,
  pais_destino char(2), region_destino text, ciudad_destino text, codigo_postal_destino text,
  zona_destino text,                   -- zona definida por el tenant (ops.tenant_config_kpi(LOG, zonas))
  bultos int, peso_kg numeric(10,3), peso_volumetrico_kg numeric(10,3),
  pedido_at timestamptz, listo_despacho_at timestamptz, despacho_at timestamptz,
  primer_intento_at timestamptz, entrega_at timestamptz, finalizado_at timestamptz,
  fecha_promesa date, fecha_limite_despacho timestamptz,
  estado text not null,                -- dominio estado_envio (§4.4.1)
  estado_origen text, cantidad_intentos int default 0,
  motivo_no_entrega text,              -- dominio motivo_no_entrega: 'ausente','direccion_incorrecta','rechazado','zona_inaccesible','extraviado','danado','otro'
  costo_envio numeric(18,2), costo_envio_estimado boolean,
  importe_envio_cobrado numeric(18,2), moneda_orig char(3),
  es_devolucion boolean default false
);
create table core.fct_evento_envio (evento_envio_id text primary key, envio_id text not null, evento_at timestamptz not null, estado_origen text, estado text, descripcion text, ubicacion text);
create table core.fct_preparacion (
  preparacion_id text primary key, pedido_id text, deposito_id text, operario text,
  inicio_at timestamptz, fin_at timestamptz, lineas int, unidades numeric(18,4), lineas_con_error int default 0
);
```

#### 4.4.1 Dominio `estado_envio`

| valor | es_final | es_exitoso |
|---|---|---|
| `pendiente`, `en_preparacion`, `listo_para_despachar`, `despachado`, `en_transito`, `en_distribucion`, `no_entregado_reintento`, `listo_para_retirar` | no | — |
| `entregado` | sí | sí |
| `devuelto_origen`, `cancelado`, `extraviado_danado` | sí | no |

### 4.5 Marketing

```sql
create table core.fct_ads_diario (
  tenant_id uuid, source_id text, source_key text,
  fecha date not null, plataforma text not null, cuenta_ads_id text,
  campana_id text not null, conjunto_id text, anuncio_id text,
  moneda_orig char(3), tc_aplicado numeric(18,8),
  gasto numeric(18,2), gasto_orig numeric(18,2),
  impresiones bigint, alcance bigint, frecuencia numeric(10,4),     -- alcance/frecuencia no aditivos
  clics bigint, clics_enlace bigint,
  conversiones_plataforma numeric(18,4), valor_conversiones_plataforma numeric(18,2),
  leads_plataforma numeric(18,4), agregados_carrito_plataforma numeric(18,4),
  reproducciones_video bigint, reproducciones_video_75 bigint,
  ventana_atribucion text,
  _cargado_at timestamptz, _actualizado_at timestamptz, primary key (tenant_id, source_id, source_key)
);

create table core.fct_web_diario (
  tenant_id uuid, source_id text, source_key text,
  fecha date not null, propiedad_id text,
  fuente text, medio text, campana text, canal_marketing text, dispositivo text, campana_id text,
  sesiones bigint, usuarios bigint, usuarios_nuevos bigint, sesiones_con_interaccion bigint,
  vistas_pagina bigint, vistas_producto bigint, agregados_carrito bigint, checkouts_iniciados bigint,
  transacciones bigint, ingresos_web numeric(18,2),   -- solo para tasas; la venta oficial es fct_pedido
  leads_web bigint,
  _cargado_at timestamptz, _actualizado_at timestamptz, primary key (tenant_id, source_id, source_key)
);

create table core.fct_email_campana (
  email_campana_id text primary key, plataforma text, tipo text,   -- 'campana','automatizacion'
  nombre text, fecha_envio date,
  destinatarios bigint, entregados bigint, rebotes bigint, aperturas_unicas bigint, clics_unicos bigint,
  bajas bigint, reportes_spam bigint, conversiones numeric(18,4), ingresos_atribuidos numeric(18,2)
);
create table core.fct_suscriptores_diario (tenant_id uuid, fecha date, plataforma text, lista text, suscriptores_activos bigint, altas bigint, bajas bigint, source_id text, _cargado_at timestamptz, primary key (tenant_id, fecha, plataforma, lista));

create table core.fct_lead (
  lead_id text primary key, fecha_creacion date not null, creado_at timestamptz,
  canal_marketing text, utm_source text, utm_medium text, utm_campaign text, campana_id text, formulario text,
  estado_origen text,
  estado text,                         -- dominio estado_lead: 'nuevo','contactado','calificado','descalificado','convertido'
  primer_contacto_at timestamptz, fecha_calificacion date, fecha_conversion date,
  vendedor_id text, cliente_id text, oportunidad_id text, email_hash text, telefono_hash text
);

create table core.fct_atribucion_pedido (   -- calculada (docs/kpis/12_marketing §0.3)
  tenant_id uuid, pedido_id text, modelo text, canal_marketing text, plataforma text, campana_id text, fuente text, medio text,
  peso numeric(6,4) default 1, _cargado_at timestamptz,
  primary key (tenant_id, pedido_id, modelo, canal_marketing, campana_id)
);
```

### 4.6 Precios, promociones y vencimientos

```sql
create table core.fct_lista_precio_proveedor (   -- listas de precios de proveedores (cada formato de lista = una fuente file_import/http_api + mapping)
  lista_precio_proveedor_id text primary key, proveedor_id text not null, producto_id text,   -- producto_id '-1' si el código del proveedor no está vinculado (DQ-21)
  codigo_producto_proveedor text, descripcion_proveedor text,
  fecha_vigencia_desde date not null, fecha_recepcion_lista date,
  precio_lista numeric(18,4),          -- precio de lista del proveedor, sin impuesto, por unidad de compra
  descuento_total_pct numeric(8,4),    -- bonificaciones en cascada ya compuestas: 1 − Π(1 − dᵢ)
  costo_neto numeric(18,4),            -- costo por unidad de venta, sin impuesto, moneda base
  costo_neto_orig numeric(18,4), moneda_orig char(3), tc_aplicado numeric(18,8),
  unidades_por_unidad_compra numeric(18,4),
  es_vigente boolean                   -- última vigencia ≤ hoy por (proveedor, producto)
);

create table core.fct_precio_venta (   -- historial de precios de venta propios
  precio_venta_id text primary key, producto_id text not null,
  lista_precios text, canal_id text, sucursal_id text,   -- null = aplica a todos
  precio numeric(18,4),                -- sin impuesto
  precio_final numeric(18,4),          -- precio al público (con impuesto) tal como se exhibe
  vigente_desde timestamptz not null, vigente_hasta timestamptz,
  es_promocional boolean default false, promocion_id text
);

create table core.dim_promocion (
  promocion_id text primary key, nombre text,
  mecanica text,                       -- dominio mecanica_promocion: 'descuento_pct','precio_especial','nxm','segunda_unidad','combo','cupon','envio_gratis','cuotas_sin_interes','regalo','otro'
  valor numeric(18,4),                 -- % o precio según mecánica
  objetivo text,                       -- dominio objetivo_promocion: 'liquidar_stock','trafico','lanzamiento','rentabilidad','fidelizacion','otro'
  fecha_inicio date, fecha_fin date,
  canal_id text, sucursales text[],    -- null = todas
  aporte_proveedor_pct numeric(8,4), aporte_proveedor_monto numeric(18,2),   -- financiamiento del proveedor
  costo_comunicacion numeric(18,2), campana_id text,
  cupon text, estado text              -- dominio estado_promocion: 'planificada','activa','finalizada','cancelada'
);
create table core.fct_promocion_producto (
  tenant_id uuid, promocion_id text, producto_id text,
  rol text,                            -- 'promocionado','regalo','componente_combo'
  precio_promocional numeric(18,4),
  source_id text, source_key text, _cargado_at timestamptz, _actualizado_at timestamptz,
  primary key (tenant_id, promocion_id, producto_id)
);

create table core.fct_stock_lote (     -- snapshot diario por lote (productos perecederos o con lote)
  tenant_id uuid, fecha date, producto_id text, deposito_id text, lote text,
  fecha_vencimiento date, cantidad numeric(18,4), costo_unitario numeric(18,4),
  metodo text,                         -- 'foto_fuente' | 'estimado_fefo' (desde recepciones con vencimiento, consumiendo por FEFO)
  source_id text, _cargado_at timestamptz,
  primary key (tenant_id, fecha, producto_id, deposito_id, lote)
);
```

Reglas:
- **Promoción por línea:** si la fuente no informa `promocion_id`, el modelo `int_pedido_linea` lo asigna cuando la línea cae en la vigencia, canal y sucursal de una promoción del producto y el precio neto unitario ≤ `precio_promocional` × 1,02 (o descuento ≥ 80 % del `valor` de la mecánica).
- **Lotes sin foto:** si la fuente no expone stock por lote pero sí recepciones con `fecha_vencimiento`, `fct_stock_lote` se estima consumiendo el stock por FEFO (primero vence, primero sale) hasta cuadrar con `fct_stock_diario`; `metodo='estimado_fefo'`.
- **Costo de reposición vigente:** `dim_producto.costo_estandar` se actualiza con el `costo_neto` de la lista vigente del proveedor principal cuando existe.

### 4.7 Actividades (instancias)

```sql
create table ops.actividad (           -- tareas generadas por las reglas de docs/14; una fila por caso detectado
  actividad_id uuid primary key, tenant_id uuid not null,
  tipo text not null,                  -- ACT-01..ACT-06
  caso text not null,                  -- código del caso dentro de la actividad (ej. 'ACT-01.C1')
  clave_dedupe text not null,          -- ej. 'ACT-01|producto|sucursal' → una sola abierta por clave
  entidad jsonb,                       -- {producto_id, sucursal_id, proveedor_id, promocion_id, lote, ...}
  detectada_at timestamptz, fecha_limite timestamptz,
  prioridad text,                      -- dominio prioridad: 'critica','alta','media','baja'
  puntaje numeric(18,4),               -- impacto estimado normalizado para ordenar
  impacto_estimado numeric(18,2),      -- en moneda base (venta, margen o capital en juego)
  evidencia jsonb,                     -- números que justifican la detección
  acciones jsonb,                      -- lista de acciones prescriptas por el caso (docs/14)
  responsable_rol text, asignado_a text,
  estado text,                         -- dominio estado_actividad: 'nueva','en_curso','resuelta','descartada','vencida','cerrada_automatica'
  resolucion text,                     -- valor de las resoluciones permitidas de la actividad
  resuelta_at timestamptz, comentario text,
  artefacto_url text                   -- archivo generado (pedido sugerido, lista de remarcación, etiquetas)
);
create unique index on ops.actividad (tenant_id, clave_dedupe) where estado in ('nueva','en_curso');
```

---

## 5. Relaciones

```
dim_cliente 1─* fct_pedido 1─* fct_pedido_linea *─1 dim_producto
fct_pedido 1─* fct_comprobante (venta) · fct_envio 1─* fct_evento_envio · fct_devolucion · fct_liquidacion_pasarela
fct_comprobante 1─0..1 fct_documento_cxc 1─* fct_aplicacion_cobro *─1 fct_cobro     (idem cxp / pago)
dim_proveedor 1─* fct_orden_compra 1─* fct_orden_compra_linea 1─* fct_recepcion
dim_producto × dim_deposito ─ fct_stock_diario · fct_movimiento_stock · parametro_reposicion
dim_cuenta_contable 1─* fct_asiento_linea · dim_cuenta_tesoreria 1─* fct_movimiento_tesoreria
dim_campana 1─* fct_ads_diario · dim_campana ←utm→ fct_web_diario / fct_pedido / fct_lead
fct_lead 1─0..1 fct_oportunidad 1─0..1 fct_pedido
dim_proveedor 1─* fct_lista_precio_proveedor *─1 dim_producto 1─* fct_precio_venta
dim_promocion 1─* fct_promocion_producto *─1 dim_producto · dim_promocion 1─* fct_pedido_linea (promocion_id)
dim_producto × dim_deposito × lote ─ fct_stock_lote
```

## 6. Identidad (`core.xref_entidad`)

```sql
create table core.xref_entidad (
  tenant_id uuid, entidad text, source_id text, source_key text,
  entidad_id text not null,
  regla text,                          -- la regla que produjo el match (ver abajo)
  confianza numeric(3,2), _actualizado_at timestamptz,
  primary key (tenant_id, entidad, source_id, source_key)
);
```

Reglas genéricas (el orden y la fuente maestra se configuran en `ops.tenant_config_kpi(IDENTIDAD, …)`; defaults):

| Entidad | Maestro por defecto | Claves de match en orden |
|---|---|---|
| producto | fuente con rol `inventario` de mayor prioridad | `normalize_sku` → `codigo_barras` → clave declarada en el mapping (`claves_identidad`) → match manual |
| cliente | fuente con rol `facturacion` o `ventas` de mayor prioridad | `identificador_fiscal` / `documento_hash` → `email_hash` → `telefono_hash` (E.164) · clientes anónimos no se unifican |
| proveedor | fuente con rol `contabilidad`/`compras` | `identificador_fiscal` |
| depósito, vendedor, sucursal | manual en onboarding | |

Sin match → la entidad queda propia de su fuente y se registra en `ops.valores_sin_mapear` (dominio `identidad_<entidad>`).

## 7. Reglas de negocio transversales

1. **Costo por línea (CMV)** — prioridad: (a) costo del movimiento de stock de salida; (b) costo informado en la línea de venta; (c) `fct_stock_diario.costo_unitario` del día; (d) `dim_producto.costo_estandar`; (e) null → DQ-07.
2. **Fecha que manda:** ventas comerciales → `fecha_pedido` (o `fecha_confirmacion` si el tenant lo elige); fiscales → `fecha_emision`; contables → `fecha_contable`; logística → timestamps del envío.
3. **`pedido_valido`** (único): `es_fuente_verdad and estado not in ('borrador','cancelado') and coalesce(estado_pago,'aprobado') not in ('rechazado','pendiente')`. Reembolsados siguen válidos; el reembolso se descuenta vía `fct_devolucion`.
4. **Moneda** base por defecto; `moneda='<ISO>'` convierte con la serie del tenant a la fecha del hecho.
5. **Términos reales:** `real_amount` con la serie de índice del tenant.

## 8. Marts (`marts.*`)

| Mart | Grano | Contenido | KPIs |
|---|---|---|---|
| `fct_saldo_tesoreria_diario` | fecha × cuenta | saldo al cierre, `es_desactualizado` | FIN-07/09/16 |
| `fct_saldo_cxc_diario` / `fct_saldo_cxp_diario` | fecha × documento | saldo, `dias_vencido`, `tramo_aging` | FIN-10…16 |
| `fct_stock_diario_kpi` | fecha × producto × depósito | stock filtrado (depósitos incluidos, gestiona_stock, sin servicios), negativos → 0 con flag | INV-* |
| `fct_stock_sku_dia` | fecha × producto | suma de depósitos vendibles | INV-05/06/07 |
| `inv__demanda_sku` | producto | `vdp` (venta diaria sobre días con stock, ventana 90), `precio_neto_prom`, `cv_demanda_semanal` | INV-05/06/07/10/12/15 |
| `inv__abc` | mes × producto | ABC/XYZ → `dim_producto.clasificacion_abc` | INV-12 |
| `ven__cohortes_recompra` | cohorte × días | % recompra 30/60/90/180 | VEN-12 |
| `ven__ltv_cohorte` | cohorte × mes | venta y margen acumulados (nominal y real) | VEN-14, MKT-09 |
| `ven__proyeccion_mes` | fecha × canal × sucursal | proyección de cierre | VEN-24, FIN-20 |
| `fin__eerr_mensual` | mes × eerr_linea × cuenta estándar × sucursal × centro de costo | EERR con `modo` ('contable'/'gestion') | FIN-01…06/19/20/22 |
| `fin__proyeccion_caja` | fecha × componente | FIN-16 | FIN-16 |
| `ven__venta_diaria_sku_punto` | fecha × producto × sucursal/depósito | unidades, importe, tickets del punto de venta ese día, precio medio, flag promoción | ACT-01/02/03/05 |
| `act__quiebre_oculto`, `act__pedido_sugerido`, `act__rotacion`, `act__remarcacion`, `act__promociones`, `act__vencimientos` | según actividad | candidatos con evidencia y caso asignado (docs/14) | actividades |

Funciones: `ref.dias_habiles(tenant, desde, hasta)`, `ref.horas_habiles(tenant, desde_ts, hasta_ts)` (usa `ops.tenant.horario_operativo`).
