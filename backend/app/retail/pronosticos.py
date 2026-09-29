"""Pronósticos con rango de confianza y su medición de error (predicciones con IA, parte A).

- Cada noche se guarda lo pronosticado para los 7 días siguientes de cada producto × sucursal, con su rango del 80 %.
- A los 7 días se compara con lo vendido: WAPE (error ponderado por volumen), sesgo (si sobreestima o subestima) y cobertura
  del rango (qué % de las veces lo real cayó dentro). Los períodos con quiebre de stock no cuentan: ahí se vendió menos porque no
  había, no porque el pronóstico estuviera mal.
- Para no esperar semanas, la primera vez se hace una «prueba sobre el pasado»: se recalcula el pronóstico de las últimas 8 semanas
  con los datos que había en cada fecha (mismo modelo: venta diaria con stock, ponderada, con factores de día, mes y feriados).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from . import calculos as C
from . import db

SEMANAS_PRUEBA = 8


def modelo(ventas: dict[date, float], cierres: dict[date, float], hoy: date, feriados: set[date], referencia=None,
           factores_ref=None) -> dict:
    """Pronóstico de 7 días y su rango, usando solo datos anteriores a `hoy`."""
    vs = {d: u for d, u in ventas.items() if d < hoy}
    cs = {d: s for d, s in cierres.items() if d < hoy}
    primera = min(list(vs) + list(cs)) if (vs or cs) else None
    sin = C.dias_sin_stock(vs, cs, hoy - timedelta(days=400), hoy - timedelta(days=1))
    alta = primera if primera and (hoy - primera).days < 28 else None
    r = C.venta_promedio_diaria(vs, sin, hoy, referencia=referencia, desde_alta=alta)
    base = C.vpd_ponderada(vs, sin, hoy)
    if r.confianza == "baja" or base is None:
        base = r.vpd
    factores = C.calcular_factores(vs, sin, hoy, feriados, factores_ref, desde=primera)
    pron = C.pronostico(base, factores, hoy, 7, feriados)
    p7 = sum(pron)
    desvio = C.desvio_semanal(C.semanas_con_stock(vs, sin, hoy), base * 7)
    minimo, maximo = C.banda(p7, desvio, 7)
    return {"pronostico": p7, "minimo": minimo, "maximo": maximo, "desvio_7d": desvio}


def registrar(conn, org_id: int, hoy: date, filas: list[tuple], origen: str = "diario") -> None:
    """filas: (producto_id, ubicacion_id, pronóstico, mínimo, máximo[, factor de corrección aplicado])."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM pronosticos_registro WHERE org_id=%s AND fecha=%s", (org_id, hoy))
    db.copiar(conn, "pronosticos_registro", ["org_id", "producto_id", "ubicacion_id", "fecha", "pronostico", "minimo", "maximo", "origen", "factor"],
              [(org_id, f[0], f[1], hoy, round(f[2], 3), round(f[3], 3), round(f[4], 3), origen, round(f[5], 4) if len(f) > 5 else 1)
               for f in filas])


def prueba_sobre_el_pasado(conn, org_id: int, hoy: date, semanas: int = SEMANAS_PRUEBA) -> int:
    """Rellena el registro de las últimas `semanas` semanas recalculando el pronóstico con los datos de cada fecha."""
    ya = {f["fecha"] for f in db.filas(conn, "SELECT DISTINCT fecha FROM pronosticos_registro WHERE org_id=%s AND fecha < %s", (org_id, hoy))}
    fechas = [hoy - timedelta(days=7 * k) for k in range(1, semanas + 1) if hoy - timedelta(days=7 * k) not in ya]
    if not fechas:
        return 0
    desde = min(fechas) - timedelta(days=400)
    ventas: dict = defaultdict(dict)
    for f in db.filas(conn, """SELECT a.producto_id, a.ubicacion_id, a.fecha, sum(a.unidades) u FROM agg_producto_ubicacion_dia a
                               JOIN ubicaciones u ON u.id = a.ubicacion_id WHERE a.org_id=%s AND a.fecha >= %s AND a.fecha < %s
                               AND u.tipo <> 'deposito' GROUP BY 1, 2, 3""", (org_id, desde, hoy)):
        ventas[(f["producto_id"], f["ubicacion_id"])][f["fecha"]] = float(f["u"])
    cierres: dict = defaultdict(dict)
    for f in db.filas(conn, "SELECT producto_id, ubicacion_id, fecha, stock_cierre FROM stock_diario WHERE org_id=%s AND fecha >= %s AND fecha < %s",
                      (org_id, desde, hoy)):
        cierres[(f["producto_id"], f["ubicacion_id"])][f["fecha"]] = float(f["stock_cierre"])
    feriados = {f["fecha"] for f in db.filas(conn, "SELECT fecha FROM calendario WHERE tipo='feriado' AND (org_id IS NULL OR org_id=%s)", (org_id,))}
    total = 0
    for t in fechas:
        filas = []
        for (pid, uid), vs in ventas.items():
            if not any(d < t for d in vs):
                continue
            m = modelo(vs, cierres.get((pid, uid), {}), t, feriados)
            filas.append((pid, uid, m["pronostico"], m["minimo"], m["maximo"]))
        registrar(conn, org_id, t, filas, "prueba_pasado")
        total += len(filas)
    return total


