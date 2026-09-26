"""Tablero: cada indicador contra una cuenta hecha directo sobre la base demo, y permisos por rol."""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.analisis import tablero
from app.erp import conector
from app.permisos import obtener_usuario

HOY = date(2026, 9, 24)  # la base demo de las pruebas se genera con esta fecha


def _kpis(seccion):
    return {k["nombre"]: k for k in seccion["kpis"]}


def _uno(sql, url):
    return conector.consultar(sql, url=url)["filas"][0][0]


@pytest.fixture
def dueno(base_demo_config):
    return tablero.tablero(obtener_usuario("u1"), 30, hoy=HOY)


def test_ventas_contra_sql_directo(dueno, base_demo):
    desde = (HOY - timedelta(days=29)).isoformat()
    base = f"FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id WHERE v.anulada = 0 AND v.fecha >= '{desde}' AND v.fecha <= '{HOY}'"
    venta = _uno(f"SELECT SUM(l.cantidad * l.precio_unitario) {base}", base_demo)
    costo = _uno(f"SELECT SUM(l.cantidad * l.costo_unitario) {base}", base_demo)
    pedidos = _uno(f"SELECT COUNT(DISTINCT v.id) {base}", base_demo)
    k = _kpis(dueno["ventas"])
    assert k["Venta neta"]["valor"] == round(venta, 2)
    assert k["Margen bruto"]["valor"] == round(venta - costo, 2)
    assert k["Pedidos"]["valor"] == pedidos
    assert k["Pedido promedio"]["valor"] == round(venta / pedidos, 2)
    assert k["Clientes activos"]["valor"] == _uno(f"SELECT COUNT(DISTINCT v.cliente_id) {base}", base_demo)


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


def test_finanzas_contra_sql_directo(dueno, base_demo):
    total = _uno("SELECT SUM(saldo) FROM cxc WHERE saldo <> 0", base_demo)
    vencida = _uno(f"SELECT SUM(saldo) FROM cxc WHERE saldo <> 0 AND fecha_vencimiento < '{HOY}'", base_demo)
    k = _kpis(dueno["finanzas"])
    assert k["Deuda de clientes"]["valor"] == round(total, 2)
    assert k["Deuda vencida"]["valor"] == round(vencida, 2)
    assert round(sum(t["saldo"] for t in dueno["finanzas"]["antiguedad"]), 2) == round(total, 2)
    assert dueno["finanzas"]["antiguedad"][0]["tramo"] == "Al día"


def test_vendedor_ve_solo_su_cartera(base_demo_config, dueno):
    laura = tablero.tablero(obtener_usuario("u2"), 30, hoy=HOY)
    assert _kpis(laura["ventas"])["Venta neta"]["valor"] < _kpis(dueno["ventas"])["Venta neta"]["valor"]
    assert _kpis(laura["ventas"])["Clientes activos"]["valor"] <= 4
    assert _kpis(laura["finanzas"])["Deuda de clientes"]["valor"] < _kpis(dueno["finanzas"])["Deuda de clientes"]["valor"]
    inv = set(_kpis(laura["inventario"]))
    assert {"Quiebres de stock", "Venta perdida por quiebres"} <= inv
    assert not inv & {"Días de inventario", "Rotación anual", "Por quebrar", "Merma"}  # sin cobertura engañosa ni datos de depósito
    assert {v["vendedor"] for v in laura["ventas"]["vendedores"]} == {"Vendedor 1"}  # no ve la tabla de vendedores


def test_compras_no_ve_finanzas(base_demo_config):
    martin = tablero.tablero(obtener_usuario("u3"), 30, hoy=HOY)
    assert martin["finanzas"]["sin_acceso"] and "Valor del inventario" in _kpis(martin["inventario"])


def test_sin_ventas_recientes_usa_el_ultimo_dia(base_demo_config):
    t = tablero.tablero(obtener_usuario("u1"), 30, hoy=HOY + timedelta(days=200))
    assert t["fecha_ajustada"] and t["fecha"] <= HOY.isoformat()


