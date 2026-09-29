"""Planes y suscripción (13.6): estado para el dueño y administración de planes y pagos para la plataforma."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import db, sesiones, suscripcion
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])
MEDIOS = ("transferencia", "mercado_pago", "efectivo", "otro")


def _planes(conn) -> list[dict]:
    return db.filas(conn, "SELECT * FROM planes WHERE activo ORDER BY orden")


@api.get("/suscripcion")
def mi_suscripcion(ctx: db.Contexto = Depends(sesiones.contexto)):
    if not ctx.org_id:
        raise HTTPException(status_code=409, detail="Elegí una empresa.")
    with db.transaccion(ctx) as conn:
        return respuesta({"estado": suscripcion.estado(conn, ctx.org_id), "planes": _planes(conn), "modulos": suscripcion.MODULOS,
                          "pagos": db.filas(conn, "SELECT fecha, plan, monto, medio, cubre_hasta, nota FROM pagos_suscripcion "
                                                  "WHERE org_id=%s ORDER BY fecha DESC, id DESC LIMIT 24", (ctx.org_id,))})


def _admin(ctx: db.Contexto = Depends(sesiones.contexto)) -> db.Contexto:
    if not ctx.es_superadmin:
        raise HTTPException(status_code=403, detail="Solo para la administración de la plataforma.")
    return ctx


@api.get("/plataforma/suscripciones")
def suscripciones(ctx: db.Contexto = Depends(_admin)):
    with db.transaccion(ctx, superadmin=True) as conn:
        empresas = db.filas(conn, "SELECT id, nombre FROM organizaciones WHERE tipo='comercio' ORDER BY nombre")
        return respuesta({"planes": _planes(conn), "modulos": suscripcion.MODULOS, "medios": MEDIOS,
                          "empresas": [{**e, **suscripcion.estado(conn, e["id"])} for e in empresas]})


class Plan(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)
    max_sucursales: int | None = Field(default=None, ge=1, le=10000)
    modulos: list[str]
    precio_mensual: Decimal | None = Field(default=None, ge=0)


@api.put("/plataforma/planes/{codigo}")
def editar_plan(codigo: str, datos: Plan, request: Request, ctx: db.Contexto = Depends(_admin)):
    if not set(datos.modulos) <= set(suscripcion.MODULOS) or "base" not in datos.modulos:
        raise HTTPException(status_code=400, detail="Los módulos son base, avanzado y completo (base siempre va).")
    with db.transaccion(ctx, superadmin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE planes SET nombre=%s, max_sucursales=%s, modulos=%s, precio_mensual=%s WHERE codigo=%s",
                        (datos.nombre, datos.max_sucursales, datos.modulos, datos.precio_mensual, codigo))
            if not cur.rowcount:
                raise HTTPException(status_code=404, detail="No existe ese plan.")
        sesiones.auditar(conn, None, ctx.usuario_id, "editar", "plan", codigo, datos.model_dump(mode="json"), sesiones.ip_de(request))
        return respuesta(_planes(conn))


class CambioPlan(BaseModel):
    plan: str
    prueba_hasta: date | None = None


@api.put("/plataforma/empresas/{org_id}/plan")
def cambiar_plan(org_id: int, datos: CambioPlan, request: Request, ctx: db.Contexto = Depends(_admin)):
    with db.transaccion(ctx, superadmin=True) as conn:
        if not db.fila(conn, "SELECT 1 FROM planes WHERE codigo=%s AND activo", (datos.plan,)):
            raise HTTPException(status_code=400, detail="No existe ese plan.")
        with conn.cursor() as cur:
            cur.execute("UPDATE organizaciones SET plan=%s, prueba_hasta=coalesce(%s, prueba_hasta), updated_at=now() WHERE id=%s",
                        (datos.plan, datos.prueba_hasta, org_id))
            if not cur.rowcount:
                raise HTTPException(status_code=404, detail="No existe esa empresa.")
        sesiones.auditar(conn, org_id, ctx.usuario_id, "cambiar_plan", "empresa", org_id, datos.model_dump(mode="json"), sesiones.ip_de(request))
        return respuesta(suscripcion.estado(conn, org_id))


class Pago(BaseModel):
    monto: Decimal = Field(ge=0)
    medio: str
    cubre_hasta: date
    plan: str | None = None
    nota: str | None = Field(default=None, max_length=300)
    fecha: date | None = None


@api.post("/plataforma/empresas/{org_id}/pagos")
def registrar_pago(org_id: int, datos: Pago, request: Request, ctx: db.Contexto = Depends(_admin)):
    """La plataforma registra un pago recibido: la empresa queda al día hasta «cubre_hasta» (y en el plan indicado)."""
    if datos.medio not in MEDIOS:
        raise HTTPException(status_code=400, detail=f"Medio de pago: {', '.join(MEDIOS)}.")
    with db.transaccion(ctx, superadmin=True) as conn:
        org = db.fila(conn, "SELECT plan FROM organizaciones WHERE id=%s", (org_id,))
        if not org:
            raise HTTPException(status_code=404, detail="No existe esa empresa.")
        plan = datos.plan or (org["plan"] if org["plan"] != "prueba" else None)
        if not plan or not db.fila(conn, "SELECT 1 FROM planes WHERE codigo=%s AND codigo <> 'prueba'", (plan,)):
            raise HTTPException(status_code=400, detail="Elegí el plan que paga (inicial, crecimiento o cadena).")
        with conn.cursor() as cur:
            cur.execute("INSERT INTO pagos_suscripcion (org_id, fecha, plan, monto, medio, cubre_hasta, nota, registrado_por) "
                        "VALUES (%s, coalesce(%s, current_date), %s, %s, %s, %s, %s, %s)",
                        (org_id, datos.fecha, plan, datos.monto, datos.medio, datos.cubre_hasta, datos.nota, ctx.usuario_id))
            cur.execute("UPDATE organizaciones SET plan=%s, pagado_hasta=greatest(coalesce(pagado_hasta, %s), %s), updated_at=now() WHERE id=%s",
                        (plan, datos.cubre_hasta, datos.cubre_hasta, org_id))
        sesiones.auditar(conn, org_id, ctx.usuario_id, "registrar_pago", "suscripcion", org_id, datos.model_dump(mode="json"), sesiones.ip_de(request))
        return respuesta(suscripcion.estado(conn, org_id))
