-- Retail · Parte 2: modelo de datos completo (sección 4 del documento).
-- Todas las tablas de empresa llevan org_id y RLS forzada; las que tienen sucursal filtran además por sucursal.
-- Importes en numeric (nunca float): precios y montos numeric(16,2), costos unitarios numeric(16,4), cantidades numeric(14,3).

-- ================================================================ catálogo
CREATE TABLE productos_maestros (          -- global: lo comparten todas las empresas
    id bigserial PRIMARY KEY,
    ean text NOT NULL UNIQUE,
    nombre text NOT NULL,
    marca text,
    fabricante text,
    categoria text,
    subcategoria text,
    presentacion text,
    unidad_medida text,
    contenido_neto numeric(12,3),
    perecedero boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE categorias (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    nombre text NOT NULL,
    padre_id bigint REFERENCES categorias(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (org_id, padre_id, nombre)
);

CREATE TABLE productos (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    maestro_id bigint REFERENCES productos_maestros(id),   -- nulo: a granel o elaboración propia
    codigo_interno text NOT NULL,
    nombre text NOT NULL,
    ean text,
    marca text,
    categoria_id bigint REFERENCES categorias(id),        -- apunta a la subcategoría (hoja del árbol)
    unidad text NOT NULL DEFAULT 'unidad',
    perecedero boolean NOT NULL DEFAULT false,
    activo boolean NOT NULL DEFAULT true,
    clase_abc char(1),                                     -- calculada (sección 10.2)
    rol_producto text,                                     -- estrella, iman, joya, peso_muerto (calculado)
    estado_mapeo text NOT NULL DEFAULT 'mapeado' CHECK (estado_mapeo IN ('mapeado', 'sin_mapear', 'propio')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (org_id, codigo_interno)
);
CREATE INDEX productos_org_ean ON productos (org_id, ean);

CREATE TABLE alias_producto (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    origen text NOT NULL CHECK (origen IN ('proveedor', 'caja', 'plataforma', 'archivo', 'documento')),
    origen_id bigint,                                      -- proveedor o plataforma
    codigo text,
    texto text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);
CREATE INDEX alias_busqueda ON alias_producto (org_id, origen, origen_id, codigo);

-- ================================================================ proveedores y compras
CREATE TABLE proveedores (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    razon_social text NOT NULL,
    cuit text,
    contacto text,
    telefono text,
    email_oc text,
    dias_visita int[] NOT NULL DEFAULT '{}',              -- 0 = lunes … 6 = domingo; vacío = sin días configurados
    demora_entrega_dias int,                               -- lead time; nulo = sin configurar
    pedido_minimo_monto numeric(16,2) NOT NULL DEFAULT 0,
    pedido_minimo_bultos int NOT NULL DEFAULT 0,
    condiciones_pago text,
    activo boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);

CREATE TABLE producto_proveedores (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    proveedor_id bigint NOT NULL REFERENCES proveedores(id),
    costo numeric(16,4),                                   -- costo vigente por unidad; nulo = sin costo
    unidad_compra text NOT NULL DEFAULT 'bulto',
    unidades_por_bulto int NOT NULL DEFAULT 1 CHECK (unidades_por_bulto > 0),
    multiplo_compra int NOT NULL DEFAULT 1 CHECK (multiplo_compra > 0),   -- en bultos
    principal boolean NOT NULL DEFAULT true,
    prioridad int NOT NULL DEFAULT 1,
    codigo_proveedor text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (producto_id, proveedor_id)
);

CREATE TABLE listas_precios_proveedor (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    proveedor_id bigint NOT NULL REFERENCES proveedores(id),
    vigencia_desde date NOT NULL,
    origen text NOT NULL DEFAULT 'manual',                -- manual, archivo, documento
    documento_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);
CREATE TABLE listas_precios_proveedor_lineas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    lista_id bigint NOT NULL REFERENCES listas_precios_proveedor(id) ON DELETE CASCADE,
    producto_id bigint REFERENCES productos(id),
    codigo text,
    descripcion text,
    costo numeric(16,4) NOT NULL,
    costo_anterior numeric(16,4)
);

CREATE TABLE ordenes_compra (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    numero text NOT NULL,
    proveedor_id bigint NOT NULL REFERENCES proveedores(id),
    ubicacion_id bigint REFERENCES ubicaciones(id),        -- nulo = consolidada (distribución por línea)
    estado text NOT NULL DEFAULT 'sugerida' CHECK (estado IN ('sugerida', 'borrador', 'aprobada', 'enviada',
                                                              'recibida_parcial', 'recibida', 'cancelada')),
    origen text NOT NULL DEFAULT 'manual' CHECK (origen IN ('sugerida', 'manual', 'importada')),
    total numeric(16,2) NOT NULL DEFAULT 0,
    fecha_esperada date,
    aprobacion text,                                       -- 'manual' o 'automatica' (bajo el límite)
    aprobada_por bigint REFERENCES usuarios(id),
    aprobada_at timestamptz,
    enviada_por bigint REFERENCES usuarios(id),            -- siempre una persona (CLAUDE.md, regla 4)
    enviada_at timestamptz,
    escalada_at timestamptz,
    notas text,
    explicacion jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (org_id, numero)
);
CREATE TABLE ordenes_compra_lineas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    orden_id bigint NOT NULL REFERENCES ordenes_compra(id) ON DELETE CASCADE,
    producto_id bigint NOT NULL REFERENCES productos(id),
    ubicacion_id bigint REFERENCES ubicaciones(id),        -- destino de esta cantidad
    cantidad numeric(14,3) NOT NULL CHECK (cantidad >= 0),
    cantidad_sugerida numeric(14,3),
    bultos numeric(14,3),
    costo numeric(16,4),
    cantidad_recibida numeric(14,3) NOT NULL DEFAULT 0,
    adelantada boolean NOT NULL DEFAULT false,             -- adelantada para completar el pedido mínimo
    explicacion jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE recepciones (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    orden_id bigint REFERENCES ordenes_compra(id),
    proveedor_id bigint REFERENCES proveedores(id),
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    fecha timestamptz NOT NULL DEFAULT now(),
    documento text,
    documento_id bigint,
    estado text NOT NULL DEFAULT 'confirmada' CHECK (estado IN ('borrador', 'confirmada')),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);
CREATE TABLE recepciones_lineas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    recepcion_id bigint NOT NULL REFERENCES recepciones(id) ON DELETE CASCADE,
    producto_id bigint NOT NULL REFERENCES productos(id),
    cantidad numeric(14,3) NOT NULL,
    costo numeric(16,4),
    lote text,
    vencimiento date,
    cantidad_esperada numeric(14,3),
    costo_esperado numeric(16,4)
);

-- ================================================================ stock
CREATE TABLE stock_actual (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    cantidad numeric(14,3) NOT NULL DEFAULT 0,            -- puede ser negativo si el sistema de caja lo permite
    reservado numeric(14,3) NOT NULL DEFAULT 0,
    en_transito numeric(14,3) NOT NULL DEFAULT 0,
    actualizado_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (producto_id, ubicacion_id)
);

CREATE TABLE stock_lotes (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    lote text NOT NULL,
    cantidad numeric(14,3) NOT NULL,
    vencimiento date,
    ingreso date NOT NULL DEFAULT current_date
);
CREATE INDEX stock_lotes_venc ON stock_lotes (org_id, vencimiento);

CREATE TABLE movimientos_stock (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    fecha timestamptz NOT NULL DEFAULT now(),
    tipo text NOT NULL CHECK (tipo IN ('venta', 'compra', 'transferencia_salida', 'transferencia_entrada', 'ajuste',
                                       'merma', 'vencimiento', 'devolucion', 'inicial')),
    cantidad numeric(14,3) NOT NULL,                       -- con signo
    costo_unitario numeric(16,4),
    documento_tipo text,
    documento_id bigint,
    motivo text,
    usuario_id bigint REFERENCES usuarios(id)
);
CREATE INDEX movimientos_prod ON movimientos_stock (org_id, producto_id, ubicacion_id, fecha);

CREATE TABLE transferencias (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    numero text NOT NULL,
    origen_id bigint NOT NULL REFERENCES ubicaciones(id),
    destino_id bigint NOT NULL REFERENCES ubicaciones(id),
    estado text NOT NULL DEFAULT 'sugerida' CHECK (estado IN ('sugerida', 'aprobada', 'enviada', 'recibida', 'cancelada')),
    motivo text NOT NULL DEFAULT 'reposicion' CHECK (motivo IN ('reposicion', 'rescate_vencimiento', 'manual')),
    valor numeric(16,2) NOT NULL DEFAULT 0,
    aprobacion text,
    aprobada_por bigint REFERENCES usuarios(id),
    aprobada_at timestamptz,
    enviada_at timestamptz,
    recibida_at timestamptz,
    explicacion jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    CHECK (origen_id <> destino_id),
    UNIQUE (org_id, numero)
);
CREATE TABLE transferencias_lineas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    transferencia_id bigint NOT NULL REFERENCES transferencias(id) ON DELETE CASCADE,
    producto_id bigint NOT NULL REFERENCES productos(id),
    cantidad numeric(14,3) NOT NULL CHECK (cantidad > 0),
    cantidad_recibida numeric(14,3),
    lote text,
    costo numeric(16,4)
);

