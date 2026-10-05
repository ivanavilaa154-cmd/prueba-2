-- SPEC v2 · diagnóstico de calidad de datos (sección 5.6): resultado de cada revisión y confianza de los datos de cada producto.
CREATE TABLE chequeos_calidad (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    fecha date NOT NULL,
    puntaje numeric(5,2) NOT NULL CHECK (puntaje BETWEEN 0 AND 100),
    detalle jsonb NOT NULL,                                -- {problemas: [{codigo, titulo, cantidad, productos, ...}], comercial: {...}}
    origen text NOT NULL DEFAULT 'semanal' CHECK (origen IN ('semanal', 'conexion', 'manual')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX chequeos_calidad_fecha ON chequeos_calidad (org_id, created_at DESC);

CREATE TABLE calidad_productos (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint PRIMARY KEY REFERENCES productos(id) ON DELETE CASCADE,
    problemas text[] NOT NULL DEFAULT '{}',
    confianza text NOT NULL CHECK (confianza IN ('alta', 'media', 'baja')),
    updated_at timestamptz NOT NULL DEFAULT now()
);

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['chequeos_calidad', 'calidad_productos']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY aislamiento ON %I USING (org_id = app_org() OR app_superadmin()) '
                       'WITH CHECK (org_id = app_org() OR app_superadmin())', t);
    END LOOP;
END $$;
