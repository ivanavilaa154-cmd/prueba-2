"""Retail · Fase 3: canasta, promociones, sensibilidad al precio, surtido y clientes (contra la estructura conocida de la demo)."""
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.retail import db, demo, motor
from app.retail.semilla import CLAVE_DEMO


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _sub(pid_nombre):
    return {p["nombre"]: p["sub"] for p in _q("SELECT p.nombre, c.nombre sub FROM productos p JOIN categorias c ON c.id = p.categoria_id")}


def test_canasta_encuentra_las_afinidades_de_la_demo(retail_demo):
    r = cliente().get("/retail/api/ventas/canasta").json()
    assert r["suficiente"] and r["tickets"] >= 500
    sub = _sub(None)
    pares = {(sub[x["si_compra"]], sub[x["tambien"]]) for x in r["reglas"]}
    esperados = {(a, b) for a, b in demo.AFINIDADES.items()} | {(b, a) for a, b in demo.AFINIDADES.items()}
    assert len(pares & esperados) >= 3                       # las parejas de la demo aparecen con lift alto
    for x in r["reglas"]:
        assert x["lift"] >= 1.5 and 0 < x["confianza"] <= 1 and "también llevan" in x["texto"]
    assert r["sugerencias"] and r["arrastre"]
    # Cálculo manual de una regla.
    x = r["reglas"][0]
    t = _q("""SELECT count(DISTINCT l.ticket_id) FILTER (WHERE l.producto_id=%s) a, count(DISTINCT l.ticket_id) FILTER (WHERE l.producto_id=%s) b
              FROM tickets_lineas l JOIN tickets tk ON tk.id = l.ticket_id WHERE tk.estado <> 'anulado' AND l.cantidad > 0 AND l.fecha > %s AND l.fecha <= %s""",
           (x["si_compra_id"], x["tambien_id"], r["desde"], r["hasta"]))[0]
    assert abs(x["confianza"] - x["tickets_juntos"] / t["a"]) < 1e-3
    assert abs(x["lift"] - (x["tickets_juntos"] / t["a"]) / (t["b"] / r["tickets"])) < 1e-2


def test_efectividad_de_promociones(retail_demo):
    r = cliente().get("/retail/api/promociones/efectividad").json()
    assert r["promociones"]
    for p in r["promociones"]:
        neto = Decimal(p["incremento_ganancia"]) - Decimal(p["canibalizacion"]) - Decimal(p["rebote"])
        assert abs(neto - Decimal(p["neto"])) < Decimal("0.02") and p["recomendacion"]
    # Las promociones de la demo venden más que su línea base.
    assert sum(Decimal(p["incremento_unidades"]) > 0 for p in r["promociones"]) >= len(r["promociones"]) * 0.7


def test_sensibilidad_invariantes(retail_demo):
    """La precisión del estimador se prueba con datos sintéticos (test_retail_calculos); la demo de prueba tiene pocas semanas."""
    r = cliente().get("/retail/api/precios/sensibilidad").json()
    assert sum(r["resumen"].values()) == len(r["productos"]) > 0
    for p in r["productos"]:
        if p["elasticidad"] is not None:
            assert -5 <= p["elasticidad"] <= 0.3 and p["clase"] in ("sensible", "poco_sensible")
        else:
            assert p["clase"] == "sin_datos"
    rem = cliente().get("/retail/api/precios/remarcacion").json()["items"]
    assert all("sensibilidad" in i for i in rem)


def test_surtido(retail_demo):
    jujuy = _q("SELECT id FROM ubicaciones WHERE nombre='San Salvador de Jujuy'")[0]["id"]
    r = cliente().get(f"/retail/api/surtido?ubicacion_id={jujuy}").json()
    for s in r["subcategorias"]:
        assert abs(sum(x["participacion"] for x in s["participacion"]) - 1) < 1e-6 or Decimal(s["facturacion"]) == 0
        assert s["marcas"] <= s["productos"]
    clases = {p["id"]: p["clase_abc"] for p in _q("SELECT id, clase_abc FROM productos")}
    assert r["discontinuar"] and all(clases[d["producto_id"]] == "C" and d["sustituto"] for d in r["discontinuar"])


def test_clientes_rfm(retail_demo):
    r = cliente().get("/retail/api/clientes").json()
    assert r["activo"] and sum(s["clientes"] for s in r["segmentos"]) == r["clientes"]
    gastos = [Decimal(x["gasto_180d"]) for x in r["mayor_valor"]]
    assert gastos == sorted(gastos, reverse=True)
    # En la demo, algunos clientes habituales (número múltiplo de 11 y menor a 300) dejaron de venir hace ~3 meses.
    dejaron = {int(x["cliente"][3:]) for x in r["dejaron_de_venir"]}
    reales = sum(1 for n in dejaron if n % 11 == 0 and n < 300)
    assert reales >= 3 and reales >= len(dejaron) / 2       # con la demo chica hay algún hueco casual


def test_sin_clientes_identificados_explica_como_activar(retail_demo):
    ctx = motor.contexto_sistema(1)
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("UPDATE tickets SET cliente = NULL")
    r = cliente().get("/retail/api/clientes").json()
    assert r["activo"] is False and "DNI" in r["como_activar"]
