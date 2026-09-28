"""Retail · Fase 3: WooCommerce, Shopify y VTEX (solo lectura), pedidos de delivery por reporte y stock publicado con aprobación humana."""
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.retail import api_ingesta, db, demo, motor, plataformas_online, stock_publicado
from app.retail.semilla import CLAVE_DEMO


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


class Falsa:
    """Plataforma en memoria. Los GET van por __call__; las escrituras quedan anotadas en .enviados."""
    def __init__(self, rutas):
        self.rutas, self.pedidos, self.enviados = rutas, [], []

    def __call__(self, url, headers):
        self.pedidos.append(url)
        u = urlparse(url)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        for patron, respuesta in self.rutas.items():
            if u.path.endswith(patron):
                return respuesta(q) if callable(respuesta) else respuesta
        raise AssertionError(f"ruta no simulada: {url}")

    def enviar(self, metodo, url, headers, cuerpo):
        self.enviados.append((metodo, urlparse(url).path, cuerpo))
        return {}


@pytest.fixture
def base(retail_demo, monkeypatch, tmp_path):
    from app.retail import cifrado
    monkeypatch.setattr(cifrado, "ARCHIVO", tmp_path / "clave")
    monkeypatch.setattr(api_ingesta, "recalcular_en_segundo_plano", lambda org, desde=None: None)
    prods = _q("SELECT p.id, p.codigo_interno, p.ean FROM productos p JOIN stock_actual s ON s.producto_id=p.id "
               "JOIN ubicaciones u ON u.id=s.ubicacion_id WHERE u.nombre='Salta Centro' AND p.ean IS NOT NULL AND s.cantidad - s.reservado >= 5 "
               "ORDER BY p.id LIMIT 2")
    centro = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Centro'")[0]["id"]
    return cliente(), prods, centro, monkeypatch


def _sync(pid):
    ctx = motor.contexto_sistema(1)
    with db.transaccion(ctx) as conn:
        return plataformas_online.sincronizar(conn, ctx, pid)


def _conectar(c, mp, falsa, cuerpo):
    mp.setattr(plataformas_online, "_http", falsa)
    mp.setattr(plataformas_online, "_enviar", falsa.enviar)
    mp.setattr(plataformas_online, "_url_publica", lambda url: url)
    probar = c.post("/retail/api/conexiones/tienda/probar", json=cuerpo)
    assert probar.status_code == 200, probar.text
    r = c.post("/retail/api/conexiones/tienda", json=cuerpo)
    assert r.status_code == 200, r.text
    listado = str(c.get("/retail/api/conexiones").json())
    for clave in ("token", "clave", "secreto"):
        if cuerpo.get(clave):
            assert cuerpo[clave] not in listado                       # las claves nunca vuelven
    return r.json()["id"]


