"""Pruebas guiadas manuales (config/pruebas/casos_manuales.yml) y evidencias adjuntas."""
from __future__ import annotations

import json
import re
import uuid

import yaml

from .. import config
from . import almacen, incidencias

TIPOS_EVIDENCIA = {"image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf", "text/plain"}
MAX_EVIDENCIA = 10 * 1024 * 1024


def sincronizar_catalogo() -> int:
    """Carga los casos del YAML (los nuevos se agregan; los que ya no están se desactivan)."""
    doc = yaml.safe_load((config.DIR_CONFIG / "pruebas" / "casos_manuales.yml").read_text(encoding="utf-8")) or {}
    codigos = []
    with almacen.conectar() as con:
        for c in doc.get("casos", []):
            codigos.append(c["codigo"])
            con.execute("INSERT INTO prueba_caso (codigo, titulo, pantalla, rol_ejecucion, pasos, resultado_esperado, activo, creado_at) "
                        "VALUES (?,?,?,?,?,?,1,?) ON CONFLICT(codigo) DO UPDATE SET titulo=excluded.titulo, pantalla=excluded.pantalla, "
                        "rol_ejecucion=excluded.rol_ejecucion, pasos=excluded.pasos, resultado_esperado=excluded.resultado_esperado, activo=1",
                        (c["codigo"], c["titulo"], c.get("pantalla"), c.get("rol"), json.dumps(c.get("pasos", []), ensure_ascii=False),
                         c.get("esperado"), almacen.ahora()))
        if codigos:
            con.execute(f"UPDATE prueba_caso SET activo=0 WHERE codigo NOT IN ({','.join('?' * len(codigos))})", codigos)
    return len(codigos)


def listar() -> list[dict]:
    sincronizar_catalogo()
    casos = almacen.filas("SELECT * FROM prueba_caso WHERE activo=1 ORDER BY codigo")
    ultimas = {}
    for e in almacen.filas("SELECT * FROM prueba_ejecucion WHERE tipo='manual' ORDER BY id"):
        ultimas[e["caso_id"]] = e
    return [{**c, "pasos": json.loads(c["pasos"] or "[]"), "ultima": ultimas.get(c["id"])} for c in casos]


def ejecutar(caso_id: int, estado: str, usuario: str, comentario: str | None = None, evidencia_id: int | None = None) -> dict:
    if estado not in ("aprobado", "fallido"):
        raise ValueError("El resultado es «aprobado» o «fallido».")
    caso = almacen.filas("SELECT * FROM prueba_caso WHERE id=?", (caso_id,))
    if not caso:
        raise KeyError("No existe ese caso de prueba.")
    caso = caso[0]
    if estado == "fallido" and not (comentario or "").strip():
        raise ValueError("Contá qué pasó en el comentario.")
    incidencia_id = None
    if estado == "fallido":
        evidencia = obtener_evidencia(evidencia_id) if evidencia_id else None
        incidencia_id = incidencias.crear("prueba_manual", f"Falló {caso['codigo']}: {caso['titulo']}", usuario, tipo="pantalla",
                                          descripcion=comentario or "", pantalla=caso["pantalla"], causa="pantalla",
                                          evidencia={"archivo": evidencia} if evidencia else None)
    with almacen.conectar() as con:
        cur = con.execute("INSERT INTO prueba_ejecucion (tipo, caso_id, entorno, estado, comentario, evidencia_id, usuario, inicio_at, fin_at, "
                          "incidencia_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          ("manual", caso_id, "produccion", estado, comentario, evidencia_id, usuario, almacen.ahora(), almacen.ahora(),
                           incidencia_id))
    return {"id": cur.lastrowid, "estado": estado, "incidencia_id": incidencia_id}


def guardar_evidencia(nombre: str, tipo: str, contenido: bytes, usuario: str) -> dict:
    if tipo not in TIPOS_EVIDENCIA:
        raise ValueError("Adjuntá una imagen (PNG, JPG), un PDF o un texto.")
    if len(contenido) > MAX_EVIDENCIA:
        raise ValueError("El archivo supera los 10 MB.")
    almacen.EVIDENCIAS.mkdir(parents=True, exist_ok=True)
    limpio = re.sub(r"[^A-Za-z0-9._-]", "_", nombre or "evidencia")[-80:]
    ruta = almacen.EVIDENCIAS / f"{uuid.uuid4().hex[:12]}_{limpio}"
    ruta.write_bytes(contenido)
    with almacen.conectar() as con:
        cur = con.execute("INSERT INTO evidencia (nombre, tipo, ruta, tamano, subido_por, subido_at) VALUES (?,?,?,?,?,?)",
                          (limpio, tipo, ruta.name, len(contenido), usuario, almacen.ahora()))
    return {"id": cur.lastrowid, "nombre": limpio}


def obtener_evidencia(id_: int) -> dict | None:
    r = almacen.filas("SELECT * FROM evidencia WHERE id=?", (id_,))
    return r[0] if r else None
