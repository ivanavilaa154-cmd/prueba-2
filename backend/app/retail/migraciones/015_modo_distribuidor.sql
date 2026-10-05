-- SPEC v2 · modo distribuidor (sección 12B) y roles nuevos (sección 2).
-- Una empresa puede ser comercio, distribuidor o ambos (modos). No confundir con organizaciones.tipo = 'distribuidor', que es la
-- cuenta externa de una marca que solo ve el panel agregado y anónimo (13.3).
ALTER TABLE organizaciones ADD COLUMN modos text[] NOT NULL DEFAULT '{comercio}'
    CHECK (cardinality(modos) > 0 AND modos <@ ARRAY['comercio', 'distribuidor']);

INSERT INTO roles VALUES
 ('jefe_ventas', 'Jefe de ventas', 'Ve a todos los vendedores, clientes, rutas, metas y cuentas corrientes (modo distribuidor).'),
 ('vendedor', 'Vendedor / preventista', 'Ve solo su cartera de clientes, su ruta, sus metas, sus pedidos y oportunidades (modo distribuidor).'),
 ('cobranzas', 'Cobranzas', 'Ve cuentas corrientes, deuda vencida y compromisos de pago (modo distribuidor).')
ON CONFLICT (codigo) DO NOTHING;

-- Cartera del vendedor: el servidor fija app.vendedor_id en cada transacción (vacío = sin restricción de cartera, para los demás roles;
-- -1 = vendedor sin ficha asignada, no ve ningún cliente).
CREATE FUNCTION app_vendedor() RETURNS bigint LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.vendedor_id', true), '')::bigint $$;

CREATE TABLE vendedores (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    nombre text NOT NULL,
    zona text,
    supervisor_id bigint REFERENCES vendedores(id),
    codigo_externo text,                                   -- p. ej. odoo:usuario:7
    activo boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (org_id, codigo_externo)
);
ALTER TABLE usuarios ADD COLUMN vendedor_id bigint REFERENCES vendedores(id);

CREATE TABLE listas_precios_clientes (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    nombre text NOT NULL,
    descuento_pct numeric(6,4) NOT NULL DEFAULT 0 CHECK (descuento_pct >= 0 AND descuento_pct < 1),   -- sobre la lista general
    codigo_externo text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (org_id, nombre)
);
CREATE TABLE listas_precios_clientes_lineas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    lista_id bigint NOT NULL REFERENCES listas_precios_clientes(id) ON DELETE CASCADE,
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    desde_cantidad numeric(14,3) NOT NULL DEFAULT 1 CHECK (desde_cantidad > 0),   -- descuento escalonado por volumen
    precio numeric(16,2) NOT NULL CHECK (precio >= 0),
    desde date NOT NULL DEFAULT current_date,
    UNIQUE (lista_id, producto_id, desde_cantidad, desde)
);

CREATE TABLE clientes_b2b (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    razon_social text NOT NULL,
    nombre_fantasia text,
    cuit text,
    direccion text,
    localidad text,
    latitud numeric(9,6),
    longitud numeric(9,6),
    zona text,
    canal text,                                            -- autoservicio, almacén, kiosco, ...
    lista_precios_id bigint REFERENCES listas_precios_clientes(id),
    limite_credito numeric(16,2),
    condicion_pago_dias int NOT NULL DEFAULT 0,
    vendedor_id bigint REFERENCES vendedores(id),
    activo boolean NOT NULL DEFAULT true,
    alta date,
    codigo_externo text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (org_id, codigo_externo)
);
CREATE INDEX clientes_b2b_vendedor ON clientes_b2b (org_id, vendedor_id);

