-- Retail · Parte 8: estado del ajuste de cada línea de recuento (los ajustes por encima del límite esperan aprobación).
ALTER TABLE recuentos_lineas ADD COLUMN estado text NOT NULL DEFAULT 'pendiente'
    CHECK (estado IN ('pendiente', 'sin_diferencia', 'ajustado', 'pendiente_aprobacion', 'rechazado'));
ALTER TABLE recuentos_lineas ADD COLUMN aprobado_por bigint REFERENCES usuarios(id);
ALTER TABLE recuentos_lineas ADD COLUMN aprobado_at timestamptz;
CREATE UNIQUE INDEX recuentos_lineas_unicas ON recuentos_lineas (recuento_id, producto_id);
