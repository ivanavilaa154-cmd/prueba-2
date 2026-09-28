"""Ventas y análisis retail (sección 10): ganadores (10.1), Pareto ABC (10.2), ventas reales por inflación (10.3),
ticket y tráfico (10.4) y control de caja (10.7). Todo filtrado por las sucursales que ve el usuario (RLS) y por el
filtro global (período, sucursales, canal)."""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query

from . import calculos as C
from . import db, permisos, sesiones
from .api_comprar import _hoy_datos, lista_ids
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])

CRITERIOS = {
    "unidades": "Unidades", "facturacion": "Facturación", "ganancia": "Ganancia", "margen": "Margen %",
    "ganancia_por_peso": "Ganancia por peso en stock", "frecuencia": "Frecuencia en tickets",
}


def periodo(conn, nombre: str | None, desde: date | None, hasta: date | None) -> tuple[date, date, date, date, str]:
    """(desde, hasta, desde_anterior, hasta_anterior, etiqueta). El período anterior tiene la misma duración; el mes se
    compara con el mismo tramo del mes anterior (1 al 15 contra 1 al 15)."""
    hoy = _hoy_datos(conn)
    nombre = nombre or "mes"
    if nombre == "hoy":
        d, h = hoy, hoy
    elif nombre == "ayer":
        d = h = hoy - timedelta(days=1)
    elif nombre == "7d":
        d, h = hoy - timedelta(days=6), hoy
    elif nombre == "mes_anterior":
        h = hoy.replace(day=1) - timedelta(days=1)
        d = h.replace(day=1)
    elif nombre == "personalizado":
        if not desde or not hasta or desde > hasta:
            raise HTTPException(status_code=400, detail="Elegí un rango de fechas válido.")
        d, h = desde, hasta
    else:
        d, h = hoy.replace(day=1), hoy
    if nombre in ("mes", "mes_anterior"):
        prev_fin_mes = d - timedelta(days=1)
        pd = prev_fin_mes.replace(day=1)
        largo = (h - d).days
        ph = min(pd + timedelta(days=largo), prev_fin_mes)
    else:
        largo = (h - d).days + 1
        ph = d - timedelta(days=1)
        pd = ph - timedelta(days=largo - 1)
    etiquetas = {"hoy": "hoy", "ayer": "ayer", "7d": "últimos 7 días", "mes": "este mes", "mes_anterior": "mes anterior"}
    return d, h, pd, ph, etiquetas.get(nombre, f"{d.strftime('%d/%m/%Y')} a {h.strftime('%d/%m/%Y')}")


def _filtros(params: dict, ubicaciones: str | None, canal: str | None, categoria: int | None = None, proveedor: int | None = None,
             alias_l: str = "l", alias_t: str = "t") -> str:
    partes = []
    ubic = lista_ids(ubicaciones)
    if ubic:
        partes.append(f"{alias_l}.ubicacion_id = ANY(%(ubic)s)")
        params["ubic"] = ubic
    if canal and canal != "todos":
        partes.append(f"{alias_t}.canal_id = (SELECT id FROM canales WHERE codigo = %(canal)s)")
        params["canal"] = canal
    if categoria:
        partes.append(f"{alias_l}.producto_id IN (SELECT p.id FROM productos p JOIN categorias c ON c.id = p.categoria_id "
                      "WHERE c.id = %(cat)s OR c.padre_id = %(cat)s)")
        params["cat"] = categoria
    if proveedor:
        partes.append(f"{alias_l}.producto_id IN (SELECT producto_id FROM producto_proveedores WHERE proveedor_id = %(prov)s AND principal)")
        params["prov"] = proveedor
    return (" AND " + " AND ".join(partes)) if partes else ""


