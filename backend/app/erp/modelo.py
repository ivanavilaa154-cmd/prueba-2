"""Modelo de datos estándar de la plataforma.

Todo sistema que se integra (Odoo, archivos CSV/Excel, la base de un ERP) se
traduce a estas tablas. Así el chat, los permisos, el tablero y los controles
funcionan igual con cualquiera. Todo campo es opcional salvo los mínimos de
cada tabla (MINIMOS): si un sistema no tiene un dato, queda vacío y los
indicadores que lo necesitan dicen que falta, en lugar de inventarlo.

Convenciones: importes en la moneda de la fila (moneda vacía = moneda de la
empresa), fechas AAAA-MM-DD, horas HH:MM, sí/no como 1/0, meses AAAA-MM.
La descripción de cada campo está en config/diccionario_datos.yaml.
"""
from __future__ import annotations

ESQUEMA = """
-- ============ VENTAS ============
CREATE TABLE clientes (id INTEGER PRIMARY KEY, razon_social TEXT, nombre_fantasia TEXT, tipo TEXT, canal TEXT,
    zona TEXT, direccion TEXT, ciudad TEXT, latitud REAL, longitud REAL, ruta TEXT, dia_visita TEXT,
    vendedor_id INTEGER, lista_precios_id INTEGER, condicion_pago_dias INTEGER, limite_credito REAL,
    fecha_alta TEXT, estado TEXT);
CREATE TABLE vendedores (id INTEGER PRIMARY KEY, nombre TEXT, sucursal_id INTEGER, zona TEXT, equipo TEXT,
    comision_pct REAL, activo INTEGER);
CREATE TABLE objetivos_vendedores (vendedor_id INTEGER, mes TEXT, objetivo_venta REAL);
CREATE TABLE visitas (id INTEGER PRIMARY KEY, vendedor_id INTEGER, cliente_id INTEGER, fecha TEXT, hora TEXT,
    resultado TEXT, con_pedido INTEGER);
CREATE TABLE ventas (id INTEGER PRIMARY KEY, tipo TEXT, numero TEXT, fecha TEXT, hora TEXT, cliente_id INTEGER,
    vendedor_id INTEGER, sucursal_id INTEGER, canal TEXT, moneda TEXT, condicion_pago_dias INTEGER, medio_pago TEXT,
    caja TEXT, anulada INTEGER DEFAULT 0, motivo_anulacion TEXT);
CREATE TABLE ventas_lineas (venta_id INTEGER, producto_id INTEGER, cantidad REAL, precio_lista REAL,
    descuento_pct REAL, precio_unitario REAL, costo_unitario REAL, impuestos REAL, en_promocion INTEGER);
CREATE TABLE devoluciones (id INTEGER PRIMARY KEY, fecha TEXT, cliente_id INTEGER, venta_id INTEGER,
    producto_id INTEGER, cantidad REAL, importe REAL, motivo TEXT);
CREATE TABLE pedidos (id INTEGER PRIMARY KEY, numero TEXT, cliente_id INTEGER, vendedor_id INTEGER,
    sucursal_id INTEGER, fecha_pedido TEXT, fecha_entrega_prometida TEXT, fecha_entrega TEXT, estado TEXT,
    motivo_anulacion TEXT);
CREATE TABLE pedidos_lineas (pedido_id INTEGER, producto_id INTEGER, cantidad_pedida REAL, cantidad_entregada REAL);
CREATE TABLE presupuestos (id INTEGER PRIMARY KEY, numero TEXT, cliente_id INTEGER, vendedor_id INTEGER, fecha TEXT,
    importe REAL, estado TEXT, venta_id INTEGER);
CREATE TABLE listas_precios (id INTEGER PRIMARY KEY, nombre TEXT, moneda TEXT);
CREATE TABLE precios (lista_precios_id INTEGER, producto_id INTEGER, precio REAL, desde TEXT);
CREATE TABLE promociones (id INTEGER PRIMARY KEY, nombre TEXT, producto_id INTEGER, desde TEXT, hasta TEXT,
    tipo TEXT, precio_promocional REAL, descuento_pct REAL, financia_proveedor INTEGER);

-- ============ INVENTARIO ============
CREATE TABLE sucursales (id INTEGER PRIMARY KEY, nombre TEXT, tipo TEXT);
CREATE TABLE productos (id INTEGER PRIMARY KEY, codigo TEXT, codigo_barras TEXT, descripcion TEXT, marca TEXT,
    categoria TEXT, subcategoria TEXT, familia TEXT, proveedor_id INTEGER, unidad TEXT, unidades_bulto INTEGER,
    multiplo_compra REAL, peso_kg REAL, volumen_m3 REAL, pesable INTEGER, perecedero INTEGER, vida_util_dias INTEGER,
    es_kit INTEGER, tasa_iva REAL, estado TEXT, fecha_alta TEXT, costo REAL, precio REAL);
CREATE TABLE componentes_kit (kit_id INTEGER, producto_id INTEGER, cantidad REAL);
CREATE TABLE stock (producto_id INTEGER, sucursal_id INTEGER, ubicacion TEXT, lote TEXT, fecha_vencimiento TEXT,
    cantidad REAL, comprometido REAL, en_transito REAL);
CREATE TABLE movimientos_stock (id INTEGER PRIMARY KEY, fecha TEXT, producto_id INTEGER, sucursal_id INTEGER,
    tipo TEXT, motivo TEXT, cantidad REAL, costo_unitario REAL, comprobante TEXT, usuario TEXT);
CREATE TABLE proveedores (id INTEGER PRIMARY KEY, nombre TEXT, plazo_pago_dias INTEGER, plazo_entrega_dias INTEGER,
    pedido_minimo REAL, pedido_minimo_unidades REAL, dias_pedido TEXT, descuento_pronto_pago_pct REAL,
    acepta_devolucion_vencidos INTEGER);
CREATE TABLE compras (id INTEGER PRIMARY KEY, numero TEXT, proveedor_id INTEGER, sucursal_id INTEGER, fecha TEXT,
    fecha_prometida TEXT, fecha_recepcion TEXT, estado TEXT, moneda TEXT);
CREATE TABLE compras_lineas (compra_id INTEGER, producto_id INTEGER, cantidad_pedida REAL, cantidad_recibida REAL,
    precio_pactado REAL, precio_facturado REAL);
CREATE TABLE costos_historial (producto_id INTEGER, fecha TEXT, costo REAL);
CREATE TABLE conteos (id INTEGER PRIMARY KEY, fecha TEXT, producto_id INTEGER, sucursal_id INTEGER,
    cantidad_contada REAL, cantidad_sistema REAL, usuario TEXT);

-- ============ FINANZAS ============
CREATE TABLE cxc (id INTEGER PRIMARY KEY, tipo TEXT, numero TEXT, cliente_id INTEGER, vendedor_id INTEGER,
    fecha_emision TEXT, fecha_vencimiento TEXT, fecha_cobro TEXT, moneda TEXT, importe REAL, saldo REAL);
CREATE TABLE cobranzas (id INTEGER PRIMARY KEY, fecha TEXT, cliente_id INTEGER, medio TEXT, importe REAL,
    moneda TEXT, cxc_id INTEGER);
CREATE TABLE cheques (id INTEGER PRIMARY KEY, tipo TEXT, numero TEXT, banco TEXT, cliente_id INTEGER,
    proveedor_id INTEGER, fecha_emision TEXT, fecha_cobro TEXT, importe REAL, moneda TEXT, estado TEXT);
CREATE TABLE cxp (id INTEGER PRIMARY KEY, tipo TEXT, numero TEXT, proveedor_id INTEGER, fecha_emision TEXT,
    fecha_vencimiento TEXT, fecha_pago TEXT, moneda TEXT, importe REAL, saldo REAL);
CREATE TABLE pagos (id INTEGER PRIMARY KEY, fecha TEXT, proveedor_id INTEGER, medio TEXT, importe REAL,
    moneda TEXT, cxp_id INTEGER);
CREATE TABLE cuentas_bancarias (id INTEGER PRIMARY KEY, nombre TEXT, tipo TEXT, moneda TEXT, saldo REAL, fecha_saldo TEXT);
CREATE TABLE movimientos_bancarios (id INTEGER PRIMARY KEY, cuenta_id INTEGER, fecha TEXT, concepto TEXT,
    importe REAL, conciliado INTEGER);
CREATE TABLE gastos (id INTEGER PRIMARY KEY, fecha TEXT, sucursal_id INTEGER, cuenta TEXT, categoria TEXT,
    importe REAL, moneda TEXT);
CREATE TABLE impuestos (id INTEGER PRIMARY KEY, impuesto TEXT, periodo TEXT, vencimiento TEXT, importe REAL, estado TEXT);
CREATE TABLE prestamos (id INTEGER PRIMARY KEY, entidad TEXT, moneda TEXT, capital REAL, tasa_anual REAL,
    fecha_inicio TEXT, cuotas INTEGER, cuota_importe REAL, saldo REAL, proximo_vencimiento TEXT);
CREATE TABLE tipos_cambio (fecha TEXT, moneda TEXT, cotizacion REAL);
CREATE TABLE presupuesto (mes TEXT, concepto TEXT, sucursal_id INTEGER, importe REAL);
"""

