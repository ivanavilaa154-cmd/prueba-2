# 06 — Capa 4: Semántica, agente IA, reportes y alertas

> Todo en esta capa trabaja sobre el modelo canónico. No existe ninguna referencia a sistemas de origen: si un dato no está en `core`/`marts`, esta capa no lo ve.

## 1. Registry de KPIs

- Fuente de verdad: `kpis/src/<area>.yml` (definición, fórmula de referencia, requisitos de datos, alertas) + `kpis/src/requisitos_entidad.yml`.
- `tools/build_kpis.py` valida contra el DDL de docs/04 y genera docs/08-13, `kpis/registry/kpi_<ID>.yml` y `kpis/catalogo_kpis.csv`.
- CI: además, cada `cube` del registry debe existir como medida/vista en `semantic/model/` con `meta.kpi_id` (test `tests/test_registry_semantica.py`).

## 2. Capa semántica (Cube)

### 2.1 Organización

```
semantic/
├── cube.js                      # contexto de seguridad, reescritura de consultas, aislamiento de caché
└── model/
    ├── cubes/                   # un cube por tabla canónica o mart:
    │     ventas (fct_pedido) · ventas_lineas · devoluciones · clientes · crm · leads · presupuesto
    │     eerr (marts.fin__eerr_mensual) · tesoreria · cxc · cxp · cobros · impuestos · control
    │     stock · reposicion · compras · preparacion · envios · ads · web · email · marketing
    │     dims/ (producto, deposito, sucursal, canal, vendedor, campana, fecha_tenant, …)
    └── views/                   # scorecards: vendedores, transportistas, marketing, resumen_ejecutivo
```

### 2.2 Reglas de modelado

1. Una medida por KPI con el nombre del campo `cube` del registry y `meta.kpi_id`.
2. Ratios como `type: number` con `sum(a) / nullif(sum(b), 0)`; nunca promedios de ratios.
3. Segmento `pedido_valido` (docs/04 §7.3) en `ventas` y `ventas_lineas`, aplicado por defecto.
4. Snapshots (stock, saldos): con rango de fechas se usa la última fecha del rango.
5. Variantes monetarias `<medida>_real` (índice de precios del tenant) y conversión a otra moneda (`ref.tipo_cambio` a la fecha del hecho) implementadas dentro del SQL del cube.
6. KPIs con **variantes** (requisitos `alternativas`, ej. modo contable/gestión): una medida por variante + medida "auto" que elige la primera disponible según `ops.kpi_capacidad`; el modo usado vuelve en metadata.
7. Pre-agregaciones por tenant; `refreshKey` = `max(_actualizado_at)` de la tabla base.

### 2.3 Ejemplo

```yaml
cubes:
  - name: ventas
    sql_table: core.fct_pedido
    segments:
      - name: pedido_valido
        sql: "{CUBE}.es_fuente_verdad and {CUBE}.estado not in ('borrador','cancelado') and coalesce({CUBE}.estado_pago,'aprobado') not in ('rechazado','pendiente')"
    measures:
      - {name: venta_neta, sql: importe_neto, type: sum, format: currency, meta: {kpi_id: VEN-01}}
      - {name: pedidos, sql: pedido_id, type: count_distinct, meta: {kpi_id: VEN-02}}
      - {name: ticket_promedio, sql: "{venta_neta} / nullif({pedidos}, 0)", type: number, meta: {kpi_id: VEN-03}}
      - name: contribucion
        sql: >
          {CUBE}.importe_neto - coalesce({CUBE}.costo_mercaderia,0) - coalesce({CUBE}.comision_canal,0)
          - coalesce({CUBE}.costo_financiacion,0) - coalesce({CUBE}.costo_envio_vendedor,0) + coalesce({CUBE}.importe_envio_cobrado,0)
        type: sum
        meta: {kpi_id: VEN-09}
    dimensions:
      - {name: pk, sql: "{CUBE}.tenant_id || {CUBE}.pedido_id", type: string, primary_key: true}
      - {name: fecha, sql: fecha_pedido, type: time}
      - {name: canal, sql: canal_id, type: string}
      - {name: canal_marketing, sql: canal_marketing, type: string}
```

### 2.4 Seguridad

```js
module.exports = {
  checkAuth: (req, auth) => { /* valida JWT emitido por el backend: {tenant_id, rol, areas} */ },
  queryRewrite: (query, { securityContext }) => {
    if (!securityContext.tenant_id) throw new Error('tenant_id requerido');
    agregarFiltroTenantATodosLosCubes(query, securityContext.tenant_id);
    validarAreasPermitidas(query, securityContext.areas);
    return query;
  },
  contextToAppId: ({ securityContext }) => `tenant_${securityContext.tenant_id}`,
  contextToOrchestratorId: ({ securityContext }) => `tenant_${securityContext.tenant_id}`,
  // conexión con rol sin BYPASSRLS y SET app.tenant_id por contexto → segunda barrera (RLS)
};
```

## 3. Servidor de herramientas para el agente (MCP)

