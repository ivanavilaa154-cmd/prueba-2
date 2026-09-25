"""Crea una base SQLite de demostración que imita un ERP de distribuidor B2B.

Uso:  python -m app.erp.demo
Los datos se generan con semilla fija, así las pruebas son reproducibles.
"""
from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from .. import config

from .modelo import ESQUEMA  # noqa: E402  (se reexporta: otros módulos lo importan desde acá)

PRODUCTOS = [
    # descripcion, categoria, proveedor, costo, margen, bulto, perecedero
    ("Leche entera 1 L", "Lácteos", 1, 38, 0.18, 12, 1),
    ("Yogur bebible 1 L", "Lácteos", 1, 62, 0.25, 12, 1),
    ("Queso colonia kg", "Lácteos", 1, 390, 0.28, 1, 1),
    ("Aceite girasol 900 ml", "Almacén", 2, 95, 0.17, 12, 0),
    ("Arroz 1 kg", "Almacén", 2, 48, 0.20, 10, 0),
    ("Fideos secos 500 g", "Almacén", 2, 33, 0.24, 20, 0),
    ("Salsa de tomate 340 g", "Almacén", 2, 29, 0.30, 24, 0),
    ("Yerba 1 kg", "Almacén", 3, 185, 0.19, 10, 0),
    ("Azúcar 1 kg", "Almacén", 3, 44, 0.15, 10, 0),
    ("Refresco cola 2 L", "Bebidas", 4, 70, 0.22, 6, 0),
    ("Agua mineral 2 L", "Bebidas", 4, 32, 0.30, 6, 0),
    ("Cerveza 1 L", "Bebidas", 4, 88, 0.26, 12, 0),
    ("Detergente 750 ml", "Limpieza", 5, 58, 0.32, 12, 0),
    ("Lavandina 1 L", "Limpieza", 5, 26, 0.35, 12, 0),
    ("Papel higiénico x4", "Limpieza", 5, 72, 0.27, 12, 0),
]

CLIENTES = [
    ("Almacén López", "almacén", "Centro", 1), ("Autoservicio López Hnos", "autoservicio", "Norte", 2),
    ("Kiosco El Sol", "kiosco", "Centro", 1), ("Almacén Don Pepe", "almacén", "Centro", 1),
    ("Super Barrio", "autoservicio", "Norte", 2), ("Restaurante La Esquina", "restaurante", "Centro", 3),
    ("Almacén Rosa", "almacén", "Norte", 2), ("Kiosco 24 h", "kiosco", "Norte", 2),
    ("Autoservicio El Ahorro", "autoservicio", "Centro", 3), ("Almacén La Familia", "almacén", "Norte", 3),
    ("Parrilla Los Amigos", "restaurante", "Norte", 3), ("Almacén Mary", "almacén", "Centro", 1),
]


def _insertar(con, tabla: str, **valores) -> None:
    columnas = list(valores)
    con.execute(f"INSERT INTO {tabla} ({','.join(columnas)}) VALUES ({','.join('?' * len(columnas))})", list(valores.values()))


