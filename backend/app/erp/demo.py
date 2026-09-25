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


CANAL = {"almacén": "Preventa", "kiosco": "Preventa", "autoservicio": "Institucional", "restaurante": "Televenta"}


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
                      sucursal_id=suc, anulada=anulada, canal=CANAL[CLIENTES[cli - 1][1]])
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
    _completar(con, hoy)
    con.commit()
    con.close()
    return ruta


def _completar(con, hoy: date) -> None:
    """Datos de ejemplo para el resto del modelo (pedidos, compras, caja, gastos...).

    Usa su propio generador aleatorio para no cambiar los datos de ventas de arriba.
    """
    rnd = random.Random(7)
    q = lambda sql, *a: con.execute(sql, a).fetchall()  # noqa: E731
    dia = lambda n: (hoy - timedelta(days=n)).isoformat()  # noqa: E731

    # Pedidos y presupuestos de los últimos 120 días (uno por venta), con algunas entregas tarde o incompletas
    for vid, fecha, cli, vend, suc in q("SELECT id, fecha, cliente_id, vendedor_id, sucursal_id FROM ventas WHERE anulada = 0 AND fecha >= ?", dia(120)):
        f = date.fromisoformat(fecha)
        tarde = rnd.random() < 0.08
        _insertar(con, "pedidos", id=vid, numero=f"PV-{vid}", cliente_id=cli, vendedor_id=vend, sucursal_id=suc,
                  fecha_pedido=(f - timedelta(days=1)).isoformat(), fecha_entrega_prometida=fecha,
                  fecha_entrega=(f + timedelta(days=2 if tarde else 0)).isoformat(), estado="entregado")
        for prod, cant in q("SELECT producto_id, cantidad FROM ventas_lineas WHERE venta_id = ?", vid):
            falta = cant if rnd.random() < 0.04 else 0
            _insertar(con, "pedidos_lineas", pedido_id=vid, producto_id=prod, cantidad_pedida=cant + falta, cantidad_entregada=cant)
        _insertar(con, "presupuestos", id=vid, numero=f"PR-{vid}", cliente_id=cli, vendedor_id=vend, fecha=(f - timedelta(days=2)).isoformat(),
                  importe=q("SELECT SUM(cantidad * precio_unitario) FROM ventas_lineas WHERE venta_id = ?", vid)[0][0], estado="aceptado", venta_id=vid)
    for i in range(40):
        _insertar(con, "presupuestos", id=900000 + i, numero=f"PR-X{i}", cliente_id=rnd.randint(1, 12), vendedor_id=rnd.randint(1, 3),
                  fecha=dia(rnd.randint(1, 120)), importe=round(rnd.uniform(3000, 15000), 2), estado=rnd.choice(["enviado", "rechazado"]))

    # Devoluciones (~2 % de las ventas)
    for i, (vid, fecha, cli) in enumerate(q("SELECT id, fecha, cliente_id FROM ventas WHERE anulada = 0 AND fecha >= ?", dia(365)), start=1):
        if rnd.random() < 0.02:
            prod, precio = q("SELECT producto_id, precio_unitario FROM ventas_lineas WHERE venta_id = ? LIMIT 1", vid)[0]
            cant = rnd.randint(1, 3)
            _insertar(con, "devoluciones", id=i, fecha=fecha, cliente_id=cli, venta_id=vid, producto_id=prod, cantidad=cant,
                      importe=round(cant * precio, 2), motivo=rnd.choice(["vencido", "roto", "error de pedido"]))

    # Objetivos por vendedor: el promedio mensual de los últimos 3 meses + 5 %
    mes = hoy.isoformat()[:7]
    for vend, venta in q("""SELECT v.vendedor_id, SUM(l.cantidad * l.precio_unitario) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
                            WHERE v.anulada = 0 AND v.fecha >= ? GROUP BY v.vendedor_id""", dia(90)):
        _insertar(con, "objetivos_vendedores", vendedor_id=vend, mes=mes, objetivo_venta=round(venta / 3 * 1.05, -3))

    # Lotes con vencimiento para los perecederos (uno ya vencido) y mercadería en tránsito
    for n, (prod, suc) in enumerate(q("SELECT s.producto_id, s.sucursal_id FROM stock s JOIN productos p ON p.id = s.producto_id "
                                      "WHERE p.perecedero = 1 AND s.cantidad > 0 ORDER BY s.producto_id, s.sucursal_id")):
        vence = hoy + timedelta(days=-2 if n == 0 else rnd.randint(4, 45))
        con.execute("UPDATE stock SET lote = ?, fecha_vencimiento = ? WHERE producto_id = ? AND sucursal_id = ?",
                    (f"L{prod:02d}{suc}{vence:%m%d}", vence.isoformat(), prod, suc))
    _insertar(con, "stock", producto_id=9, sucursal_id=1, cantidad=0, en_transito=120)

    # Compras semanales a cada proveedor (120 días), con recepción, factura, pago e historial de costos
    proveedores = q("SELECT id, plazo_pago_dias, plazo_entrega_dias FROM proveedores")
    compra = cxp = pago = mov = 0
    for dias_atras in range(119, 0, -7):
        for prov, plazo_pago, plazo_entrega in proveedores:
            compra += 1
            fecha = hoy - timedelta(days=dias_atras)
            prometida = fecha + timedelta(days=plazo_entrega)
            atraso = rnd.choice([0, 0, 0, 1, 3]) if prov != 2 else rnd.choice([0, 3, 5])
            recibida = prometida + timedelta(days=atraso)
            llego = recibida <= hoy
            _insertar(con, "compras", id=compra, numero=f"OC-{compra}", proveedor_id=prov, sucursal_id=1, fecha=fecha.isoformat(),
                      fecha_prometida=prometida.isoformat(), fecha_recepcion=recibida.isoformat() if llego else None,
                      estado="recibida" if llego else "confirmada")
            total = 0.0
            for prod, costo, bulto in q("SELECT id, costo, unidades_bulto FROM productos WHERE proveedor_id = ?", prov):
                pedida = bulto * rnd.randint(3, 10)
                recib = (pedida if rnd.random() > 0.1 else pedida - bulto) if llego else 0
                inflado = round(costo * (1 + 0.004 * (365 - dias_atras) / 30), 2)
                _insertar(con, "compras_lineas", compra_id=compra, producto_id=prod, cantidad_pedida=pedida, cantidad_recibida=recib,
                          precio_pactado=inflado, precio_facturado=inflado)
                total += recib * inflado
                if llego:
                    mov += 1
                    _insertar(con, "movimientos_stock", id=mov, fecha=recibida.isoformat(), producto_id=prod, sucursal_id=1, tipo="compra",
                              cantidad=recib, costo_unitario=inflado, comprobante=f"OC-{compra}")
                if dias_atras % 28 == 7:
                    _insertar(con, "costos_historial", producto_id=prod, fecha=fecha.isoformat(), costo=inflado)
            if llego and total:
                cxp += 1
                vence = recibida + timedelta(days=plazo_pago)
                pagada = vence + timedelta(days=rnd.choice([0, 0, 2, 5]))
                _insertar(con, "cxp", id=cxp, tipo="factura", numero=f"FP-{cxp}", proveedor_id=prov, fecha_emision=recibida.isoformat(),
                          fecha_vencimiento=vence.isoformat(), fecha_pago=pagada.isoformat() if pagada <= hoy else None,
                          importe=round(total, 2), saldo=0.0 if pagada <= hoy else round(total, 2))
                if pagada <= hoy:
                    pago += 1
                    _insertar(con, "pagos", id=pago, fecha=pagada.isoformat(), proveedor_id=prov, medio="transferencia",
                              importe=round(total, 2), cxp_id=cxp)

    # Mermas: roturas y vencimientos de perecederos
    for n in range(24):
        prod = rnd.choice([1, 2, 3, 11, 14])
        mov += 1
        _insertar(con, "movimientos_stock", id=mov, fecha=dia(rnd.randint(1, 119)), producto_id=prod, sucursal_id=rnd.choice([1, 2]),
                  tipo="merma", motivo=rnd.choice(["rotura", "vencimiento", "vencimiento"]), cantidad=-rnd.randint(1, 6))

    # Conteos físicos
    for n in range(30):
        prod, suc = rnd.randint(1, 15), rnd.choice([1, 2])
        sistema = q("SELECT COALESCE(SUM(cantidad), 0) FROM stock WHERE producto_id = ? AND sucursal_id = ?", prod, suc)[0][0]
        _insertar(con, "conteos", id=n + 1, fecha=dia(rnd.randint(1, 60)), producto_id=prod, sucursal_id=suc, cantidad_sistema=sistema,
                  cantidad_contada=sistema if rnd.random() < 0.85 else max(0, sistema - rnd.randint(1, 4)), usuario="Depósito")

    # Cobranzas de las facturas cobradas y cheques
    for n, (cxc_id, cli, fecha, importe) in enumerate(q("SELECT id, cliente_id, fecha_cobro, importe FROM cxc WHERE fecha_cobro IS NOT NULL"), start=1):
        medio = rnd.choice(["transferencia", "transferencia", "efectivo", "cheque"])
        _insertar(con, "cobranzas", id=n, fecha=fecha, cliente_id=cli, medio=medio, importe=importe, cxc_id=cxc_id)
    for n in range(8):
        _insertar(con, "cheques", id=n + 1, tipo="recibido", numero=f"{rnd.randint(1000000, 9999999)}", banco=rnd.choice(["BROU", "Itaú", "Santander"]),
                  cliente_id=rnd.randint(1, 12), fecha_emision=dia(rnd.randint(1, 40)), fecha_cobro=(hoy + timedelta(days=rnd.randint(5, 60))).isoformat(),
                  importe=round(rnd.uniform(8000, 40000), 2), estado="rechazado" if n == 0 else "cartera")

    # Bancos, gastos, impuestos, préstamo, cotizaciones y presupuesto
    _insertar(con, "cuentas_bancarias", id=1, nombre="BROU cuenta corriente", tipo="banco", moneda="UYU", saldo=1_850_000, fecha_saldo=hoy.isoformat())
    _insertar(con, "cuentas_bancarias", id=2, nombre="Caja Centro", tipo="caja", moneda="UYU", saldo=145_000, fecha_saldo=hoy.isoformat())
    gastos_mes = {"personal": 70_000, "alquiler": 18_000, "energia": 7_000, "logistica": 12_000, "sistemas": 3_000, "otros": 5_000}
    n = 0
    for m in range(12, 0, -1):
        inicio = (hoy.replace(day=1) - timedelta(days=30 * m)).replace(day=1)
        for categoria, importe in gastos_mes.items():
            n += 1
            _insertar(con, "gastos", id=n, fecha=(inicio + timedelta(days=4)).isoformat(), sucursal_id=1, cuenta=categoria.capitalize(),
                      categoria=categoria, importe=round(importe * rnd.uniform(0.95, 1.08), 2))
        _insertar(con, "impuestos", id=m, impuesto="IVA", periodo=inicio.isoformat()[:7], vencimiento=(inicio + timedelta(days=48)).isoformat(),
                  importe=round(rnd.uniform(28_000, 36_000), 2), estado="pagado" if m > 1 else "pendiente")
        _insertar(con, "presupuesto", mes=inicio.isoformat()[:7], concepto="venta", importe=750_000)
    _insertar(con, "prestamos", id=1, entidad="BROU", moneda="UYU", capital=1_200_000, tasa_anual=0.14, fecha_inicio=dia(300), cuotas=24,
              cuota_importe=57_600, saldo=780_000, proximo_vencimiento=(hoy + timedelta(days=12)).isoformat())
    for d in range(30):
        _insertar(con, "tipos_cambio", fecha=dia(d), moneda="USD", cotizacion=round(40 + rnd.uniform(-0.6, 0.6), 2))


if __name__ == "__main__":
    print(f"Base de demostración creada en {crear()}")
