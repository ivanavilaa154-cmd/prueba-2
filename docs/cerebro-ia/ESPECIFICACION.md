# CLAUDE.md — Cerebro IA Empresarial (plataforma multi-cliente, agnóstica de sistemas)

> Punto de entrada para Claude Code. Leer completo antes de escribir código. Si algo contradice un doc, manda el doc más específico.

## 1. Qué construimos

Una plataforma SaaS multi-cliente que conecta **cualquier sistema** de una empresa, traduce sus datos a un **modelo canónico único**, calcula **KPIs estandarizados** de Finanzas, Ventas, Inventario, Logística y Marketing, genera **actividades** (tareas concretas con acción, responsable y plazo), mide **procesos estándar** paso a paso, evalúa **objetivos** diarios/semanales/mensuales en tiempo real en un **tablero de gestión**, y lo expone todo a un **agente de IA** que produce reportes, alertas y respuestas.

**Principio rector — agnosticismo total:**
- El código de la plataforma **no menciona ningún sistema, proveedor, marketplace, banco, organismo ni país**. Ni en código, ni en tablas, ni en seeds, ni en KPIs, ni en tests (los tests usan fuentes simuladas con nombres neutros).
- Todo lo específico de un sistema vive en **configuración**: `source.yml` (cómo leerlo) + `mapping.yml` (cómo traducirlo), por cliente y por fuente.
- Conectar un sistema nuevo **no requiere cambios de código**. Si parece requerirlos, primero se extiende un arquetipo o el DSL de forma genérica (con tests), nunca con un caso particular.

**Regla de oro:** la IA nunca calcula a partir de datos crudos. Todo número sale de una consulta a la capa semántica.

## 2. Capas

| Capa | Doc | Qué hace |
|---|---|---|
| 1 — Ingesta | `docs/02` | Motor de conectores por **arquetipo** (API HTTP, SQL, archivos, webhook, agente local, catálogo, plugin). Guarda crudo + estado incremental |
| 2 — Almacén | `docs/03` | Esquemas raw/staging/intermediate/core/marts/ref/ops, multi-tenant, seguridad |
| 3a — Mapeo declarativo | `docs/05` | DSL + compilador: `mapping.yml` → modelos de staging generados; fuente de verdad; validación; asistente IA; matriz de capacidades |
| 3b — Modelo canónico | `docs/04` | El contrato: dims, facts, dominios categóricos, identidad, reglas, marts |
| 4 — Semántica + IA | `docs/06` | Capa semántica, herramientas del agente, reportes, alertas |
| Transversal | `docs/07` | Calidad, onboarding sin código, SLAs, plan por fases, fuentes simuladas |
| KPIs | `docs/08`–`12` | 111 KPIs (FIN 22 · VEN 27 · INV 21 · LOG 19 · MKT 22) con requisitos de datos canónicos |
| Matriz | `docs/13` | Columna canónica → KPIs que habilita |
| **Actividades** | `docs/14` | 8 actividades según el caso (quiebre oculto, pedido sugerido, rotación/sin movimiento, remarcación, promociones, vencimientos, casos trabados en procesos, objetivos en riesgo): 39 casos, 86 acciones. **Ninguna alerta sin acción** |
| **Gestión** | `docs/15` | 6 procesos estándar (venta, logística, cobranza, compra, oportunidad, devolución; 36 pasos con SLA y acción si se vence) · 24 plantillas de objetivos con validación V1-V9, cascada automática, ritmo y proyección · ciclo de tiempo real (≤ 5-15 min) · tablero web de gestión |

## 3. Stack de la plataforma (herramientas propias)

Python 3.12 (conectores, compilador de mapeos, servidor IA con FastMCP, motor de objetivos) · React/Next.js (tablero de gestión) · Dagster (orquestación) · PostgreSQL 16 (almacén, migrable) · dbt-core + dbt-utils + dbt-expectations + elementary · Cube (capa semántica) · gestor de secretos · docker-compose (`make up`).

## 4. Estructura del repo

