"""Retail · Fase 2: rentabilidad del inventario (10.6), medios de pago y fiado (10.8), proveedores (10.11), metas (10.13)."""
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.retail import api_analisis as A
from app.retail import calculos as C
from app.retail import db, demo, motor
from app.retail.semilla import CLAVE_DEMO
from conftest import DEMO_HOY


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def test_rentabilidad_con_calculo_manual(retail_demo):
    c = cliente()
    r = c.get("/retail/api/ventas/rentabilidad?nivel=ubicacion&dias=90").json()
    assert {f["nombre"] for f in r["filas"]} >= {"Salta Centro", "Salta Norte", "San Salvador de Jujuy"}
    f = next(x for x in r["filas"] if x["nombre"] == "Salta Norte")
    norte = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Norte'")[0]["id"]
    g = _q("SELECT sum(ganancia) g, sum(costo) c FROM agg_producto_ubicacion_dia WHERE ubicacion_id=%s AND fecha > %s AND fecha <= %s",
           (norte, DEMO_HOY - timedelta(days=90), DEMO_HOY))[0]
    inv = _q("""SELECT sum(s.p * coalesce((SELECT costo FROM producto_proveedores pp WHERE pp.producto_id = s.producto_id ORDER BY principal DESC LIMIT 1), 0)) i
                FROM (SELECT producto_id, avg(greatest(stock_cierre, 0)) p FROM stock_diario WHERE ubicacion_id=%s AND fecha > %s AND fecha <= %s GROUP BY 1) s""",
             (norte, DEMO_HOY - timedelta(days=90), DEMO_HOY))[0]["i"]
    assert abs(Decimal(f["inventario_promedio"]) - inv) < Decimal("1")
    assert abs(f["gmroi"] - float(g["g"] / inv)) < 0.01
    assert abs(f["rotacion"] - float(g["c"] / inv * 365 / 90)) < 0.02
    assert abs(f["dias_inventario"] - 365 / f["rotacion"]) < 0.5
    por_prod = c.get("/retail/api/ventas/rentabilidad?nivel=producto").json()
    assert len(por_prod["filas"]) > 50
    assert c.get("/retail/api/ventas/rentabilidad?nivel=otra").status_code == 400


def test_medios_de_pago_y_costo_real(retail_demo):
    c = cliente()
    r = c.get("/retail/api/ventas/medios?periodo=mes").json()
    assert abs(sum(m["participacion"] for m in r["medios"]) - 1) < 1e-6
    cred = next(m for m in r["medios"] if m["medio"] == "credito")
    cfg = {m[0]: m for m in demo.MEDIOS}["credito"]
    esperado = Decimal(cred["monto"]) * Decimal(str(cfg[2])) + Decimal(cred["monto"]) * Decimal("0.03") / 30 * cfg[3]
    assert abs(Decimal(cred["costo"]) - esperado) < Decimal("0.05")
    efectivo = next(m for m in r["medios"] if m["medio"] == "efectivo")
    assert Decimal(efectivo["costo"]) == 0
    assert r["por_ubicacion"] and r["por_canal"]
    # Cambiar la comisión cambia el costo.
    assert c.put("/retail/api/config/medios", json=[{"medio": "efectivo", "comision": 0.01, "acreditacion_dias": 0}]).status_code == 200
    r2 = c.get("/retail/api/ventas/medios?periodo=mes").json()
    ef2 = next(m for m in r2["medios"] if m["medio"] == "efectivo")
    assert abs(Decimal(ef2["costo"]) - Decimal(ef2["monto"]) * Decimal("0.01")) < Decimal("0.05")
    assert cliente("encargado.norte@norte.demo").put("/retail/api/config/medios", json=[]).status_code == 403


def test_fiado_saldos_y_antiguedad(retail_demo):
    r = cliente().get("/retail/api/cuentas-corrientes").json()
    assert r["clientes"]
    morosos = [c for c in r["clientes"] if c["nombre"] in demo.MOROSOS]
    assert morosos and all(Decimal(c["vencido"]) > 0 for c in morosos)
    assert r["clientes"][0]["nombre"] in demo.MOROSOS               # los de más deuda vencida primero
    for c in r["clientes"]:
        assert Decimal(c["saldo"]) == sum(Decimal(v) for v in c["tramos"].values())
    total = _q("SELECT sum(monto) s FROM cuentas_clientes")[0]["s"]
    assert Decimal(r["total"]) == total


def test_fiado_primero_se_pagan_las_compras_viejas():
    hoy = date(2026, 9, 24)

    class Conn:
        pass
    movs = [{"id": 1, "nombre": "X", "identificador": "1", "fecha": date(2026, 6, 1), "tipo": "compra", "monto": Decimal(100), "vencimiento": date(2026, 7, 1)},
            {"id": 1, "nombre": "X", "identificador": "1", "fecha": date(2026, 9, 1), "tipo": "compra", "monto": Decimal(50), "vencimiento": date(2026, 10, 1)},
            {"id": 1, "nombre": "X", "identificador": "1", "fecha": date(2026, 9, 10), "tipo": "pago", "monto": Decimal(-80), "vencimiento": None}]
    orig = A.db.filas
    A.db.filas = lambda conn, sql, params=(): movs
    try:
        s = A.saldos_fiado(Conn(), hoy)[0]
    finally:
        A.db.filas = orig
    assert s["saldo"] == Decimal(70) and s["vencido"] == Decimal(20)
    assert s["tramos"]["mas_90"] == Decimal(20) and s["tramos"]["0_30"] == Decimal(50)


