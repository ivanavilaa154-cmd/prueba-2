"""Liquidaciones activas: proyección de vaciado, escalera de rebajas, exhibición, control con foto y precio cartel vs caja."""
from datetime import datetime, timedelta

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
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else None


def _crear(c, hoy, escalera=(0.35, 0.5), exhibicion="gondola"):
    f = _q("""SELECT s.producto_id, s.ubicacion_id FROM stock_actual s JOIN ubicaciones u ON u.id = s.ubicacion_id
              JOIN metricas_producto_actual m ON m.producto_id = s.producto_id AND m.ubicacion_id = s.ubicacion_id
              WHERE u.tipo <> 'deposito' AND s.cantidad > 60 * m.pronostico_diario AND m.pronostico_diario > 0.3 ORDER BY s.cantidad DESC LIMIT 1""")[0]
    r = c.post("/retail/api/ofertas", json={"producto_id": f["producto_id"], "ubicacion_id": f["ubicacion_id"], "descuento": 0.2,
                                             "hasta": str(hoy + timedelta(days=10)), "origen": "sobrestock", "exhibicion": exhibicion,
                                             "escalera": list(escalera), "capacidad_exhibicion": 12})
    assert r.status_code == 200, r.text
    return r.json()["id"], f


def test_liquidacion_sugiere_bajar_escalon_y_controlar(retail_demo):
    from conftest import DEMO_HOY
    c = cliente()
    pid, f = _crear(c, DEMO_HOY)
    r = c.get("/retail/api/liquidaciones").json()
    fila = next(x for x in r["filas"] if x["id"] == pid)
    assert fila["stock"] > 0 and fila["stock_inicial"] and fila["exhibicion"] == "gondola"
    assert fila["accion"] == "controlar" and fila["ejecucion"] == "sin_control"          # recién creada: falta controlar el armado
    # Control con foto: armada, cartel y precio OK.
    foto = ("puntera.jpg", b"\xff\xd8\xff" + b"0" * 100, "image/jpeg")
    ok = c.post(f"/retail/api/liquidaciones/{pid}/control", data={"ubicacion_id": f["ubicacion_id"], "armada": "true", "cartel": "true",
                                                                    "precio_ok": "true"}, files={"foto": foto})
    assert ok.status_code == 200 and ok.json()["foto"]
    assert c.get(f"/retail/api/liquidaciones/fotos/{ok.json()['foto']}").status_code == 200
    assert c.get("/retail/api/liquidaciones/fotos/..%2F..%2Fsecreto").status_code == 404
    fila = next(x for x in c.get("/retail/api/liquidaciones").json()["filas"] if x["id"] == pid)
    assert fila["ejecucion"] == "ok"
    assert not fila["llega_a_tiempo"] and fila["accion"] == "bajar_escalon" and fila["escalon_siguiente"] == 0.35   # mucho stock, poco tiempo
    b = c.post(f"/retail/api/liquidaciones/{pid}/escalon")
    assert b.status_code == 200 and b.json()["descuento"] == 0.35 and "caja" in b.json()["mensaje"]
    c.post(f"/retail/api/liquidaciones/{pid}/escalon")
    assert c.post(f"/retail/api/liquidaciones/{pid}/escalon").status_code == 409                    # no quedan escalones
    fila = next(x for x in c.get("/retail/api/liquidaciones").json()["filas"] if x["id"] == pid)
    assert fila["accion"] == "mover"                                                                  # en góndola: pasarla a puntera
    assert c.post(f"/retail/api/liquidaciones/{pid}/control", data={"ubicacion_id": f["ubicacion_id"], "tipo": "exhibicion",
                                                                      "exhibicion": "puntera"}).status_code == 200
    fila = next(x for x in c.get("/retail/api/liquidaciones").json()["filas"] if x["id"] == pid)
    assert fila["exhibicion"] == "puntera" and fila["reponer_cada_horas"] and fila["accion"] in ("revisar", "reponer")


def test_diferencia_de_precio_cartel_vs_caja(retail_demo):
    from conftest import DEMO_HOY
    c = cliente()
    pid, f = _crear(c, DEMO_HOY)
    c.post(f"/retail/api/liquidaciones/{pid}/control", data={"ubicacion_id": f["ubicacion_id"], "armada": "true", "cartel": "true", "precio_ok": "true"})
    # Un ticket posterior a la oferta cobró el precio normal en vez del de oferta.
    t = _q("""INSERT INTO tickets (org_id, ubicacion_id, canal_id, fecha_hora, total, numero_externo, origen)
              VALUES (1, %s, (SELECT id FROM canales WHERE org_id=1 AND codigo='fisico'), %s, 9999, 'T-DIF-1', 'prueba') RETURNING id""",
           (f["ubicacion_id"], datetime.now().astimezone() + timedelta(minutes=1)))[0]["id"]
    precio = _q("SELECT (parametros->>'precio_normal')::numeric p FROM promociones WHERE id=%s", (pid,))[0]["p"]
    _q("""INSERT INTO tickets_lineas (org_id, ticket_id, ubicacion_id, fecha, producto_id, cantidad, precio_lista, precio_cobrado, descuento)
          VALUES (1, %s, %s, %s, %s, 1, %s, %s, 0)""", (t, f["ubicacion_id"], DEMO_HOY, f["producto_id"], precio, precio))
    fila = next(x for x in c.get("/retail/api/liquidaciones").json()["filas"] if x["id"] == pid)
    assert fila["diferencias_precio"] == 1 and fila["accion"] == "corregir_precio"
    assert cliente("caja.centro@norte.demo").post(f"/retail/api/liquidaciones/{pid}/escalon").status_code == 403