# A qué pilar pertenece cada tabla (para el informe de cobertura y el diccionario).
PILARES = {
    "Ventas": ["clientes", "vendedores", "objetivos_vendedores", "visitas", "ventas", "ventas_lineas", "devoluciones",
               "pedidos", "pedidos_lineas", "presupuestos", "listas_precios", "precios", "promociones"],
    "Inventario": ["sucursales", "productos", "componentes_kit", "stock", "movimientos_stock", "proveedores",
                   "compras", "compras_lineas", "costos_historial", "conteos"],
    "Finanzas": ["cxc", "cobranzas", "cheques", "cxp", "pagos", "cuentas_bancarias", "movimientos_bancarios",
                 "gastos", "impuestos", "prestamos", "tipos_cambio", "presupuesto"],
}

# Columnas sin las cuales una fila no sirve. El resto puede faltar.
MINIMOS = {
    "clientes": ["id"], "vendedores": ["id"], "objetivos_vendedores": ["vendedor_id", "mes", "objetivo_venta"],
    "visitas": ["vendedor_id", "fecha"], "ventas": ["id", "fecha"], "ventas_lineas": ["venta_id", "producto_id", "cantidad", "precio_unitario"],
    "devoluciones": ["fecha", "importe"], "pedidos": ["id", "fecha_pedido"], "pedidos_lineas": ["pedido_id", "producto_id", "cantidad_pedida"],
    "presupuestos": ["id", "fecha", "importe"], "listas_precios": ["id"], "precios": ["producto_id", "precio"],
    "promociones": ["desde", "hasta"],
    "sucursales": ["id"], "productos": ["id"], "componentes_kit": ["kit_id", "producto_id", "cantidad"],
    "stock": ["producto_id", "cantidad"], "movimientos_stock": ["fecha", "producto_id", "tipo", "cantidad"],
    "proveedores": ["id"], "compras": ["id", "fecha"], "compras_lineas": ["compra_id", "producto_id", "cantidad_pedida"],
    "costos_historial": ["producto_id", "fecha", "costo"], "conteos": ["fecha", "producto_id", "cantidad_contada"],
    "cxc": ["saldo"], "cobranzas": ["fecha", "importe"], "cheques": ["importe"], "cxp": ["saldo"],
    "pagos": ["fecha", "importe"], "cuentas_bancarias": ["id", "saldo"], "movimientos_bancarios": ["fecha", "importe"],
    "gastos": ["fecha", "importe"], "impuestos": ["importe"], "prestamos": ["saldo"],
    "tipos_cambio": ["fecha", "moneda", "cotizacion"], "presupuesto": ["mes", "concepto", "importe"],
}

