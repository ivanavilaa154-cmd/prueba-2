-- Predicciones · corrección del sesgo y parte B/C.
ALTER TABLE pronosticos_registro ADD COLUMN factor numeric(6,4) NOT NULL DEFAULT 1;     -- corrección de sesgo aplicada ese día

-- Liquidaciones activas (caso aplicado del documento de predicciones): control de ejecución en el local.
CREATE TABLE liquidacion_controles (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    promocion_id bigint NOT NULL REFERENCES promociones(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    tipo text NOT NULL CHECK (tipo IN ('control', 'reposicion', 'escalon', 'exhibicion')),
    armada boolean,
    cartel boolean,
    precio_ok boolean,
    foto text,                                  -- archivo guardado en backend/documentos/liquidaciones
    detalle jsonb NOT NULL DEFAULT '{}',
    created_by bigint REFERENCES usuarios(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX liquidacion_controles_promo ON liquidacion_controles (promocion_id, created_at DESC);
ALTER TABLE liquidacion_controles ENABLE ROW LEVEL SECURITY;
ALTER TABLE liquidacion_controles FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON liquidacion_controles USING ((org_id = app_org() AND app_ve_ubicacion(ubicacion_id)) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());
