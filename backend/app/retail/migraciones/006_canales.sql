-- Retail · Fase 2, sección 12: publicaciones en las plataformas y estado de los pedidos online.
CREATE TABLE publicaciones (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    plataforma_id bigint NOT NULL REFERENCES plataformas(id) ON DELETE CASCADE,
    producto_id bigint REFERENCES productos(id) ON DELETE SET NULL,    -- nulo = sin emparejar
    id_externo text NOT NULL,                                         -- id de la publicación o variante en la plataforma
    sku text,
    titulo text,
    precio numeric(16,2),
    stock_publicado numeric(14,3) NOT NULL DEFAULT 0,
    activa boolean NOT NULL DEFAULT true,
    actualizado_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (plataforma_id, id_externo)
);
CREATE INDEX publicaciones_producto ON publicaciones (org_id, producto_id);

CREATE TABLE pedidos_online (
    ticket_id bigint PRIMARY KEY REFERENCES tickets(id) ON DELETE CASCADE,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    ubicacion_id bigint NOT NULL REFERENCES ubicaciones(id),           -- la que despacha
    plataforma_id bigint NOT NULL REFERENCES plataformas(id),
    estado text NOT NULL CHECK (estado IN ('pendiente', 'despachado', 'entregado', 'cancelado', 'devuelto')),
    creado_at timestamptz NOT NULL,
    despachado_at timestamptz,
    reclamo boolean NOT NULL DEFAULT false,
    motivo text
);
CREATE INDEX pedidos_online_estado ON pedidos_online (org_id, estado);

ALTER TABLE publicaciones ENABLE ROW LEVEL SECURITY;
ALTER TABLE publicaciones FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON publicaciones USING (org_id = app_org() OR app_superadmin()) WITH CHECK (org_id = app_org() OR app_superadmin());
ALTER TABLE pedidos_online ENABLE ROW LEVEL SECURITY;
ALTER TABLE pedidos_online FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON pedidos_online USING ((org_id = app_org() AND app_ve_ubicacion(ubicacion_id)) OR app_superadmin())
    WITH CHECK (org_id = app_org() OR app_superadmin());

-- Consultas por rango de fechas (impacto, merma, sucursales).
CREATE INDEX stock_diario_fecha ON stock_diario (org_id, fecha);
CREATE INDEX movimientos_stock_fecha ON movimientos_stock (org_id, tipo, fecha);

-- Claves foráneas hacia tickets: sin índice, borrar tickets (regenerar la demo) recorre cada tabla hija por ticket.
CREATE INDEX IF NOT EXISTS tickets_lineas_ticket ON tickets_lineas (ticket_id);
CREATE INDEX IF NOT EXISTS pagos_ticket ON pagos (ticket_id);
CREATE INDEX IF NOT EXISTS anulaciones_ticket ON anulaciones_devoluciones (ticket_id);
CREATE INDEX IF NOT EXISTS costos_canal_ticket ON costos_canal (ticket_id);
