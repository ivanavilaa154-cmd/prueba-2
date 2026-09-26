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
