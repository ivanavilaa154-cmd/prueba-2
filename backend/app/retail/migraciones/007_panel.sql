-- Retail · Fase 3, sección 13.3: panel para distribuidores y marcas (agregado y anónimo) y portal de pedidos.
-- El distribuidor es una empresa más (tipo 'distribuidor'); sus usuarios tienen el rol 'distribuidor'.
-- Nunca ve filas de otra empresa: el servidor arma solo agregados con umbral mínimo de comercios (ver panel.py).
ALTER TABLE organizaciones ADD COLUMN tipo text NOT NULL DEFAULT 'comercio' CHECK (tipo IN ('comercio', 'distribuidor'));

CREATE TABLE marcas_distribuidor (                         -- marcas que representa (se comparan contra productos_maestros.marca)
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    marca text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    PRIMARY KEY (org_id, marca)
);
ALTER TABLE marcas_distribuidor ENABLE ROW LEVEL SECURITY;
ALTER TABLE marcas_distribuidor FORCE ROW LEVEL SECURITY;
CREATE POLICY aislamiento ON marcas_distribuidor USING (org_id = app_org() OR app_superadmin()) WITH CHECK (org_id = app_org() OR app_superadmin());

-- Portal de pedidos: el distribuidor confirma la OC que le envió el comercio (la OC sigue siendo del comercio).
ALTER TABLE ordenes_compra ADD COLUMN confirmada_proveedor_at timestamptz;
ALTER TABLE ordenes_compra ADD COLUMN entrega_prometida date;
ALTER TABLE ordenes_compra ADD COLUMN nota_proveedor text;
CREATE INDEX ordenes_compra_enviadas ON ordenes_compra (proveedor_id) WHERE enviada_at IS NOT NULL;
CREATE INDEX proveedores_cuit ON proveedores (regexp_replace(coalesce(cuit, ''), '\D', '', 'g'));

-- Claves foráneas hacia productos sin índice: borrar un producto recorría estas tablas enteras (regenerar demos, depurar catálogo).
CREATE INDEX IF NOT EXISTS tickets_lineas_producto ON tickets_lineas (producto_id);
CREATE INDEX IF NOT EXISTS movimientos_stock_producto ON movimientos_stock (producto_id);
CREATE INDEX IF NOT EXISTS ordenes_compra_lineas_producto ON ordenes_compra_lineas (producto_id);
CREATE INDEX IF NOT EXISTS recepciones_lineas_producto ON recepciones_lineas (producto_id);
CREATE INDEX IF NOT EXISTS ordenes_compra_lineas_orden ON ordenes_compra_lineas (orden_id);
