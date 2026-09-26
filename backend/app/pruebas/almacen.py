"""Base del Centro de pruebas y de la cuadratura (backend/ops.db): auditoría, pruebas, muestras, incidencias.

Es propia de la plataforma: nunca se escribe en el ERP. Los importes se guardan en
centésimos enteros (nunca con coma flotante) y se redondean solo al mostrar.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from .. import config

RUTA = Path(os.getenv("OPS_DB", str(config.BACKEND / "ops.db")))
EVIDENCIAS = Path(os.getenv("EVIDENCIAS_DIR", str(config.BACKEND / "evidencias")))

ESQUEMA = """
CREATE TABLE IF NOT EXISTS auditoria (
    id INTEGER PRIMARY KEY, at TEXT, usuario TEXT, rol TEXT, accion TEXT, objeto TEXT, detalle TEXT, ver_como TEXT);
CREATE TABLE IF NOT EXISTS prueba_caso (
    id INTEGER PRIMARY KEY, codigo TEXT UNIQUE, titulo TEXT, pantalla TEXT, rol_ejecucion TEXT, pasos TEXT,
    resultado_esperado TEXT, activo INTEGER DEFAULT 1, creado_at TEXT);
CREATE TABLE IF NOT EXISTS prueba_ejecucion (
    id INTEGER PRIMARY KEY, tipo TEXT, caso_id INTEGER, suite TEXT, entorno TEXT, estado TEXT, comentario TEXT,
    evidencia_id INTEGER, duracion_s REAL, total INTEGER, fallidas INTEGER, fallas TEXT, usuario TEXT,
    inicio_at TEXT, fin_at TEXT, incidencia_id INTEGER);
CREATE TABLE IF NOT EXISTS verificacion_muestra (
    id INTEGER PRIMARY KEY, lote_id TEXT, fuente TEXT, metrica TEXT, desde TEXT, hasta TEXT, registro_clave TEXT,
    origen_payload TEXT, plataforma TEXT, resultado TEXT DEFAULT 'pendiente', comentario TEXT, usuario TEXT,
    creado_at TEXT, marcado_at TEXT, incidencia_id INTEGER);
CREATE TABLE IF NOT EXISTS incidencia (
    id INTEGER PRIMARY KEY, origen TEXT, tipo TEXT, fuente TEXT, metrica TEXT, pantalla TEXT, fecha_dato TEXT,
    registro_clave TEXT, causa TEXT, titulo TEXT, descripcion TEXT, evidencia TEXT, estado TEXT DEFAULT 'abierta',
    responsable TEXT, test_regresion TEXT, definicion_id INTEGER, creada_por TEXT, creada_at TEXT,
    resuelta_por TEXT, resuelta_at TEXT, historial TEXT);
CREATE TABLE IF NOT EXISTS evidencia (
    id INTEGER PRIMARY KEY, nombre TEXT, tipo TEXT, ruta TEXT, tamano INTEGER, subido_por TEXT, subido_at TEXT);
CREATE TABLE IF NOT EXISTS cuadratura_definicion (
    id INTEGER PRIMARY KEY, fuente TEXT, metrica TEXT, parametros TEXT, descripcion TEXT, estado TEXT,
    dias_evaluados INTEGER, dias_ok INTEGER, evidencia TEXT, registrada_por TEXT, registrada_at TEXT);
CREATE TABLE IF NOT EXISTS calidad_cuadratura (
    id INTEGER PRIMARY KEY, fuente TEXT, metrica TEXT, periodo TEXT, grupo TEXT, verificado_el TEXT,
    origen_centesimos INTEGER, plataforma_centesimos INTEGER, origen_lineas INTEGER, plataforma_lineas INTEGER,
    cuadra INTEGER, verificado_at TEXT);
CREATE TABLE IF NOT EXISTS reconciliacion_claves (
    id INTEGER PRIMARY KEY, fuente TEXT, stream TEXT, desde TEXT, ejecutado_at TEXT, en_origen INTEGER, en_plataforma INTEGER,
    faltantes TEXT, borrados TEXT, duplicados TEXT);
"""


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def centesimos(valor) -> int:
    """Importe → centésimos enteros, sin pasar por coma flotante en el redondeo."""
    return int(Decimal(str(valor or 0)).scaleb(2).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pesos(centesimos_: int | None) -> float | None:
    return None if centesimos_ is None else float(Decimal(centesimos_).scaleb(-2))


@contextmanager
def conectar():
    con = sqlite3.connect(RUTA)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def filas(sql: str, args=()) -> list[dict]:
    with conectar() as con:
        return [dict(r) for r in con.execute(sql, args)]


def auditar(usuario, accion: str, objeto: str = "", detalle=None, ver_como: str | None = None) -> None:
    with conectar() as con:
        con.execute("INSERT INTO auditoria (at, usuario, rol, accion, objeto, detalle, ver_como) VALUES (?,?,?,?,?,?,?)",
                    (ahora(), getattr(usuario, "nombre", str(usuario)), getattr(usuario, "rol", None), accion, objeto,
                     json.dumps(detalle, ensure_ascii=False, default=str) if detalle is not None else None, ver_como))
