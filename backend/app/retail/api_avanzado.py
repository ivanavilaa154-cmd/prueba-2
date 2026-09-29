"""Análisis de la Fase 3: canasta (10.5), efectividad de promociones (10.9), sensibilidad al precio (10.10), surtido óptimo (10.12)
y clientes (10.14).

Fórmulas (también en «¿Cómo se calcula esto?»):
- Canasta: soporte, confianza y lift de cada par de productos (calculos.asociacion). Producto arrastre: aparece en muchos tickets
  y esos tickets son más grandes que el promedio (índice = % de tickets × ticket con el producto ÷ ticket promedio).
- Promociones: línea base = unidades por día de las 4 semanas previas × días de la promoción. Incremento = real − base.
  Canibalización = lo que dejaron de vender los otros productos de la subcategoría. Rebote = caída de las 2 semanas posteriores.
  Neto = ganancia extra − ganancia perdida por canibalización − ganancia perdida por rebote.
- Sensibilidad: regresión semanal (semanas sin promoción) de ln(unidades ajustadas por la estacionalidad de su categoría) sobre
  ln(precio real, sin inflación), combinada con la estimación de toda la categoría según la precisión de cada una.
- Clientes (RFM): recencia, frecuencia y gasto de 180 días en quintiles; segmentos por reglas simples.
"""
from __future__ import annotations

import math
import time as _time
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median, pstdev, quantiles

from fastapi import APIRouter, Depends, HTTPException

from . import calculos as C, suscripcion
from . import catalogo, db, permisos, sesiones
from .api_comprar import _hoy_datos
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"], dependencies=[Depends(suscripcion.modulo("completo"))])   # plan (13.6)
MINIMO_TICKETS_CANASTA = 500
_cache_sensibilidad: dict = {}


