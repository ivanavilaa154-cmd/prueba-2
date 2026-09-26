# 15 — Gestión: procesos, objetivos y seguimiento en tiempo real

> Generado por `tools/build_kpis.py` desde `gestion/src/`. No editar a mano.

## 1. Procesos estándar

Un **proceso** es la secuencia de pasos que la empresa tiene que cumplir para cada caso (cada pedido, cada factura a cobrar, cada orden de compra).
La plataforma trae un **catálogo estándar**; en el onboarding cada empresa activa los procesos que usa, apaga pasos que no aplican, ajusta plazos (SLA)
y define responsables (`ops.proceso_config`). La definición del proceso **no cambia entre empresas**: solo su configuración.

Cada paso se mide con un **evento** que ya existe en el modelo canónico (una fecha/hora de una tabla) o, si ningún sistema lo registra,
con un evento de proceso (`core.fct_evento_proceso`) que se puede cargar desde cualquier fuente o registrar a mano en el tablero.

**Regla: ningún paso sin acción.** Cada paso con plazo define qué hacer si se vence (`si_vence`: acción, responsable, plazo). Los pasos vencidos
generan tareas de la actividad ACT-07 con esa acción. El build falla si un paso con SLA no tiene `si_vence`.

**Estado de cada paso por caso** (dominio `estado_paso`): `completado`, `completado_fuera_de_sla`, `pendiente_en_plazo`, `pendiente_vencido`,
`omitido` (obligatorio que no ocurrió pero ocurrió uno posterior), `no_aplica` (condición `aplica_si` falsa), `fuera_de_orden`.

**Métricas estándar de proceso** (se calculan igual para todos los procesos y todos los pasos; se usan en objetivos como `PRC-XXX.<metrica>` o `PRC-XXX.<paso>.<metrica>`):

| Métrica | Descripción | Unidad | Dirección |
|---|---|---|---|
| `casos_iniciados` | Casos que empezaron el proceso en el período | cantidad | neutral |
| `casos_completados` | Casos que llegaron al último paso aplicable en el período | cantidad | mayor_mejor |
| `casos_en_curso` | Casos abiertos ahora (WIP) | cantidad | neutral |
| `casos_trabados` | Casos abiertos con un paso vencido o sin avanzar más de 2× el P90 histórico del paso | cantidad | menor_mejor |
| `tiempo_ciclo_p50` | Mediana del tiempo de inicio a fin (horas o días hábiles según el proceso) | tiempo | menor_mejor |
| `tiempo_ciclo_p90` | Percentil 90 del tiempo de inicio a fin | tiempo | menor_mejor |
| `tiempo_paso_p50` | Mediana del tiempo desde el paso anterior (solo con prefijo de paso: PRC-XXX.P3.tiempo_paso_p50) | tiempo | menor_mejor |
| `cumplimiento_sla_pct` | % de pasos con SLA completados dentro del plazo (global o por paso) | porcentaje | mayor_mejor |
| `conformidad_pct` | % de casos completados sin pasos obligatorios omitidos ni fuera de orden | porcentaje | mayor_mejor |
| `casos_vencidos_abiertos` | Casos con al menos un paso pendiente_vencido ahora | cantidad | menor_mejor |

**Formato de eventos y SLA:**

```yaml
evento:
  columna: <tabla.columna canónica con la fecha/hora del paso>
  relacion: <cómo se vincula con el caso, SQL sobre alias 'caso'>   # omitir si la columna es de la tabla del caso
  agregacion: min | max                                            # si hay varias filas (ej. primera recepción)
  filtro: <condición opcional>
# o bien
evento: {evento_proceso: <código del dominio evento_proceso>}

sla: {desde: <paso previo>, horas_habiles: N}      # o dias_habiles / horas / dias
sla: {limite: <tabla.columna con fecha límite>}     # la fecha comprometida está en los datos
sla: {desde_columna: <tabla.columna>, dias: N}      # relativo a una fecha que no es un paso
```

**Configuración por empresa** (`ops`):

```sql
create table ops.proceso_config (tenant_id uuid, proceso text, activo boolean, variante_default text, unidad_tiempo text, primary key (tenant_id, proceso));
create table ops.proceso_paso_config (tenant_id uuid, proceso text, paso text, activo boolean, obligatorio boolean, sla jsonb,
  responsable_rol text, accion_si_vence text, escalamiento jsonb, primary key (tenant_id, proceso, paso));   -- overrides del catálogo
```

