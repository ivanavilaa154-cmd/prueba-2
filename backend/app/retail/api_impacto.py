"""Medición de impacto (sección 13.4): línea base del comercio al conectarse y reporte mensual de mejora.

Indicadores de cada período:
- Faltantes: ventas perdidas estimadas = por producto × sucursal, días sin stock × venta diaria de los días con stock. Tasa = perdidas ÷
  (ventas + perdidas).
- Merma: costo de lo tirado (vencido, roto) ÷ ventas.
- Plata parada al cierre: stock a costo de los productos con más de 30 días de stock (al ritmo de venta de los 28 días previos).
- Margen: ganancia bruta ÷ ventas.
Línea base: las primeras 4 semanas con datos (o el rango guardado en el parámetro «linea_base»).
Mejora del mes, en pesos: faltantes evitados = (tasa base − tasa del mes) × ventas del mes; merma reducida = (merma % base − del mes) × ventas;
margen recuperado = (margen del mes − margen base) × ventas; plata liberada = plata parada base − plata parada al cierre del mes.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends

from . import db, permisos, sesiones
from .api_comprar import _hoy_datos
from .api_plata import parametro
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])


def _indicadores(conn, d: date, h: date) -> dict:
    v = db.fila(conn, """
        WITH sd AS (SELECT producto_id, ubicacion_id, count(*) FILTER (WHERE NOT con_stock) sin, count(*) FILTER (WHERE con_stock) con
                    FROM stock_diario WHERE fecha BETWEEN %(d)s AND %(h)s GROUP BY 1, 2),
             v AS (SELECT producto_id, ubicacion_id, sum(facturacion) f, sum(ganancia) g FROM agg_producto_ubicacion_dia
                   WHERE fecha BETWEEN %(d)s AND %(h)s GROUP BY 1, 2)
        SELECT coalesce(sum(v.f), 0) ventas, coalesce(sum(v.g), 0) ganancia,
               coalesce(sum(CASE WHEN sd.con > 0 THEN sd.sin * v.f / sd.con ELSE 0 END), 0) perdidas
        FROM v LEFT JOIN sd USING (producto_id, ubicacion_id)""", {"d": d, "h": h})
    merma = db.fila(conn, """
        SELECT coalesce(-sum(m.cantidad * coalesce(m.costo_unitario, (SELECT costo FROM producto_proveedores pp WHERE pp.producto_id = m.producto_id
                                                                     ORDER BY principal DESC LIMIT 1), 0)), 0) c
        FROM movimientos_stock m JOIN organizaciones o ON o.id = m.org_id
        WHERE m.tipo IN ('merma', 'vencimiento') AND (m.fecha AT TIME ZONE o.zona_horaria)::date BETWEEN %s AND %s""", (d, h))["c"]
    parada = db.fila(conn, """
        WITH cierre AS (SELECT producto_id, ubicacion_id, stock_cierre FROM stock_diario WHERE fecha = %(h)s AND stock_cierre > 0),
             ritmo AS (SELECT producto_id, sum(unidades) / 28.0 diaria FROM agg_producto_ubicacion_dia WHERE fecha > %(h)s - 28 AND fecha <= %(h)s GROUP BY 1),
             ritmo_u AS (SELECT producto_id, ubicacion_id, sum(unidades) / 28.0 diaria FROM agg_producto_ubicacion_dia
                         WHERE fecha > %(h)s - 28 AND fecha <= %(h)s GROUP BY 1, 2)
        SELECT coalesce(sum(c.stock_cierre * coalesce(pp.costo, 0)), 0) capital
        FROM cierre c JOIN ubicaciones u ON u.id = c.ubicacion_id
        LEFT JOIN ritmo r ON r.producto_id = c.producto_id
        LEFT JOIN ritmo_u ru ON ru.producto_id = c.producto_id AND ru.ubicacion_id = c.ubicacion_id
        LEFT JOIN LATERAL (SELECT costo FROM producto_proveedores x WHERE x.producto_id = c.producto_id ORDER BY principal DESC LIMIT 1) pp ON true
        WHERE c.stock_cierre > 30 * coalesce(CASE WHEN u.tipo = 'deposito' THEN r.diaria ELSE ru.diaria END, 0)""", {"h": h})["capital"]
    ventas = v["ventas"]
    return {"desde": d, "hasta": h, "ventas": ventas, "ventas_perdidas": v["perdidas"].quantize(Decimal("0.01")),
            "tasa_faltantes": float(v["perdidas"] / (ventas + v["perdidas"])) if ventas + v["perdidas"] else 0.0,
            "merma": merma, "merma_pct": float(merma / ventas) if ventas else 0.0,
            "plata_parada": parada.quantize(Decimal("0.01")), "margen": float(v["ganancia"] / ventas) if ventas else 0.0}


def linea_base(conn) -> tuple[date, date]:
    guardada = parametro(conn, "linea_base")
    if isinstance(guardada, dict) and guardada.get("desde") and guardada.get("hasta"):
        return date.fromisoformat(guardada["desde"]), date.fromisoformat(guardada["hasta"])
    primera = db.fila(conn, "SELECT min(fecha) f FROM agg_producto_ubicacion_dia")["f"]
    primera = primera or _hoy_datos(conn)
    return primera, primera + timedelta(days=27)


@api.get("/impacto")
def impacto(meses: int = 12, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        bd, bh = linea_base(conn)
        base = _indicadores(conn, bd, bh)
        filas = []
        mes = hoy.replace(day=1)
        for _ in range(max(1, min(meses, 24))):
            fin = min(hoy, (mes + timedelta(days=32)).replace(day=1) - timedelta(days=1))
            if fin <= bh:
                break
            m = _indicadores(conn, max(mes, bh + timedelta(days=1)), fin)
            ventas = m["ventas"]
            mejora = {
                "faltantes_evitados": (Decimal(str(base["tasa_faltantes"] - m["tasa_faltantes"])) * ventas).quantize(Decimal("0.01")),
                "merma_reducida": (Decimal(str(base["merma_pct"] - m["merma_pct"])) * ventas).quantize(Decimal("0.01")),
                "margen_recuperado": (Decimal(str(m["margen"] - base["margen"])) * ventas).quantize(Decimal("0.01")),
                "plata_liberada": (base["plata_parada"] - m["plata_parada"]).quantize(Decimal("0.01")),
            }
            mejora["total"] = sum((mejora[k] for k in ("faltantes_evitados", "merma_reducida", "margen_recuperado")), Decimal(0))
            filas.append({**m, "mes": mes, "mejora": mejora})
            mes = (mes - timedelta(days=1)).replace(day=1)
        return respuesta({"linea_base": base, "meses": filas, "hoy": hoy})