def _stock(pid, ubic):
    f = _q("SELECT cantidad - reservado d FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (pid, ubic))[0]["d"]
    return int(f)


def test_woocommerce_y_propuesta_aprobada(base):
    c, prods, centro, mp = base
    a, b = prods
    falsa = Falsa({
        "/wc/v3/orders": lambda q: [] if q.get("page") != "1" or q.get("per_page") == "1" else [
            {"id": 501, "status": "processing", "date_created_gmt": "2026-09-23T15:00:00", "total": "2500.00",
             "line_items": [{"product_id": 70, "variation_id": 0, "sku": a["codigo_interno"], "name": "A", "quantity": 2, "price": 1250}]},
            {"id": 502, "status": "completed", "date_created_gmt": "2026-09-22T10:00:00", "date_completed_gmt": "2026-09-22T18:00:00",
             "total": "900.00", "line_items": [{"product_id": 71, "variation_id": 72, "sku": "", "name": "B", "quantity": 1, "price": 900}]},
            {"id": 503, "status": "pending", "date_created_gmt": "2026-09-23T11:00:00", "total": "100.00", "line_items": []}],
        "/wc/v3/products": lambda q: [] if q.get("page") != "1" else [
            {"id": 70, "type": "simple", "name": "Prod A", "status": "publish", "sku": a["codigo_interno"], "price": "1250", "manage_stock": True,
             "stock_quantity": 999},
            {"id": 71, "type": "variable", "name": "Prod B", "status": "publish"}],
        "/wc/v3/products/71/variations": lambda q: [] if q.get("page") != "1" else [
            {"id": 72, "sku": "", "global_unique_id": b["ean"], "price": "900", "manage_stock": True, "stock_quantity": 0}],
    })
    pid = _conectar(c, mp, falsa, {"tipo": "woocommerce", "url": "https://tienda.ejemplo.com.ar", "clave": "ck_x", "secreto": "cs_y",
                                   "ubicacion_despacho_id": centro, "comision_pct": 0.0})
    res = _sync(pid)
    assert res["pedidos_nuevos"] == 2 and res["publicaciones"] == 2 and res["publicaciones_sin_emparejar"] == 0
    assert falsa.enviados == []                                     # sincronizar nunca escribe
    t = {x["numero_externo"]: x for x in _q("SELECT t.numero_externo, po.estado FROM tickets t JOIN pedidos_online po ON po.ticket_id=t.id "
                                            "WHERE t.plataforma_id=%s", (pid,))}
    assert t[f"{pid}-501"]["estado"] == "pendiente" and t[f"{pid}-502"]["estado"] == "entregado"

    # Propuestas: A publicado 999 (sobreventa) y B publicado 0 con stock (falta publicar).
    r = c.get("/retail/api/canales/stock/propuestas").json()
    mias = {p["nombre"]: p for p in r["propuestas"] if p["plataforma"] == "WooCommerce"}
    assert len(mias) == 2 and r["puede_aprobar"]
    motivos = {p["motivo"] for p in mias.values()}
    assert motivos == {"sobreventa", "falta_publicar"}
    ids = [p["id"] for p in mias.values()]
    # Nada salió todavía; un comprador (sin gestionar conexiones) no puede aprobar.
    assert falsa.enviados == []
    assert cliente("compras@norte.demo").post("/retail/api/canales/stock/propuestas/aplicar", json={"ids": ids}).status_code == 403
    ok = c.post("/retail/api/canales/stock/propuestas/aplicar", json={"ids": ids})
    assert ok.status_code == 200 and ok.json()["aplicadas"] == 2, ok.text
    enviados = {ruta: cuerpo for _m, ruta, cuerpo in falsa.enviados}
    assert enviados["/wp-json/wc/v3/products/70"]["stock_quantity"] == _stock(a["id"], centro)
    assert enviados["/wp-json/wc/v3/products/71/variations/72"]["stock_quantity"] == _stock(b["id"], centro)
    assert all(m == "PUT" for m, *_ in falsa.enviados)
    h = c.get("/retail/api/canales/stock/propuestas").json()
    assert not [p for p in h["propuestas"] if p["plataforma"] == "WooCommerce"]
    assert {x["estado"] for x in h["historial"] if x["plataforma"] == "WooCommerce"} == {"aplicada"}
    assert _q("SELECT count(*) n FROM auditoria WHERE accion='actualizar_stock_publicado'")[0]["n"] == 2
    # Aprobar de nuevo lo ya aplicado no vuelve a enviar.
    c.post("/retail/api/canales/stock/propuestas/aplicar", json={"ids": ids})
    assert len(falsa.enviados) == 2


def test_shopify_y_vtex_leen_y_escriben_solo_lo_aprobado(base):
    c, prods, centro, mp = base
    a, b = prods
    shop = Falsa({
        "/shop.json": {"shop": {"id": 9, "name": "Norte Online"}},
        "/products.json": lambda q: {"products": [] if q.get("since_id") != "0" else [
            {"id": 1, "title": "Prod A", "status": "active", "variants": [{"id": 11, "inventory_item_id": 111, "title": "Default Title",
                                                                          "sku": a["codigo_interno"], "price": "1000", "inventory_management": "shopify",
                                                                          "inventory_quantity": 500}]}]},
        "/orders.json": lambda q: {"orders": [] if q.get("since_id") != "0" else [
            {"id": 7001, "created_at": "2026-09-23T12:00:00-03:00", "financial_status": "paid", "fulfillment_status": "fulfilled",
             "fulfillments": [{"created_at": "2026-09-23T18:00:00-03:00"}], "total_price": "2000.00",
             "line_items": [{"variant_id": 11, "sku": a["codigo_interno"], "title": "Prod A", "quantity": 2, "price": "1000.00"}]},
            {"id": 7002, "created_at": "2026-09-23T13:00:00-03:00", "financial_status": "pending", "total_price": "5.00", "line_items": []}]},
        "/locations.json": {"locations": [{"id": 55, "active": True}]},
    })
    pid = _conectar(c, mp, shop, {"tipo": "shopify", "tienda": "Norte-Online.myshopify.com", "token": "shpat_x", "ubicacion_despacho_id": centro})
    res = _sync(pid)
    assert res["pedidos_nuevos"] == 1 and res["publicaciones"] == 1
    assert _q("SELECT config->>'tienda' t FROM plataformas WHERE id=%s", (pid,))[0]["t"] == "norte-online.myshopify.com"
    prop = [p for p in c.get("/retail/api/canales/stock/propuestas").json()["propuestas"] if p["plataforma"] == "Shopify"]
    assert len(prop) == 1 and prop[0]["motivo"] == "sobreventa"
    # Descartar: queda registrado y no se envía nada.
    assert c.post("/retail/api/canales/stock/propuestas/descartar", json={"ids": [prop[0]["id"]]}).json()["descartadas"] == 1
    assert shop.enviados == []
    # Al revisar de nuevo, la diferencia sigue y vuelve a proponerse; ahora se aprueba.
    c.post("/retail/api/canales/stock/propuestas/revisar")
    prop = [p for p in c.get("/retail/api/canales/stock/propuestas").json()["propuestas"] if p["plataforma"] == "Shopify"]
    c.post("/retail/api/canales/stock/propuestas/aplicar", json={"ids": [prop[0]["id"]]})
    assert shop.enviados == [("POST", "/admin/api/2024-10/inventory_levels/set.json",
                              {"location_id": 55, "inventory_item_id": 111, "available": _stock(a["id"], centro)})]

    vtex = Falsa({
        "/products/GetProductAndSkuIds": {"data": {}, "range": {"total": 1}},
        "/sku/stockkeepingunitids": [21],
        "/sku/stockkeepingunitbyid/21": {"Id": 21, "RefId": "", "AlternateIds": {"Ean": b["ean"]}, "NameComplete": "Prod B", "IsActive": True,
                                         "SkuSellers": [{"Price": 900}]},
        "/inventory/skus/21": {"balance": [{"warehouseId": "1_1", "totalQuantity": 400, "reservedQuantity": 0}]},
        "/oms/pvt/orders": {"list": [{"orderId": "V-1", "status": "invoiced"}], "paging": {"pages": 1}},
        "/oms/pvt/orders/V-1": {"orderId": "V-1", "status": "invoiced", "creationDate": "2026-09-23T15:00:00Z", "invoicedDate": "2026-09-23T20:00:00Z",
                                "value": 180000, "items": [{"id": "21", "refId": "", "name": "Prod B", "quantity": 2, "sellingPrice": 90000}]},
    })
    pid_v = _conectar(c, mp, vtex, {"tipo": "vtex", "cuenta": "norte", "clave": "vtexappkey-x", "secreto": "tok", "ubicacion_despacho_id": centro})
    res = _sync(pid_v)
    assert res["pedidos_nuevos"] == 1
    total = _q("SELECT total FROM tickets WHERE plataforma_id=%s", (pid_v,))[0]["total"]
    assert total == Decimal("1800.00")                               # VTEX informa en centavos
    prop = [p for p in c.get("/retail/api/canales/stock/propuestas").json()["propuestas"] if p["plataforma"] == "VTEX"]
    c.post("/retail/api/canales/stock/propuestas/aplicar", json={"ids": [p["id"] for p in prop]})
    assert vtex.enviados == [("PUT", "/api/logistics/pvt/inventory/skus/21/warehouses/1_1",
                              {"unlimitedQuantity": False, "quantity": _stock(b["id"], centro)})]


def test_validaciones_de_conexion(base):
    c, _prods, centro, _mp = base
    malos = [({"tipo": "shopify", "tienda": "tienda.com", "token": "x"}, "myshopify"),
             ({"tipo": "vtex", "cuenta": "no válida!", "clave": "a", "secreto": "b"}, "VTEX"),
             ({"tipo": "woocommerce", "url": "http://tienda.com", "clave": "a", "secreto": "b"}, "https"),
             ({"tipo": "woocommerce", "url": "https://127.0.0.1", "clave": "a", "secreto": "b"}, "pública"),
             ({"tipo": "vtex", "cuenta": "norte", "clave": "a"}, "claves"),
             ({"tipo": "pedidosya", "token": "a"}, "soportada")]
    for cuerpo, texto in malos:
        r = c.post("/retail/api/conexiones/tienda/probar", json={**cuerpo, "ubicacion_despacho_id": centro})
        assert r.status_code == 400 and texto in r.json()["detail"], (cuerpo, r.text)


def test_demo_propone_sin_enviar(retail_demo):
    c = cliente()
    r = c.get("/retail/api/canales/stock/propuestas").json()
    por = {(p["nombre"], p["plataforma"]): p for p in r["propuestas"]}
    codigos = {x["nombre"]: x["codigo_interno"] for x in r["propuestas"]}
    sobre = {p["motivo"] for p in r["propuestas"] if p["codigo_interno"] in demo.CASOS["sobreventa"]["productos"]}
    falta = {p["motivo"] for p in r["propuestas"] if p["codigo_interno"] in demo.CASOS["sin_publicar_stock"]["productos"]}
    assert sobre == {"sobreventa"} and falta == {"falta_publicar"} and codigos and por
    assert all(p["se_puede_enviar"] for p in r["propuestas"])
    elegida = next(p for p in r["propuestas"] if p["motivo"] == "sobreventa")
    res = c.post("/retail/api/canales/stock/propuestas/aplicar", json={"ids": [elegida["id"]]}).json()
    assert res["aplicadas"] == 1 and "Demo" in res["resultados"][0]["mensaje"]
    # La sobreventa de esa publicación desaparece de Canales.
    stock = c.get("/retail/api/canales/stock").json()
    assert not [s for s in stock["sobreventa"] if s["nombre"] == elegida["nombre"] and s["plataforma"] == elegida["plataforma"]]


def test_importar_pedidos_de_delivery(retail_demo, monkeypatch):
    import importlib
    ti = importlib.import_module("test_retail_importar")
    monkeypatch.setattr(api_ingesta, "recalcular_en_segundo_plano", lambda org, desde=None: None)
    c = cliente()
    prods = _q("SELECT codigo_interno, ean FROM productos WHERE ean IS NOT NULL ORDER BY id LIMIT 2")
    filas = [["Fecha", "Hora", "App", "Nro Pedido", "Local", "Codigo", "Cantidad", "Precio", "Comision", "Costo envio", "Estado"],
             ["21/09/2026", "20:10", "PedidosYa", "PY-1", "Salta Centro", prods[0]["codigo_interno"], "2", "1000", "450", "0", "Entregado"],
             ["21/09/2026", "20:10", "PedidosYa", "PY-1", "Salta Centro", prods[1]["ean"], "1", "500", "450", "0", "Entregado"],
             ["22/09/2026", "13:00", "Rappi", "R-9", "Salta Norte", prods[0]["codigo_interno"], "1", "1000", "180", "300", "Entregado"],
             ["22/09/2026", "14:00", "Rappi", "R-10", "Salta Norte", prods[0]["codigo_interno"], "1", "1000", "0", "0", "Cancelado"],
             ["22/09/2026", "15:00", "Glovo", "G-1", "Salta Norte", prods[0]["codigo_interno"], "1", "1000", "0", "0", "Entregado"]]
    archivo = ti._csv(filas)
    a, v, r = ti._importar(c, "delivery", "pedidos.csv", archivo)
    assert a["mapeo"]["pedido"] == "Nro Pedido" and a["mapeo"]["plataforma"] == "App" and a["mapeo"]["comision"] == "Comision"
    assert v["validas"] == 4 and v["con_error"] == 1 and "Glovo" in v["errores"][0]["error"]
    res = r.json()
    assert res["importadas"] == 3 and res["anulados"] == 1 and res["lineas"] == 4
    t = {x["numero_externo"].split("-", 1)[1]: x for x in _q(
        "SELECT t.numero_externo, t.total, t.estado, t.origen, c.codigo canal, cc.comision, cc.envio FROM tickets t JOIN canales c ON c.id=t.canal_id "
        "JOIN costos_canal cc ON cc.ticket_id=t.id WHERE t.origen IN ('pedidosya', 'rappi')")}
    assert t["PY-1"]["total"] == Decimal("2500.00") and t["PY-1"]["comision"] == Decimal("450.00")    # la comisión del pedido, no la suma de filas
    assert t["R-9"]["envio"] == Decimal("300.00") and t["R-9"]["canal"] == "delivery" and t["R-10"]["estado"] == "anulado"
    # Reimportar no duplica; el canal delivery queda activo y aparece en la ganancia por canal.
    _, _, r2 = ti._importar(c, "delivery", "pedidos.csv", archivo)
    assert r2.json()["importadas"] == 0 and r2.json()["duplicadas"] == 3
    assert _q("SELECT activo FROM canales WHERE codigo='delivery'")[0]["activo"]
    assert {p["tipo"] for p in _q("SELECT tipo FROM plataformas WHERE tipo IN ('pedidosya', 'rappi')")} == {"pedidosya", "rappi"}
