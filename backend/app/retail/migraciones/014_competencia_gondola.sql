-- Predicciones · parte F: precios de la competencia (16) y espacio en góndola (24). Se cargan a mano o desde un archivo.

CREATE TABLE precios_competencia (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    ubicacion_id bigint REFERENCES ubicaciones(id),          -- sucursal cercana al competidor (vacío = toda la empresa)
    competidor text NOT NULL,
    precio numeric(16,2) NOT NULL CHECK (precio > 0),
    fecha date NOT NULL,
    fuente text NOT NULL DEFAULT 'manual' CHECK (fuente IN ('manual', 'archivo')),
    created_by bigint REFERENCES usuarios(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (org_id, producto_id, competidor, fecha)
);
CREATE INDEX precios_competencia_prod ON precios_competencia (org_id, producto_id, fecha DESC);
ALTER TABLE precios_competencia ENABLE ROW LEVEL SECURITY;
ALTER TABLE precios_competencia FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON precios_competencia
    USING ((org_id = app_org() AND (ubicacion_id IS NULL OR app_ve_ubicacion(ubicacion_id))) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());

-- Espacio que ocupa cada producto en la góndola de cada sucursal: frentes y metros lineales.
CREATE TABLE espacio_gondola (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    frentes int NOT NULL DEFAULT 1 CHECK (frentes > 0),
    metros numeric(8,3) NOT NULL CHECK (metros > 0),
    updated_by bigint REFERENCES usuarios(id) ON DELETE SET NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (producto_id, ubicacion_id)
);
CREATE INDEX espacio_gondola_org ON espacio_gondola (org_id, ubicacion_id);
ALTER TABLE espacio_gondola ENABLE ROW LEVEL SECURITY;
ALTER TABLE espacio_gondola FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON espacio_gondola USING ((org_id = app_org() AND app_ve_ubicacion(ubicacion_id)) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());