CREATE TABLE recuentos (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    fecha date NOT NULL DEFAULT current_date,
    estado text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'en_curso', 'cerrado')),
    created_at timestamptz NOT NULL DEFAULT now(),
    cerrado_at timestamptz,
    created_by bigint,
    UNIQUE (org_id, ubicacion_id, fecha)
);
CREATE TABLE recuentos_lineas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    recuento_id bigint NOT NULL REFERENCES recuentos(id) ON DELETE CASCADE,
    producto_id bigint NOT NULL REFERENCES productos(id),
    motivo_seleccion text NOT NULL,                        -- stock_fantasma, clase_a, alto_valor, diferencia_previa
    stock_sistema numeric(14,3),
    contado numeric(14,3),
    diferencia numeric(14,3),
    diferencia_pesos numeric(16,2),
    motivo_ajuste text,
    contado_por bigint REFERENCES usuarios(id),
    contado_at timestamptz
);

CREATE TABLE periodos_sin_stock (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    desde date NOT NULL,
    hasta date                                             -- nulo = sigue sin stock
);
CREATE INDEX periodos_sin_stock_prod ON periodos_sin_stock (org_id, producto_id, ubicacion_id);

-- ================================================================ ventas
CREATE TABLE tickets (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    canal_id bigint NOT NULL REFERENCES canales(id),
    plataforma_id bigint REFERENCES plataformas(id),
    punto_venta text,
    cajero text,
    fecha_hora timestamptz NOT NULL,
    cliente text,
    total numeric(16,2) NOT NULL,
    estado text NOT NULL DEFAULT 'confirmado' CHECK (estado IN ('confirmado', 'anulado', 'devuelto')),
    numero_externo text NOT NULL,                          -- clave de idempotencia junto con el origen
    origen text NOT NULL DEFAULT 'demo',                   -- demo, archivo, odoo, tiendanube, mercadolibre…
    lote_importacion_id bigint,
    UNIQUE (org_id, origen, numero_externo)
);
CREATE INDEX tickets_fecha ON tickets (org_id, ubicacion_id, fecha_hora);

