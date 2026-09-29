"""Predicciones · parte B: venta por sucursal y canal, curva anual, afluencia y personal, simulador de promoción, flujo de caja y
riesgo de cobro (contra la demo)."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.retail import db, motor
from app.retail.semilla import CLAVE_DEMO


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def test_venta_por_sucursal_canal_y_dia(retail_demo):
    r = cliente().get("/retail/api/pronosticos/ventas", params={"dias": 14}).json()
    assert r["series"] and len(r["total"]) == 14
    canales = {s["canal"] for s in r["series"]}
    assert "fisico" in canales and "ecommerce" in canales
    for s in r["series"]:
        assert s["minimo"] <= s["total"] <= s["maximo"] and len(s["dias"]) == 14
        # Lo pronosticado para 14 días está en el orden de lo vendido en los últimos 28 (la mitad, con margen amplio).
        assert 0.25 * s["real_28"] <= s["total"] <= 1.2 * s["real_28"]
    assert abs(sum(d["pronostico"] for d in r["total"]) - r["total_periodo"]) < 1


def test_curva_anual(retail_demo):
    r = cliente().get("/retail/api/pronosticos/anual").json()
    assert len(r["proyectado"]) == 12 and r["real"] and r["estacionalidad"]
    assert all(p["proyectado"] > 0 for p in r["proyectado"])


def test_afluencia_y_personal(retail_demo):
    r = cliente().get("/retail/api/tienda/afluencia", params={"dias": 7}).json()
    assert len(r["dias"]) == 7 and r["capacidad_caja_hora"] > 0
    d = next(x for x in r["dias"] if x["tickets"] > 0)
    assert d["turnos"] and all(t["cajas_max"] >= 1 for t in d["turnos"])
    for h in d["horas"]:
        assert h["maximo"] >= h["tickets"] and h["cajas_pico"] >= h["cajas"]
    # Sábado vende más que el lunes en la demo (factor de semana).
    por_dia = {x["fecha"]: x["tickets"] for x in r["dias"]}
    sab = [v for f, v in por_dia.items() if date.fromisoformat(f).weekday() == 5]
    lun = [v for f, v in por_dia.items() if date.fromisoformat(f).weekday() == 0]
    assert sab and lun and sab[0] > lun[0]


def test_simulador_de_promocion(retail_demo):
    pid = _q("""SELECT m.producto_id FROM metricas_producto_actual m JOIN ubicaciones u ON u.id = m.ubicacion_id WHERE u.tipo <> 'deposito'
                GROUP BY 1 HAVING sum(m.pronostico_diario) > 1 AND sum(m.disponible) > 15 * sum(m.pronostico_diario)
                ORDER BY sum(m.pronostico_diario) DESC LIMIT 1""")[0]["producto_id"]
    c = cliente()
    chica = c.post("/retail/api/promociones/simular", json={"producto_id": pid, "descuento": 0.1, "dias": 7}).json()
    grande = c.post("/retail/api/promociones/simular", json={"producto_id": pid, "descuento": 0.6, "dias": 7}).json()
    assert chica["unidades_con_promo"] > chica["unidades_sin_promo"] and grande["unidades_extra"] >= chica["unidades_extra"]
    assert chica["precio_oferta"] == round(chica["precio"] * 0.9, 2) and not chica["limitado_por_stock"]
    assert grande["neto"] < chica["neto"]                       # regalar margen no conviene
    assert grande["recomendacion"] and chica["recomendacion"]
    assert cliente("caja.centro@norte.demo").post("/retail/api/promociones/simular",
                                                      json={"producto_id": pid, "descuento": 0.1, "dias": 7}).status_code == 403


def test_flujo_de_caja(retail_demo):
    c = cliente()
    assert c.put("/retail/api/finanzas/flujo/config", json={"saldo_inicial": 5000000, "minimo_aceptable": 1000000,
                                                          "gastos_fijos": [{"concepto": "Sueldos", "monto": 4000000, "dia": 5}]}).status_code == 200
    r = c.get("/retail/api/finanzas/flujo", params={"dias": 60}).json()
    assert r["configurado"] and len(r["linea"]) == 60
    t = r["totales"]
    assert t["cobro_ventas"] > 0 and t["compras_futuras"] > 0 and t["gastos_fijos"] >= 4000000
    primero = r["linea"][0]
    assert abs(primero["saldo"] - (5000000 + primero["entradas"] - primero["salidas"])) < 1
    assert all(x["saldo_min"] <= x["saldo"] <= x["saldo_max"] for x in r["linea"])
    assert c.put("/retail/api/finanzas/flujo/config", json={"saldo_inicial": 1, "gastos_fijos": [{"concepto": "X", "monto": 1, "dia": 40}]}).status_code == 400


def test_riesgo_de_cobro_marca_a_los_morosos(retail_demo):
    from app.retail import demo
    r = cliente().get("/retail/api/cuentas-corrientes/riesgo").json()
    assert r["clientes"]
    por_nombre = {c["nombre"]: c for c in r["clientes"]}
    morosos = [por_nombre[n]["prob_no_cobro"] for n in demo.MOROSOS if n in por_nombre]
    otros = [c["prob_no_cobro"] for c in r["clientes"] if c["nombre"] not in demo.MOROSOS]
    assert morosos and max(otros) < min(morosos) or sum(morosos) / len(morosos) > sum(otros) / len(otros) + 0.2
    assert all(0 <= c["prob_no_cobro"] <= 1 and c["accion"] for c in r["clientes"])
