-- Retail · Parte 1: empresas, estructura, usuarios, sesiones y auditoría.
-- Aislamiento: RLS forzada (también para el dueño de las tablas). El servidor fija en cada
-- transacción app.org_id, app.ubicaciones, app.todas_ubicaciones y app.usuario_id (ver db.py).

CREATE FUNCTION app_org() RETURNS bigint LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.org_id', true), '')::bigint $$;

CREATE FUNCTION app_superadmin() RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT coalesce(current_setting('app.superadmin', true), '') = '1' $$;

CREATE FUNCTION app_usuario() RETURNS bigint LANGUAGE sql STABLE AS
$$ SELECT NULLIF(current_setting('app.usuario_id', true), '')::bigint $$;

-- ¿La sesión actual puede ver esta ubicación? (todas, o solo las asignadas al usuario)
CREATE FUNCTION app_ve_ubicacion(u bigint) RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT app_superadmin()
       OR coalesce(current_setting('app.todas_ubicaciones', true), '') = '1'
       OR u = ANY (coalesce(NULLIF(current_setting('app.ubicaciones', true), ''), '{}')::bigint[]) $$;

CREATE TABLE organizaciones (
    id bigserial PRIMARY KEY,
    nombre text NOT NULL,
    cuit text,
    plan text NOT NULL DEFAULT 'prueba',
    zona_horaria text NOT NULL DEFAULT 'America/Argentina/Buenos_Aires',
    moneda text NOT NULL DEFAULT 'ARS',
    modelo_abastecimiento text NOT NULL DEFAULT 'mixto'
        CHECK (modelo_abastecimiento IN ('centralizado', 'descentralizado', 'mixto')),
    consentimiento_datos boolean NOT NULL DEFAULT false,
    consentimiento_fecha timestamptz,
    activa boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);

CREATE TABLE ubicaciones (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    nombre text NOT NULL,
    tipo text NOT NULL DEFAULT 'venta' CHECK (tipo IN ('venta', 'deposito', 'ambos')),
    direccion text,
    localidad text,
    horarios jsonb NOT NULL DEFAULT '{}',
    codigo_externo text,            -- cómo aparece en el sistema de caja (se confirma en la detección)
    activa boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (org_id, nombre)
);

CREATE TABLE canales (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    codigo text NOT NULL CHECK (codigo IN ('fisico', 'ecommerce', 'delivery', 'mayorista')),
    nombre text NOT NULL,
    activo boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (org_id, codigo)
);

CREATE TABLE plataformas (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    tipo text NOT NULL CHECK (tipo IN ('tiendanube', 'mercadolibre', 'woocommerce', 'shopify', 'vtex',
                                       'pedidosya', 'rappi', 'caja_propia', 'odoo', 'otra')),
    nombre text NOT NULL,
    canal_id bigint NOT NULL REFERENCES canales(id),
    ubicacion_despacho_id bigint REFERENCES ubicaciones(id),
    credenciales_cifradas bytea,    -- se cifran en la aplicación (parte 4); nunca en texto plano
    activa boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint
);

CREATE TABLE roles (
    codigo text PRIMARY KEY,
    nombre text NOT NULL,
    descripcion text NOT NULL
);
INSERT INTO roles VALUES
 ('dueno', 'Dueño', 'Ve y configura todo en su empresa. Aprueba OC por encima de los límites.'),
 ('comprador', 'Comprador', 'Gestiona proveedores, OC y remarcación. Aprueba OC hasta su límite.'),
 ('encargado', 'Encargado de sucursal', 'Ve solo sus sucursales. Aprueba transferencias y recepciones. Hace recuentos.'),
 ('cajero', 'Cajero / operativo', 'Recepción de mercadería, recuentos y tareas asignadas.'),
 ('distribuidor', 'Distribuidor / marca', 'Panel de datos agregados y anónimos (fase 3).');

CREATE TABLE usuarios (
    id bigserial PRIMARY KEY,
    org_id bigint REFERENCES organizaciones(id),     -- nulo solo para superadmin de la plataforma
    email text NOT NULL,
    nombre text NOT NULL,
    rol text REFERENCES roles(codigo),
    es_superadmin boolean NOT NULL DEFAULT false,
    hash_clave text NOT NULL,
    totp_secreto text,                               -- segundo factor, si lo activó
    activo boolean NOT NULL DEFAULT true,
    intentos_fallidos int NOT NULL DEFAULT 0,
    bloqueado_hasta timestamptz,
    ultimo_ingreso timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    CHECK (es_superadmin OR (org_id IS NOT NULL AND rol IS NOT NULL))
);
CREATE UNIQUE INDEX usuarios_email ON usuarios (lower(email));

