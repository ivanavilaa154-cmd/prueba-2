"""Copiloto (sección 13.2): chat sobre los datos del comercio, con herramientas que respetan permisos y sucursales."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import copiloto, db, sesiones, suscripcion
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"], dependencies=[Depends(suscripcion.modulo("avanzado"))])   # plan (13.6)


class Pregunta(BaseModel):
    mensaje: str = Field(min_length=1, max_length=2000)
    historial: list[dict] = Field(default_factory=list)


@api.post("/copiloto")
def preguntar(datos: Pregunta, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    if not ctx.org_id:
        raise HTTPException(status_code=409, detail="Elegí una empresa para trabajar.")
    if len(datos.historial) > 80:
        raise HTTPException(status_code=400, detail="La conversación es muy larga: empezá una nueva.")
    r = copiloto.responder(ctx, datos.mensaje, datos.historial)
    with db.transaccion(ctx) as conn:
        sesiones.auditar(conn, ctx, ctx.usuario_id, "preguntar", "copiloto", None,
                         {"mensaje": datos.mensaje[:300], "herramientas": [h["herramienta"] for h in r.herramientas]}, sesiones.ip_de(request))
    return respuesta({"texto": r.texto, "herramientas": r.herramientas, "propuestas": r.propuestas, "historial": r.historial})
