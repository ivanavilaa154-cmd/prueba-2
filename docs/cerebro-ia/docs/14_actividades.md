# 14 — Actividades según el caso

> Generado por `tools/build_kpis.py` desde `actividades/src/actividades.yml`. No editar a mano.

Los KPIs **miden**; las alertas de KPI **avisan**; las **actividades** le dicen a una persona concreta **qué hacer hoy, con qué producto, en qué lugar**.
Cada actividad es una regla determinística (SQL/Python sobre `core` y `marts`, sin modelo de lenguaje) que recorre el negocio, detecta casos
y genera tareas en `ops.actividad` (docs/04 §4.7).

**Regla central: ninguna alerta sin acción.** Cada actividad tiene una **tabla de casos**: cada caso tiene una condición de detección y una o más
**acciones prescriptas**, cada una con responsable, plazo y criterio de cierre. El build rechaza un caso sin acción. Si una detección no encaja en ningún caso,
no se emite (se registra en `ops.actividad_descartes` para revisar la regla).

**Anatomía de una tarea** (lo que recibe el responsable):
1. Título claro ("Revisar góndola: Producto X en Sucursal Centro").
2. Evidencia en números (por qué se detectó).
3. Caso detectado y **acciones en orden**, cada una con plazo.
4. Impacto estimado en dinero (para priorizar).
5. Botones de resolución (valores permitidos por actividad) + comentario.

**Ciclo de vida:** `nueva` → `en_curso` → `resuelta` / `descartada` (con resolución obligatoria) · `vencida` si pasa el plazo sin resolver (escala al rol superior) ·
`cerrada_automatica` si la condición desaparece sola (ej. el producto volvió a venderse). Una sola tarea abierta por `clave_dedupe`.

**Aprendizaje:** por actividad y tenant se mide la **precisión** (resueltas con resolución "confirmada" / total cerradas). Si baja de 60 % durante 4 semanas,
se propone al operador endurecer parámetros; si supera 90 % con pocas detecciones, se propone relajarlos. Los parámetros se ajustan en `ops.tenant_config_kpi(<ACT>, …)`.

**Priorización:** `puntaje = impacto_estimado × urgencia` (urgencia: 3 crítica, 2 alta, 1 media, 0,5 baja). Cada responsable recibe su lista ordenada;
tope configurable de tareas por persona por día (default 15) para no saturar: el resto queda visible pero no se notifica.

**Configuración de negocio usada por las actividades** (por tenant, editable en la interfaz):
- `ops.politica_precio(alcance_tipo, alcance_valor, metodo, margen_objetivo_pct, margen_minimo_pct, base_costo, redondeo, tolerancia_pct)` — alcance: categoría, marca, proveedor o producto (gana el más específico).
- `ops.politica_producto(alcance_tipo, alcance_valor, dias_retiro_antes_vencimiento, cobertura_objetivo_dias, dias_seguridad, nivel_servicio)`.
- `ops.responsable(rol, sucursal_id, usuario, canal_notificacion)` — a quién le llega cada tarea.

## Índice

