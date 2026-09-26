# 08 — KPIs de Finanzas

> Generado por `tools/build_kpis.py` desde `kpis/src/finanzas.yml`. No editar a mano.
> Los KPIs se calculan **solo** sobre el modelo canónico (docs/04). Cada ficha declara qué columnas canónicas necesita; qué sistema las aporta lo define el `mapping.yml` de cada fuente (docs/05).

Cubre resultados (EERR), liquidez, capital de trabajo, cobranzas/pagos, costos de cobro y controles fiscales.
**Modo contable vs gestión:** si el tenant tiene contabilidad (`fct_asiento_linea`) los KPIs de EERR usan `modo='contable'`;
si no, `modo='gestion'` (docs/03 §1.3). El KPI siempre devuelve el modo usado para que el agente lo mencione.
Todos los montos: moneda base, sin impuesto indirecto (salvo CxC/CxP/tesorería, que son **con impuesto indirecto** porque representan dinero), con opción `ajuste='real'`.

## Índice

| ID | KPI | Unidad | Dirección | Roles mínimos |
|---|---|---|---|---|
| [FIN-01](#fin-01) | Ventas netas contables | moneda | mayor_mejor | contabilidad o facturacion |
| [FIN-02](#fin-02) | Costo de mercadería vendida (CMV) | moneda | menor_mejor | contabilidad o inventario o ventas |
| [FIN-03](#fin-03) | Margen bruto ($ y %) | moneda \| porcentaje | mayor_mejor | contabilidad o facturacion+ventas |
| [FIN-04](#fin-04) | Gastos operativos por línea | moneda | menor_mejor | contabilidad o facturacion |
| [FIN-05](#fin-05) | EBITDA y margen EBITDA | moneda \| porcentaje | mayor_mejor | contabilidad o facturacion+ventas |
| [FIN-06](#fin-06) | Resultado neto | moneda | mayor_mejor | contabilidad |
| [FIN-07](#fin-07) | Caja disponible | moneda | mayor_mejor | tesoreria |
| [FIN-08](#fin-08) | Flujo de caja (operativo, inversión, financiación) | moneda | mayor_mejor | tesoreria |
| [FIN-09](#fin-09) | Burn rate y runway | moneda \| meses | mayor_mejor (runway) | tesoreria |
| [FIN-10](#fin-10) | Cuentas por cobrar (total, vencida y % vencida) | moneda \| porcentaje | menor_mejor | cuentas_corrientes |
| [FIN-11](#fin-11) | Aging de cuentas por cobrar | moneda | menor_mejor (tramos altos) | cuentas_corrientes |
| [FIN-12](#fin-12) | DSO (días de cobro) | dias | menor_mejor | cuentas_corrientes, facturacion |
| [FIN-13](#fin-13) | Cuentas por pagar y DPO | moneda \| dias | neutral | cuentas_corrientes, facturacion |
| [FIN-14](#fin-14) | Ciclo de conversión de caja | dias | menor_mejor | cuentas_corrientes, inventario |
| [FIN-15](#fin-15) | Efectividad de cobranza (CEI) | porcentaje | mayor_mejor | cuentas_corrientes, facturacion |
| [FIN-16](#fin-16) | Proyección de caja 7/30/60/90 días | moneda | mayor_mejor | tesoreria |
| [FIN-17](#fin-17) | Costo de cobro (comisiones de pasarelas, marketplaces y financiación) | porcentaje | menor_mejor | pasarela_pagos |
| [FIN-18](#fin-18) | Conciliación con registro fiscal oficial | cantidad \| moneda | menor_mejor (debe ser 0) | facturacion, registro_fiscal_oficial |
| [FIN-19](#fin-19) | Desvío vs presupuesto (EERR) | moneda \| porcentaje | depende de la línea (ingresos mayor_mejor, gastos menor_mejor) | presupuesto, contabilidad o facturacion+ventas |
| [FIN-20](#fin-20) | Punto de equilibrio | moneda | menor_mejor | contabilidad o facturacion+ventas |
| [FIN-21](#fin-21) | Posición estimada de impuesto indirecto | moneda | neutral | facturacion |
| [FIN-22](#fin-22) | Evolución real de gastos por categoría | moneda \| porcentaje | menor_mejor | referencia_indice_precios, contabilidad o facturacion |

---

## FIN-01
### Ventas netas contables

**Pregunta que responde:** ¿Cuánto facturamos netos de descuentos y devoluciones en el período?  
**Definición:** Ventas brutas menos descuentos, bonificaciones y devoluciones reconocidas en el período (línea `ventas_netas` del EERR).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `eerr.ventas_netas` |
| Unidad | moneda |
| Dirección | mayor_mejor |
| Agregación | aditivo |
| Grano mínimo | dia |
| Dimensiones | sucursal, centro_costo, canal (solo gestión), cliente (solo gestión) |
| Filtros base | estado publicado, excluye asientos de cierre |
| Parámetros | `modo`=auto\|contable\|gestion, `ajuste`=nominal\|real, `moneda`=base\|<ISO> |
| Roles de fuente mínimos | contabilidad o facturacion |
| Historia mínima | — |
| Relacionados | VEN-01, FIN-19 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
-- modo contable
select -sum(a.saldo) as ventas_netas
from core.fct_asiento_linea a join core.dim_cuenta_contable c using (cuenta_id)
where c.eerr_linea in ('ventas_brutas','descuentos_devoluciones')
  and a.estado = 'publicado' and not a.es_cierre
  and a.fecha_contable between :desde and :hasta;
-- modo gestion
select sum(importe_neto * signo) from core.fct_comprobante
where circuito = 'venta' and estado = 'emitido'
  and computa_venta
  and fecha_emision between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_asiento_linea.fecha_contable` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.saldo` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.cuenta_id` | obligatoria si se usa la variante **contable** |
| `dim_cuenta_contable.codigo_estandar` | obligatoria si se usa la variante **contable** |
| `fct_comprobante.circuito` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.clase` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.fecha_emision` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.importe_neto` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.estado` | obligatoria si se usa la variante **gestion** |

Basta con que se cumpla **una** de las variantes: contable, gestion (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- {'Diferencia con VEN-01 (comercial) es esperada': 'fecha de pedido vs factura, pedidos sin facturar, envío. El agente debe explicarla si se comparan.'}
- Documentos en moneda extranjera se valúan con el tipo de cambio informado en el propio documento si la fuente lo trae (tc_aplicado); si no, con ref.tipo_cambio.
- Tickets con rango CbteDesde-CbteHasta cuentan una vez con el importe total.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| variacion_real_vs_mismo_mes_anio_anterior < -10% | alta |
| desvio_vs_presupuesto < -10% al cierre de mes | alta |

---

## FIN-02
### Costo de mercadería vendida (CMV)

**Pregunta que responde:** ¿Cuánto nos costó lo que vendimos?  
**Definición:** Costo de los bienes/servicios vendidos en el período.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `eerr.cmv` |
| Unidad | moneda |
| Dirección | menor_mejor |
| Agregación | aditivo |
| Grano mínimo | dia |
| Dimensiones | sucursal, categoria (gestión), producto (gestión), canal (gestión) |
| Filtros base | estado publicado |
| Parámetros | `modo`=auto\|contable\|gestion |
| Roles de fuente mínimos | contabilidad o inventario o ventas |
| Historia mínima | — |
| Relacionados | FIN-03, VEN-08 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
-- contable
select sum(a.saldo) from core.fct_asiento_linea a join core.dim_cuenta_contable c using (cuenta_id)
where c.eerr_linea = 'cmv' and a.estado='publicado' and not a.es_cierre and a.fecha_contable between :desde and :hasta;
-- gestion: costo de líneas facturadas (o despachadas si no hay factura por línea)
select sum(-m.costo_total) from core.fct_movimiento_stock m
where m.tipo_movimiento in ('venta_despacho','devolucion_cliente') and m.fecha between :desde and :hasta;
-- fallback gestión sin movimientos: sum(pl.costo_total) de pedidos válidos
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_asiento_linea.fecha_contable` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.saldo` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.cuenta_id` | obligatoria si se usa la variante **contable** |
| `dim_cuenta_contable.codigo_estandar` | obligatoria si se usa la variante **contable** |
| `fct_movimiento_stock.tipo_movimiento` | obligatoria si se usa la variante **gestion_movimientos** |
| `fct_movimiento_stock.cantidad` | obligatoria si se usa la variante **gestion_movimientos** |
| `fct_movimiento_stock.costo_unitario` | obligatoria si se usa la variante **gestion_movimientos** |
| `fct_pedido.fecha_pedido` | obligatoria si se usa la variante **gestion_lineas** |
| `fct_pedido_linea.costo_total` | obligatoria si se usa la variante **gestion_lineas** |

Basta con que se cumpla **una** de las variantes: contable, gestion_movimientos, gestion_lineas (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- Empresas que registran CMV solo al cierre mensual (inventario periódico) → CMV contable = 0 en meses intermedios; usar modo gestión y avisar.
- Si % de ventas sin costo > 5 % (DQ-07) el KPI se marca "incompleto".

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| cmv_sobre_ventas sube > 3 pp vs promedio 3 meses | media |

---

## FIN-03
### Margen bruto ($ y %)

**Pregunta que responde:** ¿Cuánto nos queda después del costo de la mercadería?  
**Definición:** Ventas netas − CMV; margen % = margen bruto / ventas netas.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `eerr.margen_bruto, eerr.margen_bruto_pct` |
| Unidad | moneda \| porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio (recalcular, nunca promediar porcentajes) |
| Grano mínimo | mes (contable) / dia (gestión) |
| Dimensiones | sucursal, canal, categoria, producto (gestión) |
| Filtros base | — |
| Parámetros | `modo`=auto\|contable\|gestion |
| Roles de fuente mínimos | contabilidad o facturacion+ventas |
| Historia mínima | — |
| Relacionados | VEN-08, VEN-09, INV-11 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
margen_bruto = FIN-01 - FIN-02
margen_bruto_pct = (FIN-01 - FIN-02) / nullif(FIN-01, 0)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_asiento_linea.fecha_contable` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.saldo` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.cuenta_id` | obligatoria si se usa la variante **contable** |
| `dim_cuenta_contable.codigo_estandar` | obligatoria si se usa la variante **contable** |
| `fct_comprobante.circuito` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.clase` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.fecha_emision` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.importe_neto` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.estado` | obligatoria si se usa la variante **gestion** |
| `fct_pedido_linea.costo_total` | obligatoria si se usa la variante **gestion** |

Basta con que se cumpla **una** de las variantes: contable, gestion (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- En alta inflación el margen a costo histórico sobreestima rentabilidad; ofrecer `costo='reposicion'` usando dim_producto.costo_estandar vigente.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| margen_bruto_pct < umbral tenant (default 25%) | alta |
| caida > 3 pp vs mes anterior | media |

---

## FIN-04
### Gastos operativos por línea

**Pregunta que responde:** ¿Cuánto gastamos en comercialización, administración y personal?  
**Definición:** Suma de gastos de las líneas gastos_comercializacion, gastos_administracion y gastos_personal; desglose por cuenta estándar y centro de costo.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `eerr.gastos_operativos` |
| Unidad | moneda |
| Dirección | menor_mejor |
| Agregación | aditivo |
| Grano mínimo | mes |
| Dimensiones | eerr_linea, codigo_estandar, centro_costo, sucursal, proveedor (gestión), categoria_gasto (gestión) |
| Filtros base | estado publicado |
| Parámetros | `modo`=auto\|contable\|gestion, `ajuste`=nominal\|real |
| Roles de fuente mínimos | contabilidad o facturacion |
| Historia mínima | — |
| Relacionados | FIN-05, FIN-22 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
-- contable
select c.eerr_linea, c.codigo_estandar, sum(a.saldo) as gasto
from core.fct_asiento_linea a join core.dim_cuenta_contable c using (cuenta_id)
where c.eerr_linea in ('gastos_comercializacion','gastos_administracion','gastos_personal')
  and a.estado='publicado' and not a.es_cierre and a.fecha_contable between :desde and :hasta
group by 1,2;
-- gestion
select categoria_gasto, sum(importe_neto*signo) from core.fct_comprobante
where circuito='compra' and categoria_gasto <> 'mercaderia' and fecha_emision between :desde and :hasta group by 1
union all
select tipo, -sum(importe) from core.fct_movimiento_tesoreria
where tipo in ('sueldos_cargas','comisiones_bancarias') and fecha between :desde and :hasta group by 1;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_asiento_linea.fecha_contable` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.saldo` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.cuenta_id` | obligatoria si se usa la variante **contable** |
| `dim_cuenta_contable.codigo_estandar` | obligatoria si se usa la variante **contable** |
| `fct_comprobante.circuito` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.clase` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.fecha_emision` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.importe_neto` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.estado` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.categoria_gasto` | obligatoria si se usa la variante **gestion** |
| `fct_asiento_linea.centro_costo_id` | opcional (habilita desgloses o mayor precisión) |
| `fct_movimiento_tesoreria.tipo` | opcional (habilita desgloses o mayor precisión) |

Basta con que se cumpla **una** de las variantes: contable, gestion (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- {'Sueldos no pasan por comprobantes': 'en modo gestión se toman de tesorería (neto pagado, no costo laboral total) → avisar subestimación.'}
- Gastos anuales (seguros, patentes) generan picos; ofrecer vista `devengado_prorrateado` si el tenant carga prorrateos.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| gasto real (ajustado índice de precios) de una cuenta estándar sube > 20% vs promedio 3 meses | media |
| gastos_operativos / ventas_netas > umbral tenant | alta |

---

## FIN-05
### EBITDA y margen EBITDA

**Pregunta que responde:** ¿Cuánto genera el negocio operativamente antes de amortizaciones, intereses e impuestos?  
**Definición:** Margen bruto − gastos operativos (comercialización + administración + personal).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `eerr.ebitda, eerr.ebitda_pct` |
| Unidad | moneda \| porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | mes |
| Dimensiones | sucursal, centro_costo |
| Filtros base | — |
| Parámetros | `modo`=auto\|contable\|gestion, `ajuste`=nominal\|real |
| Roles de fuente mínimos | contabilidad o facturacion+ventas |
| Historia mínima | — |
| Relacionados | FIN-06, FIN-20 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
ebitda = FIN-03.margen_bruto - FIN-04.gastos_operativos
ebitda_pct = ebitda / nullif(FIN-01, 0)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_asiento_linea.fecha_contable` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.saldo` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.cuenta_id` | obligatoria si se usa la variante **contable** |
| `dim_cuenta_contable.codigo_estandar` | obligatoria si se usa la variante **contable** |
| `fct_comprobante.circuito` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.clase` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.fecha_emision` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.importe_neto` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.estado` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.categoria_gasto` | obligatoria si se usa la variante **gestion** |
| `fct_pedido_linea.costo_total` | obligatoria si se usa la variante **gestion** |
| `fct_asiento_linea.centro_costo_id` | opcional (habilita desgloses o mayor precisión) |
| `fct_movimiento_tesoreria.tipo` | opcional (habilita desgloses o mayor precisión) |

Basta con que se cumpla **una** de las variantes: contable, gestion (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- Por sucursal requiere que los gastos tengan sucursal/centro de costo; gastos centrales sin asignar se muestran como "Estructura central".

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| ebitda < 0 en el mes | critica |
| ebitda_pct cae > 5 pp vs promedio 3 meses | alta |

---

## FIN-06
### Resultado neto

**Pregunta que responde:** ¿Ganamos o perdimos plata en el período (después de todo)?  
**Definición:** EBITDA − amortizaciones ± resultado financiero ± otros resultados − impuesto a las ganancias.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `eerr.resultado_neto` |
| Unidad | moneda |
| Dirección | mayor_mejor |
| Agregación | aditivo |
| Grano mínimo | mes |
| Dimensiones | sucursal, centro_costo, eerr_linea |
| Filtros base | estado publicado, excluye cierre |
| Parámetros | `ajuste`=nominal\|real |
| Roles de fuente mínimos | contabilidad |
| Historia mínima | — |
| Relacionados | FIN-05 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select -sum(a.saldo) from core.fct_asiento_linea a join core.dim_cuenta_contable c using (cuenta_id)
where c.tipo in ('ingreso','costo','gasto') and a.estado='publicado' and not a.es_cierre
  and a.fecha_contable between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_asiento_linea.fecha_contable` | obligatoria |
| `fct_asiento_linea.saldo` | obligatoria |
| `fct_asiento_linea.cuenta_id` | obligatoria |
| `dim_cuenta_contable.codigo_estandar` | obligatoria |

**Casos borde y reglas:**

- {'Impuesto a las ganancias suele registrarse anual': 'mostrar resultado antes de impuestos por defecto en meses intermedios.'}

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| resultado_neto acumulado del ejercicio < 0 | alta |

---

## FIN-07
### Caja disponible

**Pregunta que responde:** ¿Cuánta plata tenemos hoy disponible?  
**Definición:** Suma de saldos al cierre del día de cuentas de tesorería con es_disponible = true (bancos, cajas, billeteras, FCI de rescate inmediato).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `tesoreria.caja_disponible` |
| Unidad | moneda |
| Dirección | mayor_mejor |
| Agregación | snapshot (no sumar entre fechas; usar último valor del período) |
| Grano mínimo | dia |
| Dimensiones | cuenta_tesoreria, tipo_cuenta, entidad, moneda |
| Filtros base | es_disponible |
| Parámetros | `moneda`=base\|<ISO>\|original, `fecha`=hoy por defecto |
| Roles de fuente mínimos | tesoreria |
| Historia mínima | — |
| Relacionados | FIN-08, FIN-09, FIN-16 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(s.saldo) from marts.fct_saldo_tesoreria_diario s
join core.dim_cuenta_tesoreria t using (cuenta_tesoreria_id)
where t.es_disponible and s.fecha = :fecha;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `dim_cuenta_tesoreria.es_disponible` | obligatoria |
| `fct_movimiento_tesoreria.fecha` | obligatoria |
| `fct_movimiento_tesoreria.importe` | obligatoria |
| `fct_movimiento_tesoreria.saldo_informado` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Cuentas en moneda extranjera se valúan al TC del día (tipo default del tenant); mostrar también en moneda original.
- Si un extracto está desactualizado (> 2 días hábiles) el saldo se marca "desactualizado" con la fecha real.
- Dinero en MP pendiente de liberar no es disponible; se informa aparte (FIN-17 / fct_liquidacion_pasarela).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| caja_disponible < caja_minima tenant | critica |
| caja_disponible < pagos comprometidos próximos 7 días | critica |

---

## FIN-08
### Flujo de caja (operativo, inversión, financiación)

**Pregunta que responde:** ¿Cuánta plata entró y salió y por qué?  
**Definición:** Suma de movimientos de tesorería por actividad, excluyendo transferencias internas.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `tesoreria.flujo_neto` |
| Unidad | moneda |
| Dirección | mayor_mejor |
| Agregación | aditivo |
| Grano mínimo | dia |
| Dimensiones | actividad, tipo, cuenta_tesoreria, contraparte |
| Filtros base | excluye transferencias internas |
| Parámetros | `ajuste`=nominal\|real |
| Roles de fuente mínimos | tesoreria |
| Historia mínima | — |
| Relacionados | FIN-07, FIN-09 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select actividad, tipo, sum(importe) as flujo
from core.fct_movimiento_tesoreria
where actividad <> 'interna' and fecha between :desde and :hasta
group by rollup(actividad, tipo);
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_movimiento_tesoreria.fecha` | obligatoria |
| `fct_movimiento_tesoreria.importe` | obligatoria |
| `fct_movimiento_tesoreria.tipo` | obligatoria |

**Casos borde y reglas:**

- Movimientos tipo 'otros' > 15 % del volumen → el KPI advierte "clasificación incompleta" (DQ-10).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| flujo operativo negativo 2 meses consecutivos | alta |

---

## FIN-09
### Burn rate y runway

**Pregunta que responde:** ¿Cuántos meses de caja nos quedan al ritmo actual?  
**Definición:** Burn = promedio mensual de flujo neto negativo (operativo + financiación de deuda) de los últimos 3 meses; runway = caja disponible / burn.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `tesoreria.burn_rate, tesoreria.runway_meses` |
| Unidad | moneda \| meses |
| Dirección | mayor_mejor (runway) |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | — |
| Filtros base | excluye transferencias internas, excluye aportes de socios |
| Parámetros | `ventana_meses`=3 |
| Roles de fuente mínimos | tesoreria |
| Historia mínima | ≥ 3 meses de historia |
| Relacionados | FIN-07, FIN-08 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
burn = -avg(flujo_neto_mensual) over últimos 3 meses cerrados (solo si < 0)
runway_meses = FIN-07 / nullif(burn, 0)   -- null si flujo positivo ("no aplica: el negocio genera caja")
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `dim_cuenta_tesoreria.es_disponible` | obligatoria |
| `fct_movimiento_tesoreria.fecha` | obligatoria |
| `fct_movimiento_tesoreria.importe` | obligatoria |
| `fct_movimiento_tesoreria.tipo` | obligatoria |
| `fct_movimiento_tesoreria.saldo_informado` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Estacionalidad fuerte (ej. aguinaldo en jun/dic) → usar ventana 6 meses si el tenant lo configura.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| runway_meses < 3 | critica |
| runway_meses < 6 | alta |

---

## FIN-10
### Cuentas por cobrar (total, vencida y % vencida)

**Pregunta que responde:** ¿Cuánto nos deben y cuánto está vencido?  
**Definición:** Saldo pendiente de documentos CxC a la fecha; vencido = saldo con fecha_vencimiento < fecha de corte.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `cxc.saldo_total, cxc.saldo_vencido, cxc.pct_vencido` |
| Unidad | moneda \| porcentaje |
| Dirección | menor_mejor |
| Agregación | snapshot |
| Grano mínimo | dia |
| Dimensiones | cliente, vendedor, sucursal, tramo_aging, tipo_cliente |
| Filtros base | estado in (pendiente, parcial) |
| Parámetros | `fecha`=hoy |
| Roles de fuente mínimos | cuentas_corrientes |
| Historia mínima | — |
| Relacionados | FIN-11, FIN-12, FIN-15 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(saldo) as cxc_total,
       sum(saldo) filter (where dias_vencido > 0) as cxc_vencida,
       sum(saldo) filter (where dias_vencido > 0) / nullif(sum(saldo),0) as pct_vencida
from marts.fct_saldo_cxc_diario where fecha = :fecha;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_documento_cxc.fecha_vencimiento` | obligatoria |
| `fct_documento_cxc.saldo_pendiente` | obligatoria |

**Casos borde y reglas:**

- Saldos a favor (NC sin aplicar, anticipos) restan; mostrar aparte "créditos a favor de clientes".
- Cheques/echeqs recibidos no depositados cuentan como cobrados (el riesgo va a FIN-16).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| pct_vencida > 20% | alta |
| un cliente concentra > 25% de la CxC vencida | media |

---

## FIN-11
### Aging de cuentas por cobrar

**Pregunta que responde:** ¿Cuánto de lo que nos deben tiene 0-30, 31-60, 61-90, >90 días de atraso?  
**Definición:** Distribución del saldo CxC por tramos de días vencidos.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `cxc.saldo_total (dimensión tramo_aging)` |
| Unidad | moneda |
| Dirección | menor_mejor (tramos altos) |
| Agregación | snapshot |
| Grano mínimo | dia |
| Dimensiones | tramo_aging, cliente, vendedor |
| Filtros base | — |
| Parámetros | `tramos`=configurables por tenant |
| Roles de fuente mínimos | cuentas_corrientes |
| Historia mínima | — |
| Relacionados | FIN-10 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
tramo_aging = case when dias_vencido <= 0 then 'a_vencer'
                   when dias_vencido <= 30 then '1_30'
                   when dias_vencido <= 60 then '31_60'
                   when dias_vencido <= 90 then '61_90'
                   else 'mas_90' end
select tramo_aging, sum(saldo) from marts.fct_saldo_cxc_diario where fecha=:fecha group by 1;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_documento_cxc.fecha_vencimiento` | obligatoria |
| `fct_documento_cxc.saldo_pendiente` | obligatoria |

**Casos borde y reglas:**

- Si no hay fecha de vencimiento se usa fecha_emision + condicion_pago_dias del cliente (marcar "vencimiento estimado").

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| saldo mas_90 > 10% de la CxC | alta |

---

## FIN-12
### DSO (días de cobro)

**Pregunta que responde:** ¿Cuántos días tardamos en promedio en cobrar?  
**Definición:** CxC promedio del período / ventas a crédito con impuesto indirecto del período × días del período.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `cxc.dso` |
| Unidad | dias |
| Dirección | menor_mejor |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | cliente, vendedor, tipo_cliente |
| Filtros base | opcional excluir ventas contado (condicion_pago_dias = 0) |
| Parámetros | `solo_credito`=True |
| Roles de fuente mínimos | cuentas_corrientes, facturacion |
| Historia mínima | — |
| Relacionados | FIN-14, FIN-15 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
dso = avg(cxc_total diario del período) / nullif(sum(importe_total*signo) ventas del período, 0) * dias_periodo
-- ventas = fct_comprobante venta emitido (con impuesto indirecto porque la CxC incluye impuesto indirecto)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_documento_cxc.saldo_pendiente` | obligatoria |
| `fct_comprobante.fecha_emision` | obligatoria |
| `fct_comprobante.importe_total` | obligatoria |
| `fct_comprobante.estado` | obligatoria |

**Casos borde y reglas:**

- En negocios mixtos (contado + cuenta corriente) calcular con `solo_credito=true` para no subestimar.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| dso > condicion_pago promedio + 15 días | alta |

---

## FIN-13
### Cuentas por pagar y DPO

**Pregunta que responde:** ¿Cuánto debemos a proveedores, cuánto vence pronto y en cuántos días pagamos?  
**Definición:** Saldo CxP a la fecha, vencido, a vencer en 7/30 días; DPO = CxP promedio / compras con impuesto indirecto × días.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `cxp.saldo_total, cxp.saldo_vencido, cxp.vence_7d, cxp.dpo` |
| Unidad | moneda \| dias |
| Dirección | neutral |
| Agregación | snapshot / calculado |
| Grano mínimo | dia |
| Dimensiones | proveedor, categoria_proveedor, tramo_aging |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | cuentas_corrientes, facturacion |
| Historia mínima | — |
| Relacionados | FIN-14, FIN-16 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(saldo) cxp_total,
       sum(saldo) filter (where dias_vencido > 0) cxp_vencida,
       sum(saldo) filter (where fecha_vencimiento between :fecha and :fecha + 7) vence_7d
from marts.fct_saldo_cxp_diario where fecha=:fecha;
dpo = avg(cxp_total diario) / nullif(sum(compras importe_total*signo), 0) * dias_periodo
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_documento_cxp.fecha_vencimiento` | obligatoria |
| `fct_documento_cxp.saldo_pendiente` | obligatoria |
| `fct_comprobante.circuito` | obligatoria |
| `fct_comprobante.fecha_emision` | obligatoria |
| `fct_comprobante.importe_total` | obligatoria |
| `fct_pago.fecha_pago` | opcional (habilita desgloses o mayor precisión) |
| `fct_pago.importe` | opcional (habilita desgloses o mayor precisión) |
| `dim_proveedor.categoria_proveedor` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Si solo hay documentos de compra sin pagos ni saldos (sin rol cuentas_corrientes) no se puede saber qué está pago → KPI no disponible.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| vence_7d > caja_disponible | critica |
| cxp_vencida > 15% del total | media |

---

## FIN-14
### Ciclo de conversión de caja

**Pregunta que responde:** ¿Cuántos días pasa la plata atrapada en el negocio?  
**Definición:** DSO + DIO − DPO.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `capital_trabajo.ciclo_caja` |
| Unidad | dias |
| Dirección | menor_mejor |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | — |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | cuentas_corrientes, inventario |
| Historia mínima | — |
| Relacionados | FIN-12, FIN-13, INV-04 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
ccc = FIN-12.dso + INV-04.dio - FIN-13.dpo
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_documento_cxc.saldo_pendiente` | obligatoria |
| `fct_documento_cxp.saldo_pendiente` | obligatoria |
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_stock_diario.costo_unitario` | obligatoria |

**Casos borde y reglas:**

- Si falta un componente se informa cuál y no se calcula.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| ccc aumenta > 15 días vs trimestre anterior | media |

---

## FIN-15
### Efectividad de cobranza (CEI)

**Pregunta que responde:** ¿Qué porcentaje de lo cobrable efectivamente cobramos en el período?  
**Definición:** (CxC inicial + ventas a crédito − CxC final) / (CxC inicial + ventas a crédito − CxC final corriente) × 100.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `cxc.cei` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | vendedor, tipo_cliente |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | cuentas_corrientes, facturacion |
| Historia mínima | — |
| Relacionados | FIN-10, FIN-12 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
cei = (cxc_ini + ventas_credito - cxc_fin) / nullif(cxc_ini + ventas_credito - cxc_fin_no_vencida, 0)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_documento_cxc.fecha_vencimiento` | obligatoria |
| `fct_documento_cxc.saldo_pendiente` | obligatoria |
| `fct_cobro.fecha_cobro` | obligatoria |
| `fct_cobro.importe` | obligatoria |
| `fct_comprobante.fecha_emision` | obligatoria |
| `fct_comprobante.importe_total` | obligatoria |

**Casos borde y reglas:**

- Meses con pocas facturas a crédito generan ruido; mostrar con volumen.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| cei < 80% | media |

---

## FIN-16
### Proyección de caja 7/30/60/90 días

**Pregunta que responde:** ¿Cuánta plata vamos a tener en las próximas semanas?  
**Definición:** Caja disponible hoy + cobros esperados (CxC por vencimiento ajustado por comportamiento histórico + liquidaciones pendientes de pasarelas) − pagos comprometidos (CxP por vencimiento + gastos recurrentes estimados).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `tesoreria.proyeccion (mart marts.fin__proyeccion_caja)` |
| Unidad | moneda |
| Dirección | mayor_mejor |
| Agregación | serie proyectada |
| Grano mínimo | dia |
| Dimensiones | componente (cobros, liquidaciones, pagos, recurrentes) |
| Filtros base | — |
| Parámetros | `horizonte_dias`=7\|30\|60\|90 |
| Roles de fuente mínimos | tesoreria |
| Historia mínima | — |
| Relacionados | FIN-07, FIN-13 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
proyeccion(d) = FIN-07(hoy)
  + Σ cxc.saldo × prob_cobro(tramo) con fecha_esperada = fecha_vencimiento + atraso_medio_cliente
  + Σ fct_liquidacion_pasarela.importe_neto where estado='aprobado' and fecha_acreditacion <= d
  - Σ cxp.saldo con fecha_vencimiento <= d
  - Σ recurrentes (sueldos, impuestos, alquiler: promedio 3 meses de fct_movimiento_tesoreria por tipo, en su día típico)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `dim_cuenta_tesoreria.es_disponible` | obligatoria |
| `fct_movimiento_tesoreria.fecha` | obligatoria |
| `fct_movimiento_tesoreria.importe` | obligatoria |
| `fct_movimiento_tesoreria.tipo` | opcional (habilita desgloses o mayor precisión) |
| `fct_documento_cxc.fecha_vencimiento` | opcional (habilita desgloses o mayor precisión) |
| `fct_documento_cxc.saldo_pendiente` | opcional (habilita desgloses o mayor precisión) |
| `fct_documento_cxp.fecha_vencimiento` | opcional (habilita desgloses o mayor precisión) |
| `fct_documento_cxp.saldo_pendiente` | opcional (habilita desgloses o mayor precisión) |
| `fct_liquidacion_pasarela.fecha_acreditacion` | opcional (habilita desgloses o mayor precisión) |
| `fct_liquidacion_pasarela.importe_neto` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- {'Es una estimación': 'el agente siempre la presenta como proyección con sus supuestos.'}

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| proyeccion < 0 en algún día de los próximos 30 | critica |

---

## FIN-17
### Costo de cobro (comisiones de pasarelas, marketplaces y financiación)

**Pregunta que responde:** ¿Cuánto nos cuesta cobrar lo que vendemos?  
**Definición:** (Comisiones de pasarelas + comisiones de canal + costo de cuotas sin interés + impuesto débitos/créditos) / venta bruta cobrada.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `cobros.costo_cobro_pct` |
| Unidad | porcentaje |
| Dirección | menor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | pasarela, medio_pago, cuotas, canal |
| Filtros base | — |
| Parámetros | `incluir_debcred`=False |
| Roles de fuente mínimos | pasarela_pagos |
| Historia mínima | — |
| Relacionados | VEN-09 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select (sum(comision) + sum(costo_financiacion)) / nullif(sum(importe_bruto),0)
from core.fct_liquidacion_pasarela where fecha_operacion between :desde and :hasta and estado not in ('rechazado');
-- + comision_canal de fct_pedido (marketplace) + impuesto_debcred de tesorería (opcional)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_liquidacion_pasarela.importe_bruto` | obligatoria |
| `fct_liquidacion_pasarela.comision` | obligatoria |
| `fct_liquidacion_pasarela.costo_financiacion` | opcional (habilita desgloses o mayor precisión) |
| `fct_liquidacion_pasarela.retenciones` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.comision_canal` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.costo_financiacion` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.medio_pago` | opcional (habilita desgloses o mayor precisión) |
| `fct_movimiento_tesoreria.tipo` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Retenciones de impuestos NO son costo (son pagos a cuenta); se informan aparte.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| costo_cobro_pct sube > 1 pp vs mes anterior | media |

---

## FIN-18
### Conciliación con registro fiscal oficial

**Pregunta que responde:** ¿Todo lo registrado ante la autoridad fiscal está en el sistema de gestión y viceversa?  
**Definición:** Cantidad e importe de documentos presentes en la fuente con rol registro_fiscal_oficial sin match en fct_comprobante (y al revés), comparando (clase, punto_emision, numero) o codigo_autorizacion_fiscal.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `control.conciliacion_fiscal` |
| Unidad | cantidad \| moneda |
| Dirección | menor_mejor (debe ser 0) |
| Agregación | aditivo |
| Grano mínimo | dia |
| Dimensiones | circuito, punto_emision, tipo_comprobante |
| Filtros base | — |
| Parámetros | `tolerancia_importe`=1 |
| Roles de fuente mínimos | facturacion, registro_fiscal_oficial |
| Historia mínima | — |
| Relacionados | FIN-01, FIN-21 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) filter (where e.comprobante_id is null) solo_registro_oficial,
       count(*) filter (where o.source_key is null) solo_gestion,
       sum(coalesce(o.importe_total,0) - coalesce(e.importe_total,0)) diferencia
from intermediate.int_comprobante_registro_oficial o
full join core.fct_comprobante e
  on o.tenant_id = e.tenant_id
 and coalesce(o.codigo_autorizacion_fiscal, o.clase||o.punto_emision||o.numero) = coalesce(e.codigo_autorizacion_fiscal, e.clase||e.punto_emision||e.numero)
where coalesce(o.fecha_emision, e.fecha_emision) between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_comprobante.circuito` | obligatoria |
| `fct_comprobante.clase` | obligatoria |
| `fct_comprobante.punto_emision` | obligatoria |
| `fct_comprobante.numero` | obligatoria |
| `fct_comprobante.fecha_emision` | obligatoria |
| `fct_comprobante.importe_total` | obligatoria |
| `fct_comprobante.codigo_autorizacion_fiscal` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Solo aplica si el país tiene registro oficial de documentos electrónicos y el tenant conectó esa fuente; si no, el KPI queda no_disponible.
- Documentos de compra que el sistema de gestión no registra (gastos menores) son esperables; permitir lista de identificadores fiscales excluidos.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| solo_registro_oficial > 0 en ventas | alta |
| compras en registro oficial no cargadas > 5% del importe | media |

---

## FIN-19
### Desvío vs presupuesto (EERR)

**Pregunta que responde:** ¿Cómo venimos contra el presupuesto en cada línea del resultado?  
**Definición:** Real − presupuesto por eerr_linea y período; % desvío = (real − ppto) / |ppto|.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `presupuesto.desvio_eerr` |
| Unidad | moneda \| porcentaje |
| Dirección | depende de la línea (ingresos mayor_mejor, gastos menor_mejor) |
| Agregación | aditivo (importes) / ratio (%) |
| Grano mínimo | mes |
| Dimensiones | eerr_linea, codigo_estandar, sucursal, version |
| Filtros base | version = 'original' por defecto |
| Parámetros | `version`=original\|reforecast_n |
| Roles de fuente mínimos | presupuesto, contabilidad o facturacion+ventas |
| Historia mínima | — |
| Relacionados | FIN-01, VEN-07 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select p.eerr_linea, r.real, p.importe as presupuesto, r.real - p.importe as desvio,
       (r.real - p.importe) / nullif(abs(p.importe),0) as desvio_pct
from core.fct_presupuesto p left join (EERR real por linea y mes) r using (periodo, eerr_linea)
where p.concepto = 'eerr_linea' and p.version = :version and p.periodo between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_presupuesto.importe` | obligatoria |
| `fct_presupuesto.eerr_linea` | obligatoria |
| `fct_asiento_linea.fecha_contable` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.saldo` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.cuenta_id` | obligatoria si se usa la variante **contable** |
| `dim_cuenta_contable.codigo_estandar` | obligatoria si se usa la variante **contable** |
| `fct_comprobante.circuito` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.clase` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.fecha_emision` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.importe_neto` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.estado` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.categoria_gasto` | obligatoria si se usa la variante **gestion** |
| `fct_pedido_linea.costo_total` | obligatoria si se usa la variante **gestion** |

Basta con que se cumpla **una** de las variantes: contable, gestion (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- Presupuesto en valores nominales vs inflación real distinta a la presupuestada → ofrecer desvío en términos reales con índice de precios.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| desvio_pct ventas < -10% o gastos > +10% | alta |

---

## FIN-20
### Punto de equilibrio

**Pregunta que responde:** ¿Cuánto necesitamos vender por mes para no perder plata?  
**Definición:** Costos fijos mensuales / margen de contribución %. Costos fijos = gastos_administracion + gastos_personal + parte fija de comercialización; margen de contribución = (ventas − CMV − gastos variables) / ventas.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `eerr.punto_equilibrio` |
| Unidad | moneda |
| Dirección | menor_mejor |
| Agregación | calculado |
| Grano mínimo | mes |
| Dimensiones | — |
| Filtros base | — |
| Parámetros | `ventana_meses`=3, `cuentas_variables`=configurable por tenant |
| Roles de fuente mínimos | contabilidad o facturacion+ventas |
| Historia mínima | — |
| Relacionados | FIN-05, VEN-24 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
margen_contribucion_pct = (ventas_netas - cmv - gastos_variables) / ventas_netas   -- promedio 3 meses
gastos_variables = comisiones + fletes + comisiones medios de pago + IIBB (cuentas 6.1.01, 6.1.02, 6.1.04, 6.1.05)
costos_fijos = gastos_operativos - gastos_variables
punto_equilibrio = costos_fijos / nullif(margen_contribucion_pct, 0)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_asiento_linea.fecha_contable` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.saldo` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.cuenta_id` | obligatoria si se usa la variante **contable** |
| `dim_cuenta_contable.codigo_estandar` | obligatoria si se usa la variante **contable** |
| `fct_comprobante.circuito` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.clase` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.fecha_emision` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.importe_neto` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.estado` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.categoria_gasto` | obligatoria si se usa la variante **gestion** |
| `fct_pedido_linea.costo_total` | obligatoria si se usa la variante **gestion** |

Basta con que se cumpla **una** de las variantes: contable, gestion (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- La clasificación fijo/variable es configurable; el agente menciona el supuesto.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| ventas_netas proyectadas del mes (VEN-24) < punto_equilibrio | alta |

---

## FIN-21
### Posición estimada de impuesto indirecto

**Pregunta que responde:** ¿Cuánto impuesto indirecto (valor agregado / ventas) vamos a tener que pagar este período?  
**Definición:** Impuesto indirecto de ventas (débito) − impuesto indirecto de compras (crédito) − retenciones/percepciones sufridas del período.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `impuestos.posicion_iva` |
| Unidad | moneda |
| Dirección | neutral |
| Agregación | aditivo |
| Grano mínimo | mes |
| Dimensiones | circuito |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | facturacion |
| Historia mínima | — |
| Relacionados | FIN-16, FIN-18 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(importe_impuesto*signo) filter (where circuito='venta')
     - sum(importe_impuesto*signo) filter (where circuito='compra')
from core.fct_comprobante where estado='emitido' and fecha_emision between :desde and :hasta;
-- menos retenciones/percepciones de impuesto indirecto sufridas (fct_cobro.importe_retenciones tipo impuesto indirecto ⚠, fct_liquidacion_pasarela.retenciones)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_comprobante.circuito` | obligatoria |
| `fct_comprobante.fecha_emision` | obligatoria |
| `fct_comprobante.estado` | obligatoria |
| `fct_comprobante.signo` | obligatoria |
| `fct_comprobante.importe_impuesto` | obligatoria |
| `fct_liquidacion_pasarela.retenciones` | opcional (habilita desgloses o mayor precisión) |
| `fct_cobro.importe_retenciones` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Es estimación de gestión, no reemplaza la declaración jurada; el agente lo aclara.
- Si el tenant está en un régimen simplificado sin impuesto indirecto discriminado, el KPI no aplica.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| posicion_iva > caja proyectada a fecha de vencimiento | alta |

---

## FIN-22
### Evolución real de gastos por categoría

**Pregunta que responde:** ¿Qué gastos crecen por encima de la inflación?  
**Definición:** Gasto por cuenta estándar / categoría en términos reales (índice de precios) y su variación vs mismo período anterior.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `eerr.gastos_operativos (ajuste='real')` |
| Unidad | moneda \| porcentaje |
| Dirección | menor_mejor |
| Agregación | aditivo / ratio |
| Grano mínimo | mes |
| Dimensiones | codigo_estandar, categoria_gasto, proveedor, centro_costo |
| Filtros base | — |
| Parámetros | `comparacion`=mes_anterior\|mismo_mes_anio_anterior\|promedio_3m |
| Roles de fuente mínimos | referencia_indice_precios, contabilidad o facturacion |
| Historia mínima | — |
| Relacionados | FIN-04 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
gasto_real = real_amount(gasto, fecha, periodo_base = mes actual)
var_real = gasto_real(periodo) / nullif(gasto_real(periodo_comparacion), 0) - 1
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `ref.indice_precios.indice` | obligatoria |
| `fct_asiento_linea.fecha_contable` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.saldo` | obligatoria si se usa la variante **contable** |
| `fct_asiento_linea.cuenta_id` | obligatoria si se usa la variante **contable** |
| `dim_cuenta_contable.codigo_estandar` | obligatoria si se usa la variante **contable** |
| `fct_comprobante.circuito` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.clase` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.fecha_emision` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.importe_neto` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.estado` | obligatoria si se usa la variante **gestion** |
| `fct_comprobante.categoria_gasto` | obligatoria si se usa la variante **gestion** |
| `fct_asiento_linea.centro_costo_id` | opcional (habilita desgloses o mayor precisión) |

Basta con que se cumpla **una** de las variantes: contable, gestion (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- índice de precios del último mes puede no estar publicado → se usa estimado y se marca.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| var_real > 15% en categoría con peso > 5% del gasto | media |

