"""Lectura directa de la base del sistema de caja (SPEC v2, 5.1, fase 2). Siempre en solo lectura.

- SQLite: con la biblioteca estándar, abriendo el archivo en modo solo lectura (mode=ro).
- DBF (dBase, FoxPro, Clipper): con un lector propio (biblioteca estándar); cada archivo .dbf de la carpeta es una tabla.
- ODBC (SQL Server —por ejemplo Tango—, Access, Firebird, MySQL…): con pyodbc y el controlador ODBC de Windows, en una conexión de
  solo lectura. pyodbc va incluido en el .exe del agente; si falta, se avisa qué instalar.

Las consultas SQL se validan antes de ejecutarse: una sola sentencia SELECT (o WITH … SELECT), sin palabras que modifiquen datos.
El agente nunca escribe en la base del cliente.
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
import struct
from decimal import Decimal, InvalidOperation
from pathlib import Path

PROHIBIDAS = re.compile(r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|exec|execute|call|attach|detach|pragma|"
                        r"vacuum|reindex|into|lock|set|commit|rollback|begin|declare|use|backup|restore|shutdown|kill|dbcc|openrowset|opendatasource|openquery|xp_\w*)\b", re.I)


class ErrorLectura(Exception):
    """La base no se pudo leer o la consulta no es válida; el mensaje se muestra en Datos → Conexiones."""


def validar_consulta(sql: str) -> str:
    """Devuelve la consulta limpia si es una sola sentencia de lectura; si no, lanza ErrorLectura."""
    sin_comentarios = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip().rstrip(";").strip()
    sin_textos = re.sub(r"'(?:''|[^'])*'", "''", sin_comentarios)
    if not re.match(r"(?is)^(select|with)\b", sin_textos):
        raise ErrorLectura("La consulta tiene que empezar con SELECT (o WITH … SELECT): el agente solo lee.")
    if ";" in sin_textos:
        raise ErrorLectura("Una consulta por sección: no se permiten varias sentencias separadas por «;».")
    m = PROHIBIDAS.search(sin_textos)
    if m:
        raise ErrorLectura(f"La consulta usa «{m.group(0)}»: el agente solo lee, no modifica la base.")
    return sin_comentarios


def _parametros(sql: str, desde) -> tuple[str, list]:
    """«:desde» → el marcador de cada motor; devuelve la consulta y la lista de parámetros."""
    n = sql.count(":desde")
    return sql.replace(":desde", "?"), [desde] * n


# ------------------------------------------------------------------------------ SQLite
class LectorSQLite:
    def __init__(self, ruta: str):
        self.ruta = Path(ruta)
        if not self.ruta.is_file():
            raise ErrorLectura(f"No encuentro la base {self.ruta}.")

    def consultar(self, sql: str, desde=None) -> tuple[list[str], list[tuple]]:
        sql, params = _parametros(validar_consulta(sql), desde)
        try:
            with sqlite3.connect(f"file:{self.ruta.as_posix()}?mode=ro", uri=True) as c:
                c.execute("PRAGMA query_only = ON")
                cur = c.execute(sql, params)
                return [d[0] for d in cur.description], cur.fetchall()
        except sqlite3.Error as e:
            raise ErrorLectura(f"SQLite: {e}")


# ------------------------------------------------------------------------------ DBF
def leer_dbf(ruta: Path, codificacion: str = "cp1252") -> tuple[list[str], list[dict]]:
    """Lee un .dbf (dBase III/IV, FoxPro, Clipper). Devuelve (campos, filas como diccionarios); saltea los registros borrados."""
    datos = ruta.read_bytes()
    if len(datos) < 32:
        raise ErrorLectura(f"{ruta.name} no es un archivo DBF.")
    cantidad, largo_encabezado, largo_registro = struct.unpack("<IHH", datos[4:12])
    campos = []
    pos = 32
    while pos < largo_encabezado - 1 and datos[pos] != 0x0D:
        nombre = datos[pos:pos + 11].split(b"\x00")[0].decode("ascii", "replace").strip()
        tipo = chr(datos[pos + 11])
        largo, decimales = datos[pos + 16], datos[pos + 17]
        campos.append((nombre, tipo, largo, decimales))
        pos += 32
    filas = []
    inicio = largo_encabezado
    for i in range(cantidad):
        reg = datos[inicio + i * largo_registro: inicio + (i + 1) * largo_registro]
        if not reg or reg[:1] == b"*":                       # borrado
            continue
        fila, p = {}, 1
        for nombre, tipo, largo, decimales in campos:
            crudo = reg[p:p + largo]
            p += largo
            fila[nombre] = _valor_dbf(crudo, tipo, decimales, codificacion)
        filas.append(fila)
    return [c[0] for c in campos], filas


def _valor_dbf(crudo: bytes, tipo: str, decimales: int, codificacion: str):
    if tipo in "CM":
        return crudo.decode(codificacion, "replace").rstrip() if tipo == "C" else None
    texto = crudo.decode("ascii", "replace").strip()
    if tipo in "NF":
        if not texto or set(texto) <= {"*"}:
            return None
        try:
            return Decimal(texto)
        except InvalidOperation:
            return None
    if tipo == "D":
        return dt.date(int(texto[:4]), int(texto[4:6]), int(texto[6:8])) if len(texto) == 8 and texto.isdigit() else None
    if tipo == "L":
        return {"T": True, "Y": True, "S": True, "F": False, "N": False}.get(texto.upper()[:1])
    if tipo == "I":
        return struct.unpack("<i", crudo)[0]
    return texto


class LectorDBF:
    """Cada consulta indica tabla (archivo sin .dbf), columnas (opcional, con alias «CAMPO as alias») e incremental (campo de fecha o número)."""

    def __init__(self, carpeta: str, codificacion: str = "cp1252"):
        self.carpeta = Path(carpeta)
        self.codificacion = codificacion
        if not self.carpeta.is_dir():
            raise ErrorLectura(f"No encuentro la carpeta {self.carpeta}.")

    def _archivo(self, tabla: str) -> Path:
        for f in self.carpeta.iterdir():
            if f.suffix.lower() == ".dbf" and f.stem.lower() == tabla.lower():
                return f
        raise ErrorLectura(f"No encuentro la tabla {tabla}.dbf en {self.carpeta}.")

    def consultar_tabla(self, tabla: str, columnas: str | None = None, incremental: str | None = None, desde=None) -> tuple[list[str], list[tuple]]:
        campos, filas = leer_dbf(self._archivo(tabla), self.codificacion)
        pedidas = [c.strip() for c in columnas.split(",")] if columnas else campos
        salida_nombres, origen = [], []
        indice = {c.upper(): c for c in campos}
        for c in pedidas:
            m = re.match(r"(?i)^(\w+)(?:\s+as\s+(\w+))?$", c)
            if not m or m.group(1).upper() not in indice:
                raise ErrorLectura(f"La tabla {tabla} no tiene la columna {c}.")
            origen.append(indice[m.group(1).upper()])
            salida_nombres.append(m.group(2) or m.group(1))
        if incremental:
            clave = indice.get(incremental.upper())
            if not clave:
                raise ErrorLectura(f"La tabla {tabla} no tiene la columna {incremental}.")
            if desde is not None:
                filas = [f for f in filas if f[clave] is not None and _comparable(f[clave]) > _comparable(desde)]
        return salida_nombres, [tuple(f[c] for c in origen) for f in filas]


def _comparable(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, (int, float, Decimal)):
        return f"{float(v):020.4f}"
    return str(v)


# ------------------------------------------------------------------------------ ODBC
class LectorODBC:
    def __init__(self, cadena: str):
        try:
            import pyodbc  # noqa: F401
        except ImportError:
            raise ErrorLectura("Para leer SQL Server, Access, Firebird o MySQL hace falta pyodbc (viene en el .exe del agente) "
                               "y el controlador ODBC de esa base instalado en Windows.")
        self.cadena = cadena

    def consultar(self, sql: str, desde=None) -> tuple[list[str], list[tuple]]:
        import pyodbc
        sql, params = _parametros(validar_consulta(sql), desde)
        try:
            with pyodbc.connect(self.cadena, readonly=True, autocommit=False, timeout=30) as c:
                cur = c.cursor()
                cur.execute(sql, params)
                filas = [tuple(f) for f in cur.fetchall()]
                c.rollback()
                return [d[0] for d in cur.description], filas
        except pyodbc.Error as e:
            raise ErrorLectura(f"ODBC: {e}")


def abrir(tipo: str, origen: str, codificacion: str = "cp1252"):
    tipo = tipo.strip().lower()
    if tipo == "sqlite":
        return LectorSQLite(origen)
    if tipo == "dbf":
        return LectorDBF(origen, codificacion)
    if tipo == "odbc":
        return LectorODBC(origen)
    raise ErrorLectura(f"Tipo de base «{tipo}» desconocido: usá sqlite, dbf u odbc.")
