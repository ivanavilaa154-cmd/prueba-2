"""Cálculo nocturno e incremental de Retail (parte 7).

1. Tablas analíticas: agg_producto_ubicacion_dia (producto × sucursal × canal × día) y agg_ubicacion_hora.
2. Períodos sin stock (a partir del stock al cierre y las ventas).
3. Métricas por producto × sucursal (sección 6): VPD sin días sin stock, pronóstico con factores, días de stock,
   fecha de quiebre, horizonte, stock de seguridad, cantidad sugerida, semáforo, capital, riesgo de vencimiento…
   con la explicación de cada número.
4. Clase ABC por ganancia (Pareto) y rol del producto.
5. Después: sugerencias de reposición (reposicion.py) y alertas (alertas.py).

Nocturno: recalcula todo. Incremental: re-agrega los últimos días y recalcula métricas (se usa tras importar datos).
"""
from __future__ import annotations

import json
import math
import threading
import time as _time
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from statistics import median
from zoneinfo import ZoneInfo

from . import calculos as C
from . import db

_candados: dict[int, threading.Lock] = defaultdict(threading.Lock)


def contexto_sistema(org_id: int) -> db.Contexto:
    """El cálculo corre como proceso del sistema dentro de la empresa, viendo todas sus sucursales."""
    return db.Contexto(usuario_id=0, org_id=org_id, rol="dueno", nombre="Sistema", todas_ubicaciones=True)


def hoy_de(conn, org_id: int) -> date:
    zona = db.fila(conn, "SELECT zona_horaria FROM organizaciones WHERE id=%s", (org_id,))["zona_horaria"]
    return datetime.now(ZoneInfo(zona)).date()


def _agregar(conn, org_id: int, desde: date | None) -> None:
    filtro = "AND l.fecha >= %(desde)s" if desde else ""
    filtro_t = "AND (t.fecha_hora AT TIME ZONE o.zona_horaria)::date >= %(desde)s" if desde else ""
    params = {"org": org_id, "desde": desde}
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM agg_producto_ubicacion_dia WHERE org_id=%(org)s {'AND fecha >= %(desde)s' if desde else ''}", params)
        cur.execute(f"""
            INSERT INTO agg_producto_ubicacion_dia (org_id, producto_id, ubicacion_id, canal_id, fecha, unidades, facturacion, costo,
                                                    ganancia, tickets, unidades_promo, sin_costo)
            SELECT l.org_id, l.producto_id, l.ubicacion_id, t.canal_id, l.fecha,
                   sum(l.cantidad), sum(l.precio_cobrado * l.cantidad),
                   sum(coalesce(l.costo_unitario, 0) * l.cantidad),
                   sum(l.precio_cobrado * l.cantidad) - sum(coalesce(l.costo_unitario, 0) * l.cantidad),
                   count(DISTINCT l.ticket_id), sum(CASE WHEN l.promocion_id IS NOT NULL THEN l.cantidad ELSE 0 END),
                   bool_or(l.costo_unitario IS NULL)
            FROM tickets_lineas l JOIN tickets t ON t.id = l.ticket_id
            WHERE l.org_id = %(org)s AND t.estado <> 'anulado' {filtro}
            GROUP BY l.org_id, l.producto_id, l.ubicacion_id, t.canal_id, l.fecha""", params)
        cur.execute(f"""DELETE FROM agg_ubicacion_hora WHERE org_id=%(org)s {'AND fecha >= %(desde)s' if desde else ''}""", params)
        cur.execute(f"""
            INSERT INTO agg_ubicacion_hora (org_id, ubicacion_id, canal_id, fecha, hora, tickets, facturacion, unidades)
            SELECT t.org_id, t.ubicacion_id, t.canal_id, (t.fecha_hora AT TIME ZONE o.zona_horaria)::date,
                   extract(hour FROM t.fecha_hora AT TIME ZONE o.zona_horaria)::int,
                   count(*) FILTER (WHERE t.total > 0), sum(t.total),
                   coalesce(sum((SELECT sum(l.cantidad) FROM tickets_lineas l WHERE l.ticket_id = t.id)), 0)
            FROM tickets t JOIN organizaciones o ON o.id = t.org_id
            WHERE t.org_id = %(org)s AND t.estado <> 'anulado' {filtro_t}
            GROUP BY 1, 2, 3, 4, 5""", params)


