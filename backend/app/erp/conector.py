"""Conector de SOLO LECTURA a la base de datos del ERP.

Primera barrera de seguridad: solo se ejecuta un único SELECT (o WITH ... SELECT).
Segunda barrera (obligatoria en producción): el usuario de base de datos del
cliente debe tener únicamente permisos de lectura.

Si se pasa el usuario, antes de ejecutar se verifican las tablas de su rol y se
aplica su filtro por fila (vendedor → su cartera). Ver app/permisos.py.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache

from sqlalchemy import create_engine, text

from .. import config
from ..permisos import Usuario, preparar_consulta


class ConsultaNoPermitida(Exception):
    pass


_PROHIBIDAS = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|"
    r"attach|detach|pragma|vacuum|exec|execute|call|copy|into|lock)\b",
    re.IGNORECASE,
)


def _sin_comentarios(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql.strip()


def validar_sql(sql: str) -> str:
    """Devuelve el SQL limpio o lanza ConsultaNoPermitida."""
    limpio = _sin_comentarios(sql).rstrip(";").strip()
    if not limpio:
        raise ConsultaNoPermitida("La consulta está vacía.")
    # Quitar literales de texto antes de buscar palabras prohibidas y ';'
    sin_literales = re.sub(r"'(?:[^']|'')*'", "''", limpio)
    if ";" in sin_literales:
        raise ConsultaNoPermitida("Solo se permite una consulta por vez.")
    if not re.match(r"^\s*(select|with)\b", sin_literales, re.IGNORECASE):
        raise ConsultaNoPermitida("Solo se permiten consultas SELECT (solo lectura).")
    encontrada = _PROHIBIDAS.search(sin_literales)
    if encontrada:
        raise ConsultaNoPermitida(f"Operación no permitida en solo lectura: {encontrada.group(0).upper()}.")
    return limpio


@lru_cache
def _motor(url: str):
    return create_engine(url, future=True)


def olvidar_conexiones() -> None:
    """Cierra las conexiones abiertas (al cambiar de base o reemplazar el archivo)."""
    for url in list(_abiertos):
        _motor(url).dispose()
    _abiertos.clear()
    _motor.cache_clear()


_abiertos: set[str] = set()


def _serializable(valor):
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return valor


_DIALECTOS = {"postgresql": "postgres", "mssql": "tsql", "mysql": "mysql", "mariadb": "mysql",
              "oracle": "oracle", "sqlite": "sqlite"}


def dialecto(url: str) -> str | None:
    """Dialecto SQL del ERP según la URL de conexión (mssql+pyodbc://... → tsql)."""
    return _DIALECTOS.get(url.split(":", 1)[0].split("+", 1)[0].lower())


def consultar(sql: str, max_filas: int | None = None, url: str | None = None,
              usuario: Usuario | None = None) -> dict:
    """Ejecuta un SELECT validado y devuelve columnas, filas y si se truncó.

    Sin usuario no se aplican permisos: solo para usos internos del sistema.
    Todo lo que llega del chat o de la API pasa el usuario.
    """
    url = url or config.ERP_URL
    limpio = validar_sql(sql)
    if usuario is not None:
        limpio = validar_sql(preparar_consulta(usuario, limpio, dialecto(url)))
    limite = max_filas or config.MAX_FILAS
    _abiertos.add(url)
    with _motor(url).connect() as conexion:
        resultado = conexion.execute(text(limpio))
        columnas = list(resultado.keys())
        filas = resultado.fetchmany(limite + 1)
        conexion.rollback()  # nunca se confirma nada
    truncado = len(filas) > limite
    filas = [[_serializable(v) for v in fila] for fila in filas[:limite]]
    return {"columnas": columnas, "filas": filas, "cantidad": len(filas), "truncado": truncado}
