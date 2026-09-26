# 07 — Calidad de datos, onboarding de clientes y plan de implementación

## 1. Tests automáticos del modelo (todas las tablas `core`)

Generados por el compilador de mapeos (staging) y definidos una vez por entidad (core):

| Tipo | Regla |
|---|---|
| Unicidad | `(tenant_id, source_id, source_key)` y PK |
| No nulos | `tenant_id`, PK, columnas de `requisitos_entidad.yml` |
| Integridad referencial | FKs → dims (se admite `'-1'`) |
| Valores aceptados | toda columna categórica ∈ `ref.valores_canonicos` de su dominio |
| Rangos | importes ≥ 0 donde el signo va aparte; `tc_aplicado > 0`; `probabilidad` 0-100; fechas de hechos no futuras |
| Consistencia | `importe_neto ≈ importe_bruto − importe_descuento`; comprobante `importe_neto ≈ gravado + no gravado + exento`; `saldo = debe − haber` |
| Aislamiento | ninguna fila con `tenant_id` inexistente o inactivo; test e2e con dos tenants que verifica que ninguna herramienta devuelve datos cruzados |

## 2. Controles de calidad de negocio (DQ-*)

Resultados en `ops.dq_resultado(tenant_id, dq_id, fecha, severidad, valor, detalle)`; los KPIs afectados los informan en `metadata`.

| ID | Control | Umbral default | Severidad | Afecta |
|---|---|---|---|---|
| DQ-01 | Frescura de cada fuente vs su SLA | > SLA; crítica si > 2× | alta/crítica | KPIs de esa fuente |
| DQ-02 | Volumen diario vs mediana de 28 días (mismo día de semana) | < 30 % o > 300 % | alta | según entidad |
| DQ-03 | Huecos en series diarias | ≥ 1 día | alta | series |
| DQ-04 | Doble conteo: registros de dos fuentes con `es_fuente_verdad` para el mismo hecho | > 0 | crítica | ventas, marketing |
| DQ-05 | Registros de fuentes no-verdad sin match con la fuente de verdad tras 72 h | > 2 % | alta | ventas |
| DQ-06 | Valores sin traducir (`ops.valores_sin_mapear`) | nuevos > 0 | media | según dominio |
| DQ-07 | % de venta sin costo | > 5 % | alta | márgenes, CMV, GMROI, LTV |
| DQ-08 | Cuentas contables con movimiento sin `codigo_estandar` | > 0 | alta | EERR |
| DQ-09 | Continuidad de saldos de tesorería (saldo anterior + movimientos = saldo informado) | ≠ 0 | alta | caja |
| DQ-10 | Movimientos de tesorería sin clasificar (`otros`) | > 15 % del volumen | media | flujo, gastos |
| DQ-11 | Diferencias con registro fiscal oficial (FIN-18) | > 0 en ventas | alta | ventas contables, impuestos |
| DQ-12 | Stock negativo | > 0 SKUs | media | inventario |
| DQ-13 | Productos sin identidad unificada entre fuentes | > 1 % de la venta | alta | producto, inventario |
| DQ-14 | Órdenes de compra abiertas > 180 días | > 0 | baja | compras |
| DQ-15 | Pedidos online sin UTM ni referrer | > 40 % | media | atribución |
| DQ-16 | Transacciones de analítica web vs pedidos online del día | desvío > 20 % | alta | conversión web |
| DQ-17 | Montos sin tipo de cambio disponible | > 0 | alta | todo lo monetario |
| DQ-18 | Índice de precios o TC faltante para el período consultado | falta | media | variantes real / otra moneda |
| DQ-19 | Envíos abiertos sin novedades > 5 días | > 3 % | media | logística |
| DQ-20 | Σ líneas vs cabecera de pedido | desvío > 1 % | alta | ventas |
| DQ-21 | Renglones de listas de proveedores sin producto vinculado | > 2 % de la lista | alta | ACT-02, ACT-04 |
| DQ-22 | Productos perecederos recibidos sin fecha de vencimiento | > 0 | media | ACT-06, INV-20 |
| DQ-23 | Productos activos sin precio de venta vigente o sin política de precio aplicable | > 0 | media | ACT-04, VEN-27 |
| DQ-24 | Punto de venta sin ventas en un día hábil de apertura | > 0 | alta | ACT-01 (evita falsos positivos) |

