"""Canales de venta y e-commerce (sección 12).

- Ganancia real por canal y plataforma = ventas − costo de la mercadería − comisión de la plataforma − envío a cargo del
  vendedor − costo del medio de pago − publicidad del período (prorrateada por los días del período).
- Stock unificado: los pedidos online sin despachar reservan stock en la sucursal que despacha.
- Sobreventa: stock publicado mayor que el disponible (stock − reservado − stock de seguridad online).
"""
from __future__ import annotations

import calendar
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from . import db, permisos, sesiones, suscripcion
from .api_comprar import _hoy_datos
from .api_plata import parametro
from .api_ventas import periodo
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"], dependencies=[Depends(suscripcion.modulo("avanzado"))])   # plan (13.6)


def _comisiones_medios(conn) -> dict:
    v = parametro(conn, "comisiones_medios") or {}
    return v if isinstance(v, dict) else json.loads(v)


def resultado_por_canal(conn, d: date, h: date) -> list[dict]:
    ventas = db.filas(conn, """
        SELECT t.canal_id, c.nombre canal, c.codigo, t.plataforma_id, coalesce(pl.nombre, c.nombre) plataforma, pl.tipo,
               sum(l.precio_cobrado * l.cantidad) ventas, sum(coalesce(l.costo_unitario, 0) * l.cantidad) costo, count(DISTINCT t.id) tickets
        FROM tickets t JOIN tickets_lineas l ON l.ticket_id = t.id JOIN canales c ON c.id = t.canal_id LEFT JOIN plataformas pl ON pl.id = t.plataforma_id
        JOIN organizaciones o ON o.id = t.org_id
        WHERE t.estado <> 'anulado' AND (t.fecha_hora AT TIME ZONE o.zona_horaria)::date BETWEEN %s AND %s
        GROUP BY 1, 2, 3, 4, 5, 6""", (d, h))
    # Publicidad cargada por mes (fila sin ticket el día 1): se prorratea por los días del período que caen en cada mes.
    publicidad = defaultdict(Decimal)
    for f in db.filas(conn, "SELECT plataforma_id, fecha, publicidad FROM costos_canal WHERE ticket_id IS NULL AND publicidad > 0 AND fecha BETWEEN %s AND %s",
                      (d.replace(day=1), h)):
        ini_mes = f["fecha"].replace(day=1)
        dias_mes = calendar.monthrange(ini_mes.year, ini_mes.month)[1]
        fin_mes = ini_mes.replace(day=dias_mes)
        solapa = (min(h, fin_mes) - max(d, ini_mes)).days + 1
        if solapa > 0:
            publicidad[f["plataforma_id"]] += f["publicidad"] * solapa / dias_mes
    comisiones_plat = {f["plataforma_id"]: f for f in db.filas(conn, """
        SELECT cc.plataforma_id, sum(cc.comision) comision, sum(cc.envio) envio FROM costos_canal cc
        WHERE cc.ticket_id IS NOT NULL AND cc.fecha BETWEEN %s AND %s GROUP BY 1""", (d, h))}
    medios_cfg = _comisiones_medios(conn)
    tasa = Decimal(str(parametro(conn, "tasa_financiera_mensual") or "0.03"))
    medios = defaultdict(Decimal)
    for f in db.filas(conn, """
        SELECT t.plataforma_id, t.canal_id, p.medio, sum(p.monto) monto FROM pagos p JOIN tickets t ON t.id = p.ticket_id JOIN organizaciones o ON o.id = t.org_id
        WHERE t.estado <> 'anulado' AND p.medio <> 'plataforma' AND (t.fecha_hora AT TIME ZONE o.zona_horaria)::date BETWEEN %s AND %s GROUP BY 1, 2, 3""", (d, h)):
        c = medios_cfg.get(f["medio"], {})
        medios[(f["canal_id"], f["plataforma_id"])] += f["monto"] * (Decimal(str(c.get("comision", 0))) + tasa / 30 * int(c.get("acreditacion_dias", 0)))
    salida = []
    for v in ventas:
        cp = comisiones_plat.get(v["plataforma_id"], {}) if v["plataforma_id"] else {}
        pub = publicidad.get(v["plataforma_id"], Decimal(0)).quantize(Decimal("0.01")) if v["plataforma_id"] else Decimal(0)
        comision = cp.get("comision") or Decimal(0)
        envio = cp.get("envio") or Decimal(0)
        medio = medios.get((v["canal_id"], v["plataforma_id"]), Decimal(0)).quantize(Decimal("0.01"))
        ganancia_bruta = v["ventas"] - v["costo"]
        real = ganancia_bruta - comision - envio - medio - pub
        salida.append({"canal": v["canal"], "codigo": v["codigo"], "plataforma_id": v["plataforma_id"], "plataforma": v["plataforma"], "tickets": v["tickets"],
                       "ventas": v["ventas"], "costo_mercaderia": v["costo"], "ganancia_bruta": ganancia_bruta, "comision": comision, "envio": envio,
                       "costo_medios": medio, "publicidad": pub, "ganancia_real": real,
                       "margen_bruto": float(ganancia_bruta / v["ventas"]) if v["ventas"] else None,
                       "margen_real": float(real / v["ventas"]) if v["ventas"] else None,
                       "ticket_promedio": (v["ventas"] / v["tickets"]).quantize(Decimal("0.01")) if v["tickets"] else None})
    total = sum((x["ventas"] for x in salida), Decimal(0))
    for x in salida:
        x["participacion"] = float(x["ventas"] / total) if total else 0
    return sorted(salida, key=lambda x: -x["ventas"])


