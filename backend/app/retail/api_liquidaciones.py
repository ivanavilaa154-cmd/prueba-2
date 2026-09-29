"""Liquidaciones activas (caso aplicado del documento de predicciones: predicciones 9, 10, 14, 15 y 24 más el control del local).

Una liquidación funciona si el precio, la ubicación y la puntera llena se cumplen a la vez. Por cada oferta de liquidación
(vencimiento, sobrestock o liquidación) y sucursal:
- Proyección de vaciado: stock actual ÷ ritmo de venta desde que empezó la oferta → ¿llega antes de la fecha límite?
- Acción sugerida: reponer la exhibición, bajar al escalón siguiente de la escalera, mover a puntera, controlar el armado o cerrar.
- Control de ejecución: checklist (armada, cartel, precio cargado) con foto, por sucursal.
- Diferencias de precio cartel vs caja: tickets que cobraron más que el precio de oferta.
- Venta extra por ubicación: lo que rindieron punteras, islas y góndolas en las liquidaciones cerradas (o valores de partida).
Bajar un escalón cambia el precio de la oferta en la plataforma; el precio en la caja lo carga una persona (se avisa).
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from . import db, permisos, sesiones, suscripcion
from .api_comprar import _hoy_datos
from .api_plata import _redondear
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"], dependencies=[Depends(suscripcion.modulo("avanzado"))])
CARPETA = Path(__file__).resolve().parents[2] / "documentos" / "liquidaciones"
EXHIBICION_INICIAL = {"puntera": 1.35, "isla": 1.2, "gondola": 1.0}      # venta extra de partida, hasta medirla
HORAS_ABIERTO = 13
TIPOS_FOTO = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def rendimiento_exhibicion(conn, hoy: date) -> dict:
    """Venta diaria durante la liquidación ÷ venta diaria de las 4 semanas previas, promedio por tipo de exhibición (liquidaciones
    terminadas del último año). Si no hay 3 o más casos de un tipo, queda el valor de partida."""
    medidos = defaultdict(list)
    for p in db.filas(conn, """SELECT productos, ubicaciones, desde, hasta, parametros FROM promociones
                               WHERE origen IN ('vencimiento', 'sobrestock', 'liquidacion') AND hasta < %s AND desde >= %s""",
                      (hoy, hoy - timedelta(days=365))):
        tipo = (p["parametros"] or {}).get("exhibicion")
        if tipo not in EXHIBICION_INICIAL:
            continue
        v = db.fila(conn, """SELECT coalesce(sum(unidades) FILTER (WHERE fecha BETWEEN %(d)s AND %(h)s), 0)::float dur,
                                    coalesce(sum(unidades) FILTER (WHERE fecha BETWEEN %(d)s - 28 AND %(d)s - 1), 0)::float ant
                             FROM agg_producto_ubicacion_dia WHERE producto_id = ANY(%(p)s)
                             AND (cardinality(%(u)s::bigint[]) = 0 OR ubicacion_id = ANY(%(u)s))""",
                    {"d": p["desde"], "h": p["hasta"], "p": p["productos"], "u": p["ubicaciones"]})
        if v["ant"] > 0:
            medidos[tipo].append((v["dur"] / ((p["hasta"] - p["desde"]).days + 1)) / (v["ant"] / 28))
    return {t: {"factor": round(sum(medidos[t]) / len(medidos[t]), 2) if len(medidos[t]) >= 3 else base,
                "casos": len(medidos[t]), "medido": len(medidos[t]) >= 3} for t, base in EXHIBICION_INICIAL.items()}


def _estado(conn, o: dict, uid: int, hoy: date, rend: dict) -> dict:
    par = o["parametros"] or {}
    pid = o["productos"][0]
    creada = o["created_at"]
    v = db.fila(conn, """SELECT coalesce(sum(l.cantidad), 0)::float u,
                                coalesce(sum(l.cantidad) FILTER (WHERE l.fecha = %(hoy)s), 0)::float hoy_u,
                                coalesce(sum(l.cantidad) FILTER (WHERE l.fecha < %(hoy)s), 0)::float completos_u
                         FROM tickets_lineas l JOIN tickets t ON t.id = l.ticket_id
                         WHERE l.producto_id=%(p)s AND l.ubicacion_id=%(u)s AND t.fecha_hora >= %(c)s AND t.estado <> 'anulado'""",
                {"p": pid, "u": uid, "c": creada, "hoy": hoy})
    st = db.fila(conn, "SELECT coalesce(cantidad - reservado, 0)::float s FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (pid, uid))
    stock = max(0.0, st["s"]) if st else 0.0
    completos = (hoy - max(o["desde"], creada.date())).days
    if completos >= 2:
        ritmo, ritmo_origen = v["completos_u"] / completos, "medido"
    else:
        # Todavía sin días completos de oferta: se predice con el pronóstico del producto, el descuento y la exhibición.
        m = db.fila(conn, "SELECT pronostico_diario::float d FROM metricas_producto_actual WHERE producto_id=%s AND ubicacion_id=%s", (pid, uid))
        base = m["d"] if m and m["d"] else 0.0
        ritmo = base * (1 - float(par.get("descuento") or 0)) ** -1.2 * rend.get(par.get("exhibicion") or "gondola", {}).get("factor", 1.0)
        ritmo_origen = "estimado"
    restantes = (o["hasta"] - hoy).days
    vaciado = hoy + timedelta(days=math.ceil(stock / ritmo)) if ritmo > 0 and stock > 0 else (hoy if stock <= 0 else None)
    llega = vaciado is not None and vaciado <= o["hasta"]
    precio_oferta = Decimal(str(par.get("precio_oferta") or 0))
    dif = db.fila(conn, """SELECT count(*) n, coalesce(sum((l.precio_cobrado - %(po)s) * l.cantidad), 0) plata
                           FROM tickets_lineas l JOIN tickets t ON t.id = l.ticket_id
                           WHERE l.producto_id=%(p)s AND l.ubicacion_id=%(u)s AND t.fecha_hora >= %(c)s AND l.cantidad > 0
                           AND t.estado <> 'anulado' AND l.precio_cobrado > %(po)s * 1.01""", {"p": pid, "u": uid, "c": creada, "po": precio_oferta})
    control = db.fila(conn, """SELECT armada, cartel, precio_ok, foto, created_at FROM liquidacion_controles
                               WHERE promocion_id=%s AND ubicacion_id=%s AND tipo='control' ORDER BY created_at DESC LIMIT 1""", (o["id"], uid))
    repuesta = db.fila(conn, """SELECT max(created_at) m FROM liquidacion_controles WHERE promocion_id=%s AND ubicacion_id=%s AND tipo='reposicion'""",
                       (o["id"], uid))["m"]
    exhib = par.get("exhibicion") or "gondola"
    capacidad = par.get("capacidad_exhibicion")
    escalera = [x for x in (par.get("escalera") or []) if x > float(par.get("descuento") or 0)]
    # Reposición de la exhibición: con el ritmo por hora, cuándo se vacía la puntera.
    reponer_cada_h = round(capacidad / (ritmo / HORAS_ABIERTO), 1) if capacidad and ritmo > 0 else None
    ejecucion = "sin_control" if not control else ("ok" if control["armada"] and control["cartel"] and control["precio_ok"] else "con_fallas")
    if stock <= 0:
        accion = ("cerrar", "Se vendió todo: cerrá la liquidación y medí el resultado.")
    elif ejecucion != "ok" and (not control or (datetime.now(control["created_at"].tzinfo) - control["created_at"]).total_seconds() > 86400):
        accion = ("controlar", "Controlá el armado: foto de la exhibición, cartel y precio cargado en la caja.")
    elif dif["n"]:
        accion = ("corregir_precio", f"La caja cobró más que el precio de oferta en {dif['n']} ventas: corregí el precio en la caja.")
    elif not llega and escalera:
        accion = ("bajar_escalon", f"Al ritmo actual no se vacía antes del {o['hasta']:%d/%m}: bajá al {escalera[0]:.0%} de descuento.")
    elif not llega and exhib != "puntera":
        accion = ("mover", "Al ritmo actual no se vacía a tiempo: pasala a una puntera.")
    elif not llega:
        accion = ("revisar", "No llega a vaciarse a tiempo ni con el último escalón: evaluá donar, transferir o devolver al proveedor.")
    elif capacidad and ritmo > 0 and v["hoy_u"] >= capacidad * 0.7 and (not repuesta or repuesta.date() < hoy):
        accion = ("reponer", "La exhibición se está vaciando: mandá a reponer.")
    else:
        accion = ("seguir", "Va bien: se vacía antes de la fecha límite.")
    return {"ubicacion_id": uid, "stock_inicial": par.get("stock_inicial"), "vendidas": round(v["u"], 1), "stock": round(stock, 1),
            "ritmo_diario": round(ritmo, 2), "ritmo_origen": ritmo_origen, "dias_restantes": restantes, "vaciado_proyectado": vaciado, "llega_a_tiempo": llega,
            "exhibicion": exhib, "factor_exhibicion": rend.get(exhib, {}).get("factor"), "capacidad_exhibicion": capacidad,
            "reponer_cada_horas": reponer_cada_h, "ejecucion": ejecucion, "ultimo_control": control,
            "diferencias_precio": dif["n"], "diferencia_plata": dif["plata"], "accion": accion[0], "accion_texto": accion[1],
            "escalon_siguiente": escalera[0] if escalera else None}


@api.get("/liquidaciones")
def liquidaciones(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        rend = rendimiento_exhibicion(conn, hoy)
        ubic = {u["id"]: u["nombre"] for u in db.filas(conn, "SELECT id, nombre FROM ubicaciones WHERE activa AND tipo <> 'deposito'")}
        promos = db.filas(conn, """SELECT p.id, p.nombre, p.productos, p.ubicaciones, p.desde, p.hasta, p.origen, p.parametros, p.created_at, pr.nombre producto,
                                          pr.codigo_interno
                                   FROM promociones p JOIN productos pr ON pr.id = p.productos[1]
                                   WHERE p.origen IN ('vencimiento', 'sobrestock', 'liquidacion') AND p.estado = 'activa' AND p.hasta >= %s
                                   ORDER BY p.hasta""", (hoy,))
        filas = []
        for o in promos:
            for uid in (o["ubicaciones"] or [u for u in ubic
                                             if db.fila(conn, "SELECT 1 FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s AND cantidad > 0",
                                                        (o["productos"][0], u))]):
                if uid not in ubic:
                    continue
                e = _estado(conn, o, uid, hoy, rend)
                filas.append({"id": o["id"], "nombre": o["nombre"], "producto": o["producto"], "codigo_interno": o["codigo_interno"],
                              "origen": o["origen"], "desde": o["desde"], "hasta": o["hasta"], "ubicacion": ubic[uid],
                              "descuento": (o["parametros"] or {}).get("descuento"), "precio_oferta": (o["parametros"] or {}).get("precio_oferta"),
                              "precio_normal": (o["parametros"] or {}).get("precio_normal"), **e})
        orden = ["corregir_precio", "controlar", "bajar_escalon", "mover", "reponer", "revisar", "cerrar", "seguir"]
        filas.sort(key=lambda f: (orden.index(f["accion"]), f["hasta"]))
        resumen = {"activas": len({f["id"] for f in filas}), "no_llegan": sum(1 for f in filas if not f["llega_a_tiempo"] and f["stock"] > 0),
                   "sin_control": sum(1 for f in filas if f["ejecucion"] != "ok"), "diferencias_precio": sum(f["diferencias_precio"] for f in filas),
                   "stock_por_liquidar": round(sum(f["stock"] for f in filas), 1)}
        return respuesta({"hoy": hoy, "filas": filas, "resumen": resumen, "exhibicion": rend})


@api.post("/liquidaciones/{promo_id}/escalon")
def bajar_escalon(promo_id: int, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Pasa al descuento siguiente de la escalera. El precio de la caja lo carga una persona (no se escribe en el sistema de caja)."""
    permisos.exigir(ctx, "remarcar")
    with db.transaccion(ctx) as conn:
        o = db.fila(conn, "SELECT * FROM promociones WHERE id=%s AND estado='activa'", (promo_id,))
        if not o:
            raise HTTPException(status_code=404, detail="No existe esa liquidación activa.")
        par = o["parametros"] or {}
        escalera = [x for x in (par.get("escalera") or []) if x > float(par.get("descuento") or 0)]
        if not escalera:
            raise HTTPException(status_code=409, detail="No quedan escalones: ya está en el último descuento.")
        nuevo = escalera[0]
        normal = Decimal(str(par["precio_normal"]))
        precio = _redondear(normal * (1 - Decimal(str(nuevo)))) if o["tipo"] == "descuento_pct" else _redondear(normal * (1 - Decimal(str(nuevo)) / 2))
        hoy = _hoy_datos(conn)
        par.update({"descuento": nuevo, "precio_oferta": str(precio),
                    "historial": (par.get("historial") or []) + [{"fecha": str(hoy), "descuento": nuevo, "precio": str(precio)}]})
        with conn.cursor() as cur:
            cur.execute("UPDATE promociones SET parametros=%s, nombre=regexp_replace(nombre, '\\d+%% off', %s) WHERE id=%s",
                        (json.dumps(par, default=str), f"{round(nuevo * 100)}% off", promo_id))
            for uid in (o["ubicaciones"] or [None]):
                if uid:
                    cur.execute("INSERT INTO liquidacion_controles (org_id, promocion_id, ubicacion_id, tipo, detalle, created_by) VALUES (%s,%s,%s,'escalon',%s,%s)",
                                (ctx.org_id, promo_id, uid, json.dumps({"descuento": nuevo, "precio": str(precio)}), ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "bajar_escalon", "promocion", promo_id, {"descuento": nuevo, "precio": str(precio)}, sesiones.ip_de(request))
        return respuesta({"descuento": nuevo, "precio_oferta": precio,
                          "mensaje": f"Nuevo precio de oferta {precio}: cargalo en la caja y reimprimí el cartel."})


@api.post("/liquidaciones/{promo_id}/control")
async def registrar_control(promo_id: int, request: Request, ubicacion_id: int = Form(...), tipo: str = Form("control"),
                            armada: bool | None = Form(None), cartel: bool | None = Form(None), precio_ok: bool | None = Form(None),
                            exhibicion: str | None = Form(None), foto: UploadFile | None = File(None),
                            ctx: db.Contexto = Depends(sesiones.contexto)):
    """Checklist del local con foto (control), reposición hecha o cambio de exhibición."""
    permisos.exigir(ctx, "recuentos")
    if tipo not in ("control", "reposicion", "exhibicion"):
        raise HTTPException(status_code=400, detail="Tipo no válido.")
    archivo = None
    if foto is not None and foto.filename:
        if foto.content_type not in TIPOS_FOTO:
            raise HTTPException(status_code=400, detail="La foto tiene que ser JPG, PNG o WEBP.")
        contenido = await foto.read()
        if len(contenido) > 8 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="La foto supera 8 MB.")
        CARPETA.mkdir(parents=True, exist_ok=True)
        archivo = f"{ctx.org_id}-{promo_id}-{hashlib.sha256(contenido).hexdigest()[:16]}{TIPOS_FOTO[foto.content_type]}"
        (CARPETA / archivo).write_bytes(contenido)
    with db.transaccion(ctx) as conn:
        o = db.fila(conn, "SELECT id, parametros FROM promociones WHERE id=%s", (promo_id,))
        if not o or not db.fila(conn, "SELECT 1 FROM ubicaciones WHERE id=%s", (ubicacion_id,)):
            raise HTTPException(status_code=404, detail="No existe esa liquidación o sucursal.")
        detalle = {}
        if tipo == "exhibicion":
            if exhibicion not in EXHIBICION_INICIAL:
                raise HTTPException(status_code=400, detail="La exhibición es puntera, isla o góndola.")
            par = o["parametros"] or {}
            par["exhibicion"] = exhibicion
            detalle = {"exhibicion": exhibicion}
            with conn.cursor() as cur:
                cur.execute("UPDATE promociones SET parametros=%s WHERE id=%s", (json.dumps(par, default=str), promo_id))
        with conn.cursor() as cur:
            cur.execute("INSERT INTO liquidacion_controles (org_id, promocion_id, ubicacion_id, tipo, armada, cartel, precio_ok, foto, detalle, created_by) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (ctx.org_id, promo_id, ubicacion_id, tipo, armada, cartel, precio_ok, archivo, json.dumps(detalle), ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, tipo, "liquidacion", promo_id, {"ubicacion_id": ubicacion_id, "foto": bool(archivo)}, sesiones.ip_de(request))
    return respuesta({"ok": True, "foto": archivo})


@api.get("/liquidaciones/fotos/{archivo}")
def ver_foto(archivo: str, ctx: db.Contexto = Depends(sesiones.contexto)):
    from fastapi.responses import FileResponse
    permisos.exigir(ctx, "ver_ventas")
    if "/" in archivo or ".." in archivo or not archivo.startswith(f"{ctx.org_id}-"):
        raise HTTPException(status_code=404, detail="No existe esa foto.")
    ruta = CARPETA / archivo
    if not ruta.exists():
        raise HTTPException(status_code=404, detail="No existe esa foto.")
    return FileResponse(ruta)