CREATE TABLE tickets_lineas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    ticket_id bigint NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),   -- copiado del ticket para filtrar por sucursal
    fecha date NOT NULL,                                       -- copiado del ticket (zona de la empresa)
    producto_id bigint NOT NULL REFERENCES productos(id),
    cantidad numeric(14,3) NOT NULL,                           -- negativa en devoluciones
    precio_lista numeric(16,2),
    precio_cobrado numeric(16,2) NOT NULL,                     -- unitario
    descuento numeric(16,2) NOT NULL DEFAULT 0,                -- total de la línea
    descuento_manual boolean NOT NULL DEFAULT false,
    costo_unitario numeric(16,4),                              -- nulo = producto sin costo
    promocion_id bigint
);
CREATE INDEX tickets_lineas_prod ON tickets_lineas (org_id, producto_id, ubicacion_id, fecha);
CREATE INDEX tickets_lineas_ticket ON tickets_lineas (ticket_id);

CREATE TABLE pagos (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    ticket_id bigint NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    medio text NOT NULL CHECK (medio IN ('efectivo', 'debito', 'credito', 'qr', 'transferencia', 'cuenta_corriente', 'plataforma')),
    monto numeric(16,2) NOT NULL,
    cuotas int NOT NULL DEFAULT 1,
    comision_estimada numeric(16,2) NOT NULL DEFAULT 0,
    plazo_acreditacion_dias int NOT NULL DEFAULT 0
);

