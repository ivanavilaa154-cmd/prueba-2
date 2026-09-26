# 11 — KPIs de Logística

> Generado por `tools/build_kpis.py` desde `kpis/src/logistica.yml`. No editar a mano.
> Los KPIs se calculan **solo** sobre el modelo canónico (docs/04). Cada ficha declara qué columnas canónicas necesita; qué sistema las aporta lo define el `mapping.yml` de cada fuente (docs/05).

Cubre preparación, despacho, entrega, calidad de entrega, costos, backlog y performance por transportista.
**Base:** `fct_envio` (un envío por pedido o por bulto-grupo), `fct_evento_envio`, `fct_preparacion`.
**Tiempos:** se miden en **horas hábiles** o **días hábiles** (`ref.fecha_tenant.es_habil` + horario operativo del tenant, default L-V 9-18)
salvo que el KPI diga "corridos". Corte de despacho configurable (default 14:00: pedidos confirmados después del corte cuentan desde el día hábil siguiente).
Envíos `modalidad = 'retiro_en_tienda'` y `es_devolucion = true` se excluyen salvo en KPIs específicos (LOG-18).
Envíos con `es_controlable = false` (preparados y despachados por un tercero) se excluyen de LOG-02, LOG-03, LOG-15, LOG-16 (no controlables) y se reportan aparte en entrega.

## Índice