CREATE TABLE rutas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    vendedor_id bigint NOT NULL REFERENCES vendedores(id),
    dia_semana int NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),   -- 0 = lunes
    nombre text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (vendedor_id, dia_semana)
);
CREATE TABLE rutas_clientes (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    ruta_id bigint NOT NULL REFERENCES rutas(id) ON DELETE CASCADE,
    cliente_id bigint NOT NULL REFERENCES clientes_b2b(id) ON DELETE CASCADE,
    orden int NOT NULL DEFAULT 0,
    PRIMARY KEY (ruta_id, cliente_id)
);
CREATE TABLE visitas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    vendedor_id bigint NOT NULL REFERENCES vendedores(id),
    cliente_id bigint NOT NULL REFERENCES clientes_b2b(id) ON DELETE CASCADE,
    fecha date NOT NULL,
    planificada boolean NOT NULL DEFAULT true,
    realizada boolean NOT NULL DEFAULT false,
    resultado text CHECK (resultado IN ('pedido', 'sin_pedido', 'cerrado', 'no_atendio')),
    motivo text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);
CREATE INDEX visitas_vendedor_fecha ON visitas (org_id, vendedor_id, fecha);

CREATE TABLE pedidos_venta (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    numero text NOT NULL,
    cliente_id bigint NOT NULL REFERENCES clientes_b2b(id),
    vendedor_id bigint REFERENCES vendedores(id),
    ubicacion_id bigint REFERENCES ubicaciones(id),        -- depósito que prepara
    fecha date NOT NULL,
    fecha_entrega_prometida date,
    estado text NOT NULL DEFAULT 'tomado'
        CHECK (estado IN ('tomado', 'preparado', 'despachado', 'entregado', 'entregado_parcial', 'rechazado', 'anulado')),
    total numeric(16,2) NOT NULL DEFAULT 0,                -- lo pedido, con descuentos, sin impuestos
    total_entregado numeric(16,2) NOT NULL DEFAULT 0,
    descuento numeric(16,2) NOT NULL DEFAULT 0,            -- otorgado por el vendedor sobre la lista del cliente
    origen text NOT NULL DEFAULT 'manual',                 -- manual, archivo, odoo
    numero_externo text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (org_id, origen, numero_externo)
);
CREATE INDEX pedidos_venta_cliente ON pedidos_venta (org_id, cliente_id, fecha);
CREATE INDEX pedidos_venta_fecha ON pedidos_venta (org_id, fecha);
CREATE TABLE pedidos_venta_lineas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    pedido_id bigint NOT NULL REFERENCES pedidos_venta(id) ON DELETE CASCADE,
    producto_id bigint NOT NULL REFERENCES productos(id),
    cantidad_pedida numeric(14,3) NOT NULL CHECK (cantidad_pedida >= 0),   -- en unidad base
    cantidad_entregada numeric(14,3) NOT NULL DEFAULT 0 CHECK (cantidad_entregada >= 0),
    faltante_stock numeric(14,3) NOT NULL DEFAULT 0 CHECK (faltante_stock >= 0),
    precio_lista numeric(16,4) NOT NULL,                   -- unitario, sin impuestos
    precio numeric(16,4) NOT NULL,                         -- unitario cobrado, sin impuestos
    descuento numeric(16,2) NOT NULL DEFAULT 0,
    costo_unitario numeric(16,4)
);
CREATE INDEX pedidos_venta_lineas_pedido ON pedidos_venta_lineas (pedido_id);
CREATE INDEX pedidos_venta_lineas_producto ON pedidos_venta_lineas (producto_id);

CREATE TABLE entregas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    pedido_id bigint NOT NULL REFERENCES pedidos_venta(id) ON DELETE CASCADE,
    fecha date NOT NULL,
    resultado text NOT NULL CHECK (resultado IN ('entregado', 'parcial', 'rechazado')),
    motivo text,
    repartidor text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);
CREATE INDEX entregas_pedido ON entregas (pedido_id);