CREATE TABLE anulaciones_devoluciones (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    ticket_id bigint REFERENCES tickets(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    tipo text NOT NULL CHECK (tipo IN ('anulacion', 'devolucion')),
    cajero text,
    motivo text,
    fecha_hora timestamptz NOT NULL,
    monto numeric(16,2) NOT NULL
);

CREATE TABLE costos_canal (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    plataforma_id bigint NOT NULL REFERENCES plataformas(id),
    ticket_id bigint REFERENCES tickets(id) ON DELETE CASCADE,  -- nulo = costo del período (publicidad, abono)
    fecha date NOT NULL,
    comision numeric(16,2) NOT NULL DEFAULT 0,
    envio numeric(16,2) NOT NULL DEFAULT 0,                     -- envío a cargo del vendedor
    publicidad numeric(16,2) NOT NULL DEFAULT 0
);

-- ================================================================ precios y promociones
CREATE TABLE precios (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    ubicacion_id bigint REFERENCES ubicaciones(id),          -- nulo = todas
    canal_id bigint REFERENCES canales(id),                  -- nulo = todos
    precio numeric(16,2) NOT NULL CHECK (precio >= 0),
    desde date NOT NULL,
    hasta date,
    origen text NOT NULL DEFAULT 'demo',                     -- demo, remarcacion, importado, caja
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);
CREATE INDEX precios_vigencia ON precios (org_id, producto_id, desde);

CREATE TABLE margenes_objetivo (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    categoria_id bigint REFERENCES categorias(id),
    producto_id bigint REFERENCES productos(id) ON DELETE CASCADE,
    canal_id bigint REFERENCES canales(id),
    margen numeric(6,4) NOT NULL CHECK (margen >= 0 AND margen < 1),   -- sobre el precio de venta
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);

CREATE TABLE reglas_redondeo (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    desde_precio numeric(16,2) NOT NULL DEFAULT 0,
    hasta_precio numeric(16,2),
    multiplo numeric(16,2) NOT NULL DEFAULT 10,            -- redondear hacia arriba a este múltiplo
    terminaciones int[] NOT NULL DEFAULT '{}',             -- p. ej. {0,5,9} en la última cifra; vacío = sin restricción
    umbral_minimo_cambio numeric(6,4) NOT NULL DEFAULT 0.01 -- no remarcar si el cambio es menor a esta proporción
);

CREATE TABLE promociones (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    nombre text NOT NULL,
    tipo text NOT NULL CHECK (tipo IN ('descuento_pct', 'precio_fijo', '2x1', 'combo', 'segunda_unidad')),
    parametros jsonb NOT NULL DEFAULT '{}',
    productos bigint[] NOT NULL DEFAULT '{}',
    ubicaciones bigint[] NOT NULL DEFAULT '{}',           -- vacío = todas
    canales bigint[] NOT NULL DEFAULT '{}',
    desde date NOT NULL,
    hasta date NOT NULL,
    origen text NOT NULL DEFAULT 'manual' CHECK (origen IN ('manual', 'liquidacion', 'sobrestock', 'vencimiento')),
    estado text NOT NULL DEFAULT 'activa' CHECK (estado IN ('sugerida', 'activa', 'finalizada', 'cancelada')),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);

-- ================================================================ clientes (fase 3, opcional)
CREATE TABLE clientes (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    identificador text NOT NULL,
    nombre text,
    alta date NOT NULL DEFAULT current_date,
    consentimiento boolean NOT NULL DEFAULT false,
    UNIQUE (org_id, identificador)
);
CREATE TABLE cuentas_clientes (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    cliente_id bigint NOT NULL REFERENCES clientes(id) ON DELETE CASCADE,
    fecha date NOT NULL,
    tipo text NOT NULL CHECK (tipo IN ('compra', 'pago', 'ajuste')),
    monto numeric(16,2) NOT NULL,
    vencimiento date
);

-- ================================================================ configuración, reglas y alertas
CREATE TABLE config_abastecimiento (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    nivel text NOT NULL CHECK (nivel IN ('ubicacion', 'categoria', 'proveedor')),   -- la empresa está en organizaciones
    referencia_id bigint NOT NULL,
    modelo text NOT NULL CHECK (modelo IN ('centralizado', 'descentralizado', 'mixto')),
    UNIQUE (org_id, nivel, referencia_id)
);

CREATE TABLE reglas_reposicion (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint REFERENCES productos(id) ON DELETE CASCADE,
    categoria_id bigint REFERENCES categorias(id),
    ubicacion_id bigint REFERENCES ubicaciones(id),
    canal_id bigint REFERENCES canales(id),
    stock_minimo numeric(14,3),
    stock_minimo_dias numeric(8,2),
    stock_maximo numeric(14,3),
    stock_maximo_dias numeric(8,2),
    punto_pedido numeric(14,3),
    stock_seguridad numeric(14,3),                         -- si se carga, reemplaza al calculado
    origenes_permitidos bigint[] NOT NULL DEFAULT '{}',    -- vacío = cualquiera con excedente
    minimo_en_origen_dias numeric(8,2) NOT NULL DEFAULT 14,
    cantidad_minima_traslado numeric(14,3) NOT NULL DEFAULT 1,
    demora_traslado_dias int NOT NULL DEFAULT 1,
    dias_traslado int[] NOT NULL DEFAULT '{0,1,2,3,4,5}',
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);

CREATE TABLE config_automatizacion (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    tipo_documento text NOT NULL CHECK (tipo_documento IN ('orden_compra', 'transferencia', 'precio', 'promocion')),
    nivel text NOT NULL DEFAULT 'borrador' CHECK (nivel IN ('solo_aviso', 'borrador', 'automatico_con_limite')),
    monto_limite numeric(16,2) NOT NULL DEFAULT 0,
    UNIQUE (org_id, tipo_documento)
);

CREATE TABLE presupuestos_compra (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    mes date NOT NULL,
    ubicacion_id bigint REFERENCES ubicaciones(id),
    monto numeric(16,2) NOT NULL,
    UNIQUE (org_id, mes, ubicacion_id)
);

CREATE TABLE parametros (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    clave text NOT NULL,
    valor jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, clave)
);

