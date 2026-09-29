"""Predicciones con IA · parte B: lo que faltaba de prioridad alta.

- (2, 6) Venta por sucursal × canal × día, 1 a 30 días, en pesos, con rango del 80 %: el mismo modelo que por producto aplicado a la
  serie diaria de facturación (patrón semanal, inicio/fin de mes, feriados, estacionalidad, tendencia) más la inflación mensual.
- (3) Curva anual: 24 meses reales y 12 proyectados con la estacionalidad aprendida y los eventos del calendario.
- (28, 29) Afluencia por hora (14 días) y cajas necesarias por turno: tickets promedio por día de semana × hora de las últimas 8
  semanas, ajustados por tendencia y feriados; cajas = tickets ÷ tickets que atiende una caja por hora (medido en los tickets).
- (14) Simulador de promoción: venta extra por el descuento (elasticidad) y por la exhibición (promos pasadas), margen,
  canibalización estimada y resultado neto, antes de lanzarla.
- (40) Flujo de caja a 90 días: cobros de ventas pronosticadas según el plazo de acreditación de cada medio, cobros de fiado,
  pagos a proveedores (OC pendientes y compras futuras según el costo de lo que se va a vender) y gastos fijos.
- (41) Riesgo de cobro por cliente de cuenta corriente: probabilidad de no cobrar según atraso, antigüedad, tendencia del saldo y
  cómo viene pagando.
"""
from __future__ import annotations

import calendar
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import calculos as C
from . import db, permisos, sesiones, suscripcion
from .api_comprar import _hoy_datos
from .api_plata import parametro
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])


def _feriados(conn) -> set[date]:
    return {f["fecha"] for f in db.filas(conn, "SELECT fecha FROM calendario WHERE tipo='feriado' AND (org_id IS NULL OR org_id = app_org())")}


def inflacion_mensual(conn) -> float:
    """Inflación mensual promedio de los últimos 3 meses del IPC cargado (0 si no hay)."""
    ipc = [float(f["indice"]) for f in db.filas(conn, "SELECT indice FROM indice_precios ORDER BY periodo DESC LIMIT 4")]
    if len(ipc) < 2:
        return 0.0
    return (ipc[0] / ipc[-1]) ** (1 / (len(ipc) - 1)) - 1


def pronostico_serie(serie: dict[date, float], hoy: date, dias: int, feriados: set[date], inflacion: float = 0.0) -> dict:
    """Pronóstico diario de una serie en pesos con su rango del 80 % por día y del total."""
    if not serie:
        return {"dias": [], "total": 0.0, "minimo": 0.0, "maximo": 0.0}
    base = C.vpd_ponderada(serie, set(), hoy) or 0.0
    factores = C.calcular_factores(serie, set(), hoy, feriados, desde=min(serie))
    pron = C.pronostico(base, factores, hoy, dias, feriados)
    pron = [x * (1 + inflacion) ** ((i + 1) / 30) for i, x in enumerate(pron)]
    desvio7 = C.desvio_semanal(C.semanas_con_stock(serie, set(), hoy), base * 7)
    salida = []
    for i, x in enumerate(pron):
        margen = C.Z_BANDA * desvio7 * math.sqrt(1 / 7)
        salida.append({"fecha": hoy + timedelta(days=i), "pronostico": round(x, 2), "minimo": round(max(0.0, x - margen), 2),
                       "maximo": round(x + margen, 2)})
    total = sum(pron)
    minimo, maximo = C.banda(total, desvio7, dias)
    return {"dias": salida, "total": round(total, 2), "minimo": round(minimo, 2), "maximo": round(maximo, 2), "desvio_7d": desvio7,
            "factores": {"semana": [round(x, 3) for x in factores.semana], "tendencia": round(factores.tendencia, 3)}}


