"""Bandeja de avisos, resumen diario (email y pantalla de Inicio) y preferencias de notificación (secciones 13.1, 13.2 y 15)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import db, emails, permisos, sesiones
from .alertas import ETIQUETAS
from .api_comprar import _hoy_datos
from .explicar import num, pesos
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])
ORDEN_PRIORIDAD = "array_position(ARRAY['urgente','normal','preventiva'], a.prioridad)"


def _filtro_destino(ctx: db.Contexto) -> tuple[str, tuple]:
    """El dueño (y la plataforma) ve todos los avisos; cada rol, los que le corresponden. La sucursal la filtra la RLS."""
    if ctx.es_superadmin or ctx.rol == "dueno":
        return "", ()
    return " AND %s = ANY(a.destinatarios)", (ctx.rol,)


@api.get("/avisos")
def bandeja(estado: str = "abiertas", tipo: str | None = None, prioridad: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        extra, params = _filtro_destino(ctx)
        condicion = "a.estado IN ('nueva', 'vista', 'escalada')" if estado == "abiertas" else "a.estado IN ('resuelta', 'descartada')" \
            if estado == "cerradas" else "true"
        if tipo:
            condicion += " AND a.tipo = %s"
            params += (tipo,)
        if prioridad:
            condicion += " AND a.prioridad = %s"
            params += (prioridad,)
        filas = db.filas(conn, f"""SELECT a.*, u.nombre ubicacion, p.nombre producto, ur.nombre resuelta_por_nombre FROM alertas a
                                   LEFT JOIN ubicaciones u ON u.id = a.ubicacion_id LEFT JOIN productos p ON p.id = a.producto_id
                                   LEFT JOIN usuarios ur ON ur.id = a.resuelta_por
                                   WHERE {condicion} {extra} ORDER BY a.estado = 'escalada' DESC, {ORDEN_PRIORIDAD}, a.impacto DESC LIMIT 500""", params)
        conteo = db.filas(conn, f"""SELECT a.prioridad, count(*) n, sum(a.impacto) impacto FROM alertas a
                                    WHERE a.estado IN ('nueva', 'vista', 'escalada') {extra} GROUP BY 1""", _filtro_destino(ctx)[1])
        return respuesta({"avisos": filas, "conteo": conteo, "etiquetas": ETIQUETAS})


class Cambio(BaseModel):
    estado: str
    motivo: str | None = Field(default=None, max_length=300)


@api.put("/avisos/{aviso_id}")
def cambiar_aviso(aviso_id: int, datos: Cambio, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    if datos.estado not in ("vista", "resuelta", "descartada"):
        raise HTTPException(status_code=400, detail="Estado no válido.")
    if datos.estado == "descartada" and not (datos.motivo or "").strip():
        raise HTTPException(status_code=400, detail="Contá por qué la descartás: así el sistema aprende qué no te sirve.")
    with db.transaccion(ctx) as conn:
        extra, params = _filtro_destino(ctx)
        a = db.fila(conn, f"SELECT a.* FROM alertas a WHERE a.id=%s {extra}", (aviso_id,) + params)
        if not a:
            raise HTTPException(status_code=404, detail="No existe ese aviso (o no es para vos).")
        with conn.cursor() as cur:
            cur.execute("UPDATE alertas SET estado=%s, resuelta_por=%s, datos = datos || %s::jsonb, updated_at=now() WHERE id=%s",
                        (datos.estado, ctx.usuario_id if datos.estado != "vista" else a["resuelta_por"],
                         json.dumps({"motivo": datos.motivo or ""}), aviso_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, datos.estado, "aviso", aviso_id, {"tipo": a["tipo"], "motivo": datos.motivo}, sesiones.ip_de(request))
    return respuesta({"ok": True})


# ------------------------------------------------------------------------------ Inicio y resumen diario
def resumen_diario(conn, ctx: db.Contexto, hoy: date | None = None) -> dict:
    """Ventas de ayer contra el mismo día de la semana anterior, ganancia, 3 avisos principales y 3 acciones."""
    hoy = hoy or _hoy_datos(conn)
    ayer = hoy - timedelta(days=1)
    semana = ayer - timedelta(days=7)

    def dia(d):
        return db.fila(conn, "SELECT coalesce(sum(facturacion), 0) f, coalesce(sum(ganancia), 0) g, coalesce(sum(tickets), 0) t "
                             "FROM agg_producto_ubicacion_dia WHERE fecha=%s", (d,))
    a, b = dia(ayer), dia(semana)
    hasta_hora = datetime.now(ZoneInfo(db.fila(conn, "SELECT zona_horaria FROM organizaciones WHERE id = app_org()")["zona_horaria"]))
    hoy_hasta = db.fila(conn, """SELECT coalesce(sum(t.total), 0) f, count(*) t FROM tickets t JOIN organizaciones o ON o.id = t.org_id
                                 WHERE t.estado <> 'anulado' AND (t.fecha_hora AT TIME ZONE o.zona_horaria)::date = %s""", (hoy,))
    hace_semana_hasta = db.fila(conn, """SELECT coalesce(sum(t.total), 0) f FROM tickets t JOIN organizaciones o ON o.id = t.org_id
                                         WHERE t.estado <> 'anulado' AND (t.fecha_hora AT TIME ZONE o.zona_horaria)::date = %s
                                         AND (t.fecha_hora AT TIME ZONE o.zona_horaria)::time <= %s""",
                                 (hoy - timedelta(days=7), hasta_hora.time() if hoy == hasta_hora.date() else datetime.max.time()))
    extra, params = _filtro_destino(ctx)
    avisos = db.filas(conn, f"""SELECT a.id, a.tipo, a.prioridad, a.titulo, a.explicacion, a.impacto, a.tipo_impacto, a.accion, a.estado
                                FROM alertas a WHERE a.estado IN ('nueva','vista','escalada') {extra}
                                ORDER BY a.estado = 'escalada' DESC, {ORDEN_PRIORIDAD}, a.impacto DESC LIMIT 3""", params)
    acciones = db.filas(conn, f"""SELECT a.id, a.tipo, a.titulo, a.impacto, a.tipo_impacto, a.accion FROM alertas a
                                  WHERE a.estado IN ('nueva','vista','escalada') AND a.tipo IN ('orden_compra','transferencia','oc_escalada','quiebre','margen',
                                  'aumento_proveedor','stock_fantasma','gondola') {extra}
                                  ORDER BY a.impacto DESC LIMIT 3""", params)
    metricas = db.fila(conn, """SELECT count(*) FILTER (WHERE m.semaforo='rojo' AND u.tipo <> 'deposito') rojos,
                                       coalesce(sum(m.capital) FILTER (WHERE m.semaforo='gris' OR m.dias_sin_venta >= 90), 0) parada,
                                       coalesce(sum(m.riesgo_vencimiento), 0) riesgo, coalesce(sum(m.capital), 0) capital
                                FROM metricas_producto_actual m JOIN ubicaciones u ON u.id = m.ubicacion_id""")
    anomalias = db.fila(conn, f"SELECT count(*) n FROM alertas a WHERE a.tipo='caja' AND a.estado IN ('nueva','vista','escalada') {extra}", params)["n"]

    def var(x, y):
        return None if not y else (Decimal(x) / Decimal(y) - 1) * 100
    return {
        "fecha": hoy, "ayer": ayer, "comparado_con": semana,
        "ventas_ayer": a["f"], "ventas_semana_anterior": b["f"], "var_ventas": var(a["f"], b["f"]),
        "ganancia_ayer": a["g"], "ganancia_semana_anterior": b["g"], "var_ganancia": var(a["g"], b["g"]),
        "tickets_ayer": a["t"], "ventas_hoy": hoy_hasta["f"], "tickets_hoy": hoy_hasta["t"], "ventas_hoy_semana_anterior": hace_semana_hasta["f"],
        "var_hoy": var(hoy_hasta["f"], hace_semana_hasta["f"]),
        "productos_en_rojo": metricas["rojos"], "plata_parada": metricas["parada"], "plata_en_riesgo": metricas["riesgo"],
        "capital_en_stock": metricas["capital"], "anomalias_caja": anomalias, "avisos": avisos, "acciones": acciones,
    }


@api.get("/inicio")
def inicio(ctx: db.Contexto = Depends(sesiones.contexto)):
    if not ctx.org_id:
        raise HTTPException(status_code=409, detail="Elegí una empresa para trabajar.")
    with db.transaccion(ctx) as conn:
        r = resumen_diario(conn, ctx)
        if not permisos.puede(ctx, "ver_costos"):
            for k in ("ganancia_ayer", "ganancia_semana_anterior", "var_ganancia", "plata_parada", "plata_en_riesgo", "capital_en_stock"):
                r[k] = None
        return respuesta(r)


def html_resumen(r: dict, nombre: str, empresa: str, url: str = "") -> str:
    def v(x):
        return "" if x is None else f" ({'+' if x > 0 else ''}{num(x)} % vs. el mismo día de la semana anterior)"
    avisos = "".join(f"<li><strong>{a['titulo']}</strong><br>{a['explicacion']}</li>" for a in r["avisos"]) or "<li>No hay avisos abiertos.</li>"
    acciones = "".join(f"<li>{a['accion'].get('etiqueta', 'Ver')}: {a['titulo']} ({pesos(a['impacto'])})</li>" for a in r["acciones"]) or "<li>Nada pendiente.</li>"
    ganancia = f"<p>Ganancia bruta: <strong>{pesos(r['ganancia_ayer'])}</strong>{v(r['var_ganancia'])}.</p>" if r["ganancia_ayer"] is not None else ""
    return (f"<div style='font-family:system-ui,sans-serif;max-width:560px'><h2>Buen día, {nombre.split()[0]}</h2>"
            f"<p>Resumen de {empresa} del {r['ayer'].strftime('%d/%m/%Y')}.</p>"
            f"<p>Ventas: <strong>{pesos(r['ventas_ayer'])}</strong>{v(r['var_ventas'])} en {num(r['tickets_ayer'], 0)} tickets.</p>{ganancia}"
            f"<h3>Lo más importante</h3><ol>{avisos}</ol><h3>Acciones recomendadas</h3><ol>{acciones}</ol>"
            + (f"<p><a href='{url}'>Abrir la plataforma</a></p>" if url else "") + "</div>")


def enviar_resumenes(org_id: int, hora_local: int, hoy: date) -> int:
    """Encola el resumen diario para cada usuario que lo tiene activo a esta hora (una vez por día)."""
    from .motor import contexto_sistema
    enviados = 0
    with db.transaccion(contexto_sistema(org_id)) as conn:
        empresa = db.fila(conn, "SELECT nombre FROM organizaciones WHERE id=%s", (org_id,))["nombre"]
        usuarios = db.filas(conn, "SELECT u.id, u.email, u.nombre, u.rol FROM usuarios u WHERE u.org_id=%s AND u.activo AND u.resumen_diario "
                                  "AND u.hora_resumen=%s AND NOT EXISTS (SELECT 1 FROM emails e WHERE e.usuario_id=u.id AND e.tipo='resumen_diario' "
                                  "AND e.created_at > now() - interval '20 hours')", (org_id, hora_local))
    for u in usuarios:
        from . import sesiones as S
        ctx = S.contexto_de_sesion({"usuario_id": u["id"], "org_activa": None})
        with db.transaccion(ctx) as conn:
            r = resumen_diario(conn, ctx, hoy)
            if not permisos.puede(ctx, "ver_costos"):
                r["ganancia_ayer"] = None
            emails.encolar(conn, org_id, u["email"], f"Resumen del día — {empresa}", html_resumen(r, u["nombre"], empresa), "resumen_diario", u["id"])
            emails.enviar_pendientes(conn)
        enviados += 1
    return enviados


def enviar_urgentes(org_id: int) -> int:
    """Avisos urgentes nuevos → email a sus destinatarios que lo tengan activado (por defecto, sí)."""
    from .motor import contexto_sistema
    n = 0
    with db.transaccion(contexto_sistema(org_id)) as conn:
        nuevos = db.filas(conn, "SELECT a.* FROM alertas a WHERE a.prioridad='urgente' AND a.estado IN ('nueva','escalada') "
                                "AND NOT (a.datos ? 'email_enviado')")
        for a in nuevos:
            destinatarios = db.filas(conn, """SELECT u.id, u.email, u.nombre FROM usuarios u WHERE u.org_id=%s AND u.activo AND u.rol = ANY(%s)
                                              AND coalesce((SELECT p.email FROM preferencias_aviso p WHERE p.usuario_id=u.id AND p.tipo_alerta IN (%s, '*')
                                                            ORDER BY p.tipo_alerta = '*' LIMIT 1), true)
                                              AND (u.rol IN ('dueno','comprador') OR %s::bigint IS NULL OR EXISTS (SELECT 1 FROM usuario_ubicaciones uu
                                                   WHERE uu.usuario_id=u.id AND uu.ubicacion_id=%s))""",
                                     (org_id, a["destinatarios"], a["tipo"], a["ubicacion_id"], a["ubicacion_id"]))
            for d in destinatarios:
                emails.encolar(conn, org_id, d["email"], f"Aviso urgente: {a['titulo']}",
                               f"<p><strong>{a['titulo']}</strong></p><p>{a['explicacion']}</p><p>Impacto: {pesos(a['impacto'])}.</p>",
                               "alerta", d["id"])
                n += 1
            with conn.cursor() as cur:
                cur.execute("UPDATE alertas SET datos = datos || '{\"email_enviado\": true}' WHERE id=%s", (a["id"],))
        emails.enviar_pendientes(conn)
    return n


class Preferencias(BaseModel):
    resumen_diario: bool
    hora_resumen: int = Field(ge=0, le=23)
    urgentes_por_email: bool = True


@api.get("/yo/preferencias")
def ver_preferencias(ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        u = db.fila(conn, "SELECT resumen_diario, hora_resumen FROM usuarios WHERE id=%s", (ctx.usuario_id,))
        p = db.fila(conn, "SELECT email FROM preferencias_aviso WHERE usuario_id=%s AND tipo_alerta='*'", (ctx.usuario_id,))
        return respuesta({**u, "urgentes_por_email": p["email"] if p else True})


@api.put("/yo/preferencias")
def guardar_preferencias(datos: Preferencias, ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("UPDATE usuarios SET resumen_diario=%s, hora_resumen=%s WHERE id=%s", (datos.resumen_diario, datos.hora_resumen, ctx.usuario_id))
        if ctx.org_id:
            cur.execute("INSERT INTO preferencias_aviso (org_id, usuario_id, tipo_alerta, email) VALUES (%s,%s,'*',%s) "
                        "ON CONFLICT (usuario_id, tipo_alerta) DO UPDATE SET email=EXCLUDED.email", (ctx.org_id, ctx.usuario_id, datos.urgentes_por_email))
    return respuesta({"ok": True})
