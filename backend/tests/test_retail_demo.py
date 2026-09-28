"""Retail · parte 2: la demo se carga completa, coherente y con los casos conocidos; el cálculo nocturno los detecta."""
from datetime import timedelta

from app.retail import db, demo, motor
from app.retail import calculos as C

from datetime import date

DEMO_HOY = date(2026, 9, 24)


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def test_demo_cargada_y_coherente(retail_demo):
    assert retail_demo["cargada"] and retail_demo["tickets"] > 5000
    assert _q("SELECT count(*) c FROM proveedores")[0]["c"] == 12
    assert _q("SELECT count(*) c FROM proveedores WHERE dias_visita = '{}'")[0]["c"] == 1
    assert _q("SELECT count(*) c FROM ubicaciones")[0]["c"] == 4
    assert _q("SELECT count(*) c FROM indice_precios")[0]["c"] >= 4
    # Los importes son numeric, nunca float
    tipos = _q("SELECT data_type FROM information_schema.columns WHERE table_name IN ('tickets','tickets_lineas','precios','pagos') "
               "AND column_name IN ('total','precio_cobrado','precio','monto')")
    assert {t["data_type"] for t in tipos} == {"numeric"}
    # El total de cada ticket coincide con sus líneas
    distintos = _q("SELECT count(*) c FROM tickets t WHERE abs(t.total - (SELECT coalesce(sum(precio_cobrado*cantidad),0) "
                   "FROM tickets_lineas l WHERE l.ticket_id=t.id)) > 0.05")
    assert distintos[0]["c"] == 0
    # Online con comisiones, en Salta Centro
    online = _q("SELECT count(*) c FROM tickets t JOIN canales c ON c.id=t.canal_id WHERE c.codigo='ecommerce'")[0]["c"]
    assert online > 50 and _q("SELECT count(*) c FROM costos_canal WHERE comision > 0")[0]["c"] > 50


def test_agregados_cuadran_con_los_tickets(retail_demo):
    a = _q("SELECT sum(facturacion) f FROM agg_producto_ubicacion_dia")[0]["f"]
    t = _q("SELECT sum(total) f FROM tickets WHERE estado <> 'anulado'")[0]["f"]
    assert abs(a - t) < 1


def test_faltante_conocido_excluido_de_la_vpd(retail_demo):
    """Criterio 1 de la sección 17: la VPD excluye los días sin stock (producto con faltante conocido)."""
    caso = demo.CASOS["faltante_conocido"]
    f = _q("""SELECT m.vpd, m.producto_id, m.ubicacion_id, m.explicacion FROM metricas_producto_actual m
              JOIN productos p ON p.id=m.producto_id JOIN ubicaciones u ON u.id=m.ubicacion_id
              WHERE p.codigo_interno=%s AND u.nombre=%s""", (caso["producto"], caso["ubicacion"]))[0]
    periodos = _q("SELECT desde, hasta FROM periodos_sin_stock WHERE producto_id=%s AND ubicacion_id=%s", (f["producto_id"], f["ubicacion_id"]))
    dias_sin = set()
    for p in periodos:
        d = p["desde"]
        while d <= (p["hasta"] or DEMO_HOY - timedelta(days=1)):
            dias_sin.add(d)
            d += timedelta(days=1)
    esperado_sin = {DEMO_HOY - timedelta(days=k) for k in range(caso["hasta_dias"] + 1, caso["desde_dias"] + 1)}
    assert esperado_sin <= dias_sin, "el período sin stock conocido tiene que estar registrado"
    # Cuenta manual: unidades de los últimos 28 días ÷ días con stock
    ventas = {r["fecha"]: float(r["u"]) for r in _q("SELECT fecha, sum(unidades) u FROM agg_producto_ubicacion_dia WHERE producto_id=%s "
                                                   "AND ubicacion_id=%s GROUP BY fecha", (f["producto_id"], f["ubicacion_id"]))}
    dias = [DEMO_HOY - timedelta(days=i) for i in range(1, 29)]
    con = [d for d in dias if d not in dias_sin]
    manual = sum(ventas.get(d, 0) for d in con) / len(con)
    assert float(f["vpd"]) == __import__("pytest").approx(manual, rel=1e-3)
    assert f["explicacion"]["dias_sin_stock"] >= len(esperado_sin)
    ingenua = sum(ventas.get(d, 0) for d in dias) / 28
    assert float(f["vpd"]) > ingenua     # sin excluir, la venta diaria quedaría subestimada


