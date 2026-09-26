"""Incidencias unificadas (automáticas, de muestra, de pruebas manuales y de la revisión independiente).

Regla: una incidencia de datos no se cierra sin un test de regresión vinculado (que exista
en el repositorio) o una definición registrada en la ficha de cuadratura.
"""
from __future__ import annotations

import json
import re

import yaml

from .. import config
from . import almacen

ESTADOS = ("abierta", "en_analisis", "para_revisar", "resuelta", "descartada")
CERRADOS = ("resuelta", "descartada")
# Causas del checklist de cuadratura (y otras para pantallas y pruebas)
CAUSAS = {
    "impuestos": "Con o sin impuestos", "fecha": "Qué fecha se usa (pedido, factura, entrega)", "zona_horaria": "Zona horaria",
    "estados": "Estados incluidos o excluidos", "notas_de_credito": "Notas de crédito y devoluciones",
    "envio_no_producto": "Envío y líneas que no son producto", "alcance": "Alcance (empresa, sucursal, canal)",
    "moneda": "Moneda y cotización", "sincronizacion": "Datos desactualizados o sin sincronizar", "borrado_en_origen": "Borrado en el origen",
    "mapeo": "Valor sin mapear o mal mapeado", "permisos": "Permisos", "pantalla": "Pantalla o experiencia de uso",
    "prueba_automatica": "Prueba automática que falla", "otra": "Otra",
}
TIPOS = ("datos", "pantalla", "permiso", "prueba", "otro")
CASOS_DIR = config.BACKEND / "tests" / "cuadratura" / "casos"
PERFILES_DIR = config.DIR_CONFIG / "perfiles"


def _historial(con, id_: int, usuario: str, texto: str) -> None:
    r = con.execute("SELECT historial FROM incidencia WHERE id=?", (id_,)).fetchone()
    h = json.loads(r[0] or "[]") if r else []
    h.append({"at": almacen.ahora(), "usuario": usuario, "texto": texto})
    con.execute("UPDATE incidencia SET historial=? WHERE id=?", (json.dumps(h, ensure_ascii=False), id_))


def crear(origen: str, titulo: str, usuario: str, tipo: str = "datos", descripcion: str = "", metrica=None, pantalla=None,
          fuente=None, fecha_dato=None, registro_clave=None, causa=None, evidencia=None, test_regresion=None,
          estado: str = "abierta") -> int:
    if tipo not in TIPOS:
        raise ValueError(f"Tipo inválido: {', '.join(TIPOS)}.")
    if causa and causa not in CAUSAS:
        causa = "otra"
    with almacen.conectar() as con:
        cur = con.execute(
            "INSERT INTO incidencia (origen, tipo, fuente, metrica, pantalla, fecha_dato, registro_clave, causa, titulo, descripcion, "
            "evidencia, estado, test_regresion, creada_por, creada_at, historial) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (origen, tipo, fuente, metrica, pantalla, fecha_dato, registro_clave, causa, titulo[:300], descripcion,
             json.dumps(evidencia, ensure_ascii=False, default=str) if evidencia is not None else None, estado, test_regresion,
             usuario, almacen.ahora(), json.dumps([{"at": almacen.ahora(), "usuario": usuario, "texto": "Creada"}], ensure_ascii=False)))
        return cur.lastrowid


def crear_si_no_existe(origen: str, titulo: str, usuario: str, **kw) -> int:
    ya = almacen.filas("SELECT id FROM incidencia WHERE titulo=? AND estado NOT IN ('resuelta', 'descartada')", (titulo[:300],))
    return ya[0]["id"] if ya else crear(origen, titulo, usuario, **kw)


