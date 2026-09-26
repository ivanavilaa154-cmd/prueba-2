"""Pruebas automáticas: cada suite corre en un entorno de prueba aislado, nunca sobre producción.

El entorno de prueba es un proceso aparte (pytest) con su propia base demo y sus propias
bases de tareas, gestión y pruebas en una carpeta temporal (ver tests/conftest.py): no
toca la base de Odoo, ni la demo en uso, ni backend/ops.db.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .. import config
from . import almacen, incidencias

SUITES = [
    {"id": "unitarios", "nombre": "Unitarios", "descripcion": "Conector de solo lectura, simulador de crédito, acceso y chat.",
     "args": ["tests/test_conector.py", "tests/test_credito.py", "tests/test_acceso.py", "tests/test_chat.py"]},
    {"id": "mapeo", "nombre": "Mapeo e integración (compilador de mappings)",
     "descripcion": "Lectura de Odoo con un Odoo simulado: mapeo de cada tabla, impuestos, moneda, permisos, cortes y control contra el reporte.",
     "args": ["tests/test_integraciones.py"]},
    {"id": "kpis", "nombre": "E2E de KPIs", "descripcion": "Cada indicador del tablero contra una cuenta hecha directo en la base.",
     "args": ["tests/test_tablero.py"]},
    {"id": "actividades", "nombre": "Escenarios de actividades", "descripcion": "Las 8 actividades con sus casos, exclusiones y ciclo de vida.",
     "args": ["tests/test_actividades.py"]},
    {"id": "gestion", "nombre": "Procesos, objetivos y cascada", "descripcion": "Pasos y plazos, validación V1-V9, cascada, ACT-07 y ACT-08.",
     "args": ["tests/test_gestion.py"]},
    {"id": "permisos", "nombre": "Permisos", "descripcion": "Cartera del vendedor, tablas por rol y acceso al Centro de pruebas.",
     "args": ["tests/test_cartera.py", "tests/test_pruebas.py", "-k", "permiso or acceso or cartera or vendedor"]},
    {"id": "cuadratura", "nombre": "Casos de cuadratura", "descripcion": "Cada diferencia encontrada queda como caso permanente (tests/cuadratura/casos).",
     "args": ["tests/cuadratura"]},
    {"id": "centro", "nombre": "Centro de pruebas", "descripcion": "Incidencias, muestras, pruebas manuales y auditoría.",
     "args": ["tests/test_pruebas.py"]},
]
_candado = threading.Lock()
_corriendo: dict = {}


def _entorno_de_prueba(tmp: Path) -> dict:
    env = dict(os.environ)
    env.update({"ENTORNO": "prueba", "OPS_DB": str(tmp / "ops.db"), "ACTIVIDADES_DB": str(tmp / "actividades.db"),
                "GESTION_DB": str(tmp / "gestion.db"), "EVIDENCIAS_DIR": str(tmp / "evidencias"),
                "ERP_URL": f"sqlite:///{tmp / 'demo.db'}", "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("ANTHROPIC_API_KEY", None)   # las pruebas nunca llaman a la IA de verdad
    return env


def _leer_junit(ruta: Path) -> tuple[int, int, list[dict], float]:
    if not ruta.exists():
        return 0, 0, [], 0.0
    raiz = ET.parse(ruta).getroot()
    suites = raiz.findall("testsuite") if raiz.tag == "testsuites" else [raiz]
    total = fallas_n = 0
    tiempo = 0.0
    fallas = []
    for s in suites:
        total += int(s.get("tests", 0))
        tiempo += float(s.get("time", 0))
        for caso in s.findall("testcase"):
            for tipo in ("failure", "error"):
                f = caso.find(tipo)
                if f is not None:
                    fallas_n += 1
                    fallas.append({"prueba": f"{caso.get('classname', '')}::{caso.get('name', '')}",
                                   "mensaje": (f.get("message") or "")[:400], "detalle": (f.text or "")[-2000:]})
    return total, fallas_n, fallas, tiempo


def _ruta_test(nombre: str) -> str | None:
    """'tests.test_tablero::test_x' (junit) → 'tests/test_tablero.py::test_x'."""
    if "::" not in nombre:
        return None
    clase, prueba = nombre.split("::", 1)
    return clase.replace(".", "/") + ".py::" + prueba.split("[")[0]


def correr(suite_id: str, usuario_nombre: str) -> dict:
    suite = next((s for s in SUITES if s["id"] == suite_id), None)
    if not suite:
        raise KeyError("Suite desconocida.")
    inicio = time.time()
    with almacen.conectar() as con:
        cur = con.execute("INSERT INTO prueba_ejecucion (tipo, suite, entorno, estado, usuario, inicio_at) VALUES (?,?,?,?,?,?)",
                          ("suite", suite_id, "prueba", "corriendo", usuario_nombre, almacen.ahora()))
        ejecucion = cur.lastrowid
    with tempfile.TemporaryDirectory(prefix="entorno_prueba_") as d:
        tmp = Path(d)
        from ..erp import demo
        demo.crear(tmp / "demo.db")   # base propia del entorno de prueba: nunca la de producción
        junit = tmp / "resultado.xml"
        try:
            proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={junit}", *suite["args"]],
                                  cwd=config.BACKEND, env=_entorno_de_prueba(tmp), capture_output=True, text=True, timeout=900)
            salida = (proc.stdout + proc.stderr)[-3000:]
        except subprocess.TimeoutExpired:
            salida = "Se cortó: la suite tardó más de 15 minutos."
        total, fallidas, fallas, _t = _leer_junit(junit)
    sin_pruebas = total == 0
    estado = "error" if (sin_pruebas and "no tests ran" not in salida) else ("fallido" if fallidas else "aprobado")
    if sin_pruebas and not fallidas and "no tests ran" in salida:
        estado = "aprobado"
    if estado == "error" and not fallas:
        fallas = [{"prueba": suite["nombre"], "mensaje": "La suite no pudo ejecutarse.", "detalle": salida}]
    duracion = round(time.time() - inicio, 1)
    with almacen.conectar() as con:
        con.execute("UPDATE prueba_ejecucion SET estado=?, total=?, fallidas=?, fallas=?, duracion_s=?, fin_at=? WHERE id=?",
                    (estado, total, fallidas, json.dumps(fallas, ensure_ascii=False), duracion, almacen.ahora(), ejecucion))
    for f in fallas:
        incidencias.crear_si_no_existe(origen="automatico", tipo="prueba", pantalla=f"Pruebas automáticas · {suite['nombre']}",
                                       titulo=f"Falla en la suite {suite['nombre']}: {f['prueba'].split('::')[-1]}",
                                       descripcion=f"{f['mensaje']}\n\n{f['detalle'][-1500:]}", causa="prueba_automatica",
                                       usuario="Sistema", test_regresion=_ruta_test(f["prueba"]))
    return {"id": ejecucion, "suite": suite_id, "estado": estado, "total": total, "fallidas": fallidas, "duracion_s": duracion}


def correr_en_segundo_plano(suites: list[str], usuario_nombre: str) -> bool:
    if not _candado.acquire(blocking=False):
        return False

    def trabajo():
        try:
            for s in suites:
                _corriendo["actual"] = s
                try:
                    correr(s, usuario_nombre)
                except Exception as e:   # una suite que no arranca no frena a las demás
                    with almacen.conectar() as con:
                        con.execute("INSERT INTO prueba_ejecucion (tipo, suite, entorno, estado, fallas, usuario, inicio_at, fin_at) "
                                    "VALUES (?,?,?,?,?,?,?,?)", ("suite", s, "prueba", "error",
                                                                 json.dumps([{"prueba": s, "mensaje": str(e), "detalle": ""}]),
                                                                 usuario_nombre, almacen.ahora(), almacen.ahora()))
        finally:
            _corriendo.clear()
            _candado.release()
    threading.Thread(target=trabajo, daemon=True).start()
    return True


def resumen() -> dict:
    ultimas = {}
    for r in almacen.filas("SELECT * FROM prueba_ejecucion WHERE tipo='suite' ORDER BY id"):
        ultimas[r["suite"]] = r
    suites = []
    for s in SUITES:
        u = ultimas.get(s["id"])
        if u:
            u = {**u, "fallas": json.loads(u["fallas"] or "[]")}
        suites.append({**{k: s[k] for k in ("id", "nombre", "descripcion")}, "ultima": u})
    return {"suites": suites, "corriendo": _corriendo.get("actual"), "en_curso": _candado.locked()}