CREATE TABLE alertas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    tipo text NOT NULL,
    prioridad text NOT NULL CHECK (prioridad IN ('urgente', 'normal', 'preventiva')),
    ubicacion_id bigint REFERENCES ubicaciones(id),
    producto_id bigint REFERENCES productos(id) ON DELETE CASCADE,
    titulo text NOT NULL,
    explicacion text NOT NULL,
    impacto numeric(16,2) NOT NULL,                        -- en pesos: perdida, en riesgo o recuperable
    tipo_impacto text NOT NULL CHECK (tipo_impacto IN ('perdida', 'en_riesgo', 'recuperable')),
    accion jsonb NOT NULL,                                 -- {etiqueta, tipo, destino, datos}
    estado text NOT NULL DEFAULT 'nueva' CHECK (estado IN ('nueva', 'vista', 'resuelta', 'descartada', 'escalada')),
    vence date,
    destinatarios text[] NOT NULL DEFAULT '{dueno}',       -- roles
    clave_dedupe text NOT NULL,
    grupo text,
    datos jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    resuelta_por bigint REFERENCES usuarios(id)
);
CREATE UNIQUE INDEX alertas_abiertas_unicas ON alertas (org_id, clave_dedupe) WHERE estado IN ('nueva', 'vista', 'escalada');

CREATE TABLE preferencias_aviso (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    usuario_id bigint NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    tipo_alerta text NOT NULL,                             -- '*' = todas
    email boolean NOT NULL DEFAULT true,
    PRIMARY KEY (usuario_id, tipo_alerta)
);
ALTER TABLE usuarios ADD COLUMN resumen_diario boolean NOT NULL DEFAULT true;
ALTER TABLE usuarios ADD COLUMN hora_resumen int NOT NULL DEFAULT 8 CHECK (hora_resumen BETWEEN 0 AND 23);

