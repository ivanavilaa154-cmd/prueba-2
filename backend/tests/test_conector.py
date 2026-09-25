import pytest

from app.erp import conector
from app.erp.conector import ConsultaNoPermitida, validar_sql
from app.permisos import AccesoDenegado, obtener_usuario, verificar_acceso


@pytest.mark.parametrize("sql", [
    "SELECT * FROM clientes",
    "select count(*) from ventas where anulada = 0;",
    "WITH t AS (SELECT cliente_id, SUM(saldo) s FROM cxc GROUP BY cliente_id) SELECT * FROM t",
    "SELECT 'delete; drop' AS texto",  # palabras prohibidas dentro de un literal
    "SELECT replace(razon_social, 'a', 'b') FROM clientes",
])
def test_permite_lecturas(sql):
    assert validar_sql(sql)


@pytest.mark.parametrize("sql", [
    "DELETE FROM ventas",
    "UPDATE clientes SET limite_credito = 0",
    "DROP TABLE cxc",
    "SELECT 1; DELETE FROM ventas",
    "WITH x AS (SELECT 1) DELETE FROM ventas",
    "INSERT INTO clientes VALUES (1)",
    "PRAGMA table_info(clientes)",
    "ATTACH DATABASE 'x.db' AS x",
    "SELECT * INTO copia FROM clientes",
    "/* comentario */ UPDATE ventas SET anulada = 1",
    "",
])
def test_bloquea_escrituras(sql):
    with pytest.raises(ConsultaNoPermitida):
        validar_sql(sql)


def test_consulta_real_en_demo(base_demo):
    r = conector.consultar("SELECT COUNT(*) AS n FROM clientes", url=base_demo)
    assert r["columnas"] == ["n"] and r["filas"][0][0] == 12


def test_limite_de_filas(base_demo):
    r = conector.consultar("SELECT * FROM ventas", max_filas=5, url=base_demo)
    assert r["cantidad"] == 5 and r["truncado"]


def test_permisos_por_tabla():
    compras = obtener_usuario("u3")
    verificar_acceso(compras, "SELECT * FROM productos p JOIN proveedores v ON v.id = p.proveedor_id")
    with pytest.raises(AccesoDenegado):
        verificar_acceso(compras, "SELECT * FROM cxc")
    verificar_acceso(obtener_usuario("u1"), "SELECT * FROM cxc")  # el dueño ve todo
