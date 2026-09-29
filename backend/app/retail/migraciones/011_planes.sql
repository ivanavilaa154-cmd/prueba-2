-- Retail · 13.6 Planes y facturación: planes por cantidad de sucursales y módulos, período de prueba y pagos de la suscripción.
CREATE TABLE planes (                                   -- global: los define la administración de la plataforma
    codigo text PRIMARY KEY,
    nombre text NOT NULL,
    max_sucursales int,                                 -- nulo = sin límite (cuenta sucursales de venta, no depósitos)
    modulos text[] NOT NULL,                            -- base, avanzado, completo
    precio_mensual numeric(16,2),                       -- nulo = a definir
    orden int NOT NULL DEFAULT 0,
    activo boolean NOT NULL DEFAULT true
);
INSERT INTO planes (codigo, nombre, max_sucursales, modulos, orden) VALUES
 ('prueba', 'Prueba (30 días, todo incluido)', NULL, '{base,avanzado,completo}', 0),
 ('inicial', 'Inicial', 1, '{base}', 1),
 ('crecimiento', 'Crecimiento', 5, '{base,avanzado}', 2),
 ('cadena', 'Cadena', NULL, '{base,avanzado,completo}', 3);

ALTER TABLE organizaciones ADD COLUMN prueba_hasta date;
ALTER TABLE organizaciones ADD COLUMN pagado_hasta date;
UPDATE organizaciones SET prueba_hasta = greatest(created_at::date, current_date) + 30 WHERE prueba_hasta IS NULL;
ALTER TABLE organizaciones ALTER COLUMN prueba_hasta SET DEFAULT current_date + 30;

CREATE TABLE pagos_suscripcion (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    fecha date NOT NULL DEFAULT current_date,
    plan text NOT NULL REFERENCES planes(codigo),
    monto numeric(16,2) NOT NULL CHECK (monto >= 0),
    medio text NOT NULL,                                -- transferencia, mercado_pago, efectivo, otro
    cubre_hasta date NOT NULL,
    nota text,
    registrado_por bigint REFERENCES usuarios(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE pagos_suscripcion ENABLE ROW LEVEL SECURITY;
ALTER TABLE pagos_suscripcion FORCE ROW LEVEL SECURITY;
CREATE POLICY lectura ON pagos_suscripcion FOR SELECT USING (org_id = app_org() OR app_superadmin());
CREATE POLICY escritura ON pagos_suscripcion FOR INSERT WITH CHECK (app_superadmin());   -- los pagos los registra la plataforma
