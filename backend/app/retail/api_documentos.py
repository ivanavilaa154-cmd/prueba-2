"""API de «Transferencias y OC» (sección 7): sugerencias, edición, aprobación por límite de monto, envío (siempre lo
confirma una persona), recepción con diferencias, cancelación y control posterior."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import db, emails, pdf, permisos, sesiones
from .api_comprar import _hoy_datos
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])

ESTADOS_EDITABLES = ("sugerida", "borrador")


def _oc(conn, oc_id: int) -> dict:
    oc = db.fila(conn, """SELECT o.*, pr.razon_social AS proveedor, pr.email_oc, pr.dias_visita, pr.demora_entrega_dias,
                                 u.nombre AS ubicacion, ua.nombre AS aprobada_por_nombre, ue.nombre AS enviada_por_nombre
                          FROM ordenes_compra o JOIN proveedores pr ON pr.id = o.proveedor_id LEFT JOIN ubicaciones u ON u.id = o.ubicacion_id
                          LEFT JOIN usuarios ua ON ua.id = o.aprobada_por LEFT JOIN usuarios ue ON ue.id = o.enviada_por WHERE o.id=%s""", (oc_id,))
    if not oc:
        raise HTTPException(status_code=404, detail="No existe esa orden de compra (o no es de tus sucursales).")
    oc["lineas"] = db.filas(conn, """SELECT l.*, p.nombre, p.codigo_interno, u.nombre AS ubicacion, pp.codigo_proveedor, pp.unidades_por_bulto
                                     FROM ordenes_compra_lineas l JOIN productos p ON p.id = l.producto_id LEFT JOIN ubicaciones u ON u.id = l.ubicacion_id
                                     LEFT JOIN producto_proveedores pp ON pp.producto_id = l.producto_id AND pp.proveedor_id = %s
                                     WHERE l.orden_id=%s ORDER BY l.adelantada, p.nombre""", (oc["proveedor_id"], oc_id))
    return oc


def _tr(conn, tr_id: int) -> dict:
    t = db.fila(conn, """SELECT t.*, o.nombre AS origen, d.nombre AS destino, ua.nombre AS aprobada_por_nombre FROM transferencias t
                         JOIN ubicaciones o ON o.id = t.origen_id JOIN ubicaciones d ON d.id = t.destino_id
                         LEFT JOIN usuarios ua ON ua.id = t.aprobada_por WHERE t.id=%s""", (tr_id,))
    if not t:
        raise HTTPException(status_code=404, detail="No existe esa transferencia (o no es de tus sucursales).")
    t["lineas"] = db.filas(conn, "SELECT l.*, p.nombre, p.codigo_interno FROM transferencias_lineas l JOIN productos p ON p.id = l.producto_id "
                                 "WHERE l.transferencia_id=%s ORDER BY p.nombre", (tr_id,))
    return t


def _recalcular_total(conn, oc_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE ordenes_compra SET total=(SELECT coalesce(sum(cantidad * coalesce(costo, 0)), 0) FROM ordenes_compra_lineas "
                    "WHERE orden_id=%s), updated_at=now() WHERE id=%s", (oc_id, oc_id))


@api.get("/documentos")
def listar_documentos(estado: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        ocs = db.filas(conn, """SELECT o.id, o.numero, o.estado, o.origen, o.total, o.fecha_esperada, o.aprobacion, o.escalada_at, o.created_at,
                                       o.explicacion, pr.razon_social AS proveedor, coalesce(u.nombre, 'Consolidada') AS ubicacion,
                                       (SELECT count(*) FROM ordenes_compra_lineas l WHERE l.orden_id = o.id) AS lineas
                                FROM ordenes_compra o JOIN proveedores pr ON pr.id = o.proveedor_id LEFT JOIN ubicaciones u ON u.id = o.ubicacion_id
                                WHERE (%s::text IS NULL OR o.estado = %s) AND (o.estado NOT IN ('recibida', 'cancelada') OR o.updated_at > now() - interval '30 days')
                                ORDER BY array_position(ARRAY['sugerida','borrador','aprobada','enviada','recibida_parcial','recibida','cancelada'], o.estado),
                                         o.escalada_at IS NULL, o.total DESC LIMIT 300""", (estado, estado))
        trs = db.filas(conn, """SELECT t.id, t.numero, t.estado, t.motivo, t.valor, t.aprobacion, t.created_at, o.nombre AS origen, d.nombre AS destino,
                                       (SELECT count(*) FROM transferencias_lineas l WHERE l.transferencia_id = t.id) AS lineas
                                FROM transferencias t JOIN ubicaciones o ON o.id = t.origen_id JOIN ubicaciones d ON d.id = t.destino_id
                                WHERE (%s::text IS NULL OR t.estado = %s) AND (t.estado NOT IN ('recibida', 'cancelada') OR t.updated_at > now() - interval '30 days')
                                ORDER BY array_position(ARRAY['sugerida','aprobada','enviada','recibida','cancelada'], t.estado), t.valor DESC LIMIT 300""",
                       (estado, estado))
        limites = {t: permisos.limite_aprobacion(conn, ctx, t) for t in ("orden_compra", "transferencia")}
        mes = _hoy_datos(conn).replace(day=1)
        presupuesto = db.fila(conn, "SELECT sum(monto) m FROM presupuestos_compra WHERE mes=%s AND ubicacion_id IS NULL", (mes,))["m"]
        comprometido = db.fila(conn, "SELECT coalesce(sum(total), 0) t FROM ordenes_compra WHERE estado IN ('aprobada','enviada','recibida_parcial','recibida') "
                                     "AND created_at >= %s", (mes,))["t"]
        return respuesta({"ordenes": ocs, "transferencias": trs, "limites": limites, "presupuesto": presupuesto, "comprometido": comprometido,
                          "puede_comprar": permisos.puede(ctx, "crear_oc"), "puede_aprobar_oc": permisos.puede(ctx, "aprobar_oc"),
                          "puede_transferir": permisos.puede(ctx, "aprobar_transferencias"), "puede_recibir": permisos.puede(ctx, "recepciones")})


@api.get("/ordenes/{oc_id}")
def ver_oc(oc_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        oc = _oc(conn, oc_id)
        oc["recepciones"] = db.filas(conn, "SELECT r.*, (SELECT json_agg(l) FROM recepciones_lineas l WHERE l.recepcion_id = r.id) lineas "
                                           "FROM recepciones r WHERE r.orden_id=%s ORDER BY r.fecha", (oc_id,))
        oc["limite"] = permisos.limite_aprobacion(conn, ctx, "orden_compra")
        return respuesta(oc)


class LineaEdicion(BaseModel):
    id: int
    cantidad: float = Field(ge=0)


class Edicion(BaseModel):
    lineas: list[LineaEdicion]
    notas: str | None = Field(default=None, max_length=500)


@api.put("/ordenes/{oc_id}")
def editar_oc(oc_id: int, datos: Edicion, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "crear_oc")
    with db.transaccion(ctx) as conn:
        oc = _oc(conn, oc_id)
        if oc["estado"] not in ESTADOS_EDITABLES:
            raise HTTPException(status_code=409, detail="Solo se editan órdenes sugeridas o en borrador.")
        cambios = []
        with conn.cursor() as cur:
            for l in datos.lineas:
                actual = next((x for x in oc["lineas"] if x["id"] == l.id), None)
                if not actual:
                    raise HTTPException(status_code=400, detail="Una de las líneas no pertenece a esta orden.")
                if Decimal(str(l.cantidad)) != actual["cantidad"]:
                    cambios.append({"producto": actual["nombre"], "antes": actual["cantidad"], "despues": l.cantidad})
                    cur.execute("UPDATE ordenes_compra_lineas SET cantidad=%s, bultos=%s WHERE id=%s",
                                (l.cantidad, l.cantidad / (actual["unidades_por_bulto"] or 1), l.id))
            cur.execute("UPDATE ordenes_compra SET estado='borrador', notas=coalesce(%s, notas) WHERE id=%s", (datos.notas, oc_id))
        _recalcular_total(conn, oc_id)
        sesiones.auditar(conn, ctx, ctx.usuario_id, "modificar", "orden_compra", oc_id, {"cambios": cambios}, sesiones.ip_de(request))
        return respuesta(_oc(conn, oc_id))


@api.post("/ordenes/{oc_id}/aprobar")
def aprobar_oc(oc_id: int, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "aprobar_oc")
    with db.transaccion(ctx) as conn:
        oc = _oc(conn, oc_id)
        if oc["estado"] not in ESTADOS_EDITABLES:
            raise HTTPException(status_code=409, detail=f"La orden está {oc['estado']}: no se puede aprobar.")
        if not permisos.puede_aprobar(conn, ctx, "orden_compra", oc["total"]):
            limite = permisos.limite_aprobacion(conn, ctx, "orden_compra")
            raise HTTPException(status_code=403, detail=f"La orden supera tu límite de aprobación ($ {limite:,.2f}). La tiene que aprobar el dueño."
                                .replace(",", "X").replace(".", ",").replace("X", "."))
        with conn.cursor() as cur:
            cur.execute("UPDATE ordenes_compra SET estado='aprobada', aprobacion='manual', aprobada_por=%s, aprobada_at=now(), updated_at=now() "
                        "WHERE id=%s", (ctx.usuario_id, oc_id))
        cambios = sum(1 for l in oc["lineas"] if l["cantidad_sugerida"] is not None and l["cantidad"] != l["cantidad_sugerida"])
        sesiones.auditar(conn, ctx, ctx.usuario_id, "aprobar", "orden_compra", oc_id, {"total": oc["total"], "lineas_modificadas": cambios},
                         sesiones.ip_de(request))
        return respuesta(_oc(conn, oc_id))


class Envio(BaseModel):
    email: str | None = Field(default=None, max_length=200)
    mensaje: str | None = Field(default=None, max_length=1000)


@api.post("/ordenes/{oc_id}/enviar")
def enviar_oc(oc_id: int, datos: Envio, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Envío al proveedor: SIEMPRE lo confirma una persona (CLAUDE.md, regla 4), aunque la OC se haya aprobado sola."""
    permisos.exigir(ctx, "crear_oc")
    with db.transaccion(ctx) as conn:
        oc = _oc(conn, oc_id)
        if oc["estado"] != "aprobada":
            raise HTTPException(status_code=409, detail="Primero hay que aprobar la orden.")
        para = (datos.email or oc["email_oc"] or "").strip()
        if "@" not in para:
            raise HTTPException(status_code=400, detail="El proveedor no tiene email para órdenes de compra: cargalo o escribilo acá.")
        empresa = db.fila(conn, "SELECT * FROM organizaciones WHERE id = app_org()")
        proveedor = db.fila(conn, "SELECT * FROM proveedores WHERE id=%s", (oc["proveedor_id"],))
        ruta = pdf.orden_compra(empresa, oc, proveedor, oc["lineas"], oc["ubicacion"] or "Según detalle por sucursal")
        html = (f"<p>Hola, {proveedor['razon_social']}:</p><p>Te enviamos la orden de compra <strong>{oc['numero']}</strong> de "
                f"{empresa['nombre']} por <strong>$ {oc['total']:,.2f}</strong>".replace(",", "X").replace(".", ",").replace("X", ".") +
                f" (va adjunta en PDF). Entrega en: {oc['ubicacion'] or 'según detalle'}.</p>" +
                (f"<p>{datos.mensaje}</p>" if datos.mensaje else "") + f"<p>Saludos,<br>{ctx.nombre}</p>")
        emails.encolar(conn, ctx.org_id, para, f"Orden de compra {oc['numero']} — {empresa['nombre']}", html, "orden_compra", ctx.usuario_id, str(ruta))
        with conn.cursor() as cur:
            cur.execute("UPDATE ordenes_compra SET estado='enviada', enviada_por=%s, enviada_at=now(), updated_at=now() WHERE id=%s",
                        (ctx.usuario_id, oc_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "enviar", "orden_compra", oc_id, {"para": para, "total": oc["total"]}, sesiones.ip_de(request))
        resultado = emails.enviar_pendientes(conn)
        return respuesta({"orden": _oc(conn, oc_id), "email": resultado})


@api.get("/ordenes/{oc_id}/pdf")
def pdf_oc(oc_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        oc = _oc(conn, oc_id)
        empresa = db.fila(conn, "SELECT * FROM organizaciones WHERE id = app_org()")
        proveedor = db.fila(conn, "SELECT * FROM proveedores WHERE id=%s", (oc["proveedor_id"],))
        ruta = pdf.orden_compra(empresa, oc, proveedor, oc["lineas"], oc["ubicacion"] or "Según detalle por sucursal")
    return FileResponse(ruta, media_type="application/pdf", filename=ruta.name)


class Cancelacion(BaseModel):
    motivo: str = Field(min_length=2, max_length=300)


@api.post("/ordenes/{oc_id}/cancelar")
def cancelar_oc(oc_id: int, datos: Cancelacion, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "crear_oc")
    with db.transaccion(ctx) as conn:
        oc = _oc(conn, oc_id)
        if oc["estado"] in ("recibida", "cancelada"):
            raise HTTPException(status_code=409, detail="La orden ya está cerrada.")
        with conn.cursor() as cur:
            cur.execute("UPDATE ordenes_compra SET estado='cancelada', cancelada_motivo=%s, updated_at=now() WHERE id=%s", (datos.motivo, oc_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "cancelar", "orden_compra", oc_id, {"motivo": datos.motivo}, sesiones.ip_de(request))
    return respuesta({"ok": True})


class LineaRecibida(BaseModel):
    producto_id: int
    ubicacion_id: int | None = None
    cantidad: float = Field(ge=0)
    costo: str | None = None
    lote: str | None = Field(default=None, max_length=60)
    vencimiento: date | None = None


class Recepcion(BaseModel):
    lineas: list[LineaRecibida]
    documento: str | None = Field(default=None, max_length=80)


def registrar_recepcion(conn, ctx, oc: dict | None, proveedor_id: int | None, ubicacion_id: int, lineas: list[LineaRecibida],
                        documento: str | None, documento_id: int | None = None) -> dict:
    """Recepción contra OC (o sin OC): suma stock, lotes y movimientos; compara cantidades y costos con lo pedido; actualiza el
    costo vigente del proveedor. Un costo distinto dispara la revisión de precios (remarcación)."""
    rc = db.fila(conn, "INSERT INTO recepciones (org_id, orden_id, proveedor_id, ubicacion_id, documento, documento_id, created_by) "
                       "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id", (ctx.org_id, oc["id"] if oc else None, proveedor_id, ubicacion_id, documento,
                                                                      documento_id, ctx.usuario_id))
    diferencias = []
    aumentos = []
    pedidas = {}
    if oc:
        for l in oc["lineas"]:
            clave = (l["producto_id"], l["ubicacion_id"] or oc["ubicacion_id"])
            pedidas[clave] = pedidas.get(clave, 0) + float(l["cantidad"] - l["cantidad_recibida"])
    with conn.cursor() as cur:
        for l in lineas:
            destino = l.ubicacion_id or ubicacion_id
            costo = Decimal(l.costo) if l.costo not in (None, "") else None
            esperado = pedidas.get((l.producto_id, destino))
            costo_esperado = next((x["costo"] for x in (oc["lineas"] if oc else []) if x["producto_id"] == l.producto_id), None)
            dif = []
            if esperado is not None and l.cantidad < esperado:
                dif.append("faltante")
            if esperado is not None and l.cantidad > esperado:
                dif.append("sobrante")
            if costo is not None and costo_esperado is not None and abs(costo - costo_esperado) > Decimal("0.01"):
                dif.append("costo_distinto")
            if esperado is None and oc:
                dif.append("no_pedido")
            cur.execute("INSERT INTO recepciones_lineas (org_id, recepcion_id, producto_id, cantidad, costo, lote, vencimiento, cantidad_esperada, "
                        "costo_esperado, diferencia) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (ctx.org_id, rc["id"], l.producto_id, l.cantidad, costo, l.lote, l.vencimiento, esperado, costo_esperado, ",".join(dif) or None))
            if dif:
                diferencias.append({"producto_id": l.producto_id, "tipo": dif, "esperado": esperado, "recibido": l.cantidad,
                                    "costo_esperado": costo_esperado, "costo": costo})
            if l.cantidad > 0:
                cur.execute("INSERT INTO stock_actual (org_id, producto_id, ubicacion_id, cantidad) VALUES (%s,%s,%s,%s) "
                            "ON CONFLICT (producto_id, ubicacion_id) DO UPDATE SET cantidad = stock_actual.cantidad + EXCLUDED.cantidad, actualizado_at=now()",
                            (ctx.org_id, l.producto_id, destino, l.cantidad))
                cur.execute("INSERT INTO movimientos_stock (org_id, producto_id, ubicacion_id, tipo, cantidad, costo_unitario, documento_tipo, documento_id, usuario_id) "
                            "VALUES (%s,%s,%s,'compra',%s,%s,'recepcion',%s,%s)", (ctx.org_id, l.producto_id, destino, l.cantidad, costo, rc["id"], ctx.usuario_id))
                if l.lote or l.vencimiento:
                    cur.execute("INSERT INTO stock_lotes (org_id, producto_id, ubicacion_id, lote, cantidad, vencimiento, ingreso) VALUES (%s,%s,%s,%s,%s,%s,current_date)",
                                (ctx.org_id, l.producto_id, destino, l.lote or f"R{rc['id']}", l.cantidad, l.vencimiento))
            if oc:
                cur.execute("UPDATE ordenes_compra_lineas SET cantidad_recibida = cantidad_recibida + %s WHERE orden_id=%s AND producto_id=%s "
                            "AND coalesce(ubicacion_id, %s) = %s", (l.cantidad, oc["id"], l.producto_id, destino, destino))
            if costo is not None and proveedor_id:
                anterior = db.fila(conn, "SELECT costo FROM producto_proveedores WHERE producto_id=%s AND proveedor_id=%s", (l.producto_id, proveedor_id))
                if anterior and anterior["costo"] is not None and costo > anterior["costo"] * Decimal("1.005"):
                    aumentos.append({"producto_id": l.producto_id, "antes": anterior["costo"], "despues": costo})
                cur.execute("UPDATE producto_proveedores SET costo=%s, updated_at=now() WHERE producto_id=%s AND proveedor_id=%s",
                            (costo, l.producto_id, proveedor_id))
        if oc:
            cur.execute("""UPDATE ordenes_compra SET estado = CASE WHEN (SELECT bool_and(cantidad_recibida >= cantidad) FROM ordenes_compra_lineas
                           WHERE orden_id=%s) THEN 'recibida' ELSE 'recibida_parcial' END, updated_at=now() WHERE id=%s""", (oc["id"], oc["id"]))
    return {"recepcion_id": rc["id"], "diferencias": diferencias, "aumentos_de_costo": aumentos}


@api.post("/ordenes/{oc_id}/recepcion")
def recibir_oc(oc_id: int, datos: Recepcion, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "recepciones")
    with db.transaccion(ctx) as conn:
        oc = _oc(conn, oc_id)
        if oc["estado"] not in ("enviada", "aprobada", "recibida_parcial"):
            raise HTTPException(status_code=409, detail="Solo se reciben órdenes aprobadas o enviadas.")
        destino = oc["ubicacion_id"] or (datos.lineas[0].ubicacion_id if datos.lineas else None)
        if not destino:
            raise HTTPException(status_code=400, detail="Indicá en qué sucursal se recibe.")
        r = registrar_recepcion(conn, ctx, oc, oc["proveedor_id"], destino, datos.lineas, datos.documento)
        sesiones.auditar(conn, ctx, ctx.usuario_id, "recibir", "orden_compra", oc_id, r, sesiones.ip_de(request))
        return respuesta({**r, "orden": _oc(conn, oc_id)})


class Seleccion(BaseModel):
    items: list[dict]            # [{producto_id, ubicacion_id, cantidad?}]
    tipo: str = "orden_compra"   # orden_compra | transferencia
    origen_id: int | None = None


@api.post("/documentos/desde-seleccion")
def crear_desde_seleccion(datos: Seleccion, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Botones de «Comprar y reponer»: arma OC en borrador (una por proveedor y sucursal) o una transferencia desde el origen
    con más excedente (o el elegido)."""
    from .reposicion import _numero
    if datos.tipo == "orden_compra":
        permisos.exigir(ctx, "crear_oc")
    else:
        permisos.exigir(ctx, "aprobar_transferencias")
    if not datos.items:
        raise HTTPException(status_code=400, detail="Elegí al menos un producto.")
    with db.transaccion(ctx) as conn:
        creados = []
        if datos.tipo == "orden_compra":
            grupos: dict = {}
            for it in datos.items:
                m = db.fila(conn, """SELECT m.*, pp.costo, pp.unidades_por_bulto, pp.multiplo_compra FROM metricas_producto_actual m
                                     LEFT JOIN producto_proveedores pp ON pp.producto_id = m.producto_id AND pp.proveedor_id = m.proveedor_id
                                     WHERE m.producto_id=%s AND m.ubicacion_id=%s""", (it["producto_id"], it["ubicacion_id"]))
                if not m or not m["proveedor_id"]:
                    raise HTTPException(status_code=400, detail="Uno de los productos no tiene proveedor cargado.")
                cantidad = float(it.get("cantidad") or m["cantidad_sugerida"] or 0)
                if cantidad <= 0:
                    multiplo = (m["unidades_por_bulto"] or 1) * (m["multiplo_compra"] or 1)
                    cantidad = multiplo
                grupos.setdefault((m["proveedor_id"], m["ubicacion_id"]), []).append((m, cantidad))
            for (prov, uid), lineas in grupos.items():
                oc = db.fila(conn, "INSERT INTO ordenes_compra (org_id, numero, proveedor_id, ubicacion_id, estado, origen, created_by) "
                                   "VALUES (%s,%s,%s,%s,'borrador','manual',%s) RETURNING id",
                             (ctx.org_id, _numero(conn, "OC", "ordenes_compra"), prov, uid, ctx.usuario_id))
                with conn.cursor() as cur:
                    for m, cantidad in lineas:
                        cur.execute("INSERT INTO ordenes_compra_lineas (org_id, orden_id, producto_id, ubicacion_id, cantidad, cantidad_sugerida, bultos, costo, explicacion) "
                                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                    (ctx.org_id, oc["id"], m["producto_id"], uid, cantidad, m["cantidad_sugerida"], cantidad / (m["unidades_por_bulto"] or 1),
                                     m["costo"], json.dumps({"desde": "comprar_y_reponer"})))
                _recalcular_total(conn, oc["id"])
                creados.append({"tipo": "orden_compra", "id": oc["id"]})
        else:
            por_destino: dict = {}
            for it in datos.items:
                por_destino.setdefault(it["ubicacion_id"], []).append(it)
            for destino, items in por_destino.items():
                origen = datos.origen_id
                if not origen:
                    cand = db.fila(conn, """SELECT m.ubicacion_id, sum(m.disponible) d FROM metricas_producto_actual m JOIN ubicaciones u ON u.id = m.ubicacion_id
                                            WHERE m.producto_id = ANY(%s) AND m.ubicacion_id <> %s AND m.disponible > 0
                                            GROUP BY 1 ORDER BY bool_or(u.tipo='deposito') DESC, 2 DESC LIMIT 1""",
                                   ([i["producto_id"] for i in items], destino))
                    if not cand:
                        raise HTTPException(status_code=400, detail="Ninguna otra sucursal o depósito tiene stock de estos productos.")
                    origen = cand["ubicacion_id"]
                t = db.fila(conn, "INSERT INTO transferencias (org_id, numero, origen_id, destino_id, estado, motivo, created_by) "
                                  "VALUES (%s,%s,%s,%s,'sugerida','manual',%s) RETURNING id",
                            (ctx.org_id, _numero(conn, "TR", "transferencias"), origen, destino, ctx.usuario_id))
                with conn.cursor() as cur:
                    for it in items:
                        m = db.fila(conn, "SELECT cantidad_sugerida, (SELECT costo FROM producto_proveedores WHERE producto_id=%s ORDER BY principal DESC LIMIT 1) costo "
                                          "FROM metricas_producto_actual WHERE producto_id=%s AND ubicacion_id=%s", (it["producto_id"], it["producto_id"], destino))
                        cantidad = float(it.get("cantidad") or (m and m["cantidad_sugerida"]) or 1)
                        cur.execute("INSERT INTO transferencias_lineas (org_id, transferencia_id, producto_id, cantidad, costo) VALUES (%s,%s,%s,%s,%s)",
                                    (ctx.org_id, t["id"], it["producto_id"], max(1, cantidad), m["costo"] if m else None))
                    cur.execute("UPDATE transferencias SET valor=(SELECT coalesce(sum(cantidad*coalesce(costo,0)),0) FROM transferencias_lineas WHERE transferencia_id=%s) WHERE id=%s",
                                (t["id"], t["id"]))
                creados.append({"tipo": "transferencia", "id": t["id"]})
        sesiones.auditar(conn, ctx, ctx.usuario_id, "crear_desde_seleccion", datos.tipo, None, {"creados": creados, "items": len(datos.items)},
                         sesiones.ip_de(request))
        return respuesta({"creados": creados}, 201)


# ------------------------------------------------------------------------------ transferencias
@api.get("/transferencias/{tr_id}")
def ver_transferencia(tr_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        return respuesta(_tr(conn, tr_id))


@api.post("/transferencias/{tr_id}/aprobar")
def aprobar_transferencia(tr_id: int, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "aprobar_transferencias")
    with db.transaccion(ctx) as conn:
        t = _tr(conn, tr_id)
        if t["estado"] != "sugerida":
            raise HTTPException(status_code=409, detail=f"La transferencia está {t['estado']}.")
        if not permisos.puede_aprobar(conn, ctx, "transferencia", t["valor"]):
            raise HTTPException(status_code=403, detail="La transferencia supera tu límite de aprobación. La tiene que aprobar el dueño.")
        with conn.cursor() as cur:
            cur.execute("UPDATE transferencias SET estado='aprobada', aprobacion='manual', aprobada_por=%s, aprobada_at=now(), updated_at=now() WHERE id=%s",
                        (ctx.usuario_id, tr_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "aprobar", "transferencia", tr_id, {"valor": t["valor"]}, sesiones.ip_de(request))
        return respuesta(_tr(conn, tr_id))


@api.post("/transferencias/{tr_id}/enviar")
def enviar_transferencia(tr_id: int, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Enviada: descuenta del origen y suma «en tránsito» en el destino."""
    permisos.exigir(ctx, "recepciones")
    with db.transaccion(ctx) as conn:
        t = _tr(conn, tr_id)
        if t["estado"] != "aprobada":
            raise HTTPException(status_code=409, detail="Solo se envían transferencias aprobadas.")
        with conn.cursor() as cur:
            for l in t["lineas"]:
                cur.execute("UPDATE stock_actual SET cantidad = cantidad - %s, actualizado_at=now() WHERE producto_id=%s AND ubicacion_id=%s",
                            (l["cantidad"], l["producto_id"], t["origen_id"]))
                cur.execute("INSERT INTO stock_actual (org_id, producto_id, ubicacion_id, en_transito) VALUES (%s,%s,%s,%s) ON CONFLICT (producto_id, ubicacion_id) "
                            "DO UPDATE SET en_transito = stock_actual.en_transito + EXCLUDED.en_transito, actualizado_at=now()",
                            (ctx.org_id, l["producto_id"], t["destino_id"], l["cantidad"]))
                cur.execute("INSERT INTO movimientos_stock (org_id, producto_id, ubicacion_id, tipo, cantidad, costo_unitario, documento_tipo, documento_id, usuario_id) "
                            "VALUES (%s,%s,%s,'transferencia_salida',%s,%s,'transferencia',%s,%s)",
                            (ctx.org_id, l["producto_id"], t["origen_id"], -l["cantidad"], l["costo"], tr_id, ctx.usuario_id))
                if l["lote"]:
                    cur.execute("UPDATE stock_lotes SET cantidad = greatest(0, cantidad - %s) WHERE producto_id=%s AND ubicacion_id=%s AND lote=%s",
                                (l["cantidad"], l["producto_id"], t["origen_id"], l["lote"]))
            cur.execute("UPDATE transferencias SET estado='enviada', enviada_at=now(), updated_at=now() WHERE id=%s", (tr_id,))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "enviar", "transferencia", tr_id, {"lineas": len(t["lineas"])}, sesiones.ip_de(request))
        return respuesta(_tr(conn, tr_id))


class RecepcionTransferencia(BaseModel):
    lineas: list[dict]      # [{id, cantidad_recibida}]


@api.post("/transferencias/{tr_id}/recibir")
def recibir_transferencia(tr_id: int, datos: RecepcionTransferencia, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Recibida: suma en el destino, resta «en tránsito» y registra las diferencias con lo enviado."""
    permisos.exigir(ctx, "recepciones")
    with db.transaccion(ctx) as conn:
        t = _tr(conn, tr_id)
        if t["estado"] != "enviada":
            raise HTTPException(status_code=409, detail="Solo se reciben transferencias enviadas.")
        recibidas = {int(x["id"]): Decimal(str(x["cantidad_recibida"])) for x in datos.lineas}
        diferencias = []
        with conn.cursor() as cur:
            for l in t["lineas"]:
                q = recibidas.get(l["id"], l["cantidad"])
                dif = None if q == l["cantidad"] else ("faltante" if q < l["cantidad"] else "sobrante")
                if dif:
                    diferencias.append({"producto": l["nombre"], "enviado": l["cantidad"], "recibido": q})
                cur.execute("UPDATE transferencias_lineas SET cantidad_recibida=%s, diferencia=%s WHERE id=%s", (q, dif, l["id"]))
                cur.execute("UPDATE stock_actual SET cantidad = cantidad + %s, en_transito = greatest(0, en_transito - %s), actualizado_at=now() "
                            "WHERE producto_id=%s AND ubicacion_id=%s", (q, l["cantidad"], l["producto_id"], t["destino_id"]))
                cur.execute("INSERT INTO movimientos_stock (org_id, producto_id, ubicacion_id, tipo, cantidad, costo_unitario, documento_tipo, documento_id, usuario_id, motivo) "
                            "VALUES (%s,%s,%s,'transferencia_entrada',%s,%s,'transferencia',%s,%s,%s)",
                            (ctx.org_id, l["producto_id"], t["destino_id"], q, l["costo"], tr_id, ctx.usuario_id, dif))
            cur.execute("UPDATE transferencias SET estado='recibida', recibida_at=now(), updated_at=now() WHERE id=%s", (tr_id,))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "recibir", "transferencia", tr_id, {"diferencias": diferencias}, sesiones.ip_de(request))
        return respuesta({"transferencia": _tr(conn, tr_id), "diferencias": diferencias})


@api.post("/transferencias/{tr_id}/cancelar")
def cancelar_transferencia(tr_id: int, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "aprobar_transferencias")
    with db.transaccion(ctx) as conn:
        t = _tr(conn, tr_id)
        if t["estado"] not in ("sugerida", "aprobada"):
            raise HTTPException(status_code=409, detail="Solo se cancelan transferencias sugeridas o aprobadas (sin enviar).")
        with conn.cursor() as cur:
            cur.execute("UPDATE transferencias SET estado='cancelada', updated_at=now() WHERE id=%s", (tr_id,))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "cancelar", "transferencia", tr_id, None, sesiones.ip_de(request))
    return respuesta({"ok": True})


# ------------------------------------------------------------------------------ control posterior
@api.get("/reposicion/control")
def control_posterior(dias: int = 30, ctx: db.Contexto = Depends(sesiones.contexto)):
    """% de sugerencias aprobadas sin cambios, modificadas o ignoradas; ajustes aprendidos; plata ahorrada por transferir."""
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        desde = hoy - timedelta(days=dias)
        lineas = db.filas(conn, """SELECT o.estado, o.aprobacion, l.cantidad, l.cantidad_sugerida FROM ordenes_compra_lineas l
                                   JOIN ordenes_compra o ON o.id = l.orden_id WHERE o.origen='sugerida' AND o.created_at >= %s""", (desde,))
        aprobadas = [l for l in lineas if l["estado"] in ("aprobada", "enviada", "recibida", "recibida_parcial")]
        sin_cambios = sum(1 for l in aprobadas if l["cantidad"] == l["cantidad_sugerida"])
        ignoradas = sum(1 for l in lineas if l["estado"] == "cancelada")
        total = len(lineas) or 1
        ahorro = db.fila(conn, """SELECT coalesce(sum(coalesce(l.cantidad_recibida, l.cantidad) * coalesce(l.costo, 0)), 0) v FROM transferencias_lineas l
                                  JOIN transferencias t ON t.id = l.transferencia_id WHERE t.estado='recibida' AND t.recibida_at >= %s""", (desde,))["v"]
        aprendidos = db.filas(conn, "SELECT a.*, p.nombre FROM ajustes_aprendizaje a JOIN productos p ON p.id = a.producto_id ORDER BY a.created_at DESC LIMIT 50")
        return respuesta({"dias": dias, "lineas_sugeridas": len(lineas), "aprobadas_sin_cambios": round(100 * sin_cambios / total, 1),
                          "modificadas": round(100 * (len(aprobadas) - sin_cambios) / total, 1), "ignoradas": round(100 * ignoradas / total, 1),
                          "plata_ahorrada_por_transferir": ahorro, "ajustes_aprendidos": aprendidos})
