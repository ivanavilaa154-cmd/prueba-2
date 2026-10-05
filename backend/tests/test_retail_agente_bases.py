"""SPEC v2 · Fase 2 · 4: el agente lee la base del sistema de caja (SQLite, DBF, ODBC) en solo lectura y trae solo lo nuevo."""
import datetime as dt
import hashlib
import sqlite3
import struct
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.retail import api_ingesta
from app.retail.semilla import CLAVE_DEMO
from test_retail_agente import PorTestClient
from test_retail_importar import _q

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "agente"))
import agente_sync  # noqa: E402
import lectores  # noqa: E402


@pytest.fixture(autouse=True)
def sin_recalculo(monkeypatch):
    monkeypatch.setattr(api_ingesta, "recalcular_en_segundo_plano", lambda org, desde=None: None)


# ------------------------------------------------------------------------------ solo lectura
@pytest.mark.parametrize("sql", ["DELETE FROM ventas", "UPDATE ventas SET precio = 0", "select 1; drop table ventas", "SELECT * INTO copia FROM ventas",
                                 "WITH x AS (SELECT 1) DELETE FROM ventas", "select * from t where a = xp_cmdshell('dir')", "PRAGMA writable_schema = 1",
                                 "SELECT 1 /* */ ; INSERT INTO t VALUES (1)"])
def test_solo_se_permiten_consultas_de_lectura(sql):
    with pytest.raises(lectores.ErrorLectura):
        lectores.validar_consulta(sql)


def test_consultas_validas():
    for sql in ["SELECT a FROM t WHERE f > :desde", "with x as (select 1 a) select a from x", "SELECT REPLACE(nombre, 'x', 'y') FROM t WITH (NOLOCK)",
                "SELECT 'delete' AS texto FROM t -- comentario con drop"]:
        assert lectores.validar_consulta(sql)


# ------------------------------------------------------------------------------ SQLite, de punta a punta
def _base(ruta: Path, suc: str, prods: list[str], dias: list[dt.date], desde_numero: int = 1) -> None:
    with sqlite3.connect(ruta) as c:
        c.execute("CREATE TABLE IF NOT EXISTS ventas (fecha TEXT, hora TEXT, local TEXT, numero INTEGER, codigo TEXT, cantidad REAL, precio REAL)")
        c.execute("CREATE TABLE IF NOT EXISTS existencias (codigo TEXT, local TEXT, cantidad REAL)")
        n = desde_numero
        for d in dias:
            for p in prods:
                c.execute("INSERT INTO ventas VALUES (?,?,?,?,?,?,?)", (d.isoformat(), "10:30", suc, n, p, 2, 1500.5))
                n += 1
        if not c.execute("SELECT 1 FROM existencias").fetchone():
            c.executemany("INSERT INTO existencias VALUES (?,?,?)", [(p, suc, 40) for p in prods])


def _ini(tmp_path, token, base, extra=""):
    carpeta = tmp_path / "exportaciones"
    carpeta.mkdir(exist_ok=True)
    ini = tmp_path / "agente.ini"
    ini.write_text(f"""[agente]
url = http://localhost
token = {token}
carpeta = {carpeta}
cada_minutos = 15

[base]
tipo = sqlite
ruta = {base}

[consulta:ventas]
tipo = ventas
incremental = fecha
desde_inicial = 2026-09-01
sql = SELECT fecha, hora, local AS sucursal, 'B-' || numero AS ticket, codigo AS producto, cantidad, precio
      FROM ventas WHERE fecha > :desde ORDER BY fecha

[consulta:stock]
tipo = stock
cada_minutos = 60
sql = SELECT codigo AS producto, local AS sucursal, cantidad FROM existencias
{extra}""", encoding="utf-8")
    return agente_sync.Config(ini), carpeta


