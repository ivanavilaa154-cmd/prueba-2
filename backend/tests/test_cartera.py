"""Filtro por fila: un vendedor solo ve los datos de su cartera, lo pida como lo pida."""
import json

import pytest

from app.chat import herramientas
from app.erp import conector
from app.permisos import AccesoDenegado, Usuario, obtener_usuario, preparar_consulta, tablas_de_sql

CARTERA_LAURA = {1, 3, 4, 12}  # clientes con vendedor_id = 1 en la base demo


@pytest.fixture
def laura():
    return obtener_usuario("u2")


def _ids(resultado, columna=0):
    return {fila[columna] for fila in resultado["filas"]}


def _sin_filtro(sql, base):
    return conector.consultar(sql, max_filas=100_000, url=base)


def test_ve_solo_sus_clientes(base_demo, laura):
    r = conector.consultar("SELECT id FROM clientes", url=base_demo, usuario=laura)
    assert _ids(r) == CARTERA_LAURA


@pytest.mark.parametrize("sql", [
    "SELECT c.id FROM clientes c",
    "SELECT id FROM CLIENTES",
    "SELECT id FROM main.clientes",
    "SELECT x.id FROM productos p, clientes x",
    "SELECT id FROM clientes WHERE vendedor_id = 2 OR 1 = 1",
    "SELECT id FROM (SELECT * FROM clientes) t",
    "SELECT id FROM clientes UNION SELECT id FROM clientes",
    "WITH mios AS (SELECT * FROM clientes) SELECT id FROM mios",
    "SELECT DISTINCT v.cliente_id FROM ventas v",
    "SELECT DISTINCT cliente_id FROM cxc WHERE cliente_id IN (SELECT id FROM clientes)",
])
def test_no_se_puede_esquivar(base_demo, laura, sql):
    r = conector.consultar(sql, max_filas=100_000, url=base_demo, usuario=laura)
    assert r["cantidad"] > 0 and _ids(r) <= CARTERA_LAURA


def test_totales_de_ventas_y_deuda_coinciden_con_su_cartera(base_demo, laura):
    cartera = ",".join(map(str, sorted(CARTERA_LAURA)))
    consultas = {
        "SELECT COUNT(*) FROM ventas": f"SELECT COUNT(*) FROM ventas WHERE cliente_id IN ({cartera})",
        "SELECT ROUND(SUM(saldo), 2) FROM cxc": f"SELECT ROUND(SUM(saldo), 2) FROM cxc WHERE cliente_id IN ({cartera})",
        "SELECT COUNT(*) FROM ventas_lineas":
            f"SELECT COUNT(*) FROM ventas_lineas l JOIN ventas v ON v.id = l.venta_id WHERE v.cliente_id IN ({cartera})",
    }
    for como_laura, esperado in consultas.items():
        filtrado = conector.consultar(como_laura, url=base_demo, usuario=laura)["filas"][0][0]
        assert filtrado == _sin_filtro(esperado, base_demo)["filas"][0][0], como_laura
    total = _sin_filtro("SELECT COUNT(*) FROM ventas", base_demo)["filas"][0][0]
    assert conector.consultar("SELECT COUNT(*) FROM ventas", url=base_demo, usuario=laura)["filas"][0][0] < total


def test_lineas_sin_join_solo_de_su_cartera(base_demo, laura):
    r = conector.consultar("SELECT DISTINCT venta_id FROM ventas_lineas", max_filas=100_000,
                           url=base_demo, usuario=laura)
    ventas = _sin_filtro("SELECT id, cliente_id FROM ventas", base_demo)["filas"]
    cliente_de = dict(ventas)
    assert r["cantidad"] > 0 and {cliente_de[v] for v in _ids(r)} <= CARTERA_LAURA


def test_catalogo_sin_filtro(base_demo, laura):
    r = conector.consultar("SELECT COUNT(*) FROM productos", url=base_demo, usuario=laura)
    assert r["filas"][0][0] == 16  # 15 con ventas + 1 sin movimiento (caso de actividades)


def test_cte_con_nombre_de_tabla_se_rechaza(base_demo, laura):
    with pytest.raises(AccesoDenegado, match="otro nombre"):
        conector.consultar("WITH clientes AS (SELECT * FROM cxc) SELECT * FROM clientes",
                           url=base_demo, usuario=laura)


def test_tablas_fuera_del_rol_siguen_bloqueadas(base_demo, laura):
    with pytest.raises(AccesoDenegado):
        conector.consultar("SELECT * FROM proveedores", url=base_demo, usuario=laura)


def test_vendedor_sin_cartera_no_consulta(base_demo):
    sin_cartera = Usuario(id="x", nombre="Sin cartera", rol="vendedor")
    with pytest.raises(AccesoDenegado, match="cartera"):
        conector.consultar("SELECT id FROM clientes", url=base_demo, usuario=sin_cartera)


def test_dueno_ve_todo(base_demo):
    r = conector.consultar("SELECT COUNT(*) FROM clientes", url=base_demo, usuario=obtener_usuario("u1"))
    assert r["filas"][0][0] == 12


def test_coma_ya_no_esquiva_permisos_de_tabla():
    compras = obtener_usuario("u3")
    assert tablas_de_sql("SELECT * FROM productos, cxc") == {"productos", "cxc"}
    with pytest.raises(AccesoDenegado):
        preparar_consulta(compras, "SELECT * FROM productos p, cxc c")


def test_reescritura_en_sql_server(laura):
    sql = preparar_consulta(laura, "SELECT TOP 5 c.razon_social FROM dbo.clientes AS c", "tsql")
    assert "vendedor_id = 1" in sql and "dbo.clientes" in sql and "TOP 5" in sql


def test_herramienta_del_chat_aplica_la_cartera(base_demo_config, laura):
    salida = json.loads(herramientas.ejecutar("consultar_erp", {"sql": "SELECT id FROM clientes", "motivo": "t"}, laura))
    assert {fila[0] for fila in salida["filas"]} == CARTERA_LAURA