def crear(ruta: Path | None = None, hoy: date | None = None) -> Path:
    ruta = ruta or config.BACKEND / "demo_erp.db"
    hoy = hoy or date.today()
    if ruta.exists():
        ruta.unlink()
    rnd = random.Random(42)
    con = sqlite3.connect(ruta)
    con.executescript(ESQUEMA)

    for i, nombre in ((1, "Centro"), (2, "Norte")):
        _insertar(con, "sucursales", id=i, nombre=nombre, tipo="sucursal")
    for i, nombre, suc in ((1, "Laura", 1), (2, "Diego", 2), (3, "Sofía", 1)):
        _insertar(con, "vendedores", id=i, nombre=nombre, sucursal_id=suc, activo=1)
    for i, nombre, pago, entrega, minimo in ((1, "Lácteos del Este", 15, 2, 20000), (2, "Alimentos Unidos", 21, 5, 40000),
                                             (3, "Molinos del Sur", 30, 7, 30000), (4, "Bebidas Río", 21, 3, 25000),
                                             (5, "Higiene Total", 30, 6, 15000)):
        _insertar(con, "proveedores", id=i, nombre=nombre, plazo_pago_dias=pago, plazo_entrega_dias=entrega, pedido_minimo=minimo)
    for i, (desc, cat, prov, costo, margen, bulto, per) in enumerate(PRODUCTOS, start=1):
        precio = round(costo / (1 - margen), 2)
        _insertar(con, "productos", id=i, codigo=f"P{i:03d}", descripcion=desc, categoria=cat, proveedor_id=prov,
                  costo=costo, precio=precio, unidades_bulto=bulto, perecedero=per, unidad="u", tasa_iva=0.22, estado="activo")
        for suc in (1, 2):
            _insertar(con, "stock", producto_id=i, sucursal_id=suc, cantidad=rnd.choice([0, 5, 20, 60, 150, 400]))

    for i, (nombre, tipo, zona, vend) in enumerate(CLIENTES, start=1):
        plazo = rnd.choice([0, 15, 30, 30])
        alta = hoy - timedelta(days=rnd.randint(60, 1500))
        _insertar(con, "clientes", id=i, razon_social=nombre, tipo=tipo, zona=zona, vendedor_id=vend, condicion_pago_dias=plazo,
                  limite_credito=plazo * 15000, fecha_alta=alta.isoformat(), estado="activo", canal="preventa")

    # Ventas de los últimos 365 días; el cliente 9 deja de comprar hace 70 días (churn).
    venta_id, cxc_id = 0, 0
    for dia in range(365, 0, -1):
        fecha = hoy - timedelta(days=dia)
        if fecha.weekday() == 6:
            continue
        for cli in range(1, len(CLIENTES) + 1):
            if rnd.random() > 0.35 or (cli == 9 and dia < 70):
                continue
            vend = CLIENTES[cli - 1][3]
            suc = 1 if CLIENTES[cli - 1][2] == "Centro" else 2
            venta_id += 1
            anulada = 1 if rnd.random() < 0.01 else 0
            _insertar(con, "ventas", id=venta_id, tipo="factura", fecha=fecha.isoformat(), cliente_id=cli, vendedor_id=vend,
                      sucursal_id=suc, anulada=anulada, canal="preventa")
            total = 0.0
            for prod in rnd.sample(range(1, len(PRODUCTOS) + 1), rnd.randint(3, 7)):
                costo = PRODUCTOS[prod - 1][3] * (1 + 0.004 * (365 - dia) / 30)  # inflación
                margen = PRODUCTOS[prod - 1][4]
                precio = costo / (1 - margen) * rnd.uniform(0.95, 1.0)
                cant = rnd.randint(2, 24)
                total += cant * precio
                _insertar(con, "ventas_lineas", venta_id=venta_id, producto_id=prod, cantidad=cant, precio_unitario=round(precio, 2),
                          costo_unitario=round(costo, 2), impuestos=round(cant * precio * 0.22, 2))
            plazo = con.execute("SELECT condicion_pago_dias FROM clientes WHERE id=?", (cli,)).fetchone()[0]
            if plazo and not anulada:
                cxc_id += 1
                venc = fecha + timedelta(days=plazo)
                atraso = rnd.choice([0, 0, 3, 7, 12, 20]) + (25 if cli in (5, 8) else 0)
                cobro = venc + timedelta(days=atraso)
                pendiente = cobro > hoy
                _insertar(con, "cxc", id=cxc_id, tipo="factura", cliente_id=cli, vendedor_id=vend, fecha_emision=fecha.isoformat(),
                          fecha_vencimiento=venc.isoformat(), fecha_cobro=None if pendiente else cobro.isoformat(),
                          importe=round(total, 2), saldo=round(total, 2) if pendiente else 0.0)
    con.commit()
    con.close()
    return ruta


if __name__ == "__main__":
    print(f"Base de demostración creada en {crear()}")