## 3. Onboarding de un cliente (sin código)

Flujo en la interfaz de operador + CLI `cerebro`. Cada paso tiene estado en `ops.onboarding_paso`.

1. **Alta del tenant:** país, moneda base, zona horaria, inicio de ejercicio, tasa de impuesto indirecto por defecto, horario operativo, series de TC e índice de precios a usar, contexto inflacionario (sí/no).
2. **Inventario de sistemas por rol:** para cada sistema del cliente se registra qué roles cumple (docs/01 §3) — sin importar su marca.
3. **Conexión:** por cada fuente, `source.yml` (desde plantilla o perfil existente) + credenciales en el gestor de secretos → `cerebro fuente probar`.
4. **Descubrimiento:** `cerebro fuente descubrir` → muestra y esquema inferido.
5. **Mapeo:** asistente de IA propone `mapping.yml` → validación → vista previa → corrección humana → publicación (docs/05 §7-9).
6. **Fuente de verdad** por entidad donde haya superposición (`ops.fuente_de_verdad`) y reglas de réplica (`replica_de`).
7. **Traducciones de volumen:** plan de cuentas → estándar, depósitos, sucursales/puntos de emisión, categorías de gasto de los principales proveedores, reglas de clasificación de tesorería. El sistema propone; un humano valida.
8. **Carga histórica:** 24 meses de ventas/contabilidad; lo que permitan las fuentes para publicidad/analítica; stock actual + 12 meses de movimientos.
9. **Matriz de capacidades:** revisar `ops.kpi_capacidad` con el cliente: qué KPIs quedan disponibles, cuáles degradados y qué haría falta conectar para el resto.
10. **Validación de números con el cliente** (criterio de salida): venta del último mes cerrado ±1 % vs su propio reporte; saldos de tesorería = extractos; stock valorizado ±2 %; gasto publicitario = plataforma ±1 %.
11. **Configuración de KPIs:** umbrales, SLAs, caja mínima, objetivos, presupuesto.
11b. **Configuración de actividades:** responsables por rol y sucursal (`ops.responsable`), política de precios por categoría (`ops.politica_precio`: margen objetivo y mínimo, redondeo), política de producto (días de retiro antes de vencimiento, cobertura objetivo, nivel de servicio), días de pedido y mínimos de proveedores. Las **listas de precios de proveedores** se conectan como fuentes `file_import` (una por formato de lista; se puede reutilizar como perfil) con rol `precios_compra`.
12. **Activación** de reportes y alertas.

**Perfiles:** si el sistema de un cliente nuevo ya fue mapeado para otro cliente, el operador puede partir del perfil guardado (docs/05 §2) y solo ajustar lo propio. Objetivo de servicio: primer reporte en ≤ 10 días hábiles.

## 4. SLAs de frescura

Se configuran por fuente en `source.yml` (`frecuencia`) y por tenant. Defaults sugeridos por rol:

| Rol | SLA |
|---|---|
| ventas (online) | 1 h |
| ventas (gestión), crm, cuentas_corrientes | 2 h |
| logistica, pasarela_pagos | 3 h |
| inventario | foto 24 h, movimientos 2 h |
| tesoreria | 1 día hábil |
| publicidad, analitica_web, email_marketing | 24 h (+ relectura de ventana de atribución) |
| facturacion, registro_fiscal_oficial, contabilidad | 24 h |
| referencias | 1 día hábil (TC), 5 días post-publicación (índice) |

## 5. Observabilidad

- Orquestador: estado por asset y tenant; alertas internas ante fallas repetidas o credenciales vencidas.
- dbt + elementary: tests y anomalías de volumen.
- Servidor IA: latencia y errores por herramienta, consultas por tenant/usuario, tokens por reporte, tasa de números no encontrados en post-validación (objetivo 0).
- Panel interno por tenant: frescura, DQ abiertos, valores sin mapear, capacidad de KPIs, uso.

