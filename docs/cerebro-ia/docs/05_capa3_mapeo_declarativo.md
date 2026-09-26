# 05 — Capa 3a: Mapeo declarativo (raw → canónico)

> Esta es la pieza que hace que la plataforma funcione con **cualquier sistema**.
> Un `mapping.yml` describe cómo cada stream crudo se convierte en entidades canónicas. Un **compilador** lo valida y genera los modelos SQL (dbt) de `staging`. La plataforma nunca tiene SQL escrito a mano para una fuente.

## 1. Flujo

```
raw_<tenant>.<source_id>__<stream>  ──(mapping.yml)──►  compilador  ──►  staging.stg_<tenant>__<source_id>__<entidad>.sql   (generado)
                                                                              │
                                    intermediate.int_<entidad>  (genérico: une todas las fuentes de la entidad, identidad, fuente de verdad)
                                                                              │
                                                                         core.<entidad>
```

- **staging** (generado por fuente): versión vigente del registro, extracción de campos, tipos, traducción de valores, impuestos, moneda, zona horaria. Salida con **exactamente las columnas canónicas** de la entidad (las no mapeadas = null).
- **intermediate** (código genérico de la plataforma, uno por entidad): `union all` de todos los staging publicados de esa entidad para ese tenant + identidad (docs/04 §6) + fuente de verdad (§6) + cálculos derivados (primera compra, costo, atribución).
- **core**: materialización incremental.

## 2. Archivos por fuente

```
sources/<tenant_slug>/<source_id>/
├── source.yml        # cómo leer (docs/02)
├── mapping.yml       # cómo traducir (este doc)
└── tests.yml         # expectativas propias de esta fuente (opcional)
```

**Perfiles reutilizables:** cuando varios clientes usan el mismo sistema, el operador puede guardar el par `source.yml` + `mapping.yml` como **perfil** en `perfiles/<nombre_elegido>/` y cada tenant lo **hereda** con `extiende: perfiles/<nombre>` sobreescribiendo solo lo propio (value_maps, cuentas, reglas). Los perfiles son datos de configuración, no parte del núcleo, y la plataforma se entrega sin perfiles.

**Listas de precios de proveedores:** cada proveedor suele enviar su lista en un formato propio (planilla, archivo, portal). Cada formato es una fuente `file_import` (o `http_api`) con su `mapping.yml` hacia `fct_lista_precio_proveedor`; el `proveedor_id` puede ser literal en el mapping. Las bonificaciones en cascada se componen con el DSL (`1 - (1 - d1) * (1 - d2) …`). Los códigos del proveedor se vinculan a productos por `claves_identidad` (código de barras, código del proveedor guardado en un mapeo por tabla, o SKU).

## 3. Estructura de `mapping.yml`

