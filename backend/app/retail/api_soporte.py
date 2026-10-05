"""Costo de servir (SPEC v2, 13.7): precisión de los pronósticos por empresa, tiempo de implementación y tickets de soporte.

- El cliente pide ayuda desde Mi cuenta (POST /soporte) y ve sus pedidos de ayuda.
- La administración de la plataforma ve el panel por empresa, registra tickets atendidos por otros medios, los resuelve con el tiempo
  dedicado y anota las horas de implementación.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import db, sesiones
from .rutas import _superadmin, respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])
TEMAS = "^(implementacion|datos|conexion|uso|error|facturacion|otro)$"


class PedidoAyuda(BaseModel):
    asunto: str = Field(min_length=3, max_length=200)
    detalle: str | None = Field(default=None, max_length=4000)
    tema: str = Field(default="uso", pattern=TEMAS)


@api.get("/soporte")
def mis_tickets(ctx: db.Contexto = Depends(sesiones.contexto)):
    if not ctx.org_id:
        raise HTTPException(status_code=409, detail="Elegí una empresa para trabajar.")
    with db.transaccion(ctx) as conn:
        return respuesta(db.filas(conn, """SELECT id, asunto, tema, estado, respuesta, created_at, resuelto_at FROM tickets_soporte
                                           ORDER BY created_at DESC LIMIT 30"""))


@api.post("/soporte")
def pedir_ayuda(datos: PedidoAyuda, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    if not ctx.org_id:
        raise HTTPException(status_code=409, detail="Elegí una empresa para trabajar.")
    with db.transaccion(ctx) as conn:
        t = db.fila(conn, """INSERT INTO tickets_soporte (org_id, asunto, detalle, tema, origen, created_by)
                             VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (ctx.org_id, datos.asunto.strip(), datos.detalle, datos.tema, "plataforma" if ctx.es_superadmin else "cliente", ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "crear", "ticket_soporte", t["id"], {"tema": datos.tema}, sesiones.ip_de(request))
    return respuesta({"id": t["id"], "mensaje": "Recibimos tu pedido de ayuda: te respondemos por email y lo ves acá."}, 201)


# ------------------------------------------------------------------------------ panel interno (administración de la plataforma)
@api.get("/plataforma/costo-de-servir")
def panel(ctx: db.Contexto = Depends(_superadmin)):
    ahora = datetime.now(timezone.utc)
    with db.transaccion(ctx, superadmin=True) as conn:
        empresas = db.filas(conn, """
            SELECT o.id, o.nombre, o.plan, o.modos, o.created_at, o.implementacion_lista_at, o.implementacion_horas, o.primer_ingreso_completo_at,
                   (SELECT count(*) FROM jsonb_object_keys(o.primer_ingreso)) primer_ingreso_confirmados,
                   (SELECT min(l.created_at) FROM lotes_importacion l WHERE l.org_id = o.id) primer_dato,
                   (SELECT count(*) FROM tickets_soporte t WHERE t.org_id = o.id AND t.estado = 'abierto') abiertos,
                   (SELECT count(*) FROM tickets_soporte t WHERE t.org_id = o.id AND t.created_at > now() - interval '90 days') tickets_90,
                   (SELECT coalesce(sum(t.minutos), 0) FROM tickets_soporte t WHERE t.org_id = o.id AND t.created_at > now() - interval '90 days') minutos_90,
                   (SELECT count(DISTINCT s.usuario_id) FROM sesiones s JOIN usuarios u ON u.id = s.usuario_id
                     WHERE u.org_id = o.id AND s.creada > now() - interval '30 days') usuarios_activos_30
            FROM organizaciones o WHERE o.tipo IS DISTINCT FROM 'distribuidor' ORDER BY o.nombre""")
        precision = {}
        for f in db.filas(conn, """SELECT DISTINCT ON (org_id) org_id, fecha, wape, mape, sesgo, cobertura, evaluados
                                   FROM precision_pronosticos ORDER BY org_id, fecha DESC"""):
            precision[f["org_id"]] = f
        anterior = {f["org_id"]: f for f in db.filas(conn, """
            SELECT DISTINCT ON (p.org_id) p.org_id, p.wape FROM precision_pronosticos p
            JOIN (SELECT org_id, max(fecha) f FROM precision_pronosticos GROUP BY 1) u ON u.org_id = p.org_id
            WHERE p.fecha <= u.f - 28 ORDER BY p.org_id, p.fecha DESC""")}
        historia = {}
        for f in db.filas(conn, "SELECT org_id, fecha, wape, mape FROM precision_pronosticos WHERE fecha > current_date - 90 ORDER BY fecha"):
            historia.setdefault(f["org_id"], []).append({"fecha": f["fecha"], "wape": f["wape"], "mape": f["mape"]})
        tickets = db.filas(conn, """SELECT t.id, t.org_id, o.nombre empresa, t.asunto, t.detalle, t.tema, t.estado, t.origen, t.minutos, t.respuesta,
                                           t.created_at, t.resuelto_at, u.nombre autor
                                    FROM tickets_soporte t JOIN organizaciones o ON o.id = t.org_id LEFT JOIN usuarios u ON u.id = t.created_by
                                    ORDER BY t.estado = 'resuelto', t.created_at DESC LIMIT 100""")
    filas = []
    for e in empresas:
        lista = e["implementacion_lista_at"]
        p = precision.get(e["id"])
        a = anterior.get(e["id"])
        filas.append({**e, "dias_implementacion": (lista - e["created_at"]).days if lista else None,
                      "dias_desde_alta": (ahora - e["created_at"]).days,
                      "horas_soporte_90": round(e["minutos_90"] / 60, 1),
                      "precision": p, "historia": historia.get(e["id"], []),
                      "wape_hace_4_semanas": a["wape"] if a else None})
    con = [f for f in filas if f["dias_implementacion"] is not None]
    resumen = {"empresas": len(filas), "abiertos": sum(f["abiertos"] for f in filas),
               "horas_soporte_90": round(sum(f["minutos_90"] for f in filas) / 60, 1),
               "dias_implementacion_promedio": round(sum(f["dias_implementacion"] for f in con) / len(con), 1) if con else None,
               "sin_implementar": sum(1 for f in filas if f["implementacion_lista_at"] is None)}
    return respuesta({"resumen": resumen, "empresas": filas, "tickets": tickets})