| ID | Actividad | Entidad | Frecuencia | Responsable principal | Casos |
|---|---|---|---|---|---|
| [ACT-01](#act-01) | Quiebre oculto (falta en góndola con stock en sistema) | producto × punto de venta (sucursal o depósito vendible) | diaria (06:00 hora local, sobre el día anterior) + opcional cada 2 h en horario operativo (versión intradía) | encargado_sucursal | 4 |
| [ACT-02](#act-02) | Pedido sugerido | proveedor (con líneas producto × depósito) | según los días de pedido de cada proveedor (`dim_proveedor.dias_pedido`); si no hay, diaria. Urgencias (caso C1) se evalúan todos los días. | comprador | 5 |
| [ACT-03](#act-03) | Rotación y productos que no se mueven | producto × depósito/sucursal | semanal (lunes) + mensual (revisión de surtido) | comercial | 4 |
| [ACT-04](#act-04) | Remarcación y margen según listas de proveedores | producto (y lista de precios / sucursal / canal) | al recibir una lista nueva de proveedor (evento) + diaria para erosión de margen + semanal para listas desactualizadas | comercial | 7 |
| [ACT-05](#act-05) | Promociones que no rindieron | promoción (con detalle por producto y sucursal) | día 3 de cada promoción activa (control temprano) + al finalizar + 14 días después (efecto posterior) | comercial | 6 |
| [ACT-06](#act-06) | Vencimientos | lote (producto × depósito × lote) | diaria (06:00) | encargado_sucursal | 5 |

---

## ACT-01
### Quiebre oculto (falta en góndola con stock en sistema)

**El caso de negocio:** Un producto que se vende todos los días deja de venderse aunque el sistema dice que hay stock. Probablemente no está exhibido (quedó en depósito, está mal ubicado, se dañó, se lo robaron o el stock del sistema está mal).

| Atributo | Valor |
|---|---|
| Entidad | producto × punto de venta (sucursal o depósito vendible) |
| Frecuencia | diaria (06:00 hora local, sobre el día anterior) + opcional cada 2 h en horario operativo (versión intradía) |
| Responsable principal | encargado_sucursal |
| Parámetros (por tenant) | `ventana_base_dias`=28, `pct_dias_con_venta_min`=0.8, `lambda_min`=1, `prob_umbral`=0.01, `actividad_local_min`=0.7, `variacion_precio_excluir`=0.15 |
| Impacto (para priorizar) | venta_perdida_estimada = λ × k × precio neto medio (y margen perdido = × margen %); se proyecta λ × precio por cada día adicional sin resolver. |
| KPIs relacionados | INV-06, INV-07, INV-13, INV-21 |

#### Detección

**Universo:** productos activos con venta regular en el punto de venta — vendió en ≥ 80 % de los días abiertos de las últimas 4 semanas (sin contar los días evaluados) y su venta media λ ≥ 1 unidad/día.

**Condiciones:**

- Días consecutivos sin venta k tal que la probabilidad de no vender por azar sea < 1 %: P = e^(−λ·k) < 0,01 (ej. λ = 2/día → k ≥ 3; λ = 5/día → k ≥ 1).
- El punto de venta estuvo abierto y con actividad normal esos días (tickets totales ≥ 70 % de su promedio del mismo día de semana).
- Stock disponible en sistema > 0 durante esos días en ese punto de venta.

**Exclusiones (no se genera tarea):**

- Stock en sistema = 0 → no es oculto; lo trata INV-06 / ACT-02.
- Terminó una promoción del producto en los 3 días previos (caída natural).
- Subió el precio de venta > 15 % en los últimos 7 días (se evalúa en ACT-04, caso C5).
- Producto `estacional_fuera_temporada`, `discontinuado` o con CV de demanda semanal > 1 (irregular).

**Versión intradía:** Con curva horaria del producto (share de venta por hora, 8 semanas): si a la hora h la venta acumulada del día = 0 y la esperada ≥ 4 unidades, se adelanta la detección.

**Cálculo de referencia:**

```sql
-- marts.act__quiebre_oculto (sobre marts.ven__venta_diaria_sku_punto y marts.fct_stock_diario_kpi)
with base as (
  select tenant_id, producto_id, punto_id,
         avg(unidades) filter (where dia_abierto)                           as lambda,
         avg((unidades > 0)::int) filter (where dia_abierto)                as pct_dias_con_venta,
         stddev(unidades) filter (where dia_abierto)                        as sigma
  from marts.ven__venta_diaria_sku_punto
  where fecha between :hoy - 35 and :hoy - 8
  group by 1,2,3),
racha as (   -- días consecutivos recientes sin venta, con local abierto y stock > 0
  select v.tenant_id, v.producto_id, v.punto_id, count(*) as k, min(s.stock_disponible) as stock_min
  from marts.ven__venta_diaria_sku_punto v
  join marts.fct_stock_diario_kpi s using (tenant_id, producto_id, fecha)   -- s.deposito del punto
  where v.fecha > coalesce((select max(fecha) from marts.ven__venta_diaria_sku_punto x
                            where x.producto_id = v.producto_id and x.punto_id = v.punto_id and x.unidades > 0), '1900-01-01')
    and v.dia_abierto and v.actividad_relativa >= :actividad_local_min and s.stock_disponible > 0
  group by 1,2,3)
select b.*, r.k, r.stock_min, exp(-b.lambda * r.k) as p_azar,
       b.lambda * r.k * precio_neto_prom as venta_perdida_estimada
from base b join racha r using (tenant_id, producto_id, punto_id)
where b.pct_dias_con_venta >= :pct_dias_con_venta_min and b.lambda >= :lambda_min
  and exp(-b.lambda * r.k) < :prob_umbral;
```

#### Casos y acciones (cada detección cae en un caso; cada caso prescribe acciones)

**ACT-01.C1 — Stock en depósito, no en exhibición**  
*Cuándo:* Se detecta el patrón y el punto de venta tiene depósito trasero o stock en otra ubicación del mismo punto (o no se puede distinguir la ubicación).  
*Prioridad:* alta (crítica si el producto es clase A)

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Ir a la góndola/exhibición y verificar si el producto está visible, con precio y en su lugar. | repositor | 2 h hábiles |
| 2 | Si no está: buscarlo en depósito y reponer la exhibición completa. | repositor | mismo día |
| 3 | Si no aparece en ningún lado: hacer conteo físico y registrar el ajuste de inventario con motivo 'faltante' (pasa al caso C3). | encargado_sucursal | mismo día |

*Cierre:* Se resuelve con la resolución elegida; se cierra automáticamente si el producto vuelve a venderse ≥ 50 % de λ en las 24 h siguientes.

**ACT-01.C2 — Producto exhibido pero sin venta (problema de exhibición o precio)**  
*Cuándo:* La tarea C1 se resolvió como "estaba exhibido" y la venta no se recupera en 48 h.  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Verificar que el precio de góndola coincida con el precio del sistema y que la etiqueta sea legible. | repositor | mismo día |
| 2 | Verificar ubicación (altura, frente, cantidad de frentes) contra el planograma o la ubicación anterior; restituirla. | encargado_sucursal | 24 h |
| 3 | Si hay un cambio de precio reciente, derivar a comercial para revisar (ACT-04 C5). | comercial | 48 h |

*Cierre:* Venta vuelve a ≥ 50 % de λ durante 2 días, o resolución manual.

**ACT-01.C3 — Stock fantasma confirmado (el sistema dice que hay y no hay)**  
*Cuándo:* Resolución de C1 = "no hay stock físico", o conteo físico < 50 % del stock de sistema.  
*Prioridad:* alta

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Registrar el ajuste de inventario por la diferencia contada (motivo 'faltante' o 'error_carga'). | encargado_sucursal | mismo día |
| 2 | Generar reposición urgente: incluir el producto en el próximo pedido sugerido del proveedor (ACT-02) o transferir desde otra sucursal con stock. | comprador | 24 h |
| 3 | Si el mismo producto/sucursal tiene 2 o más stock fantasma en 60 días: programar conteo cíclico de la categoría y revisar posible robo. | gerente_operaciones | 7 días |

*Cierre:* Ajuste registrado (se verifica por movimiento de stock tipo ajuste en la fecha) + pedido/transferencia creada.

**ACT-01.C4 — Producto dañado o vencido en exhibición**  
*Cuándo:* Resolución de C1 = "estaba dañado/vencido".  
*Prioridad:* alta

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Retirar las unidades de la exhibición y registrar merma con motivo 'rotura' o 'vencimiento'. | repositor | inmediato |
| 2 | Reponer con unidades en buen estado; si no hay, pedir reposición urgente. | encargado_sucursal | mismo día |
| 3 | Si es vencimiento: revisar el resto de los lotes del producto (dispara ACT-06). | encargado_sucursal | 24 h |

*Cierre:* Merma registrada.

**Resoluciones posibles:** `repuesto_desde_deposito`, `estaba_exhibido`, `no_hay_stock_fisico_ajustado`, `danado_o_vencido_retirado`, `precio_o_etiqueta_corregidos`, `falso_positivo`  
**Cuentan como detección confirmada (precisión):** `repuesto_desde_deposito`, `no_hay_stock_fisico_ajustado`, `danado_o_vencido_retirado`, `precio_o_etiqueta_corregidos`

**Ejemplo de tarea:** _Sucursal Centro — Producto X (clase A) vende 6 u/día y lleva 2 días sin ventas; el sistema indica 48 u. Venta perdida estimada: $ 23.400. Acción 1: verificar góndola antes de las 11:00._

**Requisitos de datos canónicos:**

| Columna canónica | Tipo |
|---|---|
| `fct_pedido.pedido_at` | obligatoria |
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_stock_diario.stock_disponible` | obligatoria |
| `fct_pedido.deposito_id` | obligatoria en variante **punto_por_deposito** |
| `fct_pedido.sucursal_id` | obligatoria en variante **punto_por_sucursal** |
| `dim_deposito.sucursal_id` | obligatoria en variante **punto_por_sucursal** |
| `fct_precio_venta.precio` | opcional |
| `dim_promocion.fecha_fin` | opcional |
| `dim_producto.estado_surtido` | opcional |
| `dim_producto.clasificacion_abc` | opcional |

---

## ACT-02
### Pedido sugerido

**El caso de negocio:** Saber qué comprarle a cada proveedor, cuánto y cuándo, para no quedarse sin stock ni sobrestockearse, respetando mínimos, bultos y vencimientos.

| Atributo | Valor |
|---|---|
| Entidad | proveedor (con líneas producto × depósito) |
| Frecuencia | según los días de pedido de cada proveedor (`dim_proveedor.dias_pedido`); si no hay, diaria. Urgencias (caso C1) se evalúan todos los días. |
| Responsable principal | comprador |
| Parámetros (por tenant) | `nivel_servicio_por_abc`={'A': 0.95, 'B': 0.9, 'C': 0.8}, `dias_revision_default`=7, `tope_cobertura_factor`=1.5, `factor_vida_util`=0.9 |
| Impacto (para priorizar) | importe del pedido; para C1 = venta perdida evitada (d × días hasta quiebre sin pedir × precio). |
| KPIs relacionados | INV-05, INV-06, INV-10, INV-15, INV-17 |

#### Detección

**Universo:** productos activos (`estado_surtido = 'activo'`) con `gestiona_stock` y proveedor principal asignado.

**Condiciones:**

- Demanda diaria d = VDP corregida por quiebres (marts.inv__demanda_sku); σ = desvío de la demanda diaria (28-90 días).
- Período a cubrir T = lead time + días hasta el próximo día de pedido del proveedor (revisión).
- Stock de seguridad SS = z(nivel de servicio) × σ × √(lead time); z por clase ABC: A 1,65 (95 %), B 1,28 (90 %), C 0,84 (80 %).
- Necesidad = d × T + SS − (stock disponible + en tránsito).
- Cantidad sugerida = redondeo hacia arriba a múltiplo de unidades_por_bulto de max(0, Necesidad).
- Tope por vencimiento (perecederos): cantidad ≤ d × (vida_util_dias − dias_retiro_antes_vencimiento) × 0,9 − stock disponible.
- Tope por sobrestock: la cobertura resultante no puede superar la cobertura objetivo × 1,5 (salvo compra de oportunidad aprobada).

**Exclusiones (no se genera tarea):**

- Productos `a_discontinuar` / `discontinuado` → cantidad 0 y se listan aparte para confirmar que no se repongan.
- Productos clase C con cobertura actual > 60 días.

**Cálculo de referencia:**

```sql
-- marts.act__pedido_sugerido
select p.proveedor_id, pr.producto_id, pr.deposito_id, d.vdp, d.sigma, lt.lead_time, rv.dias_revision,
       z(pr.clase_abc) * d.sigma * sqrt(lt.lead_time)                                         as ss,
       d.vdp * (lt.lead_time + rv.dias_revision) + ss - (s.stock_disponible + s.stock_en_transito) as necesidad,
       ceil(greatest(necesidad,0) / coalesce(pr.unidades_por_bulto,1)) * coalesce(pr.unidades_por_bulto,1) as cantidad,
       least(cantidad, tope_vencimiento, tope_cobertura)                                        as cantidad_final,
       cantidad_final * lpp.costo_neto                                                         as importe
from … ;  -- lead_time: parametro_reposicion → dim_proveedor.lead_time_dias_estandar → mediana real (INV-17)
```

#### Casos y acciones (cada detección cae en un caso; cada caso prescribe acciones)

**ACT-02.C1 — Quiebre inminente (urgente)**  
*Cuándo:* Cobertura actual (disponible + tránsito) / d < lead time del proveedor y el producto es clase A o B.  
*Prioridad:* critica

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Emitir hoy el pedido del producto aunque no sea día de pedido del proveedor (pedido urgente con las cantidades sugeridas). | comprador | mismo día |
| 2 | Si el proveedor no puede entregar a tiempo: transferir stock desde otra sucursal con cobertura > 2× objetivo (la tarea lista cuáles). | gerente_operaciones | 24 h |
| 3 | Si no hay alternativa: activar sustituto (producto de la misma categoría con stock) y avisar a ventas/sucursales. | comercial | 24 h |

*Cierre:* Existe orden de compra o transferencia creada para el producto con fecha ≥ detección.

**ACT-02.C2 — Pedido regular del proveedor**  
*Cuándo:* Es día de pedido del proveedor y hay ≥ 1 línea con cantidad_final > 0.  
*Prioridad:* alta

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Revisar el borrador de pedido (archivo adjunto con producto, stock, venta diaria, cobertura, cantidad sugerida, costo e importe). | comprador | mismo día |
| 2 | Aprobar o corregir cantidades (cada corrección pide motivo: 'promoción planificada', 'cambio de proveedor', 'otro'). | comprador | mismo día |
| 3 | Enviar el pedido al proveedor y cargar la orden de compra en el sistema de gestión. | comprador | mismo día |

*Cierre:* Orden de compra al proveedor creada en los 2 días siguientes; se compara lo pedido vs lo sugerido para aprendizaje.

**ACT-02.C3 — Pedido por debajo del mínimo del proveedor**  
*Cuándo:* Importe total sugerido < `monto_minimo_pedido` del proveedor.  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Completar el mínimo adelantando productos del mismo proveedor con menor cobertura (la tarea propone cuáles, sin superar tope de cobertura). | comprador | mismo día |
| 2 | Si no conviene completar: posponer al próximo día de pedido, salvo que haya líneas del caso C1. | comprador | mismo día |

*Cierre:* Pedido emitido con el mínimo o pospuesto con motivo.

**ACT-02.C4 — Compra limitada por vencimiento**  
*Cuándo:* Producto perecedero donde el tope por vida útil recortó la cantidad sugerida.  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Pedir solo la cantidad tope indicada y aumentar la frecuencia de pedido de este producto (la tarea sugiere cada cuántos días). | comprador | mismo día |
| 2 | Negociar con el proveedor entregas más chicas o más frecuentes si el bulto obliga a comprar de más. | comprador | 30 días |

*Cierre:* Pedido emitido con cantidad ≤ tope.

**ACT-02.C5 — Productos a discontinuar con reposición pendiente**  
*Cuándo:* Producto `a_discontinuar` con órdenes abiertas o incluido por error en la última compra.  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Cancelar o reducir la orden de compra abierta del producto. | comprador | 48 h |
| 2 | Derivar el stock remanente a liquidación (ACT-03 C1). | comercial | 7 días |

*Cierre:* Orden cancelada/ajustada o confirmación de que se mantiene.

**Resoluciones posibles:** `pedido_emitido_como_sugerido`, `pedido_emitido_corregido`, `transferencia_realizada`, `sustituto_activado`, `pospuesto`, `descartado`  
**Cuentan como detección confirmada (precisión):** `pedido_emitido_como_sugerido`, `pedido_emitido_corregido`, `transferencia_realizada`, `sustituto_activado`

**Ejemplo de tarea:** _Proveedor Y — pedido del martes: 34 productos, $ 1.240.000. 3 productos en quiebre inminente (cobertura 2 días, entrega en 4). Adjunto: pedido_sugerido_Y.csv._

**Requisitos de datos canónicos:**

| Columna canónica | Tipo |
|---|---|
| `fct_stock_diario.stock_disponible` | obligatoria |
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `dim_producto.proveedor_principal_id` | obligatoria |
| `parametro_reposicion.lead_time_dias` | obligatoria en variante **lead_time_parametro** |
| `dim_proveedor.lead_time_dias_estandar` | obligatoria en variante **lead_time_proveedor** |
| `fct_orden_compra.fecha_emision` | obligatoria en variante **lead_time_historico** |
| `fct_recepcion.fecha_recepcion` | obligatoria en variante **lead_time_historico** |
| `fct_stock_diario.stock_en_transito` | opcional |
| `dim_producto.unidades_por_bulto` | opcional |
| `dim_producto.vida_util_dias` | opcional |
| `dim_producto.estado_surtido` | opcional |
| `dim_proveedor.dias_pedido` | opcional |
| `dim_proveedor.monto_minimo_pedido` | opcional |
| `fct_lista_precio_proveedor.costo_neto` | opcional |

---

## ACT-03
### Rotación y productos que no se mueven

**El caso de negocio:** Detectar mercadería que inmoviliza plata (no se vende o se vende muy lento) y decidir qué hacer con cada producto antes de que se desvalorice.

| Atributo | Valor |
|---|---|
| Entidad | producto × depósito/sucursal |
| Frecuencia | semanal (lunes) + mensual (revisión de surtido) |
| Responsable principal | comercial |
| Parámetros (por tenant) | `dias_sin_movimiento`=60, `factor_lento`=2, `caida_pct`=0.5, `antiguedad_min_dias`=60, `valor_minimo_para_tarea`=configurable (default 1 % del inventario de la sucursal o importe fijo) |
| Impacto (para priorizar) | capital inmovilizado = valor del stock a costo (C1/C2), o valor del exceso sobre la cobertura objetivo (C2); C4 = venta recuperable en la sucursal destino. |
| KPIs relacionados | INV-03, INV-09, INV-10, INV-11, INV-12 |

#### Detección

**Universo:** productos con stock físico > 0, dados de alta hace más de 60 días.

**Condiciones:**

- Sin movimiento: 0 ventas en los últimos N días (default 60) con stock > 0.
- Rotación lenta: cobertura (stock / VDP) > 2 × cobertura objetivo de su categoría.
- En caída: VDP de las últimas 4 semanas < 50 % de la VDP de las 12 semanas previas, sin quiebre que lo explique.
- Desbalance entre sucursales: el mismo producto sin venta en una sucursal y con cobertura < objetivo en otra.

**Cálculo de referencia:**

```sql
-- marts.act__rotacion: una fila por producto × punto con segmento asignado (primer caso que aplica en orden C4, C1, C2, C3)
select producto_id, punto_id, stock_fisico, valor_stock, dias_sin_venta, vdp, cobertura_dias, vdp_4s, vdp_12s_previas,
       case when … end as caso
from marts.fct_stock_diario_kpi join marts.inv__demanda_sku … where fecha = :hoy;
```

#### Casos y acciones (cada detección cae en un caso; cada caso prescribe acciones)

**ACT-03.C1 — Sin movimiento**  
*Cuándo:* 0 ventas en los últimos 60 días con stock > 0.  
*Prioridad:* alta si valor a costo ≥ umbral; media en otro caso

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Bloquear la reposición del producto (marcar 'a_discontinuar' o poner cantidad 0 en el pedido sugerido). | comprador | 48 h |
| 2 | Si el proveedor acepta devolución o cambio: gestionar la devolución. | comprador | 15 días |
| 3 | Si no: lanzar liquidación con el descuento sugerido (el mayor que respeta el margen mínimo o, si es necesario, llega a costo) y exhibición destacada; se crea la promoción y se evalúa con ACT-05. | comercial | 7 días |
| 4 | Si a los 30 días de liquidación sigue sin venderse: decidir baja/donación y registrar merma. | gerente_general | 30 días |

*Cierre:* Se cierra al vender ≥ 80 % del stock, al registrar la devolución/baja, o por decisión documentada de mantenerlo.

**ACT-03.C2 — Rotación lenta (sobrestock)**  
*Cuándo:* Cobertura > 2 × objetivo de la categoría, con ventas > 0.  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Suspender compras del producto hasta que la cobertura vuelva al objetivo (se refleja en el pedido sugerido). | comprador | 48 h |
| 2 | Mejorar exhibición (punta de góndola, cercanía a caja) o incluirlo en una promoción cruzada con un producto de alta rotación. | comercial | 7 días |
| 3 | Revisar el tamaño de compra y el bulto con el proveedor para las próximas compras. | comprador | 30 días |

*Cierre:* Cobertura ≤ 1,2 × objetivo o decisión documentada.

**ACT-03.C3 — Producto en caída**  
*Cuándo:* VDP últimas 4 semanas < 50 % de las 12 previas, sin quiebre ni cambio de temporada.  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Verificar si hubo cambio de precio propio o de la competencia, de ubicación o de calidad (la tarea muestra el historial de precio y de ubicación si existe). | comercial | 7 días |
| 2 | Ajustar el pedido sugerido a la nueva demanda (se aplica automáticamente) y reducir el stock de seguridad. | comprador | próximo pedido |
| 3 | Si la caída persiste 8 semanas: evaluar reemplazo del producto en el surtido. | comercial | 60 días |

*Cierre:* Recuperación de VDP ≥ 80 % de la previa o decisión documentada.

**ACT-03.C4 — Desbalance entre sucursales**  
*Cuándo:* Sin venta ≥ 30 días en una sucursal con stock, mientras otra sucursal del tenant tiene cobertura < objetivo del mismo producto.  
*Prioridad:* alta

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Transferir la cantidad sugerida (mínimo entre el stock sobrante del origen y la necesidad del destino) a la sucursal que sí lo vende. | gerente_operaciones | 7 días |
| 2 | Registrar la transferencia en el sistema de gestión para que el stock refleje la nueva ubicación. | encargado_sucursal | al despachar |

*Cierre:* Movimiento de transferencia registrado entre esas sucursales.

**Resoluciones posibles:** `reposicion_bloqueada`, `devuelto_a_proveedor`, `liquidacion_lanzada`, `transferido`, `baja_registrada`, `se_mantiene_justificado`, `falso_positivo`  
**Cuentan como detección confirmada (precisión):** `reposicion_bloqueada`, `devuelto_a_proveedor`, `liquidacion_lanzada`, `transferido`, `baja_registrada`

**Ejemplo de tarea:** _142 productos sin movimiento hace 60+ días inmovilizan $ 3.850.000 a costo. Top 10 adjunto con acción sugerida; 12 se pueden transferir a Sucursal Norte, donde sí se venden._

**Requisitos de datos canónicos:**

| Columna canónica | Tipo |
|---|---|
| `fct_stock_diario.stock_fisico` | obligatoria |
| `fct_stock_diario.costo_unitario` | obligatoria |
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_pedido.fecha_pedido` | obligatoria |
| `dim_producto.fecha_alta` | opcional |
| `dim_producto.categoria_n1` | opcional |
| `dim_proveedor.acepta_devolucion_vencidos` | opcional |
| `fct_precio_venta.precio` | opcional |
| `dim_deposito.sucursal_id` | opcional |

---

## ACT-04
### Remarcación y margen según listas de proveedores

**El caso de negocio:** Cuando un proveedor cambia su lista de precios hay que actualizar los precios de venta para sostener el margen; también detectar productos que ya venden por debajo del margen mínimo o del costo.

| Atributo | Valor |
|---|---|
| Entidad | producto (y lista de precios / sucursal / canal) |
| Frecuencia | al recibir una lista nueva de proveedor (evento) + diaria para erosión de margen + semanal para listas desactualizadas |
| Responsable principal | comercial |
| Parámetros (por tenant) | `tolerancia_pct`=0.02, `dias_lista_desactualizada`=45, `variacion_costo_alerta_pct`=0.03, `politica_stock_existente`=reposicion (remarcar todo el stock) \| promedio (remarcar al ingresar la nueva mercadería) |
| Impacto (para priorizar) | margen mensual recuperado = VDP × 30 × (margen unitario objetivo − margen unitario actual); C3 = pérdida mensual evitada. |
| KPIs relacionados | FIN-03, VEN-08, VEN-27 |

#### Detección

**Universo:** productos activos con precio de venta vigente.

**Condiciones:**

- Costo de reposición vigente = costo_neto de la lista vigente del proveedor principal (o último costo de compra si no hay lista).
- Margen actual = (precio − costo_reposicion) / precio (método margen_sobre_precio) o markup = (precio − costo) / costo, según ops.politica_precio.
- Precio sugerido = costo_reposicion / (1 − margen_objetivo) (o costo × (1 + markup_objetivo)), redondeado con la regla de redondeo del tenant (terminaciones y múltiplos).
- Se sugiere remarcar solo si |precio sugerido − precio actual| / precio actual > tolerancia (default 2 %).

**Exclusiones (no se genera tarea):**

- Precio promocional vigente (se evalúa al terminar la promoción).
- Productos con precio fijado por contrato o precio sugerido de fabricante bloqueado (marca en ops.politica_precio).

**Cálculo de referencia:**

```sql
-- marts.act__remarcacion
select pv.producto_id, pv.lista_precios, pv.sucursal_id, pv.precio as precio_actual,
       lpp.costo_neto as costo_nuevo, lpp_ant.costo_neto as costo_anterior,
       (lpp.costo_neto / nullif(lpp_ant.costo_neto,0) - 1) as var_costo,
       (pv.precio - lpp.costo_neto) / nullif(pv.precio,0) as margen_actual,
       redondear(lpp.costo_neto / (1 - pol.margen_objetivo_pct/100), pol.redondeo) as precio_sugerido,
       vdp * 30 * (precio_sugerido - pv.precio) as impacto_mensual_venta
from core.fct_precio_venta pv
join core.fct_lista_precio_proveedor lpp on lpp.es_vigente and …
left join lateral (anterior vigencia) lpp_ant on true
join ops.politica_precio pol on (alcance más específico)
where pv.vigente_hasta is null and not pv.es_promocional;
```

#### Casos y acciones (cada detección cae en un caso; cada caso prescribe acciones)

**ACT-04.C1 — Aumento de lista del proveedor**  
*Cuándo:* Llegó una lista con costo_neto mayor al anterior en > 3 % para uno o más productos.  
*Prioridad:* alta (crítica si el aumento promedio de la lista > 10 %)

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Revisar el archivo de remarcación: precio actual, costo nuevo, margen actual, precio sugerido, margen resultante e impacto (ordenado por impacto). | comercial | 24 h |
| 2 | Aprobar o ajustar los precios sugeridos (ajuste manual pide motivo) y cargarlos en el sistema de gestión con la fecha de vigencia. | comercial | 48 h |
| 3 | Imprimir y cambiar las etiquetas de góndola de los productos remarcados (listado por sucursal y pasillo/categoría). | encargado_sucursal | 24 h desde la carga |
| 4 | Si la política es 'promedio': programar la remarcación para el día de ingreso de la mercadería al nuevo costo (la tarea queda en espera de esa recepción). | comercial | al recibir |

*Cierre:* Existe un nuevo precio vigente ≥ precio sugerido × (1 − tolerancia) para los productos aprobados; las etiquetas se confirman con la resolución.

**ACT-04.C2 — Erosión de margen (sin lista nueva)**  
*Cuándo:* Margen actual con costo de reposición < margen mínimo de la política, aunque no haya llegado una lista (ej. subió el costo por compra reciente).  
*Prioridad:* alta

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Remarcar al precio sugerido o documentar por qué se sostiene el precio (competencia, producto gancho). | comercial | 48 h |
| 2 | Si se sostiene el precio: marcar el producto como 'margen bajo aceptado' con fecha de revisión (se re-evalúa en 30 días). | comercial | 48 h |

*Cierre:* Nuevo precio cargado o excepción registrada con fecha de revisión.

**ACT-04.C3 — Venta por debajo del costo**  
*Cuándo:* Precio de venta vigente (sin promoción) < costo de reposición.  
*Prioridad:* critica

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Corregir el precio hoy (puede ser error de carga) o confirmar que es una decisión comercial. | comercial | mismo día |
| 2 | Si fue error de carga: revisar otros productos cargados en la misma actualización (la tarea los lista). | comercial | 24 h |

*Cierre:* Precio ≥ costo o excepción aprobada por gerente_general.

**ACT-04.C4 — Baja de costo del proveedor**  
*Cuándo:* Lista con costo_neto menor al anterior en > 3 %.  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Decidir: trasladar la baja al precio (más competitivo) o sostener el precio y ganar margen. La tarea muestra ambos escenarios con su impacto. | comercial | 7 días |
| 2 | Aprovechar la baja para aumentar la compra si el producto es clase A con buena rotación (ajuste del pedido sugerido). | comprador | próximo pedido |

*Cierre:* Decisión registrada.

**ACT-04.C5 — Aumento de precio que frenó la venta**  
*Cuándo:* Tras una remarcación > 15 %, la VDP de las 2 semanas siguientes cayó > 40 % vs las 4 previas (sin quiebre).  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Revisar el precio contra la competencia y el precio de productos sustitutos; ajustar si quedó fuera de mercado. | comercial | 7 días |
| 2 | Si el margen lo permite, bajar al margen objetivo mínimo; si no, evaluar reemplazar el producto (ACT-03 C3). | comercial | 14 días |

*Cierre:* Nuevo precio o decisión documentada.

**ACT-04.C6 — Lista de proveedor desactualizada**  
*Cuándo:* El proveedor no envía lista hace más de 45 días y su última compra fue a un costo > 3 % del costo de lista (o el índice de precios subió > 5 % desde la última lista).  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Pedir al proveedor la lista de precios vigente y cargarla (o subir el archivo para que se procese automáticamente). | comprador | 7 días |

*Cierre:* Nueva lista cargada para ese proveedor.

**ACT-04.C7 — Precios inconsistentes entre sucursales o canales**  
*Cuándo:* El mismo producto tiene precios distintos entre sucursales/canales por encima de la diferencia permitida por la política.  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Unificar los precios según la política (o documentar la diferencia intencional por canal). | comercial | 7 días |

*Cierre:* Diferencia dentro de la política o excepción registrada.

**Resoluciones posibles:** `remarcado_como_sugerido`, `remarcado_ajustado`, `se_mantiene_precio_justificado`, `error_de_carga_corregido`, `lista_solicitada`, `etiquetas_cambiadas`, `falso_positivo`  
**Cuentan como detección confirmada (precisión):** `remarcado_como_sugerido`, `remarcado_ajustado`, `error_de_carga_corregido`, `lista_solicitada`, `etiquetas_cambiadas`

**Ejemplo de tarea:** _Llegó la lista del Proveedor Z con +8,4 % promedio en 212 productos. Si no se remarca, el margen de la categoría cae de 32 % a 26 % (−$ 410.000/mes). Archivo de remarcación y etiquetas por sucursal adjuntos._

**Requisitos de datos canónicos:**

| Columna canónica | Tipo |
|---|---|
| `fct_lista_precio_proveedor.costo_neto` | obligatoria |
| `fct_lista_precio_proveedor.fecha_vigencia_desde` | obligatoria |
| `fct_precio_venta.precio` | obligatoria |
| `fct_precio_venta.vigente_desde` | obligatoria |
| `fct_precio_venta.precio_final` | opcional |
| `fct_precio_venta.sucursal_id` | opcional |
| `fct_precio_venta.canal_id` | opcional |
| `fct_pedido_linea.cantidad` | opcional |
| `fct_orden_compra_linea.precio_unitario` | opcional |
| `ref.indice_precios.indice` | opcional |

---

## ACT-05
### Promociones que no rindieron

**El caso de negocio:** Saber si cada promoción generó venta y margen adicionales o si solo regaló margen, y cortarla o corregirla a tiempo.

| Atributo | Valor |
|---|---|
| Entidad | promoción (con detalle por producto y sucursal) |
| Frecuencia | día 3 de cada promoción activa (control temprano) + al finalizar + 14 días después (efecto posterior) |
| Responsable principal | comercial |
| Parámetros (por tenant) | `semanas_base`=6, `roi_minimo`=0, `lift_minimo_esperado_por_mecanica`={'descuento_pct': 0.3, 'precio_especial': 0.3, 'nxm': 0.5, 'segunda_unidad': 0.4, 'combo': 0.2, 'cupon': 0.1}, `dia_control_temprano`=3 |
| Impacto (para priorizar) | margen incremental neto (negativo = plata perdida); en control temprano, pérdida proyectada al fin de la promoción. |
| KPIs relacionados | VEN-08, VEN-18, VEN-26, MKT-07 |

#### Detección

**Universo:** promociones con fecha de inicio ≤ hoy y al menos un producto vinculado.

**Condiciones:**

- Línea base (sin promo) por producto × sucursal = venta diaria media del mismo día de semana en las 6 semanas previas, ajustada por la tendencia de la sucursal (grupo de control: productos de la misma categoría no promocionados).
- Incremento de unidades = unidades en promo − línea base; lift = unidades promo / línea base − 1.
- Margen incremental = margen bruto en promo − margen bruto de la línea base − costo de comunicación + aporte del proveedor.
- Canibalización = caída de venta de productos de la misma categoría no promocionados vs su línea base.
- Efecto posterior = caída de venta del producto en las 2 semanas siguientes vs línea base (compra adelantada).
- ROI = margen incremental neto (con canibalización y efecto posterior) / costo de la promoción (descuento otorgado + comunicación − aporte proveedor).
- Tráfico: variación de tickets de la sucursal y del ticket medio en los tickets que incluyeron el producto promocionado.

**Cálculo de referencia:**

```sql
-- marts.act__promociones: una fila por promoción (y detalle producto × sucursal)
select pr.promocion_id, pr.mecanica, pr.objetivo, unidades_promo, unidades_base, lift, venta_incremental,
       margen_promo, margen_base, margen_incremental, canibalizacion, efecto_posterior, costo_promocion, roi,
       quiebre_durante_promo_pct, var_tickets, var_ticket_medio, caso
from core.dim_promocion pr join … ;
```

#### Casos y acciones (cada detección cae en un caso; cada caso prescribe acciones)

**ACT-05.C1 — Promoción en curso que no despega (control temprano)**  
*Cuándo:* En el día 3, lift < 50 % del lift mínimo esperado para su mecánica y no hubo quiebre de stock del producto.  
*Prioridad:* alta

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Verificar ejecución en el punto de venta: cartel de promoción visible, precio promocional cargado en caja, producto exhibido (checklist por sucursal). | encargado_sucursal | 24 h |
| 2 | Si la ejecución está bien: reforzar comunicación o cambiar mecánica; si no hay margen para eso, cortar la promoción antes de su fin. | comercial | 48 h |

*Cierre:* Checklist completo + decisión (seguir, reforzar, cortar).

**ACT-05.C2 — Quiebre durante la promoción**  
*Cuándo:* Stock disponible = 0 en ≥ 20 % de los días × sucursales de la promoción.  
*Prioridad:* alta

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Reponer de inmediato (pedido urgente o transferencia) o suspender la comunicación en las sucursales sin stock. | comprador | mismo día |
| 2 | Para próximas promociones: calcular el stock previo con el lift esperado (se agrega automáticamente al pedido sugerido cuando la promoción está 'planificada'). | comprador | próxima promoción |

*Cierre:* Stock repuesto o comunicación suspendida.

**ACT-05.C3 — Vendió más pero perdió margen**  
*Cuándo:* Al finalizar, venta incremental > 0 pero margen incremental neto < 0.  
*Prioridad:* alta

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | No repetir con el mismo descuento: la ficha sugiere el descuento máximo que deja margen incremental ≥ 0 con el lift observado. | comercial | antes de la próxima planificación |
| 2 | Negociar aporte del proveedor para repetirla (el monto necesario para que el ROI sea ≥ 0 está en la ficha). | comprador | 30 días |

*Cierre:* Ficha revisada y decisión registrada (no repetir / repetir con cambios / repetir con aporte).

**ACT-05.C4 — No movió la venta**  
*Cuándo:* Al finalizar, lift < 10 %.  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Descartar esta mecánica para este producto/categoría; la ficha propone la mecánica con mejor resultado histórico en la categoría. | comercial | antes de la próxima planificación |

*Cierre:* Decisión registrada.

**ACT-05.C5 — Solo canibalizó o adelantó compras**  
*Cuándo:* Lift > 0 pero la venta incremental neta (con canibalización y efecto posterior) ≤ 0.  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Evitar promocionar productos con sustitutos directos del mismo margen; preferir promociones cruzadas o de categoría. | comercial | próxima planificación |
| 2 | Si el objetivo era tráfico: validar con la variación de tickets; si no subió, no repetir. | comercial | próxima planificación |

*Cierre:* Decisión registrada.

**ACT-05.C6 — Promoción que rindió (para replicar)**  
*Cuándo:* ROI ≥ umbral y margen incremental neto > 0.  
*Prioridad:* baja

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Agregar a la biblioteca de promociones exitosas y evaluar replicarla en otras sucursales/canales o en productos similares. | comercial | 30 días |

*Cierre:* Registrada en la biblioteca.

**Resoluciones posibles:** `ejecucion_corregida`, `reforzada`, `cortada_anticipadamente`, `no_repetir`, `repetir_con_cambios`, `repetir_con_aporte_proveedor`, `replicar`, `falso_positivo`  
**Cuentan como detección confirmada (precisión):** `ejecucion_corregida`, `reforzada`, `cortada_anticipadamente`, `no_repetir`, `repetir_con_cambios`, `repetir_con_aporte_proveedor`, `replicar`

**Ejemplo de tarea:** _Promo '2x1 Categoría Q' (terminó ayer): +38 % unidades, pero margen incremental −$ 186.000 y 40 % de la suba canibalizó a productos de la misma categoría. No repetir con 2x1; con 3x2 el margen incremental estimado sería +$ 22.000._

**Requisitos de datos canónicos:**

| Columna canónica | Tipo |
|---|---|
| `dim_promocion.fecha_inicio` | obligatoria |
| `dim_promocion.fecha_fin` | obligatoria |
| `fct_promocion_producto.producto_id` | obligatoria |
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_pedido_linea.importe_neto` | obligatoria |
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido_linea.promocion_id` | opcional |
| `fct_pedido_linea.costo_total` | opcional |
| `dim_promocion.aporte_proveedor_monto` | opcional |
| `dim_promocion.costo_comunicacion` | opcional |
| `dim_promocion.campana_id` | opcional |
| `fct_stock_diario.stock_disponible` | opcional |
| `fct_pedido.sucursal_id` | opcional |

---

## ACT-06
### Vencimientos

**El caso de negocio:** Evitar que la mercadería se venza en góndola o en depósito, retirar a tiempo lo que ya no se puede vender y recuperar valor antes de perderlo.

| Atributo | Valor |
|---|---|
| Entidad | lote (producto × depósito × lote) |
| Frecuencia | diaria (06:00) |
| Responsable principal | encargado_sucursal |
| Parámetros (por tenant) | `dias_retiro_default`=0, `ventana_alerta_dias`=30, `elasticidad_default`=-2, `descuento_maximo_pct`=0.5 |
| Impacto (para priorizar) | valor a costo en riesgo (y margen si se vende a tiempo); C1 = valor a registrar como merma. |
| KPIs relacionados | INV-14, INV-20 |

#### Detección

**Universo:** lotes con cantidad > 0 y fecha de vencimiento conocida (foto por lote o estimación FEFO desde recepciones).

**Condiciones:**

- Días a vencer = fecha_vencimiento − hoy; fecha límite de venta = fecha_vencimiento − dias_retiro_antes_vencimiento.
- Consumo FEFO: para cada lote, la venta esperada antes de su fecha límite = VDP del producto en ese depósito × días hasta la fecha límite, restando lo que consumen antes los lotes que vencen primero.
- Unidades en riesgo = max(0, cantidad del lote − venta esperada disponible para ese lote).
- Velocidad necesaria = cantidad / días hasta fecha límite; multiplicador = velocidad necesaria / VDP.

**Cálculo de referencia:**

```sql
-- marts.act__vencimientos
select l.producto_id, l.deposito_id, l.lote, l.fecha_vencimiento, l.cantidad, l.costo_unitario,
       l.fecha_vencimiento - :hoy as dias_a_vencer,
       greatest(0, l.cantidad - greatest(0, d.vdp * (fecha_limite - :hoy) - consumo_lotes_previos)) as unidades_en_riesgo,
       unidades_en_riesgo * l.costo_unitario as valor_en_riesgo,
       (l.cantidad / nullif(fecha_limite - :hoy,0)) / nullif(d.vdp,0) as multiplicador_necesario
from core.fct_stock_lote l join marts.inv__demanda_sku d using (tenant_id, producto_id)
where l.fecha = :hoy and l.cantidad > 0;
```

#### Casos y acciones (cada detección cae en un caso; cada caso prescribe acciones)

**ACT-06.C1 — Vencido o pasado de la fecha límite de venta**  
*Cuándo:* dias_a_vencer ≤ 0, o hoy > fecha límite de venta.  
*Prioridad:* critica

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Retirar HOY todas las unidades del lote de la exhibición y separarlas en depósito identificadas. | repositor | inmediato |
| 2 | Si el proveedor acepta devolución de vencidos y está dentro del plazo de aviso: gestionar la devolución o nota de crédito. | comprador | según dias_aviso_devolucion del proveedor |
| 3 | Si no: registrar la merma con motivo 'vencimiento' y disponer según la normativa aplicable. | encargado_sucursal | 24 h |

*Cierre:* Movimiento de merma o devolución a proveedor registrado por la cantidad del lote.

**ACT-06.C2 — Vence pronto y no llega a venderse a precio normal**  
*Cuándo:* Unidades en riesgo > 0 y días hasta fecha límite ≤ 30 (o el umbral de su categoría); multiplicador necesario entre 1,2 y 4.  
*Prioridad:* alta (crítica si faltan ≤ 7 días)

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Aplicar el descuento sugerido para acelerar la venta (calculado con la elasticidad e del producto o la default: descuento = 1 − multiplicador^(1/e); con e = −2 y multiplicador 2 → 29 %; acotado al descuento máximo y nunca por debajo del costo salvo en C3), con cartel de 'consumo preferente'. | comercial | 24 h |
| 2 | Ubicar el lote al frente de la exhibición (FEFO) y verificar que no haya lotes más nuevos adelante. | repositor | mismo día |
| 3 | Re-evaluar en 3 días: si la velocidad no alcanza, profundizar descuento o pasar al caso C3. | comercial | 3 días |

*Cierre:* Unidades en riesgo = 0 (vendidas) o pasa a C1/C3.

**ACT-06.C3 — Vence pronto y ni con descuento llega**  
*Cuándo:* Multiplicador necesario > 4, o C2 sin mejora al re-evaluar.  
*Prioridad:* alta

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Transferir las unidades a la sucursal/canal donde el producto rota más rápido (la tarea indica destino y cantidad que sí llega a venderse). | gerente_operaciones | 48 h |
| 2 | Si el proveedor acepta cambio por vencimiento próximo: solicitarlo. | comprador | 48 h |
| 3 | Si nada de lo anterior: donar antes del vencimiento o liquidar a costo en canal alternativo. | gerente_general | antes de la fecha límite |

*Cierre:* Transferencia, cambio, donación o venta registrada.

**ACT-06.C4 — Sobrecompra de perecederos (causa raíz)**  
*Cuándo:* El mismo producto generó casos C1-C3 en 2 o más lotes en 90 días.  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Reducir la cantidad por pedido y aumentar la frecuencia (el tope por vida útil del pedido sugerido pasa a ser obligatorio para este producto). | comprador | próximo pedido |
| 2 | Revisar con el proveedor la vida útil con la que entrega (lotes que llegan con poca vida remanente). | comprador | 30 días |

*Cierre:* Parámetro de compra ajustado y registrado.

**ACT-06.C5 — Lote sin fecha de vencimiento cargada**  
*Cuándo:* Producto perecedero con recepción en los últimos 30 días sin fecha_vencimiento.  
*Prioridad:* media

| # | Acción | Responsable | Plazo |
|---|---|---|---|
| 1 | Cargar la fecha de vencimiento del lote recibido (sin ese dato no se puede alertar). | encargado_sucursal | 48 h |

*Cierre:* Fecha de vencimiento cargada.

**Resoluciones posibles:** `retirado_y_mermado`, `devuelto_a_proveedor`, `descuento_aplicado_y_vendido`, `transferido`, `donado`, `cambio_por_proveedor`, `fecha_cargada`, `falso_positivo`  
**Cuentan como detección confirmada (precisión):** `retirado_y_mermado`, `devuelto_a_proveedor`, `descuento_aplicado_y_vendido`, `transferido`, `donado`, `cambio_por_proveedor`, `fecha_cargada`

**Ejemplo de tarea:** _Sucursal Sur — Lote L-2231 de Producto W: 64 unidades vencen en 9 días; al ritmo actual se venden 27. En riesgo: 37 u ($ 55.500 a costo). Acción: 25 % de descuento hoy y ubicar al frente; revisar el viernes._

**Requisitos de datos canónicos:**

| Columna canónica | Tipo |
|---|---|
| `fct_pedido_linea.producto_id` | obligatoria |
| `fct_pedido_linea.cantidad` | obligatoria |
| `fct_stock_lote.fecha_vencimiento` | obligatoria en variante **stock_por_lote** |
| `fct_stock_lote.cantidad` | obligatoria en variante **stock_por_lote** |
| `fct_recepcion.fecha_vencimiento` | obligatoria en variante **recepciones_con_vencimiento** |
| `fct_recepcion.cantidad_recibida` | obligatoria en variante **recepciones_con_vencimiento** |
| `fct_stock_diario.stock_fisico` | obligatoria en variante **recepciones_con_vencimiento** |
| `dim_producto.dias_retiro_antes_vencimiento` | opcional |
| `dim_producto.es_perecedero` | opcional |
| `dim_proveedor.acepta_devolucion_vencidos` | opcional |
| `dim_proveedor.dias_aviso_devolucion` | opcional |
| `fct_stock_lote.costo_unitario` | opcional |