# Columnas sí/no (1/0).
BOOLEANAS = {("ventas", "anulada"), ("ventas_lineas", "en_promocion"), ("visitas", "con_pedido"),
             ("vendedores", "activo"), ("promociones", "financia_proveedor"), ("productos", "pesable"),
             ("productos", "perecedero"), ("productos", "es_kit"), ("proveedores", "acepta_devolucion_vencidos"),
             ("movimientos_bancarios", "conciliado")}

# Columnas de fecha que no empiezan con "fecha".
FECHAS_EXTRA = {"desde", "hasta", "vencimiento", "proximo_vencimiento"}

# Valores esperados en columnas de tipo (documentación y controles).
VALORES = {
    ("ventas", "tipo"): ["factura", "ticket", "remito"],
    ("movimientos_stock", "tipo"): ["venta", "compra", "devolucion_cliente", "devolucion_proveedor", "transferencia_entrada",
                                   "transferencia_salida", "ajuste", "merma", "vencimiento", "consumo_interno", "produccion"],
    ("cobranzas", "medio"): ["efectivo", "transferencia", "tarjeta", "cheque", "billetera", "otro"],
    ("cheques", "tipo"): ["recibido", "emitido"],
    ("cheques", "estado"): ["cartera", "depositado", "cobrado", "rechazado", "entregado"],
    ("cuentas_bancarias", "tipo"): ["banco", "caja"],
    ("cxc", "tipo"): ["factura", "nota_credito", "nota_debito"],
    ("cxp", "tipo"): ["factura", "nota_credito", "nota_debito"],
}


def es_fecha(columna: str) -> bool:
    return columna.startswith("fecha") or columna in FECHAS_EXTRA


def pilar_de(tabla: str) -> str | None:
    return next((p for p, tablas in PILARES.items() if tabla in tablas), None)


def actualizar_base(ruta) -> list[str]:
    """Lleva una base SQLite creada con una versión anterior al modelo actual, sin borrar datos.

    Crea las tablas que faltan y agrega las columnas que faltan (quedan vacías). Devuelve qué cambió.
    """
    import re
    import sqlite3
    from pathlib import Path

    ruta = Path(ruta)
    if not ruta.exists():
        return []
    cambios = []
    con = sqlite3.connect(ruta)
    try:
        existentes = {t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        for sentencia in [x.strip() for x in ESQUEMA.split(";") if "CREATE TABLE" in x]:
            sentencia = re.sub(r"--[^\n]*", "", sentencia).strip()
            tabla = re.search(r"CREATE TABLE (\w+)", sentencia).group(1)
            if tabla not in existentes:
                con.execute(sentencia)
                cambios.append(f"tabla {tabla}")
                continue
            tiene = {c[1] for c in con.execute(f"PRAGMA table_info({tabla})")}
            cuerpo = sentencia[sentencia.index("(") + 1: sentencia.rindex(")")]
            for definicion in re.split(r",\s*(?![^()]*\))", cuerpo):
                partes = definicion.split()
                if not partes or partes[0] in tiene:
                    continue
                tipo = " ".join(p for p in partes[1:] if p.upper() not in ("PRIMARY", "KEY"))
                con.execute(f"ALTER TABLE {tabla} ADD COLUMN {partes[0]} {tipo}")
                cambios.append(f"{tabla}.{partes[0]}")
        con.commit()
    finally:
        con.close()
    return cambios
