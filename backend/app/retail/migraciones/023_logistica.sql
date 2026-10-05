-- SPEC v2 · Fase 2 · 12B.5 Pedidos y logística: repartidores, devoluciones en la entrega y tiempos.
-- cantidad_entregada sigue siendo lo que el cliente se quedó; lo que devolvió en el momento de la entrega se registra aparte.
CREATE TABLE repartidores (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    nombre text NOT NULL,
    vehiculo text,
    zona text,
    activo boolean NOT NULL DEFAULT true,
    codigo_externo text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE (org_id, nombre)
);
ALTER TABLE repartidores ENABLE ROW LEVEL SECURITY;
ALTER TABLE repartidores FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON repartidores USING (org_id = app_org() OR app_superadmin()) WITH CHECK (org_id = app_org() OR app_superadmin());
ALTER TABLE entregas ADD COLUMN repartidor_id bigint REFERENCES repartidores(id) ON DELETE SET NULL;
ALTER TABLE pedidos_venta_lineas
    ADD COLUMN cantidad_devuelta numeric(14,3) NOT NULL DEFAULT 0 CHECK (cantidad_devuelta >= 0),
    ADD COLUMN motivo_devolucion text;
CREATE INDEX entregas_fecha ON entregas (org_id, fecha);