def test_proveedores_servicio_costos_y_configuracion(retail_demo):
    c = cliente()
    r = c.get("/retail/api/proveedores/analisis").json()["proveedores"]
    assert len(r) == 12
    con_oc = [p for p in r if p["ordenes"]]
    assert con_oc and all(0 < p["servicio_unidades"] <= 1 and 0 <= p["puntualidad"] <= 1 for p in con_oc)
    # El demo tiene proveedores que a veces fallan: no todos entregan el 100 %.
    assert any(p["servicio_unidades"] < 1 for p in con_oc)
    aumento = next(p for p in r if p["razon_social"] == demo.CASOS["aumento_sin_remarcar"]["proveedor"])
    assert aumento["costos"] and aumento["costos"]["variacion"] > 0 and aumento["costos"]["inflacion"] is not None
    sin_dias = [p for p in r if "días de visita" in p["sin_configurar"]]
    assert sin_dias                                                  # el demo tiene un proveedor sin días
    p = sin_dias[0]
    ok = c.put(f"/retail/api/proveedores/{p['id']}", json={"dias_visita": [1, 3], "demora_entrega_dias": 2, "pedido_minimo_monto": "50000",
                                                          "email_oc": "pedidos@prov.test"})
    assert ok.status_code == 200
    p2 = next(x for x in c.get("/retail/api/proveedores/analisis").json()["proveedores"] if x["id"] == p["id"])
    assert p2["dias_visita"] == [1, 3] and "días de visita" not in p2["sin_configurar"]
    assert c.put(f"/retail/api/proveedores/{p['id']}", json={"dias_visita": [9]}).status_code == 400
    assert cliente("encargado.norte@norte.demo").put(f"/retail/api/proveedores/{p['id']}", json={}).status_code == 403


def test_proyeccion_con_patron_semanal():
    semana = [1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 0.5]
    # Del jueves 24/09 al miércoles 30/09 faltan: vie, sáb (×2), dom (×0,5), lun, mar y mié → 6,5 días de venta base.
    p = A.proyeccion(1000.0, date(2026, 9, 24), date(2026, 9, 30), semana, 1.2, 100.0)
    assert p == 1000 + 100 * (1 + 2 + 0.5 + 1 + 1 + 1)
    # Los primeros 5 días del mes llevan el factor de inicio de mes.
    p2 = A.proyeccion(0.0, date(2026, 9, 30), date(2026, 10, 2), [1.0] * 7, 1.2, 100.0)
    assert abs(p2 - 240.0) < 1e-9
    assert A.semaforo_meta(1.02) == "verde" and A.semaforo_meta(0.97) == "amarillo" and A.semaforo_meta(0.8) == "rojo" and A.semaforo_meta(None) == "gris"


def test_metas_del_demo_y_edicion(retail_demo):
    c = cliente()
    r = c.get("/retail/api/metas").json()
    assert r["dias_transcurridos"] == DEMO_HOY.day and r["dias_mes"] == 30
    total = next(f for f in r["filas"] if f["ubicacion"] == "Total")
    ventas = next(m for m in total["metricas"] if m["metrica"] == "ventas")
    suma = sum(Decimal(next(m for m in f["metricas"] if m["metrica"] == "ventas")["meta"]) for f in r["filas"] if f["ubicacion"] != "Total")
    assert Decimal(ventas["meta"]) == suma
    assert ventas["proyeccion"] > ventas["actual"] and ventas["semaforo"] in ("verde", "amarillo", "rojo")
    norte = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Norte'")[0]["id"]
    assert c.put("/retail/api/metas", json=[{"mes": str(DEMO_HOY), "ubicacion_id": norte, "metrica": "ventas", "valor": "1"}]).status_code == 200
    f = next(x for x in c.get("/retail/api/metas").json()["filas"] if x["ubicacion_id"] == norte)
    assert next(m for m in f["metricas"] if m["metrica"] == "ventas")["semaforo"] == "verde"
    assert c.put("/retail/api/metas", json=[{"mes": str(DEMO_HOY), "metrica": "margen", "valor": "28"}]).status_code == 400
    enc = cliente("encargado.norte@norte.demo")
    assert enc.put("/retail/api/metas", json=[]).status_code == 403
    assert [f["ubicacion"] for f in enc.get("/retail/api/metas").json()["filas"]] == ["Salta Norte", "Total"]


def test_alerta_de_deuda_vencida(retail_demo):
    a = _q("SELECT titulo, explicacion, impacto, accion FROM alertas WHERE tipo='fiado'")
    assert len(a) == 1 and all(m in a[0]["explicacion"] for m in demo.MOROSOS) and a[0]["impacto"] > 0