@api.get("/canales/resultado")
def resultado(periodo_: str | None = Query(None, alias="periodo"), desde: date | None = None, hasta: date | None = None,
              ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        d, h, _, _, etiqueta = periodo(conn, periodo_, desde, hasta)
        filas = resultado_por_canal(conn, d, h)
        hoy = _hoy_datos(conn)
        evolucion = db.filas(conn, """
            SELECT date_trunc('month', a.fecha)::date mes, c.nombre canal, sum(a.facturacion) ventas
            FROM agg_producto_ubicacion_dia a JOIN canales c ON c.id = a.canal_id
            WHERE a.fecha > %s GROUP BY 1, 2 ORDER BY 1""", ((hoy.replace(day=1) - timedelta(days=330)).replace(day=1),))
        return respuesta({"periodo": {"desde": d, "hasta": h, "etiqueta": etiqueta}, "filas": filas, "evolucion": evolucion})


def sobreventa(conn) -> list[dict]:
    seguridad = Decimal(str(parametro(conn, "stock_seguridad_online") or 0))
    filas = db.filas(conn, """
        SELECT pb.id, pb.plataforma_id, pl.nombre plataforma, pb.producto_id, p.nombre, p.codigo_interno, pb.sku, pb.stock_publicado,
               pl.ubicacion_despacho_id, u.nombre ubicacion, coalesce(s.cantidad, 0) stock, coalesce(s.reservado, 0) reservado, pb.precio
        FROM publicaciones pb JOIN plataformas pl ON pl.id = pb.plataforma_id JOIN productos p ON p.id = pb.producto_id
        LEFT JOIN ubicaciones u ON u.id = pl.ubicacion_despacho_id
        LEFT JOIN stock_actual s ON s.producto_id = pb.producto_id AND s.ubicacion_id = pl.ubicacion_despacho_id
        WHERE pb.activa""")
    salida = []
    for f in filas:
        disponible = max(Decimal(0), f["stock"] - f["reservado"] - seguridad)
        if f["stock_publicado"] > disponible:
            salida.append(f | {"disponible": disponible, "exceso": f["stock_publicado"] - disponible,
                               "en_riesgo": ((f["stock_publicado"] - disponible) * (f["precio"] or 0)).quantize(Decimal("0.01"))})
    return sorted(salida, key=lambda x: -x["exceso"])


@api.get("/canales/stock")
def stock_online(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        pendientes = db.filas(conn, """
            SELECT po.ticket_id, t.numero_externo, pl.nombre plataforma, po.creado_at, t.total, u.nombre ubicacion,
                   (SELECT count(*) FROM tickets_lineas l WHERE l.ticket_id = po.ticket_id) lineas
            FROM pedidos_online po JOIN tickets t ON t.id = po.ticket_id JOIN plataformas pl ON pl.id = po.plataforma_id JOIN ubicaciones u ON u.id = po.ubicacion_id
            WHERE po.estado = 'pendiente' ORDER BY po.creado_at""")
        reservado = db.fila(conn, "SELECT coalesce(sum(reservado), 0) r, count(*) FILTER (WHERE reservado > 0) productos FROM stock_actual")
        return respuesta({"sobreventa": sobreventa(conn), "pendientes": pendientes, "reservado": reservado,
                          "stock_seguridad_online": parametro(conn, "stock_seguridad_online") or 0})


@api.get("/canales/ecommerce")
def metricas_ecommerce(dias: int = 90, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        desde = hoy - timedelta(days=max(7, min(dias, 365)))
        por_producto = db.filas(conn, """
            SELECT l.producto_id, p.nombre, count(DISTINCT po.ticket_id) pedidos,
                   count(DISTINCT po.ticket_id) FILTER (WHERE po.estado = 'cancelado') cancelados,
                   count(DISTINCT po.ticket_id) FILTER (WHERE po.estado = 'devuelto') devueltos,
                   count(DISTINCT po.ticket_id) FILTER (WHERE po.reclamo) reclamos
            FROM pedidos_online po JOIN tickets_lineas l ON l.ticket_id = po.ticket_id JOIN productos p ON p.id = l.producto_id
            WHERE po.creado_at >= %s GROUP BY 1, 2
            HAVING count(DISTINCT po.ticket_id) FILTER (WHERE po.estado IN ('cancelado', 'devuelto') OR po.reclamo) > 0
            ORDER BY count(DISTINCT po.ticket_id) FILTER (WHERE po.estado IN ('cancelado', 'devuelto') OR po.reclamo) DESC LIMIT 50""", (desde,))
        totales = db.fila(conn, """
            SELECT count(*) pedidos, count(*) FILTER (WHERE estado = 'cancelado') cancelados, count(*) FILTER (WHERE estado = 'devuelto') devueltos,
                   count(*) FILTER (WHERE reclamo) reclamos FROM pedidos_online WHERE creado_at >= %s""", (desde,))
        despacho = db.filas(conn, """
            SELECT u.nombre ubicacion, pl.nombre plataforma, count(*) despachados,
                   (avg(extract(epoch FROM despachado_at - creado_at)) / 3600)::float horas_promedio,
                   count(*) FILTER (WHERE despachado_at - creado_at <= interval '24 hours')::float / count(*) en_24h
            FROM pedidos_online po JOIN ubicaciones u ON u.id = po.ubicacion_id JOIN plataformas pl ON pl.id = po.plataforma_id
            WHERE po.despachado_at IS NOT NULL AND po.creado_at >= %s GROUP BY 1, 2 ORDER BY 1, 2""", (desde,))
        # Se venden bien en el local y no están publicados en ninguna plataforma.
        no_publicados = db.filas(conn, """
            SELECT a.producto_id, p.nombre, p.codigo_interno, sum(a.unidades) unidades_30d, sum(a.facturacion) facturacion_30d
            FROM agg_producto_ubicacion_dia a JOIN canales c ON c.id = a.canal_id AND c.codigo = 'fisico' JOIN productos p ON p.id = a.producto_id
            WHERE a.fecha > %s - 30 AND a.fecha <= %s
              AND NOT EXISTS (SELECT 1 FROM publicaciones pb WHERE pb.producto_id = a.producto_id AND pb.activa)
            GROUP BY 1, 2, 3 ORDER BY sum(a.facturacion) DESC LIMIT 20""", (hoy, hoy))
        hay_publicaciones = bool(db.fila(conn, "SELECT 1 FROM publicaciones LIMIT 1"))
        return respuesta({"desde": desde, "totales": totales, "por_producto": por_producto, "despacho": despacho,
                          "no_publicados": no_publicados if hay_publicaciones else []})


# --- stock publicado: propuestas que aprueba una persona (CLAUDE.md, regla 4) ----------------------------------------

class SeleccionPropuestas(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


@api.get("/canales/stock/propuestas")
def propuestas_stock(ctx: db.Contexto = Depends(sesiones.contexto)):
    from . import stock_publicado
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        return respuesta({"propuestas": stock_publicado.listar(conn), "historial": stock_publicado.historial(conn),
                          "puede_aprobar": permisos.puede(ctx, "gestionar_conexiones"),
                          "stock_seguridad_online": parametro(conn, "stock_seguridad_online") or 0})


@api.post("/canales/stock/propuestas/revisar")
def revisar_propuestas(ctx: db.Contexto = Depends(sesiones.contexto)):
    from . import stock_publicado
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        return respuesta(stock_publicado.proponer(conn))


@api.post("/canales/stock/propuestas/aplicar")
def aplicar_propuestas(datos: SeleccionPropuestas, ctx: db.Contexto = Depends(sesiones.contexto)):
    """La persona eligió qué actualizar: recién acá se escribe en las plataformas."""
    from . import stock_publicado
    permisos.exigir(ctx, "gestionar_conexiones")
    resultados = stock_publicado.aplicar(ctx, datos.ids)
    ok = sum(1 for r in resultados if r["estado"] == "aplicada")
    return respuesta({"resultados": resultados, "aplicadas": ok,
                      "mensaje": f"{ok} de {len(resultados)} publicaciones actualizadas" + ("" if ok == len(resultados) else "; revisá las que fallaron.")})


@api.post("/canales/stock/propuestas/descartar")
def descartar_propuestas(datos: SeleccionPropuestas, ctx: db.Contexto = Depends(sesiones.contexto)):
    from . import stock_publicado
    permisos.exigir(ctx, "gestionar_conexiones")
    with db.transaccion(ctx) as conn:
        n = stock_publicado.descartar(conn, ctx, datos.ids)
        sesiones.auditar(conn, ctx, ctx.usuario_id, "descartar", "propuesta_stock", None, {"ids": datos.ids})
    return respuesta({"descartadas": n})
