"""Predicciones de distribución y preventa (33 a 39) sobre la base demo del Panel ERP, con permisos por rol."""
from datetime import date, timedelta

from app.analisis import distribucion
from app.erp import conector
from app.permisos import obtener_usuario


def _grupo(r, numero):
    return next(g for g in r["grupos"] if g["titulo"].startswith(numero))


def _kpi(g, nombre):
    return next(k["valor"] for k in g["kpis"] if k["nombre"] == nombre)


def test_calcula_los_siete_bloques(base_demo_config):
    r = distribucion.distribucion(obtener_usuario("u1"))
    assert [g["titulo"][:2] for g in r["grupos"]] == ["33", "34", "35", "36", "37", "38", "39"]
    for g in r["grupos"]:
        assert g["kpis"] and g["paneles"], g["titulo"]


def test_pedido_sugerido_trae_rango_y_montos_coherentes(base_demo_config):
    g = _grupo(distribucion.distribucion(obtener_usuario("u1")), "33")
    filas = g["paneles"][0]["filas"]
    assert filas
    for cliente, zona, proxima, ciclo, texto, monto, rango in filas:
        assert ciclo >= 1 and monto > 0 and " × " in texto
        minimo, maximo = (int(x.replace(".", "")) for x in rango.split(" a "))
        assert minimo <= monto <= maximo


def test_entregas_fallidas_coincide_con_la_base(base_demo_config):
    g = _grupo(distribucion.distribucion(obtener_usuario("u1")), "36")
    zonas = next(p for p in g["paneles"] if p["titulo"] == "Por zona y día")["filas"]
    for nombre, n, fallidas, tasa in zonas:
        assert 0 <= fallidas <= n and abs(tasa - fallidas / n) < 1e-3
    # «Llegaron tarde» (últimos 30 días) es la misma cuenta hecha directo en la base.
    ultima = conector.consultar("SELECT MAX(fecha) FROM ventas WHERE anulada = 0")["filas"][0][0]
    hoy = date.fromisoformat(ultima) + timedelta(days=1)
    tarde = conector.consultar(f"""SELECT COUNT(*) FROM pedidos WHERE fecha_entrega > fecha_entrega_prometida
        AND fecha_entrega_prometida >= '{hoy - timedelta(days=30)}' AND fecha_entrega_prometida < '{hoy}'
        AND fecha_pedido >= '{hoy - timedelta(days=120)}'""")["filas"][0][0]
    assert _kpi(g, "Llegaron tarde") == tarde


def test_el_vendedor_ve_solo_su_cartera(base_demo_config):
    dueno = distribucion.distribucion(obtener_usuario("u1"))
    vendedor = distribucion.distribucion(obtener_usuario("u2"))
    propios = {f[0] for f in conector.consultar(
        "SELECT COALESCE(nombre_fantasia, razon_social) FROM clientes WHERE vendedor_id = 1")["filas"]}
    sugeridos = {f[0] for f in _grupo(vendedor, "33")["paneles"][0]["filas"]}
    assert sugeridos and sugeridos <= propios
    assert _kpi(_grupo(vendedor, "33"), "Clientes con pedido sugerido") < _kpi(_grupo(dueno, "33"), "Clientes con pedido sugerido")


def test_stock_en_el_canal_y_potencial(base_demo_config):
    r = distribucion.distribucion(obtener_usuario("u1"))
    canal = _grupo(r, "39")
    assert _kpi(canal, "Unidades en el canal") > 0 and _kpi(canal, "Días de canal") > 0
    pot = _grupo(r, "38")["paneles"][0]["filas"]
    assert all(f[5] > 0 and f[4] > 0 for f in pot)
