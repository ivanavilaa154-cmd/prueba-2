"""Vistas por rol (predicciones, parte D): Dirección, Comercial, Sucursal, Marketing y Finanzas.

Cada vista tiene los mismos bloques: indicadores clave, avisos ordenados por plata en juego, un pronóstico con su rango de confianza,
una tabla de detalle y los atajos a la pantalla o al simulador donde se actúa. Todo sale de los mismos cálculos que el resto de la
plataforma; la vista solo elige qué mostrar a cada persona.
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException

from . import db, permisos, sesiones, suscripcion
from .api_avisos import _filtro_destino
from .api_comprar import _hoy_datos
from .api_predicciones import _feriados, calcular_flujo, inflacion_mensual, pronostico_serie, riesgo_clientes
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])

VISTAS = {
    "direccion": {"nombre": "Dirección", "roles": {"dueno"}},
    "comercial": {"nombre": "Comercial", "roles": {"dueno", "comprador"}},
    "sucursal": {"nombre": "Sucursal", "roles": {"dueno", "comprador", "encargado"}},
    "marketing": {"nombre": "Marketing", "roles": {"dueno", "comprador"}},
    "finanzas": {"nombre": "Finanzas", "roles": {"dueno"}},
}
ALERTAS = {
    "direccion": None,                                              # todas
    "comercial": ["quiebre", "sobrestock", "stock_muerto", "margen", "aumento_proveedor", "caida_a", "orden_compra", "oc_escalada",
                  "sobreventa", "vencimiento"],
    "sucursal": ["gondola", "stock_fantasma", "transferencia", "vencimiento", "quiebre", "inventario", "meta", "sobreventa", "fiado"],
    "marketing": ["caida_a", "meta", "sobrestock", "stock_muerto", "vencimiento"],
    "finanzas": ["caja", "fiado", "oc_escalada", "aumento_proveedor", "margen"],
}
ATAJOS = {
    "direccion": [("Ver pronósticos", "/pronosticos/"), ("Flujo de caja", "/finanzas/"), ("Comparar sucursales", "/sucursales/"),
                  ("Salud de los pronósticos", "/modelos/")],
    "comercial": [("Comprar y reponer", "/comprar/"), ("Plata parada", "/plata-parada/"), ("Precios", "/precios/"),
                  ("Simular una promoción", "/ventas/#promociones")],
    "sucursal": [("Comprar y reponer", "/comprar/"), ("Vencimientos y liquidaciones", "/vencimientos/"), ("Transferencias", "/transferencias/"),
                 ("Personal por turno", "/pronosticos/#afluencia")],
    "marketing": [("Simular una promoción", "/ventas/#promociones"), ("Canasta", "/ventas/#canasta"),
                  ("Clientes", "/ventas/#clientes"), ("Año y eventos", "/pronosticos/#anual")],
    "finanzas": [("Flujo de caja", "/finanzas/"), ("Riesgo de cobro", "/finanzas/#cobro"), ("Medios de pago", "/ventas/#medios"),
                 ("Proveedores", "/proveedores/")],
}
POR_DEFECTO = {"dueno": "direccion", "comprador": "comercial", "encargado": "sucursal"}


def _rol(ctx: db.Contexto) -> str:
    return "dueno" if ctx.es_superadmin else (ctx.rol or "")


def vistas_de(ctx: db.Contexto) -> list[dict]:
    rol = _rol(ctx)
    return [{"codigo": k, "nombre": v["nombre"]} for k, v in VISTAS.items() if rol in v["roles"]]


def _var(x: float, y: float) -> float | None:
    return None if not y else round((x / y - 1) * 100, 1)


def _kpi(nombre: str, valor, formato: str = "plata", detalle: str | None = None, variacion: float | None = None,
         bueno_si_sube: bool = True) -> dict:
    return {"nombre": nombre, "valor": valor, "formato": formato, "detalle": detalle, "variacion": variacion, "bueno_si_sube": bueno_si_sube}


def _suma(conn, desde: date, hasta: date, ubicacion: int | None) -> dict:
    extra = " AND ubicacion_id = %s" if ubicacion else ""
    return db.fila(conn, f"""SELECT coalesce(sum(facturacion), 0)::float f, coalesce(sum(ganancia), 0)::float g, coalesce(sum(unidades), 0)::float u,
                                    coalesce(sum(unidades_promo), 0)::float up
                             FROM agg_producto_ubicacion_dia WHERE fecha >= %s AND fecha < %s{extra}""",
                   (desde, hasta, *([ubicacion] if ubicacion else [])))


def _tickets(conn, desde: date, hasta: date, ubicacion: int | None) -> float:
    extra = " AND ubicacion_id = %s" if ubicacion else ""
    return db.fila(conn, f"SELECT coalesce(sum(tickets), 0)::float t FROM agg_ubicacion_hora WHERE fecha >= %s AND fecha < %s{extra}",
                   (desde, hasta, *([ubicacion] if ubicacion else [])))["t"]


def _pronostico(conn, hoy: date, dias: int, ubicacion: int | None, medida: str = "facturacion") -> dict:
    """Serie diaria real de los últimos 28 días y pronóstico con rango del 80 % para los próximos `dias`."""
    extra = " AND ubicacion_id = %s" if ubicacion else ""
    tabla, col = ("agg_ubicacion_hora", "tickets") if medida == "tickets" else ("agg_producto_ubicacion_dia", "facturacion")
    serie = {f["fecha"]: f["v"] for f in db.filas(conn, f"SELECT fecha, sum({col})::float v FROM {tabla} WHERE fecha >= %s AND fecha < %s{extra} "
                                                        "GROUP BY 1", (hoy - timedelta(days=400), hoy, *([ubicacion] if ubicacion else [])))}
    if not serie:
        return {"medida": medida, "puntos": [], "total": 0, "minimo": 0, "maximo": 0}
    p = pronostico_serie(serie, hoy, dias, _feriados(conn), inflacion_mensual(conn) if medida == "facturacion" else 0.0)
    puntos = [{"fecha": hoy - timedelta(days=i), "real": round(serie.get(hoy - timedelta(days=i), 0.0), 2)} for i in range(28, 0, -1)]
    puntos += [{"fecha": d["fecha"], "pronostico": d["pronostico"], "rango": [d["minimo"], d["maximo"]]} for d in p["dias"]]
    return {"medida": medida, "puntos": puntos, "total": p["total"], "minimo": p["minimo"], "maximo": p["maximo"]}


def _alertas(conn, ctx: db.Contexto, vista: str, ubicacion: int | None) -> list[dict]:
    extra, params = _filtro_destino(ctx)
    if ALERTAS[vista] is not None:
        extra += " AND a.tipo = ANY(%s)"
        params += (ALERTAS[vista],)
    if ubicacion:
        extra += " AND (a.ubicacion_id = %s OR a.ubicacion_id IS NULL)"
        params += (ubicacion,)
    filas = db.filas(conn, f"""SELECT a.id, a.tipo, a.prioridad, a.titulo, a.explicacion, a.impacto, a.tipo_impacto, a.accion, a.estado, u.nombre ubicacion
                              FROM alertas a LEFT JOIN ubicaciones u ON u.id = a.ubicacion_id
                              WHERE a.estado IN ('nueva','vista','escalada') {extra}
                              ORDER BY a.impacto DESC, array_position(ARRAY['urgente','normal','preventiva'], a.prioridad) LIMIT 40""", params)
    vistos, salida = set(), []
    for a in filas:                                                   # avisos iguales (p. ej. varias transferencias al mismo local): uno solo
        if (a["tipo"], a["titulo"]) not in vistos:
            vistos.add((a["tipo"], a["titulo"]))
            salida.append(a)
    return salida[:6]


def _ubicacion_de(conn, ctx: db.Contexto, pedida: int | None) -> dict:
    tiendas = db.filas(conn, "SELECT id, nombre FROM ubicaciones WHERE activa AND tipo <> 'deposito' ORDER BY nombre")   # la RLS deja solo las suyas
    if not tiendas:
        raise HTTPException(status_code=409, detail="No tenés sucursales asignadas.")
    elegida = next((t for t in tiendas if t["id"] == pedida), tiendas[0])
    return {"elegida": elegida, "opciones": tiendas}


# ------------------------------------------------------------------------------ cada vista
def _direccion(conn, hoy: date, costos: bool) -> dict:
    a, b = _suma(conn, hoy - timedelta(days=7), hoy, None), _suma(conn, hoy - timedelta(days=14), hoy - timedelta(days=7), None)
    pron = _pronostico(conn, hoy, 30, None)
    capital = db.fila(conn, "SELECT coalesce(sum(capital), 0)::float c, coalesce(sum(capital) FILTER (WHERE semaforo='gris' OR dias_sin_venta >= 90), 0)::float p "
                            "FROM metricas_producto_actual")
    kpis = [_kpi("Venta últimos 7 días", a["f"], variacion=_var(a["f"], b["f"]), detalle="contra los 7 días anteriores"),
            _kpi("Venta proyectada 30 días", pron["total"], detalle=f"rango 80 %: {round(pron['minimo'])} a {round(pron['maximo'])}", formato="plata_rango")]
    if costos:
        kpis += [_kpi("Margen últimos 7 días", round(a["g"] / a["f"] * 100, 1) if a["f"] else None, "pct",
                      variacion=round((a["g"] / a["f"] - b["g"] / b["f"]) * 100, 1) if a["f"] and b["f"] else None, detalle="puntos contra la semana anterior"),
                 _kpi("Plata parada", capital["p"], detalle=f"de {round(capital['c'])} en stock", bueno_si_sube=False)]
    filas = []
    for f in db.filas(conn, """SELECT u.nombre, sum(a.facturacion) FILTER (WHERE a.fecha >= %s)::float v7,
                                      sum(a.facturacion) FILTER (WHERE a.fecha < %s)::float v7a,
                                      sum(a.ganancia) FILTER (WHERE a.fecha >= %s)::float g7
                               FROM agg_producto_ubicacion_dia a JOIN ubicaciones u ON u.id = a.ubicacion_id
                               WHERE a.fecha >= %s AND a.fecha < %s GROUP BY 1 ORDER BY 2 DESC NULLS LAST""",
                      (hoy - timedelta(days=7), hoy - timedelta(days=7), hoy - timedelta(days=7), hoy - timedelta(days=14), hoy)):
        filas.append({"Sucursal": f["nombre"], "Venta 7 días": f["v7"] or 0, "Variación %": _var(f["v7"] or 0, f["v7a"] or 0),
                      **({"Margen %": round((f["g7"] or 0) / f["v7"] * 100, 1) if f["v7"] else None} if costos else {})})
    return {"kpis": kpis, "pronostico": {"titulo": "Venta de la empresa: real y próximos 30 días", **pron},
            "detalle": {"titulo": "Sucursales", "columnas": list(filas[0]) if filas else [], "filas": filas}}


def _comercial(conn, hoy: date, costos: bool) -> dict:
    riesgo = db.fila(conn, """SELECT count(*) FILTER (WHERE m.prob_quiebre >= 0.5) n, coalesce(sum(m.ventas_en_riesgo) FILTER (WHERE m.prob_quiebre >= 0.5), 0)::float v,
                                     count(*) FILTER (WHERE m.cantidad_sugerida > 0) sugeridos
                              FROM metricas_producto_actual m JOIN ubicaciones u ON u.id = m.ubicacion_id WHERE u.tipo <> 'deposito'""")
    riesgo["parada"] = db.fila(conn, "SELECT coalesce(sum(capital) FILTER (WHERE semaforo='gris' OR dias_sin_venta >= 90), 0)::float p "
                                     "FROM metricas_producto_actual")["p"]                # igual que Inicio: incluye depósitos
    a, b = _suma(conn, hoy - timedelta(days=28), hoy, None), _suma(conn, hoy - timedelta(days=56), hoy - timedelta(days=28), None)
    kpis = [_kpi("Productos con riesgo de quiebre", riesgo["n"], "numero", detalle="probabilidad de 50 % o más antes de la próxima entrega",
                 bueno_si_sube=False),
            _kpi("Venta en riesgo por quiebre", riesgo["v"], bueno_si_sube=False),
            _kpi("Venta 28 días", a["f"], variacion=_var(a["f"], b["f"]), detalle="contra los 28 días anteriores")]
    if costos:
        kpis.append(_kpi("Plata parada", riesgo["parada"], bueno_si_sube=False))
    filas = []
    for f in db.filas(conn, """SELECT coalesce(cp.nombre, c.nombre, 'Sin categoría') cat,
                                      sum(a.facturacion) FILTER (WHERE a.fecha >= %s)::float v, sum(a.facturacion) FILTER (WHERE a.fecha < %s)::float va,
                                      sum(a.ganancia) FILTER (WHERE a.fecha >= %s)::float g
                               FROM agg_producto_ubicacion_dia a JOIN productos p ON p.id = a.producto_id
                               LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
                               WHERE a.fecha >= %s AND a.fecha < %s GROUP BY 1 ORDER BY 2 DESC NULLS LAST LIMIT 12""",
                      (hoy - timedelta(days=28), hoy - timedelta(days=28), hoy - timedelta(days=28), hoy - timedelta(days=56), hoy)):
        filas.append({"Categoría": f["cat"], "Venta 28 días": f["v"] or 0, "Variación %": _var(f["v"] or 0, f["va"] or 0),
                      **({"Margen %": round((f["g"] or 0) / f["v"] * 100, 1) if f["v"] else None} if costos else {})})
    return {"kpis": kpis, "pronostico": {"titulo": "Venta total: real y próximos 30 días", **_pronostico(conn, hoy, 30, None)},
            "detalle": {"titulo": "Categorías (últimos 28 días)", "columnas": list(filas[0]) if filas else [], "filas": filas}}


def _sucursal(conn, hoy: date, ubicacion: int) -> dict:
    ayer = _suma(conn, hoy - timedelta(days=1), hoy, ubicacion)
    semana = _suma(conn, hoy - timedelta(days=8), hoy - timedelta(days=7), ubicacion)
    pron = _pronostico(conn, hoy, 14, ubicacion)
    manana = next((p for p in pron["puntos"] if p.get("fecha") == hoy + timedelta(days=1)), None) or \
        next((p for p in pron["puntos"] if "pronostico" in p), {"pronostico": 0, "rango": [0, 0]})
    m = db.fila(conn, """SELECT count(*) FILTER (WHERE prob_quiebre >= 0.5) q, count(*) FILTER (WHERE semaforo='rojo') rojos
                         FROM metricas_producto_actual WHERE ubicacion_id=%s""", (ubicacion,))
    lotes = db.fila(conn, """SELECT count(*) n FROM stock_lotes WHERE ubicacion_id=%s AND cantidad > 0 AND vencimiento BETWEEN %s AND %s""",
                    (ubicacion, hoy, hoy + timedelta(days=7)))["n"]
    kpis = [_kpi("Venta de ayer", ayer["f"], variacion=_var(ayer["f"], semana["f"]), detalle="contra el mismo día de la semana anterior"),
            _kpi("Venta esperada mañana", manana["pronostico"], "plata_rango", detalle=f"rango 80 %: {round(manana['rango'][0])} a {round(manana['rango'][1])}"),
            _kpi("Productos que se pueden quedar sin stock", m["q"], "numero", bueno_si_sube=False),
            _kpi("Lotes que vencen esta semana", lotes, "numero", bueno_si_sube=False)]
    filas = [{"Producto": f["nombre"], "Stock": f["disponible"], "Días de stock": f["dias_stock"], "Riesgo de quiebre %": round(f["prob"] * 100),
              "Sugerido": f["cantidad_sugerida"]}
             for f in db.filas(conn, """SELECT p.nombre, m.disponible::float disponible, round(m.dias_stock, 1)::float dias_stock,
                                               coalesce(m.prob_quiebre, 0)::float prob, m.cantidad_sugerida::float cantidad_sugerida
                                        FROM metricas_producto_actual m JOIN productos p ON p.id = m.producto_id
                                        WHERE m.ubicacion_id=%s AND m.prob_quiebre >= 0.3 ORDER BY m.prob_quiebre DESC, m.ventas_en_riesgo DESC NULLS LAST LIMIT 15""",
                                     (ubicacion,))]
    return {"kpis": kpis, "pronostico": {"titulo": "Venta de la sucursal: real y próximas 2 semanas", **pron},
            "detalle": {"titulo": "Qué revisar hoy en la góndola", "columnas": list(filas[0]) if filas else [], "filas": filas}}


def _marketing(conn, hoy: date) -> dict:
    a, b = _suma(conn, hoy - timedelta(days=28), hoy, None), _suma(conn, hoy - timedelta(days=56), hoy - timedelta(days=28), None)
    ta, tb = _tickets(conn, hoy - timedelta(days=28), hoy, None), _tickets(conn, hoy - timedelta(days=56), hoy - timedelta(days=28), None)
    activas = db.filas(conn, """SELECT id, nombre, tipo, desde, hasta, cardinality(productos) productos, origen FROM promociones
                               WHERE estado='activa' AND hasta >= %s ORDER BY desde DESC LIMIT 12""", (hoy,))
    kpis = [_kpi("Ticket promedio (28 días)", a["f"] / ta if ta else None, variacion=_var(a["f"] / ta if ta else 0, b["f"] / tb if tb else 0)),
            _kpi("Tickets por día", round(ta / 28), "numero", variacion=_var(ta, tb), detalle="contra los 28 días anteriores"),
            _kpi("Ventas con promoción", round(a["up"] / a["u"] * 100, 1) if a["u"] else None, "pct", detalle="de las unidades vendidas"),
            _kpi("Promociones activas", len(activas), "numero")]
    filas = [{"Promoción": p["nombre"], "Desde": p["desde"], "Hasta": p["hasta"], "Productos": p["productos"],
              "Origen": {"manual": "Manual", "liquidacion": "Liquidación", "sobrestock": "Sobrestock", "vencimiento": "Vencimiento"}.get(p["origen"], p["origen"])}
             for p in activas]
    return {"kpis": kpis, "pronostico": {"titulo": "Tráfico: tickets por día, real y próximos 30 días", **_pronostico(conn, hoy, 30, None, "tickets")},
            "detalle": {"titulo": "Promociones activas", "columnas": list(filas[0]) if filas else [], "filas": filas}}


def _finanzas(conn, ctx: db.Contexto, hoy: date) -> dict:
    if not ctx.es_superadmin and "avanzado" not in suscripcion.estado(conn, ctx.org_id)["modulos"]:
        return {"kpis": [], "bloqueado": "Tu plan no incluye Finanzas (flujo de caja y riesgo de cobro).", "pronostico": None, "detalle": None}
    f = calcular_flujo(conn, 90)
    clientes = riesgo_clientes(conn, hoy)
    en_riesgo = sum(c["en_riesgo"] for c in clientes)
    kpis = [_kpi("Saldo hoy", f["saldo_inicial"], detalle=None if f["configurado"] else "cargalo en Finanzas"),
            _kpi("Saldo en 90 días", f["saldo_final"]),
            _kpi("Primer día bajo el mínimo", f["primer_dia_bajo_minimo"], "fecha", detalle="ninguno en 90 días" if not f["primer_dia_bajo_minimo"] else None),
            _kpi("Cuentas corrientes en riesgo", en_riesgo, detalle=f"de {round(sum(float(c['saldo']) for c in clientes))} adeudado", bueno_si_sube=False)]
    puntos = [{"fecha": d["fecha"], "pronostico": d["saldo"], "rango": [d["saldo_min"], d["saldo_max"]]} for d in f["linea"]]
    filas = [{"Cliente": c["nombre"], "Saldo": c["saldo"], "Probabilidad de no cobrar %": round(c["prob_no_cobro"] * 100), "En riesgo": c["en_riesgo"],
              "Qué hacer": c["accion"]} for c in clientes[:10]]
    return {"kpis": kpis, "pronostico": {"titulo": "Saldo de caja proyectado a 90 días", "medida": "saldo", "puntos": puntos,
                                         "total": f["saldo_final"], "minimo": puntos[-1]["rango"][0] if puntos else 0,
                                         "maximo": puntos[-1]["rango"][1] if puntos else 0, "linea_minimo": f["minimo_aceptable"]},
            "detalle": {"titulo": "Cuentas corrientes con más riesgo", "columnas": list(filas[0]) if filas else [], "filas": filas}}


@api.get("/vistas")
def lista(ctx: db.Contexto = Depends(sesiones.contexto)):
    rol = _rol(ctx)
    return respuesta({"vistas": vistas_de(ctx), "por_defecto": POR_DEFECTO.get(rol)})


@api.get("/vistas/{vista}")
def vista(vista: str, ubicacion_id: int | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    if not ctx.org_id:
        raise HTTPException(status_code=409, detail="Elegí una empresa para trabajar.")
    if vista not in VISTAS:
        raise HTTPException(status_code=404, detail="Esa vista no existe.")
    if _rol(ctx) not in VISTAS[vista]["roles"]:
        raise HTTPException(status_code=403, detail=f"Tu rol no tiene la vista {VISTAS[vista]['nombre']}.")
    costos = permisos.puede(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        ubic = None
        if vista == "sucursal":
            ubic = _ubicacion_de(conn, ctx, ubicacion_id)
            cuerpo = _sucursal(conn, hoy, ubic["elegida"]["id"])
        elif vista == "direccion":
            cuerpo = _direccion(conn, hoy, costos)
        elif vista == "comercial":
            cuerpo = _comercial(conn, hoy, costos)
        elif vista == "marketing":
            cuerpo = _marketing(conn, hoy)
        else:
            cuerpo = _finanzas(conn, ctx, hoy)
        alertas = _alertas(conn, ctx, vista, ubic["elegida"]["id"] if ubic else None)
        return respuesta({"vista": vista, "nombre": VISTAS[vista]["nombre"], "hoy": hoy, "vistas": vistas_de(ctx), "ubicacion": ubic,
                          "alertas": alertas, "atajos": [{"etiqueta": e, "ruta": r} for e, r in ATAJOS[vista]], **cuerpo})
