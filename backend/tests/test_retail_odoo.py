"""Retail · parte 4: conexión con Odoo Punto de Venta (Odoo falso en memoria, solo lectura)."""
import copy
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from test_integraciones import _filtrar

from app.integraciones import odoo
from app.main import app
from app.retail import api_ingesta, db, motor, odoo_pos
from app.retail.semilla import CLAVE_DEMO

M2O = lambda i, n="": [i, n] if i else False  # noqa: E731
CLAVE = "clave-de-prueba-odoo"


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def _datos(ean_existente):
    return {
        "stock.warehouse": [{"id": 1, "name": "Salta Centro", "code": "SC", "lot_stock_id": M2O(10)},
                            {"id": 2, "name": "Galpón Tucumán", "code": "GT", "lot_stock_id": M2O(20)}],
        "stock.location": [{"id": 10, "warehouse_id": M2O(1, "Salta Centro")}, {"id": 20, "warehouse_id": M2O(2)}],
        "pos.config": [{"id": 60, "name": "Caja 1", "picking_type_id": M2O(61)}, {"id": 70, "name": "Caja Tucumán", "picking_type_id": M2O(71)}],
        "stock.picking.type": [{"id": 61, "warehouse_id": M2O(1)}, {"id": 71, "warehouse_id": M2O(2)}],
        "product.product": [
            {"id": 500, "name": "Producto ya cargado", "barcode": ean_existente, "default_code": False, "lst_price": 100.0, "sale_ok": True, "uom_id": M2O(1, "Unidades")},
            {"id": 501, "name": "Alfajor de Odoo", "barcode": False, "default_code": "ALF-ODOO", "lst_price": 900.0, "sale_ok": True, "uom_id": M2O(1, "Unidades")},
        ],
        "pos.order": [
            {"id": 1, "name": "Caja 1/0001", "date_order": "2026-09-22 13:05:00", "config_id": M2O(60, "Caja 1"), "user_id": M2O(9, "Ana"), "amount_total": 2800.0, "state": "paid"},
            {"id": 2, "name": "Caja 1/0002", "date_order": "2026-09-22 14:10:00", "config_id": M2O(60, "Caja 1"), "user_id": M2O(9, "Ana"), "amount_total": 900.0, "state": "done"},
            {"id": 3, "name": "Caja 1/0003", "date_order": "2026-09-22 15:00:00", "config_id": M2O(60, "Caja 1"), "user_id": M2O(9, "Ana"), "amount_total": 0.0, "state": "cancel"},
            {"id": 4, "name": "Tucumán/0001", "date_order": "2026-09-22 15:00:00", "config_id": M2O(70, "Caja Tucumán"), "user_id": M2O(9), "amount_total": 50.0, "state": "paid"},
        ],
        "pos.order.line": [
            {"id": 11, "order_id": M2O(1), "product_id": M2O(500), "qty": 2.0, "price_unit": 1000.0, "discount": 5.0, "price_subtotal_incl": 1900.0, "total_cost": 1200.0},
            {"id": 12, "order_id": M2O(1), "product_id": M2O(501), "qty": 1.0, "price_unit": 900.0, "discount": 0.0, "price_subtotal_incl": 900.0, "total_cost": 500.0},
            {"id": 13, "order_id": M2O(2), "product_id": M2O(501), "qty": 1.0, "price_unit": 900.0, "discount": 0.0, "price_subtotal_incl": 900.0, "total_cost": 500.0},
        ],
        "pos.payment": [{"id": 1, "pos_order_id": M2O(1), "amount": 2000.0, "payment_method_id": M2O(1, "Efectivo")},
                        {"id": 2, "pos_order_id": M2O(1), "amount": 800.0, "payment_method_id": M2O(2, "Tarjeta de Débito")},
                        {"id": 3, "pos_order_id": M2O(2), "amount": 900.0, "payment_method_id": M2O(3, "Mercado Pago QR")}],
        "stock.quant": [{"id": 1, "product_id": M2O(501), "quantity": 7.0, "location_id": M2O(10)},
                        {"id": 2, "product_id": M2O(501), "quantity": 3.0, "location_id": M2O(10)},
                        {"id": 3, "product_id": M2O(501), "quantity": 50.0, "location_id": M2O(20)}],
    }


