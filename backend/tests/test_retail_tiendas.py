"""Retail · Fase 2, sección 5.4: conectores de Tiendanube y Mercado Libre (plataformas falsas en memoria, solo GET)."""
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.retail import api_ingesta, db, motor, plataformas_online
from app.retail.semilla import CLAVE_DEMO

TOKEN = "token-de-prueba"


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


class Falsa:
    def __init__(self, rutas):
        self.rutas, self.pedidos = rutas, []

    def __call__(self, url, headers):
        assert TOKEN in (headers.get("Authentication", "") + headers.get("Authorization", ""))
        self.pedidos.append(url)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        for patron, respuesta in self.rutas.items():
            if u.path.endswith(patron):
                return respuesta(q) if callable(respuesta) else respuesta
        raise AssertionError(f"ruta no simulada: {url}")


@pytest.fixture
def base(retail_demo, monkeypatch, tmp_path):
    from app.retail import cifrado
    monkeypatch.setattr(cifrado, "ARCHIVO", tmp_path / "clave")
    monkeypatch.setattr(api_ingesta, "recalcular_en_segundo_plano", lambda org, desde=None: None)
    prods = _q("SELECT codigo_interno, ean FROM productos WHERE ean IS NOT NULL ORDER BY id LIMIT 2")
    centro = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Centro'")[0]["id"]
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": "dueno@norte.demo", "clave": CLAVE_DEMO}).status_code == 200
    return c, prods, centro, monkeypatch


def _sync(pid):
    ctx = motor.contexto_sistema(1)
    with db.transaccion(ctx) as conn:
        return plataformas_online.sincronizar(conn, ctx, pid)