def _por_producto(conn, d: date, h: date, extra: str, params: dict, dia_semana: int | None, franja: str | None) -> dict:
    p = {**params, "d": d, "h": h}
    filtro_tiempo = ""
    if dia_semana is not None:
        filtro_tiempo += " AND extract(isodow FROM t.fecha_hora AT TIME ZONE o.zona_horaria) = %(dow)s"
        p["dow"] = dia_semana + 1
    if franja:
        hd, hh = (int(x) for x in franja.split("-"))
        filtro_tiempo += " AND extract(hour FROM t.fecha_hora AT TIME ZONE o.zona_horaria) >= %(hd)s AND extract(hour FROM t.fecha_hora AT TIME ZONE o.zona_horaria) < %(hh)s"
        p["hd"], p["hh"] = hd, hh
    filas = db.filas(conn, f"""
        SELECT l.producto_id, sum(l.cantidad) u, sum(l.precio_cobrado * l.cantidad) f,
               sum(l.precio_cobrado * l.cantidad) - sum(coalesce(l.costo_unitario, 0) * l.cantidad) g,
               bool_or(l.costo_unitario IS NULL) sin_costo, count(DISTINCT l.ticket_id) tk
        FROM tickets_lineas l JOIN tickets t ON t.id = l.ticket_id JOIN organizaciones o ON o.id = t.org_id
        WHERE t.estado <> 'anulado' AND l.fecha BETWEEN %(d)s AND %(h)s {extra} {filtro_tiempo}
        GROUP BY 1""", p)
    return {f["producto_id"]: f for f in filas}


