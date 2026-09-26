# 10 — KPIs de Inventario

> Generado por `tools/build_kpis.py` desde `kpis/src/inventario.yml`. No editar a mano.
> Los KPIs se calculan **solo** sobre el modelo canónico (docs/04). Cada ficha declara qué columnas canónicas necesita; qué sistema las aporta lo define el `mapping.yml` de cada fuente (docs/05).

Cubre valor y salud del stock, rotación, cobertura, quiebres, inmovilizado, exactitud, reposición y proveedores.
**Base:** `fct_stock_diario` (foto) + `fct_movimiento_stock` (flujo) + ventas de `fct_pedido_linea` (demanda).
**Venta diaria promedio (VDP)** = unidades vendidas en pedidos válidos en los últimos N días (default 90) / **días con stock disponible > 0** en esa ventana
(corrige la subestimación de demanda por quiebres). Definida en `marts.inv__demanda_sku` y reutilizada por INV-05, 06, 07, 10, 15.
Depósitos con `incluir_en_kpis = false` o `tipo in ('transito','virtual')` se excluyen salvo que se pidan explícitamente. Productos `gestiona_stock = false` o `es_servicio` siempre excluidos.

## Índice

| ID | KPI | Unidad | Dirección | Roles mínimos |
|---|---|---|---|---|
| [INV-01](#inv-01) | Valor del inventario | moneda | neutral | inventario |
| [INV-02](#inv-02) | Unidades en stock y SKUs con stock | unidades \| cantidad | neutral | inventario |
| [INV-03](#inv-03) | Rotación de inventario | veces | mayor_mejor | inventario |
| [INV-04](#inv-04) | Días de inventario (DIO) | dias | menor_mejor (dentro de un rango sano) | inventario |
| [INV-05](#inv-05) | Cobertura de stock por SKU (días) | dias | neutral (rango objetivo por clasificación ABC) | inventario, ventas |
| [INV-06](#inv-06) | Tasa de quiebre de stock | porcentaje | menor_mejor | inventario, ventas |
| [INV-07](#inv-07) | Venta perdida estimada por quiebre | moneda | menor_mejor | inventario, ventas |
| [INV-08](#inv-08) | Fill rate (tasa de cumplimiento de pedidos) | porcentaje | mayor_mejor | ventas |
| [INV-09](#inv-09) | Stock inmovilizado (sin movimiento) | moneda \| cantidad | menor_mejor | inventario, ventas |
| [INV-10](#inv-10) | Sobrestock | moneda | menor_mejor | inventario, ventas |
| [INV-11](#inv-11) | GMROI | ratio | mayor_mejor | inventario, ventas |
| [INV-12](#inv-12) | Clasificación ABC (y XYZ) | categoría | neutral | ventas |
| [INV-13](#inv-13) | Exactitud de inventario | porcentaje | mayor_mejor | inventario |
| [INV-14](#inv-14) | Ajustes y mermas | moneda \| porcentaje | menor_mejor | inventario |
| [INV-15](#inv-15) | SKUs a reponer (bajo punto de pedido) | cantidad \| moneda | menor_mejor | inventario, ventas |
| [INV-16](#inv-16) | Cumplimiento de proveedores (OTIF proveedor) | porcentaje | mayor_mejor | compras |
| [INV-17](#inv-17) | Lead time real de proveedores | dias | menor_mejor | compras |
| [INV-18](#inv-18) | Sell-through | porcentaje | mayor_mejor | inventario, ventas |
| [INV-19](#inv-19) | Compras en tránsito / OC abiertas | moneda | neutral | compras |
| [INV-20](#inv-20) | Stock en riesgo de vencimiento | moneda | menor_mejor | ventas, lotes_vencimientos o compras+inventario |
| [INV-21](#inv-21) | Quiebres ocultos (falta en góndola) | cantidad \| porcentaje \| moneda | menor_mejor | inventario, ventas |

---

## INV-01
### Valor del inventario

**Pregunta que responde:** ¿Cuánta plata tenemos en stock?  
**Definición:** Σ stock físico × costo unitario a la fecha (costo); opcional a precio de venta.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.valor` |
| Unidad | moneda |
| Dirección | neutral |
| Agregación | snapshot |
| Grano mínimo | dia |
| Dimensiones | deposito, tipo_deposito, categoria, marca, proveedor, clasificacion_abc |
| Filtros base | depósitos incluidos, gestiona_stock |
| Parámetros | `valuacion`=costo\|reposicion\|precio_venta, `moneda`=base\|<ISO> |
| Roles de fuente mínimos | inventario |
| Historia mínima | — |
| Relacionados | INV-03, INV-09 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(valor_stock) valor_costo, sum(valor_stock_precio_venta) valor_venta
from marts.fct_stock_diario_kpi where fecha = :fecha;   -- vista con filtros base aplicados
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_stock_diario.costo_unitario` | obligatoria si se usa la variante **costo_foto** |
| `dim_producto.costo_estandar` | obligatoria si se usa la variante **costo_estandar** |
| `dim_producto.categoria_n1` | opcional (habilita desgloses o mayor precisión) |

Basta con que se cumpla **una** de las variantes: costo_foto, costo_estandar (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- Stock negativo (errores de carga) se trata como 0 en valor y se informa en DQ-12.
- En inflación, valuación `reposicion` (costo_estandar vigente) refleja mejor el capital inmovilizado.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| valor real del stock crece > 15% mientras ventas reales caen | alta |

---

## INV-02
### Unidades en stock y SKUs con stock

**Pregunta que responde:** ¿Cuántas unidades y cuántos productos distintos tenemos disponibles?  
**Definición:** Σ stock disponible; cantidad de SKUs activos con stock disponible > 0.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.unidades_disponibles, stock.skus_con_stock` |
| Unidad | unidades \| cantidad |
| Dirección | neutral |
| Agregación | snapshot |
| Grano mínimo | dia |
| Dimensiones | deposito, categoria, marca |
| Filtros base | depósitos vendibles, producto activo |
| Parámetros | `tipo_stock`=fisico\|disponible\|reservado\|en_transito |
| Roles de fuente mínimos | inventario |
| Historia mínima | — |
| Relacionados | INV-06 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(stock_disponible), count(distinct producto_id) filter (where stock_disponible > 0)
from marts.fct_stock_diario_kpi where fecha = :fecha;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_stock_diario.stock_reservado` | opcional (habilita desgloses o mayor precisión) |
| `fct_stock_diario.stock_en_transito` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

---

## INV-03
### Rotación de inventario

**Pregunta que responde:** ¿Cuántas veces al año renovamos el stock?  
**Definición:** CMV del período / valor promedio de inventario a costo del período, anualizado.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.rotacion_anual` |
| Unidad | veces |
| Dirección | mayor_mejor |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | categoria, marca, proveedor, deposito, producto |
| Filtros base | depósitos incluidos |
| Parámetros | `periodo_dias`=90 |
| Roles de fuente mínimos | inventario |
| Historia mínima | — |
| Relacionados | INV-04, INV-11 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
rotacion = sum(cmv periodo) / nullif(avg(valor_stock diario periodo), 0) * (365 / dias_periodo)
-- cmv = Σ -costo_total de fct_movimiento_stock tipo venta_despacho/devolucion_cliente (o FIN-02 gestión)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_stock_diario.costo_unitario` | obligatoria |
| `fct_movimiento_stock.tipo_movimiento` | obligatoria si se usa la variante **cmv_movimientos** |
| `fct_movimiento_stock.costo_unitario` | obligatoria si se usa la variante **cmv_movimientos** |
| `fct_pedido_linea.costo_total` | obligatoria si se usa la variante **cmv_lineas** |

Basta con que se cumpla **una** de las variantes: cmv_movimientos, cmv_lineas (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- Productos nuevos (< periodo) distorsionan; excluirlos o marcar.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| rotacion de una categoría cae > 25% vs trimestre anterior | media |

---

## INV-04
### Días de inventario (DIO)

**Pregunta que responde:** ¿Para cuántos días de venta nos alcanza el stock (en valor)?  
**Definición:** Valor de inventario promedio / CMV diario promedio del período.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.dio` |
| Unidad | dias |
| Dirección | menor_mejor (dentro de un rango sano) |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | categoria, deposito, proveedor |
| Filtros base | depósitos incluidos |
| Parámetros | `periodo_dias`=90 |
| Roles de fuente mínimos | inventario |
| Historia mínima | — |
| Relacionados | INV-03, FIN-14 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
dio = avg(valor_stock) / nullif(sum(cmv) / dias_periodo, 0)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_stock_diario.costo_unitario` | obligatoria |
| `fct_movimiento_stock.tipo_movimiento` | obligatoria si se usa la variante **cmv_movimientos** |
| `fct_movimiento_stock.costo_unitario` | obligatoria si se usa la variante **cmv_movimientos** |
| `fct_pedido_linea.costo_total` | obligatoria si se usa la variante **cmv_lineas** |

Basta con que se cumpla **una** de las variantes: cmv_movimientos, cmv_lineas (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| dio > objetivo tenant (default 90) | media |

---

## INV-05
### Cobertura de stock por SKU (días)

**Pregunta que responde:** ¿Para cuántos días nos alcanza el stock de cada producto?  
**Definición:** Stock disponible (+ en tránsito opcional) / venta diaria promedio (VDP) del SKU.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.cobertura_dias` |
| Unidad | dias |
| Dirección | neutral (rango objetivo por clasificación ABC) |
| Agregación | calculado por SKU (no promediar; usar mediana ponderada por venta al agregar) |
| Grano mínimo | dia |
| Dimensiones | producto, categoria, clasificacion_abc, deposito, proveedor |
| Filtros base | producto activo, vdp > 0 |
| Parámetros | `ventana_vdp_dias`=90, `incluir_transito`=False |
| Roles de fuente mínimos | inventario, ventas |
| Historia mínima | — |
| Relacionados | INV-06, INV-10, INV-15 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select s.producto_id, s.stock_disponible / nullif(d.vdp, 0) cobertura_dias
from marts.fct_stock_diario_kpi s join marts.inv__demanda_sku d using (tenant_id, producto_id)
where s.fecha = :fecha;   -- agregado por producto sumando depósitos vendibles
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_stock_diario.stock_reservado` | opcional (habilita desgloses o mayor precisión) |
| `fct_stock_diario.stock_en_transito` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- VDP = 0 → cobertura "infinita" → va a INV-09 (inmovilizado).
- {'Productos estacionales': "permitir `ventana_vdp='mismo_periodo_anio_anterior'`."}

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| SKU clase A con cobertura < lead_time_dias del proveedor | alta |

---

## INV-06
### Tasa de quiebre de stock

**Pregunta que responde:** ¿Qué porcentaje de nuestros productos está sin stock?  
**Definición:** SKUs activos con demanda (VDP > 0) y stock disponible = 0 / SKUs activos con demanda; versión ponderada por venta.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.tasa_quiebre, stock.tasa_quiebre_ponderada` |
| Unidad | porcentaje |
| Dirección | menor_mejor |
| Agregación | ratio (snapshot) / promedio diario en períodos |
| Grano mínimo | dia |
| Dimensiones | categoria, clasificacion_abc, deposito, canal (stock asignado), proveedor |
| Filtros base | producto activo, vdp > 0 |
| Parámetros | — |
| Roles de fuente mínimos | inventario, ventas |
| Historia mínima | — |
| Relacionados | INV-07, VEN-17 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) filter (where s.stock_disponible <= 0)::numeric / nullif(count(*),0) quiebre_skus,
       sum(d.vdp * d.precio_neto_prom) filter (where s.stock_disponible <= 0) / nullif(sum(d.vdp * d.precio_neto_prom),0) quiebre_ponderado
from marts.inv__demanda_sku d left join marts.fct_stock_sku_dia s using (tenant_id, producto_id)
where s.fecha = :fecha and d.vdp > 0;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `dim_producto.activo` | obligatoria |
| `fct_stock_diario.stock_reservado` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Si hay depósitos de fulfillment de terceros y propios, reportar quiebre por depósito (sin stock en el de terceros pero con stock propio = oportunidad de reposición).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| quiebre_ponderado > 5% | alta |
| SKU clase A sin stock | critica |

---

## INV-07
### Venta perdida estimada por quiebre

**Pregunta que responde:** ¿Cuánta venta perdimos por no tener stock?  
**Definición:** Σ por SKU de (días sin stock en el período × VDP × precio neto promedio).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.venta_perdida` |
| Unidad | moneda |
| Dirección | menor_mejor |
| Agregación | aditivo |
| Grano mínimo | dia |
| Dimensiones | producto, categoria, proveedor |
| Filtros base | producto activo con vdp > 0 |
| Parámetros | — |
| Roles de fuente mínimos | inventario, ventas |
| Historia mínima | ≥ 30 días de fotos |
| Relacionados | INV-06 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(d.dias_sin_stock * v.vdp * v.precio_neto_prom)
from (select producto_id, count(*) dias_sin_stock from marts.fct_stock_sku_dia
      where stock_disponible <= 0 and fecha between :desde and :hasta group by 1) d
join marts.inv__demanda_sku v using (producto_id);
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_pedido_linea.importe_neto` | obligatoria |

**Casos borde y reglas:**

- Es estimación; el agente la presenta como "hasta" y no la suma a ventas.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| venta_perdida del mes > 5% de la venta neta | alta |

---

## INV-08
### Fill rate (tasa de cumplimiento de pedidos)

**Pregunta que responde:** ¿Qué porcentaje de lo que nos piden podemos entregar completo?  
**Definición:** Líneas (o unidades) entregadas completas / líneas pedidas, en pedidos válidos despachados.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.fill_rate` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | deposito, categoria, cliente (B2B), canal |
| Filtros base | pedido_valido, estado despachado/entregado |
| Parámetros | `medida`=unidades\|lineas |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | LOG-07 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(least(cantidad_entregada, cantidad)) / nullif(sum(cantidad),0) fill_rate_unidades,
       count(*) filter (where cantidad_entregada >= cantidad)::numeric / nullif(count(*),0) fill_rate_lineas
from core.fct_pedido_linea l join core.fct_pedido p using (pedido_id)
where pedido_valido and p.estado in ('despachado','entregado') and p.fecha_pedido between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_pedido_linea.cantidad_entregada` | obligatoria |
| `fct_pedido.estado` | obligatoria |

**Casos borde y reglas:**

- En B2C la falta de stock se refleja como cancelación (VEN-17) más que como entrega parcial.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| fill_rate_lineas < 95% | alta |

---

## INV-09
### Stock inmovilizado (sin movimiento)

**Pregunta que responde:** ¿Cuánta plata tenemos en productos que no se venden?  
**Definición:** Valor de stock de SKUs sin ventas en los últimos N días (default 90) y con stock > 0.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.valor_inmovilizado` |
| Unidad | moneda \| cantidad |
| Dirección | menor_mejor |
| Agregación | snapshot |
| Grano mínimo | dia |
| Dimensiones | categoria, marca, proveedor, deposito, tramo_dias_sin_venta (90-180, 180-365, >365) |
| Filtros base | stock > 0 |
| Parámetros | `dias`=90 |
| Roles de fuente mínimos | inventario, ventas |
| Historia mínima | — |
| Relacionados | INV-10, INV-01 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(valor_stock), count(distinct producto_id)
from marts.fct_stock_diario_kpi where fecha = :fecha and stock_fisico > 0
  and coalesce(dias_sin_venta, 9999) > :dias;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_stock_diario.costo_unitario` | obligatoria |
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido.fecha_pedido` | obligatoria |

**Casos borde y reglas:**

- Productos dados de alta hace < N días no cuentan como inmovilizados.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| inmovilizado > 20% del valor de inventario | alta |

---

## INV-10
### Sobrestock

**Pregunta que responde:** ¿Qué productos tienen más stock del necesario?  
**Definición:** Valor del stock por encima de la cobertura objetivo (default 60 días o stock_maximo) para SKUs con VDP > 0.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.valor_sobrestock` |
| Unidad | moneda |
| Dirección | menor_mejor |
| Agregación | snapshot |
| Grano mínimo | dia |
| Dimensiones | categoria, proveedor, clasificacion_abc |
| Filtros base | vdp > 0 |
| Parámetros | `cobertura_objetivo_dias`=A 30 / B 45 / C 60 (config) |
| Roles de fuente mínimos | inventario, ventas |
| Historia mínima | — |
| Relacionados | INV-05, INV-09 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
exceso_unidades = greatest(stock_disponible - greatest(vdp * cobertura_objetivo, coalesce(stock_maximo,0)), 0)
valor_sobrestock = Σ exceso_unidades × costo_unitario
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_stock_diario.costo_unitario` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `parametro_reposicion.stock_maximo` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Compras anticipadas deliberadas (cobertura inflacionaria, temporada) → el tenant puede marcar excepciones.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| sobrestock > 15% del valor de inventario | media |

---

## INV-11
### GMROI

**Pregunta que responde:** ¿Cuánto margen bruto nos devuelve cada unidad de moneda invertida en stock?  
**Definición:** Margen bruto del período (anualizado) / valor promedio de inventario a costo.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.gmroi` |
| Unidad | ratio |
| Dirección | mayor_mejor |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | categoria, marca, proveedor, producto |
| Filtros base | pedido_valido |
| Parámetros | `periodo_dias`=90 |
| Roles de fuente mínimos | inventario, ventas |
| Historia mínima | — |
| Relacionados | INV-03, VEN-08 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
gmroi = (Σ (importe_neto - costo_total) líneas del periodo * 365/dias) / nullif(avg(valor_stock), 0)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido_linea.importe_neto` | obligatoria |
| `fct_pedido_linea.costo_total` | obligatoria |
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_stock_diario.costo_unitario` | obligatoria |

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| categoría con gmroi < 1 | media |

---

## INV-12
### Clasificación ABC (y XYZ)

**Pregunta que responde:** ¿Cuáles son los productos que más importan?  
**Definición:** ABC por venta neta (o margen) de 12 meses — A = 80 % acumulado, B = siguiente 15 %, C = último 5 %; XYZ por coeficiente de variación de la demanda semanal (X < 0.5, Y < 1, Z ≥ 1).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `productos.clasificacion_abc (dimensión) + conteos` |
| Unidad | categoría |
| Dirección | neutral |
| Agregación | dimensión |
| Grano mínimo | mes |
| Dimensiones | categoria, deposito |
| Filtros base | pedido_valido |
| Parámetros | `base`=venta\|margen\|unidades, `ventana_meses`=12 |
| Roles de fuente mínimos | ventas |
| Historia mínima | — |
| Relacionados | INV-05, INV-06, VEN-23 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
-- marts.inv__abc (mensual, escribe dim_producto.clasificacion_abc)
with v as (select producto_id, sum(importe_neto) venta from core.fct_pedido_linea l join core.fct_pedido p using(pedido_id)
           where pedido_valido and p.fecha_pedido > current_date - 365 group by 1)
select producto_id, case when acum <= 0.8 then 'A' when acum <= 0.95 then 'B' else 'C' end
from (select *, sum(venta) over (order by venta desc) / sum(venta) over () acum from v) x;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido_linea.importe_neto` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_pedido_linea.costo_total` | obligatoria |

**Casos borde y reglas:**

- Productos sin ventas en 12 meses → clase 'D' (candidatos a discontinuar).

---

## INV-13
### Exactitud de inventario

**Pregunta que responde:** ¿El stock del sistema coincide con el físico?  
**Definición:** % de SKUs contados cuya diferencia está dentro de la tolerancia (default 0 unidades o ±2 %); valor absoluto de diferencias / valor contado.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.exactitud_inventario` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | deposito, categoria, clasificacion_abc |
| Filtros base | — |
| Parámetros | `tol_unid`=0, `tol_pct`=0.02 |
| Roles de fuente mínimos | inventario |
| Historia mínima | — |
| Relacionados | INV-14 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) filter (where abs(diferencia) <= greatest(:tol_unid, abs(cantidad_sistema)*:tol_pct))::numeric / nullif(count(*),0) exactitud,
       sum(abs(valor_diferencia)) / nullif(sum(cantidad_contada * costo),0) error_valor
from core.fct_conteo_inventario where fecha between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_conteo_inventario.cantidad_sistema` | obligatoria |
| `fct_conteo_inventario.cantidad_contada` | obligatoria |

**Casos borde y reglas:**

- Sin conteos en el período → KPI no disponible; se usa INV-14 como proxy.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| exactitud < 95% | alta |

---

## INV-14
### Ajustes y mermas

**Pregunta que responde:** ¿Cuánto stock perdemos por ajustes, roturas o faltantes?  
**Definición:** Valor neto de ajustes negativos + mermas − ajustes positivos / CMV del período.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.valor_ajustes, stock.merma_pct` |
| Unidad | moneda \| porcentaje |
| Dirección | menor_mejor |
| Agregación | aditivo / ratio |
| Grano mínimo | dia |
| Dimensiones | deposito, motivo_ajuste, categoria, producto |
| Filtros base | excluye inventario_inicial |
| Parámetros | — |
| Roles de fuente mínimos | inventario |
| Historia mínima | — |
| Relacionados | INV-13 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select -sum(costo_total) filter (where tipo_movimiento in ('ajuste_negativo','merma','ajuste_positivo')) valor_ajustes,
       -sum(costo_total) filter (where tipo_movimiento in ('ajuste_negativo','merma','ajuste_positivo')) / nullif(cmv,0) pct_cmv
from core.fct_movimiento_stock where fecha between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_movimiento_stock.tipo_movimiento` | obligatoria |
| `fct_movimiento_stock.cantidad` | obligatoria |
| `fct_movimiento_stock.costo_unitario` | obligatoria |
| `fct_movimiento_stock.motivo_ajuste` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| merma_pct > 1% del CMV | alta |
| ajuste negativo único > umbral tenant | media |

---

## INV-15
### SKUs a reponer (bajo punto de pedido)

**Pregunta que responde:** ¿Qué tenemos que comprar ya?  
**Definición:** SKUs activos cuyo stock disponible + en tránsito ≤ punto de pedido; cantidad sugerida = objetivo − (disponible + tránsito).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `reposicion.skus_a_reponer, reposicion.valor_sugerido` |
| Unidad | cantidad \| moneda |
| Dirección | menor_mejor |
| Agregación | snapshot |
| Grano mínimo | dia |
| Dimensiones | proveedor, deposito, categoria, clasificacion_abc |
| Filtros base | producto activo, gestiona_stock |
| Parámetros | `dias_seguridad`=7, `cobertura_objetivo`=30 |
| Roles de fuente mínimos | inventario, ventas |
| Historia mínima | — |
| Relacionados | INV-05, INV-16, INV-17 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
punto_pedido = coalesce(pr.punto_pedido, vdp * (lead_time_dias + dias_seguridad))
objetivo = coalesce(pr.stock_maximo, vdp * (lead_time_dias + cobertura_objetivo))
sugerido = greatest(objetivo - (stock_disponible + stock_en_transito), 0) redondeado a múltiplo de compra
where stock_disponible + stock_en_transito <= punto_pedido
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `parametro_reposicion.lead_time_dias` | obligatoria si se usa la variante **lead_time_parametro** |
| `dim_producto.proveedor_principal_id` | obligatoria si se usa la variante **lead_time_proveedor** |
| `dim_proveedor.lead_time_dias_estandar` | obligatoria si se usa la variante **lead_time_proveedor** |
| `fct_orden_compra.fecha_emision` | obligatoria si se usa la variante **lead_time_historico** |
| `fct_recepcion.fecha_recepcion` | obligatoria si se usa la variante **lead_time_historico** |
| `fct_stock_diario.stock_en_transito` | opcional (habilita desgloses o mayor precisión) |
| `fct_stock_diario.stock_reservado` | opcional (habilita desgloses o mayor precisión) |
| `parametro_reposicion.punto_pedido` | opcional (habilita desgloses o mayor precisión) |
| `parametro_reposicion.stock_maximo` | opcional (habilita desgloses o mayor precisión) |

Basta con que se cumpla **una** de las variantes: lead_time_parametro, lead_time_proveedor, lead_time_historico (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- Es sugerencia; el agente no genera OCs, solo lista (la creación de OC es fase 3 con aprobación humana).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| SKU clase A bajo punto de pedido sin OC abierta | alta |

---

## INV-16
### Cumplimiento de proveedores (OTIF proveedor)

**Pregunta que responde:** ¿Los proveedores entregan a tiempo y completo?  
**Definición:** Líneas de OC recibidas completas (≥ 98 % de lo pedido) y a tiempo (fecha_ultima_recepcion ≤ fecha_entrega_prometida + tolerancia) / líneas de OC con fecha prometida vencida en el período.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `compras.otif_proveedor` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | mes |
| Dimensiones | proveedor, categoria |
| Filtros base | OC no cancelada |
| Parámetros | `tolerancia_dias`=2 |
| Roles de fuente mínimos | compras |
| Historia mínima | — |
| Relacionados | INV-17 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) filter (where cantidad_recibida >= 0.98*cantidad_pedida
                        and fecha_ultima_recepcion <= fecha_entrega_prometida + :tol)::numeric / nullif(count(*),0)
from core.fct_orden_compra_linea l join core.fct_orden_compra o using (orden_compra_id)
where o.estado <> 'cancelada' and l.fecha_entrega_prometida between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_orden_compra.fecha_emision` | obligatoria |
| `fct_orden_compra_linea.fecha_entrega_prometida` | obligatoria |
| `fct_orden_compra_linea.cantidad_pedida` | obligatoria |
| `fct_orden_compra_linea.cantidad_recibida` | obligatoria |
| `fct_recepcion.fecha_recepcion` | obligatoria |
| `fct_orden_compra.estado` | obligatoria |

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| proveedor principal con otif < 80% | media |

---

## INV-17
### Lead time real de proveedores

**Pregunta que responde:** ¿Cuánto tardan de verdad los proveedores en entregar?  
**Definición:** Mediana y P90 de días entre fecha de emisión/aprobación de la OC y primera recepción, por proveedor.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `compras.lead_time_mediana, compras.lead_time_p90` |
| Unidad | dias |
| Dirección | menor_mejor |
| Agregación | mediana |
| Grano mínimo | mes |
| Dimensiones | proveedor, categoria |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | compras |
| Historia mínima | — |
| Relacionados | INV-15, INV-16 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select proveedor_id, percentile_cont(0.5) within group (order by fecha_primera_recepcion - fecha_emision) from core.fct_orden_compra_linea join core.fct_orden_compra using (orden_compra_id) where fecha_primera_recepcion between :desde and :hasta group by 1;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_orden_compra.fecha_emision` | obligatoria |
| `fct_orden_compra_linea.fecha_entrega_prometida` | obligatoria |
| `fct_recepcion.fecha_recepcion` | obligatoria |

**Casos borde y reglas:**

- Alimenta MB-REPOSICION.lead_time_dias cuando el sistema de gestión no lo tiene.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| lead time P90 > lead_time_dias_estandar × 1.5 | media |

---

## INV-18
### Sell-through

**Pregunta que responde:** ¿Qué porcentaje de lo que recibimos ya vendimos?  
**Definición:** Unidades vendidas / (unidades vendidas + stock final) en el período, o por lote/temporada desde la recepción.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.sell_through` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | semana |
| Dimensiones | categoria, marca, temporada (atributo producto), proveedor |
| Filtros base | — |
| Parámetros | `desde_recepcion`=False |
| Roles de fuente mínimos | inventario, ventas |
| Historia mínima | — |
| Relacionados | INV-09 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
sell_through = unidades_vendidas / nullif(unidades_vendidas + stock_fisico_final, 0)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_recepcion.fecha_recepcion` | opcional (habilita desgloses o mayor precisión) |
| `dim_producto.temporada` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Clave en moda/temporada; el atributo temporada viene de categoría o campo custom ⚠.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| temporada con sell_through < 50% a mitad de temporada | media |

---

## INV-19
### Compras en tránsito / OC abiertas

**Pregunta que responde:** ¿Cuánto tenemos comprado que todavía no llegó?  
**Definición:** Σ (cantidad pedida − recibida) × precio de OCs confirmadas no canceladas; atrasadas = fecha_entrega_prometida < hoy.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `compras.valor_oc_abiertas, compras.valor_oc_atrasadas` |
| Unidad | moneda |
| Dirección | neutral |
| Agregación | snapshot |
| Grano mínimo | dia |
| Dimensiones | proveedor, deposito, categoria |
| Filtros base | OC confirmada |
| Parámetros | — |
| Roles de fuente mínimos | compras |
| Historia mínima | — |
| Relacionados | INV-15, FIN-13 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum((cantidad_pedida - cantidad_recibida) * precio_unitario) valor_abierto,
       sum(...) filter (where l.fecha_entrega_prometida < current_date) valor_atrasado
from core.fct_orden_compra_linea l join core.fct_orden_compra o using (orden_compra_id)
where o.estado in ('confirmada','recibida_parcial') and cantidad_recibida < cantidad_pedida;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_orden_compra_linea.cantidad_pedida` | obligatoria |
| `fct_orden_compra_linea.cantidad_recibida` | obligatoria |
| `fct_orden_compra.fecha_emision` | obligatoria |
| `fct_orden_compra_linea.fecha_entrega_prometida` | obligatoria |
| `fct_orden_compra.estado` | obligatoria |

**Casos borde y reglas:**

- OCs viejas nunca cerradas (> 180 días) se listan para limpieza (DQ-14).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| OC atrasada de SKU en quiebre | alta |

---

## INV-20
### Stock en riesgo de vencimiento

**Pregunta que responde:** ¿Cuánta mercadería se nos puede vencer antes de venderla?  
**Definición:** Valor a costo de las unidades que, al ritmo de venta actual y consumiendo por FEFO, no se venderían antes de su fecha límite de venta; más el valor ya vencido sin retirar.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `stock.valor_riesgo_vencimiento` |
| Unidad | moneda |
| Dirección | menor_mejor |
| Agregación | snapshot |
| Grano mínimo | dia |
| Dimensiones | deposito, categoria, proveedor, tramo_dias_a_vencer (0, 1-7, 8-30, 31-60) |
| Filtros base | lotes con cantidad > 0 |
| Parámetros | `ventana_dias`=60 |
| Roles de fuente mínimos | ventas, lotes_vencimientos o compras+inventario |
| Historia mínima | — |
| Relacionados | INV-14, INV-09 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(valor_en_riesgo) filter (where dias_a_vencer > 0) as valor_en_riesgo,
       sum(cantidad * costo_unitario) filter (where dias_a_vencer <= 0) as valor_vencido
from marts.act__vencimientos where fecha = :fecha;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_stock_lote.fecha_vencimiento` | obligatoria si se usa la variante **stock_por_lote** |
| `fct_stock_lote.cantidad` | obligatoria si se usa la variante **stock_por_lote** |
| `fct_stock_lote.costo_unitario` | obligatoria si se usa la variante **stock_por_lote** |
| `fct_recepcion.fecha_vencimiento` | obligatoria si se usa la variante **recepciones_con_vencimiento** |
| `fct_recepcion.cantidad_recibida` | obligatoria si se usa la variante **recepciones_con_vencimiento** |
| `fct_stock_diario.costo_unitario` | obligatoria si se usa la variante **recepciones_con_vencimiento** |
| `dim_producto.dias_retiro_antes_vencimiento` | opcional (habilita desgloses o mayor precisión) |

Basta con que se cumpla **una** de las variantes: stock_por_lote, recepciones_con_vencimiento (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- Con la variante recepciones_con_vencimiento los lotes son estimados (FEFO); el agente lo aclara.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| valor_en_riesgo > 1% del valor del inventario | alta |
| valor_vencido > 0 (mercadería vencida sin retirar) | critica |

---

## INV-21
### Quiebres ocultos (falta en góndola)

**Pregunta que responde:** ¿Cuántos productos dejamos de vender por no estar exhibidos aunque había stock?  
**Definición:** Cantidad de casos de quiebre oculto detectados (ACT-01), tasa de confirmación y venta perdida estimada por esos casos.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `actividades.quiebres_ocultos` |
| Unidad | cantidad \| porcentaje \| moneda |
| Dirección | menor_mejor |
| Agregación | aditivo / ratio |
| Grano mínimo | dia |
| Dimensiones | sucursal, categoria, caso, resolucion |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | inventario, ventas |
| Historia mínima | — |
| Relacionados | INV-06, INV-07, INV-13 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) casos, avg((resolucion = any(:confirmadas))::int) tasa_confirmacion, sum(impacto_estimado) venta_perdida
from ops.actividad where tipo = 'ACT-01' and detectada_at::date between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.pedido_at` | obligatoria |
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_stock_diario.stock_disponible` | obligatoria |

**Casos borde y reglas:**

- La venta perdida es una estimación (λ × días × precio); el agente la presenta como 'hasta'.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| sucursal con > 10 quiebres ocultos confirmados en la semana | alta |

