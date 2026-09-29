"""Predicciones · parte A: rango de confianza, probabilidad de quiebre y salud de los pronósticos (contra la demo)."""
from fastapi.testclient import TestClient

from app.main import app
from app.retail import db
from app.retail.semilla import CLAVE_DEMO


def cliente():
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": "dueno@norte.demo", "clave": CLAVE_DEMO}).status_code == 200
    return c


def test_comprar_trae_rango_y_probabilidad_de_quiebre(retail_demo):
    filas = [f for f in cliente().get("/retail/api/comprar").json()["filas"] if f["tipo_ubicacion"] != "deposito" and f["pronostico_7d"]]
    assert filas
    for f in filas:
        assert float(f["pronostico_7d_min"]) <= float(f["pronostico_7d"]) <= float(f["pronostico_7d_max"])
        assert f["prob_quiebre"] is None or 0 <= float(f["prob_quiebre"]) <= 1
    rojos = [float(f["prob_quiebre"]) for f in filas if f["semaforo"] == "rojo" and f["prob_quiebre"] is not None]
    verdes = [float(f["prob_quiebre"]) for f in filas if f["semaforo"] == "verde" and f["prob_quiebre"] is not None]
    assert rojos and verdes and sum(rojos) / len(rojos) > 0.5 > sum(verdes) / len(verdes)


def test_salud_de_los_pronosticos(retail_demo):
    r = cliente().get("/retail/api/modelos/salud").json()
    g = r["global"]
    print({k: g[k] for k in ("wape", "sesgo", "cobertura", "n")}, r["excluidos_por_quiebre"])
    assert r["evaluados"] > 200 and r["origen_prueba"] > 0                 # la prueba sobre el pasado ya dejó semanas medidas
    assert 0 < g["wape"] < 0.8
    assert abs(g["sesgo"]) < 0.2                                            # sin sobreestimar ni subestimar de forma sistemática
    assert 0.7 <= g["cobertura"] <= 0.93                                    # el rango del 80 % contiene lo real ~80 % de las veces
    assert r["semanas"] and r["por_categoria"] and r["por_ubicacion"] and r["peores"]
    assert r["peores"][0]["error_pesos"] >= r["peores"][-1]["error_pesos"]
    assert r["datos"]["productos"] > 0 and r["avisos"]                      # la demo chica tiene 120 días: avisa que falta historia
    with db.transaccion(superadmin=True) as conn:
        assert db.fila(conn, "SELECT count(*) n FROM pronosticos_registro WHERE origen='diario'")["n"] > 0


def test_correccion_de_sesgo_con_topes(retail_demo):
    from app.retail import motor, pronosticos
    from app.retail.api_comprar import _hoy_datos
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        f = pronosticos.factores_sesgo(conn, _hoy_datos(conn))
    assert f and all(0.8 <= v <= 1.25 for v in f.values())
    r = cliente().get("/retail/api/modelos/salud").json()
    assert all(0.8 <= c["factor"] <= 1.25 for c in r["correcciones"])
    # El cálculo de hoy ya usó la corrección y la dejó registrada.
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        assert db.fila(conn, "SELECT count(*) n FROM pronosticos_registro WHERE origen='diario' AND factor <> 1")["n"] > 0
