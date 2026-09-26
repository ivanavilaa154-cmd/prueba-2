"""Base propia de gestión (backend/gestion.db): eventos de proceso cargados a mano, objetivos, metas y evaluaciones.

Nunca se escribe en el ERP. Todo se guarda por fuente de datos (demo, archivos, Odoo...),
así cambiar de fuente no mezcla objetivos ni eventos.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .. import config
from ..erp import fuente

RUTA = Path(os.getenv("GESTION_DB", str(config.BACKEND / "gestion.db")))

ESQUEMA = """
CREATE TABLE IF NOT EXISTS evento_proceso (
    id INTEGER PRIMARY KEY, fuente TEXT, proceso TEXT, caso_key TEXT, codigo TEXT, fecha TEXT,
    resultado TEXT, detalle TEXT, usuario TEXT, origen TEXT, registrado_at TEXT);
CREATE INDEX IF NOT EXISTS evento_caso ON evento_proceso (fuente, proceso, caso_key);
CREATE TABLE IF NOT EXISTS objetivo (
    id INTEGER PRIMARY KEY, fuente TEXT, plantilla_id TEXT, nombre TEXT, metrica TEXT, alcance_tipo TEXT, alcance_valor TEXT,
    alcance_nombre TEXT, periodicidad TEXT, tipo_meta TEXT, curva_esperada TEXT, umbral_en_riesgo REAL DEFAULT 0.95,
    umbral_fuera_de_camino REAL DEFAULT 0.85, peso REAL DEFAULT 1, responsable_rol TEXT, objetivo_padre_id INTEGER,
    metodo_reparto TEXT, modo_reparto TEXT DEFAULT 'recuperar', area TEXT, meta_base REAL, participacion REAL, estado TEXT, justificacion TEXT,
    creado_por TEXT, aprobado_por TEXT, creado_at TEXT);
CREATE TABLE IF NOT EXISTS objetivo_meta (
    objetivo_id INTEGER, periodo_inicio TEXT, periodo_fin TEXT, meta REAL, origen TEXT, PRIMARY KEY (objetivo_id, periodo_inicio));
CREATE TABLE IF NOT EXISTS objetivo_evaluacion (
    objetivo_id INTEGER, periodo_inicio TEXT, evaluado_at TEXT, valor_actual REAL, valor_esperado REAL, meta REAL,
    avance_pct REAL, ritmo REAL, proyeccion_cierre REAL, prob_cumplimiento REAL, estado TEXT, datos_hasta TEXT,
    muestra INTEGER, advertencias TEXT, PRIMARY KEY (objetivo_id, periodo_inicio, evaluado_at));
CREATE TABLE IF NOT EXISTS objetivo_validacion (objetivo_id INTEGER, regla TEXT, severidad TEXT, mensaje TEXT, creado_at TEXT);
CREATE TABLE IF NOT EXISTS objetivo_comentario (objetivo_id INTEGER, periodo_inicio TEXT, usuario TEXT, texto TEXT, creado_at TEXT);
"""


def fuente_actual() -> str:
    return fuente.actual()


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
