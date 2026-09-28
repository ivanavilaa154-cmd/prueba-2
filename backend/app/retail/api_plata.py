"""Dónde está parada la plata (sección 9): capital inmovilizado, lo que dejó de venderse, próximos a vencer, qué ofertar y merma.

Fórmulas (también en «¿Cómo se calcula esto?» de cada pantalla):
- Capital en stock = stock × costo del proveedor principal.
- Cobertura del capital = capital ÷ costo de lo vendido por día (últimos 30 días).
- Stock sano: hasta 30 días de stock · sobrestock: más de 30 · stock muerto: sin ventas en 90 días o más (configurables).
- Unidades que no llegan a venderse (por lote, el que vence antes se vende primero) = cantidad − pronóstico acumulado hasta
  el vencimiento. Plata en riesgo = unidades que no llegan × costo.
- Descuento mínimo: el menor de la escala (10 % → ventas ×1,3 … 50 % → ×3,5, configurable) con el que la demanda hasta el
  vencimiento cubre también lo que sobra.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import calculos as C
from . import db, pdf, permisos, sesiones
from .api_comprar import _hoy_datos, lista_ids
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])
DEFECTOS = {"umbral_sobrestock_dias": 30, "umbral_muerto_dias": 90}
TRAMOS_VENCIMIENTO = ((7, "menos de 7 días"), (15, "7 a 15 días"), (30, "15 a 30 días"))


def parametro(conn, clave: str):
    f = db.fila(conn, "SELECT valor FROM parametros WHERE clave=%s", (clave,))
    return f["valor"] if f else DEFECTOS.get(clave)


def _metricas(conn, ubicaciones: str | None, categoria: int | None, con_explicacion: bool = False) -> list[dict]:
    params: dict = {}
    filtros = ["u.tipo <> 'deposito' OR m.disponible > 0"]
    ubic = lista_ids(ubicaciones)
    if ubic:
        filtros.append("m.ubicacion_id = ANY(%(ubic)s)")
        params["ubic"] = ubic
    if categoria:
        filtros.append("(c.id = %(cat)s OR c.padre_id = %(cat)s)")
        params["cat"] = categoria
    extra = "m.explicacion," if con_explicacion else "(m.explicacion->>'dias_sin_stock')::int AS dias_sin_stock_28,"
    return db.filas(conn, f"""
        SELECT m.producto_id, m.ubicacion_id, p.nombre, p.codigo_interno, p.perecedero, u.nombre AS ubicacion, u.tipo AS tipo_ubicacion,
               coalesce(cp.nombre, c.nombre) AS categoria, coalesce(cp.id, c.id) AS categoria_id, c.id AS subcategoria_id, c.nombre AS subcategoria,
               pr.id AS proveedor_id, pr.razon_social AS proveedor, m.disponible, m.dias_stock, m.dias_sin_venta, m.capital, m.tendencia,
               m.pronostico_diario, m.riesgo_vencimiento, m.cantidad_sugerida, {extra}
               (m.explicacion->>'costo')::numeric AS costo, (m.explicacion->>'precio')::numeric AS precio
        FROM metricas_producto_actual m JOIN productos p ON p.id = m.producto_id JOIN ubicaciones u ON u.id = m.ubicacion_id
        LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
        LEFT JOIN proveedores pr ON pr.id = m.proveedor_id
        WHERE ({') AND ('.join(filtros)})""", params)


def red_de_venta(conn) -> dict:
    """Por producto, lo que venden todas las sucursales juntas: el depósito no vende, abastece; su stock se mide contra eso."""
    return {f["producto_id"]: f for f in db.filas(conn, """
        SELECT m.producto_id, sum(m.pronostico_diario) pronostico, min(m.dias_sin_venta) dias_sin_venta
        FROM metricas_producto_actual m JOIN ubicaciones u ON u.id = m.ubicacion_id WHERE u.tipo <> 'deposito' GROUP BY 1""")}


def estado_stock(m: dict, sobre: int, muerto: int, red: dict | None = None) -> str | None:
    if (m["disponible"] or 0) <= 0:
        return None
    if m["tipo_ubicacion"] == "deposito" and red is not None:
        r = red.get(m["producto_id"])
        m["dias_sin_venta"] = r["dias_sin_venta"] if r else None
        m["dias_stock"] = (m["disponible"] / r["pronostico"]).quantize(Decimal("0.01")) if r and r["pronostico"] else None
    if m["dias_sin_venta"] is None or m["dias_sin_venta"] >= muerto:
        return "muerto"
    if m["dias_stock"] is not None and m["dias_stock"] > sobre:
        return "sobrestock"
    return "sano"


def _variaciones(conn, hoy: date, productos: list[int], ubic: list[int]) -> dict:
    """Por producto (sucursales elegidas): 30 días vs 30 anteriores, mes actual vs mismo tramo del año anterior,
    últimas 4 semanas vs promedio de 4 semanas de los 3 meses previos."""
    if not productos:
        return {}
    ini_mes = hoy.replace(day=1)
    try:
        ini_mes_aa, hoy_aa = ini_mes.replace(year=hoy.year - 1), hoy.replace(year=hoy.year - 1)
    except ValueError:       # 29 de febrero
        ini_mes_aa, hoy_aa = ini_mes.replace(year=hoy.year - 1), hoy.replace(year=hoy.year - 1, day=28)
    filas = db.filas(conn, """
        SELECT producto_id,
               sum(unidades) FILTER (WHERE fecha > %(h)s - 30 AND fecha <= %(h)s) u30,
               sum(unidades) FILTER (WHERE fecha > %(h)s - 60 AND fecha <= %(h)s - 30) u30p,
               sum(unidades) FILTER (WHERE fecha >= %(im)s AND fecha <= %(h)s) umes,
               sum(unidades) FILTER (WHERE fecha >= %(ima)s AND fecha <= %(ha)s) umes_aa,
               sum(unidades) FILTER (WHERE fecha > %(h)s - 28 AND fecha <= %(h)s) u4s,
               sum(unidades) FILTER (WHERE fecha > %(h)s - 118 AND fecha <= %(h)s - 28) u3m
        FROM agg_producto_ubicacion_dia WHERE producto_id = ANY(%(p)s) AND (%(todas)s OR ubicacion_id = ANY(%(u)s)) AND fecha > %(h)s - 400
        GROUP BY producto_id""", {"h": hoy, "im": ini_mes, "ima": ini_mes_aa, "ha": hoy_aa, "p": productos, "u": ubic or [0], "todas": not ubic})

    def var(a, b):
        return None if not b else float((Decimal(a or 0) - b) / b)
    return {f["producto_id"]: {"ultimos_30_vs_anteriores": var(f["u30"], f["u30p"]), "mes_vs_anio_anterior": var(f["umes"], f["umes_aa"]),
                               "4_semanas_vs_3_meses": var(f["u4s"], (f["u3m"] or 0) / Decimal("3.214") if f["u3m"] else None),
                               "unidades_30d": float(f["u30"] or 0)} for f in filas}


def _causas(conn, hoy: date, m: dict, var: dict, sustitutos: dict, precio_antes: dict) -> list[str]:
    causas = []
    antes = precio_antes.get(m["producto_id"])
    if antes and m["precio"] and m["precio"] > antes * Decimal("1.08"):
        causas.append(f"Subió de precio {float((m['precio'] - antes) / antes):.0%} en los últimos 45 días")
    s = sustitutos.get((m["subcategoria_id"], m["producto_id"]))
    if s:
        causas.append(f"Un sustituto de la misma subcategoría creció: {s}")
    if (m.get("dias_sin_stock_28") or 0) >= 7:
        causas.append(f"Estuvo {m['dias_sin_stock_28']} de los últimos 28 días sin stock")
    if var.get("mes_vs_anio_anterior") is not None and var["mes_vs_anio_anterior"] < -0.3 and (var.get("ultimos_30_vs_anteriores") or 0) < -0.3:
        causas.append("Puede ser fin de temporada: también cayó frente al mismo mes del año pasado")
    return causas


def recomendacion(estado: str | None, tendencia: str | None) -> str:
    if estado == "muerto":
        return "Sacar del surtido: liquidar al costo o pedir cambio al proveedor"
    if estado == "sobrestock" and tendencia == "cayendo":
        return "Dejar de comprar y ofertar la segunda unidad con descuento"
    if estado == "sobrestock":
        return "Dejar de comprar hasta volver a 30 días de stock"
    if tendencia == "cayendo":
        return "Comprar menos: la venta viene bajando"
    return "Sin acción"


@api.get("/plata-parada")
def plata_parada(ubicaciones: str | None = None, categoria: int | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        sobre, muerto = int(parametro(conn, "umbral_sobrestock_dias")), int(parametro(conn, "umbral_muerto_dias"))
        ms = _metricas(conn, ubicaciones, categoria)
        red = red_de_venta(conn)
        ubic = lista_ids(ubicaciones)
        costo_diario = db.fila(conn, "SELECT coalesce(sum(costo), 0) / 30 c FROM agg_producto_ubicacion_dia WHERE fecha > %s AND fecha <= %s "
                                     "AND (%s OR ubicacion_id = ANY(%s))", (hoy - timedelta(days=30), hoy, not ubic, ubic or [0]))["c"]
        dist = defaultdict(lambda: {"capital": Decimal(0), "productos": 0})
        por = {k: defaultdict(lambda: defaultdict(Decimal)) for k in ("categoria", "proveedor", "ubicacion")}
        sin_ventas = {t: {"productos": 0, "capital": Decimal(0)} for t in (15, 30, 60, 90)}
        total = Decimal(0)
        for m in ms:
            cap = m["capital"] or Decimal(0)
            est = estado_stock(m, sobre, muerto, red)
            m["estado"] = est
            if not est:
                continue
            total += cap
            dist[est]["capital"] += cap
            dist[est]["productos"] += 1
            for k, nombre in (("categoria", m["categoria"]), ("proveedor", m["proveedor"]), ("ubicacion", m["ubicacion"])):
                por[k][nombre or "Sin dato"][est] += cap
                por[k][nombre or "Sin dato"]["total"] += cap
            for t in sin_ventas:
                if m["dias_sin_venta"] is None or m["dias_sin_venta"] >= t:
                    sin_ventas[t]["productos"] += 1
                    sin_ventas[t]["capital"] += cap
        # Lista: lo que tiene plata parada (sobrestock o muerto) o viene cayendo, ordenado por capital.
        lista = sorted([m for m in ms if m["estado"] in ("sobrestock", "muerto") or (m["estado"] and m["tendencia"] == "cayendo")],
                       key=lambda m: -(m["capital"] or 0))[:300]
        variaciones = _variaciones(conn, hoy, list({m["producto_id"] for m in lista}), ubic)
        precio_antes = {f["producto_id"]: f["precio"] for f in db.filas(conn, """
            SELECT DISTINCT ON (producto_id) producto_id, precio FROM precios
            WHERE ubicacion_id IS NULL AND canal_id IS NULL AND desde <= %s AND (hasta IS NULL OR hasta >= %s) ORDER BY producto_id, desde DESC""",
            (hoy - timedelta(days=45), hoy - timedelta(days=45)))}
        # Sustitutos: el producto de la misma subcategoría que más creció (30 días vs 30 anteriores), si creció 20 % o más.
        crecimiento = db.filas(conn, """
            SELECT p.categoria_id, p.id, p.nombre, sum(a.unidades) FILTER (WHERE a.fecha > %(h)s - 30) u30,
                   sum(a.unidades) FILTER (WHERE a.fecha <= %(h)s - 30) u30p
            FROM agg_producto_ubicacion_dia a JOIN productos p ON p.id = a.producto_id
            WHERE a.fecha > %(h)s - 60 AND a.fecha <= %(h)s GROUP BY 1, 2, 3""", {"h": hoy})
        mejor = {}
        for f in crecimiento:
            if f["u30p"] and f["u30"] and f["u30"] >= f["u30p"] * Decimal("1.2") and f["u30"] >= 10:
                if f["categoria_id"] not in mejor or f["u30"] - f["u30p"] > mejor[f["categoria_id"]][1]:
                    mejor[f["categoria_id"]] = (f, f["u30"] - f["u30p"])
        sustitutos = {}
        for m in lista:
            b = mejor.get(m["subcategoria_id"])
            if b and b[0]["id"] != m["producto_id"] and m["tendencia"] in ("cayendo", "muerto"):
                sustitutos[(m["subcategoria_id"], m["producto_id"])] = f"{b[0]['nombre']} (+{float((b[0]['u30'] - b[0]['u30p']) / b[0]['u30p']):.0%})"
        items = []
        for m in lista:
            v = variaciones.get(m["producto_id"], {})
            items.append({k: m[k] for k in ("producto_id", "ubicacion_id", "nombre", "codigo_interno", "ubicacion", "categoria", "proveedor",
                                            "disponible", "dias_stock", "dias_sin_venta", "capital", "tendencia", "estado", "costo", "precio")}
                         | {"variaciones": v, "causas": _causas(conn, hoy, m, v, sustitutos, precio_antes),
                            "recomendacion": recomendacion(m["estado"], m["tendencia"])})
        venc = _vencimientos(conn, ubicaciones, categoria, hoy)
        fin_mes = hoy.replace(day=calendar.monthrange(hoy.year, hoy.month)[1])
        riesgo_mes = sum((l["plata_en_riesgo"] for l in venc if l["vencimiento"] <= fin_mes), Decimal(0))
        ofertas = [l for l in venc if l["oferta"] and (l["oferta"]["descuento"] or 0) > 0]

        def tabla(k):
            return sorted(({"nombre": n, **{e: v.get(e, Decimal(0)) for e in ("sano", "sobrestock", "muerto", "total")}} for n, v in por[k].items()),
                          key=lambda x: -x["total"])
        return respuesta({
            "hoy": hoy, "umbrales": {"sobrestock": sobre, "muerto": muerto},
            "tarjetas": {"plata_parada": dist["sobrestock"]["capital"] + dist["muerto"]["capital"], "capital_total": total,
                         "cobertura_dias": float(total / costo_diario) if costo_diario else None, "riesgo_vencimiento_mes": riesgo_mes,
                         "dejaron_de_venderse": sin_ventas[30]["productos"], "ofertas_sugeridas": len(ofertas),
                         "plata_recuperable": sum((l["oferta"]["recuperable"] for l in ofertas), Decimal(0))},
            "distribucion": {e: dist[e] for e in ("sano", "sobrestock", "muerto")},
            "sin_ventas": [{"dias": t, **v} for t, v in sin_ventas.items()],
            "por_categoria": tabla("categoria"), "por_proveedor": tabla("proveedor"), "por_ubicacion": tabla("ubicacion"),
            "items": items,
        })


# ------------------------------------------------------------------------------ vencimientos y ofertas
def _redondear(precio: Decimal) -> Decimal:
    return (precio / 10).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * 10 if precio >= 100 else precio.quantize(Decimal("0.01"))


def _vencimientos(conn, ubicaciones: str | None, categoria: int | None, hoy: date, horizonte: int = 45) -> list[dict]:
    salida = []
    activas = {(pid, u) for f in db.filas(conn, "SELECT productos, ubicaciones FROM promociones WHERE estado='activa' AND hasta >= %s", (hoy,))
               for pid in f["productos"] for u in (f["ubicaciones"] or [None])}
    for m in _metricas(conn, ubicaciones, categoria, con_explicacion=True):
        lotes = (m["explicacion"] or {}).get("lotes") or []
        pron = (m["explicacion"] or {}).get("pronostico_120d") or []
        for l in lotes:
            if not l.get("vencimiento"):
                continue
            venc = date.fromisoformat(str(l["vencimiento"])[:10])
            dias = (venc - hoy).days
            if dias > horizonte or dias < 0:
                continue
            costo = m["costo"] or Decimal(0)
            precio = m["precio"]
            no_llegan = Decimal(str(l["no_llegan"]))
            demanda = sum(pron[:max(0, dias)])
            item = {"producto_id": m["producto_id"], "ubicacion_id": m["ubicacion_id"], "nombre": m["nombre"], "codigo_interno": m["codigo_interno"],
                    "ubicacion": m["ubicacion"], "categoria": m["categoria"], "lote": l["lote"], "vencimiento": venc, "dias": dias,
                    "tramo": next((t for d, t in TRAMOS_VENCIMIENTO if dias < d), "más de 30 días"), "cantidad": Decimal(str(l["cantidad"])),
                    "no_llegan": no_llegan, "plata_en_riesgo": (no_llegan * costo).quantize(Decimal("0.01")), "costo": costo, "precio": precio,
                    "en_oferta": (m["producto_id"], m["ubicacion_id"]) in activas or (m["producto_id"], None) in activas, "oferta": None}
            if no_llegan > 0 and precio:
                d = C.descuento_minimo(float(no_llegan), demanda, dias)
                vendidas = Decimal(str(l["cantidad"])) - no_llegan
                sin_oferta = (vendidas * precio).quantize(Decimal("0.01"))
                if d:
                    precio_oferta = _redondear(precio * Decimal(str(1 - d[0])))
                    con_oferta = (Decimal(str(l["cantidad"])) * precio_oferta).quantize(Decimal("0.01"))
                    item["oferta"] = {"descuento": d[0], "precio_oferta": precio_oferta, "sin_oferta": sin_oferta, "con_oferta": con_oferta,
                                      "recuperable": max(Decimal(0), con_oferta - sin_oferta),
                                      "texto": f"{d[0]:.0%} de descuento hasta el {venc.strftime('%d/%m')}: vendés las {float(l['cantidad']):g} "
                                               f"unidades y recuperás {con_oferta - sin_oferta:,.0f} $ más que sin oferta"}
                else:
                    texto = (f"Vence {'mañana' if dias <= 1 else f'en {dias} días'}: ofertalo al cierre del día y lo que quede, registralo como merma"
                             if dias <= 2 else "Ni con 50 % de descuento se vende a tiempo: transferilo a una sucursal que venda más o pedí cambio al proveedor")
                    item["oferta"] = {"descuento": None, "recuperable": Decimal(0), "sin_oferta": sin_oferta, "texto": texto}
            salida.append(item)
    return sorted(salida, key=lambda x: (x["dias"], -x["plata_en_riesgo"]))


@api.get("/vencimientos")
def vencimientos(ubicaciones: str | None = None, categoria: int | None = None, dias: int = 45, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        lotes = _vencimientos(conn, ubicaciones, categoria, hoy, min(max(dias, 7), 120))
        tramos = defaultdict(lambda: {"lotes": 0, "plata_en_riesgo": Decimal(0)})
        for l in lotes:
            tramos[l["tramo"]]["lotes"] += 1
            tramos[l["tramo"]]["plata_en_riesgo"] += l["plata_en_riesgo"]
        return respuesta({"hoy": hoy, "lotes": lotes, "tramos": [{"tramo": t, **tramos[t]} for _, t in TRAMOS_VENCIMIENTO + ((0, "más de 30 días"),)],
                          "plata_en_riesgo": sum((l["plata_en_riesgo"] for l in lotes), Decimal(0)),
                          "recuperable": sum((l["oferta"]["recuperable"] for l in lotes if l["oferta"]), Decimal(0)),
                          "puede_ofertar": permisos.puede(ctx, "remarcar")})


class NuevaOferta(BaseModel):
    producto_id: int
    ubicacion_id: int | None = None
    descuento: float = Field(gt=0, lt=0.9)
    hasta: date
    origen: str = "vencimiento"                       # vencimiento, sobrestock, liquidacion
    tipo: str = "descuento_pct"                       # descuento_pct, segunda_unidad
    unidades_objetivo: float | None = None


@api.post("/ofertas")
def crear_oferta(datos: NuevaOferta, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "remarcar")
    if datos.origen not in ("vencimiento", "sobrestock", "liquidacion") or datos.tipo not in ("descuento_pct", "segunda_unidad"):
        raise HTTPException(status_code=400, detail="Tipo de oferta no válido.")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        if datos.hasta < hoy:
            raise HTTPException(status_code=400, detail="La fecha de fin ya pasó.")
        p = db.fila(conn, """SELECT p.nombre, (SELECT precio FROM precios x WHERE x.producto_id = p.id AND x.ubicacion_id IS NULL AND x.canal_id IS NULL
                                                 AND x.desde <= %s AND (x.hasta IS NULL OR x.hasta >= %s) ORDER BY desde DESC LIMIT 1) precio,
                                    (SELECT costo FROM producto_proveedores pp WHERE pp.producto_id = p.id ORDER BY principal DESC LIMIT 1) costo
                             FROM productos p WHERE p.id=%s""", (hoy, hoy, datos.producto_id))
        if not p or not p["precio"]:
            raise HTTPException(status_code=404, detail="El producto no existe o no tiene precio.")
        d = Decimal(str(datos.descuento))
        precio_oferta = _redondear(p["precio"] * (1 - d)) if datos.tipo == "descuento_pct" else _redondear(p["precio"] * (1 - d / 2))
        nombre = (f"{p['nombre']}: {datos.descuento:.0%} off" if datos.tipo == "descuento_pct" else f"{p['nombre']}: 2.ª unidad al {datos.descuento:.0%} off")
        o = db.fila(conn, "INSERT INTO promociones (org_id, nombre, tipo, parametros, productos, ubicaciones, desde, hasta, origen, estado, created_by) "
                          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'activa',%s) RETURNING id",
                    (ctx.org_id, nombre, datos.tipo, db_json({"descuento": datos.descuento, "precio_normal": p["precio"], "precio_oferta": precio_oferta,
                                                              "costo": p["costo"], "unidades_objetivo": datos.unidades_objetivo}),
                     [datos.producto_id], [datos.ubicacion_id] if datos.ubicacion_id else [], hoy, datos.hasta, datos.origen, ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "crear", "promocion", o["id"], {"nombre": nombre, "hasta": str(datos.hasta)}, sesiones.ip_de(request))
        return respuesta({"id": o["id"], "nombre": nombre, "precio_oferta": precio_oferta})


def db_json(valor) -> str:
    import json
    return json.dumps(valor, default=str)


@api.get("/ofertas")
def ofertas(ctx: db.Contexto = Depends(sesiones.contexto)):
    """Seguimiento: unidades vendidas desde que empezó la oferta y plata recuperada (lo cobrado por las unidades que iban a
    vencer o sobraban, hasta el objetivo)."""
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        filas = db.filas(conn, "SELECT id, nombre, tipo, parametros, productos, ubicaciones, desde, hasta, origen, estado FROM promociones "
                               "WHERE origen <> 'manual' ORDER BY desde DESC, id DESC LIMIT 100")
        for o in filas:
            v = db.fila(conn, "SELECT coalesce(sum(unidades), 0) u, coalesce(sum(facturacion), 0) f FROM agg_producto_ubicacion_dia "
                              "WHERE producto_id = ANY(%s) AND fecha >= %s AND fecha <= %s AND (cardinality(%s::bigint[]) = 0 OR ubicacion_id = ANY(%s))",
                        (o["productos"], o["desde"], min(o["hasta"], hoy), o["ubicaciones"], o["ubicaciones"]))
            objetivo = o["parametros"].get("unidades_objetivo")
            unidades = v["u"] if not objetivo else min(v["u"], Decimal(str(objetivo)))
            o["vendidas"] = v["u"]
            o["plata_recuperada"] = (unidades * Decimal(str(o["parametros"].get("precio_oferta") or 0))).quantize(Decimal("0.01"))
            o["vigente"] = o["estado"] == "activa" and o["hasta"] >= hoy
        return respuesta(filas)


@api.get("/ofertas/{oferta_id}/cartel")
def cartel(oferta_id: int, tamano: str = "a5", ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        o = db.fila(conn, "SELECT * FROM promociones WHERE id=%s", (oferta_id,))
        if not o:
            raise HTTPException(status_code=404, detail="No existe esa oferta.")
        p = db.fila(conn, "SELECT nombre FROM productos WHERE id=%s", (o["productos"][0],))
    ruta = pdf.cartel_oferta(p["nombre"], o, tamano if tamano in ("a4", "a5", "a6") else "a5")
    return FileResponse(ruta, media_type="application/pdf", filename=ruta.name)


@api.post("/ofertas/{oferta_id}/finalizar")
def finalizar_oferta(oferta_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "remarcar")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("UPDATE promociones SET estado='finalizada' WHERE id=%s AND estado='activa'", (oferta_id,))
    return respuesta({"ok": True})


# ------------------------------------------------------------------------------ merma
class Merma(BaseModel):
    producto_id: int
    ubicacion_id: int
    cantidad: float = Field(gt=0)
    motivo: str                    # vencimiento, rotura, robo, otro
    lote: str | None = None
    detalle: str | None = Field(default=None, max_length=300)


@api.post("/merma")
def registrar_merma(datos: Merma, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "recuentos")
    if datos.motivo not in ("vencimiento", "rotura", "robo", "otro"):
        raise HTTPException(status_code=400, detail="Motivo no válido.")
    with db.transaccion(ctx) as conn:
        if not db.fila(conn, "SELECT 1 FROM ubicaciones WHERE id=%s", (datos.ubicacion_id,)):
            raise HTTPException(status_code=404, detail="No existe esa sucursal o no tenés acceso.")
        costo = db.fila(conn, "SELECT costo FROM producto_proveedores WHERE producto_id=%s ORDER BY principal DESC LIMIT 1", (datos.producto_id,))
        cant = Decimal(str(datos.cantidad))
        with conn.cursor() as cur:
            cur.execute("UPDATE stock_actual SET cantidad = cantidad - %s, actualizado_at=now() WHERE producto_id=%s AND ubicacion_id=%s",
                        (cant, datos.producto_id, datos.ubicacion_id))
            if not cur.rowcount:
                cur.execute("INSERT INTO stock_actual (org_id, producto_id, ubicacion_id, cantidad) VALUES (%s,%s,%s,%s)",
                            (ctx.org_id, datos.producto_id, datos.ubicacion_id, -cant))
            if datos.lote:
                cur.execute("UPDATE stock_lotes SET cantidad = greatest(0, cantidad - %s) WHERE producto_id=%s AND ubicacion_id=%s AND lote=%s",
                            (cant, datos.producto_id, datos.ubicacion_id, datos.lote))
            motivo = f"{datos.motivo}{': ' + datos.detalle if datos.detalle else ''}"
            cur.execute("INSERT INTO movimientos_stock (org_id, producto_id, ubicacion_id, tipo, cantidad, costo_unitario, documento_tipo, motivo, usuario_id) "
                        "VALUES (%s,%s,%s,%s,%s,%s,'merma',%s,%s)",
                        (ctx.org_id, datos.producto_id, datos.ubicacion_id, "vencimiento" if datos.motivo == "vencimiento" else "merma", -cant,
                         costo["costo"] if costo else None, motivo, ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "merma", "stock", datos.producto_id, datos.model_dump(), sesiones.ip_de(request))
        return respuesta({"ok": True, "costo": (cant * costo["costo"]).quantize(Decimal("0.01")) if costo and costo["costo"] else None})


@api.get("/merma")
def merma(meses: int = 6, ubicaciones: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        desde = (hoy.replace(day=1) - timedelta(days=31 * (max(1, min(meses, 24)) - 1))).replace(day=1)
        ubic = lista_ids(ubicaciones)
        filas = db.filas(conn, """
            SELECT m.producto_id, p.nombre, coalesce(cp.nombre, c.nombre) categoria, pr.razon_social proveedor, u.nombre ubicacion,
                   date_trunc('month', m.fecha AT TIME ZONE o.zona_horaria)::date mes, m.tipo,
                   -sum(m.cantidad) unidades, -sum(m.cantidad * coalesce(m.costo_unitario, pp.costo, 0)) costo
            FROM movimientos_stock m JOIN productos p ON p.id = m.producto_id JOIN ubicaciones u ON u.id = m.ubicacion_id
            JOIN organizaciones o ON o.id = m.org_id
            LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
            LEFT JOIN LATERAL (SELECT costo, proveedor_id FROM producto_proveedores x WHERE x.producto_id = p.id ORDER BY principal DESC LIMIT 1) pp ON true
            LEFT JOIN proveedores pr ON pr.id = pp.proveedor_id
            WHERE m.tipo IN ('merma', 'vencimiento') AND m.fecha >= %s AND (%s OR m.ubicacion_id = ANY(%s))
            GROUP BY 1, 2, 3, 4, 5, 6, 7""", (desde, not ubic, ubic or [0]))
        rankings = {k: defaultdict(lambda: {"unidades": Decimal(0), "costo": Decimal(0)}) for k in ("nombre", "categoria", "proveedor", "ubicacion")}
        mensual = defaultdict(lambda: {"vencimiento": Decimal(0), "merma": Decimal(0)})
        for f in filas:
            for k in rankings:
                r = rankings[k][f[k] or "Sin dato"]
                r["unidades"] += f["unidades"]
                r["costo"] += f["costo"]
            mensual[f["mes"]][f["tipo"]] += f["costo"]

        def top(k):
            return sorted(({"nombre": n, **v} for n, v in rankings[k].items()), key=lambda x: -x["costo"])[:20]
        return respuesta({"total": sum((f["costo"] for f in filas), Decimal(0)),
                          "por_producto": top("nombre"), "por_categoria": top("categoria"), "por_proveedor": top("proveedor"), "por_ubicacion": top("ubicacion"),
                          "mensual": [{"mes": m, **mensual[m]} for m in sorted(mensual)]})
