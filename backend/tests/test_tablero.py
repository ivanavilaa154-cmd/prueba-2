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
    assert set(_kpis(laura["inventario"])) == {"Quiebres de stock", "Venta perdida por quiebres"}  # sin cobertura engañosa
    assert {v["vendedor"] for v in laura["ventas"]["vendedores"]} == {"Vendedor 1"}  # no ve la tabla de vendedores


def test_compras_no_ve_finanzas(base_demo_config):
    martin = tablero.tablero(obtener_usuario("u3"), 30, hoy=HOY)
    assert martin["finanzas"]["sin_acceso"] and "Valor del inventario" in _kpis(martin["inventario"])


def test_sin_ventas_recientes_usa_el_ultimo_dia(base_demo_config):
    t = tablero.tablero(obtener_usuario("u1"), 30, hoy=HOY + timedelta(days=200))
    assert t["fecha_ajustada"] and t["fecha"] <= HOY.isoformat()


def test_nunca_inventa_lo_que_falta(dueno):
    assert any("caja" in n["indicador"].lower() for n in dueno["no_disponibles"])


def test_endpoint(base_demo_config):
    from app import main

    api = TestClient(main.app)
    assert api.get("/tablero", params={"usuario_id": "u1", "dias": 30}).status_code == 200
    assert api.get("/tablero", params={"usuario_id": "u1", "dias": 45}).status_code == 400
    assert api.get("/tablero", params={"usuario_id": "nadie"}).status_code == 403
