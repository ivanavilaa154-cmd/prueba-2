"""Catálogo de actividades (config/actividades.yml) y configuración de la empresa (config/actividades_empresa.yaml).

El catálogo dice qué se detecta, en qué casos cae cada detección y qué acciones
prescribe cada caso (responsable y plazo). La regla central es "ninguna alerta
sin acción": si un caso no tiene acciones, el catálogo no se carga.
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, timedelta
from functools import lru_cache

import yaml

from .. import config

PRIORIDADES = ("critica", "alta", "media", "baja")
URGENCIA = {"critica": 3, "alta": 2, "media": 1, "baja": 0.5}
ABIERTAS = ("nueva", "en_curso", "vencida")
CERRADAS = ("resuelta", "descartada", "cerrada_automatica")


class CatalogoInvalido(Exception):
    pass


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn").lower()


def validar(doc: dict) -> None:
    """Falla si una actividad no cumple el contrato (casos con acciones, responsable y plazo)."""
    ids = set()
    for a in doc.get("actividades", []):
        if a["id"] in ids:
            raise CatalogoInvalido(f"Actividad repetida: {a['id']}")
        ids.add(a["id"])
        if not a.get("casos"):
            raise CatalogoInvalido(f"{a['id']} no tiene casos")
        if not a.get("resoluciones"):
            raise CatalogoInvalido(f"{a['id']} no tiene resoluciones")
        if not set(a.get("resolucion_confirmada", [])) <= set(a["resoluciones"]):
            raise CatalogoInvalido(f"{a['id']}: resolución confirmada que no está entre las resoluciones")
        for c in a["casos"]:
            if not c.get("acciones"):
                raise CatalogoInvalido(f"{a['id']}.{c['codigo']}: caso sin acción (ninguna alerta sin acción)")
            for acc in c["acciones"]:
                if not acc.get("responsable") or not acc.get("plazo"):
                    raise CatalogoInvalido(f"{a['id']}.{c['codigo']}: acción sin responsable o plazo")


@lru_cache
def catalogo() -> dict:
    doc = yaml.safe_load((config.DIR_CONFIG / "actividades.yml").read_text(encoding="utf-8"))
    validar(doc)
    return doc


@lru_cache
def empresa() -> dict:
    ruta = config.DIR_CONFIG / "actividades_empresa.yaml"
    return (yaml.safe_load(ruta.read_text(encoding="utf-8")) if ruta.exists() else None) or {}


def actividades() -> dict[str, dict]:
    return {a["id"]: a for a in catalogo()["actividades"]}


def actividad(act_id: str) -> dict:
    return actividades()[act_id]


def caso(act_id: str, codigo: str) -> dict:
    return next(c for c in actividad(act_id)["casos"] if c["codigo"] == codigo)


def parametros(act_id: str) -> dict:
    p = dict(actividad(act_id).get("parametros") or {})
    p.update((empresa().get("parametros") or {}).get(act_id) or {})
    return p


def rol_plataforma(rol_actividad: str) -> str:
    return (empresa().get("responsables") or {}).get(rol_actividad, "dueno")


def escala_a() -> str:
    return empresa().get("escala_a", "dueno")


def tope_diario() -> int:
    return int(empresa().get("tope_diario_por_persona", 15))


def prioridad_base(texto: str | None) -> str:
    """'alta (crítica si ...)' → 'alta'."""
    primera = _sin_tildes((texto or "media").split()[0]).strip(" ,;")
    return primera if primera in PRIORIDADES else "media"


def plazo_dias(plazo: str) -> int | None:
    """Días hábiles corridos que da un plazo del catálogo; None si depende de un evento (al recibir, próximo pedido...)."""
    t = _sin_tildes(plazo)
    if t.startswith("inmediato") or "mismo dia" in t or re.match(r"\d+\s*h\s*habiles", t):
        return 0
    m = re.match(r"(\d+)\s*h\b", t)
    if m:
        return math.ceil(int(m.group(1)) / 24)
    m = re.match(r"(\d+)\s*dias?\b", t)
    if m:
        return int(m.group(1))
    return None


def vence_accion(plazo: str, desde: date) -> str | None:
    d = plazo_dias(plazo)
    return None if d is None else (desde + timedelta(days=d)).isoformat()


def _especificidad(p: dict) -> int:
    return {"todas": 0, "categoria": 1, "marca": 2, "proveedor": 3, "producto": 4}.get(p.get("alcance_tipo"), 0)


def politica(nombre: str, producto: dict) -> dict:
    """Política de precio o de producto que aplica al producto: gana la más específica."""
    aplicables = []
    for p in empresa().get(nombre) or []:
        tipo, valor = p.get("alcance_tipo", "todas"), p.get("alcance_valor")
        clave = {"categoria": "categoria", "marca": "marca", "proveedor": "proveedor_id", "producto": "id"}.get(tipo)
        if tipo == "todas" or (clave and str(producto.get(clave)) == str(valor)):
            aplicables.append(p)
    resultado: dict = {}
    for p in sorted(aplicables, key=_especificidad):
        resultado.update({k: v for k, v in p.items() if v is not None})
    return resultado
