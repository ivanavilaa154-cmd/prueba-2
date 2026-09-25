"""Genera el preview que corre entero en el navegador (sin servidor).

Uso (desde la carpeta del proyecto):
    backend/.venv/bin/python tools/build_preview.py [salida.html]

Toma del proyecto todo lo que el preview necesita para comportarse igual que la
API: esquema y datos de la base demo, roles y filtros por fila, diccionario,
prompts del chat, definiciones de herramientas y parámetros financieros. Así el
preview no se desincroniza: si cambia la configuración, se vuelve a generar.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

from app import config  # noqa: E402
from app.chat import herramientas  # noqa: E402
from app.erp import demo, importar  # noqa: E402

PLANTILLA = Path(__file__).resolve().parent / "preview" / "plantilla.html"


def _datos_demo(hoy: date) -> dict:
    with tempfile.TemporaryDirectory() as carpeta:
        ruta = demo.crear(Path(carpeta) / "demo.db", hoy=hoy)
        con = sqlite3.connect(ruta)
        tablas = {}
        for (tabla,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY rowid"):
            cursor = con.execute(f"SELECT * FROM {tabla}")
            tablas[tabla] = {"columnas": [c[0] for c in cursor.description], "filas": cursor.fetchall()}
        con.close()
    return tablas


def datos(hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    marcas = {"USUARIO": "{USUARIO}", "FECHA_HOY": "{FECHA_HOY}"}  # se completan en el navegador
    return {
        "hoy_demo": hoy.isoformat(),
        "empresa": config.empresa(),
        "roles": config.roles(),
        "diccionario": config.diccionario(),
        "esquema_sql": demo.ESQUEMA,
        "esquema": importar._esquema(),
        "obligatorias": importar.OBLIGATORIAS,
        "booleanas": sorted(f"{t}.{c}" for t, c in importar.BOOLEANAS),
        "max_filas": config.MAX_FILAS,
        "prompt_sistema": "\n\n".join([
            config.prompt("00_base.md", marcas),
            config.prompt("06_chat_interno.md", marcas),
            config.prompt("05_centro_decisiones.md", marcas),
        ]),
        "resumen_diccionario": config.resumen_diccionario(),
        "herramientas": herramientas.DEFINICIONES,
        "demo": _datos_demo(hoy),
    }


def generar(salida: Path) -> Path:
    contenido = json.dumps(datos(), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    html = PLANTILLA.read_text(encoding="utf-8").replace("__DATOS__", contenido)
    salida.write_text(html, encoding="utf-8")
    return salida


if __name__ == "__main__":
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else RAIZ / "preview.html"
    print(f"Preview generado en {generar(destino)} ({destino.stat().st_size // 1024} KB)")