class OdooPos:
    def __init__(self, datos):
        self.datos, self.metodos = datos, []

    def __call__(self, url, payload):
        p = payload["params"]
        if p["service"] == "common":
            if p["method"] == "version":
                return {"result": {"server_version": "17.0"}}
            return {"result": 6 if p["args"][2] == CLAVE else False}
        _, _, _, modelo, metodo, args, kwargs = p["args"]
        self.metodos.append(metodo)
        filas = self.datos.get(modelo, [])
        if metodo == "check_access_rights":
            return {"result": True}
        if metodo == "fields_get":
            return {"result": {c: {"type": "char"} for f in filas for c in f}}
        if metodo == "search_count":
            return {"result": len(_filtrar(filas, args[0]))}
        if metodo == "read":
            return {"result": [f for f in filas if f["id"] in args[0]]}
        if metodo == "search_read":
            encontrados = _filtrar(filas, args[0])
            ini = kwargs.get("offset", 0)
            return {"result": encontrados[ini:ini + kwargs.get("limit", 10**6)]}
        raise AssertionError(metodo)


@pytest.fixture
def odoo_falso(retail_demo, monkeypatch, tmp_path):
    from app.retail import cifrado
    monkeypatch.setattr(cifrado, "ARCHIVO", tmp_path / "clave")
    monkeypatch.setattr(api_ingesta, "recalcular_en_segundo_plano", lambda org, desde=None: None)
    ean = _q("SELECT ean FROM productos WHERE ean IS NOT NULL ORDER BY id LIMIT 1")[0]["ean"]
    falso = OdooPos(copy.deepcopy(_datos(ean)))
    monkeypatch.setattr(odoo, "_http", falso)
    return falso


def cliente():
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": "dueno@norte.demo", "clave": CLAVE_DEMO}).status_code == 200
    return c


CRED = {"url": "https://odoo.test", "base": "comercio", "usuario": "integracion@comercio.com", "api_key": CLAVE}


def _conectar(c):
    det = c.post("/retail/api/conexiones/odoo/probar", json=CRED)
    assert det.status_code == 200, det.text
    det = det.json()
    almacenes = {a["id"]: a["ubicacion_sugerida"] for a in det["almacenes"]}
    r = c.post("/retail/api/conexiones/odoo", json={**CRED, "almacenes": almacenes})
    assert r.status_code == 200, r.text
    return det, r.json()["id"]


def _sincronizar(pid):
    ctx = motor.contexto_sistema(1)
    with db.transaccion(ctx) as conn:
        return odoo_pos.sincronizar(conn, ctx, pid)


def test_deteccion_y_credenciales_cifradas(odoo_falso):
    c = cliente()
    det, pid = _conectar(c)
    centro = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Centro'")[0]["id"]
    assert {a["id"]: a["ubicacion_sugerida"] for a in det["almacenes"]} == {1: centro, 2: None}
    assert [x["almacen_id"] for x in det["cajas"]] == [1, 2] and det["conteos"]["tickets"] == 3
    guardada = _q("SELECT config, credenciales_cifradas FROM plataformas WHERE id=%s", (pid,))[0]
    assert CLAVE.encode() not in bytes(guardada["credenciales_cifradas"]) and "api_key" not in guardada["config"]
    lista = c.get("/retail/api/conexiones").json()
    assert lista[0]["tiene_clave"] and CLAVE not in str(lista)
    assert _q("SELECT codigo_externo FROM ubicaciones WHERE id=%s", (centro,))[0]["codigo_externo"] == "odoo:almacen:1"
    # Clave equivocada: se avisa y no se guarda nada.
    malo = c.post("/retail/api/conexiones/odoo/probar", json={**CRED, "api_key": "otra"})
    assert malo.status_code == 400 and "rechazó" in malo.json()["detail"]