| ID | KPI | Unidad | Dirección | Roles mínimos |
|---|---|---|---|---|
| [LOG-01](#log-01) | Envíos despachados | cantidad | mayor_mejor | logistica |
| [LOG-02](#log-02) | Tiempo de preparación | horas | menor_mejor | logistica |
| [LOG-03](#log-03) | Despacho a tiempo | porcentaje | mayor_mejor | logistica |
| [LOG-04](#log-04) | Lead time total de entrega | dias | menor_mejor | logistica |
| [LOG-05](#log-05) | Tiempo de tránsito | dias | menor_mejor | logistica |
| [LOG-06](#log-06) | Entregas a tiempo (OTD) | porcentaje | mayor_mejor | logistica |
| [LOG-07](#log-07) | OTIF (a tiempo y completo) | porcentaje | mayor_mejor | logistica, ventas |
| [LOG-08](#log-08) | Entrega en primer intento | porcentaje | mayor_mejor | logistica |
| [LOG-09](#log-09) | Envíos fallidos / devueltos a origen | porcentaje | menor_mejor | logistica |
| [LOG-10](#log-10) | Envíos extraviados o siniestrados | porcentaje \| moneda | menor_mejor | logistica, ventas |
| [LOG-11](#log-11) | Costo de envío por pedido | moneda | menor_mejor | logistica |
| [LOG-12](#log-12) | Costo logístico sobre venta | porcentaje | menor_mejor | logistica, ventas |
| [LOG-13](#log-13) | Subsidio de envío | moneda \| porcentaje | menor_mejor | logistica |
| [LOG-14](#log-14) | Backlog de despacho | cantidad | menor_mejor | logistica, ventas |
| [LOG-15](#log-15) | Precisión de preparación (picking) | porcentaje | mayor_mejor | logistica o ventas |
| [LOG-16](#log-16) | Productividad de preparación | unidades/hora | mayor_mejor | logistica |
| [LOG-17](#log-17) | Scorecard de transportistas | varias | mayor_mejor | logistica |
| [LOG-18](#log-18) | Logística inversa | porcentaje \| moneda \| dias | menor_mejor | logistica |
| [LOG-19](#log-19) | Distribución geográfica de envíos | varias | neutral | logistica |

---

## LOG-01
### Envíos despachados

**Pregunta que responde:** ¿Cuántos pedidos despachamos?  
**Definición:** Cantidad de envíos con despacho_at en el período.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.despachados` |
| Unidad | cantidad |
| Dirección | mayor_mejor |
| Agregación | aditivo |
| Grano mínimo | dia |
| Dimensiones | transportista, modalidad, deposito_origen, zona_destino, region_destino, canal |
| Filtros base | no devolución |
| Parámetros | — |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-14 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) from core.fct_envio where not es_devolucion and local_date(despacho_at) between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.despacho_at` | obligatoria |
| `fct_envio.estado` | obligatoria |

**Casos borde y reglas:**

- 

---

## LOG-02
### Tiempo de preparación

**Pregunta que responde:** ¿Cuánto tardamos desde que se confirma el pedido hasta que está listo para despachar?  
**Definición:** Mediana y P90 de horas hábiles entre pedido_at (ajustado al corte) y listo_despacho_at.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.horas_preparacion_p50, envios.horas_preparacion_p90` |
| Unidad | horas |
| Dirección | menor_mejor |
| Agregación | percentil |
| Grano mínimo | dia |
| Dimensiones | deposito_origen, canal, dia_semana, franja_horaria_pedido |
| Filtros base | excluye envíos no controlables |
| Parámetros | `corte_hora`=14:00, `unidad`=horas_habiles\|horas_corridas |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-03, LOG-16 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select percentile_cont(0.5) within group (order by horas_habiles(pedido_at_ajustado, listo_despacho_at)),
       percentile_cont(0.9) within group (order by horas_habiles(pedido_at_ajustado, listo_despacho_at))
from core.fct_envio where es_controlable and modalidad <> 'retiro_en_tienda'
  and listo_despacho_at is not null and local_date(listo_despacho_at) between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.pedido_at` | obligatoria |
| `fct_envio.listo_despacho_at` | obligatoria si se usa la variante **con_listo_despacho** |
| `fct_envio.despacho_at` | obligatoria si se usa la variante **solo_despacho** |
| `fct_preparacion.inicio_at` | opcional (habilita desgloses o mayor precisión) |
| `fct_preparacion.fin_at` | opcional (habilita desgloses o mayor precisión) |

Basta con que se cumpla **una** de las variantes: con_listo_despacho, solo_despacho (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- Si no hay listo_despacho_at se usa despacho_at (se informa "preparación + espera de colecta").

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| p90 > 24 horas hábiles | media |

---

## LOG-03
### Despacho a tiempo

**Pregunta que responde:** ¿Qué porcentaje de pedidos despachamos dentro del plazo comprometido?  
**Definición:** Envíos con despacho_at ≤ fecha_limite_despacho / envíos cuyo límite cayó en el período (incluye los aún no despachados con límite vencido como fuera de término).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.despacho_a_tiempo_pct` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | deposito_origen, canal, modalidad |
| Filtros base | excluye envíos no controlables, excluye cancelados |
| Parámetros | `sla_horas`=tenant (default 24 hábiles) |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-02, LOG-14 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) filter (where despacho_at <= fecha_limite_despacho)::numeric / nullif(count(*),0)
from core.fct_envio where es_controlable and modalidad <> 'retiro_en_tienda' and not es_devolucion
  and local_date(fecha_limite_despacho) between :desde and :hasta and estado <> 'cancelado';
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.despacho_at` | obligatoria |
| `fct_envio.fecha_limite_despacho` | obligatoria |
| `fct_envio.estado` | obligatoria |

**Casos borde y reglas:**

- marketplace mide "despachos demorados" para reputación con su propio límite: usar estimated_handling_limit.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| despacho_a_tiempo < 95% | alta |
| canal marketplace < 97% (riesgo reputación) | alta |

---

## LOG-04
### Lead time total de entrega

**Pregunta que responde:** ¿Cuántos días tarda el cliente en recibir su pedido desde que compra?  
**Definición:** Mediana y P90 de días hábiles entre pedido_at y entrega_at, envíos entregados en el período.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.lead_time_p50, envios.lead_time_p90` |
| Unidad | dias |
| Dirección | menor_mejor |
| Agregación | percentil |
| Grano mínimo | dia |
| Dimensiones | transportista, modalidad, zona_destino, region_destino, canal |
| Filtros base | entregados |
| Parámetros | `unidad`=dias_habiles\|dias_corridos |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-05, LOG-06 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select percentile_cont(0.5) within group (order by dias_habiles(pedido_at, entrega_at)) from core.fct_envio where estado='entregado' and local_date(entrega_at) between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.pedido_at` | obligatoria |
| `fct_envio.entrega_at` | obligatoria |
| `fct_envio.estado` | obligatoria |
| `fct_envio.zona_destino` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Sin entrega_at (flota propia sin registro) → KPI no disponible para ese transportista.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| p50 de una zona sube > 1 día vs mes anterior | media |

---

## LOG-05
### Tiempo de tránsito

**Pregunta que responde:** ¿Cuánto tarda el transportista desde que retira hasta que entrega?  
**Definición:** Mediana y P90 de días hábiles entre despacho_at y entrega_at.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.transito_p50, envios.transito_p90` |
| Unidad | dias |
| Dirección | menor_mejor |
| Agregación | percentil |
| Grano mínimo | dia |
| Dimensiones | transportista, servicio, zona_destino, region_destino |
| Filtros base | entregados |
| Parámetros | — |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-17 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select percentile_cont(0.5) within group (order by dias_habiles(despacho_at, entrega_at)) from core.fct_envio where estado='entregado' and local_date(entrega_at) between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.despacho_at` | obligatoria |
| `fct_envio.entrega_at` | obligatoria |
| `fct_envio.estado` | obligatoria |
| `fct_envio.zona_destino` | opcional (habilita desgloses o mayor precisión) |
| `fct_evento_envio.evento_at` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| transportista con p90 > SLA contratado por zona | media |

---

## LOG-06
### Entregas a tiempo (OTD)

**Pregunta que responde:** ¿Qué porcentaje de pedidos llegó en la fecha prometida al cliente?  
**Definición:** Envíos entregados con local_date(entrega_at) ≤ fecha_promesa / envíos con fecha_promesa en el período (los no entregados con promesa vencida cuentan como tarde).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.otd_pct` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | transportista, modalidad, zona_destino, canal, deposito_origen |
| Filtros base | con fecha_promesa, excluye cancelados |
| Parámetros | — |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-07 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) filter (where estado='entregado' and local_date(entrega_at) <= fecha_promesa)::numeric / nullif(count(*),0)
from core.fct_envio where not es_devolucion and estado <> 'cancelado' and fecha_promesa between :desde and least(:hasta, current_date - 1);
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.entrega_at` | obligatoria |
| `fct_envio.fecha_promesa` | obligatoria |
| `fct_envio.estado` | obligatoria |

**Casos borde y reglas:**

- Cuando la promesa es un rango se usa el límite superior.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| otd < 90% | alta |

---

## LOG-07
### OTIF (a tiempo y completo)

**Pregunta que responde:** ¿Qué porcentaje de pedidos llegó a tiempo, completo y sin error?  
**Definición:** Pedidos entregados a tiempo (LOG-06) con todas sus líneas completas (fill 100 %) y sin devolución por error_preparacion / danado_transporte / pedidos con promesa en el período.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.otif_pct` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | canal, transportista, deposito_origen, cliente (B2B) |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | logistica, ventas |
| Historia mínima | — |
| Relacionados | LOG-06, INV-08 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
otif = count(pedidos where a_tiempo and completo and not reclamo_logistico) / count(pedidos con promesa en periodo)
completo = Σ cantidad_entregada >= Σ cantidad (fct_pedido_linea)
reclamo_logistico = exists fct_devolucion motivo in ('error_preparacion','danado_transporte','no_entregado')
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.entrega_at` | obligatoria |
| `fct_envio.fecha_promesa` | obligatoria |
| `fct_envio.estado` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_pedido_linea.cantidad_entregada` | obligatoria |
| `fct_devolucion.motivo` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| otif < 90% | alta |

---

## LOG-08
### Entrega en primer intento

**Pregunta que responde:** ¿Qué porcentaje de envíos se entrega en la primera visita?  
**Definición:** Envíos entregados con cantidad_intentos = 1 / envíos entregados + fallidos del período.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.primer_intento_pct` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | transportista, zona_destino, region_destino |
| Filtros base | domicilio (excluye retiro en sucursal) |
| Parámetros | — |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-09 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) filter (where estado='entregado' and cantidad_intentos <= 1)::numeric / nullif(count(*) filter (where estado in ('entregado','devuelto_origen')),0) from core.fct_envio where local_date(coalesce(entrega_at, _actualizado_at)) between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.estado` | obligatoria |
| `fct_envio.cantidad_intentos` | obligatoria si se usa la variante **intentos** |
| `fct_evento_envio.evento_at` | obligatoria si se usa la variante **eventos** |
| `fct_evento_envio.estado` | obligatoria si se usa la variante **eventos** |

Basta con que se cumpla **una** de las variantes: intentos, eventos (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| primer_intento < 85% | media |

---

## LOG-09
### Envíos fallidos / devueltos a origen

**Pregunta que responde:** ¿Qué porcentaje de envíos no llega al cliente?  
**Definición:** Envíos en estado devuelto_origen / envíos finalizados (entregado + devuelto_origen + extraviado) del período, con desglose de motivo.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.fallidos_pct` |
| Unidad | porcentaje |
| Dirección | menor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | transportista, motivo_no_entrega, zona_destino, canal |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-08, LOG-10 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) filter (where estado='devuelto_origen')::numeric / nullif(count(*) filter (where estado in ('entregado','devuelto_origen','extraviado_danado')),0) from core.fct_envio where local_date(_actualizado_at) between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.estado` | obligatoria |
| `fct_envio.motivo_no_entrega` | opcional (habilita desgloses o mayor precisión) |
| `fct_envio.finalizado_at` | opcional (habilita desgloses o mayor precisión) |
| `fct_evento_envio.evento_at` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Usar fecha del evento final (fct_evento_envio) cuando exista, no _actualizado_at.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| fallidos > 3% | alta |

---

## LOG-10
### Envíos extraviados o siniestrados

**Pregunta que responde:** ¿Cuántos envíos se pierden o llegan rotos?  
**Definición:** Envíos extraviado_danado + devoluciones por danado_transporte / envíos despachados; valor a costo de lo perdido.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.siniestros_pct, envios.valor_siniestros` |
| Unidad | porcentaje \| moneda |
| Dirección | menor_mejor |
| Agregación | ratio / aditivo |
| Grano mínimo | mes |
| Dimensiones | transportista, zona_destino |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | logistica, ventas |
| Historia mínima | — |
| Relacionados | LOG-09, LOG-17 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
tasa = (count(envios extraviado_danado) + count(devoluciones motivo danado_transporte)) / count(despachados)
valor = Σ costo_mercaderia de esos pedidos
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.estado` | obligatoria |
| `fct_envio.despacho_at` | obligatoria |
| `fct_pedido_linea.costo_total` | obligatoria |
| `fct_devolucion.motivo` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Siniestros reclamables al transportista: informar monto a reclamar si el tenant carga seguro/declarado.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| siniestros > 0.5% | alta |

---

## LOG-11
### Costo de envío por pedido

**Pregunta que responde:** ¿Cuánto nos cuesta en promedio enviar un pedido?  
**Definición:** Σ costo_envio / envíos despachados (también por kg).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.costo_por_envio, envios.costo_por_kg` |
| Unidad | moneda |
| Dirección | menor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | transportista, zona_destino, modalidad, canal |
| Filtros base | no devolución |
| Parámetros | `ajuste`=real por defecto |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-12, LOG-13 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(costo_envio)/nullif(count(*),0), sum(costo_envio)/nullif(sum(coalesce(peso_volumetrico_kg, peso_kg)),0) from core.fct_envio where not es_devolucion and local_date(despacho_at) between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.costo_envio` | obligatoria |
| `fct_envio.despacho_at` | obligatoria |
| `fct_envio.zona_destino` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Costos estimados por tarifa se marcan; al llegar la factura del transportista se reemplazan.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| costo real por envío sube > 10% vs mes anterior | media |

---

## LOG-12
### Costo logístico sobre venta

**Pregunta que responde:** ¿Qué porcentaje de lo que vendemos se va en logística?  
**Definición:** (Σ costo_envio − Σ importe_envio_cobrado + costo de preparación opcional) / venta neta de los pedidos despachados.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.costo_logistico_pct` |
| Unidad | porcentaje |
| Dirección | menor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | canal, transportista, zona_destino, categoria |
| Filtros base | — |
| Parámetros | `neto_de_cobrado`=True, `incluir_devoluciones`=True |
| Roles de fuente mínimos | logistica, ventas |
| Historia mínima | — |
| Relacionados | VEN-09, LOG-13 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select (sum(e.costo_envio) - sum(coalesce(e.importe_envio_cobrado,0))) / nullif(sum(p.importe_neto),0)
from core.fct_envio e join core.fct_pedido p using (pedido_id)
where not e.es_devolucion and local_date(e.despacho_at) between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.costo_envio` | obligatoria |
| `fct_pedido.importe_neto` | obligatoria |
| `fct_pedido.importe_envio_cobrado` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- incluir_devoluciones suma el costo de envíos es_devolucion (logística inversa).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| costo_logistico_pct > umbral tenant (default 8%) | alta |

---

## LOG-13
### Subsidio de envío

**Pregunta que responde:** ¿Cuánto ponemos de nuestro bolsillo en envíos gratis?  
**Definición:** Σ (costo_envio − importe_envio_cobrado) donde costo > cobrado; % de envíos con envío gratis.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.subsidio, envios.pct_envio_gratis` |
| Unidad | moneda \| porcentaje |
| Dirección | menor_mejor |
| Agregación | aditivo / ratio |
| Grano mínimo | dia |
| Dimensiones | canal, zona_destino, rango_ticket |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-12 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(greatest(costo_envio - coalesce(importe_envio_cobrado,0),0)), avg((coalesce(importe_envio_cobrado,0)=0)::int) from core.fct_envio where not es_devolucion and local_date(despacho_at) between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.costo_envio` | obligatoria |
| `fct_pedido.importe_envio_cobrado` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

---

## LOG-14
### Backlog de despacho

**Pregunta que responde:** ¿Cuántos pedidos están pendientes de despachar y cuántos están atrasados?  
**Definición:** Pedidos válidos confirmados sin despacho_at (estado pendiente/en_preparacion/listo_para_despachar) a la fecha; atrasados = fecha_limite_despacho < ahora; antigüedad en horas hábiles.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.backlog, envios.backlog_atrasado` |
| Unidad | cantidad |
| Dirección | menor_mejor |
| Agregación | snapshot |
| Grano mínimo | hora |
| Dimensiones | deposito_origen, canal, modalidad |
| Filtros base | excluye envíos no controlables |
| Parámetros | — |
| Roles de fuente mínimos | logistica, ventas |
| Historia mínima | — |
| Relacionados | LOG-03, VEN-17 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select count(*) backlog, count(*) filter (where fecha_limite_despacho < now()) atrasados,
       max(horas_habiles(pedido_at, now())) antiguedad_max
from core.fct_envio where despacho_at is null and estado in ('pendiente','en_preparacion','listo_para_despachar');
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.pedido_at` | obligatoria |
| `fct_envio.despacho_at` | obligatoria |
| `fct_envio.fecha_limite_despacho` | obligatoria |
| `fct_envio.estado` | obligatoria |
| `fct_pedido.estado` | obligatoria |
| `fct_pedido.fecha_confirmacion` | obligatoria |

**Casos borde y reglas:**

- Pedidos confirmados sin envío creado se agregan desde fct_pedido (estado confirmado, sin envío) como backlog "sin preparar".

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| atrasados > 0 en marketplace | critica |
| backlog > 1.5× promedio de despachos diarios | alta |

---

## LOG-15
### Precisión de preparación (picking)

**Pregunta que responde:** ¿Qué porcentaje de pedidos preparamos sin errores?  
**Definición:** 1 − (pedidos con error de preparación / pedidos preparados). Error = línea con error registrada en preparación o devolución motivo error_preparacion.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.precision_picking_pct` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | semana |
| Dimensiones | deposito, operario, categoria |
| Filtros base | excluye envíos no controlables |
| Parámetros | — |
| Roles de fuente mínimos | logistica o ventas |
| Historia mínima | — |
| Relacionados | VEN-16 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
1 - count(distinct pedido_id where lineas_con_error > 0 or devolucion.motivo = 'error_preparacion') / count(distinct pedidos preparados)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_preparacion.lineas_con_error` | obligatoria si se usa la variante **registro_preparacion** |
| `fct_devolucion.motivo` | obligatoria si se usa la variante **devoluciones** |

Basta con que se cumpla **una** de las variantes: registro_preparacion, devoluciones (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| precision < 99% | media |

---

## LOG-16
### Productividad de preparación

**Pregunta que responde:** ¿Cuántas unidades/pedidos preparamos por hora de trabajo?  
**Definición:** Unidades (o líneas o pedidos) preparadas / horas de preparación registradas.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `preparacion.unidades_por_hora` |
| Unidad | unidades/hora |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | deposito, operario, franja_horaria |
| Filtros base | — |
| Parámetros | `medida`=unidades\|lineas\|pedidos |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-02 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(unidades) / nullif(sum(extract(epoch from fin_at - inicio_at))/3600,0) from core.fct_preparacion where local_date(fin_at) between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_preparacion.inicio_at` | obligatoria |
| `fct_preparacion.fin_at` | obligatoria |

**Casos borde y reglas:**

- Sin inicio_at el KPI no está disponible.

---

## LOG-17
### Scorecard de transportistas

**Pregunta que responde:** ¿Qué transportista funciona mejor y a qué costo?  
**Definición:** Vista por transportista × zona con envíos, costo por envío, tránsito P50/P90, OTD, primer intento, fallidos y siniestros.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `view transportistas_scorecard` |
| Unidad | varias |
| Dirección | mayor_mejor |
| Agregación | vista |
| Grano mínimo | mes |
| Dimensiones | transportista, servicio, zona_destino |
| Filtros base | mínimo 30 envíos por celda para mostrar |
| Parámetros | — |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-05, LOG-06, LOG-11 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
vista compuesta LOG-01, LOG-11, LOG-05, LOG-06, LOG-08, LOG-09, LOG-10 con dimensiones transportista y zona_destino
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.despacho_at` | obligatoria |
| `fct_envio.entrega_at` | obligatoria |
| `fct_envio.fecha_promesa` | obligatoria |
| `fct_envio.estado` | obligatoria |
| `fct_envio.costo_envio` | obligatoria |
| `fct_envio.cantidad_intentos` | opcional (habilita desgloses o mayor precisión) |
| `fct_envio.zona_destino` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| transportista peor en OTD y más caro en una zona con > 100 envíos/mes → sugerir revisión | media |

---

## LOG-18
### Logística inversa

**Pregunta que responde:** ¿Cuántas devoluciones físicas gestionamos y cuánto cuestan?  
**Definición:** Envíos es_devolucion / envíos despachados; costo de envíos de devolución; tiempo desde solicitud hasta recepción en depósito.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.logistica_inversa_pct, envios.costo_inversa, devoluciones.dias_recepcion` |
| Unidad | porcentaje \| moneda \| dias |
| Dirección | menor_mejor |
| Agregación | ratio / aditivo / mediana |
| Grano mínimo | mes |
| Dimensiones | canal, transportista, motivo |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | VEN-16 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
tasa = count(envios es_devolucion) / count(envios despachados)
costo = Σ costo_envio where es_devolucion
tiempo = median(fct_devolucion.fecha_recepcion - fecha_solicitud)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.es_devolucion` | obligatoria |
| `fct_envio.costo_envio` | obligatoria |
| `fct_envio.estado` | obligatoria |
| `fct_devolucion.fecha_solicitud` | opcional (habilita desgloses o mayor precisión) |
| `fct_devolucion.fecha_recepcion` | opcional (habilita desgloses o mayor precisión) |
| `fct_devolucion.motivo` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

---

## LOG-19
### Distribución geográfica de envíos

**Pregunta que responde:** ¿A dónde enviamos y cómo nos va en cada zona?  
**Definición:** Envíos, % del total, costo promedio y lead time por region/zona.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `envios.despachados (dimensiones geográficas)` |
| Unidad | varias |
| Dirección | neutral |
| Agregación | vista |
| Grano mínimo | mes |
| Dimensiones | region_destino, zona_destino, localidad_destino |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | logistica |
| Historia mínima | — |
| Relacionados | LOG-17 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
vista agregada de fct_envio por region_destino / zona_destino con LOG-01, LOG-11, LOG-04
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_envio.costo_envio` | obligatoria |
| `fct_envio.despacho_at` | obligatoria |
| `fct_envio.entrega_at` | obligatoria |
| `fct_envio.zona_destino` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

