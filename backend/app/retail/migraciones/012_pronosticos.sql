-- Predicciones · parte A: rango de confianza, probabilidad de quiebre y registro de pronósticos para medir el error.
ALTER TABLE metricas_producto_actual ADD COLUMN pronostico_7d numeric(14,3);
ALTER TABLE metricas_producto_actual ADD COLUMN pronostico_7d_min numeric(14,3);
ALTER TABLE metricas_producto_actual ADD COLUMN pronostico_7d_max numeric(14,3);
ALTER TABLE metricas_producto_actual ADD COLUMN prob_quiebre numeric(6,4);      -- antes de la próxima llegada

CREATE TABLE pronosticos_registro (          -- lo que se pronosticó cada día para los 7 siguientes (se compara con lo real)
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),
    fecha date NOT NULL,                     -- día del cálculo; cubre fecha … fecha + 6
    pronostico numeric(14,3) NOT NULL,
    minimo numeric(14,3) NOT NULL,
    maximo numeric(14,3) NOT NULL,
    origen text NOT NULL DEFAULT 'diario' CHECK (origen IN ('diario', 'prueba_pasado')),
    PRIMARY KEY (producto_id, ubicacion_id, fecha)
);
CREATE INDEX pronosticos_registro_org ON pronosticos_registro (org_id, fecha);
ALTER TABLE pronosticos_registro ENABLE ROW LEVEL SECURITY;
ALTER TABLE pronosticos_registro FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON pronosticos_registro USING ((org_id = app_org() AND app_ve_ubicacion(ubicacion_id)) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());
