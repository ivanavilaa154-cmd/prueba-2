-- SPEC v2 · 13.7: precisión medida (foto diaria del error de los pronósticos por empresa, para el panel interno) y medición de
-- soporte (tiempo de implementación y tickets por empresa) para controlar el costo de servir.
CREATE TABLE precision_pronosticos (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    fecha date NOT NULL,
    wape numeric(8,4),                 -- Σ|real − pronóstico| / Σ real
    mape numeric(8,4),                 -- promedio de |real − pronóstico| / real, en producto-semanas con venta
    sesgo numeric(8,4),
    cobertura numeric(6,4),            -- cuántas veces la venta real cayó dentro del rango
    evaluados int NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, fecha)
);
CREATE TABLE tickets_soporte (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    asunto text NOT NULL,
    detalle text,
    tema text NOT NULL DEFAULT 'uso' CHECK (tema IN ('implementacion', 'datos', 'conexion', 'uso', 'error', 'facturacion', 'otro')),
    estado text NOT NULL DEFAULT 'abierto' CHECK (estado IN ('abierto', 'resuelto')),
    origen text NOT NULL DEFAULT 'cliente' CHECK (origen IN ('cliente', 'plataforma')),
    minutos int NOT NULL DEFAULT 0 CHECK (minutos >= 0),          -- tiempo dedicado por la plataforma
    respuesta text,
    created_at timestamptz NOT NULL DEFAULT now(),
    resuelto_at timestamptz,
    created_by bigint REFERENCES usuarios(id) ON DELETE SET NULL
);
CREATE INDEX tickets_soporte_org ON tickets_soporte (org_id, created_at);
DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['precision_pronosticos', 'tickets_soporte'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY aislamiento ON %I USING (org_id = app_org() OR app_superadmin()) WITH CHECK (org_id = app_org() OR app_superadmin())', t);
    END LOOP;
END $$;
ALTER TABLE organizaciones
    ADD COLUMN implementacion_lista_at timestamptz,               -- primer cálculo con datos: desde acá la empresa usa la plataforma
    ADD COLUMN implementacion_horas numeric(8,2) NOT NULL DEFAULT 0 CHECK (implementacion_horas >= 0);   -- horas de la plataforma