class TicketPlataforma(PedidoAyuda):
    org_id: int
    minutos: int = Field(default=0, ge=0, le=100000)
    resuelto: bool = False


@api.post("/plataforma/soporte")
def registrar(datos: TicketPlataforma, ctx: db.Contexto = Depends(_superadmin)):
    """Un ticket atendido por teléfono, WhatsApp o email: se registra con el tiempo dedicado."""
    with db.transaccion(ctx, superadmin=True) as conn:
        if not db.fila(conn, "SELECT 1 FROM organizaciones WHERE id=%s", (datos.org_id,)):
            raise HTTPException(status_code=404, detail="No existe esa empresa.")
        t = db.fila(conn, """INSERT INTO tickets_soporte (org_id, asunto, detalle, tema, origen, minutos, estado, resuelto_at, created_by)
                             VALUES (%s,%s,%s,%s,'plataforma',%s,%s,CASE WHEN %s THEN now() END,%s) RETURNING id""",
                    (datos.org_id, datos.asunto.strip(), datos.detalle, datos.tema, datos.minutos, "resuelto" if datos.resuelto else "abierto",
                     datos.resuelto, ctx.usuario_id))
    return respuesta({"id": t["id"]}, 201)


class Atencion(BaseModel):
    minutos: int = Field(default=0, ge=0, le=100000)      # se suman al tiempo ya dedicado
    respuesta: str | None = Field(default=None, max_length=4000)
    resuelto: bool = True


@api.put("/plataforma/soporte/{ticket_id}")
def atender(ticket_id: int, datos: Atencion, ctx: db.Contexto = Depends(_superadmin)):
    with db.transaccion(ctx, superadmin=True) as conn, conn.cursor() as cur:
        cur.execute("""UPDATE tickets_soporte SET minutos = minutos + %s, respuesta = coalesce(%s, respuesta),
                           estado = CASE WHEN %s THEN 'resuelto' ELSE 'abierto' END,
                           resuelto_at = CASE WHEN %s THEN coalesce(resuelto_at, now()) END WHERE id = %s""",
                    (datos.minutos, datos.respuesta, datos.resuelto, datos.resuelto, ticket_id))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="No existe ese ticket.")
    return respuesta({"ok": True})


class Implementacion(BaseModel):
    horas: float = Field(ge=0, le=10000)


@api.put("/plataforma/empresas/{org_id}/implementacion")
def horas_implementacion(org_id: int, datos: Implementacion, ctx: db.Contexto = Depends(_superadmin)):
    with db.transaccion(ctx, superadmin=True) as conn, conn.cursor() as cur:
        cur.execute("UPDATE organizaciones SET implementacion_horas = %s WHERE id = %s", (datos.horas, org_id))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="No existe esa empresa.")
    return respuesta({"ok": True})

