"""Panel ERP por empresa (CLAUDE.md, regla 8: cada empresa ve solo lo suyo).

Con cuentas unificadas, el panel ERP deja de ser de una sola empresa: cada una tiene su carpeta con
- erp.db: lo que se trae de su Odoo (ventas, pedidos, clientes, stock, deuda...), en el modelo estándar;
- importada.db: lo que importe a mano (archivos), si no usa Odoo;
- actividades.db y gestion.db: sus tareas y objetivos;
- estado.json: historial de sincronizaciones.

Una sola conexión de Odoo por empresa: la que se guarda (cifrada) en Retail → Datos → Conexiones. Con esa misma conexión se
alimentan las dos secciones: Retail trae los tickets de caja y el panel ERP, todo lo demás.

En cada pedido, el ingreso unificado (acceso.py) fija de qué empresa es: el dueño, la suya; la administración, la que eligió
en Retail (si no eligió ninguna, ve la demostración). Todo el panel lee esa empresa desde acá.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from . import config

CARPETA = Path(os.getenv("EMPRESAS_DIR", str(config.BACKEND / "datos" / "empresas")))
SINCRONIZAR_CADA_HORAS = 3

_org: ContextVar[int | None] = ContextVar("erp_org", default=None)
_persona: ContextVar[dict | None] = ContextVar("erp_persona", default=None)
_progreso: dict[int, dict] = {}
_candados: dict[int, threading.Lock] = {}


# ------------------------------------------------------------------------------ contexto del pedido
def activar(org_id: int | None, persona: dict | None = None):
    return _org.set(org_id), _persona.set(persona)


def desactivar(tokens) -> None:
    _org.reset(tokens[0])
    _persona.reset(tokens[1])


def org() -> int | None:
    return _org.get()


def persona() -> dict | None:
    return _persona.get()


def carpeta(org_id: int) -> Path:
    c = CARPETA / str(int(org_id))
    c.mkdir(parents=True, exist_ok=True)
    return c


def ruta(nombre: str) -> Path | None:
    """Archivo de la empresa del pedido (None fuera de una empresa: se usa el global de siempre)."""
    o = org()
    return carpeta(o) / nombre if o else None


def _base_vacia(destino: Path) -> None:
    from .erp.modelo import ESQUEMA
    con = sqlite3.connect(destino)
    try:
        con.executescript(ESQUEMA)
        con.commit()
    finally:
        con.close()


def fuente_elegida(org_id: int) -> str:
    try:
        return json.loads((carpeta(org_id) / "fuente.json").read_text(encoding="utf-8"))["fuente"]
    except (OSError, ValueError, KeyError):
        return "odoo" if (carpeta(org_id) / "erp.db").exists() or not (carpeta(org_id) / "importada.db").exists() else "importada"


def elegir_fuente(org_id: int, fuente: str) -> None:
    if fuente not in ("odoo", "importada"):
        raise ValueError("Elegí Odoo o los archivos importados.")
    archivo = "erp.db" if fuente == "odoo" else "importada.db"
    if not (carpeta(org_id) / archivo).exists():
        raise ValueError("Todavía no sincronizaste Odoo." if fuente == "odoo" else "Todavía no importaste archivos.")
    (carpeta(org_id) / "fuente.json").write_text(json.dumps({"fuente": fuente}), encoding="utf-8")


def url_erp() -> str | None:
    """Base del ERP de la empresa del pedido. Si todavía no tiene datos, una base vacía: el panel dice qué falta."""
    o = org()
    if not o:
        return None
    archivo = carpeta(o) / ("importada.db" if fuente_elegida(o) == "importada" else "erp.db")
    if not archivo.exists():
        _base_vacia(archivo)
    return f"sqlite:///{archivo}"


def tiene_datos(org_id: int) -> bool:
    archivo = carpeta(org_id) / ("importada.db" if fuente_elegida(org_id) == "importada" else "erp.db")
    if not archivo.exists():
        return False
    con = sqlite3.connect(archivo)
    try:
        return bool(con.execute("SELECT EXISTS (SELECT 1 FROM ventas)").fetchone()[0])
    except sqlite3.Error:
        return False
    finally:
        con.close()


# ------------------------------------------------------------------------------ la conexión de Odoo de la empresa
def credenciales(org_id: int) -> dict | None:
    """La conexión de Odoo guardada en Retail (descifrada, solo en memoria del servidor)."""
    from .retail import cifrado, db
    from .retail.motor import contexto_sistema
    with db.transaccion(contexto_sistema(org_id)) as conn:
        p = db.fila(conn, "SELECT id, config, credenciales_cifradas FROM plataformas WHERE tipo='odoo' AND activa "
                          "AND credenciales_cifradas IS NOT NULL ORDER BY id LIMIT 1")
    if not p:
        return None
    cfg = p["config"] if isinstance(p["config"], dict) else json.loads(p["config"])
    return {"plataforma_id": p["id"], "url": cfg.get("url"), "base": cfg.get("base"), "usuario": cfg.get("usuario"),
            "api_key": cifrado.descifrar(p["credenciales_cifradas"]).get("api_key")}


def _leer_estado(org_id: int) -> dict:
    try:
        return json.loads((carpeta(org_id) / "estado.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"historial": []}


def estado(org_id: int) -> dict:
    e = _leer_estado(org_id)
    p = dict(_progreso.get(org_id) or {"corriendo": False, "paso": "", "inicio": None})
    p["segundos"] = round(time.time() - p["inicio"]) if p.get("corriendo") and p.get("inicio") else 0
    ultima = next((h for h in e["historial"] if h.get("ok")), None)
    proxima = (ultima["ts"] + SINCRONIZAR_CADA_HORAS * 3600) if ultima else None
    return {"progreso": p, "historial": e["historial"][:10], "ultima_ok": ultima, "base_disponible": tiene_datos(org_id),
            "cada_min": SINCRONIZAR_CADA_HORAS * 60,
            "proxima": datetime.fromtimestamp(proxima).isoformat(timespec="minutes") if proxima else None,
            "segundos_para_proxima": max(0, round(proxima - time.time())) if proxima else None}


def sincronizar(org_id: int, transporte=None, meses: int = 12) -> dict:
    """Trae de Odoo todo lo que usa el panel ERP y lo guarda en la base de la empresa (bloqueante)."""
    from .integraciones import gestor, odoo
    candado = _candados.setdefault(org_id, threading.Lock())
    if not candado.acquire(blocking=False):
        raise RuntimeError("Ya hay una sincronización en curso.")
    inicio = time.time()
    _progreso[org_id] = {"corriendo": True, "paso": "Conectando con Odoo…", "inicio": inicio}
    entrada = {"ts": inicio, "fecha": datetime.fromtimestamp(inicio).isoformat(timespec="seconds")}
    try:
        c = credenciales(org_id)
        if not c:
            raise odoo.OdooError("Esta empresa todavía no conectó Odoo.")
        cliente = odoo.ClienteOdoo(c["url"], c["base"], c["usuario"], c["api_key"], transporte=transporte)
        extraccion = odoo.Extraccion(cliente, meses=meses, avisar=lambda texto: _progreso[org_id].update(paso=texto))
        tablas = extraccion.ejecutar()
        _progreso[org_id]["paso"] = "Comparando con el reporte de ventas de Odoo…"
        try:
            control = odoo.control_ventas(extraccion.c, tablas, meses, zona=str(extraccion.zona))
        except Exception as e:                      # el control nunca frena la sincronización
            control = {"disponible": False, "motivo": f"No se pudo comparar con el reporte de ventas de Odoo: {e}"}
        _progreso[org_id]["paso"] = "Guardando…"
        avisos = gestor._guardar_base(tablas, carpeta(org_id) / "erp.db")
        entrada.update(ok=True, conteos={t: len(f) for t, f in tablas.items() if f}, avisos=extraccion.avisos + avisos,
                       control_ventas=control)
    except Exception as e:
        entrada.update(ok=False, error=f"{e}" if isinstance(e, odoo.OdooError) else f"{type(e).__name__}: {e}")
    finally:
        entrada["segundos"] = round(time.time() - inicio, 1)
        e = _leer_estado(org_id)
        e["historial"] = [entrada] + e["historial"][:19]
        (carpeta(org_id) / "estado.json").write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")
        _progreso[org_id] = {"corriendo": False, "paso": "", "inicio": None}
        candado.release()
    if entrada.get("ok"):
        _revisar_actividades(org_id)
    return entrada


def _revisar_actividades(org_id: int) -> None:
    """Con datos nuevos, el panel revisa sus actividades (tareas) de esa empresa."""
    tokens = activar(org_id, {"nombre": "Sistema", "superadmin": False})
    try:
        from .actividades import motor
        motor.ejecutar()
    except Exception as e:                          # nunca frena: se reintenta en la próxima sincronización
        print(f"Panel ERP: no se pudieron revisar las actividades de la empresa {org_id} ({type(e).__name__}: {str(e)[:120]})")
    finally:
        desactivar(tokens)


def sincronizar_en_segundo_plano(org_id: int) -> bool:
    if (_progreso.get(org_id) or {}).get("corriendo"):
        return False
    _progreso[org_id] = {"corriendo": True, "paso": "Conectando con Odoo…", "inicio": time.time()}

    def correr():
        try:
            sincronizar(org_id)
        except RuntimeError:
            pass

    threading.Thread(target=correr, daemon=True).start()
    return True


def toca_sincronizar(org_id: int) -> bool:
    """Para el programador de cada hora: si pasaron SINCRONIZAR_CADA_HORAS desde la última (o nunca se sincronizó)."""
    if (_progreso.get(org_id) or {}).get("corriendo") or not credenciales(org_id):
        return False
    ultima = next((h for h in _leer_estado(org_id)["historial"] if h.get("ok")), None)
    return not ultima or time.time() - ultima["ts"] >= SINCRONIZAR_CADA_HORAS * 3600