def test_tiendanube(base):
    c, prods, centro, mp = base
    pedidos = [
        {"id": 101, "created_at": "2026-09-23T15:00:00+0000", "status": "open", "payment_status": "paid", "shipping_status": "shipped",
         "shipped_at": "2026-09-23T20:00:00+0000", "total": "3000.00", "shipping_cost_owner": "0.00",
         "products": [{"variant_id": 1, "sku": prods[0]["codigo_interno"], "name": "A", "quantity": 2, "price": "1500.00"}]},
        {"id": 102, "created_at": "2026-09-24T10:00:00+0000", "status": "open", "payment_status": "paid", "shipping_status": "unpacked",
         "total": "900.00", "shipping_cost_owner": "500.00", "products": [{"variant_id": 2, "sku": None, "name": "B", "quantity": 1, "price": "900.00"}]},
        {"id": 103, "created_at": "2026-09-24T11:00:00+0000", "status": "cancelled", "payment_status": "paid", "total": "100.00", "products": []},
        {"id": 104, "created_at": "2026-09-24T12:00:00+0000", "status": "open", "payment_status": "pending", "total": "100.00", "products": []},
    ]
    falsa = Falsa({"/store": {"id": 555, "name": {"es": "Almacén del Norte"}},
                   "/products": lambda q: [] if q.get("page") != "1" else [
                       {"id": 10, "name": {"es": "Prod A"}, "published": True, "variants": [{"id": 1, "sku": prods[0]["codigo_interno"], "stock": 40, "price": "1500.00"}]},
                       {"id": 11, "name": {"es": "Prod B"}, "published": True, "variants": [{"id": 2, "sku": None, "barcode": prods[1]["ean"], "stock": 3, "price": "900.00"}]},
                       {"id": 12, "name": {"es": "Algo que no vendemos"}, "published": True, "variants": [{"id": 3, "sku": "ZZZ", "stock": 1, "price": "1"}]}],
                   "/orders": lambda q: pedidos if q.get("page") == "1" else []})
    mp.setattr(plataformas_online, "_http", falsa)
    probar = c.post("/retail/api/conexiones/tienda/probar", json={"tipo": "tiendanube", "token": TOKEN, "store_id": "555"})
    assert probar.status_code == 200 and probar.json()["nombre"] == "Almacén del Norte"
    r = c.post("/retail/api/conexiones/tienda", json={"tipo": "tiendanube", "token": TOKEN, "store_id": "555", "ubicacion_despacho_id": centro, "comision_pct": 0.02})
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert TOKEN not in str(c.get("/retail/api/conexiones").json())
    res = _sync(pid)
    assert res["pedidos_nuevos"] == 3 and res["publicaciones"] == 3 and res["publicaciones_sin_emparejar"] == 1
    t = {x["numero_externo"]: x for x in _q("SELECT t.numero_externo, t.estado, t.total, t.ubicacion_id, po.estado pedido, cc.comision, cc.envio "
                                            "FROM tickets t JOIN pedidos_online po ON po.ticket_id = t.id JOIN costos_canal cc ON cc.ticket_id = t.id WHERE t.plataforma_id=%s", (pid,))}
    assert t[f"{pid}-101"]["pedido"] == "despachado" and t[f"{pid}-101"]["comision"] == Decimal("60.00")
    assert t[f"{pid}-102"]["pedido"] == "pendiente" and t[f"{pid}-102"]["envio"] == Decimal("500.00")
    assert t[f"{pid}-103"]["estado"] == "anulado" and all(x["ubicacion_id"] == centro for x in t.values())
    # El pendiente reserva stock en la sucursal que despacha (el producto B se emparejó por código de barras).
    b = _q("SELECT id FROM productos WHERE ean=%s", (prods[1]["ean"],))[0]["id"]
    assert _q("SELECT reservado FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (b, centro))[0]["reservado"] == Decimal("1")
    # Resincronizar: sin duplicados; el pedido pendiente ahora está despachado y libera la reserva.
    pedidos[1] |= {"shipping_status": "shipped", "shipped_at": "2026-09-24T18:00:00+0000"}
    res2 = _sync(pid)
    assert res2["pedidos_nuevos"] == 0 and res2["pedidos_actualizados"] == 1
    assert _q("SELECT reservado FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (b, centro))[0]["reservado"] == 0


def test_mercadolibre(base):
    c, prods, centro, mp = base
    falsa = Falsa({
        "/users/me": {"id": 77, "nickname": "ALMACENNORTE"},
        "/users/77/items/search": {"results": ["MLA1", "MLA2"], "paging": {"total": 2}},
        "/items": [{"code": 200, "body": {"id": "MLA1", "title": "Publicación A", "price": 1600, "available_quantity": 12, "status": "active",
                                           "seller_custom_field": prods[0]["codigo_interno"]}},
                   {"code": 200, "body": {"id": "MLA2", "title": "Publicación B", "price": 950, "available_quantity": 999, "status": "active",
                                           "attributes": [{"id": "GTIN", "value_name": prods[1]["ean"]}]}}],
        "/orders/search": {"paging": {"total": 1}, "results": [
            {"id": 9001, "date_created": "2026-09-24T09:00:00.000-03:00", "status": "paid", "total_amount": 3200, "shipping": {"id": 55},
             "order_items": [{"item": {"id": "MLA1", "seller_sku": prods[0]["codigo_interno"], "title": "Publicación A"}, "quantity": 2, "unit_price": 1600,
                              "sale_fee": 208}]}]},
        "/shipments/55/costs": {"senders": [{"cost": 3500}]},
        "/shipments/55": {"status": "ready_to_ship", "status_history": {}},
    })
    mp.setattr(plataformas_online, "_http", falsa)
    r = c.post("/retail/api/conexiones/tienda", json={"tipo": "mercadolibre", "token": TOKEN, "ubicacion_despacho_id": centro})
    assert r.status_code == 200, r.text
    res = _sync(r.json()["id"])
    assert res["pedidos_nuevos"] == 1 and res["publicaciones_sin_emparejar"] == 0
    t = _q("SELECT cc.comision, cc.envio, po.estado FROM tickets t JOIN costos_canal cc ON cc.ticket_id = t.id JOIN pedidos_online po ON po.ticket_id = t.id "
           "WHERE t.origen='mercadolibre' AND t.numero_externo LIKE %s", (f"{r.json()['id']}-%",))[0]
    assert t["comision"] == Decimal("416.00") and t["envio"] == Decimal("3500.00") and t["estado"] == "pendiente"
    # La publicación B muestra 999 publicados: es sobreventa contra el stock de Salta Centro.
    sob = c.get("/retail/api/canales/stock").json()["sobreventa"]
    assert any(s["plataforma"] == "Mercado Libre" and Decimal(s["stock_publicado"]) == 999 for s in sob)


def test_token_rechazado(base):
    c, prods, centro, mp = base

    def rechaza(url, headers):
        raise plataformas_online.ErrorPlataforma("La plataforma rechazó el acceso: revisá o renová el token.")
    mp.setattr(plataformas_online, "_http", rechaza)
    r = c.post("/retail/api/conexiones/tienda/probar", json={"tipo": "mercadolibre", "token": "malo"})
    assert r.status_code == 400 and "rechazó" in r.json()["detail"]
    assert c.post("/retail/api/conexiones/tienda", json={"tipo": "vtex", "token": "x", "ubicacion_despacho_id": centro}).status_code == 400