def listar(estado: str | None = None, origen: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM incidencia WHERE 1=1", []
    if estado == "abiertas":
        sql += " AND estado NOT IN ('resuelta', 'descartada')"
    elif estado:
        sql += " AND estado=?"
        args.append(estado)
    if origen:
        sql += " AND origen=?"
        args.append(origen)
    return [_fila(r) for r in almacen.filas(sql + " ORDER BY id DESC", args)]


def _fila(r: dict) -> dict:
    r = dict(r)
    r["evidencia"] = json.loads(r["evidencia"]) if r.get("evidencia") else None
    r["historial"] = json.loads(r["historial"] or "[]")
    r["causa_texto"] = CAUSAS.get(r.get("causa") or "", "")
    return r


def obtener(id_: int) -> dict:
    r = almacen.filas("SELECT * FROM incidencia WHERE id=?", (id_,))
    if not r:
        raise KeyError("No existe esa incidencia.")
    return _fila(r[0])


def test_existe(ruta: str | None) -> bool:
    """El test vinculado existe en el repositorio (acepta 'tests/archivo.py::test_x' o un caso .yml)."""
    if not ruta:
        return False
    archivo = ruta.split("::")[0].strip()
    if ".." in archivo or archivo.startswith("/"):
        return False
    p = config.BACKEND / archivo
    if not p.exists():
        return False
    if "::" in ruta and p.suffix == ".py":
        nombre = ruta.split("::")[-1].strip()
        return bool(re.search(rf"def {re.escape(nombre)}\b", p.read_text(encoding="utf-8")))
    return True


def actualizar(id_: int, usuario: str, estado=None, responsable=None, test_regresion=None, definicion: str | None = None,
               causa=None, comentario: str | None = None) -> dict:
    inc = obtener(id_)
    cambios = {}
    with almacen.conectar() as con:
        if causa:
            if causa not in CAUSAS:
                raise ValueError("Causa inválida.")
            cambios["causa"] = causa
        if responsable is not None:
            cambios["responsable"] = responsable.strip()[:80]
        if test_regresion is not None:
            if test_regresion and not test_existe(test_regresion):
                raise ValueError(f"No encuentro ese test en el repositorio: {test_regresion}")
            cambios["test_regresion"] = test_regresion or None
        if definicion:
            cur = con.execute("INSERT INTO cuadratura_definicion (fuente, metrica, descripcion, estado, registrada_por, registrada_at) "
                              "VALUES (?,?,?,?,?,?)", (inc["fuente"], inc["metrica"], definicion.strip()[:2000], "registrada", usuario,
                                                        almacen.ahora()))
            cambios["definicion_id"] = cur.lastrowid
        if estado:
            if estado not in ESTADOS:
                raise ValueError(f"Estado inválido: {', '.join(ESTADOS)}.")
            if estado == "resuelta" and inc["tipo"] == "datos":
                test = cambios.get("test_regresion", inc["test_regresion"])
                defin = cambios.get("definicion_id", inc["definicion_id"])
                if not (test_existe(test) or defin):
                    raise ValueError("Una incidencia de datos no se cierra sin un test de regresión vinculado o una definición "
                                     "registrada en la ficha de cuadratura.")
            cambios["estado"] = estado
            if estado in CERRADOS:
                cambios.update(resuelta_por=usuario, resuelta_at=almacen.ahora())
        if cambios:
            con.execute(f"UPDATE incidencia SET {', '.join(f'{k}=?' for k in cambios)} WHERE id=?", (*cambios.values(), id_))
            _historial(con, id_, usuario, "; ".join(f"{k}: {v}" for k, v in cambios.items()))
        if comentario:
            _historial(con, id_, usuario, comentario.strip()[:1000])
    return obtener(id_)


def crear_caso_regresion(id_: int, usuario: str) -> dict:
    """Guarda la diferencia como caso de prueba permanente (tests/cuadratura/casos) y en el perfil del tipo de sistema."""
    inc = obtener(id_)
    if inc["tipo"] != "datos":
        raise ValueError("Solo las incidencias de datos se guardan como caso de cuadratura.")
    if not inc.get("causa") or inc["causa"] in ("otra", "prueba_automatica"):
        raise ValueError("Primero indicá la causa del checklist (impuestos, fecha, estados...).")
    CASOS_DIR.mkdir(parents=True, exist_ok=True)
    nombre = f"INC-{id_:05d}.yml"
    caso = {"id": f"INC-{id_:05d}", "fuente": inc["fuente"] or "odoo", "metrica": inc["metrica"], "causa": inc["causa"],
            "titulo": inc["titulo"], "descripcion": inc["descripcion"], "registro": inc["registro_clave"], "fecha": inc["fecha_dato"],
            "evidencia": inc["evidencia"], "creado_por": usuario, "creado_at": almacen.ahora(),
            "comprobacion": "La definición espejo de la métrica tiene que tratar este caso igual que el sistema de origen."}
    (CASOS_DIR / nombre).write_text(yaml.safe_dump(caso, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # Perfil del tipo de sistema: la lista de trampas conocidas crece con cada caso
    PERFILES_DIR.mkdir(parents=True, exist_ok=True)
    perfil = PERFILES_DIR / f"{caso['fuente']}.yml"
    datos = yaml.safe_load(perfil.read_text(encoding="utf-8")) if perfil.exists() else None
    datos = datos or {"sistema": caso["fuente"], "casos_conocidos": []}
    if caso["id"] not in [c.get("id") for c in datos.get("casos_conocidos", [])]:
        datos.setdefault("casos_conocidos", []).append({"id": caso["id"], "metrica": caso["metrica"], "causa": caso["causa"],
                                                         "titulo": caso["titulo"]})
    perfil.write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return actualizar(id_, usuario, test_regresion=f"tests/cuadratura/casos/{nombre}",
                      comentario="Guardada como caso de regresión permanente y en el perfil del sistema.")