```yaml
source_id: ventas_principal
version: 3
extiende: null                        # o perfiles/<nombre>
defaults:
  zona_horaria_origen: UTC
  moneda: "{{ campo('$.currency') }}"          # expresión o literal ISO
  precios_incluyen_impuesto: true              # si true, sin_impuesto() se aplica a los campos marcados `con_impuesto: true`
  tasa_impuesto: tenant_default                # número o 'tenant_default' o expresión por registro
entidades:

  fct_pedido:
    desde: pedidos                             # stream
    filtro: "campo('$.status') != 'draft_test'"   # opcional: descartar registros
    grano: registro                            # registro | explotar('$.path') | agrupar_por(expr)
    clave: "campo('$.id')"                     # → source_key
    campos:
      numero:              "campo('$.number')"
      pedido_at:           "a_timestamp(campo('$.created_at'))"
      fecha_pedido:        "fecha_local(a_timestamp(campo('$.created_at')))"
      confirmado_at:       "a_timestamp(campo('$.paid_at'))"
      estado_origen:       "concat(campo('$.status'), '|', campo('$.payment_status'))"
      estado:              {valor: "concat(campo('$.status'), '|', campo('$.payment_status'))", traducir: estado_pedido}
      estado_pago:         {valor: "campo('$.payment_status')", traducir: estado_pago}
      cliente_id:          {referencia: dim_cliente, clave: "campo('$.customer.id')"}
      canal_id:            {literal: ecommerce_propio}
      importe_bruto:       {valor: "a_numero(campo('$.subtotal'))", con_impuesto: true, moneda: defecto}
      importe_descuento:   {valor: "suma(a_numero(campo('$.discount')), a_numero(campo('$.coupon_discount')))", con_impuesto: true}
      importe_neto:        "importe_bruto - importe_descuento"      # puede referenciar columnas canónicas ya calculadas
      importe_envio_cobrado: {valor: "a_numero(campo('$.shipping_cost'))", con_impuesto: true}
      importe_total:       {valor: "a_numero(campo('$.total'))"}
      utm_source:          "parametro_url(campo('$.landing_url'), 'utm_source')"
      utm_medium:          "parametro_url(campo('$.landing_url'), 'utm_medium')"
      utm_campaign:        "parametro_url(campo('$.landing_url'), 'utm_campaign')"
      medio_pago:          {valor: "campo('$.payment_method')", traducir: medio_pago}
      cuotas:              "a_entero(campo('$.installments'))"
    claves_identidad:                          # alimentan core.xref_entidad
      dim_cliente: {email_hash: "hash_pii(campo('$.customer.email'))", documento_hash: "hash_pii(campo('$.customer.document'))"}

  fct_pedido_linea:
    desde: pedidos
    grano: "explotar('$.items')"               # una fila por elemento del array
    clave: "concat(campo('$.id'), '-', item('$.id'))"
    campos:
      pedido_id:           {referencia: fct_pedido, clave: "campo('$.id')"}
      producto_id:         {referencia: dim_producto, clave: "item('$.variant_id')", claves_identidad: {sku: "item('$.sku')"}}
      cantidad:            "a_numero(item('$.quantity'))"
      precio_unitario_lista: {valor: "a_numero(item('$.price'))", con_impuesto: true}
      importe_neto:        {valor: "a_numero(item('$.price')) * a_numero(item('$.quantity'))", con_impuesto: true}
    prorrateos:
      - {columna: importe_descuento, desde_cabecera: importe_descuento, base: importe_neto}   # reparte descuento de cabecera en líneas

value_maps:                                    # traducciones de valores de origen → catálogo canónico
  estado_pedido:
    dominio: estado_pedido
    reglas:
      - {origen: "open|pending",   canonico: pendiente_pago}
      - {origen: "open|paid",      canonico: confirmado}
      - {origen: "closed|paid",    canonico: entregado}
      - {origen_regex: "^cancel",  canonico: cancelado}
    default: otro                              # valores no cubiertos → 'otro' + registro en ops.valores_sin_mapear
  estado_pago:
    dominio: estado_pago
    reglas: [{origen: pending, canonico: pendiente}, {origen: paid, canonico: aprobado}, {origen: refunded, canonico: reembolsado}]
  medio_pago:
    dominio: medio_pago
    reglas: [{origen_regex: "(?i)card|tarjeta", canonico: tarjeta_credito}, {origen_regex: "(?i)transfer", canonico: transferencia}]

reglas_clasificacion: []                       # ver §5.3 (tesorería, categorías de gasto)
```

## 4. Lenguaje de expresiones (DSL)

Expresiones en texto, parseadas y compiladas a SQL. **No** se permite SQL libre. Funciones disponibles (lista cerrada; agregar una función = cambio de plataforma con test):

| Categoría | Función | Descripción |
|---|---|---|
| Acceso | `campo('$.a.b[0].c')` | JSONPath sobre `_payload` del registro |
| | `item('$.x')` | JSONPath sobre el elemento actual cuando `grano: explotar(...)` |
| | `padre('$.x')` | campo del registro padre (streams hijos) |
| | `columna('nombre')` | valor de otra columna canónica ya calculada en la misma entidad (también por nombre directo) |
| | `metadato('extraido_at')` | metadatos del registro crudo |
| Tipos | `a_texto`, `a_numero(x, decimal=',', miles='.')`, `a_entero`, `a_booleano(x, verdaderos=[...])` | |
| Fechas | `a_timestamp(x, formato=null, zona=null)`, `a_fecha(x, formato)`, `fecha_local(ts)`, `desde_epoch(x, unidad='s'|'ms')` | sin zona → `zona_horaria_origen` |
| Texto | `concat`, `minusculas`, `mayusculas`, `recortar`, `reemplazar(x, patron, por)`, `extraer(x, regex, grupo)`, `dividir(x, sep, n)`, `parametro_url(url, nombre)` | |
| Lógica | `si(cond, a, b)`, `caso(cond1, v1, cond2, v2, ..., defecto)`, `coalesce(...)`, `es_nulo`, `en(x, [..])`, operadores `+ - * / = != > < >= <= and or not` | |
| Arrays | `suma_array('$.items', expr)`, `cuenta_array('$.items')`, `primero_array('$.items', condicion)`, `explotar('$.path')` (solo en `grano`) | |
| Negocio | `sin_impuesto(x, tasa)`, `a_moneda_base(x, moneda, fecha)`, `hash_pii(x)`, `normalizar_sku(x)`, `normalizar_id_fiscal(x)`, `normalizar_telefono(x, pais)`, `traducir(x, value_map)`, `busqueda(entidad, clave)` | |
| Agregación | `agrupar_por(expr)` en `grano` + `sumar(expr)`, `maximo`, `minimo`, `primero(expr, orden)` en campos | para fuentes con varias filas por entidad (ej. movimientos → saldo) |