## 6. Plan por fases (criterios de aceptación)

### Fase 0 — Fundaciones
- `make up` levanta almacén, orquestador, capa semántica, servidor IA.
- Esquemas, roles, RLS, `ops.*`, seeds (`ref_valores_canonicos`, `ref_plan_cuentas_estandar`), `ref.fecha`.
- `tools/build_kpis.py` en CI.
- **Aceptación:** test de aislamiento con 2 tenants sintéticos en verde.

### Fase 1 — Motor genérico de ingesta y mapeo
- `BaseConnector` + arquetipos `http_api`, `sql_database`, `file_import`, `webhook`; JSON Schemas de `source.yml` y `mapping.yml`.
- Compilador de mapeos completo (todas las funciones del DSL de docs/05 §4) con suite de tests por función.
- Modelos `intermediate` genéricos por entidad (unión, identidad, fuente de verdad) y `core`.
- **Aceptación:** con **fuentes simuladas** (§7) de tres "sistemas" ficticios de estructuras distintas (API paginada con arrays anidados, base SQL relacional, archivos planilla), la plataforma produce el mismo `core` esperado **sin escribir código específico**, solo YAML.

### Fase 2 — KPIs, capa semántica e IA
- Marts, cubes y medidas de los 107 KPIs; matriz de capacidades; servidor MCP con todas las herramientas; reportes y alertas.
- **Aceptación:** cada KPI tiene test e2e con valor esperado; con una fuente simulada removida, los KPIs afectados pasan a `no_disponible`/`degradado` y el agente lo explica correctamente.

### Fase 2b — Actividades
- Marts `ven__venta_diaria_sku_punto` y `act__*`, motor de actividades (docs/06 §5), herramientas de actividades del servidor IA, artefactos (pedido sugerido, remarcación, etiquetas, fichas de promoción).
- **Aceptación:** con las fuentes simuladas, cada caso de cada actividad (31 casos) tiene un escenario de prueba que lo dispara y verifica: caso asignado, acciones, responsable, plazo, cierre automático y deduplicación; y un escenario negativo por cada exclusión.

### Fase 3 — Operación a escala
- Asistente de mapeo con IA, interfaz de onboarding, perfiles reutilizables, `push_agent`, arquetipo `conector_catalogo`.
- **Aceptación:** un sistema nunca visto se conecta y publica su mapping en < 1 día de trabajo de operador, sin cambios de código.

## 7. Fuentes simuladas y tests e2e

`tests/fixtures/` contiene un generador de datos que expone **tres sistemas ficticios** con nombres neutros (`sim_api`, `sim_sql`, `sim_archivos`) y estructuras deliberadamente distintas:
- `sim_api`: servidor HTTP local con OAuth simulado, paginación por cursor, precios con impuesto incluido, fechas ISO con zona, arrays anidados de líneas, webhooks.
- `sim_sql`: base relacional con cabecera/renglones, códigos de estado numéricos, fechas sin zona, montos con signo en notas de crédito.
- `sim_archivos`: CSV/XLSX con decimales con coma, encabezados en otra fila, extractos de movimientos sin id.

Incluyen además: listas de precios de proveedores en planillas con formatos distintos (bonificaciones en cascada, unidades de compra ≠ de venta), historial de precios de venta, promociones de varias mecánicas (una que rinde, una que pierde margen, una que canibaliza), lotes perecederos con vencimientos próximos, y un producto de alta rotación que deja de venderse con stock en sistema (quiebre oculto).
Incluyen casos borde: duplicados entre fuentes (réplicas), documentos en moneda extranjera, cancelaciones, devoluciones, stock negativo, UTMs vacías, días sin datos, transferencias internas, valores de estado no mapeados.
Cada KPI tiene su valor esperado en `tests/e2e/esperados/<KPI>.json`. El CI ejecuta: fuentes simuladas → ingesta → compilación de mappings → dbt → capa semántica → `consultar_kpi` y compara.