def test_casos_de_borde_en_las_metricas(retail_demo):
    def metrica(codigo, ubic):
        return _q("""SELECT m.* FROM metricas_producto_actual m JOIN productos p ON p.id=m.producto_id JOIN ubicaciones u ON u.id=m.ubicacion_id
                     WHERE p.codigo_interno=%s AND u.nombre=%s""", (codigo, ubic))[0]
    fantasma = metrica(demo.CASOS["stock_fantasma"]["producto"], demo.CASOS["stock_fantasma"]["ubicacion"])
    assert float(fantasma["disponible"]) == 24 and fantasma["dias_sin_venta"] >= 6
    assert C.posible_stock_fantasma(float(fantasma["disponible"]), float(fantasma["vpd"]), fantasma["dias_sin_venta"])
    negativo = metrica(demo.CASOS["stock_negativo"]["producto"], demo.CASOS["stock_negativo"]["ubicacion"])
    assert float(negativo["disponible"]) < 0 and negativo["explicacion"]["stock_negativo"]
    # se calcula como 0 disponible: lo sugerido cubre el horizonte completo más lo que falta por llegar
    assert negativo["explicacion"]["necesidad"] >= negativo["explicacion"]["pronostico_horizonte"] - negativo["explicacion"]["pedidos_abiertos"] - 0.01
    sin_costo = _q("SELECT m.capital, m.explicacion FROM metricas_producto_actual m JOIN productos p ON p.id=m.producto_id "
                   "WHERE p.codigo_interno=%s LIMIT 1", (demo.CASOS["sin_costo"]["producto"],))[0]
    assert sin_costo["capital"] is None and sin_costo["explicacion"]["sin_costo"]
    nuevo = _q("SELECT m.confianza FROM metricas_producto_actual m JOIN productos p ON p.id=m.producto_id "
               "JOIN ubicaciones u ON u.id=m.ubicacion_id WHERE p.codigo_interno=%s AND u.tipo<>'deposito'",
               (demo.CASOS["producto_nuevo"]["producto"],))
    assert nuevo and all(n["confianza"] == "baja" for n in nuevo)
    sin_dias = _q("SELECT m.explicacion FROM metricas_producto_actual m JOIN proveedores pr ON pr.id=m.proveedor_id "
                  "WHERE pr.dias_visita='{}' LIMIT 1")
    assert sin_dias and "no tiene días de visita" in sin_dias[0]["explicacion"]["supuesto_proveedor"]


def test_abc_de_la_demo(retail_demo):
    clases = {r["clase_abc"]: r["c"] for r in _q("SELECT clase_abc, count(*) c FROM productos GROUP BY 1")}
    assert set(clases) == {"A", "B", "C"} and clases["A"] < clases["C"]
    assert _q("SELECT count(DISTINCT mes) c FROM historial_abc")[0]["c"] >= 4


def test_cajero_anomalo_tiene_mas_anulaciones(retail_demo):
    caso = demo.CASOS["cajero_anomalo"]
    tasas = _q("""SELECT t.cajero, count(*) FILTER (WHERE t.estado='anulado')::numeric / count(*) tasa FROM tickets t
                  JOIN ubicaciones u ON u.id=t.ubicacion_id WHERE u.nombre=%s AND t.cajero IS NOT NULL GROUP BY 1""", (caso["ubicacion"],))
    tasa = {t["cajero"]: float(t["tasa"]) for t in tasas}
    otros = [v for k, v in tasa.items() if k != caso["cajero"]]
    assert tasa[caso["cajero"]] > 3 * max(otros)


def test_encargado_no_ve_metricas_de_otras_sucursales(retail_demo):
    from app.retail import sesiones
    u = _q("SELECT id FROM usuarios WHERE email='encargado.norte@norte.demo'")[0]["id"]
    ctx = sesiones.contexto_de_sesion({"usuario_id": u, "org_activa": None})
    with db.transaccion(ctx) as conn:
        nombres = {r["nombre"] for r in db.filas(conn, "SELECT DISTINCT u.nombre FROM metricas_producto_actual m JOIN ubicaciones u ON u.id=m.ubicacion_id")}
        tickets = db.filas(conn, "SELECT DISTINCT ubicacion_id FROM tickets")
    assert nombres == {"Salta Norte"} and len(tickets) == 1


def test_recalculo_incremental(retail_demo):
    r = motor.recalcular(1, hoy=DEMO_HOY, tipo="incremental")
    assert r["metricas"] > 0 and _q("SELECT count(*) c FROM ejecuciones_calculo WHERE estado='ok'")[0]["c"] >= 2
