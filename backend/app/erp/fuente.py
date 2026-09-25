"""Qué base consulta la plataforma: la demo, los archivos importados, Odoo o el ERP del .env.

Se cambia en caliente desde el preview. Solo cambia config.ERP_URL; todas las
consultas siguen pasando por el conector de solo lectura.
"""
from __future__ import annotations

import os
import re

from .. import config
from . import conector, importar

URL_DEMO = f"sqlite:///{config.BACKEND / 'demo_erp.db'}"
URL_IMPORTADA = f"sqlite:///{importar.RUTA}"
RUTA_ODOO = config.BACKEND / "odoo.db"
URL_ODOO = f"sqlite:///{RUTA_ODOO}"


def _url_env() -> str | None:
    url = os.getenv("ERP_URL", "").strip()
    return url or None


def opciones() -> dict[str, str | None]:
    return {
        "demo": URL_DEMO,
        "importada": URL_IMPORTADA if importar.RUTA.exists() else None,
        "odoo": URL_ODOO if RUTA_ODOO.exists() else None,
        "erp": _url_env(),
    }


def actual() -> str:
    for tipo, url in opciones().items():
        if url and url == config.ERP_URL:
            return tipo
    return "erp"


def usar(tipo: str) -> None:
    url = opciones().get(tipo)
    if not url:
        raise ValueError({
            "importada": "Todavía no importaste archivos.",
            "odoo": "Todavía no sincronizaste Odoo.",
            "erp": "No hay ERP_URL en backend/.env.",
        }.get(tipo, f"Fuente desconocida: {tipo}"))
    conector.olvidar_conexiones()
    config.ERP_URL = url


def ocultar_clave(url: str) -> str:
    return re.sub(r"(://[^:/@]+:)[^@]+@", r"\1****@", url)


def resumen() -> dict:
    """Filas por tabla del diccionario en la fuente activa (uso interno, sin rol)."""
    tablas = {}
    for tabla in config.diccionario().get("tablas", {}):
        try:
            tablas[tabla] = conector.consultar(f"SELECT COUNT(*) FROM {tabla}")["filas"][0][0]
        except Exception as e:  # la tabla no existe en este ERP o no hay permiso
            tablas[tabla] = None
            if not tablas.get("_error"):
                tablas["_error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
    error = tablas.pop("_error", None)
    return {
        "fuente": actual(),
        "url": ocultar_clave(config.ERP_URL),
        "disponibles": {k: bool(v) for k, v in opciones().items()},
        "tablas": tablas,
        "error": error,
    }