### 3.1 Principios
- Solo herramientas de alto nivel; **no existe SQL libre**.
- `tenant_id` y áreas permitidas salen del token, nunca de parámetros.
- Solo se ofrecen KPIs con `ops.kpi_capacidad.estado in ('disponible','degradado')`.
- Toda respuesta numérica trae `metadata`: `kpi_id`, definición corta, período, filtros, moneda, ajuste, variante/modo, frescura por fuente, advertencias de calidad y casos borde activados.

### 3.2 Herramientas

| Herramienta | Parámetros | Devuelve |
|---|---|---|
| `listar_kpis` | `area?`, `busqueda?` | KPIs disponibles/degradados con dimensiones habilitadas |
| `describir_kpi` | `kpi_id` | definición, fórmula resumida, requisitos, casos borde, relacionados, estado de capacidad |
| `consultar_kpi` | `kpi_id`, `desde`, `hasta`, `granularidad?`, `dimensiones?`, `filtros?`, `comparar?` (periodo_anterior, anio_anterior, presupuesto, mismo_periodo_a_la_fecha), `moneda?`, `ajuste?`, `parametros?`, `top_n?`, `orden?` | serie/tabla + totales + comparación + metadata |
| `comparar_kpis` | `kpi_ids[]` (≤ 6) + mismos parámetros | tabla combinada |
| `explicar_variacion` | `kpi_id`, `periodo`, `comparar`, `dimensiones_candidatas?` | drivers de la variación (§3.4) |
| `detalle_registros` | `kpi_id`, filtros, `limite` | filas de detalle sin datos personales (solo KPIs con `meta.drilldown`) |
| `estado_datos` | — | fuentes conectadas y sus roles, frescura, controles de calidad fallidos, valores sin mapear, KPIs no disponibles y qué rol de fuente los habilitaría |
| `alertas_activas` | `area?`, `severidad_min?` | alertas abiertas con contexto |
| `generar_reporte` | `plantilla`, `periodo`, `destinatario_rol?` | reporte + JSON de datos |
| `listar_actividades` | `tipo?`, `estado?`, `responsable_rol?`, `sucursal?`, `prioridad_min?` | tareas ordenadas por puntaje, con caso y acciones |
| `detalle_actividad` | `actividad_id` | evidencia, acciones con plazos, historial, artefactos (pedido sugerido, remarcación, etiquetas) |
| `actualizar_actividad` | `actividad_id`, `estado`, `resolucion?`, `comentario?`, `asignado_a?` | única escritura permitida al agente: sobre `ops.actividad`, nunca sobre sistemas del cliente; valida resolución contra la actividad |
| `resumen_actividades` | `periodo` | abiertas/vencidas por rol y sucursal, impacto resuelto, precisión por actividad |
| `consultar_objetivos`, `detalle_objetivo`, `proponer_objetivo`, `estado_proceso`, `casos_trabados`, `registrar_evento_proceso` | ver docs/15 §6 | gestión de procesos y objetivos |

### 3.3 Instrucciones de sistema del agente (plantilla `mcp_server/prompts/sistema.md`)
1. Todo número sale de una herramienta; si ninguna lo responde, decirlo y, si aplica, qué dato/rol de fuente falta (`estado_datos`).
2. Citar período, moneda, nominal/real, y frescura si algún dato tiene más de 24 h.
3. Si el tenant tiene configurado contexto inflacionario (`ops.tenant.preferencias.reportar_real = true`), toda comparación monetaria entre períodos se reporta también en términos reales.
4. No sumar métricas de plataformas publicitarias entre sí; distinguir "según la plataforma" de "venta real".
5. Mencionar advertencias de calidad cuando afectan la conclusión, y la variante usada cuando el KPI tiene variantes.
6. Para "¿por qué?" usar `explicar_variacion` antes de opinar.
7. Recomendaciones marcadas como sugerencias con el dato que las sustenta; el agente no ejecuta acciones en sistemas del cliente.
8. Sin datos personales, sin datos de otros tenants, sin inventar nombres.
9. Idioma y tono según `ops.tenant.preferencias`.

### 3.4 `explicar_variacion`
1. Consultar el KPI en ambos períodos por cada dimensión candidata (defaults por área).
2. Aditivos: contribución de cada miembro al Δ total, ordenada por |contribución|.
3. Ratios: descomposición mix vs tasa: Δ = Σ(w₁ᵢ − w₀ᵢ)·r₀ᵢ + Σ w₁ᵢ·(r₁ᵢ − r₀ᵢ).
4. Venta: efecto precio / volumen / mix sobre líneas de producto.
5. Top 5 drivers por dimensión + la dimensión que más concentra el Δ.

## 4. Reportes

Plantillas en `reports/templates/*.yml` (`id`, `frecuencia`, `roles_destino`, `secciones[]` con KPIs, dimensiones, comparaciones e instrucción de redacción, `formato`). Una sección cuyo KPI no está disponible para el tenant se omite automáticamente (y se lista al final como "no disponible por falta de datos").

