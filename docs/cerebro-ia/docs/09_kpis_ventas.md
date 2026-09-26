# 09 — KPIs de Ventas

> Generado por `tools/build_kpis.py` desde `kpis/src/ventas.yml`. No editar a mano.
> Los KPIs se calculan **solo** sobre el modelo canónico (docs/04). Cada ficha declara qué columnas canónicas necesita; qué sistema las aporta lo define el `mapping.yml` de cada fuente (docs/05).

Cubre volumen, crecimiento, rentabilidad comercial, clientes, devoluciones y pipeline B2B.
**Base de venta:** por defecto los KPIs de ventas son **comerciales** (`fct_pedido`, fecha de pedido, filtro `pedido_valido`, docs/02 §7.3).
El parámetro `base='facturada'` cambia a `fct_comprobante` circuito venta (equivale a FIN-01 modo gestión).
Montos sin impuesto indirecto y sin envío cobrado, moneda base, con opción `ajuste='real'`.
**Filtro `pedido_valido`** = `es_fuente_verdad and estado not in ('borrador','cancelado') and coalesce(estado_pago,'aprobado') not in ('rechazado','pendiente')`.

## Índice

| ID | KPI | Unidad | Dirección | Roles mínimos |
|---|---|---|---|---|
| [VEN-01](#ven-01) | Venta neta | moneda | mayor_mejor | ventas |
| [VEN-02](#ven-02) | Cantidad de pedidos | cantidad | mayor_mejor | ventas |
| [VEN-03](#ven-03) | Ticket promedio | moneda | mayor_mejor | ventas |
| [VEN-04](#ven-04) | Unidades vendidas y unidades por pedido | unidades | mayor_mejor | ventas |
| [VEN-05](#ven-05) | Mix y participación por canal | porcentaje | neutral | ventas |
| [VEN-06](#ven-06) | Crecimiento de ventas (nominal y real) | porcentaje | mayor_mejor | ventas |
| [VEN-07](#ven-07) | Cumplimiento de presupuesto / cuota | porcentaje | mayor_mejor | presupuesto, ventas |
| [VEN-08](#ven-08) | Margen bruto comercial por producto/categoría | moneda \| porcentaje | mayor_mejor | ventas |
| [VEN-09](#ven-09) | Margen de contribución por canal | moneda \| porcentaje | mayor_mejor | ventas |
| [VEN-10](#ven-10) | Clientes activos | cantidad | mayor_mejor | ventas |
| [VEN-11](#ven-11) | Clientes nuevos y participación de nuevos en la venta | cantidad \| porcentaje | mayor_mejor | ventas |
| [VEN-12](#ven-12) | Tasa de recompra | porcentaje | mayor_mejor | ventas |
| [VEN-13](#ven-13) | Frecuencia de compra | ratio \| dias | mayor_mejor (frecuencia) | ventas |
| [VEN-14](#ven-14) | LTV (valor de vida del cliente) | moneda | mayor_mejor | ventas |
| [VEN-15](#ven-15) | Churn de clientes (B2B / recurrentes) | porcentaje \| cantidad | menor_mejor | ventas |
| [VEN-16](#ven-16) | Tasa de devolución | porcentaje | menor_mejor | ventas |
| [VEN-17](#ven-17) | Tasa de cancelación | porcentaje | menor_mejor | ventas |
| [VEN-18](#ven-18) | Descuento promedio | porcentaje | menor_mejor | ventas |
| [VEN-19](#ven-19) | Pipeline abierto y ponderado | moneda | mayor_mejor | crm |
| [VEN-20](#ven-20) | Tasa de cierre (win rate) | porcentaje | mayor_mejor | crm |
| [VEN-21](#ven-21) | Ciclo de venta | dias | menor_mejor | crm |
| [VEN-22](#ven-22) | Velocidad de pipeline | moneda por día | mayor_mejor | crm |
| [VEN-23](#ven-23) | Concentración de ventas (Pareto clientes/productos) | porcentaje | menor_mejor | ventas |
| [VEN-24](#ven-24) | Proyección de cierre de mes | moneda | mayor_mejor | ventas |
| [VEN-25](#ven-25) | Productividad por vendedor | varias | mayor_mejor | ventas |
| [VEN-26](#ven-26) | Rendimiento de promociones (ROI) | ratio \| moneda \| porcentaje | mayor_mejor | promociones, ventas |
| [VEN-27](#ven-27) | Productos con margen bajo el mínimo | cantidad \| porcentaje | menor_mejor | precios_venta, precios_compra o ventas |

---

## VEN-01
### Venta neta

**Pregunta que responde:** ¿Cuánto vendimos?  
**Definición:** Suma de importe neto (sin impuesto indirecto, sin envío, después de descuentos) de pedidos válidos, menos devoluciones del período.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.venta_neta` |
| Unidad | moneda |
| Dirección | mayor_mejor |
| Agregación | aditivo |
| Grano mínimo | dia |
| Dimensiones | canal, sucursal, vendedor, cliente, tipo_cliente, region, producto, categoria, marca, canal_marketing, medio_pago |
| Filtros base | pedido_valido |
| Parámetros | `base`=comercial\|facturada, `neto_devoluciones`=True, `ajuste`=nominal\|real, `moneda`=base\|<ISO> |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | FIN-01, VEN-06, VEN-24 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(p.importe_neto) - coalesce((select sum(d.importe_neto) from core.fct_devolucion d
        where d.estado in ('recibida','reintegrada') and d.fecha_recepcion between :desde and :hasta),0) as venta_neta
from core.fct_pedido p where pedido_valido and p.fecha_pedido between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.estado` | obligatoria |
| `fct_pedido.es_fuente_verdad` | obligatoria |
| `fct_pedido.importe_neto` | obligatoria |
| `fct_pedido.estado_pago` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.canal_id` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido_linea.producto_id` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido_linea.importe_neto` | opcional (habilita desgloses o mayor precisión) |
| `fct_devolucion.fecha_recepcion` | opcional (habilita desgloses o mayor precisión) |
| `fct_devolucion.importe_neto` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Con dimensión producto/categoría se suma fct_pedido_linea.importe_neto (el descuento de cabecera ya viene prorrateado en líneas).
- Pedidos de marketplace en pack cuentan como un pedido.
- Pedidos en moneda extranjera → TC del día del pedido.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| venta diaria < 60% del promedio del mismo día de semana de las últimas 4 semanas | alta |
| venta del mes proyectada (VEN-24) < 90% presupuesto | alta |

---

## VEN-02
### Cantidad de pedidos

**Pregunta que responde:** ¿Cuántas ventas/pedidos hicimos?  
**Definición:** Conteo de pedidos válidos distintos.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.pedidos` |
| Unidad | cantidad |
| Dirección | mayor_mejor |
| Agregación | aditivo (distinct por grano) |
| Grano mínimo | dia |
| Dimensiones | canal, sucursal, vendedor, region, canal_marketing, medio_pago |
| Filtros base | pedido_valido |
| Parámetros | — |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | VEN-03 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(distinct pedido_id) from core.fct_pedido where pedido_valido and fecha_pedido between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.estado` | obligatoria |
| `fct_pedido.es_fuente_verdad` | obligatoria |
| `fct_pedido.estado_pago` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.canal_id` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Con dimensión producto se cuentan pedidos que contienen el producto (no aditivo entre productos).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| pedidos del día = 0 en canal con histórico > 5/día | critica |

---

## VEN-03
### Ticket promedio

**Pregunta que responde:** ¿Cuánto gasta en promedio cada pedido?  
**Definición:** Venta neta de pedidos válidos / cantidad de pedidos válidos (sin descontar devoluciones).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.ticket_promedio` |
| Unidad | moneda |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | canal, sucursal, vendedor, tipo_cliente, canal_marketing, es_primera_compra |
| Filtros base | pedido_valido |
| Parámetros | `ajuste`=nominal\|real |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | VEN-01, VEN-04 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(importe_neto)/nullif(count(distinct pedido_id),0) from core.fct_pedido where pedido_valido and fecha_pedido between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.estado` | obligatoria |
| `fct_pedido.es_fuente_verdad` | obligatoria |
| `fct_pedido.importe_neto` | obligatoria |
| `fct_pedido.es_primera_compra` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Comparaciones interanuales siempre en términos reales por inflación.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| ticket real cae > 10% vs promedio 3 meses | media |

---

## VEN-04
### Unidades vendidas y unidades por pedido

**Pregunta que responde:** ¿Cuántas unidades vendimos y cuántas lleva cada pedido?  
**Definición:** Suma de cantidad de líneas de pedidos válidos; UPT = unidades / pedidos.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.unidades, ventas.unidades_por_pedido` |
| Unidad | unidades |
| Dirección | mayor_mejor |
| Agregación | aditivo / ratio |
| Grano mínimo | dia |
| Dimensiones | producto, categoria, marca, canal, sucursal |
| Filtros base | pedido_valido, excluye es_servicio |
| Parámetros | — |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | INV-05 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(l.cantidad) unidades, sum(l.cantidad)/nullif(count(distinct l.pedido_id),0) upt
from core.fct_pedido_linea l join core.fct_pedido p using (pedido_id)
where pedido_valido and p.fecha_pedido between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.estado` | obligatoria |
| `fct_pedido.es_fuente_verdad` | obligatoria |

**Casos borde y reglas:**

- Productos vendidos por kg/metro no se suman con unidades; agrupar por unidad_medida.

---

## VEN-05
### Mix y participación por canal

**Pregunta que responde:** ¿Qué porcentaje de la venta viene de cada canal?  
**Definición:** Venta neta del canal / venta neta total.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.venta_neta (share calculado en MCP con `comparar='share'`)` |
| Unidad | porcentaje |
| Dirección | neutral |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | canal, sucursal, categoria, canal_marketing |
| Filtros base | pedido_valido |
| Parámetros | `dimension_share`=canal |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | VEN-09 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select canal_id, sum(importe_neto) / sum(sum(importe_neto)) over () from core.fct_pedido where pedido_valido and fecha_pedido between :desde and :hasta group by 1;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.importe_neto` | obligatoria |
| `fct_pedido.canal_id` | obligatoria |

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| un canal concentra > 70% de la venta (riesgo de dependencia) | media |

---

## VEN-06
### Crecimiento de ventas (nominal y real)

**Pregunta que responde:** ¿Crecemos? ¿Y por encima de la inflación?  
**Definición:** Variación % de venta neta vs período de comparación, nominal y ajustada por índice de precios.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.venta_neta con comparación (time dimension compareDateRange)` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | calculado |
| Grano mínimo | dia |
| Dimensiones | canal, sucursal, categoria, vendedor |
| Filtros base | pedido_valido |
| Parámetros | `comparacion`=mes_anterior\|anio_anterior\|mtd, `ajuste`=real por defecto |
| Roles de fuente mínimos | ventas |
| Historia mínima | ≥ 13 meses de historia para interanual |
| Relacionados | VEN-01, FIN-22 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
var_nominal = venta(periodo) / nullif(venta(comp), 0) - 1
var_real = real_amount(venta(periodo)) / nullif(real_amount(venta(comp)), 0) - 1
-- comp: mes_anterior | mismo_periodo_anio_anterior | mismo_periodo_a_la_fecha (MTD vs MTD con igual cantidad de días hábiles)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.importe_neto` | obligatoria |
| `ref.indice_precios.indice` | opcional (habilita desgloses o mayor precisión) |
| `ref.feriado.fecha` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Comparación MTD debe igualar días hábiles transcurridos (ref.fecha.es_habil), no días calendario.
- En contextos inflacionarios el agente debe reportar SIEMPRE la variación real junto a la nominal.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| var_real interanual < -5% | alta |

---

## VEN-07
### Cumplimiento de presupuesto / cuota

**Pregunta que responde:** ¿Qué porcentaje del objetivo llevamos?  
**Definición:** Venta neta real / presupuesto (o cuota) del período; también % esperado a la fecha según días hábiles transcurridos.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `presupuesto.cumplimiento_ventas` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | mes |
| Dimensiones | canal, sucursal, vendedor, categoria |
| Filtros base | presupuesto concepto in (venta_neta, cuota_vendedor) |
| Parámetros | `version`=original |
| Roles de fuente mínimos | presupuesto, ventas |
| Historia mínima | — |
| Relacionados | FIN-19, VEN-24 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
cumplimiento = venta_neta / nullif(ppto, 0)
esperado_a_la_fecha = dias_habiles_transcurridos / dias_habiles_mes
ritmo = cumplimiento / nullif(esperado_a_la_fecha, 0)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.importe_neto` | obligatoria |
| `fct_presupuesto.importe` | obligatoria |
| `fct_pedido.vendedor_id` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.canal_id` | opcional (habilita desgloses o mayor precisión) |
| `ref.feriado.fecha` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Presupuesto anual sin apertura mensual → se distribuye por estacionalidad del año anterior (marcar).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| ritmo < 0.9 después del día hábil 10 | alta |

---

## VEN-08
### Margen bruto comercial por producto/categoría

**Pregunta que responde:** ¿Qué productos y categorías nos dejan más margen?  
**Definición:** Venta neta de líneas − costo de líneas; margen % = margen / venta.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.margen_bruto, ventas.margen_bruto_pct` |
| Unidad | moneda \| porcentaje |
| Dirección | mayor_mejor |
| Agregación | aditivo / ratio |
| Grano mínimo | dia |
| Dimensiones | producto, categoria, marca, canal, sucursal, vendedor, cliente |
| Filtros base | pedido_valido, costo_total not null |
| Parámetros | `costo`=historico\|reposicion |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | FIN-03, VEN-09, INV-11 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select pr.categoria_n1, sum(l.importe_neto) venta, sum(l.costo_total) costo,
       sum(l.importe_neto - l.costo_total) margen, sum(l.importe_neto - l.costo_total)/nullif(sum(l.importe_neto),0) margen_pct
from core.fct_pedido_linea l join core.fct_pedido p using (pedido_id) join core.dim_producto pr using (producto_id)
where pedido_valido and p.fecha_pedido between :desde and :hasta group by 1;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido_linea.importe_neto` | obligatoria |
| `fct_pedido_linea.costo_unitario` | obligatoria |
| `fct_pedido_linea.costo_total` | obligatoria |
| `dim_producto.categoria_n1` | opcional (habilita desgloses o mayor precisión) |
| `dim_producto.categoria_n2` | opcional (habilita desgloses o mayor precisión) |
| `dim_producto.categoria_n3` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Informa `pct_venta_sin_costo`; si > 5 % el agente lo aclara.
- costo='reposicion' usa dim_producto.costo_estandar actual (mejor para decisiones de precio en inflación).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| producto con margen_pct < 0 y ventas > 0 | alta |
| categoría baja > 5 pp de margen vs mes anterior | media |

---

## VEN-09
### Margen de contribución por canal

**Pregunta que responde:** ¿Qué canal es realmente rentable después de comisiones, envío y financiación?  
**Definición:** Venta neta − CMV − comisión del canal − costo de financiación − costo de envío a cargo del vendedor (+ envío cobrado) − comisión de pasarela − inversión publicitaria asignada al canal (opcional).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.contribucion, ventas.contribucion_pct` |
| Unidad | moneda \| porcentaje |
| Dirección | mayor_mejor |
| Agregación | aditivo / ratio |
| Grano mínimo | dia |
| Dimensiones | canal, categoria, producto, modalidad |
| Filtros base | pedido_valido |
| Parámetros | `incluir_ads`=False |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | VEN-05, FIN-17, LOG-12 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select p.canal_id,
  sum(p.importe_neto) venta,
  sum(p.importe_neto - p.costo_mercaderia - coalesce(p.comision_canal,0) - coalesce(p.costo_financiacion,0)
      - coalesce(p.costo_envio_vendedor,0) + coalesce(p.importe_envio_cobrado,0) - coalesce(lp.comision,0)) contribucion
from core.fct_pedido p left join (select pedido_id, sum(comision) comision from core.fct_liquidacion_pasarela group by 1) lp using (pedido_id)
where pedido_valido and p.fecha_pedido between :desde and :hasta group by 1;
-- opcional incluir_ads: restar Σ fct_ads_diario.gasto asignado (asignación plataforma → canal de venta configurada por el tenant)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.importe_neto` | obligatoria |
| `fct_pedido.canal_id` | obligatoria |
| `fct_pedido_linea.costo_total` | obligatoria |
| `fct_pedido.comision_canal` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.costo_financiacion` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.costo_envio_vendedor` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.importe_envio_cobrado` | opcional (habilita desgloses o mayor precisión) |
| `fct_liquidacion_pasarela.comision` | opcional (habilita desgloses o mayor precisión) |
| `fct_ads_diario.gasto` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Si el canal informa comisiones con impuesto incluido, el mapping las guarda netas con sin_impuesto().
- Envíos bonificados por el canal → costo_envio_vendedor puede ser 0 o negativo.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| contribucion_pct de un canal < 10% | alta |
| producto con contribución negativa en marketplace | alta |

---

## VEN-10
### Clientes activos

**Pregunta que responde:** ¿Cuántos clientes distintos nos compraron?  
**Definición:** Clientes distintos con ≥1 pedido válido en el período (o en ventana móvil de 12 meses para "base activa").

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `clientes.activos` |
| Unidad | cantidad |
| Dirección | mayor_mejor |
| Agregación | no_aditivo (distinct) |
| Grano mínimo | dia |
| Dimensiones | canal, tipo_cliente, region, vendedor |
| Filtros base | pedido_valido, cliente identificado |
| Parámetros | `ventana`=periodo\|12m_movil |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | VEN-11, VEN-12 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(distinct cliente_id) from core.fct_pedido where pedido_valido and cliente_id <> '-1' and fecha_pedido between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.cliente_id` | obligatoria |
| `dim_cliente.tipo_cliente` | opcional (habilita desgloses o mayor precisión) |
| `dim_cliente.region` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Consumidores finales sin identificación (mostrador) no cuentan; se informa % de venta anónima.
- Un mismo comprador en dos canales se unifica solo si coincide documento, email o teléfono (docs/04 §6).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| base activa 12m cae > 5% vs trimestre anterior | media |

---

## VEN-11
### Clientes nuevos y participación de nuevos en la venta

**Pregunta que responde:** ¿Cuántos clientes nuevos ganamos y cuánto aportan?  
**Definición:** Clientes cuya primera compra válida cae en el período; % venta de nuevos = venta de pedidos es_primera_compra / venta total.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `clientes.nuevos, ventas.pct_venta_nuevos` |
| Unidad | cantidad \| porcentaje |
| Dirección | mayor_mejor |
| Agregación | aditivo (nuevos) / ratio |
| Grano mínimo | dia |
| Dimensiones | canal, canal_marketing, region, tipo_cliente |
| Filtros base | pedido_valido |
| Parámetros | — |
| Roles de fuente mínimos | ventas |
| Historia mínima | ≥ 12 meses (antes |
| Relacionados | MKT-08 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(distinct cliente_id) filter (where es_primera_compra) nuevos,
       sum(importe_neto) filter (where es_primera_compra) / nullif(sum(importe_neto),0) pct_venta_nuevos
from core.fct_pedido where pedido_valido and fecha_pedido between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.cliente_id` | obligatoria |
| `fct_pedido.importe_neto` | obligatoria |
| `fct_pedido.canal_id` | opcional (habilita desgloses o mayor precisión) |
| `fct_atribucion_pedido.canal_marketing` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- La historia cargada define "nuevo": si el tenant trae solo 6 meses, un cliente viejo parece nuevo.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| nuevos cae > 20% vs mes anterior | media |

---

## VEN-12
### Tasa de recompra

**Pregunta que responde:** ¿Qué porcentaje de clientes vuelve a comprar?  
**Definición:** Clientes con ≥2 pedidos en ventana / clientes con ≥1 pedido en ventana (12 meses móviles por defecto); y cohortes de recompra a 30/60/90/180 días.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `clientes.tasa_recompra, cohortes.recompra_n_dias` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | canal (de primera compra), canal_marketing adquisición, categoria primera compra |
| Filtros base | pedido_valido, cliente identificado |
| Parámetros | `ventana_meses`=12, `dias_cohorte`=30\|60\|90\|180 |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | VEN-13, VEN-14, VEN-15 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
with c as (select cliente_id, count(distinct pedido_id) n from core.fct_pedido
           where pedido_valido and fecha_pedido > :hasta - interval '12 months' and fecha_pedido <= :hasta group by 1)
select count(*) filter (where n >= 2)::numeric / nullif(count(*),0) from c;
-- cohortes: marts.ven__cohortes_recompra (cohorte = mes de primera compra, % que recompra en N días)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.cliente_id` | obligatoria |

**Casos borde y reglas:**

- En marketplace el buyer id cambia poco pero no hay email; la recompra cross-canal puede subestimarse.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| tasa_recompra 12m cae > 3 pp vs trimestre anterior | media |

---

## VEN-13
### Frecuencia de compra

**Pregunta que responde:** ¿Cada cuántos días nos compra un cliente?  
**Definición:** Pedidos / clientes activos en ventana; y mediana de días entre pedidos consecutivos del mismo cliente.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `clientes.frecuencia, clientes.dias_entre_compras` |
| Unidad | ratio \| dias |
| Dirección | mayor_mejor (frecuencia) |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | tipo_cliente, canal, vendedor |
| Filtros base | pedido_valido |
| Parámetros | `ventana_meses`=12 |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | VEN-12, VEN-15 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
frecuencia = count(distinct pedido_id) / count(distinct cliente_id)   -- ventana 12m
dias_entre_compras = percentile_cont(0.5) within group (order by fecha_pedido - lag(fecha_pedido) over (partition by cliente_id order by fecha_pedido))
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.cliente_id` | obligatoria |

**Casos borde y reglas:**

- 

---

## VEN-14
### LTV (valor de vida del cliente)

**Pregunta que responde:** ¿Cuánto margen nos deja un cliente a lo largo del tiempo?  
**Definición:** Margen bruto acumulado promedio por cliente de una cohorte a 12 meses de su primera compra (LTV histórico); opcional LTV predictivo = ticket × frecuencia × margen% × vida esperada.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `clientes.ltv_12m` |
| Unidad | moneda |
| Dirección | mayor_mejor |
| Agregación | calculado por cohorte |
| Grano mínimo | mes |
| Dimensiones | cohorte, canal_adquisicion, canal_marketing, tipo_cliente |
| Filtros base | cohortes con ≥ 12 meses de antigüedad |
| Parámetros | `horizonte_meses`=6\|12\|24, `ajuste`=real por defecto, `base`=margen\|venta |
| Roles de fuente mínimos | ventas |
| Historia mínima | ≥ 12 meses de historia con clientes identificados |
| Relacionados | MKT-09 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
-- histórico por cohorte (marts.ven__ltv_cohorte)
select date_trunc('month', c.fecha_primera_compra) cohorte,
       sum(l.importe_neto - l.costo_total) / count(distinct c.cliente_id) ltv_12m
from core.dim_cliente c join core.fct_pedido p using (cliente_id) join core.fct_pedido_linea l using (pedido_id)
where pedido_valido and p.fecha_pedido < c.fecha_primera_compra + interval '12 months' group by 1;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.cliente_id` | obligatoria |
| `fct_pedido_linea.importe_neto` | obligatoria |
| `fct_pedido_linea.costo_total` | obligatoria |

**Casos borde y reglas:**

- Siempre en términos reales: sumar importes de distintos meses sin ajustar distorsiona.

---

## VEN-15
### Churn de clientes (B2B / recurrentes)

**Pregunta que responde:** ¿Cuántos clientes dejaron de comprarnos?  
**Definición:** Clientes activos al inicio del período que no compraron en los últimos N días (N = umbral tenant, default 2× su frecuencia típica o 90 días) / clientes activos al inicio.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `clientes.churn, clientes.en_riesgo` |
| Unidad | porcentaje \| cantidad |
| Dirección | menor_mejor |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | vendedor, tipo_cliente, region |
| Filtros base | tipo_cliente = 'empresa' por defecto |
| Parámetros | `dias_inactividad`=90 |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | VEN-12, VEN-23 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
en_riesgo = clientes con dias_desde_ultima_compra > 1.5 × su dias_entre_compras mediano
churn = clientes activos(inicio) sin compra en ventana N / clientes activos(inicio)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.cliente_id` | obligatoria |
| `dim_cliente.tipo_cliente` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.vendedor_id` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- En B2C de baja frecuencia (compra anual) churn no es significativo; el agente usa VEN-12.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| cliente top 20 (por venta 12m) en riesgo | alta |

---

## VEN-16
### Tasa de devolución

**Pregunta que responde:** ¿Qué porcentaje de lo vendido nos devuelven y por qué?  
**Definición:** Unidades (o importe) devueltas / unidades (o importe) vendidas, emparejando por fecha de pedido original (cohorte) o por fecha de devolución (flujo).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `devoluciones.tasa_unidades, devoluciones.tasa_importe` |
| Unidad | porcentaje |
| Dirección | menor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | producto, categoria, marca, canal, motivo, transportista |
| Filtros base | pedido_valido |
| Parámetros | `base`=cohorte\|flujo, `medida`=unidades\|importe |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | LOG-15, LOG-18 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
-- por cohorte de pedido (recomendado)
select sum(l.cantidad_devuelta) / nullif(sum(l.cantidad),0)
from core.fct_pedido_linea l join core.fct_pedido p using (pedido_id)
where pedido_valido and p.fecha_pedido between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_devolucion.fecha_recepcion` | obligatoria |
| `fct_devolucion.cantidad` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_devolucion.importe_neto` | opcional (habilita desgloses o mayor precisión) |
| `fct_devolucion.motivo` | opcional (habilita desgloses o mayor precisión) |
| `fct_devolucion.pedido_linea_id` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Períodos recientes (< 30 días) están incompletos en base cohorte; marcar "madurando".

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| producto con tasa > 2× la de su categoría y ≥ 10 unidades vendidas | alta |
| tasa total sube > 2 pp vs promedio 3 meses | media |

---

## VEN-17
### Tasa de cancelación

**Pregunta que responde:** ¿Qué porcentaje de pedidos se cancela?  
**Definición:** Pedidos cancelados (excluye borradores y carritos abandonados) / pedidos creados no borrador.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.tasa_cancelacion` |
| Unidad | porcentaje |
| Dirección | menor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | canal, medio_pago, motivo (si disponible), deposito |
| Filtros base | es_fuente_verdad |
| Parámetros | — |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | INV-06, LOG-14 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) filter (where estado='cancelado')::numeric / nullif(count(*) filter (where estado <> 'borrador'),0)
from core.fct_pedido where es_fuente_verdad and fecha_pedido between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.estado` | obligatoria |
| `fct_pedido.estado_pago` | obligatoria |
| `fct_pedido.canal_id` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.medio_pago` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- marketplace cancela por falta de stock y penaliza reputación → cruzar con INV-06.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| tasa_cancelacion marketplace > 2% | alta |

---

## VEN-18
### Descuento promedio

**Pregunta que responde:** ¿Cuánto estamos descontando sobre precio de lista?  
**Definición:** Importe de descuentos / importe bruto (precio lista).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.descuento_pct` |
| Unidad | porcentaje |
| Dirección | menor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | vendedor, canal, cupon, categoria, cliente |
| Filtros base | pedido_valido |
| Parámetros | — |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | VEN-08 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(importe_descuento)/nullif(sum(importe_bruto),0) from core.fct_pedido where pedido_valido and fecha_pedido between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.importe_bruto` | obligatoria |
| `fct_pedido.importe_descuento` | obligatoria |
| `fct_pedido.vendedor_id` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.canal_id` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Precio promocional publicado (tachado) en e-commerce no siempre queda como descuento; depende de la fuente.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| vendedor con descuento_pct > 1.5× promedio del equipo | media |

---

## VEN-19
### Pipeline abierto y ponderado

**Pregunta que responde:** ¿Cuánto negocio tenemos en juego en el CRM?  
**Definición:** Suma de importe de oportunidades abiertas; ponderado = Σ importe × probabilidad.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `crm.pipeline_abierto, crm.pipeline_ponderado` |
| Unidad | moneda |
| Dirección | mayor_mejor |
| Agregación | snapshot |
| Grano mínimo | dia |
| Dimensiones | etapa, vendedor, pipeline, mes de cierre esperado, origen |
| Filtros base | no cerrada |
| Parámetros | `cierre_esperado_hasta`=None |
| Roles de fuente mínimos | crm |
| Historia mínima | — |
| Relacionados | VEN-20, VEN-21, VEN-22 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(importe) pipeline, sum(importe*probabilidad/100) ponderado, count(*) oportunidades
from core.fct_oportunidad where not esta_cerrada;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_oportunidad.etapa` | obligatoria |
| `fct_oportunidad.importe` | obligatoria |
| `fct_oportunidad.esta_cerrada` | obligatoria |
| `fct_oportunidad.fecha_cierre_esperada` | obligatoria |
| `fct_oportunidad.probabilidad` | opcional (habilita desgloses o mayor precisión) |
| `fct_oportunidad.vendedor_id` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Oportunidades con cierre esperado vencido > 30 días se marcan "estancadas" y se muestran aparte.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| pipeline ponderado del mes siguiente < 1.0× cuota | alta |
| oportunidades estancadas > 20% del pipeline | media |

---

## VEN-20
### Tasa de cierre (win rate)

**Pregunta que responde:** ¿Qué porcentaje de oportunidades ganamos?  
**Definición:** Ganadas / (ganadas + perdidas) cerradas en el período (por cantidad e importe).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `crm.win_rate` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | mes |
| Dimensiones | vendedor, origen, pipeline, motivo_perdida, rango_importe |
| Filtros base | cerrada en período |
| Parámetros | — |
| Roles de fuente mínimos | crm |
| Historia mínima | — |
| Relacionados | VEN-19, MKT-16 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) filter (where esta_ganada)::numeric / nullif(count(*),0) win_rate_cant,
       sum(importe) filter (where esta_ganada) / nullif(sum(importe),0) win_rate_importe
from core.fct_oportunidad where esta_cerrada and fecha_cierre between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_oportunidad.esta_ganada` | obligatoria |
| `fct_oportunidad.esta_cerrada` | obligatoria |
| `fct_oportunidad.fecha_cierre` | obligatoria |
| `fct_oportunidad.importe` | obligatoria |
| `fct_oportunidad.fecha_cierre_esperada` | opcional (habilita desgloses o mayor precisión) |
| `fct_oportunidad.vendedor_id` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| win_rate cae > 10 pp vs trimestre anterior | media |

---

## VEN-21
### Ciclo de venta

**Pregunta que responde:** ¿Cuántos días tarda en cerrarse una venta?  
**Definición:** Mediana de (fecha_cierre − fecha_creacion) de oportunidades ganadas; tiempo en cada etapa desde el historial.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `crm.ciclo_venta_dias` |
| Unidad | dias |
| Dirección | menor_mejor |
| Agregación | mediana |
| Grano mínimo | mes |
| Dimensiones | vendedor, origen, rango_importe, etapa (tiempo por etapa) |
| Filtros base | ganadas |
| Parámetros | — |
| Roles de fuente mínimos | crm |
| Historia mínima | — |
| Relacionados | VEN-22 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select percentile_cont(0.5) within group (order by fecha_cierre - fecha_creacion)
from core.fct_oportunidad where esta_ganada and fecha_cierre between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_oportunidad.fecha_creacion` | obligatoria |
| `fct_oportunidad.fecha_cierre` | obligatoria |
| `fct_oportunidad.esta_ganada` | obligatoria |
| `fct_oportunidad.esta_cerrada` | obligatoria |
| `fct_oportunidad_historial_etapa.etapa` | obligatoria |
| `fct_oportunidad_historial_etapa.entrada_at` | obligatoria |
| `fct_oportunidad.fecha_cierre_esperada` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

---

## VEN-22
### Velocidad de pipeline

**Pregunta que responde:** ¿Cuánto dinero por día genera nuestro pipeline?  
**Definición:** (Oportunidades abiertas × win rate × ticket promedio ganado) / ciclo de venta en días.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `crm.velocidad_pipeline` |
| Unidad | moneda por día |
| Dirección | mayor_mejor |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | vendedor, pipeline |
| Filtros base | — |
| Parámetros | `ventana_meses`=6 |
| Roles de fuente mínimos | crm |
| Historia mínima | ≥ 6 meses |
| Relacionados | VEN-19, VEN-20, VEN-21 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
velocidad = (count_abiertas * VEN-20.win_rate_cant * avg_importe_ganado) / nullif(VEN-21.ciclo_dias, 0)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_oportunidad.importe` | obligatoria |
| `fct_oportunidad.esta_ganada` | obligatoria |
| `fct_oportunidad.esta_cerrada` | obligatoria |
| `fct_oportunidad.fecha_creacion` | obligatoria |
| `fct_oportunidad.fecha_cierre` | obligatoria |
| `fct_oportunidad.fecha_cierre_esperada` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

---

## VEN-23
### Concentración de ventas (Pareto clientes/productos)

**Pregunta que responde:** ¿Dependemos de pocos clientes o productos?  
**Definición:** % de la venta que explica el top 10 / top 20 % de clientes o productos; índice HHI opcional.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.concentracion` |
| Unidad | porcentaje |
| Dirección | menor_mejor |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | entidad (cliente\|producto\|categoria) |
| Filtros base | pedido_valido |
| Parámetros | `entidad`=cliente\|producto, `top_n`=10 |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | VEN-15, INV-12 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
with r as (select cliente_id, sum(importe_neto) v from core.fct_pedido where pedido_valido and fecha_pedido between :desde and :hasta group by 1)
select sum(v) filter (where rk <= 10) / sum(v) top10_pct
from (select *, rank() over (order by v desc) rk from r) x;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.importe_neto` | obligatoria |
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido_linea.importe_neto` | obligatoria |
| `fct_pedido.cliente_id` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| un solo cliente > 20% de la venta 12m | alta |

---

## VEN-24
### Proyección de cierre de mes

**Pregunta que responde:** ¿Cuánto vamos a vender a fin de mes al ritmo actual?  
**Definición:** Venta MTD + venta diaria esperada × días hábiles restantes, con estacionalidad por día de semana de las últimas 8 semanas y ajuste por pipeline/pedidos pendientes en B2B.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.proyeccion_mes (mart marts.ven__proyeccion_mes, recalculado diario)` |
| Unidad | moneda |
| Dirección | mayor_mejor |
| Agregación | calculado |
| Grano mínimo | dia |
| Dimensiones | canal, sucursal |
| Filtros base | pedido_valido |
| Parámetros | — |
| Roles de fuente mínimos | ventas |
| Historia mínima | ≥ 8 semanas de historia |
| Relacionados | VEN-07, FIN-20 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
proyeccion = venta_mtd + Σ_{d en dias restantes} promedio_venta(dia_semana(d), ultimas 8 semanas, excluyendo feriados) × factor_tendencia
factor_tendencia = venta_mtd / venta_esperada_mtd_segun_mismo_modelo (acotado 0.7–1.3)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido.importe_neto` | obligatoria |
| `fct_pedido.canal_id` | opcional (habilita desgloses o mayor precisión) |
| `ref.feriado.fecha` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Eventos especiales (eventos promocionales masivos) se marcan en ref.fecha como evento para no contaminar la base.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| proyeccion < 90% presupuesto | alta |

---

## VEN-25
### Productividad por vendedor

**Pregunta que responde:** ¿Cómo rinde cada vendedor?  
**Definición:** Venta neta, pedidos, ticket, margen %, descuento %, clientes activos y cumplimiento de cuota por vendedor.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `view vendedores_scorecard` |
| Unidad | varias |
| Dirección | mayor_mejor |
| Agregación | vista |
| Grano mínimo | mes |
| Dimensiones | vendedor, equipo, sucursal |
| Filtros base | pedido_valido, vendedor_id <> '-1' |
| Parámetros | — |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | VEN-07 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
vista compuesta de VEN-01, VEN-02, VEN-03, VEN-08, VEN-18, VEN-10, VEN-07 con dimensión vendedor
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.vendedor_id` | obligatoria |
| `fct_pedido.importe_neto` | obligatoria |
| `fct_pedido.importe_descuento` | opcional (habilita desgloses o mayor precisión) |
| `fct_presupuesto.importe` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido_linea.costo_total` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Ventas online sin vendedor quedan en "Sin asignar" y se excluyen del ranking.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| vendedor con ritmo de cuota < 0.7 al día hábil 15 | media |

---

## VEN-26
### Rendimiento de promociones (ROI)

**Pregunta que responde:** ¿Las promociones nos hacen ganar o perder plata?  
**Definición:** Margen incremental neto de las promociones (con canibalización y efecto posterior) sobre su costo (descuento otorgado + comunicación − aporte del proveedor); % de promociones que rindieron.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `promociones.roi, promociones.margen_incremental` |
| Unidad | ratio \| moneda \| porcentaje |
| Dirección | mayor_mejor |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | mecanica, objetivo, categoria, canal, sucursal |
| Filtros base | promociones finalizadas hace ≥ 14 días para incluir efecto posterior |
| Parámetros | `roi_minimo`=0 |
| Roles de fuente mínimos | promociones, ventas |
| Historia mínima | — |
| Relacionados | VEN-08, VEN-18 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(margen_incremental_neto) margen_incremental, sum(margen_incremental_neto) / nullif(sum(costo_promocion),0) roi,
       avg((roi >= :roi_minimo)::int) pct_rindieron
from marts.act__promociones where fecha_fin between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `dim_promocion.fecha_inicio` | obligatoria |
| `dim_promocion.fecha_fin` | obligatoria |
| `fct_promocion_producto.producto_id` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_pedido_linea.importe_neto` | obligatoria |
| `fct_pedido_linea.costo_total` | obligatoria |
| `fct_pedido_linea.promocion_id` | opcional (habilita desgloses o mayor precisión) |
| `dim_promocion.aporte_proveedor_monto` | opcional (habilita desgloses o mayor precisión) |
| `dim_promocion.costo_comunicacion` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Promociones superpuestas sobre el mismo producto se evalúan en conjunto y se informa la superposición.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| margen incremental neto del mes < 0 | alta |

---

## VEN-27
### Productos con margen bajo el mínimo

**Pregunta que responde:** ¿Cuántos productos estamos vendiendo por debajo del margen que definimos (o del costo)?  
**Definición:** Productos activos cuyo margen con costo de reposición vigente está por debajo del margen mínimo de su política de precio; ponderado por venta.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `precios.productos_bajo_margen` |
| Unidad | cantidad \| porcentaje |
| Dirección | menor_mejor |
| Agregación | snapshot |
| Grano mínimo | dia |
| Dimensiones | categoria, proveedor, marca, lista_precios, sucursal |
| Filtros base | sin precio promocional vigente |
| Parámetros | — |
| Roles de fuente mínimos | precios_venta, precios_compra o ventas |
| Historia mínima | — |
| Relacionados | FIN-03, VEN-08 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) filter (where margen_actual < margen_minimo) productos_bajo_minimo,
       count(*) filter (where precio_actual < costo_nuevo) productos_bajo_costo,
       sum(venta_30d) filter (where margen_actual < margen_minimo) / nullif(sum(venta_30d),0) pct_venta_bajo_minimo
from marts.act__remarcacion where fecha = :fecha;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_precio_venta.precio` | obligatoria |
| `fct_precio_venta.vigente_desde` | obligatoria |
| `fct_lista_precio_proveedor.costo_neto` | obligatoria si se usa la variante **costo_lista_proveedor** |
| `dim_producto.costo_estandar` | obligatoria si se usa la variante **costo_estandar** |

Basta con que se cumpla **una** de las variantes: costo_lista_proveedor, costo_estandar (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- Requiere política de precio cargada (ops.politica_precio); sin política se usa el margen promedio de la categoría de los últimos 90 días como referencia.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| productos_bajo_costo > 0 | critica |
| pct_venta_bajo_minimo > 10% | alta |

