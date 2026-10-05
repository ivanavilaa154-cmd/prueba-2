-- SPEC v2 · agente de sincronización local (sección 5.1): un programa en la PC del local sube las exportaciones del sistema de caja
-- desde una carpeta. Se identifica con un token propio (se guarda solo su hash) y reporta su estado en cada conexión.
CREATE TABLE agentes_sincronizacion (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    nombre text NOT NULL,
    token_hash text NOT NULL UNIQUE,
    activo boolean NOT NULL DEFAULT true,
    version text,
    equipo text,                                           -- nombre de la PC que informa el agente
    carpeta text,                                          -- la carpeta que vigila (informada por el agente)
    ultima_conexion timestamptz,
    ultima_subida timestamptz,
    archivos_subidos int NOT NULL DEFAULT 0,
    pendientes int NOT NULL DEFAULT 0,                     -- archivos en su cola local (por ejemplo, sin internet)
    ultimo_error text,
    ultimo_error_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint REFERENCES usuarios(id) ON DELETE SET NULL
);
ALTER TABLE agentes_sincronizacion ENABLE ROW LEVEL SECURITY;
ALTER TABLE agentes_sincronizacion FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON agentes_sincronizacion USING (org_id = app_org() OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());
ALTER TABLE lotes_importacion ADD COLUMN agente_id bigint REFERENCES agentes_sincronizacion(id) ON DELETE SET NULL;
-- Encabezados en su orden original: para retomar después la confirmación de columnas de un archivo que subió el agente.
ALTER TABLE lotes_importacion ADD COLUMN encabezados jsonb;
