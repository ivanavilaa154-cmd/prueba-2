"""Privacidad y cumplimiento (13.5): política aceptada, acceso a los datos, baja de la empresa, supresión de un cliente y copias."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import db, permisos, privacidad, sesiones
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])


@api.get("/privacidad")
def estado_privacidad(ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        u = db.fila(conn, "SELECT privacidad_version, privacidad_aceptada_at FROM usuarios WHERE id=%s", (ctx.usuario_id,))
        baja = privacidad.estado_baja(conn, ctx.org_id) if ctx.org_id else None
    return respuesta({"version": privacidad.VERSION_POLITICA, "aceptada": bool(u and u["privacidad_version"] == privacidad.VERSION_POLITICA),
                      "aceptada_at": u["privacidad_aceptada_at"] if u else None, "baja": baja, "dias_baja": privacidad.DIAS_BAJA})


@api.post("/privacidad/aceptar")
def aceptar_privacidad(request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE usuarios SET privacidad_version=%s, privacidad_aceptada_at=now() WHERE id=%s",
                        (privacidad.VERSION_POLITICA, ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "aceptar", "politica_privacidad", privacidad.VERSION_POLITICA, ip=sesiones.ip_de(request))
    return respuesta({"ok": True})


@api.get("/empresa/exportar")
def exportar_empresa(request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Derecho de acceso: todos los datos de la empresa en un ZIP (un CSV por tabla)."""
    permisos.exigir(ctx, "configurar_empresa")
    with db.transaccion(ctx) as conn:
        contenido = privacidad.exportar(conn, ctx.org_id)
        sesiones.auditar(conn, ctx, ctx.usuario_id, "exportar", "empresa", ctx.org_id, {"bytes": len(contenido)}, sesiones.ip_de(request))
    nombre = f"datos-empresa-{datetime.now().strftime('%Y%m%d')}.zip"
    return Response(contenido, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


class PedidoBaja(BaseModel):
    confirmacion: str = Field(max_length=200)          # el nombre de la empresa, escrito a mano


@api.post("/empresa/baja")
def pedir_baja(datos: PedidoBaja, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Derecho de supresión: la empresa y todos sus datos se borran al terminar el plazo; hasta entonces se puede cancelar."""
    permisos.exigir(ctx, "configurar_empresa")
    if ctx.rol != "dueno" and not ctx.es_superadmin:
        raise HTTPException(status_code=403, detail="La baja la pide el dueño.")
    with db.transaccion(ctx) as conn:
        org = db.fila(conn, "SELECT nombre FROM organizaciones WHERE id=%s", (ctx.org_id,))
        if datos.confirmacion.strip().lower() != org["nombre"].strip().lower():
            raise HTTPException(status_code=400, detail=f"Para confirmar escribí el nombre de la empresa: {org['nombre']}.")
        with conn.cursor() as cur:
            cur.execute("UPDATE organizaciones SET baja_solicitada_at=now(), baja_solicitada_por=%s WHERE id=%s AND baja_solicitada_at IS NULL",
                        (ctx.usuario_id, ctx.org_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "pedir_baja", "empresa", ctx.org_id, {"dias": privacidad.DIAS_BAJA}, sesiones.ip_de(request))
        return respuesta(privacidad.estado_baja(conn, ctx.org_id))


@api.delete("/empresa/baja")
def cancelar_baja(request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    with db.transaccion(ctx) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE organizaciones SET baja_solicitada_at=NULL, baja_solicitada_por=NULL WHERE id=%s", (ctx.org_id,))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "cancelar_baja", "empresa", ctx.org_id, {}, sesiones.ip_de(request))
    return respuesta({"ok": True})


@api.get("/clientes/buscar")
def buscar_cliente(q: str, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    if len(q.strip()) < 3:
        return respuesta([])
    with db.transaccion(ctx) as conn:
        return respuesta(db.filas(conn, """SELECT id, identificador, nombre, alta FROM clientes WHERE anonimizado_at IS NULL
                                           AND (identificador ILIKE %(q)s OR nombre ILIKE %(q)s) ORDER BY nombre LIMIT 20""",
                                  {"q": f"%{q.strip()}%"}))


@api.post("/clientes/{cliente_id}/suprimir")
def suprimir_cliente(cliente_id: int, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Supresión de un cliente final: se borran sus datos personales; sus compras quedan sin identificar."""
    permisos.exigir(ctx, "configurar_empresa")
    with db.transaccion(ctx) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE clientes SET identificador=NULL, nombre=NULL, consentimiento=false, anonimizado_at=now() "
                        "WHERE id=%s AND anonimizado_at IS NULL", (cliente_id,))
            if not cur.rowcount:
                raise HTTPException(status_code=404, detail="No existe ese cliente (o ya se suprimieron sus datos).")
        sesiones.auditar(conn, ctx, ctx.usuario_id, "suprimir_datos", "cliente", cliente_id, {}, sesiones.ip_de(request))
    return respuesta({"ok": True})


def _superadmin(ctx: db.Contexto = Depends(sesiones.contexto)) -> db.Contexto:
    if not ctx.es_superadmin:
        raise HTTPException(status_code=403, detail="Solo para la administración de la plataforma.")
    return ctx


@api.get("/plataforma/respaldos")
def listar_respaldos(ctx: db.Contexto = Depends(_superadmin)):
    return respuesta({"copias": privacidad.copias(), "guardadas": privacidad.COPIAS_A_GUARDAR,
                      "bajas": _bajas_pendientes()})


def _bajas_pendientes() -> list[dict]:
    with db.transaccion(superadmin=True) as conn:
        return db.filas(conn, "SELECT id, nombre, baja_solicitada_at FROM organizaciones WHERE baja_solicitada_at IS NOT NULL ORDER BY 3")


@api.post("/plataforma/respaldos")
def respaldar_ahora(ctx: db.Contexto = Depends(_superadmin)):
    try:
        archivo = privacidad.respaldar()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    with db.transaccion(ctx, superadmin=True) as conn:
        sesiones.auditar(conn, None, ctx.usuario_id, "respaldar", "base", archivo.name, {})
    return respuesta({"archivo": archivo.name, "bytes": archivo.stat().st_size})
