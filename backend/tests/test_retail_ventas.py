"""Retail · parte 11: ganadores, Pareto, inflación, ticket y tráfico, control de caja (criterios de la sección 17)."""
from datetime import timedelta
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


def test_ganadores_y_comparacion(retail_demo):
    r = cliente().get("/retail/api/ventas/ganadores?periodo=mes").json()
    assert set(r["rankings"]) == set(r["criterios"])
    top = r["rankings"]["ganancia"]["mejores"]
    assert len(top) == 10 and [x["posicion"] for x in top] == list(range(1, 11))
    assert Decimal(top[0]["valor"]) >= Decimal(top[-1]["valor"])
    assert all(x["cambio"] in ("sube", "baja", "igual", "nuevo") for x in top)
    assert Decimal(r["resumen"]["facturacion"]) > 0 and Decimal(r["resumen"]["facturacion_anterior"]) > 0


def test_pareto_suma_100_y_coincide_con_calculo_manual(retail_demo):
    """Criterio: la clase ABC suma exactamente 100 % y coincide con un cálculo manual en la muestra."""
    r = cliente().get("/retail/api/ventas/pareto?criterio=ganancia").json()
    assert Decimal(r["suma_participaciones"]) == Decimal(100)
    h = retail_demo["hasta"]
    from datetime import date
    hasta = date.fromisoformat(h) - timedelta(days=1)
    manual = _q("""SELECT l.producto_id id, sum(l.precio_cobrado*l.cantidad) - sum(coalesce(l.costo_unitario,0)*l.cantidad) g
                   FROM tickets_lineas l JOIN tickets t ON t.id=l.ticket_id WHERE t.estado<>'anulado' AND l.fecha BETWEEN %s AND %s GROUP BY 1""",
                (hasta - timedelta(days=89), hasta))
    total = sum(m["g"] for m in manual if m["g"] > 0)
    acumulado = Decimal(0)
    esperado = {}
    for m in sorted([m for m in manual if m["g"] > 0], key=lambda m: (-m["g"], str(m["id"]))):
        esperado[m["id"]] = "A" if acumulado < Decimal("0.8") else "B" if acumulado < Decimal("0.95") else "C"
        acumulado += m["g"] / total
    obtenido = {i["id"]: i["clase"] for i in r["items"]}
    assert all(obtenido[k] == v for k, v in esperado.items())
    assert r["matriz_cruzada"]


def test_ventas_deflactadas_coinciden_con_calculo_manual(retail_demo):
    """Criterio: las ventas deflactadas coinciden con el cálculo manual usando el índice cargado."""
    r = cliente().get("/retail/api/ventas/inflacion").json()
    ipc = {x["periodo"].isoformat(): x["indice"] for x in _q("SELECT periodo, indice FROM indice_precios")}
    base = ipc[max(ipc)]
    for m in r["meses"]:
        manual = (Decimal(m["nominal"]) * base / ipc[m["mes"]]).quantize(Decimal("0.01"))
        assert Decimal(m["real"]) == manual
    con_var = [m for m in r["meses"] if "efectos_mensual" in m]
    for m in con_var:
        e = m["efectos_mensual"]
        assert abs(Decimal(e["efecto_precio"]) + Decimal(e["efecto_cantidad"]) - Decimal(e["variacion"])) < Decimal("0.01")


def test_ticket_y_trafico(retail_demo):
    r = cliente().get("/retail/api/ventas/ticket?periodo=7d").json()
    d = r["descomposicion"]
    assert abs(Decimal(d["efecto_clientes"]) + Decimal(d["efecto_gasto"]) - Decimal(d["variacion"])) < Decimal("0.01")
    assert r["mapa_calor"] and {x["dia"] for x in r["mapa_calor"]} <= set(range(7))
    assert {x["clave"] for x in r["por"]["ubicacion"]} == {"Salta Centro", "Salta Norte", "San Salvador de Jujuy"}


def test_control_de_caja_detecta_al_cajero_anomalo(retail_demo):
    caso = demo.CASOS["cajero_anomalo"]
    r = cliente().get("/retail/api/caja?periodo=personalizado&desde=2026-06-01&hasta=2026-09-24").json()
    marcados = {(a["cajero"], a["medida"]) for a in r["alertas"]}
    assert (caso["cajero"], "anulaciones") in marcados
    assert all(a["cajero"] == caso["cajero"] for a in r["alertas"] if a["medida"] == "anulaciones")
    assert r["detalle"] and r["por_turno"]


def test_encargado_solo_ve_su_sucursal_en_ventas(retail_demo):
    r = cliente("encargado.norte@norte.demo").get("/retail/api/ventas/ticket?periodo=7d").json()
    assert {x["clave"] for x in r["por"]["ubicacion"]} == {"Salta Norte"}
    assert cliente("caja.centro@norte.demo").get("/retail/api/ventas/ganadores").status_code == 403