CREATE TABLE documentos_cc (                               -- cuenta corriente del cliente
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    cliente_id bigint NOT NULL REFERENCES clientes_b2b(id),
    tipo text NOT NULL CHECK (tipo IN ('factura', 'nota_credito', 'nota_debito', 'recibo')),
    numero text NOT NULL,
    fecha date NOT NULL,
    vencimiento date,
    importe numeric(16,2) NOT NULL,                        -- con impuestos; positivo factura/ND, negativo NC/recibo
    saldo numeric(16,2) NOT NULL DEFAULT 0,                -- lo que queda por cobrar de este documento
    pedido_id bigint REFERENCES pedidos_venta(id),
    cobrador text,
    origen text NOT NULL DEFAULT 'manual',
    numero_externo text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (org_id, origen, numero_externo)
);
CREATE INDEX documentos_cc_cliente ON documentos_cc (org_id, cliente_id, fecha);

CREATE TABLE compromisos_pago (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    cliente_id bigint NOT NULL REFERENCES clientes_b2b(id) ON DELETE CASCADE,
    fecha date NOT NULL,                                   -- fecha prometida
    monto numeric(16,2) NOT NULL CHECK (monto > 0),
    estado text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'cumplido', 'incumplido')),
    nota text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);

CREATE TABLE objetivos_marca (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    marca text NOT NULL,
    desde date NOT NULL,
    hasta date NOT NULL,
    tipo text NOT NULL CHECK (tipo IN ('volumen', 'cobertura', 'mix')),
    objetivo numeric(16,3) NOT NULL CHECK (objetivo > 0),  -- volumen: unidades; cobertura: clientes; mix: productos distintos
    bonificacion numeric(16,2) NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    CHECK (hasta >= desde)
);

CREATE TABLE metas_vendedor (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    vendedor_id bigint NOT NULL REFERENCES vendedores(id) ON DELETE CASCADE,
    mes date NOT NULL CHECK (extract(day FROM mes) = 1),
    venta numeric(16,2),
    ganancia numeric(16,2),
    UNIQUE (vendedor_id, mes)
);

-- Aislamiento: empresa siempre; además, el vendedor solo ve los clientes de su cartera y lo que cuelga de ellos.
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['vendedores', 'listas_precios_clientes', 'listas_precios_clientes_lineas', 'rutas', 'objetivos_marca']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY aislamiento ON %I USING (org_id = app_org() OR app_superadmin()) '
                       'WITH CHECK (org_id = app_org() OR app_superadmin())', t);
    END LOOP;
END $$;

ALTER TABLE clientes_b2b ENABLE ROW LEVEL SECURITY;
ALTER TABLE clientes_b2b FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON clientes_b2b
    USING ((org_id = app_org() AND (app_vendedor() IS NULL OR vendedor_id = app_vendedor())) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());

-- Lo que cuelga de un cliente: visible si el cliente lo es (la subconsulta ya pasa por la RLS de clientes_b2b).
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['rutas_clientes', 'visitas', 'pedidos_venta', 'documentos_cc', 'compromisos_pago']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY aislamiento ON %I USING ((org_id = app_org() AND (app_vendedor() IS NULL '
                       'OR cliente_id IN (SELECT id FROM clientes_b2b))) OR app_superadmin()) '
                       'WITH CHECK (org_id = app_org() OR app_superadmin())', t);
    END LOOP;
    FOREACH t IN ARRAY ARRAY['pedidos_venta_lineas', 'entregas']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY aislamiento ON %I USING ((org_id = app_org() AND (app_vendedor() IS NULL '
                       'OR pedido_id IN (SELECT id FROM pedidos_venta))) OR app_superadmin()) '
                       'WITH CHECK (org_id = app_org() OR app_superadmin())', t);
    END LOOP;
END $$;

ALTER TABLE metas_vendedor ENABLE ROW LEVEL SECURITY;
ALTER TABLE metas_vendedor FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON metas_vendedor
    USING ((org_id = app_org() AND (app_vendedor() IS NULL OR vendedor_id = app_vendedor())) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());