```
cerebro-ia/
├── CLAUDE.md
├── docs/                              # esta especificación
├── schemas/                           # JSON Schema de source.yml y mapping.yml (generar desde docs/02 y docs/05)
├── plantillas/fuente_ejemplo/         # plantillas vacías de source.yml / mapping.yml
├── perfiles/                          # (vacío) perfiles reutilizables que crean los operadores
├── sources/<tenant_slug>/<source_id>/ # configuración por cliente (fuera del repo en producción: en ops.artefacto_config)
├── ingestion/
│   ├── core/                          # base.py (BaseConnector), runner, estado, escritura raw
│   ├── arquetipos/                    # http_api/, sql_database/, file_import/, webhook/, push_agent/, conector_catalogo/
│   ├── plugins/                       # (vacío) solo casos excepcionales, fuera del núcleo
│   └── webhooks/                      # servicio receptor genérico
├── mapping_compiler/                  # parser DSL → SQL, validador, generador de modelos dbt, vista previa
├── orchestration/                     # Dagster: assets generados desde ops.tenant_fuente
├── warehouse/dbt/
│   ├── models/staging/generated/      # GENERADO por el compilador (no editar)
│   ├── models/intermediate/           # genérico por entidad
│   ├── models/core/                   # modelo canónico
│   ├── models/marts/
│   ├── seeds/                         # ← copiar seeds/ de este paquete
│   └── macros/
├── semantic/                          # Cube
├── kpis/src/                          # FUENTE DE VERDAD de KPIs (editar acá)
├── kpis/registry/                     # generado
├── actividades/src/actividades.yml    # FUENTE DE VERDAD de actividades (casos → acciones)
├── actividades/registry/              # generado
├── gestion/src/                       # FUENTE DE VERDAD: procesos.yml, objetivos.yml, tiempo_real_y_tablero.md
├── gestion/registry/                  # generado
├── app/                               # tablero de gestión web (docs/15 §5)
├── mcp_server/                        # herramientas del agente, prompts, reportes, alertas
├── tools/build_kpis.py                # valida KPIs, actividades, procesos y objetivos contra docs/04 y genera docs/08-15 + registries
└── tests/                             # fuentes simuladas (sim_api, sim_sql, sim_archivos) + e2e
```

## 5. Convenciones obligatorias

- Modelo canónico en español, snake_case, sin tildes. Código interno en inglés está OK.
- Columnas técnicas en toda tabla `core`: `tenant_id`, `source_id`, `source_key`, `_cargado_at`, `_actualizado_at`.
- Montos en moneda base del tenant, sin impuestos indirectos (salvo columnas que lo digan); `_orig`, `moneda_orig`, `tc_aplicado`.
- Fechas UTC; fechas de negocio en zona del tenant.
- Categóricas: solo valores de `ref.valores_canonicos`; la traducción desde origen solo en `value_maps` del mapping.
- Nada de SQL escrito a mano por fuente: staging siempre generado por el compilador.
- Multi-tenant en tres barreras (RLS, capa semántica, token del servidor IA). Un bug de aislamiento es crítico.
- Datos personales hasheados en `core`; la IA nunca los recibe.
- **Ninguna alerta sin acción:** toda actividad asigna cada detección a un caso con acciones prescriptas (responsable, plazo, criterio de cierre). El build falla si un caso no tiene acción. Lo mismo para procesos (todo paso con SLA tiene `si_vence`) y objetivos (toda plantilla tiene acciones para 'en riesgo' y 'fuera de camino'). La detección y la evaluación son determinísticas; el modelo de lenguaje solo redacta.

## 6. Qué NO hacer

- No crear archivos, tablas, columnas, seeds, condiciones ni tests con nombres de sistemas o países reales.
- No hacer que la IA escriba SQL libre.
- No mezclar datos de tenants en consultas, caché o prompts.
- No convertir monedas con la cotización de hoy para hechos históricos.
- No publicar un mapping sin validación y aprobación humana.
- No duplicar hechos entre fuentes: usar `ops.fuente_de_verdad` + `replica_de` (docs/05 §6).

## 7. Orden de trabajo

Seguir las fases de `docs/07 §6` y no avanzar sin cumplir los criterios de aceptación:
0. Fundaciones → 1. Motor genérico de ingesta y mapeo (validado con 3 fuentes simuladas distintas sin código específico) → 2. KPIs + semántica + IA → 2b. Actividades → 2c. Procesos, objetivos y tablero (docs/15 §7) → 3. Operación a escala.

Primera sesión: leer docs 01 → 02 → 03 → 04 → 05 → 06 → 07; correr `python3 tools/build_kpis.py` (debe decir `OK: 111 KPIs`, `OK: 6 procesos · 36 pasos · 24 plantillas…` y `OK: 8 actividades · 39 casos · 86 acciones`); ejecutar Fase 0.