| ID | Proceso | Área | Caso | Pasos |
|---|---|---|---|---|
| [PRC-VEN](#prc-ven) | Ciclo de venta (del pedido al cobro) | ventas | `fct_pedido` | 7 |
| [PRC-LOG](#prc-log) | Cumplimiento del pedido (logística) | logistica | `fct_envio` | 6 |
| [PRC-COB](#prc-cob) | Cobranza (de la factura al cobro aplicado) | finanzas | `fct_documento_cxc` | 6 |
| [PRC-COM](#prc-com) | Compra (de la orden al pago) | inventario | `fct_orden_compra` | 7 |
| [PRC-CRM](#prc-crm) | Oportunidad comercial (del lead al pedido) | ventas | `fct_lead` | 6 |
| [PRC-DEV](#prc-dev) | Devolución (de la solicitud al reintegro) | ventas | `fct_devolucion` | 4 |

---

### PRC-VEN
#### Ciclo de venta (del pedido al cobro)

**Caso:** una fila de `fct_pedido` (clave `pedido_id`, filtro `pedido_valido`). **Unidad de tiempo:** horas_habiles.

**Variantes:** `prepago` (Se paga antes de preparar (online, contado). Condición: `caso.estado_pago is not null and dim_cliente.condicion_pago_dias = 0`); `cuenta_corriente` (Se entrega y se cobra después (empresas, mayoristas). Condición: `dim_cliente.condicion_pago_dias > 0`)

| Paso | Nombre | Evento que lo marca | Oblig. | Aplica si | Plazo (SLA) | Si se vence: acción | Responsable | Plazo de la acción |
|---|---|---|---|---|---|---|---|---|
| P1 | Pedido registrado | `fct_pedido.pedido_at` | sí | — | — | — | — | — |
| P2 | Pago confirmado | `fct_pedido.confirmado_at` | sí | variante = 'prepago' | desde: P1, horas: 48 | Contactar al cliente para completar el pago; si no paga en 72 h, cancelar el pedido y liberar el stock reservado. | vendedor | 24 h |
| P3 | Facturado | `fct_comprobante.fecha_emision` (min) — vínculo: `fct_comprobante.pedido_id = caso.pedido_id and fct_comprobante.circuito = 'venta' and fct_comprobante.clase in ('factura','ticket')` | sí | — | desde: P2, horas_habiles: 24, alternativa_desde: P1 | Emitir la factura del pedido (verificar datos fiscales del cliente si la emisión falló). | administrativo | mismo día |
| P4 | Preparado | `fct_envio.listo_despacho_at` (min) — vínculo: `fct_envio.pedido_id = caso.pedido_id and not fct_envio.es_devolucion` | no | — | desde: P2, horas_habiles: 24, alternativa_desde: P1 | Preparar el pedido; si falta un producto, avisar al vendedor para ofrecer reemplazo o entrega parcial. | operario_deposito | 4 h hábiles |
| P5 | Despachado | `fct_envio.despacho_at` (min) — vínculo: `fct_envio.pedido_id = caso.pedido_id and not fct_envio.es_devolucion` | sí | — | limite: fct_envio.fecha_limite_despacho, alternativa: desde: P4, horas_habiles: 8 | Despachar o coordinar el retiro con el transportista hoy; si no es posible, informar al cliente la nueva fecha. | logistica | mismo día |
| P6 | Entregado | `fct_envio.entrega_at` (max) — vínculo: `fct_envio.pedido_id = caso.pedido_id and not fct_envio.es_devolucion` | sí | — | limite: fct_envio.fecha_promesa | Reclamar al transportista el estado del envío y avisar al cliente con una fecha nueva de entrega. | logistica | 24 h |
| P7 | Cobrado | `fct_documento_cxc.fecha_cancelacion` (max) — vínculo: `fct_documento_cxc.comprobante_id in (select comprobante_id from core.fct_comprobante c where c.pedido_id = caso.pedido_id)` | sí | variante = 'cuenta_corriente' | limite: fct_documento_cxc.fecha_vencimiento | Iniciar la gestión de cobranza del documento (proceso PRC-COB). | cobrador | 24 h |

---

### PRC-LOG
#### Cumplimiento del pedido (logística)

**Caso:** una fila de `fct_envio` (clave `envio_id`, filtro `not es_devolucion and es_controlable`). **Unidad de tiempo:** horas_habiles.

| Paso | Nombre | Evento que lo marca | Oblig. | Aplica si | Plazo (SLA) | Si se vence: acción | Responsable | Plazo de la acción |
|---|---|---|---|---|---|---|---|---|
| P1 | Pedido liberado para preparar | `fct_envio.pedido_at` | sí | — | — | — | — | — |
| P2 | Inicio de preparación | `fct_preparacion.inicio_at` (min) — vínculo: `fct_preparacion.pedido_id = caso.pedido_id` | no | — | desde: P1, horas_habiles: 8 | Asignar el pedido a un preparador y priorizarlo en la lista de picking. | operario_deposito | 2 h hábiles |
| P3 | Listo para despachar | `fct_envio.listo_despacho_at` | sí | — | desde: P1, horas_habiles: 16 | Terminar el embalaje y etiquetado; si hay faltantes, registrar el motivo y avisar al vendedor. | operario_deposito | 4 h hábiles |
| P4 | Despachado | `fct_envio.despacho_at` | sí | — | limite: fct_envio.fecha_limite_despacho, alternativa: desde: P3, horas_habiles: 8 | Coordinar retiro urgente o entrega con flota propia; registrar el motivo de la demora. | logistica | mismo día |
| P5 | Primer intento de entrega | `fct_envio.primer_intento_at` | no | — | limite: fct_envio.fecha_promesa | Consultar al transportista por el envío sin novedades y escalar el reclamo. | logistica | 24 h |
| P6 | Entregado | `fct_envio.entrega_at` | sí | — | limite: fct_envio.fecha_promesa | Avisar al cliente con fecha nueva y, si corresponde, ofrecer compensación según política; registrar reclamo al transportista. | logistica | 24 h |

---

### PRC-COB
#### Cobranza (de la factura al cobro aplicado)

**Caso:** una fila de `fct_documento_cxc` (clave `documento_cxc_id`, filtro `estado <> 'anulado' and importe_original > 0`). **Unidad de tiempo:** dias_habiles.

| Paso | Nombre | Evento que lo marca | Oblig. | Aplica si | Plazo (SLA) | Si se vence: acción | Responsable | Plazo de la acción |
|---|---|---|---|---|---|---|---|---|
| P1 | Documento emitido | `fct_documento_cxc.fecha_emision` | sí | — | — | — | — | — |
| P2 | Recordatorio previo al vencimiento | evento de proceso `recordatorio_cobro_enviado` | no | — | desde_columna: fct_documento_cxc.fecha_vencimiento, dias: -3 | Enviar recordatorio de vencimiento al cliente (plantilla estándar) y registrarlo. | cobrador | mismo día |
| P3 | Gestión de cobranza tras el vencimiento | evento de proceso `gestion_cobranza_realizada` | sí | caso.saldo_pendiente > 0 and current_date > caso.fecha_vencimiento | desde_columna: fct_documento_cxc.fecha_vencimiento, dias_habiles: 2 | Contactar al cliente (llamado o mensaje), registrar el resultado y, si hay compromiso, la promesa de pago con fecha e importe. | cobrador | 24 h |
| P4 | Promesa de pago registrada | evento de proceso `promesa_pago_registrada` | no | — | desde: P3, dias_habiles: 3 | Volver a contactar y pedir fecha concreta de pago; si no hay respuesta, escalar a finanzas. | cobrador | 48 h |
| P5 | Cobrado | `fct_documento_cxc.fecha_cancelacion` | sí | — | limite: fct_documento_cxc.fecha_vencimiento | Seguir la escalera de cobranza (ver escalamiento). | cobrador | según escalamiento |
| P6 | Cobro aplicado a la factura | `fct_aplicacion_cobro.fecha_aplicacion` (max) — vínculo: `fct_aplicacion_cobro.documento_cxc_id = caso.documento_cxc_id` | no | — | desde: P5, dias_habiles: 2 | Aplicar el cobro recibido a la factura en el sistema de gestión (cobros sin imputar distorsionan la cuenta corriente). | administrativo | 48 h |

**Escalamiento de P5 (Cobrado):**

| Días vencido | Acción | Responsable | Plazo |
|---|---|---|---|
| 15 | Aviso formal al cliente y a su vendedor; el vendedor contacta a su referente. | vendedor | 48 h |
| 30 | Suspender nuevas ventas a cuenta corriente al cliente hasta regularizar (registrar evento credito_suspendido). | finanzas | 24 h |
| 60 | Proponer plan de pagos o derivar a gestión externa/legal; evaluar previsión por incobrable. | gerente_general | 7 días |

---

### PRC-COM
#### Compra (de la orden al pago)

**Caso:** una fila de `fct_orden_compra` (clave `orden_compra_id`, filtro `estado <> 'borrador'`). **Unidad de tiempo:** dias_habiles.

| Paso | Nombre | Evento que lo marca | Oblig. | Aplica si | Plazo (SLA) | Si se vence: acción | Responsable | Plazo de la acción |
|---|---|---|---|---|---|---|---|---|
| P1 | Orden emitida | `fct_orden_compra.fecha_emision` | sí | — | — | — | — | — |
| P2 | Orden aprobada | `fct_orden_compra.fecha_aprobacion` | no | — | desde: P1, dias_habiles: 1 | Aprobar o rechazar la orden de compra pendiente. | gerente_operaciones | mismo día |
| P3 | Confirmada por el proveedor | evento de proceso `confirmacion_proveedor` | no | — | desde: P2, dias_habiles: 2, alternativa_desde: P1 | Pedir al proveedor confirmación de la orden y fecha de entrega. | comprador | 24 h |
| P4 | Primera recepción | `fct_recepcion.fecha_recepcion` (min) — vínculo: `fct_recepcion.orden_compra_id = caso.orden_compra_id` | sí | — | limite: fct_orden_compra.fecha_entrega_prometida | Reclamar la entrega al proveedor; si hay productos en quiebre, evaluar compra alternativa (ACT-02 C1). | comprador | 24 h |
| P5 | Recepción completa | `fct_orden_compra.fecha_recepcion_completa` | no | — | desde: P4, dias_habiles: 5 | Definir con el proveedor el saldo pendiente: entrega o cancelación del remanente. | comprador | 48 h |
| P6 | Factura del proveedor recibida | `fct_comprobante.fecha_emision` (min) — vínculo: `fct_comprobante.orden_compra_id = caso.orden_compra_id and fct_comprobante.circuito = 'compra'` | sí | — | desde: P4, dias_habiles: 5 | Solicitar la factura al proveedor y controlarla contra lo recibido (cantidades y precios de lista). | administrativo | 48 h |
| P7 | Pagada | `fct_documento_cxp.fecha_cancelacion` (max) — vínculo: `fct_documento_cxp.comprobante_id in (select comprobante_id from core.fct_comprobante c where c.orden_compra_id = caso.orden_compra_id)` | sí | — | limite: fct_documento_cxp.fecha_vencimiento | Programar el pago vencido en el próximo lote de pagos o acordar nueva fecha con el proveedor. | finanzas | 48 h |

---

### PRC-CRM
#### Oportunidad comercial (del lead al pedido)

**Caso:** una fila de `fct_lead` (clave `lead_id`, filtro `true`). **Unidad de tiempo:** horas_habiles.

| Paso | Nombre | Evento que lo marca | Oblig. | Aplica si | Plazo (SLA) | Si se vence: acción | Responsable | Plazo de la acción |
|---|---|---|---|---|---|---|---|---|
| P1 | Lead recibido | `fct_lead.creado_at` | sí | — | — | — | — | — |
| P2 | Primer contacto | `fct_lead.primer_contacto_at` | sí | — | desde: P1, horas_habiles: 2 | Contactar al lead ahora (la probabilidad de conversión cae rápido con la demora) y registrar el contacto. | vendedor | 1 h hábil |
| P3 | Calificado | `fct_lead.fecha_calificacion` | no | — | desde: P2, dias_habiles: 5 | Calificar o descartar el lead (con motivo) para no dejarlo abierto. | vendedor | 48 h |
| P4 | Propuesta enviada | `fct_oportunidad_historial_etapa.entrada_at` (min) — vínculo: `fct_oportunidad_historial_etapa.oportunidad_id = caso.oportunidad_id and fct_oportunidad_historial_etapa.etapa = 'propuesta'` | no | — | desde: P3, dias_habiles: 5 | Enviar la propuesta o registrar por qué no corresponde. | vendedor | 48 h |
| P5 | Oportunidad cerrada | `fct_oportunidad.fecha_cierre` (max) — vínculo: `fct_oportunidad.oportunidad_id = caso.oportunidad_id` | no | — | limite: fct_oportunidad.fecha_cierre_esperada | Actualizar la fecha de cierre esperada con un próximo paso concreto, o cerrar como perdida con motivo. | vendedor | 48 h |
| P6 | Pedido generado | `fct_pedido.pedido_at` (min) — vínculo: `fct_pedido.pedido_id = (select pedido_id from core.fct_oportunidad o where o.oportunidad_id = caso.oportunidad_id)` | no | — | desde: P5, dias_habiles: 3 | Cargar el pedido de la oportunidad ganada. | vendedor | 24 h |

---

### PRC-DEV
#### Devolución (de la solicitud al reintegro)

**Caso:** una fila de `fct_devolucion` (clave `devolucion_id`, filtro `estado <> 'rechazada'`). **Unidad de tiempo:** dias_habiles.

| Paso | Nombre | Evento que lo marca | Oblig. | Aplica si | Plazo (SLA) | Si se vence: acción | Responsable | Plazo de la acción |
|---|---|---|---|---|---|---|---|---|
| P1 | Devolución solicitada | `fct_devolucion.fecha_solicitud` | sí | — | — | — | — | — |
| P2 | Producto recibido | `fct_devolucion.fecha_recepcion` | sí | — | desde: P1, dias_habiles: 7 | Verificar el envío de retorno con el cliente/transportista y enviarle instrucciones si no lo despachó. | logistica | 48 h |
| P3 | Reintegro o cambio realizado | `fct_devolucion.fecha_reintegro` | sí | — | desde: P2, dias_habiles: 3 | Realizar el reintegro o el cambio y avisar al cliente. | administrativo | 24 h |
| P4 | Nota de crédito emitida | `fct_comprobante.fecha_emision` (min) — vínculo: `fct_comprobante.comprobante_id = caso.comprobante_id and fct_comprobante.clase = 'nota_credito'` | no | — | desde: P2, dias_habiles: 3 | Emitir la nota de crédito correspondiente a la devolución. | administrativo | 48 h |

## 2. Objetivos — definición, validación, cascada y seguimiento en tiempo real

Un **objetivo** es una meta numérica sobre una métrica, para un alcance (empresa, área, sucursal, canal, equipo, vendedor, persona)
y un período (diario, semanal, mensual, trimestral, anual), con un responsable.
La plataforma trae **plantillas estándar** (abajo). Cada empresa elige cuáles usa, les pone valor y responsable; la definición es la misma para todas.

**Métricas que puede usar un objetivo** (siempre medidas por la plataforma, nunca cargadas a mano):
- `kpi: <ID>` — cualquier KPI disponible del registry (docs/08-12).
- `proceso: PRC-XXX.<metrica>` o `PRC-XXX.<paso>.<metrica>` — métricas estándar de proceso (docs/15 §1).
- `actividad: ACT-XX.<metrica>` o `actividad: todas.<metrica>` — `tareas_resueltas_en_plazo_pct`, `tareas_vencidas`, `impacto_resuelto`.

### Modelo de datos (esquema `ops`)
```sql
create table ops.objetivo (
  objetivo_id uuid primary key, tenant_id uuid not null, plantilla_id text,     -- OBJ-xx o null si es personalizado
  nombre text, metrica text not null,                 -- 'kpi:VEN-01' | 'proceso:PRC-LOG.P4.cumplimiento_sla_pct' | 'actividad:ACT-01.tareas_resueltas_en_plazo_pct'
  parametros jsonb,                                   -- parámetros del KPI (moneda, ajuste, base, …)
  alcance_tipo text, alcance_valor text,              -- 'empresa' | 'area' | 'sucursal' | 'canal' | 'equipo' | 'vendedor' | 'persona' | 'categoria'
  periodicidad text not null,                         -- dominio periodicidad
  tipo_meta text not null,                            -- dominio tipo_meta: minimo (≥) | maximo (≤) | rango | exacto
  curva_esperada text not null,                       -- dominio curva_esperada
  umbral_en_riesgo numeric default 0.95,              -- ritmo por debajo del cual pasa a amarillo
  umbral_fuera_de_camino numeric default 0.85,        -- ritmo por debajo del cual pasa a rojo
  peso numeric default 1,                             -- para puntaje de tableros
  responsable_rol text, responsable_usuario text,
  objetivo_padre_id uuid,                             -- cascada (mensual → semanal → diario; empresa → sucursal → vendedor)
  metodo_reparto text,                                -- 'dias_habiles' | 'estacionalidad_historica' | 'participacion_historica' | 'manual' | 'igual'
  vigente_desde date, vigente_hasta date, estado text,   -- 'borrador' | 'validado' | 'activo' | 'archivado'
  creado_por text, aprobado_por text
);
create table ops.objetivo_meta (                      -- una fila por instancia de período (ej. semana 38, 2026-09-21)
  objetivo_id uuid, periodo_inicio date, periodo_fin date,
  meta numeric, meta_min numeric, meta_max numeric,   -- min/max para 'rango'
  origen text,                                        -- 'manual' | 'cascada' | 'sugerida_aceptada'
  primary key (objetivo_id, periodo_inicio)
);
create table ops.objetivo_evaluacion (                -- historial de evaluaciones (cada corrida) → permite ver la evolución intradía
  objetivo_id uuid, periodo_inicio date, evaluado_at timestamptz,
  valor_actual numeric, valor_esperado_a_la_fecha numeric, avance_pct numeric, ritmo numeric,
  proyeccion_cierre numeric, prob_cumplimiento numeric, estado text,   -- dominio estado_objetivo
  datos_actualizados_at timestamptz, advertencias jsonb,
  primary key (objetivo_id, periodo_inicio, evaluado_at)
);
create table ops.objetivo_validacion (objetivo_id uuid, regla text, severidad text, mensaje text, datos jsonb, creado_at timestamptz);
```
`marts.obj__estado_actual` = última evaluación por objetivo y período vigente (lo que muestra el tablero).

### Evaluación (cada corrida del ciclo de tiempo real, docs/15 §4)
Sea `M` la meta del período, `A` el valor actual acumulado al momento `t`, `c(t)` la **curva esperada** acumulada (fracción de la meta que "debería" estar lograda en `t`):
- `lineal`: c(t) = tiempo transcurrido / duración del período.
- `dias_habiles`: c(t) = días hábiles transcurridos (+ fracción del día según horario operativo) / días hábiles del período.
- `estacionalidad_historica`: c(t) = participación acumulada histórica (últimas 8 semanas / 12 meses) por día de semana y día del mes, excluyendo fechas marcadas como evento.
- `intradia_historica` (objetivos diarios): c(t) = participación acumulada histórica por hora del mismo día de semana.
- `no_aplica`: para métricas no acumulables (ratios, snapshots, tiempos): se compara el valor actual contra la meta directamente.

Para métricas **acumulables** (aditivas: venta, pedidos, cobrado, casos completados):
- `esperado = M × c(t)` · `avance = A / M` · `ritmo = A / esperado`
- `proyeccion_cierre = A / c(t)` (con c(t) ≥ 0,15; antes se usa `A + M × (1 − c(t)) × ritmo_acotado`, ritmo acotado a [0,5; 1,5])
- `prob_cumplimiento` = P(proyección ≥ M) con la dispersión histórica del error de proyección para ese avance de período (tabla empírica por tenant y métrica; default normal con CV 10 %).
Para métricas **no acumulables** (%, tiempos, stocks): `ritmo = valor / meta` si tipo_meta = minimo; `meta / valor` si maximo; se exige muestra mínima (ej. ≥ 30 casos) para evaluar; si no, `no_evaluable`.
**Estado:** `cumplido` (período cerrado y meta alcanzada, o meta acumulable ya superada) · `en_camino` (ritmo ≥ umbral_en_riesgo) · `en_riesgo` (entre umbrales) ·
`fuera_de_camino` (ritmo < umbral_fuera_de_camino) · `no_evaluable` (datos de la métrica más viejos que su SLA de frescura, o muestra insuficiente) · `sin_meta`.
Primer 10 % del período: los objetivos acumulables no pasan a rojo (poca información), salvo objetivos diarios después de la hora de mayor venta.

### Cascada (una vez definido el objetivo mensual, el resto se genera solo)
- **En el tiempo:** mensual → semanal → diario, repartiendo la meta con `metodo_reparto` (por defecto `estacionalidad_historica` si hay ≥ 8 semanas de datos, si no `dias_habiles`). Si un día queda por debajo o por encima, la **meta de los días restantes se recalcula** (modo `recuperar`: lo que falta se reparte en lo que queda; modo `fijo`: no se recalcula) — configurable.
- **En el alcance:** empresa → sucursales / canales / vendedores según `participacion_historica` (últimos 3 meses) o manual; la suma de los hijos debe igualar al padre en métricas aditivas (regla V4).
- Métricas no aditivas (margen %, OTD) se heredan con la misma meta (o se ajustan manualmente) y el padre se evalúa con su propio valor, no con el promedio de los hijos.

### Validación de objetivos (al crear o editar; estado `borrador` → `validado`)
| Regla | Qué verifica | Severidad |
|---|---|---|
| V1 Métrica disponible | la métrica existe y está `disponible`/`degradado` para el tenant (`ops.kpi_capacidad`) | bloquea |
| V2 Coherencia de sentido | tipo_meta coherente con la dirección de la métrica (no poner "mínimo" a un tiempo de entrega) | bloquea |
| V3 Datos completos | período, alcance válido, responsable y meta presentes; rango con min < max | bloquea |
| V4 Suma de la cascada | hijos aditivos suman al padre (±0,5 %); períodos cortos suman al largo | bloquea |
| V5 Realismo | meta vs distribución histórica del mismo período (12-24 meses, en términos reales si es monetaria): > P95 histórico o crecimiento real requerido > 30 % → "muy exigente"; < P25 → "poco exigente" | advierte (requiere justificación para activar) |
| V6 Contra presupuesto | si hay presupuesto cargado para la misma métrica y período, diferencia > 5 % | advierte |
| V7 Conflictos | objetivos que tiran en sentidos opuestos para el mismo alcance (ej. subir margen % y subir descuento %; bajar stock y subir fill rate al máximo) | advierte |
| V8 Controlabilidad | el responsable tiene alcance sobre lo que se mide (un vendedor no puede tener objetivo de empresa) | advierte |
| V9 Muestra suficiente | métricas no aditivas con volumen esperado bajo para el período (ej. OTD diario con < 30 envíos) → sugerir período más largo | advierte |
Para cada objetivo nuevo, la plataforma **sugiere la meta** con el método de la plantilla (`meta_sugerida`) y muestra la validación antes de guardarlo.

### Regla: ningún objetivo en rojo sin acción
Cada plantilla define `si_en_riesgo` y `si_fuera_de_camino` con acciones (responsable y plazo) y `palancas` (KPIs y actividades que empujan la métrica).
Al cambiar de estado se genera una tarea ACT-08 con esas acciones + la explicación automática de la variación (`explicar_variacion`) + las tareas abiertas de las actividades-palanca.
El build falla si una plantilla no tiene acciones para ambos estados.

### Plantillas estándar de objetivos

| ID | Objetivo | Área | Métrica | Períodos | Meta | Responsable |
|---|---|---|---|---|---|---|
| [OBJ-01](#obj-01) | Venta neta | ventas | `kpi:VEN-01` | diario, semanal, mensual | minimo | comercial |
| [OBJ-02](#obj-02) | Cantidad de pedidos / tickets | ventas | `kpi:VEN-02` | diario, semanal, mensual | minimo | comercial |
| [OBJ-03](#obj-03) | Ticket promedio | ventas | `kpi:VEN-03` | semanal, mensual | minimo | comercial |
| [OBJ-04](#obj-04) | Margen bruto comercial | ventas | `kpi:VEN-08` | semanal, mensual | minimo | comercial |
| [OBJ-05](#obj-05) | Clientes nuevos | ventas | `kpi:VEN-11` | semanal, mensual | minimo | comercial |
| [OBJ-06](#obj-06) | Cumplimiento de cuota por vendedor | ventas | `kpi:VEN-07` | semanal, mensual | minimo | vendedor |
| [OBJ-07](#obj-07) | Despacho en plazo | logistica | `kpi:LOG-03` | diario, semanal, mensual | minimo | logistica |
| [OBJ-08](#obj-08) | Entregas a tiempo (OTD) | logistica | `kpi:LOG-06` | semanal, mensual | minimo | logistica |
| [OBJ-09](#obj-09) | Backlog atrasado en cero | logistica | `kpi:LOG-14` | diario | maximo | logistica |
| [OBJ-10](#obj-10) | Costo logístico sobre venta | logistica | `kpi:LOG-12` | mensual | maximo | logistica |
| [OBJ-11](#obj-11) | Cobranza del período | finanzas | `kpi:FIN-15` | semanal, mensual | minimo | cobrador |
| [OBJ-12](#obj-12) | Cartera vencida | finanzas | `kpi:FIN-10` | semanal, mensual | maximo | finanzas |
| [OBJ-13](#obj-13) | Documentos gestionados a tiempo | finanzas | `proceso:PRC-COB.P3.cumplimiento_sla_pct` | semanal, mensual | minimo | cobrador |
| [OBJ-14](#obj-14) | Gastos operativos dentro del presupuesto | finanzas | `kpi:FIN-04` | mensual | maximo | finanzas |
| [OBJ-15](#obj-15) | Caja mínima | finanzas | `kpi:FIN-07` | diario | minimo | finanzas |
| [OBJ-16](#obj-16) | Quiebre de stock | inventario | `kpi:INV-06` | diario, semanal | maximo | comprador |
| [OBJ-17](#obj-17) | Días de inventario | inventario | `kpi:INV-04` | mensual | maximo | comprador |
| [OBJ-18](#obj-18) | Pedidos a proveedores en tiempo | inventario | `proceso:PRC-COM.P4.cumplimiento_sla_pct` | mensual | minimo | comprador |
| [OBJ-19](#obj-19) | Mercadería vencida o en riesgo | inventario | `kpi:INV-20` | semanal, mensual | maximo | encargado_sucursal |
| [OBJ-20](#obj-20) | Eficiencia de marketing (MER) | marketing | `kpi:MKT-07` | semanal, mensual | minimo | marketing |
| [OBJ-21](#obj-21) | Costo de adquisición (CAC) | marketing | `kpi:MKT-08` | mensual | maximo | marketing |
| [OBJ-22](#obj-22) | Pedidos facturados en plazo | ventas | `proceso:PRC-VEN.P3.cumplimiento_sla_pct` | diario, semanal | minimo | administrativo |
| [OBJ-23](#obj-23) | Tiempo de ciclo de venta a entrega | logistica | `proceso:PRC-VEN.tiempo_ciclo_p90` | semanal, mensual | maximo | gerente_operaciones |
| [OBJ-24](#obj-24) | Tareas resueltas en plazo | gestion | `actividad:todas.tareas_resueltas_en_plazo_pct` | semanal, mensual | minimo | gerente_operaciones |

---

### OBJ-01
#### Venta neta

| Atributo | Valor |
|---|---|
| Métrica | `kpi:VEN-01` |
| Períodos | diario, semanal, mensual |
| Alcances | empresa, sucursal, canal, vendedor, categoria |
| Tipo de meta | minimo |
| Curva esperada | `diario`=intradia_historica, `semanal`=estacionalidad_historica, `mensual`=estacionalidad_historica |
| Meta sugerida | Venta del mismo período del año anterior en términos reales × (1 + crecimiento real objetivo del tenant, default 5 %), llevada a nominal con la inflación esperada; alternativa: presupuesto cargado. |
| Responsable | comercial |
| Palancas | VEN-24, VEN-15, INV-06, ACT-01, ACT-02, MKT-07 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Revisar la explicación automática de la brecha (canal, sucursal, categoría con mayor caída) y confirmar si es precio, tráfico o falta de stock. | comercial | 24 h |
| 🟡 en riesgo | 2 | Resolver primero las tareas abiertas de quiebre oculto y reposición urgente de productos clase A (ACT-01, ACT-02 C1). | encargado_sucursal | 24 h |
| 🔴 fuera de camino | 1 | Armar plan de recuperación: contactar clientes recurrentes en riesgo (VEN-15), activar una promoción táctica con margen positivo (ver histórico ACT-05) y reforzar la inversión en el canal con mejor ROAS real. | comercial | 48 h |
| 🔴 fuera de camino | 2 | Reunión de seguimiento con responsables de sucursal/canal y revisión diaria hasta volver a amarillo. | gerente_general | 72 h |

---

### OBJ-02
#### Cantidad de pedidos / tickets

| Atributo | Valor |
|---|---|
| Métrica | `kpi:VEN-02` |
| Períodos | diario, semanal, mensual |
| Alcances | empresa, sucursal, canal |
| Tipo de meta | minimo |
| Curva esperada | `diario`=intradia_historica, `semanal`=estacionalidad_historica, `mensual`=estacionalidad_historica |
| Meta sugerida | Pedidos del mismo período del año anterior × (1 + crecimiento objetivo de tráfico). |
| Responsable | comercial |
| Palancas | MKT-10, MKT-11, VEN-17, ACT-05 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Verificar tráfico (sesiones, visitas) y conversión; si cayó el tráfico, revisar inversión y campañas activas; si cayó la conversión, revisar precios y stock de los más vendidos. | marketing | 24 h |
| 🔴 fuera de camino | 1 | Lanzar acción de tráfico (campaña o comunicación a la base de clientes) y revisar cancelaciones del período. | marketing | 48 h |

---

### OBJ-03
#### Ticket promedio

| Atributo | Valor |
|---|---|
| Métrica | `kpi:VEN-03` |
| Períodos | semanal, mensual |
| Alcances | empresa, sucursal, canal, vendedor |
| Tipo de meta | minimo |
| Curva esperada | `semanal`=no_aplica, `mensual`=no_aplica |
| Meta sugerida | Ticket real promedio de los últimos 3 meses × (1 + objetivo de mejora, default 3 %). |
| Responsable | comercial |
| Palancas | VEN-04, VEN-18, ACT-05 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Revisar descuentos otorgados (VEN-18) y el mix de productos; reforzar venta sugerida/complementaria en caja o en el carrito online. | comercial | 48 h |
| 🔴 fuera de camino | 1 | Definir combos o umbrales de envío gratis/beneficio por monto mínimo y medir su efecto en 2 semanas. | comercial | 7 días |

---

### OBJ-04
#### Margen bruto comercial

| Atributo | Valor |
|---|---|
| Métrica | `kpi:VEN-08` (`medida`=margen_bruto_pct) |
| Períodos | semanal, mensual |
| Alcances | empresa, categoria, canal, sucursal |
| Tipo de meta | minimo |
| Curva esperada | `semanal`=no_aplica, `mensual`=no_aplica |
| Meta sugerida | Margen objetivo de la política de precios ponderado por el mix de venta de los últimos 3 meses. |
| Responsable | comercial |
| Palancas | ACT-04, VEN-27, VEN-18, ACT-05 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Resolver las tareas de remarcación pendientes (ACT-04), empezando por las de mayor impacto. | comercial | 48 h |
| 🔴 fuera de camino | 1 | Congelar descuentos no aprobados, revisar promociones activas con margen negativo (ACT-05 C3) y productos bajo costo (ACT-04 C3). | gerente_general | 24 h |

---

### OBJ-05
#### Clientes nuevos

| Atributo | Valor |
|---|---|
| Métrica | `kpi:VEN-11` (`medida`=nuevos) |
| Períodos | semanal, mensual |
| Alcances | empresa, canal, vendedor |
| Tipo de meta | minimo |
| Curva esperada | `semanal`=dias_habiles, `mensual`=dias_habiles |
| Meta sugerida | Promedio de los últimos 6 meses del mismo mes × (1 + crecimiento objetivo). |
| Responsable | comercial |
| Palancas | MKT-08, MKT-15, MKT-16, PRC-CRM |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Revisar leads sin contactar y el tiempo al primer contacto (PRC-CRM P2); asignar los pendientes. | vendedor | 24 h |
| 🔴 fuera de camino | 1 | Reforzar campañas de adquisición en el canal con menor CAC y revisar la oferta para primera compra. | marketing | 72 h |

---

### OBJ-06
#### Cumplimiento de cuota por vendedor

| Atributo | Valor |
|---|---|
| Métrica | `kpi:VEN-07` |
| Períodos | semanal, mensual |
| Alcances | vendedor, equipo |
| Tipo de meta | minimo |
| Curva esperada | `semanal`=dias_habiles, `mensual`=dias_habiles |
| Meta sugerida | Cuota cargada en presupuesto (concepto cuota_vendedor); si no hay, participación histórica del vendedor × objetivo de empresa. |
| Responsable | vendedor |
| Palancas | VEN-19, VEN-15, VEN-25 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Priorizar oportunidades del pipeline con cierre esperado en el período y clientes en riesgo de su cartera. | vendedor | 48 h |
| 🔴 fuera de camino | 1 | Sesión 1 a 1 con el líder para plan de cierre de la semana (oportunidades concretas y visitas). | comercial | 72 h |

---

### OBJ-07
#### Despacho en plazo

| Atributo | Valor |
|---|---|
| Métrica | `kpi:LOG-03` |
| Períodos | diario, semanal, mensual |
| Alcances | empresa, deposito, canal |
| Tipo de meta | minimo |
| Curva esperada | `diario`=no_aplica, `semanal`=no_aplica, `mensual`=no_aplica |
| Meta sugerida | 95 % (97 % para canales con penalización por demora); o P75 histórico si es mayor. |
| Responsable | logistica |
| Palancas | LOG-14, LOG-02, PRC-LOG |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Priorizar el backlog por fecha límite de despacho y reasignar preparadores a los pedidos por vencer. | logistica | 2 h |
| 🔴 fuera de camino | 1 | Habilitar turno/horas extra o colecta adicional y avisar a clientes con despacho demorado. | gerente_operaciones | mismo día |

---

### OBJ-08
#### Entregas a tiempo (OTD)

| Atributo | Valor |
|---|---|
| Métrica | `kpi:LOG-06` |
| Períodos | semanal, mensual |
| Alcances | empresa, transportista, zona |
| Tipo de meta | minimo |
| Curva esperada | `semanal`=no_aplica, `mensual`=no_aplica |
| Meta sugerida | 92 % o P75 histórico. |
| Responsable | logistica |
| Palancas | LOG-17, LOG-05, LOG-08 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Identificar transportista/zona que explica la caída (scorecard LOG-17) y reclamarle con el listado de envíos atrasados. | logistica | 48 h |
| 🔴 fuera de camino | 1 | Redirigir envíos de la zona afectada a un transportista alternativo y ajustar la fecha prometida al cliente para esa zona. | gerente_operaciones | 72 h |

---

### OBJ-09
#### Backlog atrasado en cero

| Atributo | Valor |
|---|---|
| Métrica | `kpi:LOG-14` (`medida`=backlog_atrasado) |
| Períodos | diario |
| Alcances | empresa, deposito |
| Tipo de meta | maximo |
| Curva esperada | `diario`=no_aplica |
| Meta sugerida | 0 pedidos atrasados al cierre del día. |
| Responsable | logistica |
| Palancas | LOG-03, PRC-LOG |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Despachar primero los pedidos atrasados y los que vencen hoy. | operario_deposito | 2 h |
| 🔴 fuera de camino | 1 | Escalar: recursos extra hoy y comunicación proactiva a clientes afectados. | gerente_operaciones | mismo día |

---

### OBJ-10
#### Costo logístico sobre venta

| Atributo | Valor |
|---|---|
| Métrica | `kpi:LOG-12` |
| Períodos | mensual |
| Alcances | empresa, canal |
| Tipo de meta | maximo |
| Curva esperada | `mensual`=no_aplica |
| Meta sugerida | Promedio real de los últimos 3 meses − 0,5 pp. |
| Responsable | logistica |
| Palancas | LOG-11, LOG-13, LOG-17 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Revisar envíos con subsidio alto (LOG-13) y zonas con costo por envío fuera de rango. | logistica | 7 días |
| 🔴 fuera de camino | 1 | Renegociar tarifas o cambiar mix de transportistas por zona; revisar el umbral de envío gratis. | gerente_operaciones | 30 días |

---

### OBJ-11
#### Cobranza del período

| Atributo | Valor |
|---|---|
| Métrica | `kpi:FIN-15` |
| Períodos | semanal, mensual |
| Alcances | empresa, vendedor, cobrador |
| Tipo de meta | minimo |
| Curva esperada | `semanal`=no_aplica, `mensual`=no_aplica |
| Meta sugerida | Efectividad de cobranza (CEI) 90 % o P75 histórico. |
| Responsable | cobrador |
| Palancas | FIN-10, FIN-11, PRC-COB |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Trabajar el listado de documentos vencidos por importe (PRC-COB P3) y registrar promesas de pago. | cobrador | 48 h |
| 🔴 fuera de camino | 1 | Aplicar la escalera de cobranza (aviso formal, suspensión de crédito a 30 días) a los 10 mayores deudores. | finanzas | 72 h |

---

### OBJ-12
#### Cartera vencida

| Atributo | Valor |
|---|---|
| Métrica | `kpi:FIN-10` (`medida`=pct_vencido) |
| Períodos | semanal, mensual |
| Alcances | empresa, vendedor |
| Tipo de meta | maximo |
| Curva esperada | `semanal`=no_aplica, `mensual`=no_aplica |
| Meta sugerida | 15 % o P25 histórico (el mejor cuartil de la empresa). |
| Responsable | finanzas |
| Palancas | FIN-11, FIN-12, PRC-COB |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Revisar clientes con documentos a más de 30 días y confirmar que tengan gestión registrada. | cobrador | 48 h |
| 🔴 fuera de camino | 1 | Suspender ventas a cuenta corriente a clientes con más de 60 días de atraso y revisar límites de crédito. | gerente_general | 72 h |

---

### OBJ-13
#### Documentos gestionados a tiempo

| Atributo | Valor |
|---|---|
| Métrica | `proceso:PRC-COB.P3.cumplimiento_sla_pct` |
| Períodos | semanal, mensual |
| Alcances | empresa, cobrador |
| Tipo de meta | minimo |
| Curva esperada | `semanal`=no_aplica, `mensual`=no_aplica |
| Meta sugerida | 95 %. |
| Responsable | cobrador |
| Palancas | PRC-COB, ACT-07 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Resolver las tareas de gestión de cobranza vencidas (ACT-07 sobre PRC-COB). | cobrador | 24 h |
| 🔴 fuera de camino | 1 | Reasignar cartera entre cobradores o reforzar horas de gestión. | finanzas | 72 h |

---

### OBJ-14
#### Gastos operativos dentro del presupuesto

| Atributo | Valor |
|---|---|
| Métrica | `kpi:FIN-04` |
| Períodos | mensual |
| Alcances | empresa, centro_costo |
| Tipo de meta | maximo |
| Curva esperada | `mensual`=dias_habiles |
| Meta sugerida | Presupuesto de gastos del mes; si no hay, promedio real de 3 meses. |
| Responsable | finanzas |
| Palancas | FIN-22, FIN-19 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Identificar las cuentas que explican el desvío y congelar gastos no comprometidos de esas cuentas. | finanzas | 72 h |
| 🔴 fuera de camino | 1 | Aprobación previa obligatoria para nuevos gastos del mes y revisión de contratos recurrentes. | gerente_general | 7 días |

---

### OBJ-15
#### Caja mínima

| Atributo | Valor |
|---|---|
| Métrica | `kpi:FIN-07` |
| Períodos | diario |
| Alcances | empresa |
| Tipo de meta | minimo |
| Curva esperada | `diario`=no_aplica |
| Meta sugerida | Pagos promedio de 15 días (configurable). |
| Responsable | finanzas |
| Palancas | FIN-16, FIN-13, OBJ-11 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Revisar la proyección de caja a 30 días y reprogramar pagos no críticos. | finanzas | 24 h |
| 🔴 fuera de camino | 1 | Acelerar cobranza de los mayores saldos vencidos y evaluar financiación de corto plazo. | gerente_general | 48 h |

---

### OBJ-16
#### Quiebre de stock

| Atributo | Valor |
|---|---|
| Métrica | `kpi:INV-06` (`medida`=tasa_quiebre_ponderada) |
| Períodos | diario, semanal |
| Alcances | empresa, sucursal, categoria |
| Tipo de meta | maximo |
| Curva esperada | `diario`=no_aplica, `semanal`=no_aplica |
| Meta sugerida | 3 % ponderado por venta (1 % para clase A). |
| Responsable | comprador |
| Palancas | ACT-02, ACT-01, INV-15 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Emitir hoy los pedidos urgentes de ACT-02 C1 y resolver quiebres ocultos (ACT-01). | comprador | mismo día |
| 🔴 fuera de camino | 1 | Revisar proveedores con peor cumplimiento (INV-16) y activar transferencias entre sucursales. | gerente_operaciones | 48 h |

---

### OBJ-17
#### Días de inventario

| Atributo | Valor |
|---|---|
| Métrica | `kpi:INV-04` |
| Períodos | mensual |
| Alcances | empresa, categoria |
| Tipo de meta | maximo |
| Curva esperada | `mensual`=no_aplica |
| Meta sugerida | Objetivo de cobertura por categoría de la política de producto ponderado por mix. |
| Responsable | comprador |
| Palancas | ACT-03, INV-09, INV-10 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Reducir compras de productos en sobrestock (ACT-03 C2) en los próximos pedidos. | comprador | próximo pedido |
| 🔴 fuera de camino | 1 | Plan de liquidación de inmovilizado (ACT-03 C1) y revisión de mínimos de compra con proveedores. | comercial | 14 días |

---

### OBJ-18
#### Pedidos a proveedores en tiempo

| Atributo | Valor |
|---|---|
| Métrica | `proceso:PRC-COM.P4.cumplimiento_sla_pct` |
| Períodos | mensual |
| Alcances | empresa, proveedor |
| Tipo de meta | minimo |
| Curva esperada | `mensual`=no_aplica |
| Meta sugerida | 90 %. |
| Responsable | comprador |
| Palancas | INV-16, INV-17, PRC-COM |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Reclamar las órdenes atrasadas y actualizar las fechas prometidas en el sistema. | comprador | 48 h |
| 🔴 fuera de camino | 1 | Aumentar el lead time/stock de seguridad de los proveedores incumplidores y evaluar proveedores alternativos. | comprador | 30 días |

---

### OBJ-19
#### Mercadería vencida o en riesgo

| Atributo | Valor |
|---|---|
| Métrica | `kpi:INV-20` |
| Períodos | semanal, mensual |
| Alcances | empresa, sucursal, categoria |
| Tipo de meta | maximo |
| Curva esperada | `semanal`=no_aplica, `mensual`=no_aplica |
| Meta sugerida | ≤ 0,5 % del valor del inventario. |
| Responsable | encargado_sucursal |
| Palancas | ACT-06, ACT-02 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Ejecutar las tareas de vencimiento próximas (ACT-06 C2) hoy. | encargado_sucursal | 24 h |
| 🔴 fuera de camino | 1 | Aplicar el tope por vida útil a todos los perecederos del pedido sugerido y revisar lotes que llegan con poca vida. | comprador | 7 días |

---

### OBJ-20
#### Eficiencia de marketing (MER)

| Atributo | Valor |
|---|---|
| Métrica | `kpi:MKT-07` (`medida`=mer) |
| Períodos | semanal, mensual |
| Alcances | empresa |
| Tipo de meta | minimo |
| Curva esperada | `semanal`=no_aplica, `mensual`=no_aplica |
| Meta sugerida | P50 de los últimos 6 meses o el mínimo que garantiza contribución positiva (1 / (margen de contribución % − costos variables)). |
| Responsable | marketing |
| Palancas | MKT-06, MKT-19, MKT-20 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Pausar o reducir campañas con ROAS real por debajo del mínimo y anuncios fatigados (MKT-20). | marketing | 48 h |
| 🔴 fuera de camino | 1 | Reasignar presupuesto al canal con mejor ROAS real y revisar la oferta/landing de las campañas principales. | marketing | 72 h |

---

### OBJ-21
#### Costo de adquisición (CAC)

| Atributo | Valor |
|---|---|
| Métrica | `kpi:MKT-08` |
| Períodos | mensual |
| Alcances | empresa, canal_marketing |
| Tipo de meta | maximo |
| Curva esperada | `mensual`=no_aplica |
| Meta sugerida | LTV 12 m / 3. |
| Responsable | marketing |
| Palancas | MKT-05, MKT-09, OBJ-05 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Revisar campañas de adquisición con CPA creciente y ajustar segmentación/puja. | marketing | 72 h |
| 🔴 fuera de camino | 1 | Reducir inversión de adquisición hasta recuperar eficiencia y reforzar canales propios (email, orgánico). | marketing | 7 días |

---

### OBJ-22
#### Pedidos facturados en plazo

| Atributo | Valor |
|---|---|
| Métrica | `proceso:PRC-VEN.P3.cumplimiento_sla_pct` |
| Períodos | diario, semanal |
| Alcances | empresa, sucursal |
| Tipo de meta | minimo |
| Curva esperada | `diario`=no_aplica, `semanal`=no_aplica |
| Meta sugerida | 98 %. |
| Responsable | administrativo |
| Palancas | PRC-VEN, ACT-07 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Emitir las facturas pendientes vencidas (listado de ACT-07 sobre PRC-VEN P3). | administrativo | mismo día |
| 🔴 fuera de camino | 1 | Revisar la causa (errores de datos fiscales, integración caída) con el operador de la plataforma y el sistema de facturación. | finanzas | 24 h |

---

### OBJ-23
#### Tiempo de ciclo de venta a entrega

| Atributo | Valor |
|---|---|
| Métrica | `proceso:PRC-VEN.tiempo_ciclo_p90` |
| Períodos | semanal, mensual |
| Alcances | empresa, canal |
| Tipo de meta | maximo |
| Curva esperada | `semanal`=no_aplica, `mensual`=no_aplica |
| Meta sugerida | P90 del último trimestre − 10 %. |
| Responsable | gerente_operaciones |
| Palancas | PRC-VEN, PRC-LOG, LOG-04 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Ver en el tablero de procesos qué paso concentra la demora (mayor aumento de tiempo_paso_p50) y atacar ese paso. | gerente_operaciones | 72 h |
| 🔴 fuera de camino | 1 | Revisión del proceso con los responsables de cada paso; definir cambios y medir 2 semanas. | gerente_general | 7 días |

---

### OBJ-24
#### Tareas resueltas en plazo

| Atributo | Valor |
|---|---|
| Métrica | `actividad:todas.tareas_resueltas_en_plazo_pct` |
| Períodos | semanal, mensual |
| Alcances | empresa, sucursal, persona |
| Tipo de meta | minimo |
| Curva esperada | `semanal`=no_aplica, `mensual`=no_aplica |
| Meta sugerida | 85 %. |
| Responsable | gerente_operaciones |
| Palancas | ACT-01, ACT-02, ACT-03, ACT-04, ACT-05, ACT-06, ACT-07 |

| Estado | # | Acción | Responsable | Plazo |
|---|---|---|---|---|
| 🟡 en riesgo | 1 | Revisar tareas vencidas por responsable y reasignar las de mayor impacto. | gerente_operaciones | 48 h |
| 🔴 fuera de camino | 1 | Revisar la carga de tareas por persona (tope diario) y la precisión de las actividades; ajustar parámetros si hay muchas falsas alarmas. | gerente_general | 7 días |


## 4. Seguimiento en tiempo real

"Tiempo real" se define por **niveles de latencia** según lo que permite cada fuente; el tablero siempre muestra "actualizado hace X" por objetivo y proceso.

| Nivel | Latencia objetivo (evento en origen → tablero) | Fuentes típicas | Cómo |
|---|---|---|---|
| T1 — casi en vivo | ≤ 5 min | fuentes con webhook o API con cursor fino (ventas online, pagos, envíos) | webhook → lectura del registro → micro-lote |
| T2 — frecuente | ≤ 15 min | APIs sin webhook, bases de datos (sistema de gestión) | lectura incremental cada 5-15 min |
| T3 — horario | ≤ 1 h | CRM, publicidad del día en curso, analítica web | lectura horaria |
| T4 — diario | ≤ 24 h | extractos, listas de precios, referencias | carga diaria |

**Ciclo de tiempo real** (orquestador, cada 5 min en horario operativo; cada 30 min fuera de horario), por tenant:
1. Ingesta incremental de los streams T1/T2 con novedades.
2. `dbt build` **incremental y acotado** a los modelos afectados (selector por linaje desde los streams leídos) + `marts.proc__caso_paso`, `marts.proc__caso` (solo casos tocados y casos abiertos) + `marts.obj__base_intradia` (acumulados del período vigente por objetivo).
3. Evaluación de objetivos (Python, sin modelo de lenguaje) → `ops.objetivo_evaluacion` y `marts.obj__estado_actual`.
4. Motor de actividades para ACT-07 y ACT-08 (y ACT-01 intradía si está activo).
5. Publicación de cambios al tablero por **Server-Sent Events / WebSocket** (canal por tenant y usuario, solo los objetivos/casos visibles para ese usuario).
6. Presupuesto de tiempo del ciclo: ≤ 2 min p95 por tenant; si se excede, el ciclo siguiente se saltea y se alerta al operador (no se acumulan ciclos).

Reglas:
- Los KPIs del día en curso se calculan sobre `core` con pre-agregaciones de la capa semántica con `refreshKey` de 5 min para el período vigente; períodos cerrados usan pre-agregaciones diarias.
- Un objetivo cuya métrica depende de una fuente T4 no se muestra como "en vivo": su evaluación intradía es `no_aplica` y se evalúa tras la carga diaria.
- Si una fuente supera su SLA, sus objetivos pasan a `no_evaluable` (no se muestran números viejos como si fueran actuales).

## 5. Tablero de gestión (aplicación web para cada empresa)

Aplicación web (responsive, usable en celular) sobre las mismas APIs (capa semántica + servidor de herramientas + `ops`). Frontend: React/Next.js (herramienta de la plataforma). Autenticación por usuario con rol y alcance (sucursales/áreas/cartera); cada usuario ve solo lo suyo y lo que tiene debajo.

| Pantalla | Qué muestra | Interacciones |
|---|---|---|
| **1. Mis objetivos / Resumen** | Tarjetas por objetivo con semáforo, valor actual, meta, % avance, ritmo, proyección de cierre y "actualizado hace X". Selector día / semana / mes. Agrupado por área. Puntaje global ponderado por `peso`. | Filtrar por área, sucursal, responsable. Clic → detalle. |
| **2. Detalle de objetivo** | Curva acumulada real vs esperada (con banda de proyección), valor intradía, historia de períodos anteriores, explicación de la brecha por dimensión, palancas con sus tareas abiertas, cascada (padre/hijos) con su estado. | Registrar comentario/plan de recuperación; ver tareas ACT-08. |
| **3. Procesos** | Por proceso: embudo de pasos con casos en cada paso, tiempo mediano por paso, % en SLA por paso, casos trabados. Variantes separadas. | Clic en un paso → lista de casos con antigüedad y responsable; **"registrar paso"** para eventos de proceso (ej. gestión de cobranza, confirmación de proveedor). |
| **4. Mis tareas** | Tareas de todas las actividades asignadas al usuario, ordenadas por puntaje, con acciones, plazo y evidencia. | Cambiar estado, elegir resolución, comentar, descargar artefacto (pedido sugerido, remarcación, etiquetas). |
| **5. Configurar objetivos** | Asistente: elegir plantilla → alcance y período → meta sugerida → validación (V1-V9) → cascada automática (vista previa de metas por semana/día y por sucursal/vendedor) → aprobar. | Editar metas de la cascada a mano (revalida V4); importar metas desde planilla con plantilla fija. |
| **6. Configurar procesos** | Procesos del catálogo: activar/desactivar, pasos aplicables, SLA por paso, responsables, escalamientos. | Vista previa del impacto (cuántos casos quedarían vencidos con el SLA nuevo sobre el último mes). |
| **7. Tablero por responsable / sucursal** | Ranking y comparación de objetivos y cumplimiento de procesos entre sucursales, equipos o personas (solo para roles de gestión). | Exportar. |
| **8. Asistente (chat)** | El agente de IA con las herramientas de docs/06, respondiendo sobre objetivos, procesos y tareas del usuario. | Preguntas libres ("¿por qué estoy en rojo en ventas?"). |

Notificaciones: cambio de estado de objetivos propios (a amarillo/rojo/cumplido), tareas críticas y resumen diario (mañana: objetivos del día y tareas; cierre: cómo terminó el día). Canal por usuario (app, email, mensajería).

## 6. Herramientas del agente (se agregan a docs/06 §3.2)

| Herramienta | Parámetros | Devuelve |
|---|---|---|
| `consultar_objetivos` | `periodicidad?`, `area?`, `alcance?`, `estado?` | objetivos con valor, meta, avance, ritmo, proyección, estado, frescura |
| `detalle_objetivo` | `objetivo_id`, `periodo?` | curva real vs esperada, explicación de la brecha, palancas, cascada, historial |
| `proponer_objetivo` | `plantilla_id`, `alcance`, `periodicidad`, `meta?` | meta sugerida + resultado de validación V1-V9 + cascada propuesta (no guarda; guardar requiere aprobación humana en el tablero) |
| `estado_proceso` | `proceso`, `desde?`, `hasta?`, `variante?` | embudo, tiempos por paso, % SLA, conformidad |
| `casos_trabados` | `proceso?`, `paso?`, `responsable_rol?` | casos con paso vencido/detenido, acción y responsable |
| `registrar_evento_proceso` | `proceso`, `caso_key`, `codigo_evento`, `resultado?`, `detalle?` | registra un paso manual (solo en `core.fct_evento_proceso`, con `origen='agente'` y el usuario del token) |

## 7. Plan de implementación (se agrega a docs/07 §6)

**Fase 2c — Procesos, objetivos y tablero**
- `core.fct_evento_proceso`, `ops.proceso_config`, marts `proc__caso_paso` / `proc__caso`, métricas estándar de proceso en la capa semántica (cube `procesos` con dimensiones proceso, paso, variante).
- Tablas `ops.objetivo*`, motor de evaluación, cascada y validación V1-V9, ACT-07 y ACT-08.
- Ciclo de tiempo real (§4) y aplicación web (§5).
- **Aceptación:**
  1. Con las fuentes simuladas, cada proceso del catálogo reconstruye sus casos y pasos; un escenario por estado de paso (completado, fuera de SLA, vencido, omitido, fuera de orden, no aplica).
  2. Un objetivo mensual de venta cargado genera automáticamente metas semanales y diarias y por sucursal que suman al total (V4), y la validación V5 marca como "muy exigente" una meta > P95 histórico.
  3. Un pedido nuevo en la fuente simulada con webhook aparece en el avance del objetivo diario en ≤ 5 min (T1) y en ≤ 15 min por lectura incremental (T2).
  4. Un objetivo que cruza el umbral genera una tarea ACT-08 con las acciones de su plantilla, y no se vuelve a notificar hasta cambiar de estado.
  5. Un usuario de una sucursal no ve objetivos, casos ni tareas de otra sucursal (test de permisos).

