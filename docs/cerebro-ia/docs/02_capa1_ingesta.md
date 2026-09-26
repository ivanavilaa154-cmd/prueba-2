# 02 — Capa 1: Ingesta genérica

> Objetivo: leer **cualquier** sistema sin escribir código específico. Un sistema se conecta declarando en `source.yml` a qué **arquetipo** pertenece y cómo se parametriza. El motor ejecuta el arquetipo.
> La capa 1 **no interpreta** los datos: no renombra, no convierte monedas, no filtra por lógica de negocio. Solo trae registros completos, sin pérdida, y guarda el estado incremental.

## 1. Arquetipos de conexión

| Arquetipo | Cuándo | Componentes configurables |
|---|---|---|
| `http_api` | El sistema expone una API web (REST/JSON, XML, GraphQL) | autenticación, endpoints por stream, paginación, incremental, ruta de registros, streams hijos, límites de tasa |
| `sql_database` | Acceso de lectura a la base del sistema | driver, conexión, consulta por stream con parámetro de cursor, clave primaria |
| `file_import` | El sistema solo exporta archivos (CSV, XLSX, JSON, XML, TXT de ancho fijo, formatos bancarios) | origen del archivo, parser, hoja, filas de encabezado, formato de números y fechas, deduplicación |
| `webhook` | El sistema avisa cambios por eventos | ruta, validación de firma, qué stream refrescar o si el evento se guarda como registro |
| `push_agent` | El sistema está en la red interna del cliente sin acceso externo | se instala un agente local que ejecuta `sql_database` o `file_import` y **empuja** registros por HTTPS |
| `conector_catalogo` | Existe un conector open source ya hecho y confiable para ese sistema | referencia al conector + su configuración; la salida se normaliza al mismo formato crudo |
| `plugin` | Caso excepcional que ningún arquetipo cubre (protocolos propietarios, firmas criptográficas, SOAP complejo) | clase Python que implementa `BaseConnector`; vive en `ingestion/plugins/<nombre>/`, fuera del núcleo |

Regla: **antes de escribir un `plugin`, demostrar que no alcanza con un arquetipo declarativo** (dejar constancia en el PR).

## 2. Interfaz común (`ingestion/core/base.py`)

Todos los arquetipos y plugins implementan la misma interfaz, para que el orquestador los trate igual:

```python
class BaseConnector(ABC):
    def __init__(self, tenant_id: str, source_id: str, spec: SourceSpec, secrets: SecretResolver): ...
    def check(self) -> CheckResult                                # credenciales, permisos, conectividad
    def discover(self) -> list[StreamSchema]                     # streams disponibles + esquema inferido de una muestra
    def read(self, stream: str, state: StreamState | None) -> Iterator[RawRecord]
    def next_state(self, stream: str) -> StreamState              # cursor a persistir tras la lectura exitosa
    def sample(self, stream: str, n: int = 50) -> list[dict]      # muestra para el asistente de mapeo (docs/05 §9)
```

`RawRecord` = `{stream, source_key, payload: dict, cursor_value, extraido_at}`. `source_key` se obtiene con `primary_key` del stream (expresión JSONPath o columnas).

## 3. Especificación de fuente (`sources/<tenant_slug>/<source_id>/source.yml`)

```yaml
source_id: ventas_principal          # nombre libre que elige el operador (NO el nombre comercial del sistema)
arquetipo: http_api
roles: [ventas, inventario]          # docs/01 §3
zona_horaria_origen: UTC             # cómo vienen las fechas sin offset
moneda_default: null                 # si el origen no informa moneda
autenticacion:
  tipo: oauth2_authorization_code    # api_key_header | api_key_query | bearer | basic | oauth2_client_credentials | oauth2_authorization_code | custom_header | certificado_cliente
  secreto: vault://tenants/{tenant}/ventas_principal
  token_url: https://…/oauth/token
  refresh: automatico
base_url: https://…/api/v1
limites: {requests_por_minuto: 120, concurrencia: 2, reintentos: 5, backoff: exponencial}
streams:
  - nombre: pedidos
    endpoint: /orders
    metodo: GET
    registros_en: $.results                      # JSONPath al array de registros
    primary_key: $.id
    paginacion: {tipo: pagina, parametro: page, tamano_parametro: per_page, tamano: 200, fin: vacio}
      # tipos: pagina | offset | cursor_token (token_en: $.next_cursor, parametro: cursor) | link_header | url_siguiente (en: $.next) | ventana_fechas (dias: 7)
    incremental:
      cursor: $.updated_at                       # campo del registro que avanza
      parametro: updated_since                   # cómo se envía al origen
      formato: iso8601
      lookback: 2h                               # re-lee una ventana para no perder actualizaciones tardías
    frecuencia: 1h
  - nombre: pedido_detalle                       # stream hijo
    padre: pedidos
    endpoint: /orders/{padre.id}/items
    registros_en: $.items
    primary_key: [$.order_id, $.id]
  - nombre: metricas_diarias                     # recalculables hacia atrás
    endpoint: /reports/daily
    parametros: {desde: "{ventana_inicio:%Y-%m-%d}", hasta: "{ventana_fin:%Y-%m-%d}"}
    incremental: {tipo: ventana_fechas, dias_por_llamada: 7, relectura_dias: 28}
```

