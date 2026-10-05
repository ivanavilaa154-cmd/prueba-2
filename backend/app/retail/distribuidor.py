"""Modo distribuidor (SPEC v2, sección 12B): cálculos de los 5 reportes iniciales (12B.7) y de la vista del vendedor.

Una «compra» del cliente es un pedido que no se anuló ni se rechazó en la entrega. Lo que se vende de un pedido:
- entregado o entregado parcial → lo entregado;
- tomado, preparado o despachado (todavía en camino) → lo pedido;
- rechazado o anulado → nada.
Precios y costos de los pedidos son sin impuestos (el distribuidor factura con IVA aparte), así la ganancia es neta.

Todas las consultas pasan por la RLS: un vendedor (app.vendedor_id) solo ve los clientes de su cartera y lo que cuelga de ellos.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, timedelta

from . import calculos, db

COMPRA = "p.estado NOT IN ('anulado', 'rechazado')"
FACTURABLE = ("CASE WHEN p.estado IN ('entregado', 'entregado_parcial') THEN l.cantidad_entregada "
              "WHEN p.estado IN ('tomado', 'preparado', 'despachado') THEN l.cantidad_pedida ELSE 0 END")
ESTADOS = {"activo": "Activo", "en_riesgo": "En riesgo", "perdido": "Dejó de comprar", "sin_compras": "Sin compras en el año"}
TRAMOS = ("a_vencer", "d0_30", "d31_60", "d61_90", "d90_mas")


def _f(v) -> float:
    return float(v or 0)


# ------------------------------------------------------------------------------------------------ 1. clientes que dejaron de comprar
def umbrales(conn) -> dict:
    o = db.fila(conn, "SELECT cliente_factor_riesgo r, cliente_factor_perdido p, cliente_perdido_min_dias m FROM organizaciones WHERE id = app_org()")
    return {"riesgo": float(o["r"]), "perdido": float(o["p"]), "min_dias": int(o["m"])} if o else {"riesgo": 1.5, "perdido": 3.0, "min_dias": 21}


def clasificar(fechas: list[date], hoy: date, u: dict) -> dict:
    """Estado de un cliente según su propio ritmo: el intervalo habitual es la mediana de sus últimos 12 intervalos entre compras.
    Con menos de 3 compras no hay ritmo propio y se toma 30 días."""
    if not fechas:
        return {"estado": "sin_compras", "intervalo": None, "dias_sin_comprar": None, "ultima_compra": None, "proxima_esperada": None}
    diferencias = [(b - a).days for a, b in zip(fechas, fechas[1:])][-12:]
    intervalo = max(1.0, statistics.median(diferencias)) if len(fechas) >= 3 else 30.0
    dias = (hoy - fechas[-1]).days
    if dias > max(u["min_dias"], u["perdido"] * intervalo):
        estado = "perdido"
    elif dias > u["riesgo"] * intervalo:
        estado = "en_riesgo"
    else:
        estado = "activo"
    return {"estado": estado, "intervalo": round(intervalo, 1), "dias_sin_comprar": dias, "ultima_compra": fechas[-1],
            "proxima_esperada": fechas[-1] + timedelta(days=round(intervalo)), "pocas_compras": len(fechas) < 3}


def estado_clientes(conn, hoy: date) -> list[dict]:
    """Un renglón por cliente con su estado y la plata que se deja de facturar por mes (lo que compraba en los 180 días
    anteriores a su última compra, llevado a 30 días)."""
    u = umbrales(conn)
    clientes = db.filas(conn, f"""
        SELECT c.id, c.razon_social, c.nombre_fantasia, c.localidad, c.zona, c.canal, c.vendedor_id, v.nombre AS vendedor,
               c.limite_credito, (SELECT array_agg(DISTINCT p.fecha ORDER BY p.fecha) FROM pedidos_venta p
                                  WHERE p.cliente_id = c.id AND {COMPRA} AND p.fecha > %(hoy)s::date - 400 AND p.fecha <= %(hoy)s) AS fechas
        FROM clientes_b2b c LEFT JOIN vendedores v ON v.id = c.vendedor_id
        WHERE c.activo ORDER BY c.razon_social""", {"hoy": hoy})
    ventas = {f["cliente_id"]: f for f in db.filas(conn, f"""
        WITH u AS (SELECT p.cliente_id, max(p.fecha) ultima, min(p.fecha) primera FROM pedidos_venta p
                   WHERE {COMPRA} AND p.fecha <= %(hoy)s GROUP BY 1)
        SELECT p.cliente_id, u.ultima, u.primera, sum(l.precio * {FACTURABLE}) venta,
               sum((l.precio - coalesce(l.costo_unitario, l.precio)) * {FACTURABLE}) ganancia
        FROM pedidos_venta p JOIN u ON u.cliente_id = p.cliente_id JOIN pedidos_venta_lineas l ON l.pedido_id = p.id
        WHERE {COMPRA} AND p.fecha > u.ultima - 180 AND p.fecha <= u.ultima GROUP BY 1, 2, 3""", {"hoy": hoy})}
    salida = []
    for c in clientes:
        e = clasificar(c["fechas"] or [], hoy, u)
        v = ventas.get(c["id"])
        mensual = ganancia_mensual = 0.0
        if v:
            base = min(180, (v["ultima"] - max(v["primera"], v["ultima"] - timedelta(days=180))).days + (e["intervalo"] or 30))
            mensual = _f(v["venta"]) * 30 / base
            ganancia_mensual = _f(v["ganancia"]) * 30 / base
        perdiendo = e["estado"] in ("en_riesgo", "perdido")
        salida.append({"cliente_id": c["id"], "cliente": c["nombre_fantasia"] or c["razon_social"], "razon_social": c["razon_social"],
                       "localidad": c["localidad"], "zona": c["zona"], "canal": c["canal"], "vendedor_id": c["vendedor_id"], "vendedor": c["vendedor"],
                       **{k: v for k, v in e.items() if k != "pocas_compras"}, "pocas_compras": e.get("pocas_compras", False),
                       "venta_mensual": round(mensual, 2), "ganancia_mensual": round(ganancia_mensual, 2),
                       "deja_de_facturar_mes": round(mensual, 2) if perdiendo else 0.0,
                       "explicacion": _explicar(e)})
    return salida


def _explicar(e: dict) -> str:
    if e["estado"] == "sin_compras":
        return "No compró en el último año."
    ritmo = f"compra cada {e['intervalo']:g} días" if not e.get("pocas_compras") else "compró pocas veces (se toma un ritmo de 30 días)"
    return f"{ritmo.capitalize()} y lleva {e['dias_sin_comprar']} días sin comprar."


def resumen_clientes(filas: list[dict]) -> dict:
    cuenta = defaultdict(int)
    for f in filas:
        cuenta[f["estado"]] += 1
    return {"total": len(filas), **{k: cuenta.get(k, 0) for k in ESTADOS},
            "deja_de_facturar_mes": round(sum(f["deja_de_facturar_mes"] for f in filas), 2),
            "en_juego_perdidos": round(sum(f["deja_de_facturar_mes"] for f in filas if f["estado"] == "perdido"), 2),
            "en_juego_riesgo": round(sum(f["deja_de_facturar_mes"] for f in filas if f["estado"] == "en_riesgo"), 2)}


# ------------------------------------------------------------------------------------------------ 2. rendimiento por vendedor
def _por_vendedor(conn, desde: date, hasta: date) -> dict:
    filas = db.filas(conn, f"""
        SELECT p.vendedor_id, sum(l.precio * {FACTURABLE}) venta, sum(coalesce(l.costo_unitario, 0) * {FACTURABLE}) costo,
               sum(greatest(l.precio_lista - l.precio, 0) * {FACTURABLE}) descuentos, sum(l.precio_lista * {FACTURABLE}) venta_lista,
               count(DISTINCT p.id) pedidos, count(DISTINCT p.cliente_id) clientes,
               count(DISTINCT (p.cliente_id, l.producto_id)) cliente_producto, count(DISTINCT (p.cliente_id, pr.categoria_id)) cliente_categoria
        FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id JOIN productos pr ON pr.id = l.producto_id
        WHERE {COMPRA} AND p.fecha BETWEEN %s AND %s AND p.vendedor_id IS NOT NULL GROUP BY 1""", (desde, hasta))
    return {f["vendedor_id"]: f for f in filas}


def rendimiento_vendedores(conn, desde: date, hasta: date, hoy: date) -> dict:
    dias = (hasta - desde).days + 1
    actual, anterior = _por_vendedor(conn, desde, hasta), _por_vendedor(conn, desde - timedelta(days=dias), desde - timedelta(days=1))
    mes = hoy.replace(day=1)
    fin_mes = (mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    del_mes = _por_vendedor(conn, mes, hoy)
    metas = {m["vendedor_id"]: m for m in db.filas(conn, "SELECT vendedor_id, venta, ganancia FROM metas_vendedor WHERE mes = %s", (mes,))}
    estados = defaultdict(lambda: {"en_riesgo": 0, "perdido": 0, "plata": 0.0})
    for c in estado_clientes(conn, hoy):
        if c["estado"] in ("en_riesgo", "perdido") and c["vendedor_id"]:
            estados[c["vendedor_id"]][c["estado"]] += 1
            estados[c["vendedor_id"]]["plata"] += c["deja_de_facturar_mes"]
    filas = []
    for v in db.filas(conn, "SELECT id, nombre, zona FROM vendedores WHERE activo ORDER BY nombre"):
        a, b, m = actual.get(v["id"], {}), anterior.get(v["id"], {}), del_mes.get(v["id"], {})
        venta, costo = _f(a.get("venta")), _f(a.get("costo"))
        ganancia = venta - costo
        venta_ant = _f(b.get("venta"))
        meta = metas.get(v["id"])
        transcurridos = (hoy - mes).days + 1
        proyeccion = _f(m.get("venta")) / transcurridos * fin_mes.day if transcurridos else 0.0
        clientes = int(a.get("clientes") or 0)
        filas.append({
            "vendedor_id": v["id"], "vendedor": v["nombre"], "zona": v["zona"], "venta": round(venta, 2), "ganancia": round(ganancia, 2),
            "margen": round(ganancia / venta, 4) if venta else None, "descuentos": round(_f(a.get("descuentos")), 2),
            "descuento_pct": round(_f(a.get("descuentos")) / _f(a.get("venta_lista")), 4) if _f(a.get("venta_lista")) else None,
            "venta_anterior": round(venta_ant, 2), "variacion": round(venta / venta_ant - 1, 4) if venta_ant else None,
            "pedidos": int(a.get("pedidos") or 0), "clientes": clientes,
            "productos_por_cliente": round(int(a.get("cliente_producto") or 0) / clientes, 1) if clientes else None,
            "categorias_por_cliente": round(int(a.get("cliente_categoria") or 0) / clientes, 1) if clientes else None,
            "meta_mes": _f(meta["venta"]) if meta and meta["venta"] else None, "venta_mes": round(_f(m.get("venta")), 2),
            "proyeccion_mes": round(proyeccion, 2),
            "cumplimiento_proyectado": round(proyeccion / _f(meta["venta"]), 4) if meta and meta["venta"] else None,
            "clientes_en_riesgo": estados[v["id"]]["en_riesgo"], "clientes_perdidos": estados[v["id"]]["perdido"],
            "plata_en_riesgo_mes": round(estados[v["id"]]["plata"], 2)})
    filas.sort(key=lambda f: -f["venta"])
    for i, f in enumerate(filas, 1):
        f["ranking"] = i
    con_clientes = [f for f in filas if f["clientes"]]
    equipo = {"productos_por_cliente": round(statistics.mean(f["productos_por_cliente"] for f in con_clientes), 1) if con_clientes else None,
              "categorias_por_cliente": round(statistics.mean(f["categorias_por_cliente"] for f in con_clientes), 1) if con_clientes else None,
              "venta": round(sum(f["venta"] for f in filas), 2), "ganancia": round(sum(f["ganancia"] for f in filas), 2),
              "descuentos": round(sum(f["descuentos"] for f in filas), 2)}
    equipo["margen"] = round(equipo["ganancia"] / equipo["venta"], 4) if equipo["venta"] else None
    return {"desde": desde, "hasta": hasta, "vendedores": filas, "equipo": equipo, "marcas": objetivos_marcas(conn, hoy)}


def objetivos_marcas(conn, hoy: date) -> list[dict]:
    """Objetivos de las marcas representadas vigentes y la bonificación en riesgo («faltan 120 unidades para cobrar $X»)."""
    salida = []
    for o in db.filas(conn, "SELECT * FROM objetivos_marca WHERE desde <= %s AND hasta >= %s ORDER BY marca", (hoy, hoy)):
        r = db.fila(conn, f"""
            SELECT coalesce(sum({FACTURABLE}), 0) volumen, count(DISTINCT p.cliente_id) FILTER (WHERE {FACTURABLE} > 0) cobertura,
                   count(DISTINCT l.producto_id) FILTER (WHERE {FACTURABLE} > 0) mix
            FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id JOIN productos pr ON pr.id = l.producto_id
            WHERE {COMPRA} AND p.fecha BETWEEN %s AND %s AND lower(pr.marca) = lower(%s)""", (o["desde"], min(hoy, o["hasta"]), o["marca"]))
        logrado = _f(r[o["tipo"]])
        transcurrido = ((min(hoy, o["hasta"]) - o["desde"]).days + 1) / ((o["hasta"] - o["desde"]).days + 1)
        proyectado = logrado / transcurrido if o["tipo"] == "volumen" and transcurrido else logrado
        objetivo = _f(o["objetivo"])
        unidad = {"volumen": "unidades", "cobertura": "clientes", "mix": "productos"}[o["tipo"]]
        falta = max(0.0, objetivo - logrado)
        salida.append({"marca": o["marca"], "tipo": o["tipo"], "desde": o["desde"], "hasta": o["hasta"], "objetivo": objetivo, "logrado": logrado,
                       "avance": round(logrado / objetivo, 4), "proyectado": round(proyectado, 1), "bonificacion": _f(o["bonificacion"]),
                       "en_riesgo": proyectado < objetivo, "falta": falta,
                       "mensaje": (f"Faltan {falta:,.0f} {unidad} para cobrar la bonificación de ${_f(o['bonificacion']):,.0f}."
                                   .replace(",", ".") if falta else "Objetivo cumplido.")})
    return salida


# ------------------------------------------------------------------------------------------------ 4. cuenta corriente vencida
def tramo(dias_vencido: int) -> str:
    if dias_vencido <= 0:
        return "a_vencer"
    return "d0_30" if dias_vencido <= 30 else "d31_60" if dias_vencido <= 60 else "d61_90" if dias_vencido <= 90 else "d90_mas"


def cuenta_corriente(conn, hoy: date) -> dict:
    docs = db.filas(conn, "SELECT cliente_id, tipo, saldo, coalesce(vencimiento, fecha) vence FROM documentos_cc WHERE saldo <> 0")
    por_cliente: dict[int, dict] = defaultdict(lambda: {**{t: 0.0 for t in TRAMOS}, "a_favor": 0.0, "dias_max": 0})
    for d in docs:
        c = por_cliente[d["cliente_id"]]
        if d["saldo"] < 0:
            c["a_favor"] += _f(d["saldo"])
            continue
        dias = (hoy - d["vence"]).days
        c[tramo(dias)] += _f(d["saldo"])
        c["dias_max"] = max(c["dias_max"], dias)
    if not por_cliente:
        return {"clientes": [], "totales": {**{t: 0.0 for t in TRAMOS}, "saldo": 0.0, "vencido": 0.0}, "por_vendedor": [], "compromisos": []}
    clientes = {c["id"]: c for c in db.filas(conn, f"""
        SELECT c.id, coalesce(c.nombre_fantasia, c.razon_social) cliente, c.limite_credito, c.vendedor_id, v.nombre vendedor,
               (SELECT max(p.fecha) FROM pedidos_venta p WHERE p.cliente_id = c.id AND {COMPRA}) ultima_compra
        FROM clientes_b2b c LEFT JOIN vendedores v ON v.id = c.vendedor_id WHERE c.id = ANY(%s)""", (list(por_cliente),))}
    compromisos = defaultdict(list)
    for p in db.filas(conn, "SELECT id, cliente_id, fecha, monto, estado, nota FROM compromisos_pago WHERE estado = 'pendiente' OR fecha >= %s ORDER BY fecha",
                      (hoy - timedelta(days=60),)):
        p["incumplido"] = p["estado"] == "incumplido" or (p["estado"] == "pendiente" and p["fecha"] < hoy)
        compromisos[p["cliente_id"]].append(p)
    filas = []
    for cid, t in por_cliente.items():
        c = clientes.get(cid)
        if not c:
            continue
        vencido = sum(t[k] for k in TRAMOS[1:])
        saldo = sum(t[k] for k in TRAMOS) + t["a_favor"]
        if saldo <= 0 and not vencido:
            continue
        sigue = bool(c["ultima_compra"] and vencido > 0 and t["dias_max"] > 30 and (hoy - c["ultima_compra"]).days <= 14)
        supera = bool(c["limite_credito"] and saldo > _f(c["limite_credito"]))
        alertas = []
        if sigue:
            alertas.append("Tiene deuda vencida de más de 30 días y sigue comprando.")
        if supera:
            alertas.append(f"Supera su límite de crédito (${_f(c['limite_credito']):,.0f}): conviene frenar nuevos pedidos hasta que pague.".replace(",", "."))
        if any(p["incumplido"] for p in compromisos[cid]):
            alertas.append("No cumplió un compromiso de pago.")
        filas.append({"cliente_id": cid, "cliente": c["cliente"], "vendedor_id": c["vendedor_id"], "vendedor": c["vendedor"],
                      **{k: round(t[k], 2) for k in TRAMOS}, "a_favor": round(t["a_favor"], 2), "saldo": round(saldo, 2), "vencido": round(vencido, 2),
                      "dias_mayor_atraso": max(0, t["dias_max"]), "limite_credito": _f(c["limite_credito"]) if c["limite_credito"] else None,
                      "sigue_comprando": sigue, "supera_limite": supera, "bloqueo_sugerido": supera or (sigue and t["dias_max"] > 60),
                      "ultima_compra": c["ultima_compra"], "compromisos": compromisos[cid], "alertas": alertas})
    filas.sort(key=lambda f: (-f["d90_mas"] - f["d61_90"], -f["vencido"]))
    totales = {k: round(sum(f[k] for f in filas), 2) for k in (*TRAMOS, "saldo", "vencido")}
    cobrado = {r["vendedor_id"]: _f(r["cobrado"]) for r in db.filas(conn, """
        SELECT c.vendedor_id, -sum(d.importe) cobrado FROM documentos_cc d JOIN clientes_b2b c ON c.id = d.cliente_id
        WHERE d.tipo = 'recibo' AND d.fecha > %s GROUP BY 1""", (hoy - timedelta(days=30),))}
    vend = defaultdict(lambda: {"vencido": 0.0, "saldo": 0.0, "clientes_con_deuda_vencida": 0})
    for f in filas:
        x = vend[(f["vendedor_id"], f["vendedor"])]
        x["vencido"] += f["vencido"]
        x["saldo"] += f["saldo"]
        x["clientes_con_deuda_vencida"] += f["vencido"] > 0
    por_vendedor = sorted(({"vendedor_id": k[0], "vendedor": k[1] or "Sin vendedor", "vencido": round(x["vencido"], 2), "saldo": round(x["saldo"], 2),
                            "clientes_con_deuda_vencida": x["clientes_con_deuda_vencida"], "cobrado_30_dias": round(cobrado.get(k[0], 0.0), 2)}
                           for k, x in vend.items()), key=lambda r: -r["vencido"])
    return {"clientes": filas, "totales": totales, "por_vendedor": por_vendedor,
            "alertas": {"sigue_comprando": sum(f["sigue_comprando"] for f in filas), "supera_limite": sum(f["supera_limite"] for f in filas)}}


# ------------------------------------------------------------------------------------------------ 5. Pareto de clientes y productos
def pareto(conn, desde: date, hasta: date) -> dict:
    """Por ganancia (neta de descuentos) en el período."""
    def armar(filas: list[dict], clave: str, nombre: str) -> dict:
        abc = calculos.clasificar_abc({f[clave]: f["ganancia"] for f in filas})
        salida = []
        for f in sorted(filas, key=lambda f: -_f(f["ganancia"])):
            clase, part, acum = abc[f[clave]]
            salida.append({"id": f[clave], "nombre": f[nombre], "venta": round(_f(f["venta"]), 2), "ganancia": round(_f(f["ganancia"]), 2),
                           "clase": clase, "participacion": round(float(part), 4), "acumulado": round(float(acum), 4)})
        a = [s for s in salida if s["clase"] == "A"]
        return {"filas": salida, "cantidad": len(salida), "clase_a": len(a),
                "mensaje": (f"{len(a)} de {len(salida)} ({len(a) / len(salida):.0%}) dejan el 80 % de la ganancia." if salida else "Sin ventas en el período.")}
    base = f"""FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id
               WHERE {COMPRA} AND p.fecha BETWEEN %(d)s AND %(h)s"""
    clientes = db.filas(conn, f"""
        SELECT p.cliente_id, coalesce(c.nombre_fantasia, c.razon_social) cliente, sum(l.precio * {FACTURABLE}) venta,
               sum((l.precio - coalesce(l.costo_unitario, l.precio)) * {FACTURABLE}) ganancia
        {base.replace('WHERE', 'JOIN clientes_b2b c ON c.id = p.cliente_id WHERE', 1)} GROUP BY 1, 2""", {"d": desde, "h": hasta})
    productos = db.filas(conn, f"""
        SELECT l.producto_id, pr.nombre producto, sum(l.precio * {FACTURABLE}) venta,
               sum((l.precio - coalesce(l.costo_unitario, l.precio)) * {FACTURABLE}) ganancia
        {base.replace('WHERE', 'JOIN productos pr ON pr.id = l.producto_id WHERE', 1)} GROUP BY 1, 2""", {"d": desde, "h": hasta})
    return {"desde": desde, "hasta": hasta, "clientes": armar(clientes, "cliente_id", "cliente"), "productos": armar(productos, "producto_id", "producto")}


# ------------------------------------------------------------------------------------------------ oportunidades y pedido sugerido
def oportunidades(conn, hoy: date, cliente_ids: list[int] | None = None, maximo: int = 5) -> dict[int, list[dict]]:
    """Categorías que compra la mayoría de los clientes parecidos (misma zona y canal; si son menos de 5, mismo canal) y este no,
    en los últimos 90 días. Cada una trae el producto más elegido por esos clientes y una cantidad sugerida (la mediana por pedido)."""
    filas = db.filas(conn, f"""
        SELECT p.cliente_id, c.zona, c.canal, pr.categoria_id, cat.nombre categoria, l.producto_id, pr.nombre producto,
               count(DISTINCT p.id) pedidos, sum({FACTURABLE}) unidades, sum((l.precio - coalesce(l.costo_unitario, l.precio)) * {FACTURABLE}) ganancia,
               avg(l.precio) precio
        FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id JOIN clientes_b2b c ON c.id = p.cliente_id
        JOIN productos pr ON pr.id = l.producto_id LEFT JOIN categorias cat ON cat.id = pr.categoria_id
        WHERE {COMPRA} AND p.fecha > %s AND p.fecha <= %s AND pr.categoria_id IS NOT NULL
        GROUP BY 1, 2, 3, 4, 5, 6, 7""", (hoy - timedelta(days=90), hoy))
    perfil: dict[int, tuple] = {}
    categorias: dict[int, set] = defaultdict(set)
    por_cat: dict[int, list[dict]] = defaultdict(list)
    nombres = {}
    for f in filas:
        perfil[f["cliente_id"]] = (f["zona"], f["canal"])
        categorias[f["cliente_id"]].add(f["categoria_id"])
        por_cat[f["categoria_id"]].append(f)
        nombres[f["categoria_id"]] = f["categoria"]
    objetivo = cliente_ids if cliente_ids is not None else list(perfil)
    if cliente_ids is not None:       # los que no compraron nada en 90 días también reciben sugerencias (por su zona y canal)
        for c in db.filas(conn, "SELECT id, zona, canal FROM clientes_b2b WHERE id = ANY(%s)", (cliente_ids,)):
            perfil.setdefault(c["id"], (c["zona"], c["canal"]))
    salida: dict[int, list[dict]] = {}
    for cid in objetivo:
        if cid not in perfil:
            continue
        zona, canal = perfil[cid]
        parecidos = [o for o, p in perfil.items() if o != cid and p == (zona, canal) and categorias[o]]
        if len(parecidos) < 5:
            parecidos = [o for o, p in perfil.items() if o != cid and p[1] == canal and categorias[o]]
        if len(parecidos) < 3:
            salida[cid] = []
            continue
        grupo = set(parecidos)
        propuestas = []
        for cat in {c for o in parecidos for c in categorias[o]} - categorias[cid]:
            compradores = {f["cliente_id"] for f in por_cat[cat] if f["cliente_id"] in grupo}
            proporcion = len(compradores) / len(parecidos)
            if proporcion < 0.4:
                continue
            productos: dict[int, dict] = {}
            for f in por_cat[cat]:
                if f["cliente_id"] in grupo:
                    p = productos.setdefault(f["producto_id"], {"producto_id": f["producto_id"], "producto": f["producto"], "clientes": 0,
                                                                "por_pedido": [], "ganancia": 0.0, "precio": _f(f["precio"])})
                    p["clientes"] += 1
                    p["por_pedido"].append(_f(f["unidades"]) / max(1, f["pedidos"]))
                    p["ganancia"] += _f(f["ganancia"])
            mejor = max(productos.values(), key=lambda p: (p["clientes"], p["ganancia"]))
            cantidad = max(1, math.ceil(statistics.median(mejor["por_pedido"])))
            ganancia_mes = sum(_f(f["ganancia"]) for f in por_cat[cat] if f["cliente_id"] in grupo) / len(compradores) / 3
            propuestas.append({"categoria_id": cat, "categoria": nombres[cat], "compran_parecidos": round(proporcion, 2),
                               "producto_id": mejor["producto_id"], "producto": mejor["producto"], "cantidad_sugerida": cantidad,
                               "precio": round(mejor["precio"], 2), "ganancia_mes_estimada": round(ganancia_mes, 2),
                               "explicacion": f"Lo compran {len(compradores)} de {len(parecidos)} clientes parecidos ({proporcion:.0%}); este no lo compró en 90 días."})
        propuestas.sort(key=lambda p: -p["compran_parecidos"] * max(p["ganancia_mes_estimada"], 1))
        salida[cid] = propuestas[:maximo]
    return salida


# ------------------------------------------------------------------------------------------------ pedidos y entregas
def pedidos(conn, desde: date, hasta: date) -> dict:
    """Fill rate (unidades y líneas entregadas sobre lo pedido), plata no facturada por faltantes y rechazos por motivo."""
    r = db.fila(conn, """
        SELECT coalesce(sum(l.cantidad_pedida), 0) pedidas, coalesce(sum(l.cantidad_entregada), 0) entregadas, count(*) lineas,
               count(*) FILTER (WHERE l.cantidad_entregada >= l.cantidad_pedida) lineas_completas,
               coalesce(sum(l.faltante_stock * l.precio), 0) no_facturado_faltantes
        FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id
        WHERE p.estado IN ('entregado', 'entregado_parcial', 'rechazado') AND p.fecha BETWEEN %s AND %s""", (desde, hasta))
    estados = db.filas(conn, "SELECT estado, count(*) n, sum(total) total FROM pedidos_venta WHERE fecha BETWEEN %s AND %s GROUP BY 1 ORDER BY 2 DESC",
                       (desde, hasta))
    rechazos = db.filas(conn, """SELECT coalesce(e.motivo, 'Sin motivo') motivo, count(*) n, sum(p.total) total FROM entregas e
                                 JOIN pedidos_venta p ON p.id = e.pedido_id
                                 WHERE e.resultado = 'rechazado' AND e.fecha BETWEEN %s AND %s GROUP BY 1 ORDER BY 2 DESC""", (desde, hasta))
    faltantes = db.filas(conn, """SELECT l.producto_id, pr.nombre producto, sum(l.faltante_stock) unidades, sum(l.faltante_stock * l.precio) plata
                                  FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id JOIN productos pr ON pr.id = l.producto_id
                                  WHERE l.faltante_stock > 0 AND p.fecha BETWEEN %s AND %s GROUP BY 1, 2 ORDER BY 4 DESC LIMIT 15""", (desde, hasta))
    recientes = db.filas(conn, """SELECT p.id, p.numero, p.fecha, p.estado, p.total, p.total_entregado, coalesce(c.nombre_fantasia, c.razon_social) cliente,
                                         v.nombre vendedor FROM pedidos_venta p JOIN clientes_b2b c ON c.id = p.cliente_id
                                  LEFT JOIN vendedores v ON v.id = p.vendedor_id ORDER BY p.fecha DESC, p.id DESC LIMIT 40""")
    pedidas = _f(r["pedidas"])
    return {"desde": desde, "hasta": hasta,
            "fill_rate_unidades": round(_f(r["entregadas"]) / pedidas, 4) if pedidas else None,
            "fill_rate_lineas": round(r["lineas_completas"] / r["lineas"], 4) if r["lineas"] else None,
            "no_facturado_faltantes": round(_f(r["no_facturado_faltantes"]), 2), "estados": estados, "rechazos": rechazos,
            "faltantes": faltantes, "recientes": recientes, **logistica(conn, desde, hasta)}


# ------------------------------------------------------------------------------------------------ Fase 2 · logística (12B.5)
def logistica(conn, desde: date, hasta: date) -> dict:
    """Tiempo entre pedido y entrega (y si llegó para la fecha prometida), rechazos y devoluciones por motivo, cliente, producto y
    repartidor, y el resumen de cada repartidor."""
    entregas = db.filas(conn, """
        SELECT e.fecha - p.fecha dias, (p.fecha_entrega_prometida IS NULL OR e.fecha <= p.fecha_entrega_prometida) a_tiempo
        FROM entregas e JOIN pedidos_venta p ON p.id = e.pedido_id
        WHERE e.resultado <> 'rechazado' AND e.fecha BETWEEN %s AND %s""", (desde, hasta))
    tramos = {"mismo_dia": 0, "1_dia": 0, "2_dias": 0, "3_o_mas": 0}
    for e in entregas:
        tramos["mismo_dia" if e["dias"] <= 0 else "1_dia" if e["dias"] == 1 else "2_dias" if e["dias"] == 2 else "3_o_mas"] += 1
    tiempos = {"entregas": len(entregas), "dias_promedio": round(sum(e["dias"] for e in entregas) / len(entregas), 2) if entregas else None,
               "a_tiempo": round(sum(e["a_tiempo"] for e in entregas) / len(entregas), 4) if entregas else None, "distribucion": tramos}
    # Devoluciones en la entrega (líneas) y rechazos del pedido entero: «plata» es lo que no se facturó.
    devoluciones = f"""
        SELECT {{clave}}, sum(l.cantidad_devuelta) unidades, sum(l.cantidad_devuelta * l.precio) plata, count(DISTINCT p.id) pedidos
        FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id {{union}}
        WHERE l.cantidad_devuelta > 0 AND p.fecha BETWEEN %s AND %s GROUP BY 1 ORDER BY 3 DESC LIMIT 15"""
    rechazos = """
        SELECT {clave}, count(DISTINCT p.id) pedidos, sum(p.total) plata
        FROM entregas e JOIN pedidos_venta p ON p.id = e.pedido_id {union}
        WHERE e.resultado = 'rechazado' AND e.fecha BETWEEN %s AND %s GROUP BY 1 ORDER BY 3 DESC LIMIT 15"""
    dims = {
        "motivo": ("coalesce(l.motivo_devolucion, 'Sin motivo') nombre", "", "coalesce(e.motivo, 'Sin motivo') nombre", ""),
        "cliente": ("coalesce(c.nombre_fantasia, c.razon_social) nombre", "JOIN clientes_b2b c ON c.id = p.cliente_id",
                    "coalesce(c.nombre_fantasia, c.razon_social) nombre", "JOIN clientes_b2b c ON c.id = p.cliente_id"),
        "producto": ("pr.nombre", "JOIN productos pr ON pr.id = l.producto_id", None, None),
        "repartidor": ("coalesce(r.nombre, 'Sin repartidor') nombre",
                       "LEFT JOIN entregas e ON e.pedido_id = p.id LEFT JOIN repartidores r ON r.id = e.repartidor_id",
                       "coalesce(r.nombre, 'Sin repartidor') nombre", "LEFT JOIN repartidores r ON r.id = e.repartidor_id"),
    }
    por = {}
    for dim, (cd, ud, cr, ur) in dims.items():
        por[dim] = {"devoluciones": db.filas(conn, devoluciones.format(clave=cd, union=ud), (desde, hasta)),
                    "rechazos": db.filas(conn, rechazos.format(clave=cr, union=ur), (desde, hasta)) if cr else []}
    repartidores = db.filas(conn, """
        SELECT r.id, r.nombre, r.zona, count(e.id) entregas,
               count(e.id) FILTER (WHERE e.resultado = 'rechazado') rechazadas,
               avg(e.fecha - p.fecha) FILTER (WHERE e.resultado <> 'rechazado') dias_promedio,
               avg(CASE WHEN p.fecha_entrega_prometida IS NULL OR e.fecha <= p.fecha_entrega_prometida THEN 1 ELSE 0 END)
                   FILTER (WHERE e.resultado <> 'rechazado') a_tiempo,
               coalesce(sum((SELECT sum(l.cantidad_devuelta * l.precio) FROM pedidos_venta_lineas l WHERE l.pedido_id = p.id)), 0) devuelto
        FROM repartidores r LEFT JOIN entregas e ON e.repartidor_id = r.id AND e.fecha BETWEEN %s AND %s
        LEFT JOIN pedidos_venta p ON p.id = e.pedido_id
        WHERE r.activo GROUP BY 1, 2, 3 ORDER BY 2""", (desde, hasta))
    for x in repartidores:
        x["rechazo"] = round(x["rechazadas"] / x["entregas"], 4) if x["entregas"] else None
        x["dias_promedio"] = round(float(x["dias_promedio"]), 2) if x["dias_promedio"] is not None else None
        x["a_tiempo"] = round(float(x["a_tiempo"]), 4) if x["a_tiempo"] is not None else None
    total_devuelto = _f(db.fila(conn, """SELECT sum(l.cantidad_devuelta * l.precio) t FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id
                                         WHERE p.fecha BETWEEN %s AND %s""", (desde, hasta))["t"])
    return {"tiempos": tiempos, "por": por, "repartidores": repartidores, "devuelto": round(total_devuelto, 2)}


# ------------------------------------------------------------------------------------------------ vista del vendedor
def mi_cartera(conn, vendedor_id: int | None, hoy: date) -> dict:
    """Lo que gana el vendedor mirando esto: clientes a recuperar, la ruta de hoy con qué ofrecer, su meta y la deuda de su cartera.
    La RLS ya acota todo a su cartera cuando quien mira es un vendedor."""
    estados = estado_clientes(conn, hoy)
    if vendedor_id:
        estados = [e for e in estados if e["vendedor_id"] == vendedor_id]
    por_id = {e["cliente_id"]: e for e in estados}
    cc = cuenta_corriente(conn, hoy)
    deuda = {c["cliente_id"]: c for c in cc["clientes"] if not vendedor_id or c["vendedor_id"] == vendedor_id}
    ruta = db.filas(conn, """SELECT rc.cliente_id, rc.orden FROM rutas r JOIN rutas_clientes rc ON rc.ruta_id = r.id
                             WHERE r.vendedor_id = %s AND r.dia_semana = %s ORDER BY rc.orden""", (vendedor_id, hoy.weekday())) if vendedor_id else []
    recuperar = sorted((e for e in estados if e["estado"] in ("en_riesgo", "perdido")), key=lambda e: -e["deja_de_facturar_mes"])[:15]
    ids = list({r["cliente_id"] for r in ruta} | {e["cliente_id"] for e in recuperar[:8]})
    ops = oportunidades(conn, hoy, ids, maximo=3) if ids else {}
    visitas = {v["cliente_id"]: v for v in db.filas(conn, "SELECT cliente_id, realizada, resultado FROM visitas WHERE fecha = %s AND vendedor_id = %s",
                                                    (hoy, vendedor_id))} if vendedor_id else {}
    paradas = []
    for r in ruta:
        e, d = por_id.get(r["cliente_id"]), deuda.get(r["cliente_id"])
        if not e:
            continue
        paradas.append({**{k: e[k] for k in ("cliente_id", "cliente", "localidad", "estado", "dias_sin_comprar", "venta_mensual", "explicacion")},
                        "orden": r["orden"], "vencido": d["vencido"] if d else 0.0, "alertas_deuda": d["alertas"] if d else [],
                        "oportunidades": ops.get(r["cliente_id"], []), "visita": visitas.get(r["cliente_id"])})
    meta = None
    if vendedor_id:
        rend = rendimiento_vendedores(conn, hoy.replace(day=1), hoy, hoy)
        meta = next((v for v in rend["vendedores"] if v["vendedor_id"] == vendedor_id), None)
    return {"hoy": hoy, "ruta": paradas, "recuperar": [{**e, "oportunidades": ops.get(e["cliente_id"], [])} for e in recuperar],
            "resumen": resumen_clientes(estados), "meta": meta,
            "deuda": {"vencido": round(sum(d["vencido"] for d in deuda.values()), 2), "saldo": round(sum(d["saldo"] for d in deuda.values()), 2),
                      "clientes": sorted(deuda.values(), key=lambda d: -d["vencido"])[:10]}}


def periodo(texto: str | None, hoy: date) -> tuple[date, date]:
    dias = {"semana": 7, "mes": 30, "90d": 90, "anio": 365}.get(texto or "mes", 30)
    if texto == "mes_actual":
        return hoy.replace(day=1), hoy
    return hoy - timedelta(days=dias - 1), hoy



# ------------------------------------------------------------------------------------------------ Fase 2 · rutas y cobertura (12B.3)
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]


def cumplimiento_visitas(conn, desde: date, hasta: date) -> dict:
    """Visitas planificadas contra realizadas, por vendedor y por día de la semana; efectividad = visitas con pedido / realizadas."""
    filas = db.filas(conn, """
        SELECT v.vendedor_id, ve.nombre vendedor, extract(isodow FROM v.fecha)::int - 1 dia,
               count(*) FILTER (WHERE v.planificada) planificadas, count(*) FILTER (WHERE v.planificada AND v.realizada) realizadas,
               count(*) FILTER (WHERE v.realizada) realizadas_total, count(*) FILTER (WHERE v.realizada AND v.resultado = 'pedido') con_pedido,
               count(*) FILTER (WHERE NOT v.planificada AND v.realizada) fuera_de_ruta
        FROM visitas v JOIN vendedores ve ON ve.id = v.vendedor_id
        WHERE v.fecha BETWEEN %s AND %s GROUP BY 1, 2, 3 ORDER BY 2, 3""", (desde, hasta))
    motivos = db.filas(conn, """SELECT coalesce(resultado, 'no_visitado') resultado, count(*) n FROM visitas
                                WHERE fecha BETWEEN %s AND %s AND (NOT realizada OR resultado <> 'pedido') GROUP BY 1 ORDER BY 2 DESC""", (desde, hasta))
    por_vendedor: dict[int, dict] = {}
    for f in filas:
        v = por_vendedor.setdefault(f["vendedor_id"], {"vendedor_id": f["vendedor_id"], "vendedor": f["vendedor"], "planificadas": 0, "realizadas": 0,
                                                       "realizadas_total": 0, "con_pedido": 0, "fuera_de_ruta": 0, "dias": {}})
        for k in ("planificadas", "realizadas", "realizadas_total", "con_pedido", "fuera_de_ruta"):
            v[k] += f[k]
        v["dias"][DIAS[f["dia"]] if f["dia"] < 6 else "Domingo"] = {
            "planificadas": f["planificadas"], "realizadas": f["realizadas"],
            "cumplimiento": round(f["realizadas"] / f["planificadas"], 4) if f["planificadas"] else None}
    salida = []
    for v in por_vendedor.values():
        v["cumplimiento"] = round(v["realizadas"] / v["planificadas"], 4) if v["planificadas"] else None
        v["efectividad"] = round(v["con_pedido"] / v["realizadas_total"], 4) if v["realizadas_total"] else None
        salida.append(v)
    salida.sort(key=lambda v: (v["cumplimiento"] is None, v["cumplimiento"] or 0))
    total = {k: sum(v[k] for v in salida) for k in ("planificadas", "realizadas", "realizadas_total", "con_pedido")}
    total["cumplimiento"] = round(total["realizadas"] / total["planificadas"], 4) if total["planificadas"] else None
    total["efectividad"] = round(total["con_pedido"] / total["realizadas_total"], 4) if total["realizadas_total"] else None
    return {"desde": desde, "hasta": hasta, "vendedores": salida, "total": total, "motivos": motivos, "dias": DIAS}


def sin_visita(conn, hoy: date, dias: int | None = None) -> dict:
    """Clientes activos o en riesgo que no recibieron una visita realizada en los últimos X días (o nunca)."""
    if dias is None:
        dias = db.fila(conn, "SELECT dias_sin_visita d FROM organizaciones WHERE id = app_org()")["d"]
    estados = {e["cliente_id"]: e for e in estado_clientes(conn, hoy)}
    ultimas = {f["cliente_id"]: f["ultima"] for f in db.filas(conn, "SELECT cliente_id, max(fecha) ultima FROM visitas WHERE realizada AND fecha <= %s GROUP BY 1",
                                                                    (hoy,))}
    filas = []
    for cid, e in estados.items():
        ultima = ultimas.get(cid)
        if e["estado"] == "sin_compras" or (ultima and (hoy - ultima).days <= dias):
            continue
        filas.append({**{k: e[k] for k in ("cliente_id", "cliente", "localidad", "zona", "vendedor_id", "vendedor", "estado", "venta_mensual")},
                      "ultima_visita": ultima, "dias_sin_visita": (hoy - ultima).days if ultima else None})
    filas.sort(key=lambda f: (-(f["dias_sin_visita"] or 10**4), -f["venta_mensual"]))
    return {"dias": dias, "filas": filas, "plata_mensual": round(sum(f["venta_mensual"] for f in filas), 2)}


def cobertura(conn, hoy: date) -> dict:
    """Por zona: clientes que compraron en 90 días sobre el universo conocido (clientes + comercios relevados que no son clientes)."""
    clientes = db.filas(conn, f"""
        SELECT coalesce(c.zona, 'Sin zona') zona, count(*) total,
               count(*) FILTER (WHERE EXISTS (SELECT 1 FROM pedidos_venta p WHERE p.cliente_id = c.id AND {COMPRA} AND p.fecha > %s)) activos
        FROM clientes_b2b c WHERE c.activo GROUP BY 1""", (hoy - timedelta(days=90),))
    prospectos = {f["zona"]: f for f in db.filas(conn, """SELECT coalesce(zona, 'Sin zona') zona, count(*) n,
                                                                 count(*) FILTER (WHERE canal IS NOT NULL) con_canal
                                                          FROM prospectos WHERE cliente_id IS NULL GROUP BY 1""")}
    zonas = {}
    for c in clientes:
        zonas[c["zona"]] = {"zona": c["zona"], "clientes": c["total"], "activos": c["activos"], "prospectos": 0}
    for z, p in prospectos.items():
        zonas.setdefault(z, {"zona": z, "clientes": 0, "activos": 0, "prospectos": 0})["prospectos"] = p["n"]
    salida = []
    for z in zonas.values():
        universo = z["clientes"] + z["prospectos"]
        z["cobertura"] = round(z["activos"] / universo, 4) if universo else None
        salida.append(z)
    salida.sort(key=lambda z: (z["cobertura"] is None, z["cobertura"] or 0))
    return {"zonas": salida, "hay_prospectos": bool(prospectos)}


def rutas_de(conn, vendedor_id: int) -> list[dict]:
    """Los 6 días de ruta de un vendedor con sus clientes en orden (y los clientes de su cartera que no están en ninguna ruta)."""
    dias = []
    en_ruta = set()
    for d in range(6):
        clientes = db.filas(conn, """SELECT c.id cliente_id, coalesce(c.nombre_fantasia, c.razon_social) cliente, c.localidad, rc.orden
                                     FROM rutas r JOIN rutas_clientes rc ON rc.ruta_id = r.id JOIN clientes_b2b c ON c.id = rc.cliente_id
                                     WHERE r.vendedor_id = %s AND r.dia_semana = %s ORDER BY rc.orden, c.razon_social""", (vendedor_id, d))
        en_ruta |= {c["cliente_id"] for c in clientes}
        dias.append({"dia": d, "nombre": DIAS[d], "clientes": clientes})
    libres = [c for c in db.filas(conn, """SELECT id cliente_id, coalesce(nombre_fantasia, razon_social) cliente, localidad FROM clientes_b2b
                                          WHERE vendedor_id = %s AND activo ORDER BY razon_social""", (vendedor_id,)) if c["cliente_id"] not in en_ruta]
    return dias + [{"dia": None, "nombre": "Sin ruta", "clientes": libres}]


def guardar_ruta(conn, org_id: int, vendedor_id: int, dia: int, clientes: list[int], usuario_id: int | None) -> int:
    """Reemplaza los clientes (en ese orden) del día de ruta del vendedor. Solo clientes de su cartera."""
    validos = {f["id"] for f in db.filas(conn, "SELECT id FROM clientes_b2b WHERE vendedor_id = %s AND id = ANY(%s)", (vendedor_id, clientes))}
    if set(clientes) - validos:
        raise ValueError("Hay clientes que no son de la cartera de ese vendedor.")
    r = db.fila(conn, """INSERT INTO rutas (org_id, vendedor_id, dia_semana, nombre, created_by) VALUES (%s,%s,%s,%s,%s)
                         ON CONFLICT (vendedor_id, dia_semana) DO UPDATE SET nombre = EXCLUDED.nombre RETURNING id""",
                (org_id, vendedor_id, dia, DIAS[dia], usuario_id))
    with conn.cursor() as cur:
        cur.execute("DELETE FROM rutas_clientes WHERE ruta_id = %s", (r["id"],))
        for orden, cid in enumerate(dict.fromkeys(clientes), 1):
            cur.execute("INSERT INTO rutas_clientes (org_id, ruta_id, cliente_id, orden) VALUES (%s,%s,%s,%s)", (org_id, r["id"], cid, orden))
    return len(clientes)


# ------------------------------------------------------------------------------------------------ Fase 2 · marcas representadas (12B.6)
def marcas(conn, desde: date, hasta: date, hoy: date) -> dict:
    """Por marca: venta y ganancia (contra el período anterior), cobertura (clientes que la compran sobre los clientes que compraron algo),
    mix (productos vendidos sobre los de la marca), participación y la venta de los últimos 12 meses."""
    dias = (hasta - desde).days + 1

    def periodo(d, h):
        return {f["marca"]: f for f in db.filas(conn, f"""
            SELECT coalesce(pr.marca, 'Sin marca') marca, sum(l.precio * {FACTURABLE}) venta,
                   sum((l.precio - coalesce(l.costo_unitario, l.precio)) * {FACTURABLE}) ganancia, sum({FACTURABLE}) unidades,
                   count(DISTINCT p.cliente_id) FILTER (WHERE {FACTURABLE} > 0) clientes, count(DISTINCT l.producto_id) FILTER (WHERE {FACTURABLE} > 0) productos
            FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id JOIN productos pr ON pr.id = l.producto_id
            WHERE {COMPRA} AND p.fecha BETWEEN %s AND %s GROUP BY 1""", (d, h))}
    actual, anterior = periodo(desde, hasta), periodo(desde - timedelta(days=dias), desde - timedelta(days=1))
    compradores = db.fila(conn, f"SELECT count(DISTINCT p.cliente_id) n FROM pedidos_venta p WHERE {COMPRA} AND p.fecha BETWEEN %s AND %s",
                          (desde, hasta))["n"] or 0
    catalogo = {f["marca"]: f["n"] for f in db.filas(conn, "SELECT coalesce(marca, 'Sin marca') marca, count(*) n FROM productos WHERE activo GROUP BY 1")}
    mensual = defaultdict(list)
    for f in db.filas(conn, f"""SELECT coalesce(pr.marca, 'Sin marca') marca, date_trunc('month', p.fecha)::date mes, sum(l.precio * {FACTURABLE}) venta
                                FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id JOIN productos pr ON pr.id = l.producto_id
                                WHERE {COMPRA} AND p.fecha > %s GROUP BY 1, 2 ORDER BY 2""", (hoy.replace(day=1) - timedelta(days=335),)):
        mensual[f["marca"]].append({"mes": f["mes"], "venta": round(_f(f["venta"]), 2)})
    total = sum(_f(f["venta"]) for f in actual.values())
    objetivos = {}
    for o in objetivos_marcas(conn, hoy):
        objetivos.setdefault(o["marca"].lower(), []).append(o)
    filas = []
    for marca, f in actual.items():
        venta, ant = _f(f["venta"]), _f(anterior.get(marca, {}).get("venta"))
        filas.append({"marca": marca, "venta": round(venta, 2), "ganancia": round(_f(f["ganancia"]), 2),
                      "margen": round(_f(f["ganancia"]) / venta, 4) if venta else None, "unidades": _f(f["unidades"]),
                      "participacion": round(venta / total, 4) if total else None, "variacion": round(venta / ant - 1, 4) if ant else None,
                      "clientes": f["clientes"], "cobertura": round(f["clientes"] / compradores, 4) if compradores else None,
                      "productos_vendidos": f["productos"], "productos_marca": catalogo.get(marca, f["productos"]),
                      "mix": round(f["productos"] / catalogo[marca], 4) if catalogo.get(marca) else None,
                      "mensual": mensual.get(marca, []), "objetivos": objetivos.get(marca.lower(), [])})
    filas.sort(key=lambda x: -x["venta"])
    return {"desde": desde, "hasta": hasta, "marcas": filas, "clientes_compradores": compradores, "objetivos": objetivos_marcas(conn, hoy),
            "todos_los_objetivos": db.filas(conn, "SELECT * FROM objetivos_marca ORDER BY hasta DESC, marca")}
