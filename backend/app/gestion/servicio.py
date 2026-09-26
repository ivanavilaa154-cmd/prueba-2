"""Lo que muestran las pantallas de gestión: procesos por rol, ciclo de tiempo real y objetivos de ejemplo de la demo."""
from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta

from ..permisos import Usuario
from . import almacen, catalogo, objetivos, procesos


def _ve_proceso(usuario: Usuario, definicion: dict) -> bool:
    areas = catalogo.areas_de(usuario.rol)
    return areas is None or definicion["area"] in areas


def vista_procesos(usuario: Usuario, dias: int = 30, hoy: date | None = None) -> list[dict]:
    """Por proceso: embudo de pasos, tiempos, % en plazo y casos trabados (lo que el rol puede ver)."""
    hoy = hoy or date.today()
    res = []
    for pid, d in catalogo.procesos().items():
        if not _ve_proceso(usuario, d):
            continue
        p = procesos.Proceso(pid, hoy)
        item = {"id": pid, "nombre": d["nombre"], "area": d["area"], "activo": p.activo, "motivo": p.motivo or p.error,
                "unidad_tiempo": "días"}
        if not p.activo:
            res.append(item)
            continue
        vendedor_col = p.cfg["caso"].get("vendedor")
        filtro = None
        if usuario.vendedor_id is not None:
            if not vendedor_col:
                continue
            filtro = lambda c, col=vendedor_col: str(c.datos.get(col)) == str(usuario.vendedor_id)  # noqa: E731
        m = p.metricas(hoy - timedelta(days=dias - 1), hoy, filtro)
        casos = [c for c in p.casos if (not filtro or filtro(c)) and c.trabado]
        casos.sort(key=lambda c: min((c.pasos[x]["vence"] for x in c.vencidos if c.pasos[x]["vence"]), default=hoy))
        manuales = [{"paso": s["codigo"], "nombre": s["nombre"], "codigo": (p.cfg.get("pasos") or {}).get(s["codigo"], {}).get("evento_proceso")}
                    for s in d["pasos"] if (p.cfg.get("pasos") or {}).get(s["codigo"], {}).get("evento_proceso")]
        item.update({
            "metricas": {k: v for k, v in m.items() if k != "pasos"}, "pasos": list(m["pasos"].values()), "manuales": manuales,
            "trabados": [{"caso_key": c.key, "caso": c.etiqueta, "inicio": c.inicio.isoformat(),
                          "pasos_vencidos": [{"codigo": x, "nombre": c.pasos[x]["nombre"], "vence": c.pasos[x]["vence"].isoformat() if c.pasos[x]["vence"] else None,
                                              "dias": (hoy - c.pasos[x]["vence"]).days if c.pasos[x]["vence"] else None} for x in c.vencidos],
                          "detenido": c.detenido, "escalon": c.escalon,
                          "pendientes_manuales": [s["paso"] for s in manuales if c.pasos[s["paso"]]["estado"] in ("pendiente_en_plazo", "pendiente_vencido")]}
                         for c in casos[:100]],
            "total_trabados": len(casos)})
        res.append(item)
    return res


def puede_registrar(usuario: Usuario, proceso_id: str) -> bool:
    d = catalogo.procesos().get(proceso_id)
    return bool(d) and _ve_proceso(usuario, d)


# --- ciclo de tiempo real ------------------------------------------------------------------

_hilo: threading.Thread | None = None


def iniciar_ciclo() -> None:
    """Cada `ciclo_minutos` (en horario operativo; cada 30 min fuera de horario) reevalúa objetivos y casos trabados."""
    global _hilo
    if _hilo and _hilo.is_alive():
        return

    def bucle():
        ultima = 0.0
        while True:
            time.sleep(30)
            try:
                desde, hasta = catalogo.horario()
                en_horario = desde <= datetime.now().hour < hasta
                cada = float(catalogo.empresa().get("ciclo_minutos", 15)) if en_horario else 30.0
                if time.time() - ultima >= cada * 60:
                    ultima = time.time()
                    from ..actividades import motor
                    motor.ejecutar(solo=["ACT-07", "ACT-08"])
            except Exception:
                pass  # el ciclo nunca debe morir

    _hilo = threading.Thread(target=bucle, daemon=True)
    _hilo.start()


# --- demo ----------------------------------------------------------------------------------

EJEMPLOS = [
    {"plantilla_id": "OBJ-01", "periodicidad": "mensual", "cascada_tiempo": ["semanal", "diario"], "cascada_alcance": "sucursal"},
    {"plantilla_id": "OBJ-04", "periodicidad": "mensual"},
    {"plantilla_id": "OBJ-06", "periodicidad": "mensual", "alcance_tipo": "vendedor", "alcance_valor": "1"},
    {"plantilla_id": "OBJ-11", "periodicidad": "mensual"},
    {"plantilla_id": "OBJ-12", "periodicidad": "mensual"},
    {"plantilla_id": "OBJ-13", "periodicidad": "mensual"},
    {"plantilla_id": "OBJ-15", "periodicidad": "diario"},
    {"plantilla_id": "OBJ-17", "periodicidad": "mensual"},
    {"plantilla_id": "OBJ-18", "periodicidad": "mensual"},
    {"plantilla_id": "OBJ-19", "periodicidad": "mensual"},
    {"plantilla_id": "OBJ-24", "periodicidad": "mensual"},
]


def sembrar_demo(hoy: date | None = None) -> int:
    """Con la base demo y sin objetivos, carga objetivos de ejemplo y algunas gestiones de cobranza registradas."""
    if almacen.fuente_actual() != "demo" or objetivos.listar_objetivos():
        return 0
    hoy = hoy or date.today()
    dueno = Usuario(id="demo", nombre="Demo", rol="dueno")
    n = 0
    for e in EJEMPLOS:
        try:
            objetivos.guardar(e, dueno, justificacion="Objetivo de ejemplo de la demo.", hoy=hoy)
            n += 1
        except Exception:
            continue
    # Algunas facturas vencidas ya gestionadas (paso P3 de cobranza registrado a mano)
    p = procesos.Proceso("PRC-COB", hoy, eventos={})
    for c in [c for c in p.casos if c.vencidos][:6]:
        venc = c.pasos["P5"]["vence"] or hoy
        procesos.registrar_evento("PRC-COB", c.key, "gestion_cobranza_realizada", "Demo", fecha=min(hoy, venc + timedelta(days=1)),
                                  resultado="contactado", origen="demo")
    return n