CREATE TABLE usuario_ubicaciones (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    usuario_id bigint NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    PRIMARY KEY (usuario_id, ubicacion_id)
);

CREATE TABLE limites_aprobacion (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    tipo_documento text NOT NULL CHECK (tipo_documento IN ('orden_compra', 'transferencia', 'ajuste_stock', 'precio')),
    rol text REFERENCES roles(codigo),
    usuario_id bigint REFERENCES usuarios(id) ON DELETE CASCADE,
    monto_maximo numeric(18, 2) NOT NULL CHECK (monto_maximo >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    CHECK ((rol IS NULL) <> (usuario_id IS NULL))
);
CREATE UNIQUE INDEX limites_por_rol ON limites_aprobacion (org_id, tipo_documento, rol) WHERE rol IS NOT NULL;
CREATE UNIQUE INDEX limites_por_usuario ON limites_aprobacion (org_id, tipo_documento, usuario_id) WHERE usuario_id IS NOT NULL;

-- Sesiones: solo guarda el hash del token. Sin datos de negocio; no lleva RLS.
CREATE TABLE sesiones (
    id bigserial PRIMARY KEY,
    usuario_id bigint NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    token_hash text NOT NULL UNIQUE,
    org_activa bigint REFERENCES organizaciones(id),  -- superadmin: empresa en la que entró
    pendiente_2fa boolean NOT NULL DEFAULT false,
    creada timestamptz NOT NULL DEFAULT now(),
    vence timestamptz NOT NULL,
    revocada boolean NOT NULL DEFAULT false,
    ip text
);

CREATE TABLE auditoria (
    id bigserial PRIMARY KEY,
    org_id bigint REFERENCES organizaciones(id),
    usuario_id bigint REFERENCES usuarios(id) ON DELETE SET NULL,
    accion text NOT NULL,
    objeto text NOT NULL,
    objeto_id text,
    detalle jsonb NOT NULL DEFAULT '{}',
    ip text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX auditoria_org_fecha ON auditoria (org_id, created_at DESC);

-- ---------------------------------------------------------------- Row Level Security
ALTER TABLE organizaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizaciones FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON organizaciones USING (id = app_org() OR app_superadmin());

ALTER TABLE ubicaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE ubicaciones FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON ubicaciones
    USING ((org_id = app_org() AND app_ve_ubicacion(id)) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());

ALTER TABLE canales ENABLE ROW LEVEL SECURITY;
ALTER TABLE canales FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON canales USING (org_id = app_org() OR app_superadmin());

ALTER TABLE plataformas ENABLE ROW LEVEL SECURITY;
ALTER TABLE plataformas FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON plataformas USING (org_id = app_org() OR app_superadmin());

-- Un usuario siempre puede leerse a sí mismo (así se arma la sesión antes de conocer su empresa).
ALTER TABLE usuarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE usuarios FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON usuarios
    USING (org_id = app_org() OR id = app_usuario()
           OR lower(email) = lower(coalesce(current_setting('app.login_email', true), ''))
           OR app_superadmin())
    WITH CHECK (org_id = app_org() OR id = app_usuario() OR app_superadmin());

ALTER TABLE usuario_ubicaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE usuario_ubicaciones FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON usuario_ubicaciones
    USING ((org_id = app_org() AND (app_ve_ubicacion(ubicacion_id) OR usuario_id = app_usuario())) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());

ALTER TABLE limites_aprobacion ENABLE ROW LEVEL SECURITY;
ALTER TABLE limites_aprobacion FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON limites_aprobacion USING (org_id = app_org() OR app_superadmin());

ALTER TABLE auditoria ENABLE ROW LEVEL SECURITY;
ALTER TABLE auditoria FORCE ROW LEVEL SECURITY;
CREATE POLICY lectura ON auditoria FOR SELECT USING (org_id = app_org() OR app_superadmin());
CREATE POLICY escritura ON auditoria FOR INSERT
    WITH CHECK (org_id IS NULL OR org_id = app_org() OR app_superadmin());
