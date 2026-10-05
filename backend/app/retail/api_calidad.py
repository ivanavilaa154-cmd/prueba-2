"""Pantalla «Calidad de datos» (SPEC v2, sección 5.6): puntaje, problemas a corregir y el resumen comercial."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from . import calidad, db, permisos, sesiones
from .api_comprar import _hoy_datos
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])


@api.get("/calidad")
def ver(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        ultimo = db.fila(conn, "SELECT id, fecha, puntaje, detalle, origen, created_at FROM chequeos_calidad ORDER BY created_at DESC LIMIT 1")
        historia = db.filas(conn, "SELECT fecha, puntaje FROM chequeos_calidad ORDER BY created_at DESC LIMIT 12")
        confianza = {f["confianza"]: f["n"] for f in db.filas(conn, "SELECT confianza, count(*) n FROM calidad_productos GROUP BY 1")}
        return respuesta({"ultimo": ultimo, "historia": list(reversed(historia)), "confianza": confianza})


@api.post("/calidad/revisar")
def revisar(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "importar_datos")
    with db.transaccion(ctx) as conn:
        return respuesta(calidad.revisar(conn, ctx.org_id, _hoy_datos(conn), "manual"))
