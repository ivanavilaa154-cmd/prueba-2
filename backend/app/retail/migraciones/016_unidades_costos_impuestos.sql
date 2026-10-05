-- SPEC v2 · unidades y conversiones, costos de reposición e histórico, impuestos y descuentos de proveedor (sección 4).

-- Conversiones exactas a la unidad base del producto (la unidad en que se vende: unidad o kg). factor = unidades base por 1 de
-- esta unidad (bulto de 12 → 12; caja de 6 packs de 4 → 24; gramo de un producto por kg → 0,001). Por proveedor si difiere.
CREATE TABLE conversiones_unidad (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    unidad text NOT NULL CHECK (unidad ~ '^[a-záéíóúñ ]{1,20}$'),
    factor numeric(16,6) NOT NULL CHECK (factor > 0),
    proveedor_id bigint REFERENCES proveedores(id) ON DELETE CASCADE,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    UNIQUE NULLS NOT DISTINCT (producto_id, unidad, proveedor_id)
);

-- Impuestos (Argentina). El precio de venta al público incluye IVA. Para el margen se usan importes netos de impuestos
-- recuperables (IVA y percepciones de IIBB); los impuestos internos no son recuperables para quien revende: quedan en el costo.
ALTER TABLE productos ADD COLUMN iva numeric(5,4) NOT NULL DEFAULT 0.21 CHECK (iva >= 0 AND iva < 1);
ALTER TABLE productos ADD COLUMN impuestos_internos numeric(6,4) NOT NULL DEFAULT 0 CHECK (impuestos_internos >= 0 AND impuestos_internos < 1);
CREATE TABLE reglas_impuesto (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    categoria_id bigint REFERENCES categorias(id) ON DELETE CASCADE,
    producto_id bigint REFERENCES productos(id) ON DELETE CASCADE,
    iva numeric(5,4) NOT NULL CHECK (iva >= 0 AND iva < 1),            -- 0,21 · 0,105 · 0 (exento)
    impuestos_internos numeric(6,4) NOT NULL DEFAULT 0 CHECK (impuestos_internos >= 0 AND impuestos_internos < 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    CHECK ((categoria_id IS NULL) <> (producto_id IS NULL)),
    UNIQUE NULLS NOT DISTINCT (org_id, categoria_id, producto_id)
);
-- Cómo vienen cargados los costos de la empresa (facturas de un responsable inscripto: sin IVA). Percepción de IIBB por proveedor
-- (es a cuenta del impuesto: recuperable, no forma parte del costo).
ALTER TABLE organizaciones ADD COLUMN costos_con_iva boolean NOT NULL DEFAULT false;
ALTER TABLE proveedores ADD COLUMN percepcion_iibb numeric(6,4) NOT NULL DEFAULT 0 CHECK (percepcion_iibb >= 0 AND percepcion_iibb < 1);

-- Descuentos y bonificaciones del proveedor, imputables al costo de reposición: un porcentaje (con escala por cantidad) o una
-- bonificación en unidades (12 + 1 = 1 cada 13 sin cargo). Por producto o por categoría; vacío = todo el proveedor.
CREATE TABLE descuentos_proveedor (
    id bigserial PRIMARY KEY,
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    proveedor_id bigint NOT NULL REFERENCES proveedores(id) ON DELETE CASCADE,
    producto_id bigint REFERENCES productos(id) ON DELETE CASCADE,
    categoria_id bigint REFERENCES categorias(id) ON DELETE CASCADE,
    tipo text NOT NULL CHECK (tipo IN ('porcentaje', 'bonificacion', 'nota_credito')),
    porcentaje numeric(6,4) CHECK (porcentaje IS NULL OR (porcentaje > 0 AND porcentaje < 1)),
    compra_unidades int CHECK (compra_unidades IS NULL OR compra_unidades > 0),     -- bonificación: comprando N…
    bonifica_unidades int CHECK (bonifica_unidades IS NULL OR bonifica_unidades > 0), -- …recibe M sin cargo
    desde_cantidad numeric(14,3) NOT NULL DEFAULT 0,       -- escala: aplica desde esta cantidad por pedido (unidades base)
    vigente_desde date NOT NULL DEFAULT current_date,
    vigente_hasta date,
    descripcion text,
    created_at timestamptz NOT NULL DEFAULT now(),
    created_by bigint,
    CHECK ((tipo = 'bonificacion') = (compra_unidades IS NOT NULL AND bonifica_unidades IS NOT NULL)),
    CHECK (tipo = 'bonificacion' OR porcentaje IS NOT NULL)
);

-- Costo de reposición (última lista vigente del proveedor principal, menos descuentos, sin impuestos recuperables) y costo
-- histórico (promedio ponderado de las recepciones de 12 meses). Los calcula el proceso nocturno; el margen usa el de reposición.
CREATE TABLE costos_producto (
    org_id bigint NOT NULL REFERENCES organizaciones(id),
    producto_id bigint PRIMARY KEY REFERENCES productos(id) ON DELETE CASCADE,
    costo_lista numeric(16,4),                              -- tal como está cargado (con o sin IVA según la empresa)
    costo_reposicion numeric(16,4),                         -- neto de impuestos recuperables y de descuentos
    costo_reposicion_fecha date,
    costo_historico numeric(16,4),                          -- neto de impuestos recuperables
    costo_historico_fecha date,
    descuento_aplicado numeric(6,4) NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Ganancia neta en los agregados: la facturación sigue siendo lo que pagó el cliente (con IVA).
ALTER TABLE agg_producto_ubicacion_dia ADD COLUMN facturacion_neta numeric(16,2) NOT NULL DEFAULT 0;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['conversiones_unidad', 'reglas_impuesto', 'descuentos_proveedor', 'costos_producto']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY aislamiento ON %I USING (org_id = app_org() OR app_superadmin()) '
                       'WITH CHECK (org_id = app_org() OR app_superadmin())', t);
    END LOOP;
END $$;

-- Datos ya agregados: ganancia neta con el IVA por defecto (21 %); el próximo cálculo nocturno la recalcula con el IVA de cada producto.
UPDATE agg_producto_ubicacion_dia a SET facturacion_neta = round(a.facturacion / (1 + p.iva), 2),
       ganancia = round(a.facturacion / (1 + p.iva), 2) - a.costo
FROM productos p WHERE p.id = a.producto_id;
