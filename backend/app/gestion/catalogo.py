"""Catálogos de gestión (config/gestion/procesos.yml y objetivos.yml) y configuración de la empresa (config/gestion/empresa.yaml).

Regla: ningún paso con plazo sin acción (si_vence) y ninguna plantilla de objetivo
sin acciones para 'en riesgo' y 'fuera de camino'. Si falta, el catálogo no se carga.
"""
from __future__ import annotations

import math
import unicodedata
from datetime import date, timedelta
from functools import lru_cache

import yaml

from .. import config

DIR = config.DIR_CONFIG / "gestion"
DIAS = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


class CatalogoInvalido(Exception):
    pass


def validar(procesos: dict, objetivos: dict) -> None:
    for p in procesos.get("procesos", []):
        codigos = [s["codigo"] for s in p["pasos"]]
        for s in p["pasos"]:
            if s.get("sla") and not (s.get("si_vence") or {}).get("accion"):
                raise CatalogoInvalido(f"{p['id']}.{s['codigo']}: paso con plazo sin acción si se vence")
            desde = (s.get("sla") or {}).get("desde")
            if desde and desde not in codigos:
                raise CatalogoInvalido(f"{p['id']}.{s['codigo']}: el plazo se cuenta desde un paso que no existe ({desde})")
    for o in objetivos.get("plantillas", []):
        if not o.get("si_en_riesgo") or not o.get("si_fuera_de_camino"):
            raise CatalogoInvalido(f"{o['id']}: plantilla sin acciones para 'en riesgo' y 'fuera de camino'")


def _yaml(nombre: str) -> dict:
    ruta = DIR / nombre
    return (yaml.safe_load(ruta.read_text(encoding="utf-8")) if ruta.exists() else None) or {}


@lru_cache
def cargar() -> tuple[dict, dict]:
    procesos, objetivos = _yaml("procesos.yml"), _yaml("objetivos.yml")
    validar(procesos, objetivos)
    return procesos, objetivos


def procesos() -> dict[str, dict]:
    return {p["id"]: p for p in cargar()[0].get("procesos", [])}


def plantillas() -> dict[str, dict]:
    return {o["id"]: o for o in cargar()[1].get("plantillas", [])}


def metricas_proceso() -> list[dict]:
    return cargar()[0].get("metricas_estandar", [])


@lru_cache
def empresa() -> dict:
    return _yaml("empresa.yaml")


def config_proceso(proceso_id: str) -> dict:
    return (empresa().get("procesos") or {}).get(proceso_id) or {"activo": False, "motivo": "No está configurado para esta empresa."}


def areas_de(rol: str) -> list[str] | None:
    """Áreas que ve un rol; None = todas (dueño)."""
    if rol == "dueno":
        return None
    return (empresa().get("areas_por_rol") or {}).get(rol, [])


# --- calendario ---------------------------------------------------------------------

def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


@lru_cache
def _no_habiles() -> frozenset:
    dias = (empresa().get("calendario") or {}).get("dias_no_habiles", ["domingo"])
    return frozenset(DIAS.index(_sin_tildes(d)) for d in dias if _sin_tildes(d) in DIAS)


def es_habil(d: date) -> bool:
    return d.weekday() not in _no_habiles()


def horas_por_dia() -> float:
    return float((empresa().get("calendario") or {}).get("horas_por_dia_habil", 8))


def horario() -> tuple[int, int]:
    h = (empresa().get("calendario") or {}).get("horario_operativo") or {}
    return int(h.get("desde", 8)), int(h.get("hasta", 20))


def sumar_habiles(d: date, n: int) -> date:
    """d + n días hábiles (n puede ser negativo)."""
    paso = 1 if n >= 0 else -1
    restantes = abs(n)
    while restantes:
        d += timedelta(days=paso)
        if es_habil(d):
            restantes -= 1
    return d


def habiles_entre(desde: date, hasta: date) -> int:
    """Días hábiles en [desde, hasta)."""
    n, d = 0, desde
    while d < hasta:
        n += es_habil(d)
        d += timedelta(days=1)
    return n


def plazo(sla: dict, base: date) -> date:
    """Fecha límite desde una fecha base según el SLA del catálogo (horas → días, porque los datos vienen por día)."""
    if "dias_habiles" in sla:
        return sumar_habiles(base, int(sla["dias_habiles"]))
    if "horas_habiles" in sla:
        return sumar_habiles(base, math.ceil(float(sla["horas_habiles"]) / horas_por_dia()))
    if "horas" in sla:
        return base + timedelta(days=math.ceil(float(sla["horas"]) / 24))
    return base + timedelta(days=int(sla.get("dias", 0)))