CREATE TABLE emails (
    id bigserial PRIMARY KEY,
    org_id bigint REFERENCES organizaciones(id),
    usuario_id bigint REFERENCES usuarios(id) ON DELETE SET NULL,
    para text NOT NULL,
    asunto text NOT NULL,
    html text NOT NULL,
    tipo text NOT NULL,                                    -- alerta, resumen_diario, orden_compra
    estado text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'enviado', 'guardado', 'error')),
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    enviado_at timestamptz
);

CREATE TABLE metas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    periodo date NOT NULL,                                 -- primer día del mes
    ubicacion_id bigint REFERENCES ubicaciones(id),
    canal_id bigint REFERENCES canales(id),
    metrica text NOT NULL CHECK (metrica IN ('ventas', 'ganancia', 'margen')),
    valor numeric(16,4) NOT NULL,
    UNIQUE (org_id, periodo, ubicacion_id, canal_id, metrica)
);

-- ================================================================ referencias externas
CREATE TABLE indice_precios (                              -- IPC nacional (INDEC): global
    periodo date PRIMARY KEY,                              -- primer día del mes
    indice numeric(14,4) NOT NULL,
    fuente text NOT NULL DEFAULT 'INDEC'
);

CREATE TABLE calendario (
    id bigserial PRIMARY KEY,
    org_id bigint REFERENCES organizaciones(id),           -- nulo = nacional
    fecha date NOT NULL,
    tipo text NOT NULL CHECK (tipo IN ('feriado', 'cobro', 'comercial', 'local')),
    nombre text NOT NULL,
    ubicacion_id bigint REFERENCES ubicaciones(id)
);
CREATE INDEX calendario_fecha ON calendario (fecha);

CREATE TABLE clima_diario (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    fecha date NOT NULL,
    temperatura_max numeric(5,2),
    lluvia_mm numeric(6,2),
    PRIMARY KEY (ubicacion_id, fecha)
);

-- ================================================================ ingesta
CREATE TABLE lotes_importacion (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    tipo text NOT NULL,                                    -- ventas, stock, productos, compras, precios, sincronizacion
    origen text NOT NULL,                                  -- archivo, odoo, documento
    nombre_archivo text,
    huella text NOT NULL,                                  -- sha256 del contenido: reimportar no duplica
    estado text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'validado', 'importado', 'con_errores', 'duplicado')),
    filas_total int NOT NULL DEFAULT 0,
    filas_ok int NOT NULL DEFAULT 0,
    filas_error int NOT NULL DEFAULT 0,
    filas_duplicadas int NOT NULL DEFAULT 0,
    errores jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);
CREATE INDEX lotes_huella ON lotes_importacion (org_id, huella);

CREATE TABLE mapeos_columnas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    tipo text NOT NULL,
    firma text NOT NULL,                                   -- encabezados normalizados del archivo
    mapeo jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, tipo, firma)
);

CREATE TABLE staging_filas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    lote_id bigint NOT NULL REFERENCES lotes_importacion(id) ON DELETE CASCADE,
    numero int NOT NULL,
    datos jsonb NOT NULL,
    error text
);

