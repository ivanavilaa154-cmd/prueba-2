"""Retail · parte 5: lector de facturas, remitos y listas con IA (cliente falso: no llama a la API)."""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.retail import api_ingesta, db, lector, motor
from app.retail.semilla import CLAVE_DEMO


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


class ClienteFalso:
    def __init__(self, documento, stop_reason="end_turn"):
        self.pedidos = []
        self.messages = SimpleNamespace(parse=self._parse)
        self.documento = documento
        self.stop_reason = stop_reason

    def _parse(self, **kw):
        self.pedidos.append(kw)
        return SimpleNamespace(stop_reason=self.stop_reason, parsed_output=self.documento)


@pytest.fixture
def preparar(monkeypatch, tmp_path):
    monkeypatch.setattr(lector, "CARPETA", tmp_path)
    monkeypatch.setattr(api_ingesta, "recalcular_en_segundo_plano", lambda org, desde=None: None)

    def usar(documento, **kw):
        falso = ClienteFalso(documento, **kw)
        monkeypatch.setattr(lector, "_cliente", lambda: falso)
        return falso
    return usar


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _datos():
    prov = _q("SELECT id, razon_social, cuit FROM proveedores ORDER BY id LIMIT 1")[0]
    prods = _q("SELECT p.id, p.nombre, p.codigo_interno, pp.costo FROM productos p JOIN producto_proveedores pp ON pp.producto_id=p.id "
               "WHERE pp.proveedor_id=%s ORDER BY p.id LIMIT 2", (prov["id"],))
    suc = _q("SELECT id FROM ubicaciones ORDER BY id LIMIT 1")[0]["id"]
    return prov, prods, suc


def test_factura_leida_se_revisa_y_se_recibe(retail_demo, preparar):
    prov, prods, suc = _datos()
    doc = lector.DocumentoLeido(tipo="factura", proveedor=prov["razon_social"].upper(), cuit=None, numero="0003-00012345", fecha="2026-09-20",
                                vigencia_desde=None, total=None, observaciones=None, lineas=[
        lector.LineaLeida(codigo=prods[0]["codigo_interno"], descripcion=prods[0]["nombre"], cantidad=12, costo_unitario=float(prods[0]["costo"]) * 1.1,
                          lote="L1", vencimiento="2026-12-01", confianza=0.95),
        lector.LineaLeida(codigo=None, descripcion="Artículo borroso ilegible", cantidad=3, costo_unitario=10, confianza=0.4)])
    falso = preparar(doc)
    c = cliente()
    r = c.post("/retail/api/lector/leer", data={"tipo": "factura", "ubicacion_id": str(suc)}, files={"archivo": ("factura.pdf", b"%PDF-1.4 falso")})
    assert r.status_code == 200, r.text
    r = r.json()
    pedido = falso.pedidos[0]
    assert pedido["messages"][0]["content"][0]["type"] == "document" and pedido["output_format"] is lector.DocumentoLeido
    assert r["proveedor_encontrado"]["id"] == prov["id"]                      # por similitud de la razón social
    assert r["lineas"][0]["producto_id"] == prods[0]["id"] and not r["lineas"][0]["revisar"]
    assert r["lineas"][1]["producto_id"] is None and r["lineas"][1]["revisar"]
    assert c.get("/retail/api/lector").json()[0]["id"] == r["id"]

    # La persona asigna el producto de la línea borrosa y confirma.
    lineas = [dict(r["lineas"][0]), {**r["lineas"][1], "producto_id": prods[1]["id"]}]
    antes = _q("SELECT coalesce(sum(cantidad),0) s FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (prods[0]["id"], suc))[0]["s"]
    ok = c.post(f"/retail/api/lector/{r['id']}/confirmar", json={"proveedor_id": prov["id"], "ubicacion_id": suc, "lineas": lineas})
    assert ok.status_code == 200, ok.text
    assert ok.json()["aumentos_de_costo"]
    despues = _q("SELECT sum(cantidad) s FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (prods[0]["id"], suc))[0]["s"]
    assert despues - antes == Decimal("12")
    assert _q("SELECT documento FROM recepciones ORDER BY id DESC LIMIT 1")[0]["documento"] == "0003-00012345"
    assert _q("SELECT estado FROM documentos_leidos WHERE id=%s", (r["id"],))[0]["estado"] == "confirmado"
    # Lo corregido a mano quedó como alias: la próxima vez se reconoce solo.
    assert _q("SELECT producto_id FROM alias_producto WHERE texto='Artículo borroso ilegible'")[0]["producto_id"] == prods[1]["id"]
    # No se confirma dos veces.
    assert c.post(f"/retail/api/lector/{r['id']}/confirmar", json={"proveedor_id": prov["id"], "ubicacion_id": suc, "lineas": lineas}).status_code == 400


def test_lista_de_precios_por_foto(retail_demo, preparar):
    prov, prods, _ = _datos()
    nuevo = round(float(prods[0]["costo"]) * 1.2, 2)
    preparar(lector.DocumentoLeido(tipo="lista_precios", proveedor=prov["razon_social"], cuit=None, numero=None, fecha=None, vigencia_desde="2026-09-25",
                                   total=None, observaciones=None, lineas=[lector.LineaLeida(codigo=prods[0]["codigo_interno"], descripcion=prods[0]["nombre"],
                                                                                             cantidad=None, costo_unitario=nuevo, confianza=0.9)]))
    c = cliente()
    r = c.post("/retail/api/lector/leer", data={"tipo": "lista_precios"}, files={"archivo": ("lista.jpg", b"\xff\xd8\xff falso")}).json()
    ok = c.post(f"/retail/api/lector/{r['id']}/confirmar", json={"proveedor_id": prov["id"], "lineas": r["lineas"]})
    assert ok.status_code == 200, ok.text
    assert _q("SELECT costo FROM producto_proveedores WHERE producto_id=%s AND proveedor_id=%s", (prods[0]["id"], prov["id"]))[0]["costo"] == Decimal(str(nuevo))
    l = _q("SELECT lp.vigencia_desde, lp.origen FROM listas_precios_proveedor lp ORDER BY id DESC LIMIT 1")[0]
    assert l["origen"] == "documento" and l["vigencia_desde"].isoformat() == "2026-09-25"


def test_errores_del_lector(retail_demo, preparar):
    c = cliente()
    assert c.post("/retail/api/lector/leer", data={"tipo": "factura"}, files={"archivo": ("x.xlsx", b"1")}).status_code == 400
    preparar(None, stop_reason="refusal")
    r = c.post("/retail/api/lector/leer", data={"tipo": "factura"}, files={"archivo": ("x.pdf", b"1")})
    assert r.status_code == 400 and "no quiso" in r.json()["detail"]
    # Una lista de precios la carga quien gestiona proveedores, no la caja.
    assert cliente("caja.centro@norte.demo").post("/retail/api/lector/leer", data={"tipo": "lista_precios"},
                                                  files={"archivo": ("x.pdf", b"1")}).status_code == 403
