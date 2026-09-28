"""Análisis de la Fase 2: rentabilidad del inventario (10.6), medios de pago y fiado (10.8), proveedores (10.11) y metas (10.13).

Fórmulas:
- GMROI = ganancia bruta del período ÷ inventario promedio a costo. Rotación anual = costo de lo vendido ÷ inventario promedio
  × 365 ÷ días del período. Días de inventario = 365 ÷ rotación.
- Costo real de un medio de pago = comisión % (configurable) × lo cobrado + costo financiero del plazo de acreditación
  (tasa mensual configurable, 3 % por defecto, prorrateada por día).
- Nivel de servicio del proveedor = unidades recibidas ÷ pedidas; líneas completas ÷ líneas; puntualidad = recepciones hasta la
  fecha esperada ÷ recepciones.
- Proyección de cierre de mes = lo vendido + para cada día que falta: venta diaria base × factor del día de la semana
  × factor de inicio de mes (ambos medidos en las últimas 8 semanas / 3 meses).
"""
from __future__ import annotations

import calendar
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import calculos as C
from . import db, permisos, sesiones
from .api_comprar import _hoy_datos, lista_ids
from .api_plata import estado_stock, parametro, red_de_venta
from .api_ventas import periodo
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])
NOMBRES_MEDIOS = {"efectivo": "Efectivo", "debito": "Débito", "credito": "Crédito", "qr": "QR / billetera", "transferencia": "Transferencia",
                  "cuenta_corriente": "Cuenta corriente", "plataforma": "Cobrado por la plataforma"}