# ------------------------------------------------------------------------------ 10.5 canasta
@api.get("/ventas/canasta")
def canasta(dias: int = 90, ubicacion_id: int | None = None, minimo: int = 15, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        desde = hoy - timedelta(days=max(14, min(dias, 365)))
        params = {"d": desde, "h": hoy, "u": ubicacion_id, "min": max(3, minimo)}
        base = """SELECT DISTINCT l.ticket_id, l.producto_id FROM tickets_lineas l JOIN tickets t ON t.id = l.ticket_id
                  WHERE l.fecha > %(d)s AND l.fecha <= %(h)s AND t.estado <> 'anulado' AND l.cantidad > 0
                    AND (%(u)s::bigint IS NULL OR l.ubicacion_id = %(u)s)"""
        por_ticket: dict = defaultdict(set)
        with conn.cursor() as cur:
            cur.execute(base, params)
            for f in cur:
                por_ticket[f["ticket_id"]].add(f["producto_id"])
        total = len(por_ticket)
        if total < MINIMO_TICKETS_CANASTA:
            return respuesta({"suficiente": False, "tickets": total, "minimo": MINIMO_TICKETS_CANASTA, "reglas": [], "arrastre": [], "sugerencias": []})
        cuenta: dict = defaultdict(int)
        for prods_t in por_ticket.values():
            for pid in prods_t:
                cuenta[pid] += 1
        frecuentes = {pid for pid, n in cuenta.items() if n >= params["min"]}
        conteo_pares: dict = defaultdict(int)
        for prods_t in por_ticket.values():
            fs = sorted(prods_t & frecuentes)
            for i in range(len(fs)):
                for j in range(i + 1, len(fs)):
                    conteo_pares[(fs[i], fs[j])] += 1
        pares = [{"a": a_, "b": b_, "n": n} for (a_, b_), n in conteo_pares.items() if n >= params["min"]]
        nombres = {p["id"]: p["nombre"] for p in db.filas(conn, "SELECT id, nombre FROM productos")}
        reglas = []
        for p in pares:
            for x, y in ((p["a"], p["b"]), (p["b"], p["a"])):
                r = C.asociacion(p["n"], cuenta[x], cuenta[y], total)
                if r["lift"] >= 1.5 and r["confianza"] >= 0.1:
                    reglas.append({"si_compra_id": x, "si_compra": nombres.get(x), "tambien_id": y, "tambien": nombres.get(y), "tickets_juntos": p["n"],
                                   **{k: round(v, 4) for k, v in r.items()},
                                   "texto": f"El {r['confianza']:.0%} de los que compran {nombres.get(x)} también llevan {nombres.get(y)} "
                                            f"({r['lift']:.1f} veces más que el resto)"})
        # De cada par, la dirección con más confianza (la otra dice lo mismo al revés).
        mejor_dir = {}
        for r in reglas:
            k = frozenset((r["si_compra_id"], r["tambien_id"]))
            if k not in mejor_dir or r["confianza"] > mejor_dir[k]["confianza"]:
                mejor_dir[k] = r
        reglas = sorted(mejor_dir.values(), key=lambda r: (-r["lift"] * r["soporte"], -r["lift"]))
        tickets_prom = db.fila(conn, """SELECT avg(t.total) p FROM tickets t JOIN organizaciones o ON o.id = t.org_id
                                        WHERE t.estado = 'confirmado' AND (t.fecha_hora AT TIME ZONE o.zona_horaria)::date > %(d)s
                                          AND (t.fecha_hora AT TIME ZONE o.zona_horaria)::date <= %(h)s AND (%(u)s::bigint IS NULL OR t.ubicacion_id = %(u)s)""", params)["p"]
        totales = {f["id"]: f["total"] for f in db.filas(conn, "SELECT id, total FROM tickets WHERE id = ANY(%s)", (list(por_ticket),))}
        suma = defaultdict(Decimal)
        for tid, prods_t in por_ticket.items():
            for pid in prods_t:
                suma[pid] += totales.get(tid, Decimal(0))
        arrastre = [{"producto_id": pid, "tickets": n, "ticket_promedio": (suma[pid] / n).quantize(Decimal("0.01"))}
                    for pid, n in sorted(cuenta.items(), key=lambda x: -x[1])[:60]]
        for a in arrastre:
            a["nombre"] = nombres.get(a["producto_id"])
            a["presencia"] = a["tickets"] / total
            a["ticket_vs_promedio"] = float(a["ticket_promedio"] / tickets_prom) if tickets_prom else None
            a["indice"] = a["presencia"] * (a["ticket_vs_promedio"] or 0)
        arrastre = sorted([a for a in arrastre if (a["ticket_vs_promedio"] or 0) > 1.1], key=lambda a: -a["indice"])[:10]
        sugerencias = []
        usados = set()
        for r in reglas:
            clave = frozenset((r["si_compra_id"], r["tambien_id"]))
            if clave in usados:
                continue
            usados.add(clave)
            sugerencias.append({"tipo": "combo", "texto": f"Combo {r['si_compra']} + {r['tambien']} con 10 % en el segundo", "regla": r})
            sugerencias.append({"tipo": "gondola", "texto": f"Poné {r['tambien']} cerca de {r['si_compra']}", "regla": r})
            if len(usados) >= 5:
                break
        return respuesta({"suficiente": True, "tickets": total, "desde": desde, "hasta": hoy, "reglas": reglas[:40], "arrastre": arrastre,
                          "sugerencias": sugerencias, "ticket_promedio": tickets_prom})


# ------------------------------------------------------------------------------ 10.9 promociones
def _unidades(conn, productos: list[int], ubic: list[int], d: date, h: date) -> dict:
    return {f["producto_id"]: f for f in db.filas(conn, """
        SELECT producto_id, sum(unidades) u, sum(ganancia) g, sum(facturacion) f FROM agg_producto_ubicacion_dia
        WHERE producto_id = ANY(%s) AND fecha BETWEEN %s AND %s AND (cardinality(%s::bigint[]) = 0 OR ubicacion_id = ANY(%s)) GROUP BY 1""",
        (productos, d, h, ubic, ubic))}


def efecto_promocion(conn, promo: dict) -> dict:
    d, h = promo["desde"], promo["hasta"]
    dias = (h - d).days + 1
    prods = list(promo["productos"])
    ubic = list(promo["ubicaciones"] or [])
    antes = _unidades(conn, prods, ubic, d - timedelta(days=28), d - timedelta(days=1))
    durante = _unidades(conn, prods, ubic, d, h)
    despues = _unidades(conn, prods, ubic, h + timedelta(days=1), h + timedelta(days=14))
    detalle, inc_u, inc_g, rebote_g = [], Decimal(0), Decimal(0), Decimal(0)
    for pid in prods:
        a, x, y = antes.get(pid), durante.get(pid), despues.get(pid)
        base_dia = (a["u"] / 28) if a else Decimal(0)
        margen_u = (a["g"] / a["u"]) if a and a["u"] else Decimal(0)
        base_u = base_dia * dias
        real_u = x["u"] if x else Decimal(0)
        real_g = x["g"] if x else Decimal(0)
        base_g = base_u * margen_u
        post_u = y["u"] if y else Decimal(0)
        rebote_u = max(Decimal(0), base_dia * 14 - post_u)
        inc_u += real_u - base_u
        inc_g += real_g - base_g
        rebote_g += rebote_u * margen_u
        detalle.append({"producto_id": pid, "base_unidades": base_u.quantize(Decimal("0.01")), "unidades": real_u,
                        "incremento": (real_u - base_u).quantize(Decimal("0.01")), "rebote_unidades": rebote_u.quantize(Decimal("0.01"))})
    # Canibalización: otros productos de las mismas subcategorías, fuera de la promoción.
    subcats = [f["categoria_id"] for f in db.filas(conn, "SELECT DISTINCT categoria_id FROM productos WHERE id = ANY(%s)", (prods,))]
    otros = [f["id"] for f in db.filas(conn, "SELECT id FROM productos WHERE categoria_id = ANY(%s) AND NOT id = ANY(%s)", (subcats, prods))]
    canib_g = Decimal(0)
    if otros:
        oa = _unidades(conn, otros, ubic, d - timedelta(days=28), d - timedelta(days=1))
        od = _unidades(conn, otros, ubic, d, h)
        for pid in otros:
            a = oa.get(pid)
            if not a or not a["u"]:
                continue
            caida = a["u"] / 28 * dias - (od[pid]["u"] if pid in od else Decimal(0))
            if caida > 0:
                canib_g += caida * a["g"] / a["u"]
    neto = inc_g - canib_g - rebote_g
    if neto > 0:
        rec = "Repetir: dejó plata neta después de canibalización y rebote"
    elif inc_u > 0:
        rec = "Repetir con menos descuento: vendió más pero no dejó plata"
    else:
        rec = "No repetir: no aumentó las ventas"
    return {"incremento_unidades": inc_u.quantize(Decimal("0.01")), "incremento_ganancia": inc_g.quantize(Decimal("0.01")),
            "canibalizacion": canib_g.quantize(Decimal("0.01")), "rebote": rebote_g.quantize(Decimal("0.01")), "neto": neto.quantize(Decimal("0.01")),
            "recomendacion": rec, "productos": detalle}


@api.get("/promociones/efectividad")
def efectividad(meses: int = 12, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        promos = db.filas(conn, """SELECT id, nombre, tipo, parametros, productos, ubicaciones, desde, hasta, origen FROM promociones
                                   WHERE hasta < %s AND desde >= %s AND estado <> 'cancelada' ORDER BY desde DESC""",
                          (hoy, hoy - timedelta(days=31 * max(1, min(meses, 24)))))
        salida = [p | efecto_promocion(conn, p) for p in promos]
        return respuesta({"promociones": salida, "neto_total": sum((p["neto"] for p in salida), Decimal(0))})


# ------------------------------------------------------------------------------ 10.10 sensibilidad al precio
def sensibilidades(conn, hoy: date) -> dict:
    clave = (db.fila(conn, "SELECT app_org() o")["o"], hoy)
    if clave in _cache_sensibilidad and _time.time() - _cache_sensibilidad[clave][0] < 3600:
        return _cache_sensibilidad[clave][1]
    semanas = db.filas(conn, """
        SELECT a.producto_id, date_trunc('week', a.fecha)::date semana, sum(a.unidades) u, sum(a.facturacion) f, sum(a.unidades_promo) up,
               p.categoria_id, c.padre_id, p.nombre
        FROM agg_producto_ubicacion_dia a JOIN productos p ON p.id = a.producto_id JOIN categorias c ON c.id = p.categoria_id
        WHERE a.fecha > %s AND a.fecha <= %s AND a.unidades > 0 GROUP BY 1, 2, 6, 7, 8""", (hoy - timedelta(days=364), hoy - timedelta(days=hoy.weekday() + 1)))
    ipc = {f["periodo"]: float(f["indice"]) for f in db.filas(conn, "SELECT periodo, indice FROM indice_precios")}
    ultimo_ipc = ipc[max(ipc)] if ipc else 1.0
    cat_sem = defaultdict(float)
    cat_n = defaultdict(set)
    for s in semanas:
        cat_sem[(s["padre_id"] or s["categoria_id"], s["semana"])] += float(s["u"])
        cat_n[s["padre_id"] or s["categoria_id"]].add(s["semana"])
    cat_prom = {c: sum(cat_sem[(c, w)] for w in ws) / len(ws) for c, ws in cat_n.items()}
    por_prod = defaultdict(list)
    info = {}
    for s in semanas:
        cat = s["padre_id"] or s["categoria_id"]
        indice_estacion = cat_sem[(cat, s["semana"])] / cat_prom[cat] if cat_prom.get(cat) else 1.0
        mes = s["semana"].replace(day=1)
        deflactor = (ipc.get(mes) or ultimo_ipc) / ultimo_ipc
        precio_real = float(s["f"] / s["u"]) / deflactor if deflactor else None
        # Solo semanas sin promoción: la promo suma exhibición y mezclaría ese efecto con el del precio.
        if precio_real and indice_estacion > 0 and s["u"] and s["up"] / s["u"] <= Decimal("0.05"):
            por_prod[s["producto_id"]].append((precio_real, float(s["u"]) / indice_estacion))
        info[s["producto_id"]] = (s["nombre"], s["categoria_id"])
    # Estimación de cada categoría con todos sus productos (precios y unidades relativos al promedio de cada producto).
    categoria_de = {s["producto_id"]: s["padre_id"] or s["categoria_id"] for s in semanas}
    por_cat = defaultdict(list)
    for pid, puntos in por_prod.items():
        if len(puntos) < 4:
            continue
        mp = sum(p for p, _ in puntos) / len(puntos)
        mu = sum(u for _, u in puntos) / len(puntos)
        por_cat[categoria_de[pid]] += [(p / mp, u / mu) for p, u in puntos]
    cat_res = {c: C.elasticidad(pts, minimo=30) for c, pts in por_cat.items()}
    resultado = {}
    for pid, puntos in por_prod.items():
        propia = C.elasticidad(puntos)
        grupo = cat_res.get(categoria_de[pid], {})
        if propia["elasticidad"] is not None and grupo.get("elasticidad") is not None:
            e = C.combinar_estimaciones(propia["elasticidad"], propia["error"], grupo["elasticidad"], grupo["error"])
            fuente = "producto y categoría"
        elif propia["elasticidad"] is not None:
            e, fuente = propia["elasticidad"], "producto"
        elif grupo.get("elasticidad") is not None:
            e, fuente = grupo["elasticidad"], "categoría"
        else:
            resultado[pid] = {"elasticidad": None, "error": None, "r2": None, "n": propia["n"], "clase": "sin_datos", "fuente": "—", "nombre": info[pid][0]}
            continue
        e = round(max(-5.0, min(0.0, e)), 3)
        resultado[pid] = {"elasticidad": e, "error": propia.get("error"), "r2": propia.get("r2"), "n": propia["n"],
                          "clase": "poco_sensible" if e > -1.0 else "sensible", "fuente": fuente, "nombre": info[pid][0]}
    _cache_sensibilidad[clave] = (_time.time(), resultado)
    return resultado


@api.get("/precios/sensibilidad")
def sensibilidad(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        r = sensibilidades(conn, hoy)
        filas = [{"producto_id": pid, **v, "recomendacion": {"poco_sensible": "Hay margen para subir el precio: las ventas casi no cambian",
                                                            "sensible": "No subas el precio: pierde ventas. Buen candidato para ofertas",
                                                            "sin_datos": "Sin cambios de precio suficientes para medir"}[v["clase"]]}
                 for pid, v in r.items()]
        cuenta = defaultdict(int)
        for f in filas:
            cuenta[f["clase"]] += 1
        return respuesta({"productos": sorted(filas, key=lambda f: (f["clase"] == "sin_datos", f["elasticidad"] or 0)), "resumen": cuenta})


# ------------------------------------------------------------------------------ 10.12 surtido
@api.get("/surtido")
def surtido(ubicacion_id: int | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        prods = db.filas(conn, """
            SELECT p.id, p.nombre, p.marca, p.clase_abc, p.categoria_id, c.nombre subcategoria, coalesce(cp.nombre, c.nombre) categoria,
                   coalesce(sum(a.facturacion), 0) facturacion, coalesce(sum(a.ganancia), 0) ganancia, coalesce(sum(a.unidades), 0) unidades
            FROM productos p JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
            LEFT JOIN agg_producto_ubicacion_dia a ON a.producto_id = p.id AND a.fecha > %s AND a.fecha <= %s AND (%s::bigint IS NULL OR a.ubicacion_id = %s)
            WHERE p.activo GROUP BY 1, 2, 3, 4, 5, 6, 7""", (hoy - timedelta(days=90), hoy, ubicacion_id, ubicacion_id))
        por_sub = defaultdict(list)
        for p in prods:
            por_sub[(p["categoria"], p["subcategoria"])].append(p)
        subcategorias, discontinuar = [], []
        for (cat, sub), ps in por_sub.items():
            total = sum((p["facturacion"] for p in ps), Decimal(0))
            ganancias = sorted(float(p["ganancia"]) for p in ps)
            p25 = ganancias[len(ganancias) // 4] if ganancias else 0
            presentaciones = {c for p in ps for c in catalogo.fichas(p["nombre"])[1]}
            buenos = [p for p in ps if p["clase_abc"] in ("A", "B")]
            duplicados = []
            for i, a in enumerate(ps):
                for b in ps[i + 1:]:
                    if catalogo.similitud(a["nombre"], b["nombre"]) >= 0.6:
                        mayor, menor = (a, b) if a["facturacion"] >= b["facturacion"] else (b, a)
                        if mayor["facturacion"] and menor["facturacion"] < mayor["facturacion"] * Decimal("0.2"):
                            duplicados.append({"se_queda": mayor["nombre"], "bajo_rendimiento": menor["nombre"], "producto_id": menor["id"],
                                               "participacion": float(menor["facturacion"] / total) if total else 0})
            for p in ps:
                if p["clase_abc"] == "C" and float(p["ganancia"]) <= p25 and any(b["id"] != p["id"] for b in buenos):
                    sustituto = max(buenos, key=lambda b: b["facturacion"])
                    discontinuar.append({"producto_id": p["id"], "nombre": p["nombre"], "categoria": cat, "subcategoria": sub, "ganancia_90d": p["ganancia"],
                                         "participacion": float(p["facturacion"] / total) if total else 0, "sustituto": sustituto["nombre"]})
            subcategorias.append({"categoria": cat, "subcategoria": sub, "productos": len(ps), "marcas": len({p["marca"] for p in ps if p["marca"]}),
                                  "presentaciones": len(presentaciones), "facturacion": total, "duplicados": duplicados,
                                  "participacion": sorted(({"nombre": p["nombre"], "participacion": float(p["facturacion"] / total) if total else 0}
                                                           for p in ps), key=lambda x: -x["participacion"])})
        faltan = []
        if ubicacion_id:
            faltan = db.filas(conn, """
                WITH otras AS (SELECT producto_id, sum(facturacion) f, count(DISTINCT ubicacion_id) sucursales FROM agg_producto_ubicacion_dia
                               WHERE ubicacion_id <> %(u)s AND fecha > %(h)s - 90 AND fecha <= %(h)s GROUP BY 1),
                     corte AS (SELECT percentile_cont(0.7) WITHIN GROUP (ORDER BY f) c FROM otras)
                SELECT o.producto_id, p.nombre, o.f facturacion_otras, o.sucursales FROM otras o JOIN productos p ON p.id = o.producto_id, corte
                WHERE o.f >= corte.c
                  AND NOT EXISTS (SELECT 1 FROM agg_producto_ubicacion_dia a WHERE a.producto_id = o.producto_id AND a.ubicacion_id = %(u)s
                                  AND a.fecha > %(h)s - 90 AND a.unidades > 0)
                  AND NOT EXISTS (SELECT 1 FROM stock_actual s WHERE s.producto_id = o.producto_id AND s.ubicacion_id = %(u)s AND s.cantidad > 0)
                ORDER BY o.f DESC LIMIT 20""", {"u": ubicacion_id, "h": hoy})
        return respuesta({"subcategorias": sorted(subcategorias, key=lambda s: -s["facturacion"]),
                          "discontinuar": sorted(discontinuar, key=lambda d: d["ganancia_90d"])[:40], "faltan_en_sucursal": faltan})


# ------------------------------------------------------------------------------ 10.14 clientes
SEGMENTOS = {"campeones": "Campeones", "leales": "Leales", "nuevos": "Nuevos", "ocasionales": "Ocasionales", "en_riesgo": "En riesgo", "perdidos": "Perdidos"}


@api.get("/clientes")
def clientes(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        filas = db.filas(conn, """
            SELECT t.cliente, max((t.fecha_hora AT TIME ZONE o.zona_horaria)::date) ultima, count(*) tickets, sum(t.total) gasto
            FROM tickets t JOIN organizaciones o ON o.id = t.org_id
            WHERE t.cliente IS NOT NULL AND t.estado = 'confirmado' AND t.fecha_hora > %s GROUP BY 1""", (hoy - timedelta(days=180),))
        if len(filas) < 30:
            return respuesta({"activo": False, "clientes_identificados": len(filas),
                              "como_activar": "Para ver clientes, la caja tiene que registrar quién compra (DNI, tarjeta de puntos o cuenta corriente) "
                                              "y el cliente tiene que dar su consentimiento. Con 30 clientes identificados en 6 meses se activa el análisis."})
        anteriores = {f["cliente"]: f for f in db.filas(conn, """
            SELECT t.cliente, count(*) tickets, sum(t.total) gasto, min(t.fecha_hora)::date primera, max(t.fecha_hora)::date ultima FROM tickets t
            WHERE t.cliente IS NOT NULL AND t.estado = 'confirmado' AND t.fecha_hora > %s AND t.fecha_hora <= %s GROUP BY 1""",
            (hoy - timedelta(days=240), hoy - timedelta(days=60)))}
        rec = [(hoy - f["ultima"]).days for f in filas]
        cr = quantiles([-r for r in rec], n=5)
        cf = quantiles([f["tickets"] for f in filas], n=5)
        cm = quantiles([float(f["gasto"]) for f in filas], n=5)
        segs = defaultdict(lambda: {"clientes": 0, "gasto": Decimal(0)})
        lista = []
        for f, r in zip(filas, rec):
            R, F, M = C.quintil(-r, cr), C.quintil(f["tickets"], cf), C.quintil(float(f["gasto"]), cm)
            s = C.segmento_rfm(R, F, M)
            segs[s]["clientes"] += 1
            segs[s]["gasto"] += f["gasto"]
            lista.append({"cliente": f["cliente"], "ultima_compra": f["ultima"], "dias_sin_comprar": r, "compras_180d": f["tickets"], "gasto_180d": f["gasto"],
                          "rfm": f"{R}{F}{M}", "segmento": s})
        dejaron = []
        for f, r in zip(filas, rec):
            a = anteriores.get(f["cliente"])
            # Dejó de venir: era habitual y ya pasó el triple de su intervalo normal entre compras (y al menos 45 días).
            intervalo = (a["ultima"] - a["primera"]).days / (a["tickets"] - 1) if a and a["tickets"] > 1 else None
            if a and a["tickets"] >= 6 and intervalo is not None and r >= max(45, 3 * intervalo):
                dejaron.append({"cliente": f["cliente"], "dias_sin_comprar": r, "compras_antes": a["tickets"], "gasto_antes": a["gasto"]})
        valor, proximas = valor_y_proxima_compra(conn, hoy)
        for x in lista:
            x.update(valor.get(x["cliente"], {}))
        return respuesta({"activo": True, "clientes": len(filas), "segmentos": [{"segmento": k, "nombre": SEGMENTOS[k], **segs[k]} for k in SEGMENTOS],
                          "mayor_valor": sorted(lista, key=lambda x: -x["gasto_180d"])[:20],
                          "valor_de_vida": sorted((x for x in lista if x.get("valor_12m") is not None), key=lambda x: -x["valor_12m"])[:20],
                          "proximas_compras": proximas, "retencion_mensual": valor.get("_retencion"),
                          "valor_12m_total": round(sum(x.get("valor_12m") or 0 for x in lista), 2),
                          "dejaron_de_venir": sorted(dejaron, key=lambda x: -x["gasto_antes"])[:30], "lista": lista})


def valor_y_proxima_compra(conn, hoy: date) -> tuple[dict, list[dict]]:
    """(19) Valor de vida a 12 meses y (20) próxima compra de cada cliente identificado.

    Próxima compra: última compra + la mediana de sus intervalos, con rango del 10 al 90 % de esos intervalos (al menos 3 compras).
    Probabilidad de que siga activo: 1 si todavía no pasó su intervalo habitual; después cae a la mitad por cada intervalo de atraso.
    Valor a 12 meses: ganancia mensual promedio del último año × probabilidad de seguir activo × suma de la retención mensual de la
    empresa (medida: de los que compraban hace 2 a 8 meses, cuántos volvieron en los últimos 60 días) a lo largo de 12 meses."""
    compras = defaultdict(list)
    for f in db.filas(conn, """SELECT t.cliente, (t.fecha_hora AT TIME ZONE o.zona_horaria)::date dia, sum(t.total)::float total
                               FROM tickets t JOIN organizaciones o ON o.id = t.org_id
                               WHERE t.cliente IS NOT NULL AND t.estado = 'confirmado' AND t.fecha_hora > %s GROUP BY 1, 2""",
                      (hoy - timedelta(days=365),)):
        compras[f["cliente"]].append((f["dia"], f["total"]))
    margen = db.fila(conn, "SELECT coalesce(sum(ganancia) / nullif(sum(facturacion), 0), 0.25)::float m FROM agg_producto_ubicacion_dia WHERE fecha >= %s",
                     (hoy - timedelta(days=365),))["m"]
    antes = {c for c, xs in compras.items() if any(hoy - timedelta(days=240) <= d < hoy - timedelta(days=60) for d, _ in xs)}
    volvieron = sum(1 for c in antes if any(d >= hoy - timedelta(days=60) for d, _ in compras[c]))
    retencion_60 = volvieron / len(antes) if antes else 0.8
    r_mes = min(0.99, max(0.3, retencion_60 ** 0.5))
    factor_12 = sum(r_mes ** m for m in range(1, 13))
    valor, proximas = {"_retencion": round(r_mes, 3)}, []
    for c, xs in compras.items():
        xs.sort()
        dias = [d for d, _ in xs]
        primera = dias[0]
        meses = max(1.0, (hoy - primera).days / 30.4)
        gasto_mes = sum(t for _, t in xs) / meses
        sin = (hoy - dias[-1]).days
        intervalos = [(b - a).days for a, b in zip(dias, dias[1:]) if (b - a).days > 0]
        if len(intervalos) >= 2:
            tipico = median(intervalos)
            q = quantiles(intervalos, n=10) if len(intervalos) >= 3 else [min(intervalos)] * 9
            desde, hasta = dias[-1] + timedelta(days=round(q[0])), dias[-1] + timedelta(days=round(q[-1] if len(intervalos) >= 3 else max(intervalos)))
            activo = 1.0 if sin <= tipico else 0.5 ** ((sin - tipico) / max(tipico, 7))
            esperada = max(hoy, dias[-1] + timedelta(days=round(tipico)))
            if activo >= 0.25 and esperada <= hoy + timedelta(days=14):
                proximas.append({"cliente": c, "ultima_compra": dias[-1], "cada_dias": round(tipico), "proxima": esperada,
                                 "entre": max(hoy, desde), "y": max(hoy, hasta), "ticket_promedio": round(sum(t for _, t in xs) / len(xs), 2),
                                 "atrasada": sin > tipico})
        else:
            activo = 1.0 if sin <= 60 else 0.5 ** ((sin - 60) / 60)
        valor[c] = {"valor_12m": round(gasto_mes * margen * activo * factor_12, 2), "prob_activo": round(activo, 3),
                    "compras_por_mes": round(len(xs) / meses, 2)}
    proximas.sort(key=lambda x: (not x["atrasada"], x["proxima"], -x["ticket_promedio"]))   # primero las atrasadas: a quién recordarle
    return valor, proximas[:40]


# ------------------------------------------------------------------------------ (26) éxito de un lanzamiento
@api.get("/lanzamientos")
def lanzamientos(ctx: db.Contexto = Depends(sesiones.contexto)):
    """Productos lanzados en los últimos 120 días: cuánto van a vender a los 90 días (con rango) y la probabilidad de que vendan como un
    producto normal de su categoría (al menos el 40 % de los productos de la categoría venden menos que eso)."""
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        inicio = db.fila(conn, "SELECT min(fecha) f FROM agg_producto_ubicacion_dia")["f"]
        if not inicio:
            return respuesta({"lanzamientos": [], "hoy": hoy})
        nuevos = db.filas(conn, """SELECT a.producto_id, min(a.fecha) primera FROM agg_producto_ubicacion_dia a GROUP BY 1
                                   HAVING min(a.fecha) >= %s AND min(a.fecha) > %s AND min(a.fecha) <= %s""",
                          (hoy - timedelta(days=120), inicio + timedelta(days=30), hoy - timedelta(days=7)))
        if not nuevos:
            return respuesta({"lanzamientos": [], "hoy": hoy})
        ids = [n["producto_id"] for n in nuevos]
        info = {f["id"]: f for f in db.filas(conn, """SELECT p.id, p.nombre, p.codigo_interno codigo, coalesce(cp.id, c.id) cat_id, coalesce(cp.nombre, c.nombre, 'Sin categoría') categoria
                                                     FROM productos p LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
                                                     WHERE p.id = ANY(%s)""", (ids,))}
        diario = defaultdict(dict)
        for f in db.filas(conn, """SELECT producto_id, fecha, sum(unidades)::float u, sum(facturacion)::float v FROM agg_producto_ubicacion_dia
                                   WHERE producto_id = ANY(%s) GROUP BY 1, 2""", (ids,)):
            diario[f["producto_id"]][f["fecha"]] = (f["u"], f["v"])
        # Venta diaria de los productos establecidos de cada categoría (últimos 28 días).
        cat_vpd = defaultdict(list)
        for f in db.filas(conn, """SELECT coalesce(cp.id, c.id) cat_id, a.producto_id, sum(a.unidades)::float / 28 vpd
                                   FROM agg_producto_ubicacion_dia a JOIN productos p ON p.id = a.producto_id
                                   LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
                                   WHERE a.fecha >= %s AND a.fecha < %s AND NOT (a.producto_id = ANY(%s)) GROUP BY 1, 2""",
                          (hoy - timedelta(days=28), hoy, ids)):
            cat_vpd[f["cat_id"]].append(f["vpd"])
        salida = []
        for n in nuevos:
            p, primera = info.get(n["producto_id"]), n["primera"]
            if not p:
                continue
            dias = (hoy - primera).days
            serie = [diario[p["id"]].get(primera + timedelta(days=i), (0.0, 0.0)) for i in range(dias)]
            ultimos = [u for u, _ in serie[-14:]]
            vpd = sum(ultimos) / len(ultimos)
            previos = [u for u, _ in serie[-28:-14]]
            tendencia = (vpd / (sum(previos) / len(previos))) if previos and sum(previos) else 1.0
            proyectada = vpd * max(0.7, min(1.3, 1 + 0.5 * (tendencia - 1)))       # venta diaria esperada al día 90
            desvio = math.sqrt((pstdev(ultimos) / math.sqrt(len(ultimos))) ** 2 + (0.2 * proyectada) ** 2)
            referencia = cat_vpd.get(p["cat_id"], [])
            objetivo = quantiles(referencia, n=10)[3] if len(referencia) >= 5 else None
            prob = None if objetivo is None else (0.5 * math.erfc((objetivo - proyectada) / (desvio * math.sqrt(2))) if desvio else float(proyectada >= objetivo))
            vendidas = sum(u for u, _ in serie)
            restan = max(0, 90 - dias)
            total_90 = vendidas + proyectada * restan
            margen_90 = C.Z_BANDA * desvio * restan
            veredicto = ("sin_referencia" if prob is None else "va_bien" if prob >= 0.6 else "en_duda" if prob >= 0.3 else "no_despega")
            salida.append({
                "producto_id": p["id"], "producto": p["nombre"], "codigo": p["codigo"], "categoria": p["categoria"], "lanzado": primera, "dias": dias,
                "vendidas": round(vendidas, 1), "facturado": round(sum(v for _, v in serie), 2), "venta_diaria": round(vpd, 2),
                "tendencia": round(tendencia, 2), "venta_diaria_90": round(proyectada, 2), "objetivo_categoria": round(objetivo, 2) if objetivo else None,
                "unidades_90": round(total_90), "unidades_90_min": round(max(vendidas, total_90 - margen_90)), "unidades_90_max": round(total_90 + margen_90),
                "prob_exito": round(prob, 3) if prob is not None else None, "veredicto": veredicto,
                "accion": {"va_bien": "Asegurar stock y sumarlo a las sucursales donde no está",
                           "en_duda": "Darle exhibición o una promo de prueba y volver a mirar en 2 semanas",
                           "no_despega": "No reponer; pedir al proveedor cambio o devolución",
                           "sin_referencia": "Seguir mirando: su categoría tiene pocos productos para comparar"}[veredicto]})
        salida.sort(key=lambda x: x["lanzado"], reverse=True)
        return respuesta({"hoy": hoy, "lanzamientos": salida})