Formas cortas de un campo:
- `"expresión"` — valor directo.
- `{literal: x}` — constante (validada contra el dominio si la columna es categórica).
- `{valor: expr, traducir: <value_map>}` — traduce con un value_map.
- `{valor: expr, con_impuesto: true}` — aplica `sin_impuesto` si `precios_incluyen_impuesto`.
- `{valor: expr, moneda: defecto | "expr"}` — genera `_orig`, `moneda_orig`, `tc_aplicado` y el valor en moneda base automáticamente.
- `{referencia: dim_x, clave: expr}` — resuelve FK por `canonical_id` o `xref_entidad`.

## 5. Traducción de valores y clasificación

### 5.1 `value_maps`
- Cada value_map declara el **dominio canónico** destino; el compilador verifica que cada `canonico` exista en `ref.valores_canonicos`.
- `origen` exacto (case-insensitive por defecto), `origen_regex`, `origen_en: [..]`.
- `default` obligatorio (`otro` o un valor del dominio). Todo valor que cae en default se registra en `ops.valores_sin_mapear(tenant_id, source_id, dominio, valor_origen, ocurrencias, primera_vez, ultima_vez)` → alerta de onboarding DQ-06.
- Atributos derivados: si el dominio tiene atributos (ej. `clase_comprobante.signo`), las columnas dependientes (`signo`) se completan solas.

### 5.2 Mapeos grandes por tabla
Para listas extensas (plan de cuentas, categorías de productos, depósitos) el value_map puede apuntar a una tabla editable: `{tabla: core.map_cuenta_contable}` o `{tabla: ops.map_valor_tenant, dominio: categoria_gasto}` gestionada desde la interfaz de onboarding.

### 5.3 `reglas_clasificacion`
Para columnas que no vienen explícitas en origen y se deducen (ej. `tipo` de movimiento de tesorería, `categoria_gasto` de un comprobante de compra):

```yaml
reglas_clasificacion:
  - entidad: fct_movimiento_tesoreria
    columna: tipo
    reglas:                                    # se evalúan por prioridad; gana la primera
      - {prioridad: 10, si: "en(columna('contraparte_identificador_fiscal'), lista('proveedores_conocidos'))", valor: pago_proveedor}
      - {prioridad: 20, si: "extraer(minusculas(campo('$.descripcion')), '<patrón definido por el operador>') != null", valor: sueldos_cargas}
    default: otros
```
`lista('<nombre>')` refiere listas dinámicas del tenant (ej. identificadores fiscales de proveedores = `select identificador_fiscal from core.dim_proveedor`).

## 6. Fuente de verdad y deduplicación entre fuentes

Cuando dos fuentes aportan la misma entidad (ej. pedidos que existen en un sistema de ventas y replicados en otro de gestión):

```yaml
# en el mapping de la fuente que REPLICA
entidades:
  fct_pedido:
    replica_de:
      source_id: "<source_id de la fuente original>"
      clave_original: "campo('$.external_reference')"      # campo donde la réplica guarda el id original
      match_heuristico: {cliente: true, importe_tolerancia_pct: 1, fecha_tolerancia_dias: 2}
```