CREATE TABLE documentos_leidos (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    tipo text NOT NULL CHECK (tipo IN ('factura', 'remito', 'lista_precios')),
    archivo text NOT NULL,
    proveedor_id bigint REFERENCES proveedores(id),
    extraido jsonb NOT NULL DEFAULT '{}',
    estado text NOT NULL DEFAULT 'leido' CHECK (estado IN ('leido', 'confirmado', 'descartado', 'error')),
    ubicacion_id bigint REFERENCES ubicaciones(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);

-- ================================================================ tablas analíticas (precalculadas)
CREATE TABLE agg_producto_ubicacion_dia (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    canal_id bigint NOT NULL REFERENCES canales(id),
    fecha date NOT NULL,
    unidades numeric(14,3) NOT NULL DEFAULT 0,
    facturacion numeric(16,2) NOT NULL DEFAULT 0,
    costo numeric(16,2) NOT NULL DEFAULT 0,
    ganancia numeric(16,2) NOT NULL DEFAULT 0,
    tickets int NOT NULL DEFAULT 0,
    unidades_promo numeric(14,3) NOT NULL DEFAULT 0,
    sin_costo boolean NOT NULL DEFAULT false,
    PRIMARY KEY (producto_id, ubicacion_id, canal_id, fecha)
);
CREATE INDEX agg_pud_fecha ON agg_producto_ubicacion_dia (org_id, fecha);

CREATE TABLE stock_diario (                                -- stock al cierre y si hubo stock ese día
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    fecha date NOT NULL,
    stock_cierre numeric(14,3) NOT NULL,
    con_stock boolean NOT NULL,
    PRIMARY KEY (producto_id, ubicacion_id, fecha)
);

CREATE TABLE agg_ubicacion_hora (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    canal_id bigint NOT NULL REFERENCES canales(id),
    fecha date NOT NULL,
    hora int NOT NULL,
    tickets int NOT NULL,
    facturacion numeric(16,2) NOT NULL,
    unidades numeric(14,3) NOT NULL,
    PRIMARY KEY (ubicacion_id, canal_id, fecha, hora)
);

CREATE TABLE metricas_producto_actual (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    vpd numeric(14,4),
    pronostico_diario numeric(14,4),
    disponible numeric(14,3),
    dias_stock numeric(10,2),
    fecha_quiebre date,
    horizonte_dias int,
    stock_seguridad numeric(14,3),
    cantidad_sugerida numeric(14,3),
    proveedor_id bigint REFERENCES proveedores(id),
    semaforo text CHECK (semaforo IN ('rojo', 'amarillo', 'verde', 'gris')),
    clase_abc char(1),
    tendencia text,
    dias_sin_venta int,
    capital numeric(16,2),
    gmroi numeric(12,4),
    rotacion numeric(12,4),
    riesgo_vencimiento numeric(16,2),
    confianza text,
    ventas_en_riesgo numeric(16,2),
    explicacion jsonb NOT NULL DEFAULT '{}',
    calculado_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (producto_id, ubicacion_id)
);

CREATE TABLE historial_abc (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    mes date NOT NULL,
    clase char(1) NOT NULL,
    PRIMARY KEY (producto_id, mes)
);

CREATE TABLE ajustes_aprendizaje (                          -- control posterior: correcciones del usuario
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    ubicacion_id bigint REFERENCES ubicaciones(id),
    campo text NOT NULL,
    antes numeric(14,4),
    despues numeric(14,4),
    motivo text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ejecuciones_calculo (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    tipo text NOT NULL,                                    -- nocturno, incremental, manual
    inicio timestamptz NOT NULL DEFAULT now(),
    fin timestamptz,
    estado text NOT NULL DEFAULT 'corriendo',
    detalle jsonb NOT NULL DEFAULT '{}'
);

-- ================================================================ Row Level Security
-- Tablas globales: todos leen; solo la plataforma escribe.
ALTER TABLE productos_maestros ENABLE ROW LEVEL SECURITY;
ALTER TABLE productos_maestros FORCE ROW LEVEL SECURITY;
CREATE POLICY lectura ON productos_maestros FOR SELECT USING (true);
CREATE POLICY escritura ON productos_maestros FOR ALL USING (app_superadmin()) WITH CHECK (app_superadmin());
ALTER TABLE indice_precios ENABLE ROW LEVEL SECURITY;
ALTER TABLE indice_precios FORCE ROW LEVEL SECURITY;
CREATE POLICY lectura ON indice_precios FOR SELECT USING (true);
CREATE POLICY escritura ON indice_precios FOR ALL USING (app_superadmin()) WITH CHECK (app_superadmin());
ALTER TABLE calendario ENABLE ROW LEVEL SECURITY;
ALTER TABLE calendario FORCE ROW LEVEL SECURITY;
CREATE POLICY lectura ON calendario FOR SELECT USING (org_id IS NULL OR org_id = app_org() OR app_superadmin());
CREATE POLICY escritura ON calendario FOR ALL USING (org_id = app_org() OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());

DO $$
DECLARE
    t record;
BEGIN
    -- tabla, columna de sucursal (NULL = solo por empresa)
    FOR t IN SELECT * FROM (VALUES
        ('categorias', NULL), ('productos', NULL), ('alias_producto', NULL), ('proveedores', NULL),
        ('producto_proveedores', NULL), ('listas_precios_proveedor', NULL), ('listas_precios_proveedor_lineas', NULL),
        ('ordenes_compra', 'ubicacion_id'), ('ordenes_compra_lineas', 'ubicacion_id'),
        ('recepciones', 'ubicacion_id'),
        ('stock_actual', 'ubicacion_id'), ('stock_lotes', 'ubicacion_id'), ('movimientos_stock', 'ubicacion_id'),
        ('recuentos', 'ubicacion_id'),
        ('periodos_sin_stock', 'ubicacion_id'), ('tickets', 'ubicacion_id'), ('tickets_lineas', 'ubicacion_id'),
        ('pagos', 'ubicacion_id'), ('anulaciones_devoluciones', 'ubicacion_id'), ('costos_canal', NULL),
        ('precios', 'ubicacion_id'), ('margenes_objetivo', NULL), ('reglas_redondeo', NULL), ('promociones', NULL),
        ('clientes', NULL), ('cuentas_clientes', NULL), ('config_abastecimiento', NULL), ('reglas_reposicion', 'ubicacion_id'),
        ('config_automatizacion', NULL), ('presupuestos_compra', 'ubicacion_id'), ('parametros', NULL),
        ('alertas', 'ubicacion_id'), ('preferencias_aviso', NULL), ('emails', NULL), ('metas', 'ubicacion_id'),
        ('clima_diario', 'ubicacion_id'), ('lotes_importacion', NULL), ('mapeos_columnas', NULL), ('staging_filas', NULL),
        ('documentos_leidos', 'ubicacion_id'), ('agg_producto_ubicacion_dia', 'ubicacion_id'), ('stock_diario', 'ubicacion_id'),
        ('agg_ubicacion_hora', 'ubicacion_id'), ('metricas_producto_actual', 'ubicacion_id'), ('historial_abc', NULL),
        ('ajustes_aprendizaje', 'ubicacion_id'), ('ejecuciones_calculo', NULL)
    ) AS x(tabla, col)
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t.tabla);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t.tabla);
        IF t.col IS NULL THEN
            EXECUTE format('CREATE POLICY aislamiento ON %I USING (org_id = app_org() OR app_superadmin()) '
                           'WITH CHECK (org_id = app_org() OR app_superadmin())', t.tabla);
        ELSE
            -- Fila sin sucursal (p. ej. OC consolidada, alerta general): solo quien ve todas.
            EXECUTE format('CREATE POLICY aislamiento ON %I USING ((org_id = app_org() AND '
                           '(CASE WHEN %I IS NULL THEN coalesce(current_setting(''app.todas_ubicaciones'', true), '''') = ''1'' '
                           'ELSE app_ve_ubicacion(%I) END)) OR app_superadmin()) '
                           'WITH CHECK (org_id = app_org() OR app_superadmin())', t.tabla, t.col, t.col);
        END IF;
    END LOOP;
END $$;

-- Transferencias: las ve quien ve el origen o el destino.
ALTER TABLE transferencias ENABLE ROW LEVEL SECURITY;
ALTER TABLE transferencias FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON transferencias
    USING ((org_id = app_org() AND (app_ve_ubicacion(origen_id) OR app_ve_ubicacion(destino_id))) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());

-- Líneas sin sucursal propia: heredan la visibilidad de su documento (la subconsulta aplica la RLS del encabezado).
ALTER TABLE recepciones_lineas ENABLE ROW LEVEL SECURITY;
ALTER TABLE recepciones_lineas FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON recepciones_lineas
    USING ((org_id = app_org() AND EXISTS (SELECT 1 FROM recepciones r WHERE r.id = recepcion_id)) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());
ALTER TABLE transferencias_lineas ENABLE ROW LEVEL SECURITY;
ALTER TABLE transferencias_lineas FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON transferencias_lineas
    USING ((org_id = app_org() AND EXISTS (SELECT 1 FROM transferencias t WHERE t.id = transferencia_id)) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());
ALTER TABLE recuentos_lineas ENABLE ROW LEVEL SECURITY;
ALTER TABLE recuentos_lineas FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON recuentos_lineas
    USING ((org_id = app_org() AND EXISTS (SELECT 1 FROM recuentos r WHERE r.id = recuento_id)) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());
