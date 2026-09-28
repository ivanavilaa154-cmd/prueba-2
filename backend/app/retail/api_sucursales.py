"""Multisucursal (sección 8): matriz producto × sucursal, comparativos, el mismo producto en cada sucursal, precios distintos,
diferencias de inventario con alerta de faltantes sospechosos y ajustes de stock auditados.

El encargado ve solo sus sucursales: lo aplica la base (RLS), así que los comparativos comparan lo que el usuario puede ver.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query

from . import calculos as C
from . import db, permisos, sesiones
from .api_comprar import _hoy_datos, lista_ids
from .api_plata import estado_stock, parametro, red_de_venta
from .api_ventas import periodo
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])


def _ubicaciones(conn) -> list[dict]:
    return db.filas(conn, "SELECT id, nombre, tipo FROM ubicaciones WHERE activa ORDER BY tipo = 'deposito', id")


@api.get("/sucursales/matriz")
def matriz(categoria: int | None = None, q: str | None = None, solo_problemas: bool = False, limite: int = 200,
           ctx: db.Contexto = Depends(sesiones.contexto)):
    """Filas: productos (los más vendidos primero). Columnas: cada sucursal con días de stock y semáforo, más el depósito
    y lo que está en tránsito."""
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        ubic = _ubicaciones(conn)
        params: dict = {}
        filtros = ["true"]
        if categoria:
            filtros.append("(c.id = %(cat)s OR c.padre_id = %(cat)s)")
            params["cat"] = categoria
        if q and q.strip():
            filtros.append("(p.nombre ILIKE %(q)s OR p.codigo_interno = %(qq)s OR p.ean = %(qq)s)")
            params["q"], params["qq"] = f"%{q.strip()}%", q.strip()
        celdas = db.filas(conn, f"""
            SELECT m.producto_id, m.ubicacion_id, p.nombre, p.codigo_interno, coalesce(cp.nombre, c.nombre) AS categoria,
                   m.disponible, m.dias_stock, m.semaforo, m.pronostico_diario, coalesce(s.en_transito, 0) AS en_transito,
                   (SELECT min((x->>'vencimiento')::date) FROM jsonb_array_elements(m.explicacion->'lotes') x) AS vence
            FROM metricas_producto_actual m JOIN productos p ON p.id = m.producto_id
            LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
            LEFT JOIN stock_actual s ON s.producto_id = m.producto_id AND s.ubicacion_id = m.ubicacion_id
            WHERE {' AND '.join(filtros)}""", params)
        productos: dict = {}
        for f in celdas:
            p = productos.setdefault(f["producto_id"], {"producto_id": f["producto_id"], "nombre": f["nombre"], "codigo_interno": f["codigo_interno"],
                                                        "categoria": f["categoria"], "celdas": {}, "venta_diaria": Decimal(0),
                                                        "en_transito": Decimal(0), "rojos": 0})
            p["celdas"][f["ubicacion_id"]] = {"disponible": f["disponible"], "dias_stock": f["dias_stock"], "semaforo": f["semaforo"], "vence": f["vence"]}
            p["venta_diaria"] += f["pronostico_diario"] or 0
            p["en_transito"] += f["en_transito"] or 0
            p["rojos"] += f["semaforo"] == "rojo"
        filas = sorted(productos.values(), key=lambda p: (-p["rojos"] if solo_problemas else 0, -p["venta_diaria"]))
        if solo_problemas:
            filas = [p for p in filas if p["rojos"]]
        return respuesta({"ubicaciones": ubic, "productos": filas[:max(10, min(limite, 1000))], "total": len(filas)})


@api.get("/sucursales/comparativo")
def comparativo(periodo_: str | None = Query(None, alias="periodo"), desde: date | None = None, hasta: date | None = None,
                ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    ver_costos = permisos.puede(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        d, h, _, _, etiqueta = periodo(conn, periodo_, desde, hasta)
        ubic = [u for u in _ubicaciones(conn) if u["tipo"] != "deposito"]
        ventas = {f["ubicacion_id"]: f for f in db.filas(conn, """
            SELECT ubicacion_id, sum(facturacion) facturacion, sum(ganancia) ganancia, sum(unidades) unidades
            FROM agg_producto_ubicacion_dia WHERE fecha BETWEEN %s AND %s GROUP BY 1""", (d, h))}
        tickets = {f["ubicacion_id"]: f["t"] for f in db.filas(conn, "SELECT ubicacion_id, sum(tickets) t FROM agg_ubicacion_hora WHERE fecha BETWEEN %s AND %s GROUP BY 1",
                                                               (d, h))}
        merma = {f["ubicacion_id"]: f["costo"] for f in db.filas(conn, """
            SELECT m.ubicacion_id, -sum(m.cantidad * coalesce(m.costo_unitario, (SELECT costo FROM producto_proveedores pp WHERE pp.producto_id = m.producto_id
                                                                                  ORDER BY principal DESC LIMIT 1), 0)) costo
            FROM movimientos_stock m JOIN organizaciones o ON o.id = m.org_id
            WHERE m.tipo IN ('merma', 'vencimiento') AND (m.fecha AT TIME ZONE o.zona_horaria)::date BETWEEN %s AND %s GROUP BY 1""", (d, h))}
        diferencias = {f["ubicacion_id"]: f for f in db.filas(conn, """
            SELECT r.ubicacion_id, -sum(least(l.diferencia_pesos, 0)) faltante, sum(greatest(l.diferencia_pesos, 0)) sobrante, count(*) contados
            FROM recuentos_lineas l JOIN recuentos r ON r.id = l.recuento_id
            WHERE l.contado IS NOT NULL AND r.fecha BETWEEN %s AND %s GROUP BY 1""", (d, h))}
        sobre, muerto = int(parametro(conn, "umbral_sobrestock_dias")), int(parametro(conn, "umbral_muerto_dias"))
        red = red_de_venta(conn)
        metr = defaultdict(lambda: {"plata_parada": Decimal(0), "en_rojo": 0, "sin_stock": 0})
        for m in db.filas(conn, """SELECT m.producto_id, m.ubicacion_id, u.tipo AS tipo_ubicacion, m.disponible, m.dias_stock, m.dias_sin_venta, m.capital, m.semaforo
                                   FROM metricas_producto_actual m JOIN ubicaciones u ON u.id = m.ubicacion_id WHERE u.tipo <> 'deposito'"""):
            if estado_stock(m, sobre, muerto, red) in ("sobrestock", "muerto"):
                metr[m["ubicacion_id"]]["plata_parada"] += m["capital"] or 0
            metr[m["ubicacion_id"]]["en_rojo"] += m["semaforo"] == "rojo"
            metr[m["ubicacion_id"]]["sin_stock"] += (m["disponible"] or 0) <= 0 and (m["dias_sin_venta"] or 999) < 30
        filas = []
        for u in ubic:
            v = ventas.get(u["id"], {})
            fac, gan = v.get("facturacion") or Decimal(0), v.get("ganancia") or Decimal(0)
            t = tickets.get(u["id"]) or 0
            dif = diferencias.get(u["id"], {})
            perdida = (merma.get(u["id"]) or Decimal(0)) + (dif.get("faltante") or Decimal(0))
            filas.append({"ubicacion_id": u["id"], "ubicacion": u["nombre"], "ventas": fac, "ganancia": gan if ver_costos else None,
                          "margen": float(gan / fac) if fac and ver_costos else None, "tickets": t, "ticket_promedio": (fac / t).quantize(Decimal("0.01")) if t else None,
                          "plata_parada": metr[u["id"]]["plata_parada"] if ver_costos else None, "merma": merma.get(u["id"]) or Decimal(0),
                          "productos_en_rojo": metr[u["id"]]["en_rojo"], "productos_sin_stock": metr[u["id"]]["sin_stock"],
                          "diferencias_inventario": dif.get("faltante") or Decimal(0), "productos_contados": dif.get("contados") or 0,
                          "perdida_pct": float(perdida / fac) if fac else 0.0})
        # Faltantes sospechosos: merma + diferencias de inventario (en % de lo vendido) muy por encima de las demás sucursales.
        for f in filas:
            otros = [x["perdida_pct"] for x in filas if x is not f]
            z = C.z_atipico(f["perdida_pct"], otros)
            promedio = sum(otros) / len(otros) if otros else 0
            f["promedio_otras_pct"] = promedio
            f["sospechoso"] = bool(otros) and f["perdida_pct"] > 0.005 and f["perdida_pct"] >= promedio * 1.5 and (z is None or z >= 1.0)
        return respuesta({"periodo": {"desde": d, "hasta": h, "etiqueta": etiqueta}, "sucursales": filas, "ver_costos": ver_costos})


@api.get("/sucursales/producto/{producto_id}")
def producto_por_sucursal(producto_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    """El mismo producto en cada sucursal: venta diaria, ranking dentro de la sucursal (por unidades de 30 días), precio y stock."""
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        p = db.fila(conn, "SELECT id, nombre, codigo_interno FROM productos WHERE id=%s", (producto_id,))
        if not p:
            raise HTTPException(status_code=404, detail="No existe ese producto.")
        filas = db.filas(conn, """
            WITH ventas AS (
                SELECT ubicacion_id, producto_id, sum(unidades) u, sum(facturacion) f
                FROM agg_producto_ubicacion_dia WHERE fecha > %(h)s - 30 AND fecha <= %(h)s GROUP BY 1, 2),
            ranking AS (SELECT *, rank() OVER (PARTITION BY ubicacion_id ORDER BY u DESC) puesto,
                               count(*) OVER (PARTITION BY ubicacion_id) de FROM ventas)
            SELECT u.id ubicacion_id, u.nombre ubicacion, r.u unidades_30d, r.f facturacion_30d, r.puesto, r.de,
                   m.vpd, m.disponible, m.dias_stock, m.semaforo,
                   coalesce((SELECT precio FROM precios x WHERE x.producto_id = %(p)s AND x.ubicacion_id = u.id AND x.canal_id IS NULL
                               AND x.desde <= %(h)s AND (x.hasta IS NULL OR x.hasta >= %(h)s) ORDER BY desde DESC LIMIT 1),
                            (SELECT precio FROM precios x WHERE x.producto_id = %(p)s AND x.ubicacion_id IS NULL AND x.canal_id IS NULL
                               AND x.desde <= %(h)s AND (x.hasta IS NULL OR x.hasta >= %(h)s) ORDER BY desde DESC LIMIT 1)) precio
            FROM ubicaciones u LEFT JOIN ranking r ON r.ubicacion_id = u.id AND r.producto_id = %(p)s
            LEFT JOIN metricas_producto_actual m ON m.ubicacion_id = u.id AND m.producto_id = %(p)s
            WHERE u.activa AND u.tipo <> 'deposito' ORDER BY u.id""", {"h": hoy, "p": producto_id})
        vpds = [float(f["vpd"] or 0) for f in filas]
        mejor = max(vpds) if vpds else 0
        for f in filas:
            f["vs_mejor"] = float(f["vpd"] or 0) / mejor if mejor else None
        return respuesta({"producto": p, "sucursales": filas})


@api.get("/sucursales/precios-distintos")
def precios_distintos(ctx: db.Contexto = Depends(sesiones.contexto)):
    """Productos con un precio propio en alguna sucursal que se aparta del general más que el umbral (3 % por defecto)."""
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        umbral = Decimal(str(parametro(conn, "umbral_precio_distinto") or "0.03"))
        filas = db.filas(conn, """
            SELECT x.producto_id, p.nombre, p.codigo_interno, u.nombre ubicacion, x.precio precio_sucursal, x.desde,
                   (SELECT g.precio FROM precios g WHERE g.producto_id = x.producto_id AND g.ubicacion_id IS NULL AND g.canal_id IS NULL
                      AND g.desde <= %(h)s AND (g.hasta IS NULL OR g.hasta >= %(h)s) ORDER BY g.desde DESC LIMIT 1) precio_general
            FROM precios x JOIN productos p ON p.id = x.producto_id JOIN ubicaciones u ON u.id = x.ubicacion_id
            WHERE x.ubicacion_id IS NOT NULL AND x.canal_id IS NULL AND x.desde <= %(h)s AND (x.hasta IS NULL OR x.hasta >= %(h)s)
            ORDER BY p.nombre, u.nombre""", {"h": hoy})
        salida = []
        for f in filas:
            if f["precio_general"]:
                f["diferencia"] = float((f["precio_sucursal"] - f["precio_general"]) / f["precio_general"])
                if abs(Decimal(str(f["diferencia"]))) >= umbral:
                    salida.append(f)
        return respuesta({"umbral": umbral, "productos": salida})


@api.get("/sucursales/ajustes")
def ajustes(dias: int = 30, ubicaciones: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Ajustes de stock auditados: quién, cuándo, cuánto y por qué (recuentos, mermas, stock importado o sincronizado)."""
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        ubic = lista_ids(ubicaciones)
        return respuesta(db.filas(conn, """
            SELECT m.id, m.fecha, m.tipo, m.cantidad, m.motivo, m.documento_tipo, p.nombre producto, p.codigo_interno, u.nombre ubicacion,
                   coalesce(us.nombre, 'Sistema') usuario,
                   m.cantidad * coalesce(m.costo_unitario, (SELECT costo FROM producto_proveedores pp WHERE pp.producto_id = m.producto_id
                                                            ORDER BY principal DESC LIMIT 1), 0) monto
            FROM movimientos_stock m JOIN productos p ON p.id = m.producto_id JOIN ubicaciones u ON u.id = m.ubicacion_id
            LEFT JOIN usuarios us ON us.id = m.usuario_id
            WHERE m.tipo IN ('ajuste', 'merma', 'vencimiento') AND m.fecha >= %s AND (%s OR m.ubicacion_id = ANY(%s))
            ORDER BY m.fecha DESC LIMIT 500""", (hoy - timedelta(days=max(1, min(dias, 365))), not ubic, ubic or [0])))