def test_lee_la_base_sqlite_trae_solo_lo_nuevo_y_se_importa_solo(retail_demo, tmp_path):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": "dueno@norte.demo", "clave": CLAVE_DEMO}).status_code == 200
    token = c.post("/retail/api/agentes", json={"nombre": "PC con la base"}).json()["token"]
    suc = _q("SELECT nombre FROM ubicaciones WHERE tipo <> 'deposito' ORDER BY id LIMIT 1")[0]["nombre"]
    prods = [p["codigo_interno"] for p in _q("SELECT codigo_interno FROM productos ORDER BY id LIMIT 2")]
    base = tmp_path / "caja.sqlite"
    _base(base, suc, prods, [dt.date(2026, 9, 20), dt.date(2026, 9, 21)])
    huella = hashlib.sha256(base.read_bytes()).hexdigest()
    reloj = [time.time()]
    cfg, carpeta = _ini(tmp_path, token, base, "\n[consulta:mala]\ntipo = ventas\nsql = DELETE FROM ventas\n")
    agente = agente_sync.Agente(cfg, PorTestClient(cfg), reloj=lambda: reloj[0])

    r = agente.vuelta()
    assert r["consultas"]["ventas"] == 4 and r["consultas"]["stock"] == 2 and "solo lee" in r["consultas"]["mala"]
    assert r["subidos"] == 2                                          # ventas y stock, importados solos (columnas con el nombre exacto)
    assert hashlib.sha256(base.read_bytes()).hexdigest() == huella      # la base del cliente no se tocó
    assert agente.estado["marcas"]["ventas"] == "2026-09-21"
    assert _q("SELECT count(*) n FROM tickets WHERE origen = 'archivo' AND numero_externo LIKE %s", ("%-B-%",))[0]["n"] == 4
    estados = {l["tipo"]: l["estado"] for l in _q("SELECT tipo, estado FROM lotes_importacion WHERE agente_id IS NOT NULL")}
    assert estados == {"ventas": "importado", "stock": "importado"}

    # Llegan ventas nuevas: la próxima vuelta trae solo esas (el stock todavía no toca: es cada 60 minutos).
    _base(base, suc, prods, [dt.date(2026, 9, 22)], desde_numero=100)
    reloj[0] += 16 * 60
    r = agente.vuelta()
    assert r["consultas"] == {"ventas": 2, "mala": r["consultas"]["mala"]} and r["subidos"] == 1
    assert _q("SELECT count(*) n FROM tickets WHERE origen = 'archivo' AND numero_externo LIKE %s", ("%-B-%",))[0]["n"] == 6
    reloj[0] += 16 * 60
    assert agente.vuelta()["consultas"]["ventas"] == 0                # nada nuevo: no sube nada

    # El estado de cada consulta se ve en Datos → Conexiones.
    a = c.get("/retail/api/agentes").json()["agentes"][0]
    assert a["base"] == "sqlite" and a["version"] == agente_sync.VERSION
    consultas = {q["nombre"]: q for q in a["consultas"]}
    assert consultas["ventas"]["error"] is None and consultas["ventas"]["marca"] == "2026-09-22"
    assert "solo lee" in consultas["mala"]["error"]


def test_sin_red_las_lecturas_quedan_en_cola(retail_demo, tmp_path):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": "dueno@norte.demo", "clave": CLAVE_DEMO}).status_code == 200
    token = c.post("/retail/api/agentes", json={"nombre": "PC sin red"}).json()["token"]
    base = tmp_path / "caja.sqlite"
    _base(base, "Salta Centro", ["P0001"], [dt.date(2026, 9, 20)])
    cfg, carpeta = _ini(tmp_path, token, base)
    agente = agente_sync.Agente(cfg, PorTestClient(cfg, sin_internet=True))
    r = agente.vuelta()
    assert r["consultas"]["ventas"] == 1 and r["en_cola"] == 2 and r["subidos"] == 0
    assert len(list(carpeta.glob("ventas_ventas_*.csv"))) == 1         # el CSV queda en la carpeta hasta que vuelva internet


