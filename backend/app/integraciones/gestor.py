"""Configuración, sincronización y estado de las integraciones.

- La configuración de Odoo se guarda en backend/.env (regla 7: secretos solo en
  variables de entorno). La API key nunca se devuelve por la API.
- Cada sincronización arma una base nueva (backend/odoo.db) con las tablas del
  diccionario y la reemplaza entera solo si terminó bien.
- El historial de sincronizaciones queda en backend/integraciones_estado.json.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from .. import config
from ..erp import conector
from ..erp.demo import ESQUEMA
from ..erp.importar import _controles, _esquema
from . import odoo

ENV = config.BACKEND / ".env"
from ..erp.fuente import RUTA_ODOO  # noqa: E402
RUTA_ESTADO = config.BACKEND / "integraciones_estado.json"
CLAVES = {"url": "ODOO_URL", "db": "ODOO_DB", "usuario": "ODOO_USUARIO", "api_key": "ODOO_API_KEY",
          "meses": "ODOO_MESES", "cada_min": "ODOO_SINCRONIZAR_CADA_MIN"}
INTERVALOS = [0, 15, 30, 60, 180, 360, 720, 1440]
DISPONIBLE, PROXIMAMENTE = "disponible", "proximamente"

PLATAFORMAS = [
    {"id": "odoo", "nombre": "Odoo", "tipo": "ERP", "estado": DISPONIBLE,
     "descripcion": "Clientes, vendedores, productos, stock por almacén, pedidos, caja y facturas por la API de Odoo 12 o superior."},
    {"id": "archivos", "nombre": "Archivos CSV o Excel", "tipo": "Exportaciones", "estado": DISPONIBLE,
     "descripcion": "Exportaciones de cualquier ERP, un archivo por tabla."},
    {"id": "sql", "nombre": "Base de datos del ERP", "tipo": "SQL Server · PostgreSQL · MySQL · Oracle", "estado": DISPONIBLE,
     "descripcion": "Conexión directa de solo lectura con ERP_URL en backend/.env y el diccionario adaptado a sus tablas."},
    {"id": "tango", "nombre": "Tango Gestión", "tipo": "ERP", "estado": PROXIMAMENTE,
     "descripcion": "Diccionario de datos para la base SQL Server de Tango."},
    {"id": "sap_b1", "nombre": "SAP Business One", "tipo": "ERP", "estado": PROXIMAMENTE,
     "descripcion": "Service Layer o base SQL Server / HANA."},
    {"id": "memory", "nombre": "Memory", "tipo": "ERP", "estado": PROXIMAMENTE, "descripcion": "Sistema de gestión uruguayo."},
    {"id": "zeta", "nombre": "Zeta Software", "tipo": "ERP", "estado": PROXIMAMENTE, "descripcion": "Sistema de gestión uruguayo."},
    {"id": "bejerman", "nombre": "Bejerman", "tipo": "ERP", "estado": PROXIMAMENTE, "descripcion": "Base SQL Server."},
]

_candado = threading.Lock()
_progreso = {"corriendo": False, "paso": "", "inicio": None}


# --- configuración en .env ----------------------------------------------------

def _escribir_env(valores: dict[str, str]) -> None:
    """Actualiza o agrega claves en backend/.env sin tocar el resto de las líneas."""
    lineas = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    pendientes = dict(valores)
    for i, linea in enumerate(lineas):
        clave = linea.split("=", 1)[0].strip()
        if not linea.lstrip().startswith("#") and clave in pendientes:
            lineas[i] = f"{clave}={pendientes.pop(clave)}"
    if pendientes:
        lineas += ["", "# Integración con Odoo (la escribe el panel de integraciones)"] if not any("ODOO_" in l for l in lineas) else []
        lineas += [f"{k}={v}" for k, v in pendientes.items()]
    ENV.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    try:
        os.chmod(ENV, 0o600)
    except OSError:
        pass
    os.environ.update(valores)


def config_odoo(con_clave: bool = False) -> dict:
    datos = {k: os.getenv(v, "") for k, v in CLAVES.items()}
    datos["meses"] = int(datos["meses"] or 12)
    datos["cada_min"] = int(datos["cada_min"] or 0)
    datos["clave_guardada"] = bool(datos["api_key"])
    if not con_clave:
        datos.pop("api_key")
    return datos


def guardar_odoo(url: str, db: str, usuario: str, api_key: str | None, meses: int, cada_min: int) -> dict:
    if not (url and db and usuario):
        raise ValueError("Completá URL, base de datos y usuario.")
    if not (api_key or os.getenv(CLAVES["api_key"])):
        raise ValueError("Falta la API key.")
    if not 1 <= int(meses) <= 60:
        raise ValueError("Los meses de historia tienen que estar entre 1 y 60.")
    if int(cada_min) not in INTERVALOS:
        raise ValueError("Intervalo de sincronización no válido.")
    for valor in (url, db, usuario, api_key or ""):
        if "\n" in valor or "\r" in valor:
            raise ValueError("Los datos no pueden tener saltos de línea.")
    valores = {CLAVES["url"]: url.strip().rstrip("/"), CLAVES["db"]: db.strip(), CLAVES["usuario"]: usuario.strip(),
               CLAVES["meses"]: str(int(meses)), CLAVES["cada_min"]: str(int(cada_min))}
    if api_key:  # vacía = conservar la guardada
        valores[CLAVES["api_key"]] = api_key.strip()
    _escribir_env(valores)
    return config_odoo()


def cliente_odoo(url=None, db=None, usuario=None, api_key=None, transporte=None) -> odoo.ClienteOdoo:
    guardada = config_odoo(con_clave=True)
    return odoo.ClienteOdoo(url or guardada["url"], db or guardada["db"], usuario or guardada["usuario"],
                            api_key or guardada["api_key"], transporte=transporte)


# --- estado e historial ---------------------------------------------------------

def _leer_estado() -> dict:
    try:
        return json.loads(RUTA_ESTADO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"historial": []}


def _guardar_estado(estado: dict) -> None:
    RUTA_ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1), encoding="utf-8")


def estado_odoo() -> dict:
    estado = _leer_estado()
    ultima = next((h for h in estado["historial"] if h["ok"]), None)
    cada = config_odoo()["cada_min"]
    proxima = None
    if cada and ultima:
        proxima = datetime.fromtimestamp(ultima["ts"] + cada * 60).isoformat(timespec="minutes")
    return {"progreso": dict(_progreso), "historial": estado["historial"][:10], "ultima_ok": ultima,
            "proxima": proxima, "base_disponible": RUTA_ODOO.exists()}


# --- sincronización ---------------------------------------------------------------

def _guardar_base(tablas: dict[str, list[dict]], ruta: Path) -> list[str]:
    esquema = _esquema()
    temporal = ruta.with_suffix(".tmp")
    temporal.unlink(missing_ok=True)
    con = sqlite3.connect(temporal)
    try:
        con.executescript(ESQUEMA)
        for tabla, filas in tablas.items():
            columnas = list(esquema[tabla])
            con.executemany(f"INSERT INTO {tabla} ({','.join(columnas)}) VALUES ({','.join('?' * len(columnas))})",
                            [tuple(f.get(c) for c in columnas) for f in filas])
        con.commit()
        avisos = _controles(con)
    except Exception:
        con.close()
        temporal.unlink(missing_ok=True)
        raise
    con.close()
    conector.olvidar_conexiones()  # por si la fuente activa es esta misma base
    temporal.replace(ruta)
    return avisos


def sincronizar_odoo(transporte=None, ruta: Path | None = None) -> dict:
    """Corre una sincronización completa (bloqueante). Devuelve la entrada de historial."""
    if not _candado.acquire(blocking=False):
        raise RuntimeError("Ya hay una sincronización en curso.")
    inicio = time.time()
    _progreso.update(corriendo=True, paso="Conectando con Odoo…", inicio=inicio)
    entrada = {"ts": inicio, "fecha": datetime.fromtimestamp(inicio).isoformat(timespec="seconds")}
    try:
        cfg = config_odoo(con_clave=True)
        extraccion = odoo.Extraccion(cliente_odoo(transporte=transporte), meses=cfg["meses"],
                                     avisar=lambda texto: _progreso.update(paso=texto))
        tablas = extraccion.ejecutar()
        _progreso["paso"] = "Guardando…"
        avisos = _guardar_base(tablas, ruta or RUTA_ODOO)
        entrada.update(ok=True, conteos={t: len(f) for t, f in tablas.items()},
                       avisos=extraccion.avisos + avisos)
    except Exception as e:
        entrada.update(ok=False, error=f"{e}" if isinstance(e, odoo.OdooError) else f"{type(e).__name__}: {e}")
    finally:
        entrada["segundos"] = round(time.time() - inicio, 1)
        estado = _leer_estado()
        estado["historial"] = [entrada] + estado["historial"][:19]
        _guardar_estado(estado)
        _progreso.update(corriendo=False, paso="", inicio=None)
        _candado.release()
    return entrada


def sincronizar_en_segundo_plano(al_terminar=None) -> bool:
    if _progreso["corriendo"]:
        return False

    def correr():
        entrada = sincronizar_odoo()
        if al_terminar:
            al_terminar(entrada)

    _progreso.update(corriendo=True, paso="Conectando con Odoo…", inicio=time.time())
    threading.Thread(target=correr, daemon=True).start()
    return True


def iniciar_programador(al_terminar=None, cada_segundos: int = 30) -> None:
    """Revisa cada 30 s si corresponde sincronizar según ODOO_SINCRONIZAR_CADA_MIN."""
    def bucle():
        while True:
            time.sleep(cada_segundos)
            try:
                cfg = config_odoo()
                if not cfg["cada_min"] or not cfg["clave_guardada"] or _progreso["corriendo"]:
                    continue
                ultima = next(iter(_leer_estado()["historial"]), None)
                if not ultima or time.time() - ultima["ts"] >= cfg["cada_min"] * 60:
                    sincronizar_en_segundo_plano(al_terminar)
            except Exception:
                pass  # el programador nunca debe morir; el error queda en el historial

    threading.Thread(target=bucle, daemon=True).start()
