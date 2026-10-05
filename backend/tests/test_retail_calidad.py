"""SPEC v2 · diagnóstico de calidad de datos (5.6). Criterio de aceptación: detecta todos los problemas sembrados en la demo."""
from fastapi.testclient import TestClient

from app.main import app
from app.retail import db, demo, motor
from app.retail.semilla import CLAVE_DEMO


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _id(codigo):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.fila(conn, "SELECT id FROM productos WHERE codigo_interno=%s", (codigo,))["id"]


def test_detecta_todos_los_problemas_sembrados(retail_demo):
    c = cliente()
    r = c.post("/retail/api/calidad/revisar").json()
    por_codigo = {p["codigo"]: {x["id"] for x in p["productos"]} for p in r["problemas"]}
    s = demo.CASOS["calidad"]
    assert {_id(s["duplicado"]), _id(s["duplicado"] + "-DUP")} <= por_codigo["duplicado"]
    assert {_id(x) for x in s["costo_viejo"]} <= por_codigo["costo_viejo"]
    assert _id(s["sin_categoria"]) in por_codigo["sin_categoria"]
    assert _id(s["bulto"]) in por_codigo["conversion_dudosa"]
    assert _id(s["precio_cero"]) in por_codigo["venta_bajo_costo"]
    assert _id(s["stock_inmovil"][0]) in por_codigo["stock_inmovil"]
    assert _id(demo.CASOS["stock_negativo"]["producto"]) in por_codigo["stock_negativo"]
    assert _id(demo.CASOS["sin_costo"]["producto"]) in por_codigo["sin_costo"]
    assert 0 < float(r["puntaje"]) < 100
    assert float(r["comercial"]["faltantes_90_dias"]) > 0 and float(r["comercial"]["plata_parada"]) >= 0
    # La pantalla muestra el último diagnóstico y la confianza por producto llega a las recomendaciones.
    v = c.get("/retail/api/calidad").json()
    assert v["ultimo"]["puntaje"] == r["puntaje"] and v["confianza"].get("baja", 0) > 0
    filas = c.get("/retail/api/comprar").json()["filas"]
    bulto = next(f for f in filas if f["producto_id"] == _id(s["bulto"]))
    assert bulto["confianza_datos"] == "baja" and "conversion_dudosa" in bulto["problemas_datos"]


def test_el_calculo_nocturno_hace_el_primer_diagnostico(retail_demo):
    with db.transaccion(motor.contexto_sistema(1)) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM chequeos_calidad")
    r = motor.recalcular(1, tipo="incremental")
    assert "calidad" in r
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        assert db.fila(conn, "SELECT origen FROM chequeos_calidad ORDER BY id DESC LIMIT 1")["origen"] == "conexion"