Regla genérica en `int_fct_pedido`:
1. Para cada entidad, `ops.fuente_de_verdad` define qué `source_id` manda (opcionalmente por alcance, ej. por canal).
2. Registros de fuentes no-verdad que matchean (por `replica_de` o heurística) con uno de verdad → `es_fuente_verdad = false` y **enriquecen** columnas nulas del registro verdadero (UTM, comisión de canal, envío, medio de pago) según lista `enriquecer_columnas` configurable.
3. Registros de fuentes no-verdad sin match → se cuentan solo si la regla del tenant lo permite (`incluir_sin_match: true`) y se alerta DQ-05.
4. Mismo patrón para `fct_comprobante` (documentos en gestión vs registro fiscal oficial), `fct_stock_diario` (un depósito = una sola fuente) y `dim_*`.

## 7. Validación (antes de publicar un mapping)

El compilador rechaza la publicación si:
1. El YAML no cumple `schemas/mapping.schema.json`.
2. Una columna destino no existe en la entidad canónica o el tipo resultante no es compatible.
3. Falta una columna **obligatoria** de la entidad (`requisitos.yml` → `obligatorias_entidad`), ej. `fct_pedido.fecha_pedido`, `estado`, `importe_neto`.
4. Un `canonico` no existe en su dominio.
5. Una expresión referencia un JSONPath que no aparece en la muestra (`ops.fuente_muestra`) → advertencia (no bloqueo).
6. **Prueba en seco** sobre la muestra: 0 errores de conversión; % de nulos por columna ≤ umbral; importes coherentes (`importe_neto ≈ importe_bruto − importe_descuento`, total ≥ neto).

Resultado: informe de validación + **vista previa** de 20 filas canónicas para que un humano apruebe. Estados en `ops.artefacto_config`: borrador → validado → publicado (requiere aprobación) → archivado.

## 8. Compilador (`mapping_compiler/`)

- Entrada: `mapping.yml` (+ perfil heredado) + esquema canónico (`warehouse/dbt/models/core/_schema.yml`) + catálogo de dominios.
- Salida: `models/staging/generated/<tenant_slug>/<source_id>/stg_…__<entidad>.sql` + `_schema.yml` con tests (not_null de obligatorias, accepted_values de dominios, relaciones).
- Traducción de funciones a SQL a través de macros cross-database (`jsonb_extract_path_text` / `json_extract` según motor).
- Determinístico e idempotente; los modelos generados no se editan (cabecera `-- GENERADO: no editar`).
- Tests del compilador: una suite de casos por función del DSL y casos borde (arrays vacíos, números con coma, fechas sin zona, valores no mapeados, prorrateos que no cierran por redondeo → ajuste en la última línea).

## 9. Asistente de mapeo con IA (onboarding)

Para acelerar el alta de un sistema desconocido:
1. `discover` + `sample` (docs/02 §8) generan el perfil del stream: rutas, tipos, ejemplos, valores distintos de campos categóricos.
2. Un modelo de lenguaje recibe **solo el perfil y la muestra anonimizada** (sin datos personales) + el esquema canónico + el catálogo de dominios, y propone un `mapping.yml` borrador con un puntaje de confianza por campo y los `value_maps` sugeridos.
3. El compilador valida la propuesta y muestra la vista previa.
4. Un humano corrige y aprueba. **Nada se publica sin aprobación humana.**
5. Las correcciones se guardan como ejemplos para mejorar propuestas futuras del mismo tipo de fuente.

## 10. Matriz de capacidades (qué KPIs quedan disponibles)

Cada KPI declara sus **requisitos de datos canónicos** (columnas obligatorias y opcionales, `kpis/src/requisitos.yml` + cada KPI). Tras publicar mappings y cargar datos, un job calcula por tenant:

```
ops.kpi_capacidad(tenant_id, kpi_id, estado, faltantes jsonb, cobertura numeric, calculado_at)
  estado: 'disponible'   → todas las obligatorias con cobertura ≥ 95 % en el período reciente
          'degradado'    → obligatorias OK pero faltan opcionales (el KPI avisa qué no se puede desglosar)
          'no_disponible'→ falta alguna obligatoria (se informa cuál y qué rol de fuente la aportaría)
```

El servidor IA solo ofrece KPIs `disponible` o `degradado` y puede explicar qué fuente habría que conectar para habilitar el resto. Así el mismo catálogo de KPIs sirve para cualquier combinación de sistemas.