Variante `sql_database`:

```yaml
arquetipo: sql_database
conexion: {driver: mssql+pyodbc | postgresql | mysql | oracle | …, secreto: vault://…, solo_lectura: true}
streams:
  - nombre: comprobantes
    consulta: "select * from <tabla> where <columna_modificacion> > :cursor order by <columna_modificacion>"
    primary_key: [<col1>, <col2>]
    incremental: {cursor: <columna_modificacion>, inicial: "2020-01-01"}
    frecuencia: 1h
```

Variante `file_import`:

```yaml
arquetipo: file_import
origen: {tipo: carga_manual | sftp | casilla_email | bucket, ruta: "…", patron: "*.csv"}
parser: {formato: csv | xlsx | json | xml | ancho_fijo, delimitador: ";", decimal: ",", miles: ".", encoding: latin-1, hoja: 0, fila_encabezado: 1, saltear_filas_finales: 2, formato_fecha: "%d/%m/%Y"}
streams:
  - nombre: movimientos
    primary_key: hash                # hash de columnas si el archivo no trae id
    columnas_hash: [Fecha, Importe, Descripcion, Saldo]
```

Validación: `source.yml` se valida contra `schemas/source.schema.json` (Claude Code lo genera desde este doc). Los secretos **nunca** van en el YAML: solo referencias.

## 4. Almacenamiento crudo

Cada stream escribe en `raw_<tenant_slug>.<source_id>__<stream>`:

| Columna | Tipo | Descripción |
|---|---|---|
| `_raw_id` | uuid | |
| `source_key` | text | id del registro en origen (según `primary_key`) |
| `_payload` | jsonb | registro **completo** tal como vino (archivos: fila convertida a objeto con los encabezados) |
| `_hash` | text | sha256 del payload normalizado; si no cambió respecto de la última versión no se inserta |
| `_cursor` | text | valor del cursor |
| `_extraido_at` | timestamptz | |
| `_ejecucion_id` | uuid | lectura que lo trajo (trazabilidad) |

Append-only. La versión vigente de cada registro se resuelve después (último `_extraido_at` por `source_key`). Registros borrados en origen: si el arquetipo lo permite (endpoint de eliminados, flag, comparación de claves en full refresh) se inserta un registro con `_payload = {"_eliminado": true}`.

## 5. Estado y ejecución

- `ops.stream_estado(tenant_id, source_id, stream, cursor, ultima_ejecucion, ultimo_exito, registros_ultima, error)`.
- El cursor se confirma **solo** si la escritura en raw fue exitosa (at-least-once; el dedupe por `_hash` hace idempotente la re-lectura).
- Primera carga: `inicial` configurable (default 24 meses) en lotes para no saturar al origen.
- Reintentos con backoff; errores 401/403 → marca la fuente como "credenciales vencidas" y avisa al operador; 429 → respeta `Retry-After`.
- Logs estructurados JSON: `tenant_id, source_id, stream, registros, bytes, duracion_ms, error`.

## 6. Webhooks

Servicio `ingestion/webhooks` con una ruta por fuente: `/hooks/{tenant_slug}/{source_id}`. Configuración en `source.yml`:

```yaml
webhook:
  firma: {tipo: hmac_sha256, header: X-Signature, secreto: vault://…}   # o: token_en_query, ninguna (desaconsejado)
  evento_en: $.topic
  acciones:
    - {si_evento: "order.*", refrescar_stream: pedidos, id_en: $.resource_id}
    - {si_evento: "*", guardar_como_stream: eventos}
```

Principio: el webhook **dispara** una lectura por API (fuente de verdad); solo se guarda el evento como dato cuando el origen no ofrece API de consulta.

## 7. Agente local (`push_agent`)

Contenedor o servicio instalable en la red del cliente. Lee con `sql_database`/`file_import` usando una copia local de `source.yml`, y envía lotes firmados a `POST /ingesta/{tenant}/{source_id}/{stream}` (token de agente rotativo). Autoactualizable, con cola local si no hay conexión. Mismo formato `RawRecord`.

## 8. Descubrimiento asistido

`cerebro fuente descubrir <tenant> <source_id>` ejecuta `check()`, `discover()` y `sample()` de cada stream y guarda en `ops.fuente_muestra` el esquema inferido (rutas JSON, tipos, % nulos, ejemplos, cardinalidad de campos categóricos). Ese perfil es la entrada del asistente de mapeo (docs/05 §9).

## 9. Referencias externas (tipo de cambio, índice de precios, feriados)

Se conectan **igual que cualquier fuente** (normalmente `http_api` o `file_import`) con rol `referencia_*` y un `mapping.yml` hacia `ref.tipo_cambio`, `ref.indice_precios`, `ref.feriado`. La plataforma no trae proveedores precargados: se configuran por país/tenant.