def evaluados(conn, hoy: date, semanas: int = SEMANAS_PRUEBA) -> list[dict]:
    """Pronósticos ya vencidos con lo que se vendió en su semana y los días sin stock. Se traen el registro, la venta diaria y los
    días sin stock del período de una vez y se cruzan en memoria (rápido)."""
    hasta, desde = hoy - timedelta(days=7), hoy - timedelta(days=7 * (semanas + 1))
    registro = db.filas(conn, """SELECT r.producto_id, r.ubicacion_id, r.fecha, r.origen, r.pronostico::float pron, r.minimo::float mi,
                                        r.maximo::float ma, r.factor::float factor
                                 FROM pronosticos_registro r WHERE r.fecha <= %s AND r.fecha > %s""", (hasta, desde))
    if not registro:
        return []
    fin = max(r["fecha"] for r in registro) + timedelta(days=6)
    inicio = min(r["fecha"] for r in registro)
    venta: dict = defaultdict(float)
    for f in db.filas(conn, """SELECT producto_id, ubicacion_id, fecha, sum(unidades)::float u FROM agg_producto_ubicacion_dia
                               WHERE fecha BETWEEN %s AND %s GROUP BY 1, 2, 3""", (inicio, fin)):
        venta[(f["producto_id"], f["ubicacion_id"], f["fecha"])] = f["u"]
    sin_stock = {(f["producto_id"], f["ubicacion_id"], f["fecha"]) for f in db.filas(
        conn, "SELECT producto_id, ubicacion_id, fecha FROM stock_diario WHERE NOT con_stock AND fecha BETWEEN %s AND %s", (inicio, fin))}
    info = {f["id"]: f for f in db.filas(conn, """
        SELECT p.id, p.nombre, p.codigo_interno, coalesce(cp.nombre, c.nombre, 'Sin categoría') categoria, coalesce(c.padre_id, c.id) categoria_id,
               (SELECT precio FROM precios x WHERE x.producto_id = p.id AND x.ubicacion_id IS NULL AND x.canal_id IS NULL
                ORDER BY x.desde DESC LIMIT 1)::float precio
        FROM productos p LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
        WHERE p.id = ANY(%s)""", (list({r["producto_id"] for r in registro}),))}
    ubic = {f["id"]: f["nombre"] for f in db.filas(conn, "SELECT id, nombre FROM ubicaciones")}
    filas = []
    for r in registro:
        pid, uid, d0 = r["producto_id"], r["ubicacion_id"], r["fecha"]
        dias = [d0 + timedelta(days=i) for i in range(7)]
        p = info.get(pid, {})
        filas.append({**r, "vendido": sum(venta.get((pid, uid, d), 0.0) for d in dias),
                      "dias_sin": sum(1 for d in dias if (pid, uid, d) in sin_stock), "nombre": p.get("nombre"),
                      "codigo_interno": p.get("codigo_interno"), "categoria": p.get("categoria", "Sin categoría"),
                      "categoria_id": p.get("categoria_id"), "precio": p.get("precio"), "ubicacion": ubic.get(uid)})
    return filas


# Corrección del sesgo: si una categoría en una sucursal viene sobreestimando, sus pronósticos se ajustan (con topes y de a poco).
SESGO_PESO = 30            # cuántas semanas-producto hacen falta para confiar a medias en lo medido
SESGO_TOPES = (0.8, 1.25)


