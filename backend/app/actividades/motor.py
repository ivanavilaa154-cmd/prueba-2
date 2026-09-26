"""Motor de actividades: corre las reglas, arma las tareas y lleva su ciclo de vida.

Las tareas se guardan en una base propia de la plataforma (backend/actividades.db),
nunca en el ERP. Una sola tarea abierta por clave (clave_dedupe). Ciclo de vida:
nueva → en_curso → resuelta / descartada (con resolución obligatoria) · vencida si
pasa el plazo (sube a escala_a) · cerrada_automatica si la condición desaparece.
Ninguna tarea hace cambios en el ERP: son indicaciones para una persona.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from .. import config
from ..erp import fuente
from ..permisos import Usuario
from . import catalogo
from .datos import Datos
from .reglas import REGLAS, Deteccion

RUTA = Path(os.getenv("ACTIVIDADES_DB", str(config.BACKEND / "actividades.db")))
_bloqueo = threading.Lock()

ESQUEMA = """
CREATE TABLE IF NOT EXISTS actividad (
    id INTEGER PRIMARY KEY, fuente TEXT NOT NULL, tipo TEXT NOT NULL, caso TEXT NOT NULL, clave_dedupe TEXT NOT NULL,
    titulo TEXT, entidad TEXT, detectada_at TEXT, actualizada_at TEXT, fecha_limite TEXT, prioridad TEXT,
    puntaje REAL, impacto_estimado REAL, evidencia TEXT, notas TEXT, acciones TEXT, detalle TEXT,
    responsable_rol TEXT, rol_plataforma TEXT, estado TEXT, resolucion TEXT, resuelta_at TEXT, comentario TEXT,
    resuelta_por TEXT, origen TEXT DEFAULT 'regla', notificar INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS actividad_clave ON actividad (fuente, clave_dedupe);
CREATE TABLE IF NOT EXISTS actividad_descartes (fuente TEXT, fecha TEXT, tipo TEXT, clave TEXT, motivo TEXT);
CREATE TABLE IF NOT EXISTS ejecucion (fuente TEXT, at TEXT, hoy TEXT, resumen TEXT);
"""

JSON_CAMPOS = ("entidad", "evidencia", "notas", "acciones", "detalle")

# Resoluciones que abren la tarea siguiente (el caso lo indica el catálogo en su condición).
SEGUIMIENTOS = {("ACT-01", "no_hay_stock_fisico_ajustado"): "C3", ("ACT-01", "danado_o_vencido_retirado"): "C4"}


def _conectar() -> sqlite3.Connection:
    con = sqlite3.connect(RUTA)
    con.row_factory = sqlite3.Row
    con.executescript(ESQUEMA)
    return con


def _fila(r: sqlite3.Row) -> dict:
    t = dict(r)
    for c in JSON_CAMPOS:
        t[c] = json.loads(t[c]) if t.get(c) else ([] if c != "entidad" and c != "detalle" else ({} if c == "entidad" else None))
    return t


def _fuente() -> str:
    return fuente.actual()


def _acciones(act_id: str, caso: str, desde: date, propias: list | None = None) -> list[dict]:
    """Las acciones del caso del catálogo, o las propias de la detección (paso vencido, plantilla del objetivo)."""
    lista = propias or catalogo.caso(act_id, caso)["acciones"]
    return [{"orden": i + 1, "accion": a["accion"], "responsable": a["responsable"],
             "rol_plataforma": catalogo.rol_plataforma(a["responsable"]), "plazo": a["plazo"],
             "vence": catalogo.vence_accion(a["plazo"], desde)}
            for i, a in enumerate(lista)]


def _limite(acciones: list[dict]) -> str | None:
    fechas = [a["vence"] for a in acciones if a["vence"]]
    return max(fechas) if fechas else None


def _prioridad(det: Deteccion) -> str:
    return det.prioridad or catalogo.prioridad_base(catalogo.caso(det.actividad, det.caso).get("prioridad"))


def _historial(con, fte: str):
    def buscar(clave: str, prefijo: bool = False) -> list[dict]:
        sql = "SELECT * FROM actividad WHERE fuente = ? AND clave_dedupe " + ("LIKE ?" if prefijo else "= ?") + " ORDER BY id"
        return [_fila(r) for r in con.execute(sql, (fte, clave + "%" if prefijo else clave))]
    return buscar


def _crear(con, fte: str, det: Deteccion, ahora: datetime, hoy: date, origen: str = "regla") -> int:
    acciones = _acciones(det.actividad, det.caso, hoy, det.acciones)
    prioridad = _prioridad(det)
    rol = acciones[0]["responsable"]
    cur = con.execute(
        "INSERT INTO actividad (fuente, tipo, caso, clave_dedupe, titulo, entidad, detectada_at, actualizada_at, fecha_limite, "
        "prioridad, puntaje, impacto_estimado, evidencia, notas, acciones, detalle, responsable_rol, rol_plataforma, estado, origen) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (fte, det.actividad, det.caso, det.clave, det.titulo, json.dumps(det.entidad, ensure_ascii=False),
         ahora.isoformat(timespec="seconds"), ahora.isoformat(timespec="seconds"), _limite(acciones), prioridad,
         round(max(0.0, det.impacto or 0) * catalogo.URGENCIA[prioridad], 2), round(det.impacto or 0, 2),
         json.dumps(det.evidencia, ensure_ascii=False), json.dumps(det.notas, ensure_ascii=False),
         json.dumps(acciones, ensure_ascii=False), json.dumps(det.detalle, ensure_ascii=False) if det.detalle else None,
         rol, catalogo.rol_plataforma(rol), "nueva", origen))
    return cur.lastrowid


def _refrescar(con, tarea: dict, det: Deteccion, ahora: datetime) -> None:
    """Misma detección que sigue abierta: se actualizan los números, no el plazo ni el estado."""
    prioridad = _prioridad(det)
    con.execute("UPDATE actividad SET titulo=?, entidad=?, evidencia=?, notas=?, detalle=?, impacto_estimado=?, puntaje=?, "
                "prioridad=?, actualizada_at=? WHERE id=?",
                (det.titulo, json.dumps(det.entidad, ensure_ascii=False), json.dumps(det.evidencia, ensure_ascii=False),
                 json.dumps(det.notas, ensure_ascii=False), json.dumps(det.detalle, ensure_ascii=False) if det.detalle else None,
                 round(det.impacto or 0, 2), round(max(0.0, det.impacto or 0) * catalogo.URGENCIA[prioridad], 2), prioridad,
                 ahora.isoformat(timespec="seconds"), tarea["id"]))


def _cerrar_auto(con, tarea_id: int, motivo: str, ahora: datetime) -> None:
    con.execute("UPDATE actividad SET estado='cerrada_automatica', resuelta_at=?, comentario=?, actualizada_at=? WHERE id=?",
                (ahora.isoformat(timespec="seconds"), motivo, ahora.isoformat(timespec="seconds"), tarea_id))


def _suprimida(historial, clave: str, hoy: date) -> bool:
    """Una detección marcada como falso positivo no vuelve a aparecer por 7 días."""
    return any(h["resolucion"] == "falso_positivo" and h["resuelta_at"]
               and date.fromisoformat(h["resuelta_at"][:10]) >= hoy - timedelta(days=7) for h in historial(clave))


def ejecutar(hoy: date | None = None, ahora: datetime | None = None, solo: list[str] | None = None) -> dict:
    """Corre las reglas sobre la fuente activa y actualiza las tareas. Devuelve el resumen de la ejecución."""
    with _bloqueo:
        ahora = ahora or datetime.now()
        datos = Datos(hoy)
        fte = _fuente()
        con = _conectar()
        try:
            historial = _historial(con, fte)
            resumen = {"hoy": datos.hoy.isoformat(), "datos_hasta": datos.datos_hasta.isoformat() if datos.datos_hasta else None,
                       "actividades": {}}
            for act_id, regla in REGLAS.items():
                if solo and act_id not in solo:
                    continue
                try:
                    r = regla(datos, historial)
                except Exception as e:  # una regla con un dato raro no frena a las demás; sus tareas quedan como estaban
                    resumen["actividades"][act_id] = {"detectadas": 0, "nuevas": 0, "actualizadas": 0, "cerradas_solas": 0,
                                                      "descartes": 0, "faltan": [], "error": f"{type(e).__name__}: {e}"}
                    continue
                nuevas = actualizadas = cerradas = 0
                vistas = set()
                for det in r.detecciones:
                    if det.clave in vistas:   # una sola por clave en cada ejecución: gana la primera (más grave)
                        continue
                    vistas.add(det.clave)
                    if _suprimida(historial, det.clave, datos.hoy):
                        con.execute("INSERT INTO actividad_descartes VALUES (?,?,?,?,?)",
                                    (fte, datos.hoy.isoformat(), act_id, det.clave, "Marcada como falso positivo hace menos de 7 días."))
                        continue
                    abierta = con.execute("SELECT * FROM actividad WHERE fuente=? AND clave_dedupe=? AND estado IN "
                                          "('nueva','en_curso','vencida') ORDER BY id DESC LIMIT 1", (fte, det.clave)).fetchone()
                    if abierta and abierta["origen"] == "seguimiento":
                        con.execute("INSERT INTO actividad_descartes VALUES (?,?,?,?,?)",
                                    (fte, datos.hoy.isoformat(), act_id, det.clave, f"Hay un seguimiento abierto (tarea #{abierta['id']})."))
                        continue
                    if abierta and abierta["caso"] == det.caso:
                        _refrescar(con, _fila(abierta), det, ahora)
                        actualizadas += 1
                        continue
                    if abierta:
                        _cerrar_auto(con, abierta["id"], f"Pasó al caso {det.caso}.", ahora)
                    _crear(con, fte, det, ahora, datos.hoy)
                    nuevas += 1
                # Lo que la regla ya no detecta se cierra solo (salvo seguimientos y detecciones directas de otro origen)
                for t in con.execute("SELECT id, clave_dedupe FROM actividad WHERE fuente=? AND tipo=? AND origen='regla' AND "
                                     "estado IN ('nueva','en_curso','vencida')", (fte, act_id)).fetchall():
                    if t["clave_dedupe"] not in vistas:
                        _cerrar_auto(con, t["id"], "La condición desapareció en la última revisión.", ahora)
                        cerradas += 1
                for clave, motivo in r.descartes:
                    con.execute("INSERT INTO actividad_descartes VALUES (?,?,?,?,?)", (fte, datos.hoy.isoformat(), act_id, clave, motivo))
                resumen["actividades"][act_id] = {"detectadas": len(vistas), "nuevas": nuevas, "actualizadas": actualizadas,
                                                  "cerradas_solas": cerradas, "descartes": len(r.descartes), "faltan": r.faltan}
            _vencer(con, fte, datos.hoy, ahora)
            _marcar_notificables(con, fte)
            con.execute("DELETE FROM actividad_descartes WHERE fuente=? AND fecha < ?", (fte, (datos.hoy - timedelta(days=90)).isoformat()))
            con.execute("INSERT INTO ejecucion VALUES (?,?,?,?)", (fte, ahora.isoformat(timespec="seconds"), datos.hoy.isoformat(),
                                                                  json.dumps(resumen, ensure_ascii=False)))
            con.commit()
        finally:
            con.close()
        return resumen


def _vencer(con, fte: str, hoy: date, ahora: datetime) -> None:
    """Pasado el plazo sin resolver: vencida, y sube al rol de escala."""
    con.execute("UPDATE actividad SET estado='vencida', rol_plataforma=?, actualizada_at=? WHERE fuente=? AND "
                "estado IN ('nueva','en_curso') AND fecha_limite IS NOT NULL AND fecha_limite < ?",
                (catalogo.escala_a(), ahora.isoformat(timespec="seconds"), fte, hoy.isoformat()))


def _marcar_notificables(con, fte: str) -> None:
    """Cada rol recibe aviso de sus N tareas de mayor puntaje; el resto queda visible sin aviso."""
    con.execute("UPDATE actividad SET notificar = 0 WHERE fuente = ?", (fte,))
    tope = catalogo.tope_diario()
    for (rol,) in con.execute("SELECT DISTINCT rol_plataforma FROM actividad WHERE fuente=? AND estado IN ('nueva','en_curso','vencida')",
                              (fte,)).fetchall():
        ids = [r[0] for r in con.execute("SELECT id FROM actividad WHERE fuente=? AND rol_plataforma=? AND estado IN "
                                         "('nueva','en_curso','vencida') ORDER BY puntaje DESC LIMIT ?", (fte, rol, tope))]
        con.executemany("UPDATE actividad SET notificar = 1 WHERE id = ?", [(i,) for i in ids])


# --- lectura y cambios de estado ----------------------------------------------------------

def _visible(t: dict, usuario: Usuario) -> bool:
    if usuario.rol == "dueno":
        return True
    if usuario.vendedor_id is not None:   # un vendedor solo ve tareas de su cartera
        return t["entidad"].get("vendedor_id") is not None and str(t["entidad"]["vendedor_id"]) == str(usuario.vendedor_id) \
            and any(a.get("rol_plataforma") == usuario.rol for a in t["acciones"])
    return t["rol_plataforma"] == usuario.rol or any(a.get("rol_plataforma") == usuario.rol for a in t["acciones"])


def listar_todas(estado: str = "abiertas") -> list[dict]:
    """Todas las tareas (uso interno del sistema, sin filtro de rol)."""
    return listar(Usuario(id="sistema", nombre="Sistema", rol="dueno"), estado)


def ultima_ejecucion(fte: str | None = None) -> dict | None:
    con = _conectar()
    try:
        r = con.execute("SELECT at, hoy, resumen FROM ejecucion WHERE fuente=? ORDER BY at DESC LIMIT 1", (fte or _fuente(),)).fetchone()
    finally:
        con.close()
    return {"at": r["at"], "hoy": r["hoy"], **json.loads(r["resumen"])} if r else None


def al_dia(ahora: datetime | None = None) -> dict:
    """Corre las reglas si nunca corrieron con esta fuente o la última vez fue otro día."""
    ahora = ahora or datetime.now()
    ultima = ultima_ejecucion()
    if not ultima or ultima["at"][:10] != ahora.date().isoformat():
        return ejecutar(ahora=ahora)
    return ultima


def listar(usuario: Usuario, estado: str = "abiertas") -> list[dict]:
    con = _conectar()
    try:
        if estado == "abiertas":
            filtro, args = "estado IN ('nueva','en_curso','vencida')", ()
        elif estado == "cerradas":
            filtro, args = "estado IN ('resuelta','descartada','cerrada_automatica')", ()
        else:
            filtro, args = "1=1", ()
        filas = [_fila(r) for r in con.execute(f"SELECT * FROM actividad WHERE fuente=? AND {filtro} ORDER BY "
                                               "CASE estado WHEN 'vencida' THEN 0 ELSE 1 END, puntaje DESC, id",
                                               (_fuente(), *args))]
    finally:
        con.close()
    return [t for t in filas if _visible(t, usuario)]


def obtener(tarea_id: int, usuario: Usuario) -> dict:
    con = _conectar()
    try:
        r = con.execute("SELECT * FROM actividad WHERE id=? AND fuente=?", (tarea_id, _fuente())).fetchone()
    finally:
        con.close()
    if not r:
        raise KeyError("No existe esa tarea.")
    t = _fila(r)
    if not _visible(t, usuario):
        raise PermissionError("Esa tarea no es de tu rol.")
    return t


def cambiar_estado(tarea_id: int, usuario: Usuario, estado: str, resolucion: str | None = None,
                   comentario: str | None = None, ahora: datetime | None = None) -> dict:
    ahora = ahora or datetime.now()
    t = obtener(tarea_id, usuario)
    if t["estado"] in catalogo.CERRADAS:
        raise ValueError("La tarea ya está cerrada.")
    act = catalogo.actividad(t["tipo"])
    if estado == "en_curso":
        cambios = {"estado": "en_curso"}
    elif estado in ("resuelta", "descartada"):
        if resolucion not in act["resoluciones"]:
            raise ValueError(f"Elegí una resolución: {', '.join(act['resoluciones'])}.")
        if estado == "resuelta" and resolucion == "falso_positivo":
            estado = "descartada"
        cambios = {"estado": estado, "resolucion": resolucion, "resuelta_at": ahora.isoformat(timespec="seconds"),
                   "resuelta_por": usuario.nombre}
    else:
        raise ValueError("Estado no válido: en_curso, resuelta o descartada.")
    if comentario is not None:
        cambios["comentario"] = comentario.strip()[:1000]
    cambios["actualizada_at"] = ahora.isoformat(timespec="seconds")
    con = _conectar()
    try:
        con.execute(f"UPDATE actividad SET {', '.join(f'{k}=?' for k in cambios)} WHERE id=?", (*cambios.values(), tarea_id))
        siguiente = SEGUIMIENTOS.get((t["tipo"], resolucion)) if estado == "resuelta" else None
        nueva_id = None
        if siguiente:
            c = catalogo.caso(t["tipo"], siguiente)
            det = Deteccion(t["tipo"], siguiente, t["clave_dedupe"], f"{c['nombre']}: {t['entidad'].get('producto', '')} en "
                            f"{t['entidad'].get('sucursal', '')}".strip(), t["impacto_estimado"] or 0, entidad=t["entidad"],
                            evidencia=t["evidencia"], notas=[f"Sigue de la tarea #{t['id']} resuelta como «{resolucion.replace('_', ' ')}»."])
            nueva_id = _crear(con, t["fuente"], det, ahora, ahora.date(), origen="seguimiento")
        _marcar_notificables(con, t["fuente"])
        con.commit()
    finally:
        con.close()
    resultado = obtener(tarea_id, usuario)
    resultado["seguimiento_id"] = nueva_id
    return resultado


def precision(usuario: Usuario | None = None, hoy: date | None = None) -> dict[str, dict]:
    """Por actividad, en las últimas 4 semanas: confirmadas / cerradas a mano, y qué proponer."""
    hoy = hoy or date.today()
    desde = (hoy - timedelta(days=28)).isoformat()
    con = _conectar()
    try:
        filas = con.execute("SELECT tipo, resolucion, COUNT(*) FROM actividad WHERE fuente=? AND estado IN ('resuelta','descartada') "
                            "AND resuelta_at >= ? GROUP BY tipo, resolucion", (_fuente(), desde)).fetchall()
        detectadas = dict(con.execute("SELECT tipo, COUNT(*) FROM actividad WHERE fuente=? AND detectada_at >= ? GROUP BY tipo",
                                      (_fuente(), desde)).fetchall())
    finally:
        con.close()
    res = {}
    for act_id, act in catalogo.actividades().items():
        cerradas = sum(n for t, _r, n in filas if t == act_id)
        confirmadas = sum(n for t, r, n in filas if t == act_id and r in act.get("resolucion_confirmada", []))
        valor = confirmadas / cerradas if cerradas else None
        propuesta = None
        if valor is not None and cerradas >= 5 and valor < 0.6:
            propuesta = "Muchos falsos positivos: conviene endurecer los parámetros."
        elif valor is not None and cerradas >= 5 and valor > 0.9 and detectadas.get(act_id, 0) < 5:
            propuesta = "Acierta casi siempre con pocas detecciones: se pueden relajar los parámetros."
        res[act_id] = {"cerradas": cerradas, "confirmadas": confirmadas, "precision": round(valor, 3) if valor is not None else None,
                       "detectadas_4_semanas": detectadas.get(act_id, 0), "propuesta": propuesta}
    return res


def archivo_csv(tarea_id: int, usuario: Usuario) -> tuple[str, str]:
    """El adjunto de la tarea (pedido sugerido, lista de remarcación) como CSV para revisar y cargar en el sistema."""
    t = obtener(tarea_id, usuario)
    if not t["detalle"]:
        raise KeyError("Esta tarea no tiene archivo adjunto.")
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";")
    w.writerow(t["detalle"]["columnas"])
    for fila in t["detalle"]["filas"]:
        w.writerow(["" if v is None else str(v).replace(".", ",") if isinstance(v, float) else v for v in fila])
    nombre = f"{t['tipo']}_{t['caso']}_{t['id']}.csv".replace("-", "")
    return nombre, salida.getvalue()


def resumen(usuario: Usuario) -> dict:
    """Todo lo que la pestaña Actividades necesita."""
    ejecucion = al_dia()
    abiertas = listar(usuario, "abiertas")
    cerradas = listar(usuario, "cerradas")[-50:]
    cat = catalogo.catalogo()
    return {
        "ejecucion": ejecucion,
        "abiertas": abiertas,
        "cerradas": sorted(cerradas, key=lambda t: t.get("resuelta_at") or "", reverse=True),
        "precision": precision(usuario),
        "catalogo": [{"id": a["id"], "nombre": a["nombre"], "caso_de_negocio": a["caso_de_negocio"], "frecuencia": a["frecuencia"],
                      "resoluciones": a["resoluciones"], "confirmadas": a.get("resolucion_confirmada", []),
                      "casos": {c["codigo"]: {"nombre": c["nombre"], "condicion": c["condicion"], "cierre": c.get("cierre")}
                                for c in a["casos"]}}
                     for a in cat["actividades"]],
        "totales": {
            "abiertas": len(abiertas),
            "vencidas": sum(1 for t in abiertas if t["estado"] == "vencida"),
            "criticas": sum(1 for t in abiertas if t["prioridad"] == "critica"),
            "impacto": round(sum(t["impacto_estimado"] or 0 for t in abiertas), 2),
        },
    }


def en_plazo(desde: date, hasta: date) -> tuple[float | None, int]:
    """Tareas cerradas a mano en el período dentro de su plazo / (cerradas + las que vencieron en el período sin resolver)."""
    con = _conectar()
    try:
        filas = con.execute("SELECT estado, resuelta_at, fecha_limite FROM actividad WHERE fuente=? AND ("
                            "(estado IN ('resuelta','descartada') AND substr(resuelta_at, 1, 10) BETWEEN ? AND ?) OR "
                            "(estado = 'vencida' AND fecha_limite BETWEEN ? AND ?))",
                            (_fuente(), desde.isoformat(), hasta.isoformat(), desde.isoformat(), hasta.isoformat())).fetchall()
    finally:
        con.close()
    if not filas:
        return None, 0
    ok = sum(1 for e, r, lim in filas if e != "vencida" and (not lim or r[:10] <= lim))
    return round(ok / len(filas), 4), len(filas)
