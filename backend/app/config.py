"""Configuración: variables de entorno, archivos YAML y armado de prompts."""
from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[2]  # carpeta del proyecto
DIR_CONFIG = RAIZ / "config"
DIR_PROMPTS = RAIZ / "prompts"
BACKEND = RAIZ / "backend"


def _cargar_env() -> None:
    """Carga backend/.env si existe (sin dependencias externas)."""
    archivo = BACKEND / ".env"
    if not archivo.exists():
        return
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


_cargar_env()

ERP_URL = os.getenv("ERP_URL", f"sqlite:///{BACKEND / 'demo_erp.db'}")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5")
MAX_FILAS = int(os.getenv("MAX_FILAS", "200"))
MAX_VUELTAS_HERRAMIENTAS = int(os.getenv("MAX_VUELTAS_HERRAMIENTAS", "8"))


def _yaml(nombre: str) -> dict:
    return yaml.safe_load((DIR_CONFIG / nombre).read_text(encoding="utf-8"))


@lru_cache
def empresa() -> dict:
    return _yaml("empresa.yaml")


@lru_cache
def roles() -> dict:
    return _yaml("roles.yaml")


@lru_cache
def diccionario() -> dict:
    return _yaml("diccionario_datos.yaml")


def prompt(nombre: str, variables: dict | None = None) -> str:
    """Lee un prompt de /prompts y reemplaza las variables {CLAVE}."""
    texto = (DIR_PROMPTS / nombre).read_text(encoding="utf-8")
    valores = {k: str(v) for k, v in empresa().items() if not isinstance(v, dict)}
    valores["FECHA_HOY"] = date.today().isoformat()
    valores.update(variables or {})
    for clave, valor in valores.items():
        texto = texto.replace("{" + clave + "}", valor)
    return texto


def resumen_diccionario() -> str:
    """Versión compacta del diccionario para el prompt de sistema."""
    d = diccionario()
    lineas = ["TABLAS DISPONIBLES (usá ver_diccionario para el detalle):"]
    for tabla, info in d["tablas"].items():
        campos = ", ".join(info["campos"].keys())
        lineas.append(f"- {tabla}: {info['descripcion']} Campos: {campos}")
    lineas.append("RELACIONES: " + "; ".join(d.get("relaciones", [])))
    lineas.append("DEFINICIONES OFICIALES:")
    lineas += [f"- {k}: {v}" for k, v in d.get("definiciones", {}).items()]
    lineas.append("FILTROS POR DEFECTO: " + " ".join(d.get("filtros_por_defecto", [])))
    return "\n".join(lineas)