# ------------------------------------------------------------------------------ DBF
def _dbf(ruta: Path, campos: list[tuple], filas: list[tuple], borradas: set = frozenset()) -> None:
    """Escribe un dBase III mínimo (C, N, D, L)."""
    largo = 1 + sum(c[2] for c in campos)
    enc = 32 + 32 * len(campos) + 1
    datos = bytearray(struct.pack("<BBBBIHH20x", 3, 126, 10, 5, len(filas), enc, largo))
    for nombre, tipo, ancho, dec in campos:
        datos += struct.pack("<11sc4xBB14x", nombre.encode().ljust(11, b"\x00"), tipo.encode(), ancho, dec)
    datos += b"\x0d"
    for i, f in enumerate(filas):
        datos += b"*" if i in borradas else b" "
        for (nombre, tipo, ancho, dec), v in zip(campos, f):
            if tipo == "D":
                texto = v.strftime("%Y%m%d")
            elif tipo == "N":
                texto = f"{v:>{ancho}.{dec}f}"
            elif tipo == "L":
                texto = "T" if v else "F"
            else:
                texto = str(v).ljust(ancho)
            datos += texto.encode("cp1252")[:ancho].ljust(ancho)
    datos += b"\x1a"
    ruta.write_bytes(bytes(datos))


def test_lector_dbf_con_incremental_alias_y_borrados(tmp_path):
    campos = [("FECHA", "D", 8, 0), ("CODART", "C", 10, 0), ("CANT", "N", 8, 2), ("ANULADA", "L", 1, 0), ("DESCRIP", "C", 20, 0)]
    filas = [(dt.date(2026, 9, 20), "P0001", 2.5, False, "Yerba ñandú"), (dt.date(2026, 9, 21), "P0002", 1, False, "Azúcar"),
             (dt.date(2026, 9, 22), "P0003", 3, True, "Borrada"), (dt.date(2026, 9, 23), "P0004", 4, False, "Café")]
    _dbf(tmp_path / "VENTAS.DBF", campos, filas, borradas={2})
    cols, todas = lectores.leer_dbf(tmp_path / "VENTAS.DBF")
    assert cols == ["FECHA", "CODART", "CANT", "ANULADA", "DESCRIP"] and len(todas) == 3
    assert todas[0]["DESCRIP"] == "Yerba ñandú" and str(todas[0]["CANT"]) == "2.50" and todas[0]["ANULADA"] is False
    lector = lectores.LectorDBF(str(tmp_path))
    cols, filas = lector.consultar_tabla("ventas", "FECHA as fecha, CODART as producto, CANT as cantidad", "FECHA", "2026-09-20")
    assert cols == ["fecha", "producto", "cantidad"] and [f[1] for f in filas] == ["P0002", "P0004"]
    with pytest.raises(lectores.ErrorLectura):
        lector.consultar_tabla("ventas", "NOEXISTE")
    with pytest.raises(lectores.ErrorLectura):
        lector.consultar_tabla("clientes")


def test_odbc_sin_controlador_avisa_que_instalar(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyodbc", None)
    with pytest.raises(lectores.ErrorLectura, match="pyodbc"):
        lectores.abrir("odbc", "DRIVER={SQL Server};SERVER=x")
    with pytest.raises(lectores.ErrorLectura):
        lectores.abrir("oracle", "x")


def test_configuracion_con_variables_de_entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("TANGO_CLAVE", "s3creta")
    carpeta = tmp_path / "exp"
    carpeta.mkdir()
    ini = tmp_path / "agente.ini"
    ini.write_text(f"""[agente]
url = https://plataforma.test
token = ag_x
carpeta = {carpeta}

[base]
tipo = odbc
cadena = DRIVER={{ODBC Driver 17 for SQL Server}};PWD=${{TANGO_CLAVE}};Encrypt=yes;Usar=100%

[consulta:ventas]
tipo = ventas
incremental = fecha
sql = SELECT a FROM t WHERE f > :desde
""", encoding="utf-8")
    cfg = agente_sync.Config(ini)
    assert "PWD=s3creta" in cfg.base["cadena"] and "100%" in cfg.base["cadena"] and cfg.consultas[0]["nombre"] == "ventas"
    ini.write_text(ini.read_text(encoding="utf-8").replace("tipo = ventas\n", ""), encoding="utf-8")
    with pytest.raises(SystemExit, match="tipo"):
        agente_sync.Config(ini)