| Plantilla | Frecuencia | Contenido |
|---|---|---|
| `diario_operativo` | diaria | venta de ayer vs mismo día semana anterior por canal, proyección del mes, backlog y despachos atrasados, quiebres clase A, caja disponible, inversión y MER de ayer, alertas críticas |
| `semanal_gerencial` | semanal | semana vs anterior y vs año anterior (real), top/bottom productos, clientes nuevos y recompra, OTD y costo logístico, cobertura y sobrestock, MER/CAC/ROAS real, 3 mayores variaciones explicadas |
| `mensual_ejecutivo` | mensual | EERR vs presupuesto, caja/runway/proyección, capital de trabajo, rentabilidad por canal, salud de inventario, logística, marketing, 5 recomendaciones |
| `area_<area>` | semanal | todos los KPIs disponibles del área con alertas y drill-downs |
| `cobranzas`, `compras_reposicion` | diaria | CxC vencida por vendedor; SKUs a reponer y OCs atrasadas |

Pipeline:
1. El orquestador ejecuta la plantilla por tenant → todas las consultas vía las mismas herramientas (determinístico, sin modelo de lenguaje) → `reporte_datos.json` en `ops.reporte_ejecucion`.
2. El modelo de lenguaje recibe **solo** ese JSON + instrucciones de redacción.
3. **Post-validación:** todo número del texto debe existir en el JSON (tolerancia de redondeo); si no, se regenera o se marca para revisión.
4. Render (plantillas HTML/PDF) con gráficos generados desde el JSON.
5. Envío por los canales configurados en `ops.tenant.preferencias`; registro en `ops.reporte_envio`.

## 5. Motor de actividades (docs/14)

1. Tras la carga diaria (y en los horarios de cada actividad), el orquestador ejecuta los marts `act__*` por tenant; **solo corren las actividades cuyos requisitos están disponibles** (misma lógica de capacidad que los KPIs, `ops.kpi_capacidad` con `kpi_id = ACT-xx`).
2. Cada candidato se asigna al **primer caso** cuya condición cumple (orden declarado en el YAML); si ninguno aplica, va a `ops.actividad_descartes`.
3. Se hace upsert en `ops.actividad` por `clave_dedupe`: si ya hay una abierta se actualiza evidencia/impacto (y se escala prioridad si empeoró); si no, se crea con las **acciones del caso**, `fecha_limite` = detección + plazo de la acción 1, `responsable_rol` = responsable de la acción 1, y asignación según `ops.responsable` (rol + sucursal).
4. **Cierre automático:** en cada corrida se evalúa el criterio de cierre de las abiertas (ej. volvió a venderse, existe OC, precio cargado) → `cerrada_automatica`.
5. **Vencimiento y escalamiento:** tarea sin resolver pasado su plazo → `vencida` y notificación al rol superior (repositor → encargado_sucursal → gerente_operaciones → gerente_general; comprador/comercial → gerente_general).
6. **Artefactos:** pedido sugerido por proveedor, archivo de remarcación, listado de etiquetas por sucursal/pasillo y ficha de promoción se generan como CSV/XLSX/PDF desde los marts (sin modelo de lenguaje) y se adjuntan en `artefacto_url`. Cargarlos en el sistema de gestión del cliente es una acción humana (fases 1-2).
7. **Redacción:** el modelo de lenguaje solo redacta el título y el mensaje a partir de la evidencia y las acciones del caso; la post-validación de números (§4) aplica igual.
8. **Notificación:** cada responsable recibe una lista diaria (tope configurable) ordenada por puntaje; las críticas se notifican al momento por el canal configurado.
9. **Aprendizaje:** `precision = confirmadas / cerradas` por actividad y tenant (4 semanas móviles) → sugerencias de ajuste de parámetros al operador (nunca automáticas).

Reportes: `diario_operativo` incluye "tus tareas de hoy" por rol; `semanal_gerencial` incluye tareas vencidas, impacto resuelto en dinero y precisión por actividad.

## 6. Alertas

- Reglas por defecto = `alertas[]` del registry; overrides por tenant en `ops.tenant_config_kpi`.
- Tipos de condición: umbral, variación vs período (nominal o real), vs promedio móvil, vs presupuesto, sobre miembros de dimensión, persistencia N períodos.
- Frecuencia: críticas cada hora; el resto tras cada carga diaria.
- Deduplicación: `ops.alerta(tenant_id, kpi_id, regla, miembro, severidad, abierta_at, resuelta_at, valor, umbral, contexto)`; no se re-notifica hasta resolverse o escalar.
- **Supresión por calidad:** si la fuente del KPI está desactualizada o con control crítico fallido, se suprime la alerta de negocio y se emite una alerta de datos.
- El modelo de lenguaje redacta el mensaje desde `contexto` (+ `explicar_variacion` opcional) y sugiere una acción.

| Severidad | Canal | Ejemplos |
|---|---|---|
| critica | inmediato (mensajería + email) | caja bajo mínimo, backlog atrasado, caída de conversión en checkout |
| alta | en el día | margen bajo umbral, OTD < 90 % |
| media | resumen diario | fatiga creativa, suba de CPM |
| info | solo reportes | — |