# ------------------------------------------------------------------------------ 10.6 rentabilidad del inventario
@api.get("/ventas/rentabilidad")
def rentabilidad(nivel: str = "producto", dias: int = 90, ubicaciones: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    if nivel not in ("producto", "categoria", "proveedor", "ubicacion"):
        raise HTTPException(status_code=400, detail="Nivel no válido.")
    dias = max(28, min(dias, 365))
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        ubic = lista_ids(ubicaciones)
        clave = {"producto": "p.id::text", "categoria": "coalesce(cp.nombre, c.nombre, 'Sin categoría')",
                 "proveedor": "coalesce(pr.razon_social, 'Sin proveedor')", "ubicacion": "u.nombre"}[nivel]
        nombre = {"producto": "max(p.nombre)", "categoria": clave, "proveedor": clave, "ubicacion": clave}[nivel]
        filas = db.filas(conn, f"""
            WITH ventas AS (
                SELECT producto_id, ubicacion_id, sum(ganancia) ganancia, sum(costo) costo_vendido, sum(facturacion) facturacion
                FROM agg_producto_ubicacion_dia WHERE fecha > %(h)s - %(d)s AND fecha <= %(h)s AND (%(todas)s OR ubicacion_id = ANY(%(u)s)) GROUP BY 1, 2),
            stock AS (
                SELECT producto_id, ubicacion_id, avg(greatest(stock_cierre, 0)) promedio
                FROM stock_diario WHERE fecha > %(h)s - %(d)s AND fecha <= %(h)s AND (%(todas)s OR ubicacion_id = ANY(%(u)s)) GROUP BY 1, 2),
            base AS (
                SELECT coalesce(v.producto_id, s.producto_id) producto_id, coalesce(v.ubicacion_id, s.ubicacion_id) ubicacion_id,
                       coalesce(v.ganancia, 0) ganancia, coalesce(v.costo_vendido, 0) costo_vendido, coalesce(v.facturacion, 0) facturacion,
                       coalesce(s.promedio, 0) promedio
                FROM ventas v FULL JOIN stock s ON s.producto_id = v.producto_id AND s.ubicacion_id = v.ubicacion_id)
            SELECT {clave} AS clave, {nombre} AS nombre, sum(b.ganancia) ganancia, sum(b.costo_vendido) costo_vendido, sum(b.facturacion) facturacion,
                   sum(b.promedio * coalesce(pp.costo, 0)) inventario
            FROM base b JOIN productos p ON p.id = b.producto_id JOIN ubicaciones u ON u.id = b.ubicacion_id
            LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
            LEFT JOIN LATERAL (SELECT costo, proveedor_id FROM producto_proveedores x WHERE x.producto_id = p.id ORDER BY principal DESC LIMIT 1) pp ON true
            LEFT JOIN proveedores pr ON pr.id = pp.proveedor_id
            GROUP BY 1""", {"h": hoy, "d": dias, "todas": not ubic, "u": ubic or [0]})
        salida = []
        for f in filas:
            inv = f["inventario"] or Decimal(0)
            gm = C.gmroi(f["ganancia"], inv)
            rot = C.rotacion_anual(f["costo_vendido"], inv, dias)
            salida.append({"clave": f["clave"], "nombre": f["nombre"], "ganancia": f["ganancia"], "facturacion": f["facturacion"],
                           "inventario_promedio": inv.quantize(Decimal("0.01")), "gmroi": None if gm is None else round(float(gm), 3),
                           "rotacion": None if rot is None else round(float(rot), 2),
                           "dias_inventario": round(365 / float(rot), 1) if rot else None})
        total_g = sum((f["ganancia"] for f in filas), Decimal(0))
        total_i = sum((f["inventario"] or 0 for f in filas), Decimal(0))
        total_c = sum((f["costo_vendido"] for f in filas), Decimal(0))
        rot_t = C.rotacion_anual(total_c, total_i, dias)
        return respuesta({"dias": dias, "nivel": nivel, "filas": sorted(salida, key=lambda x: -(x["ganancia"] or 0)),
                          "total": {"ganancia": total_g, "inventario_promedio": total_i.quantize(Decimal("0.01")),
                                    "gmroi": round(float(C.gmroi(total_g, total_i)), 3) if total_i else None,
                                    "rotacion": round(float(rot_t), 2) if rot_t else None, "dias_inventario": round(365 / float(rot_t), 1) if rot_t else None}})


# ------------------------------------------------------------------------------ 10.8 medios de pago y fiado
def _comisiones(conn) -> dict:
    valor = parametro(conn, "comisiones_medios") or {}
    return valor if isinstance(valor, dict) else json.loads(valor)


@api.get("/ventas/medios")
def medios_de_pago(periodo_: str | None = Query(None, alias="periodo"), desde: date | None = None, hasta: date | None = None,
                   ubicaciones: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        d, h, _, _, etiqueta = periodo(conn, periodo_, desde, hasta)
        ubic = lista_ids(ubicaciones)
        filas = db.filas(conn, """
            SELECT p.medio, u.nombre ubicacion, ca.nombre canal, sum(p.monto) monto, count(DISTINCT p.ticket_id) tickets, sum(p.comision_estimada) comision_registrada
            FROM pagos p JOIN tickets t ON t.id = p.ticket_id JOIN ubicaciones u ON u.id = p.ubicacion_id JOIN canales ca ON ca.id = t.canal_id
            JOIN organizaciones o ON o.id = t.org_id
            WHERE t.estado <> 'anulado' AND (t.fecha_hora AT TIME ZONE o.zona_horaria)::date BETWEEN %s AND %s AND (%s OR p.ubicacion_id = ANY(%s))
            GROUP BY 1, 2, 3""", (d, h, not ubic, ubic or [0]))
        cfg = _comisiones(conn)
        tasa_mensual = Decimal(str(parametro(conn, "tasa_financiera_mensual") or "0.03"))
        ganancia = db.fila(conn, "SELECT coalesce(sum(ganancia), 0) g FROM agg_producto_ubicacion_dia WHERE fecha BETWEEN %s AND %s AND (%s OR ubicacion_id = ANY(%s))",
                           (d, h, not ubic, ubic or [0]))["g"]
        por_medio: dict = defaultdict(lambda: {"monto": Decimal(0), "tickets": 0, "comision_registrada": Decimal(0)})
        por_ubicacion: dict = defaultdict(lambda: defaultdict(Decimal))
        por_canal: dict = defaultdict(lambda: defaultdict(Decimal))
        for f in filas:
            m = por_medio[f["medio"]]
            m["monto"] += f["monto"]
            m["tickets"] += f["tickets"]
            m["comision_registrada"] += f["comision_registrada"] or 0
            por_ubicacion[f["ubicacion"]][f["medio"]] += f["monto"]
            por_canal[f["canal"]][f["medio"]] += f["monto"]
        total = sum((m["monto"] for m in por_medio.values()), Decimal(0))
        medios = []
        for medio, m in por_medio.items():
            c = cfg.get(medio, {})
            comision = Decimal(str(c.get("comision", 0))) * m["monto"] if c else m["comision_registrada"]
            plazo = int(c.get("acreditacion_dias", 0)) if c else 0
            financiero = m["monto"] * tasa_mensual / 30 * plazo
            costo = (comision + financiero).quantize(Decimal("0.01"))
            medios.append({"medio": medio, "nombre": NOMBRES_MEDIOS.get(medio, medio), "monto": m["monto"], "tickets": m["tickets"],
                           "participacion": float(m["monto"] / total) if total else 0, "comision_pct": float(c.get("comision", 0)) if c else None,
                           "acreditacion_dias": plazo, "costo": costo, "costo_pct": float(costo / m["monto"]) if m["monto"] else 0,
                           "impacto_margen_pct": float(costo / ganancia) if ganancia else None})
        costo_total = sum((x["costo"] for x in medios), Decimal(0))

        def tabla(dic):
            return [{"nombre": k, "total": sum(v.values(), Decimal(0)), **{m: v.get(m, Decimal(0)) for m in NOMBRES_MEDIOS}} for k, v in sorted(dic.items())]
        return respuesta({"periodo": {"desde": d, "hasta": h, "etiqueta": etiqueta}, "total": total, "costo_total": costo_total,
                          "ganancia": ganancia if permisos.puede(ctx, "ver_costos") else None,
                          "impacto_margen_pct": float(costo_total / ganancia) if ganancia else None, "tasa_financiera_mensual": tasa_mensual,
                          "medios": sorted(medios, key=lambda x: -x["monto"]), "por_ubicacion": tabla(por_ubicacion), "por_canal": tabla(por_canal)})


@api.get("/config/medios")
def ver_config_medios(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        return respuesta(_comisiones(conn))


class ComisionMedio(BaseModel):
    medio: str
    comision: float = Field(ge=0, le=0.5)
    acreditacion_dias: int = Field(ge=0, le=120)


@api.put("/config/medios")
def configurar_medios(datos: list[ComisionMedio], request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    with db.transaccion(ctx) as conn:
        cfg = _comisiones(conn)
        for m in datos:
            if m.medio not in NOMBRES_MEDIOS:
                raise HTTPException(status_code=400, detail=f"Medio no válido: {m.medio}")
            cfg[m.medio] = {"comision": m.comision, "acreditacion_dias": m.acreditacion_dias}
        with conn.cursor() as cur:
            cur.execute("INSERT INTO parametros (org_id, clave, valor) VALUES (%s,'comisiones_medios',%s) ON CONFLICT (org_id, clave) "
                        "DO UPDATE SET valor=EXCLUDED.valor, updated_at=now()", (ctx.org_id, json.dumps(cfg)))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "modificar", "comisiones_medios", None, cfg, sesiones.ip_de(request))
    return respuesta(cfg)


def saldos_fiado(conn, hoy: date) -> list[dict]:
    """Saldo por cliente y antigüedad de la deuda: los pagos cancelan primero las compras más viejas."""
    movs = db.filas(conn, """SELECT c.id, c.nombre, c.identificador, m.fecha, m.tipo, m.monto, m.vencimiento
                             FROM cuentas_clientes m JOIN clientes c ON c.id = m.cliente_id ORDER BY c.id, m.fecha, m.id""")
    clientes: dict = {}
    for m in movs:
        c = clientes.setdefault(m["id"], {"cliente_id": m["id"], "nombre": m["nombre"], "identificador": m["identificador"], "compras": [],
                                          "pagado": Decimal(0), "ultimo_pago": None})
        if m["tipo"] == "compra":
            c["compras"].append([m["fecha"], m["vencimiento"] or m["fecha"] + timedelta(days=30), m["monto"]])
        else:
            c["pagado"] += -m["monto"]
            if m["tipo"] == "pago":
                c["ultimo_pago"] = m["fecha"]
    salida = []
    for c in clientes.values():
        resto = c["pagado"]
        tramos = {"0_30": Decimal(0), "31_60": Decimal(0), "61_90": Decimal(0), "mas_90": Decimal(0)}
        vencido = Decimal(0)
        for fecha, venc, monto in c["compras"]:
            pagado = min(resto, monto)
            resto -= pagado
            pendiente = monto - pagado
            if pendiente <= 0:
                continue
            antig = (hoy - fecha).days
            tramos["0_30" if antig <= 30 else "31_60" if antig <= 60 else "61_90" if antig <= 90 else "mas_90"] += pendiente
            if venc < hoy:
                vencido += pendiente
        saldo = sum(tramos.values(), Decimal(0))
        if saldo > 0:
            salida.append({k: v for k, v in c.items() if k != "compras"} | {"saldo": saldo, "vencido": vencido, "tramos": tramos})
    return sorted(salida, key=lambda x: -x["vencido"])


@api.get("/cuentas-corrientes")
def cuentas_corrientes(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        clientes = saldos_fiado(conn, hoy)
        tramos = defaultdict(Decimal)
        for c in clientes:
            for k, v in c["tramos"].items():
                tramos[k] += v
        return respuesta({"clientes": clientes, "total": sum((c["saldo"] for c in clientes), Decimal(0)),
                          "vencido": sum((c["vencido"] for c in clientes), Decimal(0)), "tramos": tramos})


# ------------------------------------------------------------------------------ 10.11 proveedores
@api.get("/proveedores/analisis")
def proveedores_analisis(dias: int = 180, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        desde = hoy - timedelta(days=max(30, min(dias, 400)))
        base = {p["id"]: p for p in db.filas(conn, """SELECT id, razon_social, cuit, email_oc, telefono, dias_visita, demora_entrega_dias,
                                                          pedido_minimo_monto, pedido_minimo_bultos, condiciones_pago, activo FROM proveedores ORDER BY razon_social""")}
        servicio = {f["proveedor_id"]: f for f in db.filas(conn, """
            SELECT o.proveedor_id, sum(l.cantidad) pedidas, sum(least(l.cantidad_recibida, l.cantidad)) recibidas, count(*) lineas,
                   count(*) FILTER (WHERE l.cantidad_recibida >= l.cantidad) completas, count(DISTINCT o.id) ordenes
            FROM ordenes_compra o JOIN ordenes_compra_lineas l ON l.orden_id = o.id
            WHERE o.estado IN ('recibida', 'recibida_parcial') AND o.created_at >= %s GROUP BY 1""", (desde,))}
        puntual = {f["proveedor_id"]: f for f in db.filas(conn, """
            SELECT o.proveedor_id, count(*) recepciones, count(*) FILTER (WHERE (r.fecha AT TIME ZONE og.zona_horaria)::date <= o.fecha_esperada) a_tiempo,
                   avg(greatest(0, (r.fecha AT TIME ZONE og.zona_horaria)::date - o.fecha_esperada)) atraso_promedio
            FROM recepciones r JOIN ordenes_compra o ON o.id = r.orden_id JOIN organizaciones og ON og.id = r.org_id
            WHERE o.fecha_esperada IS NOT NULL AND r.fecha >= %s GROUP BY 1""", (desde,))}
        red = red_de_venta(conn)
        sobre, muerto = int(parametro(conn, "umbral_sobrestock_dias")), int(parametro(conn, "umbral_muerto_dias"))
        plata = defaultdict(Decimal)
        for m in db.filas(conn, """SELECT m.producto_id, m.proveedor_id, u.tipo tipo_ubicacion, m.disponible, m.dias_stock, m.dias_sin_venta, m.capital
                                   FROM metricas_producto_actual m JOIN ubicaciones u ON u.id = m.ubicacion_id WHERE m.proveedor_id IS NOT NULL"""):
            if estado_stock(m, sobre, muerto, red) in ("sobrestock", "muerto"):
                plata[m["proveedor_id"]] += m["capital"] or 0
        resultado = {f["proveedor_id"]: f for f in db.filas(conn, """
            WITH prov AS (SELECT DISTINCT ON (producto_id) producto_id, proveedor_id, costo FROM producto_proveedores ORDER BY producto_id, principal DESC)
            SELECT pv.proveedor_id, sum(a.ganancia) ganancia, sum(a.facturacion) facturacion, sum(a.costo) costo_vendido
            FROM agg_producto_ubicacion_dia a JOIN prov pv ON pv.producto_id = a.producto_id
            WHERE a.fecha > %s - 90 AND a.fecha <= %s GROUP BY 1""", (hoy, hoy))}
        inventario = {f["proveedor_id"]: f["inv"] for f in db.filas(conn, """
            WITH prov AS (SELECT DISTINCT ON (producto_id) producto_id, proveedor_id, costo FROM producto_proveedores ORDER BY producto_id, principal DESC)
            SELECT pv.proveedor_id, sum(s.promedio * coalesce(pv.costo, 0)) inv
            FROM (SELECT producto_id, ubicacion_id, avg(greatest(stock_cierre, 0)) promedio FROM stock_diario WHERE fecha > %s - 90 GROUP BY 1, 2) s
            JOIN prov pv ON pv.producto_id = s.producto_id GROUP BY 1""", (hoy,))}
        merma = {f["proveedor_id"]: f["costo"] for f in db.filas(conn, """
            WITH prov AS (SELECT DISTINCT ON (producto_id) producto_id, proveedor_id, costo FROM producto_proveedores ORDER BY producto_id, principal DESC)
            SELECT pv.proveedor_id, -sum(m.cantidad * coalesce(m.costo_unitario, pv.costo, 0)) costo
            FROM movimientos_stock m JOIN prov pv ON pv.producto_id = m.producto_id
            WHERE m.tipo IN ('merma', 'vencimiento') AND m.fecha >= %s - 90 GROUP BY 1""", (hoy,))}
        costos = _evolucion_costos(conn, hoy)
        salida = []
        for pid, p in base.items():
            s, pu, r = servicio.get(pid), puntual.get(pid), resultado.get(pid, {})
            gm = C.gmroi(r.get("ganancia") or Decimal(0), inventario.get(pid) or Decimal(0))
            salida.append(p | {
                "servicio_unidades": float(s["recibidas"] / s["pedidas"]) if s and s["pedidas"] else None,
                "servicio_lineas": s["completas"] / s["lineas"] if s and s["lineas"] else None, "ordenes": s["ordenes"] if s else 0,
                "puntualidad": pu["a_tiempo"] / pu["recepciones"] if pu and pu["recepciones"] else None,
                "atraso_promedio_dias": float(pu["atraso_promedio"]) if pu and pu["atraso_promedio"] is not None else None,
                "ganancia_90d": r.get("ganancia") or Decimal(0), "facturacion_90d": r.get("facturacion") or Decimal(0),
                "merma_90d": merma.get(pid) or Decimal(0), "plata_parada": plata.get(pid, Decimal(0)),
                "gmroi": None if gm is None else round(float(gm), 3), "costos": costos.get(pid),
                "sin_configurar": [x for x, falta in (("días de visita", not p["dias_visita"]), ("demora de entrega", p["demora_entrega_dias"] is None),
                                                      ("email para OC", not p["email_oc"])) if falta]})
        return respuesta({"desde": desde, "proveedores": sorted(salida, key=lambda x: -(x["ganancia_90d"] or 0))})


def _evolucion_costos(conn, hoy: date) -> dict:
    """Por proveedor, variación de su costo en 12 meses (promedio ponderado de sus productos, con los costos de cada recepción)
    contra la inflación del mismo período."""
    inicio = (hoy.replace(day=1) - timedelta(days=365)).replace(day=1)
    filas = db.filas(conn, """
        SELECT r.proveedor_id, l.producto_id, date_trunc('month', r.fecha)::date mes, avg(l.costo) costo, sum(l.cantidad) unidades
        FROM recepciones r JOIN recepciones_lineas l ON l.recepcion_id = r.id
        WHERE r.fecha >= %s AND l.costo IS NOT NULL AND r.proveedor_id IS NOT NULL GROUP BY 1, 2, 3""", (inicio,))
    indice = {f["periodo"]: f["indice"] for f in db.filas(conn, "SELECT periodo, indice FROM indice_precios WHERE periodo >= %s", (inicio,))}
    por_prov: dict = defaultdict(lambda: defaultdict(dict))
    for f in filas:
        por_prov[f["proveedor_id"]][f["producto_id"]][f["mes"]] = (f["costo"], f["unidades"])
    salida = {}
    for prov, productos in por_prov.items():
        variaciones, pesos = [], []
        primero = ultimo = None
        for meses in productos.values():
            ms = sorted(meses)
            if len(ms) < 2 or (ms[-1] - ms[0]).days < 120:
                continue
            (c0, _), (c1, u1) = meses[ms[0]], meses[ms[-1]]
            if c0:
                variaciones.append(float(c1 / c0 - 1))
                pesos.append(float(u1))
                primero = min(primero or ms[0], ms[0])
                ultimo = max(ultimo or ms[-1], ms[-1])
        if not variaciones:
            continue
        var = sum(v * w for v, w in zip(variaciones, pesos)) / sum(pesos)
        inflacion = None
        i0, i1 = indice.get(primero), indice.get(min(ultimo, max(indice)) if indice else None)
        if i0 and i1:
            inflacion = float(i1 / i0 - 1)
        salida[prov] = {"desde": primero, "hasta": ultimo, "variacion": round(var, 4), "inflacion": None if inflacion is None else round(inflacion, 4),
                        "contra_inflacion": None if inflacion is None else round((1 + var) / (1 + inflacion) - 1, 4), "productos": len(variaciones)}
    return salida


class ConfigProveedor(BaseModel):
    email_oc: str | None = None
    telefono: str | None = None
    dias_visita: list[int] = Field(default_factory=list)
    demora_entrega_dias: int | None = Field(default=None, ge=0, le=90)
    pedido_minimo_monto: Decimal = Field(default=Decimal(0), ge=0)
    pedido_minimo_bultos: int = Field(default=0, ge=0)
    condiciones_pago: str | None = None


@api.put("/proveedores/{proveedor_id}")
def configurar_proveedor(proveedor_id: int, datos: ConfigProveedor, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_proveedores")
    if any(d < 0 or d > 6 for d in datos.dias_visita):
        raise HTTPException(status_code=400, detail="Los días de visita van de 0 (lunes) a 6 (domingo).")
    with db.transaccion(ctx) as conn:
        with conn.cursor() as cur:
            cur.execute("""UPDATE proveedores SET email_oc=%s, telefono=%s, dias_visita=%s, demora_entrega_dias=%s, pedido_minimo_monto=%s,
                           pedido_minimo_bultos=%s, condiciones_pago=%s, updated_at=now() WHERE id=%s""",
                        (datos.email_oc or None, datos.telefono or None, sorted(set(datos.dias_visita)), datos.demora_entrega_dias,
                         datos.pedido_minimo_monto, datos.pedido_minimo_bultos, datos.condiciones_pago or None, proveedor_id))
            if not cur.rowcount:
                raise HTTPException(status_code=404, detail="No existe ese proveedor.")
        sesiones.auditar(conn, ctx, ctx.usuario_id, "modificar", "proveedor", proveedor_id, datos.model_dump(mode="json"), sesiones.ip_de(request))
    return respuesta({"ok": True})


# ------------------------------------------------------------------------------ 10.13 metas y proyección
def factores_calendario(conn, hoy: date, ubicacion_id: int | None) -> tuple[list[float], float, float]:
    """(factor por día de la semana, factor de los primeros 5 días del mes, venta diaria base sin esos efectos)."""
    filas = db.filas(conn, "SELECT fecha, sum(facturacion) v FROM agg_producto_ubicacion_dia WHERE fecha > %s AND fecha < %s "
                           "AND (%s::bigint IS NULL OR ubicacion_id = %s) GROUP BY 1", (hoy - timedelta(days=92), hoy, ubicacion_id, ubicacion_id))
    ventas = {f["fecha"]: float(f["v"]) for f in filas}
    if not ventas:
        return [1.0] * 7, 1.0, 0.0
    ultimas = [d for d in ventas if d > hoy - timedelta(days=57)]
    promedio = sum(ventas[d] for d in ultimas) / len(ultimas) if ultimas else 1
    semana = []
    for wd in range(7):
        vs = [ventas[d] for d in ultimas if d.weekday() == wd]
        semana.append((sum(vs) / len(vs)) / promedio if vs and promedio else 1.0)
    inicio = [v for d, v in ventas.items() if d.day <= 5]
    resto = [v for d, v in ventas.items() if d.day > 5]
    f_inicio = (sum(inicio) / len(inicio)) / (sum(resto) / len(resto)) if inicio and resto and sum(resto) else 1.0
    base_dias = [d for d in ventas if d > hoy - timedelta(days=29)]
    base = sum(ventas[d] / (semana[d.weekday()] * (f_inicio if d.day <= 5 else 1.0)) for d in base_dias) / len(base_dias) if base_dias else 0.0
    return semana, f_inicio, base


def proyeccion(actual: float, hoy: date, fin: date, semana: list[float], f_inicio: float, base: float) -> float:
    total = actual
    d = hoy + timedelta(days=1)
    while d <= fin:
        total += base * semana[d.weekday()] * (f_inicio if d.day <= 5 else 1.0)
        d += timedelta(days=1)
    return total


def semaforo_meta(cumplimiento: float | None) -> str:
    if cumplimiento is None:
        return "gris"
    return "verde" if cumplimiento >= 1 else "amarillo" if cumplimiento >= 0.95 else "rojo"


@api.get("/metas")
def metas(mes: date | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    ver_costos = permisos.puede(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        mes = (mes or hoy).replace(day=1)
        fin = mes.replace(day=calendar.monthrange(mes.year, mes.month)[1])
        corte = min(hoy, fin)
        ubic = [u for u in db.filas(conn, "SELECT id, nombre FROM ubicaciones WHERE activa AND tipo <> 'deposito' ORDER BY id")]
        cargadas = {(m["ubicacion_id"], m["metrica"]): m["valor"] for m in db.filas(conn, "SELECT ubicacion_id, metrica, valor FROM metas WHERE periodo=%s AND canal_id IS NULL", (mes,))}
        reales = {f["ubicacion_id"]: f for f in db.filas(conn, "SELECT ubicacion_id, sum(facturacion) ventas, sum(ganancia) ganancia FROM agg_producto_ubicacion_dia "
                                                               "WHERE fecha BETWEEN %s AND %s GROUP BY 1", (mes, corte))}
        filas = []
        for u in ubic + [{"id": None, "nombre": "Total"}]:
            if u["id"] is None:
                real = {"ventas": sum((r["ventas"] for r in reales.values()), Decimal(0)), "ganancia": sum((r["ganancia"] for r in reales.values()), Decimal(0))}
            else:
                real = reales.get(u["id"], {"ventas": Decimal(0), "ganancia": Decimal(0)})
            semana, f_inicio, base = factores_calendario(conn, corte, u["id"])
            margen_actual = float(real["ganancia"] / real["ventas"]) if real["ventas"] else 0
            proy_v = proyeccion(float(real["ventas"]), corte, fin, semana, f_inicio, base) if corte < fin else float(real["ventas"])
            fila = {"ubicacion_id": u["id"], "ubicacion": u["nombre"], "metricas": []}
            for metrica in ("ventas", "ganancia", "margen"):
                if metrica != "ventas" and not ver_costos:
                    continue
                meta = cargadas.get((u["id"], metrica))
                if meta is None and u["id"] is None and metrica in ("ventas", "ganancia"):
                    partes = [cargadas.get((x["id"], metrica)) for x in ubic]
                    meta = sum(partes, Decimal(0)) if partes and all(p is not None for p in partes) else None
                actual = float(real["ventas"]) if metrica == "ventas" else float(real["ganancia"]) if metrica == "ganancia" else margen_actual
                proy = proy_v if metrica == "ventas" else proy_v * margen_actual if metrica == "ganancia" else margen_actual
                cumpl = proy / float(meta) if meta else None
                fila["metricas"].append({"metrica": metrica, "meta": meta, "actual": round(actual, 4 if metrica == "margen" else 2),
                                         "proyeccion": round(proy, 4 if metrica == "margen" else 2), "cumplimiento": cumpl, "semaforo": semaforo_meta(cumpl)})
            filas.append(fila)
        return respuesta({"mes": mes, "hasta": corte, "dias_transcurridos": (corte - mes).days + 1, "dias_mes": (fin - mes).days + 1,
                          "filas": filas, "puede_editar": permisos.puede(ctx, "configurar_empresa")})


class Meta(BaseModel):
    mes: date
    ubicacion_id: int | None = None
    metrica: str
    valor: Decimal | None                  # None = borrar


@api.put("/metas")
def guardar_metas(datos: list[Meta], request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        for m in datos:
            if m.metrica not in ("ventas", "ganancia", "margen"):
                raise HTTPException(status_code=400, detail="Métrica no válida.")
            if m.metrica == "margen" and m.valor is not None and not (0 < m.valor < 1):
                raise HTTPException(status_code=400, detail="El margen va como fracción (0,28 = 28 %).")
            cur.execute("DELETE FROM metas WHERE periodo=%s AND ubicacion_id IS NOT DISTINCT FROM %s AND canal_id IS NULL AND metrica=%s",
                        (m.mes.replace(day=1), m.ubicacion_id, m.metrica))
            if m.valor is not None:
                cur.execute("INSERT INTO metas (org_id, periodo, ubicacion_id, metrica, valor) VALUES (%s,%s,%s,%s,%s)",
                            (ctx.org_id, m.mes.replace(day=1), m.ubicacion_id, m.metrica, m.valor))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "modificar", "metas", None, {"metas": [m.model_dump(mode="json") for m in datos]}, sesiones.ip_de(request))
    return respuesta({"ok": True})
