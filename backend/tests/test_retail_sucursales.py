"""Retail · Fase 2, sección 8: multisucursal."""
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
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


def test_matriz_producto_por_sucursal(retail_demo):
    r = cliente().get("/retail/api/sucursales/matriz").json()
    nombres = [u["nombre"] for u in r["ubicaciones"]]
    assert len(nombres) == 4 and r["ubicaciones"][-1]["tipo"] == "deposito"
    ventas = [Decimal(p["venta_diaria"]) for p in r["productos"]]
    assert ventas == sorted(ventas, reverse=True)
    fila = r["productos"][0]
    m = _q("SELECT ubicacion_id, semaforo, dias_stock FROM metricas_producto_actual WHERE producto_id=%s", (fila["producto_id"],))
    for x in m:
        assert fila["celdas"][str(x["ubicacion_id"])]["semaforo"] == x["semaforo"]
    problemas = cliente().get("/retail/api/sucursales/matriz?solo_problemas=true").json()["productos"]
    assert problemas and all(p["rojos"] > 0 for p in problemas)
    # El encargado solo ve sus sucursales en la matriz.
    enc = cliente("encargado.norte@norte.demo").get("/retail/api/sucursales/matriz").json()
    assert [u["nombre"] for u in enc["ubicaciones"]] == ["Salta Norte"]
    assert all(set(p["celdas"]) <= {str(enc["ubicaciones"][0]["id"])} for p in enc["productos"])


def test_comparativo_cuadra_con_las_ventas(retail_demo):
    r = cliente().get("/retail/api/sucursales/comparativo?periodo=mes").json()
    assert len(r["sucursales"]) == 3
    d, h = r["periodo"]["desde"], r["periodo"]["hasta"]
    total = _q("SELECT sum(facturacion) f FROM agg_producto_ubicacion_dia WHERE fecha BETWEEN %s AND %s", (d, h))[0]["f"]
    assert sum(Decimal(s["ventas"]) for s in r["sucursales"]) == total
    for s in r["sucursales"]:
        assert Decimal(s["ticket_promedio"]) == (Decimal(s["ventas"]) / s["tickets"]).quantize(Decimal("0.01"))
    # Un cajero no ve costos: sin ganancia ni plata parada.
    assert cliente("encargado.norte@norte.demo").get("/retail/api/sucursales/comparativo").json()["sucursales"][0]["ganancia"] is not None


def test_faltantes_sospechosos(retail_demo):
    """Una sucursal con mucha más merma que las demás queda marcada."""
    jujuy = _q("SELECT id FROM ubicaciones WHERE nombre='San Salvador de Jujuy'")[0]["id"]
    pid = _q("SELECT producto_id FROM producto_proveedores WHERE costo > 100 ORDER BY producto_id LIMIT 1")[0]["producto_id"]
    ctx = motor.contexto_sistema(1)
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO movimientos_stock (org_id, producto_id, ubicacion_id, fecha, tipo, cantidad, costo_unitario, motivo) "
                    "VALUES (1, %s, %s, %s::date - 1 + time '12:00', 'merma', -400, 5000, 'faltante')", (pid, jujuy, DEMO_HOY))
    r = cliente().get("/retail/api/sucursales/comparativo?periodo=mes").json()
    marcadas = [s["ubicacion"] for s in r["sucursales"] if s["sospechoso"]]
    assert marcadas == ["San Salvador de Jujuy"]


def test_producto_en_cada_sucursal_y_precios_distintos(retail_demo):
    c = cliente()
    pid = _q("SELECT producto_id FROM metricas_producto_actual ORDER BY pronostico_diario DESC LIMIT 1")[0]["producto_id"]
    r = c.get(f"/retail/api/sucursales/producto/{pid}").json()
    assert len(r["sucursales"]) == 3 and max(s["vs_mejor"] for s in r["sucursales"]) == 1.0
    assert all(s["puesto"] >= 1 for s in r["sucursales"] if s["unidades_30d"])
    caso = demo.CASOS["precio_distinto"]
    distintos = c.get("/retail/api/sucursales/precios-distintos").json()["productos"]
    assert {p["codigo_interno"] for p in distintos} == set(caso["productos"])
    assert all(p["ubicacion"] == caso["ubicacion"] and abs(p["diferencia"] - caso["recargo"]) < 0.02 for p in distintos)
    # Ese precio de la sucursal es el que se muestra en el producto por sucursal.
    otro = next(p for p in distintos)
    prs = {s["ubicacion"]: Decimal(s["precio"]) for s in c.get(f"/retail/api/sucursales/producto/{otro['producto_id']}").json()["sucursales"]}
    assert prs[caso["ubicacion"]] == Decimal(otro["precio_sucursal"])


def test_ajustes_auditados(retail_demo):
    c = cliente("encargado.norte@norte.demo")
    norte = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Norte'")[0]["id"]
    pid = _q("SELECT producto_id FROM stock_actual WHERE ubicacion_id=%s AND cantidad > 5 ORDER BY producto_id LIMIT 1", (norte,))[0]["producto_id"]
    assert c.post("/retail/api/merma", json={"producto_id": pid, "ubicacion_id": norte, "cantidad": 2, "motivo": "rotura", "detalle": "se cayó"}).status_code == 200
    a = c.get("/retail/api/sucursales/ajustes").json()
    assert a[0]["usuario"] == "Lucía Cruz" and a[0]["motivo"] == "rotura: se cayó" and Decimal(a[0]["cantidad"]) == Decimal("-2")
    assert all(x["ubicacion"] == "Salta Norte" for x in a)