# ------------------------------------------------------------------------------ (2, 6) venta por sucursal × canal × día
@api.get("/pronosticos/ventas")
def ventas_futuras(dias: int = 30, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    dias = max(7, min(dias, 60))
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        feriados = _feriados(conn)
        infl = inflacion_mensual(conn)
        series: dict = defaultdict(dict)
        for f in db.filas(conn, """SELECT a.ubicacion_id, u.nombre, ca.codigo canal, ca.nombre canal_nombre, a.fecha, sum(a.facturacion)::float f
                                   FROM agg_producto_ubicacion_dia a JOIN ubicaciones u ON u.id = a.ubicacion_id JOIN canales ca ON ca.id = a.canal_id
                                   WHERE a.fecha >= %s AND a.fecha < %s GROUP BY 1, 2, 3, 4, 5""", (hoy - timedelta(days=400), hoy)):
            series[(f["ubicacion_id"], f["nombre"], f["canal"], f["canal_nombre"])][f["fecha"]] = f["f"]
        filas, total_dias = [], defaultdict(lambda: [0.0, 0.0])
        for (uid, nombre, canal, canal_nombre), serie in sorted(series.items(), key=lambda x: (x[0][1], x[0][2])):
            if (hoy - max(serie)).days > 14:
                continue                                           # serie que dejó de vender: no se proyecta
            p = pronostico_serie(serie, hoy, dias, feriados, infl)
            reales = [{"fecha": hoy - timedelta(days=i), "real": round(serie.get(hoy - timedelta(days=i), 0.0), 2)} for i in range(28, 0, -1)]
            filas.append({"ubicacion_id": uid, "ubicacion": nombre, "canal": canal, "canal_nombre": canal_nombre, **p, "ultimos_28": reales,
                          "real_28": round(sum(r["real"] for r in reales), 2)})
            for d in p["dias"]:
                t = total_dias[d["fecha"]]
                t[0] += d["pronostico"]
                t[1] += ((d["maximo"] - d["pronostico"]) / C.Z_BANDA) ** 2
        total = [{"fecha": d, "pronostico": round(v[0], 2), "minimo": round(max(0.0, v[0] - C.Z_BANDA * math.sqrt(v[1])), 2),
                  "maximo": round(v[0] + C.Z_BANDA * math.sqrt(v[1]), 2)} for d, v in sorted(total_dias.items())]
        eventos = db.filas(conn, "SELECT fecha, tipo, nombre FROM calendario WHERE fecha BETWEEN %s AND %s AND (org_id IS NULL OR org_id = app_org()) "
                                 "ORDER BY fecha", (hoy, hoy + timedelta(days=dias)))
        return respuesta({"hoy": hoy, "dias": dias, "inflacion_mensual": infl, "series": filas, "total": total,
                          "total_periodo": round(sum(d["pronostico"] for d in total), 2), "eventos": eventos})


# ------------------------------------------------------------------------------ (3) curva anual con eventos
@api.get("/pronosticos/anual")
def curva_anual(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        infl = inflacion_mensual(conn)
        mensual = db.filas(conn, """SELECT date_trunc('month', a.fecha)::date mes, coalesce(cp.nombre, c.nombre, 'Sin categoría') categoria,
                                           sum(a.facturacion)::float f, count(DISTINCT a.fecha) dias
                                    FROM agg_producto_ubicacion_dia a JOIN productos p ON p.id = a.producto_id
                                    LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
                                    WHERE a.fecha >= %s AND a.fecha < %s GROUP BY 1, 2""", (date(hoy.year - 2, hoy.month, 1), hoy))
        ipc = {f["periodo"]: float(f["indice"]) for f in db.filas(conn, "SELECT periodo, indice FROM indice_precios")}
        ultimo = ipc[max(ipc)] if ipc else None
        por_mes: dict = defaultdict(float)
        por_cat_mes: dict = defaultdict(lambda: defaultdict(float))
        for f in mensual:
            por_mes[f["mes"]] += f["f"]
            por_cat_mes[f["categoria"]][f["mes"].month] += f["f"] * ((ultimo / ipc[f["mes"]]) if ultimo and ipc.get(f["mes"]) else 1)
        # Estacionalidad del total: ventas diarias del mes a precios de hoy ÷ promedio (con dos años, cada mes pesa igual).
        diaria_real = {}
        for mes, f in por_mes.items():
            dias = (min(hoy, (mes + timedelta(days=32)).replace(day=1)) - mes).days
            diaria_real[mes] = f / max(dias, 1) * ((ultimo / ipc[mes]) if ultimo and ipc.get(mes) else 1)
        por_numero = defaultdict(list)
        for mes, v in diaria_real.items():
            if mes.replace(day=1) != hoy.replace(day=1):
                por_numero[mes.month].append(v)
        prom = sum(sum(v) / len(v) for v in por_numero.values()) / len(por_numero) if por_numero else 0
        estacion = {m: (sum(v) / len(v)) / prom for m, v in por_numero.items()} if prom else {}
        ult28 = db.fila(conn, "SELECT coalesce(sum(facturacion), 0)::float f FROM agg_producto_ubicacion_dia WHERE fecha >= %s AND fecha < %s",
                        (hoy - timedelta(days=28), hoy))["f"] / 28
        base = ult28 / estacion.get(hoy.month, 1.0) if estacion else ult28
        proyectado = []
        for k in range(12):
            mes = (hoy.replace(day=1) + timedelta(days=32 * k)).replace(day=1)
            dias_mes = calendar.monthrange(mes.year, mes.month)[1]
            valor = base * estacion.get(mes.month, 1.0) * dias_mes * (1 + infl) ** (k + 0.5)
            proyectado.append({"mes": mes, "proyectado": round(valor, 2), "indice_estacional": round(estacion.get(mes.month, 1.0), 3)})
        eventos = db.filas(conn, "SELECT fecha, tipo, nombre FROM calendario WHERE fecha BETWEEN %s AND %s AND tipo IN ('comercial', 'feriado', 'cobro') "
                                 "AND (org_id IS NULL OR org_id = app_org()) ORDER BY fecha", (hoy, hoy + timedelta(days=365)))
        categorias = []
        for cat, meses in por_cat_mes.items():
            total = sum(meses.values())
            if total <= 0 or len(meses) < 6:
                continue
            prom_c = total / len(meses)
            pico = max(meses, key=meses.get)
            valle = min(meses, key=meses.get)
            categorias.append({"categoria": cat, "mes_pico": pico, "mes_valle": valle, "amplitud": round(meses[pico] / prom_c - meses[valle] / prom_c, 3),
                               "indices": {m: round(v / prom_c, 3) for m, v in sorted(meses.items())}})
        categorias.sort(key=lambda x: -x["amplitud"])
        return respuesta({"hoy": hoy, "real": [{"mes": m, "real": round(v, 2)} for m, v in sorted(por_mes.items())], "proyectado": proyectado,
                          "estacionalidad": {m: round(v, 3) for m, v in sorted(estacion.items())}, "eventos": eventos,
                          "categorias": categorias, "inflacion_mensual": infl, "meses_historia": len(por_mes)})


# ------------------------------------------------------------------------------ (28, 29) afluencia y personal
TICKETS_POR_CAJA_HORA = 30          # si no se puede medir (sin cajero en los tickets)


def capacidad_caja(conn, desde: date, hasta: date) -> tuple[float, str]:
    """Tickets que atiende una caja en una hora: percentil 90 de tickets por cajero en sus horas con actividad (las horas pico
    muestran la capacidad real, no la demanda)."""
    filas = [f["n"] for f in db.filas(conn, """SELECT count(*) n FROM tickets WHERE cajero IS NOT NULL AND estado <> 'anulado'
                                                AND fecha_hora >= %s AND fecha_hora < %s AND canal_id IN (SELECT id FROM canales WHERE codigo='fisico')
                                                GROUP BY ubicacion_id, cajero, date_trunc('hour', fecha_hora)""", (desde, hasta))]
    if len(filas) < 50:
        return float(parametro(conn, "tickets_por_caja_hora") or TICKETS_POR_CAJA_HORA), "parámetro"
    filas.sort()
    return max(5.0, float(filas[int(len(filas) * 0.9)])), "medido"


@api.get("/tienda/afluencia")
def afluencia(ubicacion_id: int | None = None, dias: int = 14, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    dias = max(1, min(dias, 28))
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        feriados = _feriados(conn)
        ubic = db.filas(conn, "SELECT id, nombre FROM ubicaciones WHERE activa AND tipo <> 'deposito' ORDER BY nombre")
        if not ubic:
            return respuesta({"ubicaciones": [], "horas": []})
        uid = ubicacion_id or ubic[0]["id"]
        filas = db.filas(conn, """SELECT fecha, hora, sum(tickets) t FROM agg_ubicacion_hora h JOIN canales ca ON ca.id = h.canal_id
                                  WHERE h.ubicacion_id=%s AND ca.codigo='fisico' AND fecha >= %s AND fecha < %s GROUP BY 1, 2""",
                          (uid, hoy - timedelta(days=56), hoy))
        por_dia_hora = defaultdict(lambda: defaultdict(float))
        totales_dia = defaultdict(float)
        for f in filas:
            totales_dia[f["fecha"]] += f["t"]
            if f["fecha"] not in feriados:
                por_dia_hora[f["fecha"].weekday()][f["hora"]] += f["t"]
        semanas_por_dia = defaultdict(int)
        for d in {f["fecha"] for f in filas}:
            if d not in feriados:
                semanas_por_dia[d.weekday()] += 1
        rec = sum(v for d, v in totales_dia.items() if d >= hoy - timedelta(days=28))
        ant = sum(v for d, v in totales_dia.items() if d < hoy - timedelta(days=28))
        tendencia = max(0.85, min(1.15, rec / ant)) if ant else 1.0
        feriado_f = 0.7
        capacidad, origen = capacidad_caja(conn, hoy - timedelta(days=56), hoy)
        horas = sorted({f["hora"] for f in filas})
        dias_salida = []
        for i in range(dias):
            d = hoy + timedelta(days=i)
            wd = d.weekday()
            n = semanas_por_dia.get(wd, 0)
            por_hora = []
            for h in horas:
                esperado = por_dia_hora[wd][h] / n * tendencia * (feriado_f if d in feriados else 1) if n else 0.0
                margen = C.Z_BANDA * math.sqrt(max(esperado, 0.0))
                cajas = math.ceil(esperado / capacidad) if esperado >= 0.5 else 0
                por_hora.append({"hora": h, "tickets": round(esperado, 1), "maximo": round(esperado + margen, 1), "cajas": cajas,
                                 "cajas_pico": math.ceil((esperado + margen) / capacidad) if esperado >= 0.5 else 0})
            turnos = []
            for nombre, desde_h, hasta_h in (("Mañana", 0, 14), ("Tarde", 14, 24)):
                hs = [x for x in por_hora if desde_h <= x["hora"] < hasta_h and x["tickets"] > 0]
                if hs:
                    turnos.append({"turno": nombre, "tickets": round(sum(x["tickets"] for x in hs)), "cajas_max": max(x["cajas"] for x in hs),
                                   "horas_caja": sum(x["cajas"] for x in hs), "hora_pico": max(hs, key=lambda x: x["tickets"])["hora"]})
            dias_salida.append({"fecha": d, "feriado": d in feriados, "tickets": round(sum(x["tickets"] for x in por_hora)), "horas": por_hora,
                                "turnos": turnos})
        return respuesta({"ubicaciones": ubic, "ubicacion_id": uid, "horas": horas, "dias": dias_salida, "capacidad_caja_hora": capacidad,
                          "capacidad_origen": origen, "tendencia": round(tendencia, 3)})


# ------------------------------------------------------------------------------ (14) simulador de promoción
class Simulacion(BaseModel):
    producto_id: int
    descuento: float = Field(gt=0, lt=0.9)
    dias: int = Field(ge=1, le=60)
    ubicacion_id: int | None = None


@api.post("/promociones/simular", dependencies=[Depends(suscripcion.modulo("completo"))])
def simular_promocion(datos: Simulacion, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Antes de lanzar: cuánto más se vendería, cuánto margen deja, cuánto le saca a los parecidos y el neto."""
    permisos.exigir(ctx, "ver_costos")
    from .api_avanzado import efecto_promocion, sensibilidades
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        p = db.fila(conn, """SELECT p.id, p.nombre, p.categoria_id,
                                    (SELECT precio FROM precios x WHERE x.producto_id = p.id AND x.ubicacion_id IS NULL AND x.canal_id IS NULL
                                     AND x.desde <= %s ORDER BY desde DESC LIMIT 1)::float precio,
                                    (SELECT costo FROM producto_proveedores pp WHERE pp.producto_id = p.id ORDER BY principal DESC LIMIT 1)::float costo
                             FROM productos p WHERE p.id=%s""", (hoy, datos.producto_id))
        if not p or not p["precio"]:
            raise HTTPException(status_code=404, detail="El producto no existe o no tiene precio.")
        m = db.filas(conn, "SELECT sum(pronostico_diario)::float d, sum(disponible)::float s FROM metricas_producto_actual m "
                           "JOIN ubicaciones u ON u.id = m.ubicacion_id WHERE m.producto_id=%s AND u.tipo <> 'deposito' "
                           "AND (%s::bigint IS NULL OR m.ubicacion_id = %s)", (datos.producto_id, datos.ubicacion_id, datos.ubicacion_id))[0]
        base_dia = m["d"] or 0.0
        stock = max(0.0, m["s"] or 0.0)
        sens = sensibilidades(conn, hoy).get(datos.producto_id, {})
        elast = sens.get("elasticidad")
        f_precio = C.factor_por_descuento(elast, datos.descuento) or C.factor_por_descuento(-1.2, datos.descuento)
        # Exhibición: lo que sumaron las promociones pasadas de la misma subcategoría más allá del precio.
        pasadas = db.filas(conn, """SELECT id, nombre, tipo, parametros, productos, ubicaciones, desde, hasta FROM promociones
                                    WHERE hasta < %s AND estado <> 'cancelada' AND desde >= %s
                                    AND EXISTS (SELECT 1 FROM productos x WHERE x.id = ANY(productos) AND x.categoria_id = %s)
                                    ORDER BY desde DESC LIMIT 6""", (hoy, hoy - timedelta(days=365), p["categoria_id"]))
        lifts, canib = [], []
        for pr in pasadas:
            e = efecto_promocion(conn, pr)
            base_u = sum(float(x["base_unidades"]) for x in e["productos"])
            if base_u > 0:
                lifts.append(1 + float(e["incremento_unidades"]) / base_u)
                if float(e["incremento_ganancia"]) > 0:
                    canib.append(min(1.0, float(e["canibalizacion"]) / float(e["incremento_ganancia"])))
        f_exhibicion = 1.0
        if lifts:
            desc_prom = datos.descuento
            f_precio_pasado = C.factor_por_descuento(elast if elast is not None else -1.2, desc_prom) or 1.0
            f_exhibicion = max(1.0, min(2.0, (sum(lifts) / len(lifts)) / f_precio_pasado))
        factor = f_precio * f_exhibicion
        sin_promo_u = base_dia * datos.dias
        con_promo_u = sin_promo_u * factor
        limitado = con_promo_u > stock
        con_promo_u_real = min(con_promo_u, stock) if stock else con_promo_u
        precio_oferta = p["precio"] * (1 - datos.descuento)
        costo = p["costo"]
        ganancia_sin = sin_promo_u * (p["precio"] - costo) if costo is not None else None
        ganancia_con = con_promo_u_real * (precio_oferta - costo) if costo is not None else None
        incremento = (ganancia_con - ganancia_sin) if ganancia_con is not None else None
        frac_canib = sum(canib) / len(canib) if canib else 0.25
        canibalizacion = max(0.0, (con_promo_u_real - sin_promo_u)) * ((p["precio"] - costo) if costo else 0) * frac_canib
        neto = (incremento - canibalizacion) if incremento is not None else None
        if costo is not None and precio_oferta <= costo:
            rec = "No conviene: el precio de oferta queda por debajo del costo."
        elif neto is not None and neto > 0:
            rec = "Conviene: deja más ganancia que no hacerla, aun descontando la canibalización."
        elif con_promo_u_real > sin_promo_u:
            rec = "Vende más pero deja menos plata: probá con menos descuento o usala solo para liquidar stock."
        else:
            rec = "No suma ventas: no la hagas."
        return respuesta({"producto": p["nombre"], "precio": round(p["precio"], 2), "precio_oferta": round(precio_oferta, 2), "costo": costo,
                          "elasticidad": elast, "fuente_elasticidad": sens.get("fuente") or "promedio del comercio (−1,2)",
                          "efecto_precio": round(f_precio, 3), "efecto_exhibicion": round(f_exhibicion, 3), "promos_pasadas": len(lifts),
                          "unidades_sin_promo": round(sin_promo_u, 1), "unidades_con_promo": round(con_promo_u_real, 1),
                          "unidades_extra": round(con_promo_u_real - sin_promo_u, 1), "limitado_por_stock": limitado, "stock": stock,
                          "ganancia_sin_promo": None if ganancia_sin is None else round(ganancia_sin, 2),
                          "ganancia_con_promo": None if ganancia_con is None else round(ganancia_con, 2),
                          "incremento_ganancia": None if incremento is None else round(incremento, 2),
                          "canibalizacion": round(canibalizacion, 2), "neto": None if neto is None else round(neto, 2), "recomendacion": rec})


# ------------------------------------------------------------------------------ (40) flujo de caja
class ConfigCaja(BaseModel):
    saldo_inicial: Decimal
    minimo_aceptable: Decimal = Decimal(0)
    gastos_fijos: list[dict] = Field(default_factory=list)       # [{"concepto": "Sueldos", "monto": 1000000, "dia": 5}]


@api.put("/finanzas/flujo/config", dependencies=[Depends(suscripcion.modulo("avanzado"))])
def configurar_caja(datos: ConfigCaja, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    for g in datos.gastos_fijos:
        if not g.get("concepto") or float(g.get("monto", 0)) < 0 or not 1 <= int(g.get("dia", 1)) <= 31:
            raise HTTPException(status_code=400, detail="Cada gasto fijo lleva concepto, monto y día del mes (1 a 31).")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO parametros (org_id, clave, valor) VALUES (%s,'flujo_caja',%s) ON CONFLICT (org_id, clave) "
                    "DO UPDATE SET valor=EXCLUDED.valor, updated_at=now()", (ctx.org_id, datos.model_dump_json()))
    return respuesta({"ok": True})


def _plazo_pago(texto: str | None) -> int:
    import re
    m = re.search(r"(\d+)", texto or "")
    return int(m.group(1)) if m else 0


@api.get("/finanzas/flujo", dependencies=[Depends(suscripcion.modulo("avanzado"))])
def flujo_de_caja(dias: int = 90, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    dias = max(30, min(dias, 120))
    with db.transaccion(ctx) as conn:
        return respuesta(calcular_flujo(conn, dias))


def calcular_flujo(conn, dias: int = 90) -> dict:
    """Saldo proyectado día a día: cobros de ventas y fiado, pagos de OC, compras para reponer y gastos fijos."""
    hoy = _hoy_datos(conn)
    cfg = parametro(conn, "flujo_caja") or {}
    cfg = cfg if isinstance(cfg, dict) else json.loads(cfg)
    saldo = float(cfg.get("saldo_inicial") or 0)
    minimo = float(cfg.get("minimo_aceptable") or 0)
    feriados = _feriados(conn)
    infl = inflacion_mensual(conn)
    # Ventas pronosticadas (total de la empresa) y su margen promedio.
    serie = {f["fecha"]: f["f"] for f in db.filas(conn, "SELECT fecha, sum(facturacion)::float f FROM agg_producto_ubicacion_dia "
                                                         "WHERE fecha >= %s AND fecha < %s GROUP BY 1", (hoy - timedelta(days=400), hoy))}
    p = pronostico_serie(serie, hoy, dias, feriados, infl)
    margen = db.fila(conn, "SELECT coalesce(sum(ganancia) / nullif(sum(facturacion), 0), 0.3)::float m FROM agg_producto_ubicacion_dia "
                           "WHERE fecha >= %s AND fecha < %s", (hoy - timedelta(days=90), hoy))["m"]
    # Mezcla de medios de pago y plazos de acreditación.
    mezcla = {f["medio"]: (float(f["monto"]), f["plazo"]) for f in db.filas(conn, """
        SELECT p.medio, sum(p.monto) monto, round(avg(p.plazo_acreditacion_dias)) plazo FROM pagos p JOIN tickets t ON t.id = p.ticket_id
        WHERE t.fecha_hora >= %s AND p.monto > 0 GROUP BY 1""", (hoy - timedelta(days=90),))}
    total_mezcla = sum(v[0] for v in mezcla.values()) or 1.0
    comisiones = parametro(conn, "comisiones_medios") or {}
    comisiones = comisiones if isinstance(comisiones, dict) else json.loads(comisiones)
    entradas, salidas = defaultdict(float), defaultdict(float)
    detalle = defaultdict(lambda: defaultdict(float))
    for d in p["dias"]:
        for medio, (monto, plazo) in mezcla.items():
            if medio == "cuenta_corriente":
                continue                                       # el fiado entra cuando se cobra (abajo)
            cfg_m = comisiones.get(medio, {})
            plazo_m = int(cfg_m.get("acreditacion_dias", plazo or 0))
            neto = d["pronostico"] * monto / total_mezcla * (1 - float(cfg_m.get("comision", 0)))
            dia = d["fecha"] + timedelta(days=plazo_m)
            entradas[dia] += neto
            detalle[dia]["cobro_ventas"] += neto
    # Cobros de fiado: saldo pendiente por vencimiento, con la probabilidad de cobro de cada cliente.
    for c in riesgo_clientes(conn, hoy):
        dia = max(hoy, c["vence"]) if c.get("vence") else hoy + timedelta(days=30)
        esperado = float(c["saldo"]) * (1 - c["prob_no_cobro"])
        entradas[dia] += esperado
        detalle[dia]["cobro_fiado"] += esperado
    # Pagos a proveedores: OC ya aprobadas o enviadas (según condiciones de pago) y compras futuras para reponer lo que se vende.
    for f in db.filas(conn, """SELECT o.estado, o.fecha_esperada, o.total::float total, pr.condiciones_pago FROM ordenes_compra o
                               JOIN proveedores pr ON pr.id = o.proveedor_id
                               WHERE o.estado IN ('aprobada', 'enviada', 'recibida_parcial')"""):
        dia = (f["fecha_esperada"] or hoy) + timedelta(days=_plazo_pago(f["condiciones_pago"]))
        if f["estado"] == "recibida_parcial" and dia < hoy:       # ya venció: se pagó con la mercadería que llegó
            continue
        dia = max(hoy, dia)
        salidas[dia] += f["total"]
        detalle[dia]["pago_proveedores"] += f["total"]
    plazo_prov = db.fila(conn, "SELECT round(avg(coalesce(substring(condiciones_pago from '(\\d+)')::int, 0))) p FROM proveedores WHERE activo")["p"] or 0
    for d in p["dias"][7:]:                                   # la primera semana ya está cubierta por las OC pendientes
        dia = d["fecha"] + timedelta(days=int(plazo_prov))
        compra = d["pronostico"] * (1 - margen)
        salidas[dia] += compra
        detalle[dia]["compras_futuras"] += compra
    for g in cfg.get("gastos_fijos", []):
        d = hoy
        while d <= hoy + timedelta(days=dias):
            if d.day == min(int(g["dia"]), calendar.monthrange(d.year, d.month)[1]):
                salidas[d] += float(g["monto"])
                detalle[d]["gastos_fijos"] += float(g["monto"])
            d += timedelta(days=1)
    linea, acumulado, bajo_minimo = [], saldo, None
    var_acum = 0.0
    for i in range(dias):
        d = hoy + timedelta(days=i)
        acumulado += entradas.get(d, 0.0) - salidas.get(d, 0.0)
        var_acum += (p["desvio_7d"] * math.sqrt(1 / 7) * (1 - margen)) ** 2 if i < len(p["dias"]) else 0
        margen_saldo = C.Z_BANDA * math.sqrt(var_acum)
        linea.append({"fecha": d, "entradas": round(entradas.get(d, 0.0), 2), "salidas": round(salidas.get(d, 0.0), 2),
                      "saldo": round(acumulado, 2), "saldo_min": round(acumulado - margen_saldo, 2), "saldo_max": round(acumulado + margen_saldo, 2)})
        if bajo_minimo is None and acumulado - margen_saldo < minimo:
            bajo_minimo = d
    resumen = defaultdict(float)
    for v in detalle.values():
        for k, x in v.items():
            resumen[k] += x
    return ({"hoy": hoy, "dias": dias, "configurado": bool(cfg), "saldo_inicial": saldo, "minimo_aceptable": minimo,
                      "gastos_fijos": cfg.get("gastos_fijos", []), "linea": linea, "primer_dia_bajo_minimo": bajo_minimo,
                      "totales": {k: round(v, 2) for k, v in resumen.items()}, "margen_promedio": round(margen, 4),
                      "saldo_final": round(acumulado, 2)})


# ------------------------------------------------------------------------------ (41) riesgo de cobro
def riesgo_clientes(conn, hoy: date) -> list[dict]:
    """Probabilidad de no cobrar el saldo de cada cliente de cuenta corriente (0 a 1), por puntos:
    atraso de lo vencido, deuda de más de 60 días, sin pagos en 45 días y saldo que crece. Transformada con una logística."""
    from .api_analisis import saldos_fiado
    clientes = saldos_fiado(conn, hoy)
    mov = defaultdict(lambda: {"compras_90": 0.0, "pagos_90": 0.0, "compras_30": 0.0, "pagos_30": 0.0, "vence": None})
    for f in db.filas(conn, "SELECT cliente_id, fecha, tipo, monto::float monto, vencimiento FROM cuentas_clientes WHERE fecha >= %s",
                      (hoy - timedelta(days=90),)):
        m = mov[f["cliente_id"]]
        if f["tipo"] == "compra":
            m["compras_90"] += f["monto"]
            if f["fecha"] >= hoy - timedelta(days=30):
                m["compras_30"] += f["monto"]
            if f["vencimiento"] and (m["vence"] is None or f["vencimiento"] < m["vence"]) and f["vencimiento"] >= hoy:
                m["vence"] = f["vencimiento"]
        elif f["tipo"] == "pago":
            m["pagos_90"] += -f["monto"]
            if f["fecha"] >= hoy - timedelta(days=30):
                m["pagos_30"] += -f["monto"]
    salida = []
    for c in clientes:
        m = mov[c["cliente_id"]]
        saldo = float(c["saldo"])
        vencido = float(c["vencido"])
        viejo = float(c["tramos"]["61_90"] + c["tramos"]["mas_90"])
        dias_sin_pago = (hoy - c["ultimo_pago"]).days if c["ultimo_pago"] else 999
        pago_ratio = m["pagos_90"] / m["compras_90"] if m["compras_90"] else (1.0 if m["pagos_90"] else 0.0)
        puntos = -3.0
        puntos += 2.5 * (vencido / saldo if saldo else 0)
        puntos += 2.0 * (viejo / saldo if saldo else 0)
        puntos += 1.2 if dias_sin_pago > 45 else 0.0
        puntos += 1.0 if m["compras_30"] > m["pagos_30"] * 1.5 and m["compras_30"] > 0 else 0.0
        puntos -= 1.5 * min(1.0, pago_ratio)
        prob = 1 / (1 + math.exp(-puntos))
        razones = []
        if vencido:
            razones.append(f"{round(vencido / saldo * 100)} % vencido")
        if viejo:
            razones.append("deuda de más de 60 días")
        if dias_sin_pago > 45:
            razones.append("sin pagos hace más de 45 días" if dias_sin_pago < 999 else "nunca pagó")
        if m["compras_30"] > m["pagos_30"] * 1.5 and m["compras_30"] > 0:
            razones.append("el saldo viene creciendo")
        if pago_ratio >= 0.9:
            razones.append("viene pagando lo que compra")
        salida.append({"cliente_id": c["cliente_id"], "nombre": c["nombre"], "saldo": c["saldo"], "vencido": c["vencido"], "vence": m["vence"],
                       "ultimo_pago": c["ultimo_pago"], "prob_no_cobro": round(prob, 3), "en_riesgo": round(saldo * prob, 2),
                       "semaforo": "rojo" if prob >= 0.5 else "amarillo" if prob >= 0.25 else "verde", "razones": razones,
                       "accion": "Venta solo de contado y llamar para cobrar" if prob >= 0.5 else
                                 "Recordar el vencimiento y no ampliar el crédito" if prob >= 0.25 else "Seguir normal"})
    return sorted(salida, key=lambda x: -x["en_riesgo"])


@api.get("/cuentas-corrientes/riesgo", dependencies=[Depends(suscripcion.modulo("avanzado"))])
def riesgo_de_cobro(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        clientes = riesgo_clientes(conn, hoy)
        return respuesta({"clientes": clientes, "saldo": round(sum(float(c["saldo"]) for c in clientes), 2),
                          "en_riesgo": round(sum(c["en_riesgo"] for c in clientes), 2),
                          "rojos": sum(1 for c in clientes if c["semaforo"] == "rojo")})