def test_nunca_inventa_lo_que_falta(base_demo, tmp_path, monkeypatch):
    import shutil
    import sqlite3

    from app import config

    copia = tmp_path / "sin_caja.db"
    shutil.copy(base_demo.replace("sqlite:///", ""), copia)
    con = sqlite3.connect(copia)
    con.execute("DELETE FROM cuentas_bancarias")
    con.execute("DELETE FROM cheques")
    con.commit()
    con.close()
    monkeypatch.setattr(config, "ERP_URL", f"sqlite:///{copia}")
    t = tablero.tablero(obtener_usuario("u1"), 30, hoy=HOY)
    faltan = " ".join(n["indicador"] + n["motivo"] for n in t["no_disponibles"]).lower()
    assert "caja" in faltan and "cheques" in faltan
    nombres = set(_kpis(t["finanzas"]))
    assert "Caja y bancos" not in nombres and "Cheques en cartera" not in nombres
    conector.olvidar_conexiones()


def test_indicadores_nuevos_contra_sql_directo(dueno, base_demo):
    k = {**_kpis(dueno["ventas"]), **_kpis(dueno["inventario"]), **_kpis(dueno["finanzas"])}
    assert k["Caja y bancos"]["valor"] == _uno("SELECT SUM(saldo) FROM cuentas_bancarias", base_demo)
    assert k["Deuda con proveedores"]["valor"] == round(_uno("SELECT SUM(saldo) FROM cxp WHERE saldo <> 0", base_demo) or 0, 2)
    desde = (HOY - timedelta(days=29)).isoformat()
    d90 = (HOY - timedelta(days=89)).isoformat()
    gastos = (_uno(f"SELECT SUM(importe) FROM gastos WHERE fecha >= '{d90}' AND fecha <= '{HOY}'", base_demo) or 0) / 90 * 30
    assert gastos > 0
    assert k["Gastos operativos"]["valor"] == round(gastos, 2)
    assert k["Resultado operativo (aprox. EBITDA)"]["valor"] == round(k["Margen bruto"]["valor"] - gastos, 2)
    imp = _uno(f"""SELECT SUM(l.impuestos) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
                   WHERE v.anulada = 0 AND v.fecha >= '{desde}' AND v.fecha <= '{HOY}'""", base_demo)
    assert k["Venta con impuestos"]["valor"] == round(k["Venta neta"]["valor"] + imp, 2)
    assert k["Cheques rechazados"]["estado"] == "critico"
    assert "Merma" in k and "Por vencer en 30 días" in k and "Pedidos completos y a tiempo" in k


def test_flujo_de_caja(dueno):
    panel = next(p for p in dueno["finanzas"]["paneles_extra"] if p["titulo"].startswith("Flujo de caja"))
    assert len(panel["filas"]) == 13
    k = _kpis(dueno["finanzas"])
    assert k["Punto más bajo de caja (13 semanas)"]["valor"] == min(f[4] for f in panel["filas"])


def test_endpoint(base_demo_config):
    from app import main

    api = TestClient(main.app)
    assert api.get("/tablero", params={"usuario_id": "u1", "dias": 30}).status_code == 200
    assert api.get("/tablero", params={"usuario_id": "u1", "dias": 45}).status_code == 400
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
    antes = tablero.tablero(obtener_usuario("u1"), 30, hoy=HOY)  # sin actualizar: no falla
    assert _kpis(antes["ventas"])["Venta neta"]["valor"] == 275.0
    conector.olvidar_conexiones()

    cambios = modelo.actualizar_base(ruta)
    assert "tabla cheques" in cambios and "ventas_lineas.impuestos" in cambios and "clientes.canal" in cambios
    assert modelo.actualizar_base(ruta) == []  # la segunda vez no hay nada que cambiar
    con = sqlite3.connect(ruta)
    assert con.execute("SELECT razon_social FROM clientes").fetchall() == [("Almacén Viejo",)]  # los datos siguen
    con.close()
    despues = tablero.tablero(obtener_usuario("u1"), 30, hoy=HOY)
    assert _kpis(despues["ventas"])["Venta neta"]["valor"] == 275.0
    assert any("caja" in n["indicador"].lower() for n in despues["no_disponibles"])

    monkeypatch.setattr(fuente, "URL_DEMO", f"sqlite:///{ruta}")
    fuente.usar("demo")  # al elegir una fuente también se actualiza
    conector.olvidar_conexiones()
