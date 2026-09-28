"""Retail · parte 10: remarcación contra la sección 11."""
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.retail import calculos as C
from app.retail import db, demo, motor
from app.retail.semilla import CLAVE_DEMO


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def test_aumento_del_proveedor_prioriza_y_sugiere_precio(retail_demo):
    r = cliente().get("/retail/api/precios/remarcacion").json()
    prov = demo.CASOS["aumento_sin_remarcar"]["proveedor"]
    subir = [i for i in r["items"] if i["estado"] == "subir"]
    assert subir and r["tarjetas"]["a_remarcar"] == len(subir)
    del_prov = [i for i in r["items"] if i["proveedor"] == prov and i["aumento_pct"]]
    assert del_prov and all(Decimal(i["aumento_pct"]) > Decimal("0.10") for i in del_prov)
    # Orden: mayor pérdida de margen por día primero
    perdidas = [Decimal(i["perdida_diaria"]) for i in subir]
    assert perdidas == sorted(perdidas, reverse=True)
    reglas = _q("SELECT * FROM reglas_redondeo ORDER BY desde_precio")
    for i in subir[:20]:
        if i["parcial"]:
            continue
        esperado = C.redondear_precio(C.precio_sugerido(Decimal(i["costo"]), Decimal(i["margen_objetivo"])), reglas)
        assert Decimal(i["sugerido"]) == esperado


def test_imanes_trasladan_la_mitad(retail_demo):
    r = cliente().get("/retail/api/precios/remarcacion").json()
    for i in r["items"]:
        if i.get("parcial"):
            assert i["rol_producto"] == "iman" and "mitad" in i["motivo"]


def test_aplicar_precios_y_etiquetas(retail_demo, tmp_path, monkeypatch):
    from app.retail import pdf
    monkeypatch.setattr(pdf, "CARPETA", tmp_path)
    c = cliente()
    r = c.get("/retail/api/precios/remarcacion?filtro=a_remarcar").json()
    elegidos = r["items"][:3]
    res = c.post("/retail/api/precios/aplicar", json={"cambios": [{"producto_id": i["id"], "precio": i["sugerido"]} for i in elegidos]})
    assert res.status_code == 200 and res.json()["aplicados"] == 3
    for i in elegidos:
        vigentes = _q("SELECT precio FROM precios WHERE producto_id=%s AND canal_id IS NULL AND hasta IS NULL", (i["id"],))
        assert len(vigentes) == 1 and vigentes[0]["precio"] == Decimal(i["sugerido"])
    pdfr = c.get(f"/retail/api/precios/etiquetas?desde={res.json()['desde']}")
    assert pdfr.status_code == 200 and pdfr.content[:4] == b"%PDF"
    assert cliente("encargado.norte@norte.demo").post("/retail/api/precios/aplicar", json={"cambios": [{"producto_id": 1, "precio": "10"}]}).status_code == 403


def test_canal_online_suma_sus_costos(retail_demo):
    general = {i["id"]: i for i in cliente().get("/retail/api/precios/remarcacion").json()["items"]}
    online = cliente().get("/retail/api/precios/remarcacion?canal=ecommerce").json()
    assert Decimal(online["canal_costo_pct"]) > 0
    for i in online["items"][:30]:
        g = general.get(i["id"])
        if g and g["sugerido"] and i["sugerido"] and not i["parcial"] and not g["parcial"]:
            assert Decimal(i["sugerido"]) >= Decimal(g["sugerido"])
