"""Salud de los pronósticos (predicciones con IA): error, sesgo y cobertura del rango, más los datos que faltan."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends

from . import db, permisos, pronosticos, sesiones
from .api_comprar import _hoy_datos
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])


@api.get("/modelos/salud")
def salud(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        r = pronosticos.salud(conn, hoy)
        datos = db.fila(conn, """
            SELECT (SELECT count(*) FROM productos WHERE activo) productos,
                   (SELECT count(*) FROM productos p WHERE activo AND NOT EXISTS
                       (SELECT 1 FROM producto_proveedores pp WHERE pp.producto_id = p.id AND pp.costo IS NOT NULL)) sin_costo,
                   (SELECT count(*) FROM productos WHERE activo AND estado_mapeo = 'sin_mapear') sin_mapear,
                   (SELECT count(*) FROM metricas_producto_actual WHERE confianza = 'baja') poca_historia,
                   (SELECT count(DISTINCT producto_id) FROM metricas_producto_actual WHERE (explicacion->>'stock_negativo')::boolean) stock_negativo,
                   (SELECT max(fecha_hora) FROM tickets) ultima_venta,
                   (SELECT min(fecha) FROM agg_producto_ubicacion_dia) primera_venta,
                   (SELECT max(calculado_at) FROM metricas_producto_actual) calculado_at,
                   (SELECT max(ultima_sincronizacion) FROM plataformas WHERE activa) ultima_sincronizacion""")
        dias_historia = (hoy - datos["primera_venta"]).days if datos["primera_venta"] else 0
        avisos = []
        if dias_historia < 365:
            avisos.append(f"Hay {dias_historia} días de historia: con 12 meses el pronóstico capta la estacionalidad del año (con 24, mejor).")
        if datos["sin_costo"]:
            avisos.append(f"{datos['sin_costo']} productos sin costo: no se puede medir el error en pesos ni el margen.")
        if datos["poca_historia"]:
            avisos.append(f"{datos['poca_historia']} producto-sucursal con poca historia: usan la referencia de su categoría y su rango es más ancho.")
        if datos["ultima_venta"] and (hoy - datos["ultima_venta"].date()) > timedelta(days=2):
            avisos.append("Las ventas no se actualizan hace más de 2 días: revisá la conexión con la caja.")
        return respuesta({**r, "hoy": hoy, "datos": {**datos, "dias_historia": dias_historia}, "avisos": avisos})
