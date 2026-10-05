"""Agente de sincronización local (SPEC v2, sección 5.1).

Muchos sistemas de caja de pymes viven en una PC del local, sin API ni nube. El agente (`tools/agente/agente_sync.py`) vigila una
carpeta donde ese sistema deja sus exportaciones (CSV o Excel) y las sube acá. Del lado del servidor se usa el mismo importador que
Datos → Importar: si las columnas de ese archivo ya se mapearon una vez, se importa solo; si no, queda esperando que el dueño confirme
las columnas en Datos → Importar (después, los siguientes entran solos). Reimportar el mismo archivo no duplica (huella del contenido).

Seguridad: el agente se identifica con un token propio (se muestra una sola vez; se guarda solo su hash) y viaja por HTTPS. El token
solo sirve para subir archivos y reportar estado de su empresa; se revoca desde Datos → Conexiones.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from . import db, importar, permisos, seguridad, sesiones
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])
TAMANO_MAXIMO = 40 * 1024 * 1024
PREFIJOS = {"venta": "ventas", "ventas": "ventas", "stock": "stock", "producto": "productos", "productos": "productos", "articulos": "productos",
            "compra": "compras", "compras": "compras", "cliente": "clientes", "clientes": "clientes", "pedido": "pedidos", "pedidos": "pedidos",
            "cuenta": "cuenta_corriente", "corriente": "cuenta_corriente", "cobranza": "cuenta_corriente", "precio": "precios", "precios": "precios", "lista": "precios", "delivery": "delivery"}


def tipo_de_archivo(nombre: str) -> str | None:
    """El tipo sale del nombre del archivo: ventas_2026-10-05.csv → ventas; stock.xlsx → stock."""
    base = re.split(r"[^a-záéíóúñ]+", nombre.lower())
    return next((PREFIJOS[p] for p in base if p in PREFIJOS), None)


# ------------------------------------------------------------------------------ administración (el dueño, con su sesión)
class AgenteNuevo(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)


@api.get("/agentes")
def listar(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_conexiones")
    with db.transaccion(ctx) as conn:
        agentes = db.filas(conn, """SELECT id, nombre, activo, version, equipo, carpeta, ultima_conexion, ultima_subida, archivos_subidos, pendientes,
                                           ultimo_error, ultimo_error_at, created_at, base, consultas FROM agentes_sincronizacion ORDER BY activo DESC, id""")
        esperando = db.filas(conn, """SELECT id, agente_id, tipo, nombre_archivo, created_at FROM lotes_importacion
                                      WHERE agente_id IS NOT NULL AND estado = 'pendiente' ORDER BY id DESC LIMIT 20""")
        return respuesta({"agentes": agentes, "esperando_columnas": esperando})


@api.post("/agentes")
def crear(datos: AgenteNuevo, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_conexiones")
    token = "ag_" + seguridad.token()
    with db.transaccion(ctx) as conn:
        a = db.fila(conn, "INSERT INTO agentes_sincronizacion (org_id, nombre, token_hash, created_by) VALUES (%s,%s,%s,%s) RETURNING id",
                    (ctx.org_id, datos.nombre.strip(), seguridad.hash_token(token), ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "crear", "agente", a["id"], {"nombre": datos.nombre}, sesiones.ip_de(request))
    return respuesta({"id": a["id"], "token": token,
                      "aviso": "Copiá este token ahora: no se vuelve a mostrar. Pegalo en agente.ini de la PC del local."}, 201)


@api.delete("/agentes/{agente_id}")
def revocar(agente_id: int, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_conexiones")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("UPDATE agentes_sincronizacion SET activo = false WHERE id = %s", (agente_id,))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="No existe ese agente.")
        sesiones.auditar(conn, ctx, ctx.usuario_id, "revocar", "agente", agente_id, None, sesiones.ip_de(request))
    return respuesta({"ok": True})


# ------------------------------------------------------------------------------ lo que llama el agente (con su token)
def agente_de(authorization: str | None = Header(default=None)) -> tuple[db.Contexto, dict]:
    if not authorization or not authorization.startswith("Agente "):
        raise HTTPException(status_code=401, detail="Falta el token del agente.")
    with db.transaccion(superadmin=True) as conn:
        a = db.fila(conn, "SELECT id, org_id, activo, created_by FROM agentes_sincronizacion WHERE token_hash = %s",
                    (seguridad.hash_token(authorization.removeprefix("Agente ").strip()),))
    if not a or not a["activo"]:
        raise HTTPException(status_code=401, detail="Token de agente inválido o revocado.")
    # El agente importa como lo haría quien lo creó (con alcance de dueño en su empresa; la RLS lo limita a ella).
    ctx = db.Contexto(usuario_id=a["created_by"] or 0, org_id=a["org_id"], rol="dueno", nombre="Agente de sincronización", todas_ubicaciones=True)
    return ctx, a


class Latido(BaseModel):
    version: str | None = Field(default=None, max_length=40)
    equipo: str | None = Field(default=None, max_length=120)
    carpeta: str | None = Field(default=None, max_length=400)
    pendientes: int = 0
    error: str | None = Field(default=None, max_length=500)
    base: str | None = Field(default=None, max_length=20)
    consultas: list[dict] = Field(default_factory=list, max_length=50)


@api.post("/agente/latido")
def latido(datos: Latido, agente=Depends(agente_de)):
    ctx, a = agente
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        consultas = [{k: (str(q.get(k))[:300] if q.get(k) is not None and k in ("error", "nombre", "tipo", "ultima", "marca") else q.get(k))
                      for k in ("nombre", "tipo", "ultima", "filas", "error", "marca")} for q in datos.consultas]
        cur.execute("""UPDATE agentes_sincronizacion SET ultima_conexion = now(), version = %s, equipo = %s, carpeta = %s, pendientes = %s,
                       ultimo_error = coalesce(%s, ultimo_error), ultimo_error_at = CASE WHEN %s::text IS NULL THEN ultimo_error_at ELSE now() END,
                       base = %s, consultas = %s WHERE id = %s""",
                    (datos.version, datos.equipo, datos.carpeta, datos.pendientes, datos.error, datos.error, datos.base, json.dumps(consultas), a["id"]))
    return respuesta({"ok": True, "hora_servidor": datetime.now().astimezone()})


@api.post("/agente/archivo")
async def subir(archivo: UploadFile = File(...), tipo: str | None = Form(default=None), agente=Depends(agente_de)):
    """Recibe una exportación. Respuestas: importado, duplicado (ya se había subido), esperando_columnas o error (con el motivo)."""
    ctx, a = agente
    contenido = await archivo.read()
    nombre = archivo.filename or "archivo.csv"
    if len(contenido) > TAMANO_MAXIMO:
        raise HTTPException(status_code=413, detail="El archivo pesa más de 40 MB.")
    tipo = tipo or tipo_de_archivo(nombre)
    if tipo not in importar.CAMPOS:
        raise HTTPException(status_code=400, detail=f"No sé qué datos trae «{nombre}»: nombralo ventas_…, stock_…, productos_…, compras_… o precios_…")
    try:
        with db.transaccion(ctx) as conn:
            r = importar.analizar(conn, ctx, tipo, nombre, contenido)
            with conn.cursor() as cur:
                cur.execute("UPDATE lotes_importacion SET agente_id = %s WHERE id = %s", (a["id"], r["lote_id"]))
                cur.execute("UPDATE agentes_sincronizacion SET ultima_conexion = now(), ultima_subida = now(), archivos_subidos = archivos_subidos + 1 "
                            "WHERE id = %s", (a["id"],))
            if r["ya_importado"]:
                with conn.cursor() as cur:
                    cur.execute("UPDATE lotes_importacion SET estado = 'duplicado' WHERE id = %s", (r["lote_id"],))
                return respuesta({"estado": "duplicado", "lote_id": r["lote_id"], "mensaje": "Ese archivo ya se había importado: no se duplica."})
            exacto = all(c in r["encabezados"] for c, _, obligatorio in importar.CAMPOS[tipo] if obligatorio)
            if not r["mapeo_recordado"] and exacto:
                # Columnas con el nombre exacto de cada dato (lo que traen las consultas del agente): no hace falta confirmarlas.
                r["mapeo"] = {c: c if c in r["encabezados"] else None for c, _, _ in importar.CAMPOS[tipo]}
            elif not r["mapeo_recordado"]:
                return respuesta({"estado": "esperando_columnas", "lote_id": r["lote_id"],
                                  "mensaje": "Primera vez con este formato: confirmá las columnas en Datos → Importar. Los siguientes entran solos."})
            v = importar.validar(conn, ctx, r["lote_id"], r["mapeo"])
            if not v["validas"]:
                return respuesta({"estado": "error", "lote_id": r["lote_id"], "mensaje": "Ninguna fila es válida.", "errores": v["errores"][:20]})
            resultado = importar.confirmar(conn, ctx, r["lote_id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    from .api_ingesta import recalcular_en_segundo_plano
    recalcular_en_segundo_plano(ctx.org_id, resultado.get("desde"))
    return respuesta({"estado": "importado", "lote_id": r["lote_id"], "filas_con_error": v["con_error"],
                      **{k: resultado[k] for k in ("importadas", "duplicadas", "mensaje") if k in resultado}})
