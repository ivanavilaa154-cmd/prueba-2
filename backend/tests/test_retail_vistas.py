"""Predicciones · parte D: vistas por rol (contra la demo)."""
from fastapi.testclient import TestClient

from app.main import app
from app.retail.semilla import CLAVE_DEMO


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def test_el_dueno_ve_las_cinco_vistas_con_sus_bloques(retail_demo):
    c = cliente()
    r = c.get("/retail/api/vistas").json()
    assert [v["codigo"] for v in r["vistas"]] == ["direccion", "comercial", "sucursal", "marketing", "finanzas"]
    assert r["por_defecto"] == "direccion"
    for v in r["vistas"]:
        d = c.get(f"/retail/api/vistas/{v['codigo']}").json()
        assert d["kpis"] and d["atajos"] and d["detalle"] is not None, v
        p = d["pronostico"]
        futuros = [x for x in p["puntos"] if "pronostico" in x]
        assert futuros and all(x["rango"][0] <= x["pronostico"] <= x["rango"][1] for x in futuros), v
        titulos = [(a["tipo"], a["titulo"]) for a in d["alertas"]]
        assert len(titulos) == len(set(titulos)) <= 6
        impactos = [float(a["impacto"]) for a in d["alertas"]]
        assert impactos == sorted(impactos, reverse=True)


def test_la_vista_de_direccion_suma_lo_mismo_que_pronosticos(retail_demo):
    c = cliente()
    d = c.get("/retail/api/vistas/direccion").json()
    total = c.get("/retail/api/pronosticos/ventas", params={"dias": 30}).json()["total_periodo"]
    assert abs(d["pronostico"]["total"] - total) / total < 0.1


def test_el_encargado_solo_ve_su_sucursal(retail_demo):
    c = cliente("encargado.norte@norte.demo")
    r = c.get("/retail/api/vistas").json()
    assert [v["codigo"] for v in r["vistas"]] == ["sucursal"] and r["por_defecto"] == "sucursal"
    d = c.get("/retail/api/vistas/sucursal").json()
    assert [o["nombre"] for o in d["ubicacion"]["opciones"]] == ["Salta Norte"]
    assert all(a["ubicacion"] in (None, "Salta Norte") for a in d["alertas"])
    otra = cliente().get("/retail/api/vistas/sucursal").json()["ubicacion"]["opciones"]
    ajena = next(o["id"] for o in otra if o["nombre"] != "Salta Norte")
    assert c.get("/retail/api/vistas/sucursal", params={"ubicacion_id": ajena}).json()["ubicacion"]["elegida"]["nombre"] == "Salta Norte"
    assert c.get("/retail/api/vistas/direccion").status_code == 403
    assert c.get("/retail/api/vistas/finanzas").status_code == 403


def test_el_cajero_no_tiene_tablero(retail_demo):
    c = cliente("caja.centro@norte.demo")
    assert c.get("/retail/api/vistas").json()["vistas"] == []
    assert c.get("/retail/api/vistas/sucursal").status_code == 403
