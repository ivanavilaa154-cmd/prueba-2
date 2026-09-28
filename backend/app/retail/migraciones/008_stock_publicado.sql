-- Retail · Fase 3: otras plataformas y stock publicado.
-- Por la regla 4 de CLAUDE.md, el stock publicado no se sincroniza solo: el sistema propone el valor y una persona lo aprueba;
-- recién entonces se escribe en la plataforma. Cada propuesta guarda quién la aprobó y qué respondió la plataforma.
ALTER TABLE publicaciones ADD COLUMN id_padre text;                          -- producto padre, artículo de inventario o depósito, según la plataforma
ALTER TABLE publicaciones ADD COLUMN controla_stock boolean NOT NULL DEFAULT true;

CREATE TABLE propuestas_stock (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    publicacion_id bigint NOT NULL REFERENCES publicaciones(id) ON DELETE CASCADE,
    plataforma_id bigint NOT NULL REFERENCES plataformas(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),                 -- la que despacha
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    stock_publicado numeric(14,3) NOT NULL,
    disponible numeric(14,3) NOT NULL,
    stock_propuesto integer NOT NULL CHECK (stock_propuesto >= 0),
    motivo text NOT NULL CHECK (motivo IN ('sobreventa', 'falta_publicar')),
    estado text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente', 'aplicada', 'error', 'descartada', 'reemplazada')),
    created_at timestamptz NOT NULL DEFAULT now(),
    resuelta_por bigint REFERENCES usuarios(id),
    resuelta_at timestamptz,
    respuesta text
);
CREATE UNIQUE INDEX propuestas_stock_pendiente ON propuestas_stock (publicacion_id) WHERE estado = 'pendiente';
CREATE INDEX propuestas_stock_org ON propuestas_stock (org_id, estado);
ALTER TABLE propuestas_stock ENABLE ROW LEVEL SECURITY;
ALTER TABLE propuestas_stock FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON propuestas_stock USING ((org_id = app_org() AND app_ve_ubicacion(ubicacion_id)) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());