@api.get("/ventas/ganadores")
def ganadores(periodo_: str | None = Query(None, alias="periodo"), desde: date | None = None, hasta: date | None = None, ubicaciones: str | None = None,
              canal: str | None = None, categoria: int | None = None, proveedor: int | None = None, dia_semana: int | None = None,
              franja: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        d, h, pd, ph, etiqueta = periodo(conn, periodo_, desde, hasta)
        params: dict = {}
        extra = _filtros(params, ubicaciones, canal, categoria, proveedor)
        actual = _por_producto(conn, d, h, extra, params, dia_semana, franja)
        anterior = _por_producto(conn, pd, ph, extra, params, dia_semana, franja)
        productos = {f["id"]: f for f in db.filas(conn, """SELECT p.id, p.nombre, p.codigo_interno, p.clase_abc, p.rol_producto,
                                                              coalesce(cp.nombre, c.nombre) AS categoria FROM productos p
                                                              LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id""")}
        p_cap: dict = {}
        extra_cap = _filtros(p_cap, ubicaciones, None, alias_l="m")
        capital = {f["producto_id"]: f["c"] for f in db.filas(conn, f"SELECT m.producto_id, sum(m.capital) c FROM metricas_producto_actual m "
                                                                   f"WHERE true {extra_cap} GROUP BY 1", p_cap)}
        tickets_total = db.fila(conn, f"""SELECT count(DISTINCT t.id) c FROM tickets t JOIN tickets_lineas l ON l.ticket_id = t.id
                                           WHERE t.estado <> 'anulado' AND l.fecha BETWEEN %(d)s AND %(h)s {extra}""", {**params, "d": d, "h": h})["c"] or 1

        def valores(f, pid):
            if not f:
                return None
            margen = (f["g"] / f["f"] * 100) if f["f"] else None
            cap = capital.get(pid)
            return {"unidades": f["u"], "facturacion": f["f"], "ganancia": f["g"], "margen": margen,
                    "ganancia_por_peso": (f["g"] / cap) if cap else None, "frecuencia": Decimal(f["tk"]) / Decimal(tickets_total) * 100,
                    "sin_costo": f["sin_costo"]}

        filas = []
        for pid, f in actual.items():
            p = productos.get(pid)
            if not p:
                continue
            filas.append({"producto_id": pid, "nombre": p["nombre"], "codigo": p["codigo_interno"], "categoria": p["categoria"],
                          "clase_abc": p["clase_abc"], "rol": p["rol_producto"], "actual": valores(f, pid), "anterior": valores(anterior.get(pid), pid)})
        rankings = {}
        for crit in CRITERIOS:
            orden = sorted([x for x in filas if x["actual"][crit] is not None], key=lambda x: x["actual"][crit], reverse=True)
            prev_orden = sorted([pid for pid, f in anterior.items() if valores(f, pid)[crit] is not None],
                                key=lambda pid: valores(anterior[pid], pid)[crit], reverse=True)
            prev_pos = {pid: i + 1 for i, pid in enumerate(prev_orden)}

            def item(x, i):
                antes = prev_pos.get(x["producto_id"])
                return {**{k: x[k] for k in ("producto_id", "nombre", "codigo", "categoria", "clase_abc", "rol")}, "posicion": i + 1,
                        "valor": x["actual"][crit], "valor_anterior": x["anterior"][crit] if x["anterior"] else None,
                        "posicion_anterior": antes, "cambio": "nuevo" if antes is None else ("sube" if antes > i + 1 else "baja" if antes < i + 1 else "igual")}
            rankings[crit] = {"mejores": [item(x, i) for i, x in enumerate(orden[:10])],
                              "peores": [item(x, len(orden) - 1 - i) for i, x in enumerate(reversed(orden[-10:]))]}
        tot = lambda dic, k: sum((f[k] for f in dic.values()), Decimal(0))
        resumen = {"facturacion": tot(actual, "f"), "facturacion_anterior": tot(anterior, "f"), "ganancia": tot(actual, "g"),
                   "ganancia_anterior": tot(anterior, "g"), "unidades": tot(actual, "u"), "unidades_anterior": tot(anterior, "u")}
        roles = defaultdict(int)
        for x in filas:
            roles[x["rol"] or "peso_muerto"] += 1
        return respuesta({"periodo": {"desde": d, "hasta": h, "desde_anterior": pd, "hasta_anterior": ph, "etiqueta": etiqueta},
                          "criterios": CRITERIOS, "rankings": rankings, "resumen": resumen, "roles": roles, "productos": len(filas)})


@api.get("/ventas/pareto")
def pareto(criterio: str = "ganancia", nivel: str = "producto", periodo_: str | None = Query(None, alias="periodo"), desde: date | None = None,
           hasta: date | None = None, ubicaciones: str | None = None, canal: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    if criterio not in ("ganancia", "unidades", "facturacion") or nivel not in ("producto", "categoria", "proveedor"):
        raise HTTPException(status_code=400, detail="Criterio o nivel no válido.")
    with db.transaccion(ctx) as conn:
        if periodo_ and periodo_ != "90d":
            d, h, _, _, etiqueta = periodo(conn, periodo_, desde, hasta)
        else:
            h = _hoy_datos(conn) - timedelta(days=1)
            d, etiqueta = h - timedelta(days=89), "últimos 90 días"
        params: dict = {"d": d, "h": h}
        extra = _filtros(params, ubicaciones, canal)
        clave = {"producto": "l.producto_id", "categoria": "coalesce(c.padre_id, c.id)", "proveedor": "pp.proveedor_id"}[nivel]
        nombre = {"producto": "p.nombre", "categoria": "coalesce(cp.nombre, c.nombre)", "proveedor": "pr.razon_social"}[nivel]
        filas = db.filas(conn, f"""
            SELECT {clave} AS id, min({nombre}) AS nombre, sum(l.cantidad) unidades, sum(l.precio_cobrado * l.cantidad) facturacion,
                   sum(l.precio_cobrado * l.cantidad) - sum(coalesce(l.costo_unitario, 0) * l.cantidad) ganancia
            FROM tickets_lineas l JOIN tickets t ON t.id = l.ticket_id JOIN productos p ON p.id = l.producto_id
            LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
            LEFT JOIN producto_proveedores pp ON pp.producto_id = p.id AND pp.principal LEFT JOIN proveedores pr ON pr.id = pp.proveedor_id
            WHERE t.estado <> 'anulado' AND l.fecha BETWEEN %(d)s AND %(h)s {extra} GROUP BY 1""", params)
        clases = C.clasificar_abc({f["id"]: f[criterio] for f in filas})
        cruzado = {}
        if nivel == "producto":
            por_unidades = C.clasificar_abc({f["id"]: f["unidades"] for f in filas})
            por_ganancia = C.clasificar_abc({f["id"]: f["ganancia"] for f in filas})
            for f in filas:
                cruzado[f["id"]] = por_unidades[f["id"]][0] + por_ganancia[f["id"]][0]
        items = []
        for f in filas:
            clase, part, acum = clases[f["id"]]
            items.append({**f, "clase": clase, "participacion": part * 100, "acumulado": acum * 100, "cruzado": cruzado.get(f["id"])})
        items.sort(key=lambda x: (-x["participacion"], str(x["nombre"])))
        conteo = defaultdict(lambda: {"items": 0, "participacion": Decimal(0)})
        for it in items:
            conteo[it["clase"]]["items"] += 1
            conteo[it["clase"]]["participacion"] += it["participacion"]
        matriz = defaultdict(int)
        for c in cruzado.values():
            matriz[c] += 1
        historial = []
        if nivel == "producto":
            historial = db.filas(conn, """SELECT h.producto_id, h.mes, h.clase FROM historial_abc h
                                          WHERE h.mes >= %s ORDER BY h.mes""", (_hoy_datos(conn).replace(day=1) - timedelta(days=370),))
        return respuesta({"criterio": criterio, "nivel": nivel, "periodo": {"desde": d, "hasta": h, "etiqueta": etiqueta}, "items": items,
                          "resumen": dict(conteo), "matriz_cruzada": dict(matriz), "historial": historial,
                          "suma_participaciones": sum((i["participacion"] for i in items), Decimal(0))})


@api.get("/ventas/inflacion")
def inflacion(meses: int = 13, ubicaciones: str | None = None, canal: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Ventas nominales, en unidades y deflactadas con el IPC (en pesos del último mes con índice)."""
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        desde = (hoy.replace(day=1) - timedelta(days=31 * (meses - 1))).replace(day=1)
        params: dict = {"d": desde}
        extra = _filtros(params, ubicaciones, canal)
        filas = db.filas(conn, f"""SELECT date_trunc('month', l.fecha)::date mes, sum(l.precio_cobrado * l.cantidad) nominal, sum(l.cantidad) unidades,
                                          count(DISTINCT l.fecha) dias
                                   FROM tickets_lineas l JOIN tickets t ON t.id = l.ticket_id
                                   WHERE t.estado <> 'anulado' AND l.fecha >= %(d)s {extra} GROUP BY 1 ORDER BY 1""", params)
        ipc = {f["periodo"]: f["indice"] for f in db.filas(conn, "SELECT periodo, indice FROM indice_precios ORDER BY periodo")}
        if not ipc:
            return respuesta({"meses": [], "aviso": "Todavía no hay índice de precios cargado (Configuración → Índice de precios)."})
        base_mes = max(ipc)
        base = ipc[base_mes]
        resultado = []
        por_mes = {}
        for f in filas:
            anteriores = [k for k in ipc if k <= f["mes"]]
            indice = ipc.get(f["mes"]) or (ipc[max(anteriores)] if anteriores else None)
            real = C.deflactar(f["nominal"], indice, base) if indice else None
            fila = {"mes": f["mes"], "nominal": f["nominal"], "unidades": f["unidades"], "real": real, "indice": indice, "dias": f["dias"],
                    "mes_incompleto": f["mes"] == hoy.replace(day=1) and hoy.day < calendar.monthrange(hoy.year, hoy.month)[1]}
            por_mes[f["mes"]] = fila
            resultado.append(fila)
        for fila in resultado:
            m = fila["mes"]
            prev = por_mes.get((m - timedelta(days=1)).replace(day=1))
            anio = por_mes.get(m.replace(year=m.year - 1))
            for nombre, otro in (("mensual", prev), ("interanual", anio)):
                if otro and otro["real"] and fila["real"]:
                    fila[f"var_{nombre}_real"] = (fila["real"] / otro["real"] - 1) * 100
                    fila[f"var_{nombre}_nominal"] = (fila["nominal"] / otro["nominal"] - 1) * 100
                    fila[f"efectos_{nombre}"] = C.efecto_precio_cantidad(otro["nominal"], otro["unidades"], fila["nominal"], fila["unidades"])
        return respuesta({"meses": resultado, "base": base_mes, "fuente_ipc": db.fila(conn, "SELECT fuente FROM indice_precios ORDER BY periodo DESC LIMIT 1")["fuente"]})


@api.get("/ventas/ticket")
def ticket_y_trafico(periodo_: str | None = Query(None, alias="periodo"), desde: date | None = None, hasta: date | None = None, ubicaciones: str | None = None,
                     canal: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        d, h, pd, ph, etiqueta = periodo(conn, periodo_, desde, hasta)
        params: dict = {}
        extra = _filtros(params, ubicaciones, canal, alias_l="t")

        def totales(a, b):
            return db.fila(conn, f"""SELECT count(*) FILTER (WHERE t.total > 0) tickets, coalesce(sum(t.total), 0) ventas,
                                            coalesce(sum((SELECT sum(l.cantidad) FROM tickets_lineas l WHERE l.ticket_id = t.id)), 0) unidades
                                     FROM tickets t JOIN organizaciones o ON o.id = t.org_id
                                     WHERE t.estado <> 'anulado' AND (t.fecha_hora AT TIME ZONE o.zona_horaria)::date BETWEEN %(a)s AND %(b)s {extra}""",
                           {**params, "a": a, "b": b})
        act, ant = totales(d, h), totales(pd, ph)
        desc = C.efecto_clientes_gasto(ant["ventas"], ant["tickets"], act["ventas"], act["tickets"])
        por = {}
        for dim, expr in (("ubicacion", "u.nombre"), ("canal", "c.nombre"), ("dia", "extract(isodow FROM t.fecha_hora AT TIME ZONE o.zona_horaria)::int"),
                          ("hora", "extract(hour FROM t.fecha_hora AT TIME ZONE o.zona_horaria)::int")):
            por[dim] = db.filas(conn, f"""SELECT {expr} AS clave, count(*) FILTER (WHERE t.total > 0) tickets, sum(t.total) ventas,
                                                 sum(t.total) / nullif(count(*) FILTER (WHERE t.total > 0), 0) promedio,
                                                 sum((SELECT sum(l.cantidad) FROM tickets_lineas l WHERE l.ticket_id = t.id))
                                                   / nullif(count(*) FILTER (WHERE t.total > 0), 0) unidades_promedio
                                          FROM tickets t JOIN organizaciones o ON o.id = t.org_id JOIN ubicaciones u ON u.id = t.ubicacion_id
                                          JOIN canales c ON c.id = t.canal_id
                                          WHERE t.estado <> 'anulado' AND (t.fecha_hora AT TIME ZONE o.zona_horaria)::date BETWEEN %(a)s AND %(b)s {extra}
                                          GROUP BY 1 ORDER BY 1""", {**params, "a": d, "b": h})
        p_mapa: dict = {"a": d if (h - d).days >= 27 else h - timedelta(days=27), "b": h}   # el mapa usa al menos 4 semanas
        extra_a = _filtros(p_mapa, ubicaciones, canal, alias_l="a", alias_t="a")
        mapa = db.filas(conn, f"""SELECT extract(isodow FROM a.fecha)::int - 1 dia, a.hora, sum(a.tickets) tickets, sum(a.facturacion) facturacion,
                                         count(DISTINCT a.fecha) dias
                                  FROM agg_ubicacion_hora a WHERE a.fecha BETWEEN %(a)s AND %(b)s {extra_a} GROUP BY 1, 2""", p_mapa)
        return respuesta({"periodo": {"desde": d, "hasta": h, "desde_anterior": pd, "hasta_anterior": ph, "etiqueta": etiqueta},
                          "actual": {**act, "promedio": act["ventas"] / act["tickets"] if act["tickets"] else None,
                                     "unidades_promedio": act["unidades"] / act["tickets"] if act["tickets"] else None},
                          "anterior": {**ant, "promedio": ant["ventas"] / ant["tickets"] if ant["tickets"] else None},
                          "descomposicion": desc, "por": por, "mapa_calor": mapa})


@api.get("/caja")
def control_de_caja(periodo_: str | None = Query(None, alias="periodo"), desde: date | None = None, hasta: date | None = None, ubicaciones: str | None = None,
                    ctx: db.Contexto = Depends(sesiones.contexto)):
    """Anulaciones, devoluciones, descuentos manuales y ventas a precio distinto de lista, por cajero, turno, sucursal y hora,
    con detección de valores atípicos (cuántos desvíos se aleja cada cajero del resto de su sucursal)."""
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        d, h, _, _, etiqueta = periodo(conn, periodo_ or "mes", desde, hasta)
        params: dict = {"a": d, "b": h}
        extra = _filtros(params, ubicaciones, None, alias_l="t")
        cajeros = db.filas(conn, f"""
            WITH base AS (
                SELECT t.*, u.nombre AS ubicacion, CASE WHEN extract(hour FROM t.fecha_hora AT TIME ZONE o.zona_horaria) < 14 THEN 'mañana' ELSE 'tarde' END turno
                FROM tickets t JOIN organizaciones o ON o.id = t.org_id JOIN ubicaciones u ON u.id = t.ubicacion_id
                WHERE t.cajero IS NOT NULL AND (t.fecha_hora AT TIME ZONE o.zona_horaria)::date BETWEEN %(a)s AND %(b)s {extra})
            SELECT b.ubicacion_id, b.ubicacion, b.cajero, count(*) tickets,
                   count(*) FILTER (WHERE b.estado='anulado') anulaciones, coalesce(sum(b.total) FILTER (WHERE b.estado='anulado'), 0) monto_anulado,
                   count(*) FILTER (WHERE b.estado='devuelto') devoluciones, coalesce(-sum(b.total) FILTER (WHERE b.estado='devuelto'), 0) monto_devuelto,
                   (SELECT count(*) FROM tickets_lineas l WHERE l.ticket_id IN (SELECT id FROM base b2 WHERE b2.cajero = b.cajero AND b2.ubicacion_id = b.ubicacion_id)
                      AND l.descuento_manual) descuentos_manuales,
                   (SELECT coalesce(sum(l.descuento), 0) FROM tickets_lineas l WHERE l.ticket_id IN (SELECT id FROM base b2 WHERE b2.cajero = b.cajero AND b2.ubicacion_id = b.ubicacion_id)
                      AND l.descuento_manual) monto_descuentos,
                   (SELECT count(*) FROM tickets_lineas l WHERE l.ticket_id IN (SELECT id FROM base b2 WHERE b2.cajero = b.cajero AND b2.ubicacion_id = b.ubicacion_id)
                      AND l.promocion_id IS NULL AND l.precio_lista IS NOT NULL AND l.precio_cobrado <> l.precio_lista) fuera_de_lista
            FROM base b GROUP BY 1, 2, 3 ORDER BY 2, 3""", params)
        por_sucursal = defaultdict(list)
        for c in cajeros:
            t = c["tickets"] or 1
            c["tasa_anulaciones"] = c["anulaciones"] / t * 100
            c["tasa_descuentos"] = c["descuentos_manuales"] / t * 100
            c["tasa_devoluciones"] = c["devoluciones"] / t * 100
            por_sucursal[c["ubicacion_id"]].append(c)
        alertas = []
        for grupo in por_sucursal.values():
            for c in grupo:
                otros = [x for x in grupo if x is not c]
                for medida, nombre in (("tasa_anulaciones", "anulaciones"), ("tasa_descuentos", "descuentos manuales"), ("tasa_devoluciones", "devoluciones")):
                    z = C.z_atipico(float(c[medida]), [float(x[medida]) for x in otros])
                    c[f"z_{medida}"] = z
                    promedio = sum(float(x[medida]) for x in otros) / len(otros) if otros else 0
                    # Además del desvío, que la cantidad no pueda explicarse por azar: con pocos cajeros el desvío de los demás es
                    # chico y 12 anulaciones contra 8 esperadas darían «atípico» sin serlo.
                    cuenta = {"tasa_anulaciones": "anulaciones", "tasa_descuentos": "descuentos_manuales", "tasa_devoluciones": "devoluciones"}[medida]
                    tasa_otros = sum(x[cuenta] for x in otros) / max(1, sum(x["tickets"] or 0 for x in otros))
                    raro = C.prob_poisson_al_menos(int(c[cuenta]), tasa_otros * (c["tickets"] or 0)) < 0.01
                    if z is not None and z >= 2 and float(c[medida]) > promedio * 1.5 and raro:
                        alertas.append({"ubicacion": c["ubicacion"], "cajero": c["cajero"], "medida": nombre, "valor": c[medida],
                                        "promedio_otros": promedio, "z": z,
                                        "monto": c["monto_anulado"] if medida == "tasa_anulaciones" else c["monto_descuentos"] if medida == "tasa_descuentos" else c["monto_devuelto"]})
        por_turno = db.filas(conn, f"""SELECT u.nombre ubicacion, CASE WHEN extract(hour FROM t.fecha_hora AT TIME ZONE o.zona_horaria) < 14 THEN 'mañana' ELSE 'tarde' END turno,
                                              count(*) tickets, count(*) FILTER (WHERE t.estado='anulado') anulaciones, count(*) FILTER (WHERE t.estado='devuelto') devoluciones
                                       FROM tickets t JOIN organizaciones o ON o.id = t.org_id JOIN ubicaciones u ON u.id = t.ubicacion_id
                                       WHERE (t.fecha_hora AT TIME ZONE o.zona_horaria)::date BETWEEN %(a)s AND %(b)s {extra} GROUP BY 1, 2 ORDER BY 1, 2""", params)
        por_hora = db.filas(conn, f"""SELECT extract(hour FROM t.fecha_hora AT TIME ZONE o.zona_horaria)::int hora, count(*) FILTER (WHERE t.estado='anulado') anulaciones,
                                             count(*) tickets FROM tickets t JOIN organizaciones o ON o.id = t.org_id
                                      WHERE (t.fecha_hora AT TIME ZONE o.zona_horaria)::date BETWEEN %(a)s AND %(b)s {extra} GROUP BY 1 ORDER BY 1""", params)
        detalle = db.filas(conn, f"""SELECT a.tipo, a.cajero, a.motivo, a.fecha_hora, a.monto, u.nombre ubicacion, t.numero_externo
                                     FROM anulaciones_devoluciones a JOIN ubicaciones u ON u.id = a.ubicacion_id LEFT JOIN tickets t ON t.id = a.ticket_id
                                     JOIN organizaciones o ON o.id = a.org_id
                                     WHERE (a.fecha_hora AT TIME ZONE o.zona_horaria)::date BETWEEN %(a)s AND %(b)s {extra.replace('t.ubicacion_id', 'a.ubicacion_id')}
                                     ORDER BY a.fecha_hora DESC LIMIT 300""", params)
        diferencias_inv = db.filas(conn, """SELECT u.nombre ubicacion, count(*) FILTER (WHERE l.diferencia < 0) faltantes, coalesce(-sum(l.diferencia_pesos) FILTER (WHERE l.diferencia < 0), 0) monto
                                            FROM recuentos_lineas l JOIN recuentos r ON r.id = l.recuento_id JOIN ubicaciones u ON u.id = r.ubicacion_id
                                            WHERE r.fecha > %s GROUP BY 1 ORDER BY 3 DESC""", (h - timedelta(days=90),))
        return respuesta({"periodo": {"desde": d, "hasta": h, "etiqueta": etiqueta}, "cajeros": cajeros, "alertas": alertas, "por_turno": por_turno,
                          "por_hora": por_hora, "detalle": detalle, "diferencias_inventario": diferencias_inv})
