"""Tablero: cada indicador contra una cuenta hecha directo sobre la base demo, y permisos por rol."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.analisis import tablero
from app.erp import conector
from app.permisos import obtener_usuario

HOY = date(2026, 9, 24)  # la base demo de las pruebas se genera con esta fecha
MES = "2026-09-01"  # mes en curso: del 1 al 24


def _kpis(seccion):
    """Indicadores de un pilar; en Finanzas, de todos sus grupos."""
    kpis = seccion.get("kpis", []) + [k for g in seccion.get("grupos", []) for k in g["kpis"]]
    return {k["nombre"]: k for k in kpis}


def _grupo(seccion, titulo):
    return next(g for g in seccion["grupos"] if g["titulo"] == titulo)


def _panel(grupo, inicio):
    return next(p for p in grupo["paneles"] if p["titulo"].startswith(inicio))


def _uno(sql, url):
    return conector.consultar(sql, url=url)["filas"][0][0]


def _venta(url, desde, hasta):
    base = f"FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id WHERE v.anulada = 0 AND v.fecha >= '{desde}' AND v.fecha <= '{hasta}'"
    return (_uno(f"SELECT SUM(l.cantidad * l.precio_unitario) {base}", url), _uno(f"SELECT SUM(l.cantidad * l.costo_unitario) {base}", url))


@pytest.fixture
def dueno(base_demo_config):
    return tablero.tablero(obtener_usuario("u1"), hoy=HOY)


def test_periodo_mensual():
    p = tablero.Periodo.crear("2026-09", HOY)
    assert (p.desde, p.hasta, p.ant_desde, p.ant_hasta, p.en_curso) == (
        date(2026, 9, 1), HOY, date(2026, 8, 1), date(2026, 8, 24), True)
    assert p.describir().startswith("Septiembre 2026 (en curso, del 1 al 24)")
    p = tablero.Periodo.crear("2026-03", HOY)  # mes cerrado: se compara con el mes anterior completo
    assert (p.desde, p.hasta, p.ant_desde, p.ant_hasta, p.en_curso) == (
        date(2026, 3, 1), date(2026, 3, 31), date(2026, 2, 1), date(2026, 2, 28), False)
    assert tablero.nombre_mes("2026-10") == "octubre 2026"


def test_meses_para_elegir(dueno):
    meses = dueno["meses"]
    assert meses[0] == {"valor": "2026-09", "nombre": "septiembre 2026", "en_curso": True, "con_ventas": True}
    assert [m["valor"] for m in meses[:3]] == ["2026-09", "2026-08", "2026-07"] and dueno["mes"] == "2026-09"


def test_ventas_contra_sql_directo(dueno, base_demo):
    base = f"FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id WHERE v.anulada = 0 AND v.fecha >= '{MES}' AND v.fecha <= '{HOY}'"
    venta, costo = _venta(base_demo, MES, HOY)
    venta_a, _ = _venta(base_demo, "2026-08-01", "2026-08-24")
    pedidos = _uno(f"SELECT COUNT(DISTINCT v.id) {base}", base_demo)
    k = _kpis(dueno["ventas"])
    assert k["Venta neta"]["valor"] == round(venta, 2)
    assert k["Venta neta"]["variacion"] == round((venta - venta_a) / venta_a, 4)
    assert k["Margen bruto"]["valor"] == round(venta - costo, 2)
    assert k["Pedidos"]["valor"] == pedidos
    assert k["Clientes activos"]["valor"] == _uno(f"SELECT COUNT(DISTINCT v.cliente_id) {base}", base_demo)


def test_mes_cerrado(base_demo_config, base_demo):
    t = tablero.tablero(obtener_usuario("u1"), "2026-08", hoy=HOY)
    venta, _ = _venta(base_demo, "2026-08-01", "2026-08-31")
    venta_a, _ = _venta(base_demo, "2026-07-01", "2026-07-31")
    k = _kpis(t["ventas"])
    assert t["mes"] == "2026-08" and not t["en_curso"]
    assert k["Venta neta"]["valor"] == round(venta, 2) and k["Venta neta"]["variacion"] == round((venta - venta_a) / venta_a, 4)
    serie = t["ventas"]["serie_mensual"]
    assert serie[-1]["mes"] == "2026-08" and serie[-1]["elegido"]
    assert "stock" in t["inventario"]["nota"].lower()  # el stock es el de hoy


def test_mes_invalido_usa_el_mas_reciente(base_demo_config):
    assert tablero.tablero(obtener_usuario("u1"), "2019-01", hoy=HOY)["mes"] == "2026-09"
    lejos = tablero.tablero(obtener_usuario("u1"), None, hoy=HOY + timedelta(days=200))
    assert lejos["mes"] == "2026-09"  # sin ventas recientes: el último mes con ventas


def test_serie_mensual_sin_meses_cortados(dueno):
    serie = dueno["ventas"]["serie_mensual"]
    assert len(serie) == 12 and serie[0]["mes"] == "2025-10" and serie[-1]["mes"] == "2026-09"
    assert serie[-1]["en_curso"] and not any(m["en_curso"] for m in serie[:-1])


def test_cliente_que_dejo_de_comprar(dueno):
    # En la demo el cliente 9 (Autoservicio El Ahorro) deja de comprar hace 70 días.
    riesgo = dueno["ventas"]["clientes_en_riesgo"]
    assert [r["cliente"] for r in riesgo] == ["Autoservicio El Ahorro"] and riesgo[0]["dias_sin_comprar"] >= 60
    assert _kpis(dueno["ventas"])["Venta en riesgo"]["estado"] == "alerta"


def test_inventario_contra_sql_directo(dueno, base_demo):
    valor = _uno("SELECT SUM(s.cantidad * p.costo) FROM stock s JOIN productos p ON p.id = s.producto_id", base_demo)
    k = _kpis(dueno["inventario"])
    assert k["Valor del inventario"]["valor"] == round(valor, 2)
    sin_stock = {f[0] for f in conector.consultar(
        "SELECT p.descripcion FROM productos p JOIN stock s ON s.producto_id = p.id GROUP BY p.id, p.descripcion HAVING SUM(s.cantidad) = 0",
        url=base_demo)["filas"]}
    assert {q["producto"] for q in dueno["inventario"]["quiebres"]} <= sin_stock
    assert k["Quiebres de stock"]["valor"] == len(dueno["inventario"]["quiebres"])


def test_finanzas_grupos(dueno):
    titulos = [g["titulo"] for g in dueno["finanzas"]["grupos"]]
    assert titulos == ["Resultados del mes", "Cobranzas y crédito", "Pagos a proveedores", "Tesorería",
                       "Capital de trabajo y salud financiera", "Impuestos", "Controles y alertas"]


def test_resultados_contra_sql_directo(dueno, base_demo):
    g = _grupo(dueno["finanzas"], "Resultados del mes")
    k = {x["nombre"]: x for x in g["kpis"]}
    venta, costo = _venta(base_demo, MES, HOY)
    assert k["Ventas netas"]["valor"] == round(venta, 2) and k["Costo de ventas"]["valor"] == round(costo, 2)
    # Septiembre todavía no tiene gastos asentados: se estiman con el promedio de junio a agosto, llevado a 24 días
    tres = _uno("SELECT SUM(importe) FROM gastos WHERE fecha >= '2026-06-01' AND fecha <= '2026-08-31'", base_demo)
    estimado = tres / 3 * 24 / 30
    assert k["Gastos operativos"]["valor"] == round(estimado, 2) and "estimado" in k["Gastos operativos"]["nota"]
    assert k["Resultado operativo"]["valor"] == round(venta - costo - estimado, 2)
    margen_pct = (venta - costo) / venta
    assert k["Punto de equilibrio"]["valor"] == round(estimado / margen_pct, 2)
    assert "Crecimiento real (vs. año anterior)" not in k  # la demo no tiene septiembre 2025 completo
    estado = _panel(g, "Estado de resultados")
    assert len(estado["filas"]) == 12 and estado["filas"][0][0].startswith("2026-09")


def test_resultados_mes_cerrado_usa_gastos_reales(base_demo_config, base_demo):
    t = tablero.tablero(obtener_usuario("u1"), "2026-08", hoy=HOY)
    k = {x["nombre"]: x for x in _grupo(t["finanzas"], "Resultados del mes")["kpis"]}
    agosto = _uno("SELECT SUM(importe) FROM gastos WHERE fecha >= '2026-08-01' AND fecha <= '2026-08-31'", base_demo)
    assert k["Gastos operativos"]["valor"] == round(agosto, 2) and k["Gastos operativos"]["nota"] == "del mes"


def test_cobranzas_contra_sql_directo(dueno, base_demo):
    g = _grupo(dueno["finanzas"], "Cobranzas y crédito")
    k = {x["nombre"]: x for x in g["kpis"]}
    total = _uno("SELECT SUM(saldo) FROM cxc WHERE saldo <> 0", base_demo)
    vencida = _uno(f"SELECT SUM(saldo) FROM cxc WHERE saldo <> 0 AND fecha_vencimiento < '{HOY}'", base_demo)
    assert k["Deuda de clientes"]["valor"] == round(total, 2) and k["Deuda vencida"]["valor"] == round(vencida, 2)
    assert round(sum(t["saldo"] for t in dueno["finanzas"]["antiguedad"]), 2) == round(total, 2)
    # Efectividad: de lo emitido antes del mes, pendiente al inicio y vencido a la fecha, cuánto se cobró en el mes
    candidatas = f"""FROM cxc WHERE fecha_emision < '{MES}' AND fecha_vencimiento <= '{HOY}' AND (fecha_cobro IS NULL OR fecha_cobro >= '{MES}')"""
    cobrado = _uno(f"SELECT SUM(importe) {candidatas} AND fecha_cobro <= '{HOY}'", base_demo)
    assert k["Efectividad de cobranza"]["valor"] == round(cobrado / _uno(f"SELECT SUM(importe) {candidatas}", base_demo), 4)
    assert k["Cobrado en el mes"]["valor"] == round(_uno(f"SELECT SUM(importe) FROM cobranzas WHERE fecha >= '{MES}' AND fecha <= '{HOY}'", base_demo), 2)
    agenda = _panel(g, "Agenda de cobranza")
    assert agenda["filas"] and all(f[2] <= (HOY + timedelta(days=7)).isoformat() for f in agenda["filas"])
    assert k["Cheques rechazados"]["estado"] == "critico"


def test_pagos_tesoreria_y_capital(dueno, base_demo):
    k = _kpis(dueno["finanzas"])
    cxp = _uno("SELECT SUM(saldo) FROM cxp WHERE saldo <> 0", base_demo)
    caja = _uno("SELECT SUM(saldo) FROM cuentas_bancarias", base_demo)
    assert k["Deuda con proveedores"]["valor"] == round(cxp, 2) and k["Caja y bancos"]["valor"] == caja
    flujo = _panel(_grupo(dueno["finanzas"], "Tesorería"), "Flujo de caja")
    assert len(flujo["filas"]) == 13 and k["Punto más bajo (13 semanas)"]["valor"] == min(f[4] for f in flujo["filas"])
    capital = {x[0]: x[1] for x in _panel(_grupo(dueno["finanzas"], "Capital de trabajo y salud financiera"), "Composición")["filas"]}
    activo = capital["Caja y bancos"] + capital["Cuentas a cobrar"] + capital["Inventario a costo"]
    pasivo = -(capital["Cuentas a pagar"] + capital["Impuestos pendientes"] + capital["Cuotas de préstamos (12 meses)"])
    assert k["Liquidez corriente"]["valor"] == round(activo / pasivo, 2)
    assert k["Capital de trabajo"]["valor"] == round(activo - pasivo, 2)
    assert k["Ciclo de conversión de caja"]["valor"] is not None


def test_controles(dueno):
    alertas = _panel(_grupo(dueno["finanzas"], "Controles y alertas"), "Alertas")["filas"]
    assert any("Cheques rechazados" in a[1] for a in alertas)


def test_vendedor_ve_solo_su_cartera(base_demo_config, dueno):
    laura = tablero.tablero(obtener_usuario("u2"), hoy=HOY)
    assert _kpis(laura["ventas"])["Venta neta"]["valor"] < _kpis(dueno["ventas"])["Venta neta"]["valor"]
    assert _kpis(laura["ventas"])["Clientes activos"]["valor"] <= 4
    assert _kpis(laura["finanzas"])["Deuda de clientes"]["valor"] < _kpis(dueno["finanzas"])["Deuda de clientes"]["valor"]
    grupos = {g["titulo"] for g in laura["finanzas"]["grupos"]}
    assert "Resultados del mes" not in grupos and "Tesorería" not in grupos  # los resultados y la caja son de la empresa
    inv = set(_kpis(laura["inventario"]))
    assert {"Quiebres de stock", "Venta perdida por quiebres"} <= inv
    assert not inv & {"Días de inventario", "Rotación anual", "Por quebrar", "Merma"}  # sin cobertura engañosa ni datos de depósito
    assert {v["vendedor"] for v in laura["ventas"]["vendedores"]} == {"Vendedor 1"}  # no ve la tabla de vendedores


def test_compras_no_ve_finanzas(base_demo_config):
    martin = tablero.tablero(obtener_usuario("u3"), hoy=HOY)
    assert martin["finanzas"]["sin_acceso"] and "Valor del inventario" in _kpis(martin["inventario"])


def test_nunca_inventa_lo_que_falta(base_demo, tmp_path, monkeypatch):
    import shutil
    import sqlite3

    from app import config

    copia = tmp_path / "sin_caja.db"
    shutil.copy(base_demo.replace("sqlite:///", ""), copia)
    con = sqlite3.connect(copia)
    con.execute("DELETE FROM cuentas_bancarias")
    con.execute("DELETE FROM cheques")
    con.execute("DELETE FROM gastos")
    con.commit()
    con.close()
    monkeypatch.setattr(config, "ERP_URL", f"sqlite:///{copia}")
    t = tablero.tablero(obtener_usuario("u1"), hoy=HOY)
    faltan = " ".join(n["indicador"] + n["motivo"] for n in t["no_disponibles"]).lower()
    assert "caja" in faltan and "cheques" in faltan and "ebitda" in faltan
    nombres = set(_kpis(t["finanzas"]))
    assert not nombres & {"Caja y bancos", "Cheques en cartera", "Resultado operativo", "Gastos operativos"}
    assert "Ventas netas" in nombres  # el estado de resultados muestra lo que sí hay
    conector.olvidar_conexiones()


def test_indicadores_nuevos_contra_sql_directo(dueno, base_demo):
    k = {**_kpis(dueno["ventas"]), **_kpis(dueno["inventario"])}
    imp = _uno(f"""SELECT SUM(l.impuestos) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
                   WHERE v.anulada = 0 AND v.fecha >= '{MES}' AND v.fecha <= '{HOY}'""", base_demo)
    assert k["Venta con impuestos"]["valor"] == round(k["Venta neta"]["valor"] + imp, 2)
    assert "Merma" in k and "Por vencer en 30 días" in k and "Pedidos completos y a tiempo" in k


def test_endpoint(base_demo_config):
    from app import main

    api = TestClient(main.app)
    assert api.get("/tablero", params={"usuario_id": "u1"}).status_code == 200
    assert api.get("/tablero", params={"usuario_id": "u1", "mes": "2026-08"}).json()["mes"] == "2026-08"
    assert api.get("/tablero", params={"usuario_id": "u1", "mes": "agosto"}).status_code == 400
    assert api.get("/tablero", params={"usuario_id": "nadie"}).status_code == 403


def test_diccionario_igual_al_modelo():
    """Cada tabla y campo del modelo está descripto en el diccionario, y nada más."""
    import sqlite3

    from app import config
    from app.erp import modelo

    con = sqlite3.connect(":memory:")
    con.executescript(modelo.ESQUEMA)
    tablas = {t: {c[1] for c in con.execute(f"PRAGMA table_info({t})")}
              for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    dicc = config.diccionario()["tablas"]
    assert set(dicc) == set(tablas) == {t for ts in modelo.PILARES.values() for t in ts}
    for tabla, campos in tablas.items():
        assert set(dicc[tabla]["campos"]) == campos, tabla
    assert set(modelo.MINIMOS) == set(tablas)


def test_cobertura(base_demo_config):
    from app.analisis import cobertura

    c = cobertura.cobertura()
    por_tabla = {t["tabla"]: t for p in c["pilares"] for t in p["tablas"]}
    assert por_tabla["clientes"]["filas"] == 12 and por_tabla["clientes"]["estado"] in ("completa", "buena")
    assert por_tabla["visitas"]["estado"] == "vacia"
    assert "nombre_fantasia" in por_tabla["clientes"]["campos_vacios"]
    assert [p["pilar"] for p in c["pilares"]] == ["Ventas", "Inventario", "Finanzas"]


VIEJO = """
CREATE TABLE sucursales (id INTEGER PRIMARY KEY, nombre TEXT);
CREATE TABLE clientes (id INTEGER PRIMARY KEY, razon_social TEXT, vendedor_id INTEGER);
CREATE TABLE productos (id INTEGER PRIMARY KEY, descripcion TEXT, costo REAL, precio REAL);
CREATE TABLE stock (producto_id INTEGER, sucursal_id INTEGER, cantidad REAL);
CREATE TABLE ventas (id INTEGER PRIMARY KEY, fecha TEXT, cliente_id INTEGER, vendedor_id INTEGER, sucursal_id INTEGER, anulada INTEGER DEFAULT 0);
CREATE TABLE ventas_lineas (venta_id INTEGER, producto_id INTEGER, cantidad REAL, precio_unitario REAL, costo_unitario REAL);
CREATE TABLE cxc (id INTEGER PRIMARY KEY, cliente_id INTEGER, fecha_emision TEXT, fecha_vencimiento TEXT, fecha_cobro TEXT, importe REAL, saldo REAL);
INSERT INTO clientes VALUES (1, 'Almacén Viejo', 1);
INSERT INTO productos VALUES (1, 'Arroz', 40, 55);
INSERT INTO stock VALUES (1, 1, 10);
INSERT INTO ventas VALUES (1, '2026-09-20', 1, 1, 1, 0);
INSERT INTO ventas_lineas VALUES (1, 1, 5, 55, 40);
INSERT INTO cxc VALUES (1, 1, '2026-09-20', '2026-10-20', NULL, 275, 275);
"""


def test_base_de_version_anterior(tmp_path, monkeypatch):
    """Una base con el modelo viejo no rompe el tablero, y se actualiza sin perder datos."""
    import sqlite3

    from app import config
    from app.erp import fuente, modelo

    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)
    con.executescript(VIEJO)
    con.close()
    monkeypatch.setattr(config, "ERP_URL", f"sqlite:///{ruta}")
    antes = tablero.tablero(obtener_usuario("u1"), hoy=HOY)  # sin actualizar: no falla
    assert _kpis(antes["ventas"])["Venta neta"]["valor"] == 275.0
    conector.olvidar_conexiones()

    cambios = modelo.actualizar_base(ruta)
    assert "tabla cheques" in cambios and "ventas_lineas.impuestos" in cambios and "clientes.canal" in cambios
    assert modelo.actualizar_base(ruta) == []  # la segunda vez no hay nada que cambiar
    con = sqlite3.connect(ruta)
    assert con.execute("SELECT razon_social FROM clientes").fetchall() == [("Almacén Viejo",)]  # los datos siguen
    con.close()
    despues = tablero.tablero(obtener_usuario("u1"), hoy=HOY)
    assert _kpis(despues["ventas"])["Venta neta"]["valor"] == 275.0
    assert any("caja" in n["indicador"].lower() for n in despues["no_disponibles"])

    monkeypatch.setattr(fuente, "URL_DEMO", f"sqlite:///{ruta}")
    fuente.usar("demo")  # al elegir una fuente también se actualiza
    conector.olvidar_conexiones()
