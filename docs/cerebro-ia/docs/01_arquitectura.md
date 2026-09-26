# 01 — Arquitectura general (agnóstica de sistemas)

## 1. Principio rector

La plataforma **no conoce ningún sistema de ningún cliente**. No hay código, tablas, seeds ni KPIs que mencionen un producto, proveedor o país en particular.
Todo lo que es específico de un sistema vive en **configuración declarativa** (archivos YAML por fuente) que se crea durante el onboarding de cada cliente.

```
Agregar un sistema nuevo  =  1 archivo source.yml (cómo leerlo)  +  1 archivo mapping.yml (cómo traducirlo)
                          ≠  escribir código nuevo en la plataforma
```

El código de la plataforma solo sabe:
1. **Leer** datos según unos pocos *arquetipos* de conexión (API HTTP, base de datos SQL, archivos, webhooks, agente local).
2. **Guardar** lo leído tal cual, en crudo.
3. **Traducir** lo crudo al **modelo canónico** ejecutando el mapeo declarado.
4. **Calcular** KPIs solo sobre el modelo canónico.
5. **Exponer** los KPIs a la IA.

## 2. Las capas

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ SISTEMAS DEL CLIENTE (cualquiera: gestión, facturación, tienda online, marketplace,        │
│ CRM, bancos, pasarelas de pago, transportistas, publicidad, analítica web, email, planillas)│
└───────────────┬──────────────────────────────────────────────────────────────────────────┘
                │  source.yml (arquetipo + auth + streams)
┌───────────────▼───────────────┐
│ CAPA 1 — INGESTA               │  Motor de conectores genérico por arquetipo. Sin lógica de negocio.
│ docs/02                        │  Salida: registros crudos + estado incremental.
└───────────────┬───────────────┘
┌───────────────▼───────────────┐
│ CAPA 2 — ALMACÉN               │  raw (crudo, append-only) · ref · ops · aislamiento por cliente.
│ docs/03                        │
└───────────────┬───────────────┘
                │  mapping.yml (DSL declarativo → compilado a SQL)
