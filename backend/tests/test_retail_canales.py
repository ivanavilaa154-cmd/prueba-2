"""Retail · Fase 2, sección 12: canales, ganancia real, stock unificado y sobreventa."""
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


def test_ganancia_real_descuenta_comisiones_envios_medios_y_publicidad(retail_demo):
    """Criterio de aceptación: la ganancia por canal descuenta comisiones y envíos."""
    r = cliente().get("/retail/api/canales/resultado?periodo=mes").json()
    ml = next(f for f in r["filas"] if f["plataforma"] == "Mercado Libre")
    d, h = r["periodo"]["desde"], r["periodo"]["hasta"]
    cc = _q("SELECT sum(comision) c, sum(envio) e FROM costos_canal cc JOIN plataformas p ON p.id = cc.plataforma_id "
            "WHERE p.tipo='mercadolibre' AND cc.ticket_id IS NOT NULL AND cc.fecha BETWEEN %s AND %s", (d, h))[0]
    assert Decimal(ml["comision"]) == cc["c"] and Decimal(ml["envio"]) == cc["e"] and Decimal(ml["publicidad"]) > 0
    esperado = Decimal(ml["ventas"]) - Decimal(ml["costo_mercaderia"]) - cc["c"] - cc["e"] - Decimal(ml["costo_medios"]) - Decimal(ml["publicidad"])
    assert Decimal(ml["ganancia_real"]) == esperado
    assert ml["margen_real"] < ml["margen_bruto"]
    fisico = [f for f in r["filas"] if f["codigo"] == "fisico"]
    assert fisico and all(Decimal(f["comision"]) == 0 and Decimal(f["costo_medios"]) > 0 for f in fisico)
    assert abs(sum(f["participacion"] for f in r["filas"]) - 1) < 1e-6
    # Publicidad: se prorratea por los días del período (el mes del demo va del 1 al 24 de septiembre).
    pub_mes = _q("SELECT publicidad FROM costos_canal cc JOIN plataformas p ON p.id = cc.plataforma_id WHERE p.tipo='mercadolibre' "
                 "AND cc.ticket_id IS NULL AND cc.fecha = %s", (d,))[0]["publicidad"]
    assert abs(Decimal(ml["publicidad"]) - pub_mes * 24 / 30) < Decimal("0.02")
    assert cliente("encargado.norte@norte.demo").get("/retail/api/canales/resultado").status_code == 200


def test_stock_unificado_y_sobreventa(retail_demo):
    r = cliente().get("/retail/api/canales/stock").json()
    caso = demo.CASOS["sobreventa"]
    codigos = {s["codigo_interno"] for s in r["sobreventa"]}
    assert set(caso["productos"]) <= codigos
    for s in r["sobreventa"]:
        assert Decimal(s["stock_publicado"]) > Decimal(s["disponible"])
        assert Decimal(s["disponible"]) == max(Decimal(0), Decimal(s["stock"]) - Decimal(s["reservado"]))
    # Los pedidos online pendientes reservan stock en la sucursal que despacha.
    pend = _q("SELECT l.producto_id, sum(l.cantidad) q FROM pedidos_online po JOIN tickets_lineas l ON l.ticket_id = po.ticket_id "
              "WHERE po.estado='pendiente' GROUP BY 1")
    centro = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Centro'")[0]["id"]
    for p in pend:
        assert _q("SELECT reservado FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (p["producto_id"], centro))[0]["reservado"] == p["q"]
    assert len(r["pendientes"]) == len({p["ticket_id"] for p in _q("SELECT ticket_id FROM pedidos_online WHERE estado='pendiente'")})
    # Aviso de sobreventa por plataforma.
    a = _q("SELECT titulo, prioridad FROM alertas WHERE tipo='sobreventa'")
    assert len(a) == 2 and all(x["prioridad"] == "urgente" for x in a)


def test_metricas_de_ecommerce(retail_demo):
    r = cliente().get("/retail/api/canales/ecommerce").json()
    t = r["totales"]
    assert t["pedidos"] > 0 and t["cancelados"] > 0 and t["reclamos"] > 0
    assert r["despacho"] and all(0 <= d["en_24h"] <= 1 and d["horas_promedio"] > 0 for d in r["despacho"])
    ml = next(d for d in r["despacho"] if d["plataforma"] == "Mercado Libre")
    tn = next(d for d in r["despacho"] if d["plataforma"] == "Tiendanube")
    assert ml["horas_promedio"] < tn["horas_promedio"]
    publicados = {p["producto_id"] for p in _q("SELECT producto_id FROM publicaciones WHERE activa")}
    assert r["no_publicados"] and all(p["producto_id"] not in publicados for p in r["no_publicados"])
    # Los pedidos cancelados no cuentan como venta.
    canc = _q("SELECT t.estado FROM pedidos_online po JOIN tickets t ON t.id = po.ticket_id WHERE po.estado='cancelado'")
    assert canc and all(x["estado"] == "anulado" for x in canc)


def test_alerta_de_meta_en_riesgo(retail_demo):
    norte = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Norte'")[0]["id"]
    ctx = motor.contexto_sistema(1)
    from conftest import DEMO_HOY
    from app.retail import alertas
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("UPDATE metas SET valor = valor * 3 WHERE ubicacion_id=%s AND metrica='ventas'", (norte,))
    alertas.generar(1, DEMO_HOY)
    a = {x["ubicacion_id"]: x for x in _q("SELECT titulo, ubicacion_id FROM alertas WHERE tipo='meta'")}
    assert norte in a and "de la meta" in a[norte]["titulo"] and "Salta Norte" in a[norte]["titulo"]
