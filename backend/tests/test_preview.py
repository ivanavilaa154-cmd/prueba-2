"""Importación de exportaciones reales y endpoints del preview."""
import io

import pytest
from fastapi.testclient import TestClient

from app import config
from app.erp import conector, fuente, importar


@pytest.mark.parametrize("texto, esperado", [
    ("1.234,56", 1234.56), ("1234,56", 1234.56), ("1,234.56", 1234.56), ("1234.56", 1234.56),
    ("$ 1.234", 1234.0), ("1.234.567", 1234567.0), ("0.220", 0.22), ("-15,5", -15.5), ("22%", 0.22),
    ("", None), (400000, 400000.0),
])
def test_numeros_rioplatenses(texto, esperado):
    assert importar.numero(texto) == esperado


@pytest.mark.parametrize("texto", ["24/09/2026", "2026-09-24", "24-09-2026", "24/09/2026 10:30"])
def test_fechas(texto):
    assert importar.fecha(texto) == "2026-09-24"


def test_tabla_por_nombre_de_archivo():
    assert importar.tabla_de_archivo("Clientes.xlsx") == "clientes"
    assert importar.tabla_de_archivo("export_ventas_lineas_2026.csv") == "ventas_lineas"
    assert importar.tabla_de_archivo("ventas sep.csv") == "ventas"
    assert importar.tabla_de_archivo("otra_cosa.csv") is None


CLIENTES = (
    "ID;Razón social;Vendedor ID;Límite crédito;Fecha alta;Teléfono\n"
    "1;Almacén Pérez;7;150.000;01/03/2024;099 123\n"
    "2;Kiosco Sur;8;20.000,50;15/06/2025;\n"
    ";Sin código;7;0;01/01/2024;\n"
    "2;Repetido;7;0;01/01/2024;\n"
).encode("cp1252")
VENTAS = b"id,fecha,cliente_id,vendedor_id,anulada\n10,2026-09-01,1,7,no\n11,2026-09-02,2,8,si\n12,2026-09-03,99,7,\n"
VENDEDORES = b"id;nombre\n7;Ana\n8;Bruno\n"


def _excel(filas):
    from openpyxl import Workbook

    libro = Workbook()
    for fila in filas:
        libro.active.append(fila)
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def test_importa_csv_y_excel(tmp_path):
    cxc = _excel([["cliente_id", "fecha_vencimiento", "saldo"], [1, "10/09/2026", 5000.5], [2, None, "1.000,00"]])
    informe = importar.importar(
        [("clientes.csv", CLIENTES), ("ventas.csv", VENTAS), ("vendedores.csv", VENDEDORES), ("cxc.xlsx", cxc)],
        ruta=tmp_path / "real.db",
    )
    por_tabla = {t["tabla"]: t for t in informe["tablas"]}
    assert por_tabla["clientes"]["filas"] == 2 and por_tabla["clientes"]["descartadas"] == 2
    assert "telefono" in por_tabla["clientes"]["columnas_ignoradas"]
    assert "tipo" in por_tabla["clientes"]["columnas_faltantes"]
    assert por_tabla["cxc"]["filas"] == 2
    assert any("ventas de clientes que no están" in a for a in informe["avisos"])

    url = f"sqlite:///{tmp_path / 'real.db'}"
    filas = conector.consultar("SELECT id, razon_social, limite_credito, fecha_alta FROM clientes ORDER BY id", url=url)["filas"]
    assert filas == [[1, "Almacén Pérez", 150000.0, "2024-03-01"], [2, "Kiosco Sur", 20000.5, "2025-06-15"]]
    assert conector.consultar("SELECT id, anulada FROM ventas ORDER BY id", url=url)["filas"] == [[10, 0], [11, 1], [12, 0]]
    assert conector.consultar("SELECT SUM(saldo) FROM cxc", url=url)["filas"][0][0] == 6000.5


def test_sin_clientes_no_importa(tmp_path):
    with pytest.raises(importar.ErrorImportacion, match="clientes"):
        importar.importar([("ventas.csv", VENTAS)], ruta=tmp_path / "x.db")


def test_falta_columna_obligatoria(tmp_path):
    with pytest.raises(importar.ErrorImportacion, match="obligatorias"):
        importar.importar([("clientes.csv", b"razon_social\nX\n")], ruta=tmp_path / "x.db")


def test_error_no_toca_la_base_anterior(tmp_path):
    ruta = tmp_path / "real.db"
    importar.importar([("clientes.csv", CLIENTES)], ruta=ruta)
    with pytest.raises(importar.ErrorImportacion):
        importar.importar([("clientes.csv", b"nombre\nX\n")], ruta=ruta)
    assert conector.consultar("SELECT COUNT(*) FROM clientes", url=f"sqlite:///{ruta}")["filas"][0][0] == 2


@pytest.fixture
def cliente_api(base_demo, tmp_path, monkeypatch):
    from app import main

    monkeypatch.setattr(importar, "RUTA", tmp_path / "datos_reales.db")
    monkeypatch.setattr(fuente, "URL_IMPORTADA", f"sqlite:///{tmp_path / 'datos_reales.db'}")
    monkeypatch.setattr(fuente, "URL_DEMO", base_demo)
    monkeypatch.setattr(config, "ERP_URL", base_demo)
    monkeypatch.delenv("ERP_URL", raising=False)
    yield TestClient(main.app)
    conector.olvidar_conexiones()


def test_preview_importa_y_filtra_por_vendedor(cliente_api):
    assert cliente_api.get("/").status_code == 200
    assert cliente_api.get("/fuente").json()["fuente"] == "demo"

    r = cliente_api.post("/importar", files=[
        ("archivos", ("clientes.csv", CLIENTES, "text/csv")),
        ("archivos", ("vendedores.csv", VENDEDORES, "text/csv")),
    ])
    assert r.status_code == 200, r.text
    assert r.json()["fuente"]["fuente"] == "importada"
    assert r.json()["fuente"]["tablas"]["clientes"] == 2

    usuarios = {u["id"] for u in cliente_api.get("/usuarios").json()}
    assert {"vendedor:7", "vendedor:8", "u1"} <= usuarios

    como_ana = cliente_api.post("/consulta", json={"usuario_id": "vendedor:7", "sql": "SELECT razon_social FROM clientes"})
    assert como_ana.json()["filas"] == [["Almacén Pérez"]]
    assert "vendedor_id = 7" in como_ana.json()["sql_ejecutado"]
    assert len(cliente_api.post("/consulta", json={"usuario_id": "u1", "sql": "SELECT * FROM clientes"}).json()["filas"]) == 2

    borrar = cliente_api.post("/consulta", json={"usuario_id": "u1", "sql": "DELETE FROM clientes"})
    assert borrar.status_code == 403

    assert cliente_api.post("/fuente", json={"fuente": "demo"}).json()["tablas"]["clientes"] == 12
    assert cliente_api.post("/fuente", json={"fuente": "erp"}).status_code == 400


def test_plantilla(cliente_api):
    r = cliente_api.get("/plantillas/clientes.csv")
    assert r.status_code == 200 and r.text.startswith("id;razon_social;")
    assert cliente_api.get("/plantillas/nada.csv").status_code == 404


def test_chat_sin_clave_avisa(cliente_api, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = cliente_api.post("/chat", json={"usuario_id": "u1", "mensaje": "hola"})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
