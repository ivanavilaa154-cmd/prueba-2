-- SPEC v2 · Fase 2 · 12B.3 Rutas y cobertura: comercios conocidos de cada zona que todavía no son clientes (prospectos) y el umbral de
-- «clientes sin visita en X días» (configurable por empresa).
CREATE TABLE prospectos (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    razon_social text NOT NULL,
    direccion text,
    localidad text,
    zona text,
    canal text,
    fuente text,                                   -- de dónde salió (relevamiento, cámara, archivo…)
    codigo_externo text,
    cliente_id bigint REFERENCES clientes_b2b(id) ON DELETE SET NULL,   -- si se convirtió en cliente
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (org_id, codigo_externo)
);
ALTER TABLE prospectos ENABLE ROW LEVEL SECURITY;
ALTER TABLE prospectos FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON prospectos USING (org_id = app_org() OR app_superadmin()) WITH CHECK (org_id = app_org() OR app_superadmin());
ALTER TABLE organizaciones ADD COLUMN dias_sin_visita int NOT NULL DEFAULT 14 CHECK (dias_sin_visita BETWEEN 3 AND 120);
CREATE INDEX visitas_cliente_fecha ON visitas (org_id, cliente_id, fecha);