def test_sincroniza_tickets_pagos_productos_y_stock_sin_duplicar(odoo_falso):
    c = cliente()
    _, pid = _conectar(c)
    centro = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Centro'")[0]["id"]
    r = _sincronizar(pid)
    assert r["tickets_nuevos"] == 2 and r["lineas"] == 3 and r["productos_nuevos"] == 1 and r["cajas_sin_sucursal"] == 1
    t = _q("SELECT id, total, punto_venta, cajero, ubicacion_id, fecha_hora FROM tickets WHERE origen='odoo' ORDER BY numero_externo")
    assert [x["total"] for x in t] == [Decimal("2800.00"), Decimal("900.00")] and t[0]["punto_venta"] == "Caja 1" and t[0]["ubicacion_id"] == centro
    linea = _q("SELECT precio_lista, precio_cobrado, descuento, costo_unitario FROM tickets_lineas WHERE ticket_id=%s ORDER BY precio_lista DESC", (t[0]["id"],))[0]
    assert (linea["precio_lista"], linea["precio_cobrado"], linea["descuento"], linea["costo_unitario"]) == \
        (Decimal("1000.00"), Decimal("950.00"), Decimal("100.00"), Decimal("600.0000"))
    medios = {p["medio"]: p["monto"] for p in _q("SELECT medio, monto FROM pagos WHERE ticket_id IN (%s, %s)", (t[0]["id"], t[1]["id"]))}
    assert medios == {"efectivo": Decimal("2000.00"), "debito": Decimal("800.00"), "qr": Decimal("900.00")}
    alfajor = _q("SELECT id FROM productos WHERE codigo_interno='ALF-ODOO'")[0]["id"]
    assert _q("SELECT cantidad FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (alfajor, centro))[0]["cantidad"] == Decimal("10")
    assert set(odoo_falso.metodos) <= odoo._METODOS_LECTURA            # nunca escribe en Odoo

    # Resincronizar no duplica; un ticket nuevo sí entra.
    r2 = _sincronizar(pid)
    assert r2["tickets_nuevos"] == 0 and r2["tickets_repetidos"] == 2 and r2["productos_nuevos"] == 0
    odoo_falso.datos["pos.order"].append({"id": 9, "name": "Caja 1/0009", "date_order": "2026-09-23 12:00:00", "config_id": M2O(60), "user_id": False,
                                          "amount_total": 900.0, "state": "paid"})
    odoo_falso.datos["pos.order.line"].append({"id": 19, "order_id": M2O(9), "product_id": M2O(501), "qty": 1.0, "price_unit": 900.0,
                                               "price_subtotal_incl": 900.0})
    r3 = _sincronizar(pid)
    assert r3["tickets_nuevos"] == 1 and _q("SELECT count(*) n FROM tickets WHERE origen='odoo'")[0]["n"] == 3
    estado = c.get("/retail/api/conexiones").json()[0]
    assert estado["estado_sincronizacion"] == "ok" and estado["sincronizado_hasta"].startswith("2026-09-23")


def test_error_de_odoo_queda_en_la_conexion(odoo_falso, monkeypatch):
    c = cliente()
    _, pid = _conectar(c)

    def caido(url, payload):
        raise OSError("Connection refused")
    monkeypatch.setattr(odoo, "_http", caido)
    assert odoo_pos.sincronizar_todas(1) is None
    estado = c.get("/retail/api/conexiones").json()[0]
    assert estado["estado_sincronizacion"] == "error" and "conectar" in estado["error_sincronizacion"]
    assert c.delete(f"/retail/api/conexiones/{pid}").status_code == 200
    assert _q("SELECT credenciales_cifradas FROM plataformas WHERE id=%s", (pid,))[0]["credenciales_cifradas"] is None


def test_usa_el_odoo_del_panel_erp_y_crea_sucursales(odoo_falso, monkeypatch):
    """La administración entra a una empresa sin sucursales y usa el Odoo que ya está conectado en el Panel ERP."""
    from app.integraciones import gestor
    from app.retail import cuentas
    monkeypatch.setattr(gestor, "config_odoo", lambda con_clave=False: {"url": "https://odoo.test", "db": "comercio",
                                                                        "usuario": "integracion@comercio.com", "api_key": CLAVE})
    with db.transaccion(superadmin=True) as conn:
        cuentas.administrador(conn, "yo@ejemplo.com", "Yo", "Clave-segura-2026")
        org = cuentas.empresa_con_dueno(conn, "Pulpo Azul", None, "dueno@pulpo.test", "Dueño", "Clave-segura-2026")
    # El dueño no puede usar la conexión de toda la instalación.
    d = TestClient(app)
    d.post("/retail/api/sesion", json={"email": "dueno@pulpo.test", "clave": "Clave-segura-2026"})
    assert d.get("/retail/api/conexiones/odoo/panel").json()["disponible"] is False
    assert d.post("/retail/api/conexiones/odoo/desde-panel").status_code == 403
    a = TestClient(app)
    a.post("/retail/api/sesion", json={"email": "yo@ejemplo.com", "clave": "Clave-segura-2026"})
    a.post("/retail/api/plataforma/entrar", json={"org_id": org})
    assert a.get("/retail/api/conexiones/odoo/panel").json()["disponible"]
    r = a.post("/retail/api/conexiones/odoo/desde-panel")
    assert r.status_code == 200, r.text
    assert sorted(r.json()["sucursales_creadas"]) == ["Galpón Tucumán", "Salta Centro"]
    with db.transaccion(superadmin=True) as conn:
        ubic = {u["nombre"]: u for u in db.filas(conn, "SELECT nombre, tipo, codigo_externo FROM ubicaciones WHERE org_id=%s", (org,))}
        plat = db.filas(conn, "SELECT config FROM plataformas WHERE org_id=%s AND tipo='odoo'", (org,))
    assert ubic["Salta Centro"]["codigo_externo"] == "odoo:almacen:1" and ubic["Salta Centro"]["tipo"] == "ambos"
    assert len(plat) == 1 and set(plat[0]["config"]["almacenes"]) == {"1", "2"}
    assert CLAVE not in str(a.get("/retail/api/conexiones").json())