┌───────────────▼───────────────┐
│ CAPA 3 — ESTANDARIZACIÓN       │  3a. Mapeo declarativo (docs/05): raw → canónico.
│ docs/04 + docs/05              │  3b. Modelo canónico (docs/04): el contrato único. Marts.
└───────────────┬───────────────┘
┌───────────────▼───────────────┐
│ CAPA 4 — SEMÁNTICA + IA        │  KPIs definidos una vez sobre el canónico · servidor de herramientas
│ docs/06 + docs/08-15           │  para el agente · reportes · alertas · ACTIVIDADES (docs/14)
│                                │  · PROCESOS, OBJETIVOS y TABLERO en tiempo real (docs/15).
└───────────────────────────────┘
```

**Regla de oro:** la IA nunca calcula a partir de datos crudos. Todo número sale de una consulta a la capa semántica.

## 3. Roles de fuente (la forma agnóstica de decir "qué es cada sistema")

La plataforma no pregunta "¿qué sistema usás?" sino "¿qué **rol** cumple esta fuente?". Una fuente puede cumplir varios roles; un rol puede tener varias fuentes.

| Rol | Qué aporta | Entidades canónicas que alimenta |
|---|---|---|
| `ventas` | Pedidos/ventas con líneas | `fct_pedido`, `fct_pedido_linea`, `dim_cliente`, `dim_producto` |
| `facturacion` | Documentos fiscales de venta y compra | `fct_comprobante`, `fct_comprobante_linea` |
| `registro_fiscal_oficial` | Réplica oficial de documentos fiscales (si el país tiene autoridad de facturación electrónica) | `stg` de control para conciliación (FIN-18) |
| `contabilidad` | Libro diario / plan de cuentas | `fct_asiento_linea`, `dim_cuenta_contable` |
| `cuentas_corrientes` | Saldos y aplicaciones de clientes/proveedores | `fct_documento_cxc/cxp`, `fct_cobro`, `fct_pago`, aplicaciones |
| `tesoreria` | Movimientos y saldos de cuentas de dinero | `fct_movimiento_tesoreria`, `dim_cuenta_tesoreria` |
| `pasarela_pagos` | Cobros electrónicos, comisiones, acreditaciones | `fct_liquidacion_pasarela` |
| `inventario` | Stock, movimientos, depósitos | `fct_stock_diario`, `fct_movimiento_stock`, `dim_deposito` |
| `compras` | Órdenes de compra y recepciones | `fct_orden_compra(_linea)`, `fct_recepcion` |
| `logistica` | Envíos, tracking, preparación | `fct_envio`, `fct_evento_envio`, `fct_preparacion` |
| `crm` | Oportunidades y leads | `fct_oportunidad`, `fct_lead` |
| `publicidad` | Gasto y rendimiento de anuncios | `fct_ads_diario`, `dim_campana` |
| `analitica_web` | Sesiones y embudo | `fct_web_diario` |
| `email_marketing` | Envíos y rendimiento de email | `fct_email_campana`, `fct_suscriptores_diario` |
| `presupuesto` | Objetivos, presupuestos y cuotas | `fct_presupuesto` |
| `precios_compra` | Listas de precios de proveedores (cada formato de lista es una fuente) | `fct_lista_precio_proveedor` |
| `precios_venta` | Listas y cambios de precios de venta propios | `fct_precio_venta` |
| `promociones` | Promociones, mecánicas y productos incluidos | `dim_promocion`, `fct_promocion_producto` |
| `lotes_vencimientos` | Stock por lote y fechas de vencimiento | `fct_stock_lote` (o `fct_recepcion.fecha_vencimiento`) |
| `referencia_tipo_cambio` | Cotizaciones de monedas | `ref.tipo_cambio` |
| `referencia_indice_precios` | Índice de inflación | `ref.indice_precios` |
| `referencia_calendario` | Feriados | `ref.feriado` |

Además, **un solo rol es "fuente de verdad"** por dominio cuando hay superposición (ej. dos fuentes con pedidos): se declara en `ops.tenant_fuente.es_fuente_verdad` por entidad (docs/05 §6).

## 4. Stack de la plataforma (herramientas propias, no sistemas del cliente)

| Función | Herramienta | Reemplazable por |
|---|---|---|
| Motor de conectores | Python 3.12 (framework propio, docs/02) + opcionalmente un catálogo de conectores de terceros open source para arquetipos ya resueltos | — |
| Orquestación | Dagster | cualquier orquestador con assets por partición |
| Almacén | PostgreSQL 16 | cualquier motor SQL soportado por dbt |
| Transformación | dbt-core (+ dbt-utils, dbt-expectations, elementary) | — |
| Compilador de mapeos | Python (propio, docs/05 §8) → genera modelos dbt | — |
| Capa semántica | Cube | cualquier capa semántica con API y multi-tenant |
| Agente IA | Servidor MCP (FastMCP, Python) + modelo de lenguaje | — |
| Secretos | Gestor de secretos | — |
| Local | docker-compose, `make up` | — |

## 5. Convenciones globales

- Modelo canónico en **español, snake_case, sin tildes**.
- Toda tabla canónica: `tenant_id`, `source_id` (fuente configurada), `source_key` (id del registro en origen), `_cargado_at`, `_actualizado_at`.
- ID canónico: `md5(tenant_id‖'|'‖source_id‖'|'‖source_key)` salvo resolución de identidad (docs/04 §6).
- Montos: moneda base del tenant (+ `_orig`, `moneda_orig`, `tc_aplicado`); **sin impuestos indirectos** salvo que la columna diga lo contrario.
- Fechas: `timestamptz` en UTC; fechas de negocio `date` en la zona horaria del tenant.
- Valores categóricos: siempre valores del **catálogo canónico** (`seeds/ref_valores_canonicos.csv`); la traducción desde valores de origen está en el `mapping.yml`, nunca en SQL a mano.
- Todo monetario admite `ajuste='real'` con `ref.indice_precios` y `moneda='<ISO>'` con `ref.tipo_cambio`.
- Aislamiento multi-cliente en tres barreras (almacén, capa semántica, servidor IA). Un bug de aislamiento es crítico.
