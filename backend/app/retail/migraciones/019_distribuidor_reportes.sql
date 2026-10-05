-- SPEC v2 · modo distribuidor, reportes iniciales (12B.7). Umbrales de «cliente en riesgo / perdido», configurables por empresa:
-- en riesgo si lleva más de factor_riesgo × su intervalo habitual sin comprar; perdido si más de factor_perdido × (y al menos min_dias).
ALTER TABLE organizaciones
    ADD COLUMN cliente_factor_riesgo numeric(5,2) NOT NULL DEFAULT 1.5 CHECK (cliente_factor_riesgo >= 1),
    ADD COLUMN cliente_factor_perdido numeric(5,2) NOT NULL DEFAULT 3 CHECK (cliente_factor_perdido >= 1),
    ADD COLUMN cliente_perdido_min_dias int NOT NULL DEFAULT 21 CHECK (cliente_perdido_min_dias BETWEEN 7 AND 365);

CREATE INDEX pedidos_venta_vendedor ON pedidos_venta (org_id, vendedor_id, fecha);
CREATE INDEX documentos_cc_saldo ON documentos_cc (org_id, cliente_id) WHERE saldo <> 0;
