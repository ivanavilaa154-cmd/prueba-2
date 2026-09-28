"""Retail · Fase 2, sección 13.4: línea base y reporte mensual de mejora."""
from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.retail import api_impacto, db, motor
from app.retail.semilla import CLAVE_DEMO
from conftest import DEMO_HOY


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def test_linea_base_y_meses(retail_demo):
    r = cliente().get("/retail/api/impacto").json()
    b = r["linea_base"]
    # La demo guarda su línea base (el comercio «se conectó» hace tres meses); sin ese parámetro son las primeras 4 semanas.
    assert b["desde"] == str(DEMO_HOY - timedelta(days=90)) and b["hasta"] == str(DEMO_HOY - timedelta(days=63))
    assert Decimal(b["ventas"]) > 0 and 0 <= b["tasa_faltantes"] < 1 and 0 < b["margen"] < 1
    assert r["meses"] and r["meses"][0]["mes"] == str(DEMO_HOY.replace(day=1))
    for m in r["meses"]:
        mj = m["mejora"]
        v = Decimal(m["ventas"])
        assert abs(Decimal(mj["merma_reducida"]) - Decimal(str(b["merma_pct"] - m["merma_pct"])) * v) < Decimal("0.02")
        assert Decimal(mj["plata_liberada"]) == Decimal(b["plata_parada"]) - Decimal(m["plata_parada"])
        assert Decimal(mj["total"]) == Decimal(mj["faltantes_evitados"]) + Decimal(mj["merma_reducida"]) + Decimal(mj["margen_recuperado"])
    assert cliente("caja.centro@norte.demo").get("/retail/api/impacto").status_code == 403


def test_ventas_perdidas_con_calculo_manual(retail_demo):
    """Un producto sin stock 2 de 10 días que vende $ 100 por día con stock pierde $ 200."""
    ctx = motor.contexto_sistema(1)
    d, h = DEMO_HOY - timedelta(days=200), DEMO_HOY - timedelta(days=191)
    with db.transaccion(ctx) as conn:
        total = api_impacto._indicadores(conn, d, h)
    fila = _q("""WITH sd AS (SELECT producto_id, ubicacion_id, count(*) FILTER (WHERE NOT con_stock) sin, count(*) FILTER (WHERE con_stock) con
                             FROM stock_diario WHERE fecha BETWEEN %s AND %s GROUP BY 1, 2),
                      v AS (SELECT producto_id, ubicacion_id, sum(facturacion) f FROM agg_producto_ubicacion_dia WHERE fecha BETWEEN %s AND %s GROUP BY 1, 2)
                 SELECT sd.sin, sd.con, v.f FROM sd JOIN v USING (producto_id, ubicacion_id)""", (d, h, d, h))
    manual = sum((Decimal(x["sin"]) * x["f"] / x["con"] for x in fila if x["con"]), Decimal(0))
    assert abs(Decimal(total["ventas_perdidas"]) - manual) < Decimal("0.05")


def test_sin_parametro_la_base_son_las_primeras_4_semanas(retail_demo):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM parametros WHERE clave='linea_base'")
        d, h = api_impacto.linea_base(conn)
    primera = _q("SELECT min(fecha) f FROM agg_producto_ubicacion_dia")[0]["f"]
    assert (d, h) == (primera, primera + timedelta(days=27))