def factores_sesgo(conn, hoy: date) -> dict:
    """{(categoría, sucursal): factor}. factor = vendido ÷ pronóstico sin corregir de las últimas semanas (sin semanas con quiebre),
    acercado a 1 según cuánta evidencia hay: 1 + (razón − 1) × n ÷ (n + SESGO_PESO), con topes 0,8 y 1,25."""
    g: dict = defaultdict(lambda: [0.0, 0.0, 0])
    for f in evaluados(conn, hoy):
        if f["dias_sin"] > 1:
            continue
        x = g[(f["categoria_id"], f["ubicacion_id"])]
        x[0] += f["vendido"]
        x[1] += f["pron"] / (f["factor"] or 1)
        x[2] += 1
    salida = {}
    for clave, (real, pron, n) in g.items():
        if n < 8 or pron <= 0 or real <= 0:
            continue
        factor = 1 + (real / pron - 1) * n / (n + SESGO_PESO)
        salida[clave] = min(SESGO_TOPES[1], max(SESGO_TOPES[0], factor))
    return salida


def salud(conn, hoy: date, semanas: int = SEMANAS_PRUEBA) -> dict:
    """Error de los pronósticos ya vencidos (los que cubren semanas completas hasta ayer)."""
    filas = evaluados(conn, hoy, semanas)
    if not filas:
        return {"global": {"wape": None, "sesgo": None, "cobertura": None, "n": 0, "real": 0}, "semanas": [], "por_categoria": [],
                "por_ubicacion": [], "peores": [], "evaluados": 0, "excluidos_por_quiebre": 0, "origen_prueba": 0, "correcciones": []}
    validas = [f for f in filas if f["dias_sin"] <= 1]
    excluidas = len(filas) - len(validas)

    def resumen(grupo):
        e = C.error_pronostico([(f["pron"], f["vendido"]) for f in grupo])
        dentro = sum(1 for f in grupo if f["mi"] - 0.5 <= f["vendido"] <= f["ma"] + 0.5)
        return {**e, "cobertura": dentro / len(grupo) if grupo else None}

    def por(clave):
        g = defaultdict(list)
        for f in validas:
            g[f[clave]].append(f)
        return sorted(({clave: k, **resumen(v)} for k, v in g.items() if sum(x["vendido"] for x in v) > 0), key=lambda x: -x["real"])

    semanal = sorted(({"semana": k, **resumen(v)} for k, v in _grupo(validas, "fecha").items()), key=lambda x: x["semana"])
    por_producto = defaultdict(list)
    for f in validas:
        por_producto[(f["producto_id"], f["nombre"], f["codigo_interno"], f["ubicacion"])].append(f)
    peores = []
    for (pid, nombre, codigo, ubic), v in por_producto.items():
        err = sum(abs(x["vendido"] - x["pron"]) for x in v) / len(v)
        precio = v[0]["precio"] or 0
        peores.append({"producto_id": pid, "nombre": nombre, "codigo_interno": codigo, "ubicacion": ubic, "error_semanal": round(err, 1),
                       "error_pesos": round(err * precio, 2), "pronostico_semanal": round(sum(x["pron"] for x in v) / len(v), 1),
                       "real_semanal": round(sum(x["vendido"] for x in v) / len(v), 1),
                       "sesgo": (sum(x["pron"] - x["vendido"] for x in v) / max(sum(x["vendido"] for x in v), 1))})
    peores.sort(key=lambda x: -x["error_pesos"])
    nombres_cat = {f["categoria_id"]: f["categoria"] for f in filas}
    nombres_ub = {f["ubicacion_id"]: f["ubicacion"] for f in filas}
    correcciones = sorted(({"categoria": nombres_cat.get(c), "ubicacion": nombres_ub.get(u), "factor": round(v, 3)}
                           for (c, u), v in factores_sesgo(conn, hoy).items() if abs(v - 1) >= 0.02), key=lambda x: x["factor"])
    return {"correcciones": correcciones, "global": resumen(validas), "semanas": semanal, "por_categoria": por("categoria")[:20], "por_ubicacion": por("ubicacion"),
            "peores": peores[:20], "evaluados": len(validas), "excluidos_por_quiebre": excluidas,
            "origen_prueba": sum(1 for f in validas if f["origen"] == "prueba_pasado")}


def _grupo(filas, clave):
    g = defaultdict(list)
    for f in filas:
        g[f[clave]].append(f)
    return g