def _foto_stock(conn, org_id: int, hoy: date) -> None:
    """Stock al cierre de hoy = stock actual (se actualiza en cada cálculo; la última foto del día queda como cierre).
    Con esto se sabe, día por día, si hubo stock (lo necesita la VPD para excluir los días sin stock)."""
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO stock_diario (org_id, producto_id, ubicacion_id, fecha, stock_cierre, con_stock)
                       SELECT org_id, producto_id, ubicacion_id, %s, cantidad, cantidad > 0 FROM stock_actual WHERE org_id=%s
                       ON CONFLICT (producto_id, ubicacion_id, fecha) DO UPDATE SET stock_cierre=EXCLUDED.stock_cierre, con_stock=EXCLUDED.con_stock""",
                    (hoy, org_id))


def recalcular(org_id: int, hoy: date | None = None, tipo: str = "nocturno", desde: date | None = None) -> dict:
    """Recalcula todo para una empresa. Devuelve un resumen (tiempos y conteos).
    desde: reagrega a partir de esa fecha (por ejemplo, después de importar ventas viejas)."""
    with _candados[org_id]:
        return _recalcular(org_id, hoy, tipo, desde)


def _recalcular(org_id: int, hoy: date | None, tipo: str, desde: date | None = None) -> dict:
    t0 = _time.time()
    ctx = contexto_sistema(org_id)
    with db.transaccion(ctx) as conn:
        hoy = hoy or hoy_de(conn, org_id)
        ejecucion = db.fila(conn, "INSERT INTO ejecuciones_calculo (org_id, tipo) VALUES (%s,%s) RETURNING id", (org_id, tipo))["id"]
        _foto_stock(conn, org_id, hoy)
        _agregar(conn, org_id, desde if desde else (None if tipo == "nocturno" else hoy - timedelta(days=3)))
        t_agg = _time.time() - t0
        prueba = None
        if tipo == "nocturno":             # primera vez: prueba sobre el pasado, así el error (y su corrección) se miden desde el día uno
            from . import pronosticos
            prueba = pronosticos.prueba_sobre_el_pasado(conn, org_id, hoy)
        resumen = _metricas(conn, org_id, hoy)
        resumen["prueba_pasado"] = prueba
        resumen["segundos_agregados"] = round(t_agg, 2)
    # Reposición y alertas en su propia transacción (usan las métricas recién guardadas).
    try:
        from . import reposicion
        resumen["reposicion"] = reposicion.generar(org_id, hoy)
    except ImportError:
        pass
    try:
        from . import alertas
        resumen["alertas"] = alertas.generar(org_id, hoy)
    except ImportError:
        pass
    resumen["segundos"] = round(_time.time() - t0, 2)
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("UPDATE ejecuciones_calculo SET fin=now(), estado='ok', detalle=%s WHERE id=%s",
                    (json.dumps(resumen, default=str), ejecucion))
    return resumen


# ------------------------------------------------------------------------------------------- métricas
def _metricas(conn, org_id: int, hoy: date) -> dict:
    desde_hist = hoy - timedelta(days=400)
    ubicaciones = {f["id"]: f for f in db.filas(conn, "SELECT id, nombre, tipo FROM ubicaciones WHERE org_id=%s AND activa", (org_id,))}
    productos = {f["id"]: f for f in db.filas(conn, """
        SELECT p.id, p.codigo_interno, p.nombre, p.categoria_id, c.padre_id, coalesce(cp.nombre, c.nombre) AS categoria,
               c.nombre AS subcategoria, p.perecedero, p.created_at::date AS alta, p.activo
        FROM productos p LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
        WHERE p.org_id=%s AND p.activo""", (org_id,))}
    proveedor = {}
    for f in db.filas(conn, """
            SELECT DISTINCT ON (pp.producto_id) pp.producto_id, pp.proveedor_id, pp.costo, pp.unidades_por_bulto, pp.multiplo_compra,
                   pr.razon_social, pr.dias_visita, pr.demora_entrega_dias
            FROM producto_proveedores pp JOIN proveedores pr ON pr.id = pp.proveedor_id
            WHERE pp.org_id=%s AND pr.activo ORDER BY pp.producto_id, pp.principal DESC, pp.prioridad""", (org_id,)):
        proveedor[f["producto_id"]] = f
    stock = {(f["producto_id"], f["ubicacion_id"]): f for f in db.filas(conn, "SELECT * FROM stock_actual WHERE org_id=%s", (org_id,))}
    # Pedidos ya aprobados (OC aprobadas/enviadas y transferencias aprobadas) y cuándo llegan; lo enviado en
    # transferencias ya está en stock_actual.en_transito (llega según la demora de traslado, 1 día por defecto).
    abiertos = defaultdict(float)
    llegadas = defaultdict(list)
    for f in db.filas(conn, """
            SELECT l.producto_id, coalesce(l.ubicacion_id, o.ubicacion_id) AS ubicacion_id, o.fecha_esperada,
                   sum(l.cantidad - l.cantidad_recibida) AS c
            FROM ordenes_compra_lineas l JOIN ordenes_compra o ON o.id = l.orden_id
            WHERE o.org_id=%s AND o.estado IN ('aprobada', 'enviada', 'recibida_parcial') GROUP BY 1, 2, 3""", (org_id,)):
        if f["ubicacion_id"] and f["c"] > 0:
            abiertos[(f["producto_id"], f["ubicacion_id"])] += float(f["c"])
            dias = (f["fecha_esperada"] - hoy).days if f["fecha_esperada"] else 2
            llegadas[(f["producto_id"], f["ubicacion_id"])].append((max(0, dias), float(f["c"])))
    for f in db.filas(conn, """
            SELECT l.producto_id, t.destino_id, sum(l.cantidad) AS c FROM transferencias_lineas l JOIN transferencias t ON t.id = l.transferencia_id
            WHERE t.org_id=%s AND t.estado = 'aprobada' GROUP BY 1, 2""", (org_id,)):
        abiertos[(f["producto_id"], f["destino_id"])] += float(f["c"])
        llegadas[(f["producto_id"], f["destino_id"])].append((2, float(f["c"])))
    precio = {}
    for f in db.filas(conn, """
            SELECT DISTINCT ON (producto_id) producto_id, precio FROM precios
            WHERE org_id=%s AND ubicacion_id IS NULL AND canal_id IS NULL AND desde <= %s AND (hasta IS NULL OR hasta >= %s)
            ORDER BY producto_id, desde DESC""", (org_id, hoy, hoy)):
        precio[f["producto_id"]] = f["precio"]
    ventas: dict = defaultdict(dict)
    for f in db.filas(conn, "SELECT producto_id, ubicacion_id, fecha, sum(unidades) AS u FROM agg_producto_ubicacion_dia "
                            "WHERE org_id=%s AND fecha >= %s GROUP BY 1, 2, 3", (org_id, desde_hist)):
        ventas[(f["producto_id"], f["ubicacion_id"])][f["fecha"]] = float(f["u"])
    cierre: dict = defaultdict(dict)
    for f in db.filas(conn, "SELECT producto_id, ubicacion_id, fecha, stock_cierre FROM stock_diario WHERE org_id=%s AND fecha >= %s",
                      (org_id, desde_hist)):
        cierre[(f["producto_id"], f["ubicacion_id"])][f["fecha"]] = float(f["stock_cierre"])
    feriados = {f["fecha"] for f in db.filas(conn, "SELECT fecha FROM calendario WHERE tipo='feriado' AND (org_id IS NULL OR org_id=%s)", (org_id,))}
    reglas = db.filas(conn, "SELECT * FROM reglas_reposicion WHERE org_id=%s", (org_id,))
    lotes = defaultdict(list)
    for f in db.filas(conn, "SELECT producto_id, ubicacion_id, lote, cantidad, vencimiento FROM stock_lotes WHERE org_id=%s AND cantidad > 0", (org_id,)):
        lotes[(f["producto_id"], f["ubicacion_id"])].append(f)
    ganancia90 = defaultdict(Decimal)
    unidades90 = defaultdict(Decimal)
    facturacion90 = defaultdict(Decimal)
    ganancia90_pu = defaultdict(Decimal)
    costo90_pu = defaultdict(Decimal)
    for f in db.filas(conn, "SELECT producto_id, ubicacion_id, sum(ganancia) g, sum(unidades) u, sum(facturacion) fa, sum(costo) co "
                            "FROM agg_producto_ubicacion_dia WHERE org_id=%s AND fecha > %s AND fecha < %s GROUP BY 1, 2",
                      (org_id, hoy - timedelta(days=91), hoy)):
        ganancia90[f["producto_id"]] += f["g"]
        unidades90[f["producto_id"]] += f["u"]
        facturacion90[f["producto_id"]] += f["fa"]
        ganancia90_pu[(f["producto_id"], f["ubicacion_id"])] += f["g"]
        costo90_pu[(f["producto_id"], f["ubicacion_id"])] += f["co"]
    merma90 = {(f["producto_id"], f["ubicacion_id"]): float(f["m"]) for f in db.filas(
        conn, "SELECT producto_id, ubicacion_id, -sum(cantidad) m FROM movimientos_stock WHERE org_id=%s AND tipo IN ('merma', 'vencimiento') "
              "AND fecha >= %s GROUP BY 1, 2", (org_id, hoy - timedelta(days=90)))}
    vendido90 = {(f["producto_id"], f["ubicacion_id"]): float(f["u"]) for f in db.filas(
        conn, "SELECT producto_id, ubicacion_id, sum(unidades) u FROM agg_producto_ubicacion_dia WHERE org_id=%s AND fecha > %s GROUP BY 1, 2",
        (org_id, hoy - timedelta(days=91)))}
    ultima_venta = {(f["producto_id"], f["ubicacion_id"]): f["u"] for f in db.filas(
        conn, "SELECT producto_id, ubicacion_id, max(fecha) u FROM agg_producto_ubicacion_dia WHERE org_id=%s AND unidades > 0 GROUP BY 1, 2",
        (org_id,))}
    stock_prom90 = {(f["producto_id"], f["ubicacion_id"]): float(f["s"]) for f in db.filas(
        conn, "SELECT producto_id, ubicacion_id, avg(greatest(stock_cierre, 0)) s FROM stock_diario WHERE org_id=%s AND fecha > %s GROUP BY 1, 2",
        (org_id, hoy - timedelta(days=91)))}

    # ---- ABC por ganancia (90 días, consolidado) y rol del producto
    abc = C.clasificar_abc({pid: ganancia90.get(pid, Decimal(0)) for pid in productos})
    margenes = {pid: float(ganancia90[pid] / facturacion90[pid]) for pid in productos if facturacion90.get(pid)}
    med_v = median([float(unidades90.get(pid, 0)) for pid in productos]) if productos else 0
    med_m = median(list(margenes.values())) if margenes else 0
    with conn.cursor() as cur:
        for pid in productos:
            rol = C.rol_producto(float(unidades90.get(pid, 0)), margenes.get(pid), med_v, med_m) if unidades90.get(pid) else "peso_muerto"
            cur.execute("UPDATE productos SET clase_abc=%s, rol_producto=%s WHERE id=%s", (abc[pid][0], rol, pid))
        mes = hoy.replace(day=1)
        cur.execute("DELETE FROM historial_abc WHERE org_id=%s AND mes=%s", (org_id, mes))
    db.copiar(conn, "historial_abc", ["org_id", "producto_id", "mes", "clase"], [(org_id, pid, mes, abc[pid][0]) for pid in productos])
    _historial_abc(conn, org_id, hoy, productos)

    # ---- referencias por categoría (para productos con poca historia)
    cat_ventas: dict = defaultdict(lambda: defaultdict(float))
    cat_productos: dict = defaultdict(set)
    for (pid, uid), vs in ventas.items():
        if pid not in productos:
            continue
        clave = (productos[pid]["padre_id"] or productos[pid]["categoria_id"], uid)
        cat_productos[clave].add(pid)
        for d, u in vs.items():
            cat_ventas[clave][d] += u
    cat_factores = {}
    cat_vpd = {}
    for clave, vs in cat_ventas.items():
        cat_factores[clave] = C.calcular_factores(vs, set(), hoy, feriados, desde=min(vs) if vs else None)
        cat_factores[clave].origen = "categoria"
        ult = [vs.get(hoy - timedelta(days=i), 0.0) for i in range(1, 29)]
        cat_vpd[clave] = sum(ult) / 28 / max(1, len(cat_productos[clave]))

    # ---- corrección de sesgo por categoría × sucursal, medida con los pronósticos anteriores
    from . import pronosticos
    sesgo = pronosticos.factores_sesgo(conn, hoy)

    # ---- métricas por producto × ubicación
    filas = []
    periodos = []
    registro = []
    ahora = datetime.now()
    conteo = defaultdict(int)
    for uid, u in ubicaciones.items():
        for pid, p in productos.items():
            clave = (pid, uid)
            st = stock.get(clave)
            if not st and clave not in ventas:
                continue
            cantidad = float(st["cantidad"]) if st else 0.0
            reservado = float(st["reservado"]) if st else 0.0
            transito = float(st["en_transito"]) if st else 0.0
            disponible = cantidad - reservado
            prov = proveedor.get(pid)
            costo = prov["costo"] if prov and prov["costo"] is not None else None
            vs = ventas.get(clave, {})
            cierres = cierre.get(clave, {})
            sin = C.dias_sin_stock(vs, cierres, desde_hist, hoy - timedelta(days=1))
            periodos.extend(_periodos(org_id, pid, uid, sin, hoy))
            catk = (p["padre_id"] or p["categoria_id"], uid)
            # Desde cuándo hay datos del producto en esta sucursal: primera venta o primer stock registrado.
            # (La fecha de alta en la base no sirve: al importar historia, todos los productos se crean el mismo día.)
            fechas = ([min(vs)] if vs else []) + ([min(cierres)] if cierres else [])
            primera = min(fechas) if fechas else None
            alta = primera if primera and (hoy - primera).days < 28 else None
            if u["tipo"] == "deposito" and not vs:
                r_vpd = C.ResultadoVPD(0.0, 0, 0, 0.0, "normal")
            else:
                r_vpd = C.venta_promedio_diaria(vs, sin, hoy, referencia=cat_vpd.get(catk), desde_alta=alta)
            base = C.vpd_ponderada(vs, sin, hoy)
            if r_vpd.confianza == "baja" or base is None:
                base = r_vpd.vpd
            factores = C.calcular_factores(vs, sin, hoy, feriados, cat_factores.get(catk), desde=primera)
            pron = C.pronostico(base, factores, hoy, 120, feriados)
            f_sesgo = sesgo.get(catk, 1.0)                    # aprende de su error medido (Salud de los pronósticos)
            if f_sesgo != 1.0:
                pron = [x * f_sesgo for x in pron]
            h = C.horizonte(hoy, prov["dias_visita"] if prov else None, prov["demora_entrega_dias"] if prov else None)
            regla = _regla(reglas, pid, p["categoria_id"], p["padre_id"], uid)
            dias_stock = C.dias_de_stock(disponible, pron)
            quiebre = C.fecha_quiebre(disponible, pron, hoy, llegadas.get(clave, []) + ([(1, transito)] if transito > 0 else [])) \
                if sum(pron[:120]) > 0 else None
            historia = [vs.get(hoy - timedelta(days=i), 0.0) for i in range(1, 57) if (hoy - timedelta(days=i)) not in sin]
            ss = C.stock_seguridad(historia, abc[pid][0], h.horizonte,
                                   float(regla["stock_seguridad"]) if regla and regla["stock_seguridad"] is not None else None)
            maximo = None
            if regla:
                if regla["stock_maximo"] is not None:
                    maximo = float(regla["stock_maximo"])
                elif regla["stock_maximo_dias"] is not None:
                    maximo = float(regla["stock_maximo_dias"]) * (sum(pron[:28]) / 28)
            pron_h = sum(pron[:h.horizonte])
            # Rango del 80 % y probabilidad de quiebre antes de la próxima llegada (predicciones, parte A).
            desvio7 = C.desvio_semanal(C.semanas_con_stock(vs, sin, hoy), sum(pron[:7]))
            p7 = sum(pron[:7])
            p7_min, p7_max = C.banda(p7, desvio7, 7)
            dias_llegada = max(1, h.llegada_proxima)
            demanda_llegada = sum(pron[:dias_llegada])
            p_quiebre = None if u["tipo"] == "deposito" or p7 <= 0 else \
                C.prob_quiebre(disponible + transito, demanda_llegada, desvio7 * math.sqrt(dias_llegada / 7))
            if u["tipo"] != "deposito" and vs:
                registro.append((pid, uid, p7, p7_min, p7_max, f_sesgo))
            # La merma histórica de los perecederos baja el pedido (sección 9: merma).
            f_merma = C.factor_merma(merma90.get(clave, 0.0), vendido90.get(clave, 0.0)) if p["perecedero"] else 1.0
            pron_h *= f_merma
            if u["tipo"] == "deposito":
                sug = C.Sugerencia(0.0, 0.0, 0.0, 1)
            else:
                sug = C.cantidad_sugerida(pron_h, ss, disponible, transito, abiertos.get(clave, 0.0),
                                          prov["unidades_por_bulto"] if prov else 1, prov["multiplo_compra"] if prov else 1, maximo)
            sem = C.semaforo(dias_stock, quiebre, hoy, h, disponible=disponible)
            conteo[sem] += 1
            capital = (Decimal(str(max(0.0, cantidad))) * costo).quantize(Decimal("0.01")) if costo is not None else None
            pv = precio.get(pid)
            riesgo_ventas = None
            if sem == "rojo" and pv is not None and quiebre is not None:
                dias_perdidos = max(0, (hoy + timedelta(days=h.llegada_proxima) - quiebre).days)
                inicio_perdida = max(0, (quiebre - hoy).days)
                riesgo_ventas = (Decimal(str(sum(pron[inicio_perdida:inicio_perdida + dias_perdidos]))) * pv).quantize(Decimal("0.01"))
            ultima = ultima_venta.get(clave)
            dias_sin_venta = (hoy - ultima).days if ultima else None
            riesgo_venc = None
            detalle_lotes = []
            if lotes.get(clave):
                detalle_lotes = C.unidades_que_no_llegan(lotes[clave], pron, hoy)
                riesgo_venc = sum(Decimal(str(x["no_llegan"])) for x in detalle_lotes) * (costo or Decimal(0))
                riesgo_venc = riesgo_venc.quantize(Decimal("0.01"))
            inv_prom = Decimal(str(stock_prom90.get(clave, 0))) * (costo or Decimal(0))
            gm = C.gmroi(ganancia90_pu.get(clave, Decimal(0)), inv_prom)
            rot = C.rotacion_anual(costo90_pu.get(clave, Decimal(0)), inv_prom, 90)
            if dias_sin_venta is not None and dias_sin_venta >= 90:
                tendencia = "muerto"
            elif factores.tendencia >= 1.1:
                tendencia = "creciendo"
            elif factores.tendencia <= 0.9:
                tendencia = "cayendo"
            else:
                tendencia = "estable"
            explicacion = {
                "vpd": round(r_vpd.vpd, 3), "vpd_ponderada": round(base, 3), "dias_con_stock": r_vpd.dias_con_stock,
                "dias_sin_stock": r_vpd.dias_sin_stock, "unidades_28d": round(r_vpd.unidades, 3), "confianza": r_vpd.confianza,
                "usa_referencia_categoria": r_vpd.usa_referencia,
                "factores": {"semana": [round(x, 3) for x in factores.semana], "inicio_mes": round(factores.inicio_mes, 3),
                             "fin_mes": round(factores.fin_mes, 3), "feriado": round(factores.feriado, 3),
                             "estacional_mes": round(factores.estacional.get(hoy.month, 1.0), 3) if factores.estacional else None,
                             "tendencia": round(factores.tendencia, 3), "origen": factores.origen},
                "pronostico_14d": [round(x, 2) for x in pron[:14]],
                "pronostico_7d": round(p7, 2), "pronostico_7d_rango": [round(p7_min, 2), round(p7_max, 2)], "desvio_semanal": round(desvio7, 3),
                "pronostico_horizonte_rango": [round(x * f_merma, 2) for x in C.banda(sum(pron[:h.horizonte]), desvio7, h.horizonte)],
                "prob_quiebre": None if p_quiebre is None else round(p_quiebre, 4), "dias_hasta_llegada": dias_llegada,
                "producto_nuevo": bool(alta), "correccion_sesgo": round(f_sesgo, 3),
                "pronostico_horizonte": round(pron_h, 2), "horizonte": h.horizonte, "proxima_oportunidad": h.proxima_oportunidad,
                "llegada_proxima": h.llegada_proxima, "supuesto_proveedor": h.supuesto,
                "proveedor": prov["razon_social"] if prov else None, "demora": prov["demora_entrega_dias"] if prov else None,
                "dias_visita": prov["dias_visita"] if prov else None,
                "stock": cantidad, "reservado": reservado, "en_transito": transito, "pedidos_abiertos": abiertos.get(clave, 0.0),
                "stock_seguridad": round(ss, 2), "necesidad": round(sug.necesidad, 2), "multiplo": sug.multiplo,
                "recortada_por_maximo": sug.recortada_por_maximo, "stock_maximo": maximo,
                "stock_negativo": cantidad < 0, "sin_costo": costo is None, "clase_abc": abc[pid][0],
                "precio": str(pv) if pv is not None else None, "costo": str(costo) if costo is not None else None,
                "merma_90d": round(merma90.get(clave, 0.0), 3), "factor_merma": round(f_merma, 3),
                "lotes": [{"lote": x["lote"], "vencimiento": x["vencimiento"], "cantidad": float(x["cantidad"]), "no_llegan": round(x["no_llegan"], 3),
                           "dias": x.get("dias"), "vendido_hasta_vencer": round(float(x["cantidad"]) - x["no_llegan"], 3)} for x in detalle_lotes],
                "pronostico_120d": [round(x, 3) for x in pron[:120]] if detalle_lotes else None,
            }
            filas.append((org_id, pid, uid, round(r_vpd.vpd, 4), round(sum(pron[:28]) / 28, 4), round(disponible, 3),
                           None if dias_stock is None else round(min(dias_stock, 99999), 2), quiebre, h.horizonte, round(ss, 3),
                           sug.cantidad, prov["proveedor_id"] if prov else None, sem, abc[pid][0], tendencia, dias_sin_venta,
                           capital, None if gm is None else round(gm, 4), None if rot is None else round(rot, 4), riesgo_venc,
                           r_vpd.confianza, riesgo_ventas, json.dumps(explicacion, default=str), ahora,
                           round(p7, 3), round(p7_min, 3), round(p7_max, 3), None if p_quiebre is None else round(p_quiebre, 4)))
    with conn.cursor() as cur:
        cur.execute("DELETE FROM metricas_producto_actual WHERE org_id=%s", (org_id,))
        cur.execute("DELETE FROM periodos_sin_stock WHERE org_id=%s", (org_id,))
    db.copiar(conn, "metricas_producto_actual", ["org_id", "producto_id", "ubicacion_id", "vpd", "pronostico_diario", "disponible",
                                                 "dias_stock", "fecha_quiebre", "horizonte_dias", "stock_seguridad", "cantidad_sugerida",
                                                 "proveedor_id", "semaforo", "clase_abc", "tendencia", "dias_sin_venta", "capital", "gmroi",
                                                 "rotacion", "riesgo_vencimiento", "confianza", "ventas_en_riesgo", "explicacion",
                                                 "calculado_at", "pronostico_7d", "pronostico_7d_min", "pronostico_7d_max", "prob_quiebre"], filas)
    pronosticos.registrar(conn, org_id, hoy, registro)
    db.copiar(conn, "periodos_sin_stock", ["org_id", "producto_id", "ubicacion_id", "desde", "hasta"], periodos)
    return {"metricas": len(filas), "semaforo": dict(conteo), "periodos_sin_stock": len(periodos)}


def _periodos(org_id: int, pid: int, uid: int, sin: set[date], hoy: date) -> list[tuple]:
    """Días sin stock consecutivos → períodos (hasta = nulo si sigue sin stock ayer)."""
    resultado = []
    for d in sorted(sin):
        if resultado and resultado[-1][4] == d - timedelta(days=1):
            resultado[-1] = resultado[-1][:4] + (d,)
        else:
            resultado.append((org_id, pid, uid, d, d))
    ayer = hoy - timedelta(days=1)
    return [r[:4] + (None if r[4] == ayer else r[4],) for r in resultado]


def _regla(reglas: list[dict], pid: int, cat: int | None, padre: int | None, uid: int) -> dict | None:
    """La regla más específica: producto+sucursal, producto, categoría+sucursal, categoría."""
    def puntaje(r):
        if r["producto_id"] == pid:
            return 4 if r["ubicacion_id"] == uid else (3 if r["ubicacion_id"] is None else -1)
        if r["categoria_id"] in (cat, padre) and r["producto_id"] is None:
            return 2 if r["ubicacion_id"] == uid else (1 if r["ubicacion_id"] is None else -1)
        return -1
    candidatas = [(puntaje(r), r) for r in reglas]
    candidatas = [c for c in candidatas if c[0] >= 0]
    return max(candidatas, key=lambda c: c[0])[1] if candidatas else None


def _historial_abc(conn, org_id: int, hoy: date, productos: dict) -> None:
    """Clase ABC de cada mes anterior (ganancia del mes). Se completa solo lo que falta."""
    hechos = {f["mes"] for f in db.filas(conn, "SELECT DISTINCT mes FROM historial_abc WHERE org_id=%s", (org_id,))}
    meses = db.filas(conn, "SELECT DISTINCT date_trunc('month', fecha)::date AS mes FROM agg_producto_ubicacion_dia WHERE org_id=%s "
                           "AND fecha < %s ORDER BY 1", (org_id, hoy.replace(day=1)))
    for m in meses:
        if m["mes"] in hechos:
            continue
        g = {f["producto_id"]: f["g"] for f in db.filas(
            conn, "SELECT producto_id, sum(ganancia) g FROM agg_producto_ubicacion_dia WHERE org_id=%s AND date_trunc('month', fecha)=%s GROUP BY 1",
            (org_id, m["mes"]))}
        clases = C.clasificar_abc({pid: g.get(pid, Decimal(0)) for pid in productos})
        db.copiar(conn, "historial_abc", ["org_id", "producto_id", "mes", "clase"],
                  [(org_id, pid, m["mes"], clase) for pid, (clase, _, _) in clases.items()])


# ------------------------------------------------------------------------------------------- programador
_programador = {"activo": False}


def iniciar_programador() -> None:
    """Cálculo nocturno (03:00 de cada empresa) e incremental cada hora. Corre en un hilo del servidor."""
    if _programador["activo"]:
        return
    _programador["activo"] = True

    def ciclo():
        hechos: set = set()
        while True:
            try:                    # privacidad: bajas vencidas y copia de seguridad diaria (13.5)
                from . import privacidad
                privacidad.procesar_bajas()
                hoy_utc = datetime.now(ZoneInfo("UTC")).date()
                if ("copia", hoy_utc) not in hechos and datetime.now(ZoneInfo("America/Argentina/Buenos_Aires")).hour >= 2:
                    hechos.add(("copia", hoy_utc))
                    print(f"Retail: copia de seguridad {privacidad.respaldar().name}")
            except Exception as ex:
                print(f"Retail: copia de seguridad o bajas no disponibles ({type(ex).__name__}: {str(ex)[:160]})")
            try:
                with db.transaccion(superadmin=True) as conn:
                    empresas = db.filas(conn, "SELECT id, zona_horaria FROM organizaciones WHERE activa")
                for e in empresas:
                    ahora = datetime.now(ZoneInfo(e["zona_horaria"]))
                    clave = (e["id"], ahora.date(), ahora.hour)
                    if clave in hechos:
                        continue
                    hechos.add(clave)
                    from . import odoo_pos
                    desde = odoo_pos.sincronizar_todas(e["id"])     # primero traer lo nuevo de la caja
                    from .. import empresas
                    if empresas.toca_sincronizar(e["id"]):           # y el Panel ERP de la empresa, cada 3 horas
                        empresas.sincronizar_en_segundo_plano(e["id"])
                    if ahora.hour == 3:
                        recalcular(e["id"], tipo="nocturno")
                    elif 7 <= ahora.hour <= 22 or desde:
                        recalcular(e["id"], tipo="incremental", desde=desde)
                    from . import api_avisos
                    api_avisos.enviar_urgentes(e["id"])
                    api_avisos.enviar_resumenes(e["id"], ahora.hour, ahora.date())
            except Exception as ex:   # la base puede no estar lista todavía
                print(f"Retail: cálculo programado no disponible ({type(ex).__name__}: {str(ex)[:120]})")
            _time.sleep(300)

    threading.Thread(target=ciclo, daemon=True).start()
