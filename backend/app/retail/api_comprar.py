"""API de «Comprar y reponer» (sección 6): tabla con semáforo, resumen por categoría, detalle del producto con su
explicación, y recuento guiado. Todo pasa por RLS: cada persona ve solo sus sucursales."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import calculos as C
from . import db, explicar, permisos, sesiones
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])


def lista_ids(texto: str | None) -> list[int]:
    if not texto:
        return []
    try:
        return [int(x) for x in texto.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Lista de sucursales no válida.")


def hoy_empresa(conn) -> date:
    from zoneinfo import ZoneInfo
    zona = db.fila(conn, "SELECT zona_horaria FROM organizaciones WHERE id = app_org()")["zona_horaria"]
    return datetime.now(ZoneInfo(zona)).date()


def fecha_calculo(conn) -> date:
    """Fecha del último cálculo de métricas (en la demo puede no ser hoy)."""
    f = db.fila(conn, "SELECT max(calculado_at) m FROM metricas_producto_actual")
    return hoy_empresa(conn) if not f or not f["m"] else f["m"].date()


def _hoy_datos(conn) -> date:
    """El «hoy» de los datos: el último día con ventas o stock registrado (la demo o una importación pueden terminar antes)."""
    f = db.fila(conn, "SELECT max(fecha) m FROM stock_diario")
    g = db.fila(conn, "SELECT max(fecha) m FROM agg_producto_ubicacion_dia")
    fechas = [x["m"] for x in (f, g) if x and x["m"]]
    return max(fechas) if fechas else hoy_empresa(conn)


@api.get("/comprar")
def comprar(ubicaciones: str | None = None, canal: str | None = None, categoria: int | None = None, proveedor: int | None = None,
            semaforo: str | None = None, abc: str | None = None, buscar: str | None = None, incluir_depositos: bool = False,
            ctx: db.Contexto = Depends(sesiones.contexto)):
    if not ctx.org_id:
        raise HTTPException(status_code=409, detail="Elegí una empresa para trabajar.")
    ubic = lista_ids(ubicaciones)
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        filtros = ["(u.tipo <> 'deposito' OR %(deps)s)"]
        params: dict = {"deps": incluir_depositos, "hoy": hoy}
        if ubic:
            filtros.append("m.ubicacion_id = ANY(%(ubic)s)")
            params["ubic"] = ubic
        if categoria:
            filtros.append("(c.id = %(cat)s OR c.padre_id = %(cat)s)")
            params["cat"] = categoria
        if proveedor:
            filtros.append("m.proveedor_id = %(prov)s")
            params["prov"] = proveedor
        if semaforo:
            filtros.append("m.semaforo = %(sem)s")
            params["sem"] = semaforo
        if abc:
            filtros.append("m.clase_abc = %(abc)s")
            params["abc"] = abc
        if buscar:
            filtros.append("(p.nombre ILIKE %(q)s OR p.codigo_interno ILIKE %(q)s OR p.ean = %(q_exacto)s)")
            params["q"] = f"%{buscar}%"
            params["q_exacto"] = buscar
        if canal and canal != "todos":
            filtros.append("EXISTS (SELECT 1 FROM agg_producto_ubicacion_dia a JOIN canales ca ON ca.id = a.canal_id "
                           "WHERE a.producto_id = m.producto_id AND a.ubicacion_id = m.ubicacion_id AND ca.codigo = %(canal)s "
                           "AND a.fecha > %(hoy)s::date - 90)")
            params["canal"] = canal
        filas = db.filas(conn, f"""
            SELECT m.producto_id, m.ubicacion_id, p.codigo_interno AS codigo, p.nombre, p.ean, u.nombre AS ubicacion, u.tipo AS tipo_ubicacion,
                   coalesce(cp.nombre, c.nombre) AS categoria, c.nombre AS subcategoria, coalesce(cp.id, c.id) AS categoria_id,
                   m.disponible AS stock, m.vpd, m.pronostico_diario, m.dias_stock, m.fecha_quiebre, m.cantidad_sugerida, m.semaforo,
                   m.clase_abc, m.confianza, m.ventas_en_riesgo, m.capital, m.dias_sin_venta, m.tendencia,
                   pr.id AS proveedor_id, pr.razon_social AS proveedor, pp.costo, pp.unidades_por_bulto,
                   (m.explicacion->>'stock_negativo')::boolean AS stock_negativo, (m.explicacion->>'sin_costo')::boolean AS sin_costo,
                   m.explicacion->>'supuesto_proveedor' AS supuesto
            FROM metricas_producto_actual m
            JOIN productos p ON p.id = m.producto_id
            JOIN ubicaciones u ON u.id = m.ubicacion_id
            LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
            LEFT JOIN proveedores pr ON pr.id = m.proveedor_id
            LEFT JOIN producto_proveedores pp ON pp.producto_id = m.producto_id AND pp.proveedor_id = m.proveedor_id
            WHERE {' AND '.join(filtros)}
            ORDER BY array_position(ARRAY['rojo','amarillo','verde','gris'], m.semaforo), m.fecha_quiebre NULLS LAST,
                     m.ventas_en_riesgo DESC NULLS LAST, p.nombre""", params)
        orden_sem = {"rojo": 0, "amarillo": 1, "verde": 2, "gris": 3}
        a_comprar = Decimal(0)
        riesgo = Decimal(0)
        por_cat: dict = {}
        for f in filas:
            f["monto_sugerido"] = (Decimal(str(f["cantidad_sugerida"])) * f["costo"]).quantize(Decimal("0.01")) \
                if f["costo"] is not None and f["cantidad_sugerida"] else Decimal(0)
            f["bultos"] = float(f["cantidad_sugerida"] or 0) / (f["unidades_por_bulto"] or 1)
            f["dia_quiebre"] = explicar.DIAS[f["fecha_quiebre"].weekday()] if f["fecha_quiebre"] else None
            if f["tipo_ubicacion"] != "deposito":
                a_comprar += f["monto_sugerido"]
                riesgo += f["ventas_en_riesgo"] or 0
            cat = por_cat.setdefault(f["categoria_id"], {"categoria_id": f["categoria_id"], "categoria": f["categoria"], "rojos": 0,
                                                         "amarillos": 0, "productos": 0, "monto_a_comprar": Decimal(0), "_dias": []})
            cat["productos"] += 1
            cat["rojos"] += f["semaforo"] == "rojo"
            cat["amarillos"] += f["semaforo"] == "amarillo"
            cat["monto_a_comprar"] += f["monto_sugerido"]
            if f["dias_stock"] is not None:
                cat["_dias"].append(float(f["dias_stock"]))
        resumen = []
        for c in por_cat.values():
            dias = sorted(c.pop("_dias"))
            c["cobertura_mediana"] = dias[len(dias) // 2] if dias else None
            resumen.append(c)
        resumen.sort(key=lambda c: (-c["rojos"], -c["monto_a_comprar"]))
        opciones = {
            "categorias": db.filas(conn, "SELECT id, nombre FROM categorias WHERE padre_id IS NULL ORDER BY nombre"),
            "proveedores": db.filas(conn, "SELECT id, razon_social AS nombre FROM proveedores WHERE activo ORDER BY razon_social"),
        }
        calculado = db.fila(conn, "SELECT max(calculado_at) m FROM metricas_producto_actual")["m"]
        return respuesta({
            "tarjetas": {"productos_en_rojo": sum(1 for f in filas if f["semaforo"] == "rojo" and f["tipo_ubicacion"] != "deposito"),
                         "productos_en_amarillo": sum(1 for f in filas if f["semaforo"] == "amarillo" and f["tipo_ubicacion"] != "deposito"),
                         "plata_a_comprar": a_comprar, "ventas_en_riesgo": riesgo},
            "filas": filas, "resumen_categorias": resumen, "opciones": opciones, "hoy": hoy, "calculado_at": calculado,
            "puede_comprar": permisos.puede(ctx, "crear_oc"), "puede_transferir": permisos.puede(ctx, "aprobar_transferencias"),
            "puede_recontar": permisos.puede(ctx, "recuentos"),
        })


@api.get("/productos/{producto_id}")
def detalle_producto(producto_id: int, ubicacion_id: int | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        p = db.fila(conn, """SELECT p.*, c.nombre AS subcategoria, coalesce(cp.nombre, c.nombre) AS categoria FROM productos p
                             LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id WHERE p.id=%s""",
                    (producto_id,))
        if not p:
            raise HTTPException(status_code=404, detail="No existe ese producto.")
        hoy = _hoy_datos(conn)
        metricas = db.filas(conn, """SELECT m.*, u.nombre AS ubicacion, u.tipo FROM metricas_producto_actual m JOIN ubicaciones u ON u.id = m.ubicacion_id
                                     WHERE m.producto_id=%s ORDER BY u.tipo='deposito', u.nombre""", (producto_id,))
        if not metricas:
            raise HTTPException(status_code=404, detail="No hay datos de este producto en tus sucursales.")
        actual = next((m for m in metricas if m["ubicacion_id"] == ubicacion_id), None) or \
            next((m for m in metricas if m["tipo"] != "deposito"), metricas[0])
        uid = actual["ubicacion_id"]
        e = actual["explicacion"]
        desde = hoy - timedelta(days=120)
        ventas = {f["fecha"]: f["u"] for f in db.filas(conn, "SELECT fecha, sum(unidades) u FROM agg_producto_ubicacion_dia WHERE producto_id=%s "
                                                            "AND ubicacion_id=%s AND fecha >= %s GROUP BY 1", (producto_id, uid, desde))}
        stock = {f["fecha"]: f["stock_cierre"] for f in db.filas(conn, "SELECT fecha, stock_cierre FROM stock_diario WHERE producto_id=%s "
                                                                      "AND ubicacion_id=%s AND fecha >= %s", (producto_id, uid, desde))}
        periodos = db.filas(conn, "SELECT desde, hasta FROM periodos_sin_stock WHERE producto_id=%s AND ubicacion_id=%s AND (hasta IS NULL OR hasta >= %s)",
                            (producto_id, uid, desde))
        sin = set()
        for r in periodos:
            d = r["desde"]
            while d <= (r["hasta"] or hoy):
                sin.add(d)
                d += timedelta(days=1)
        serie = []
        d = desde
        while d <= hoy:
            serie.append({"fecha": d, "unidades": ventas.get(d, 0), "stock": stock.get(d), "sin_stock": d in sin})
            d += timedelta(days=1)
        pron = [{"fecha": hoy + timedelta(days=i), "unidades": v} for i, v in enumerate(e.get("pronostico_14d", []))]
        lotes = db.filas(conn, "SELECT lote, cantidad, vencimiento FROM stock_lotes WHERE producto_id=%s AND ubicacion_id=%s AND cantidad > 0 "
                               "ORDER BY vencimiento NULLS LAST", (producto_id, uid))
        proveedores = db.filas(conn, """SELECT pr.id, pr.razon_social, pr.dias_visita, pr.demora_entrega_dias, pp.costo, pp.unidades_por_bulto,
                                        pp.multiplo_compra, pp.principal FROM producto_proveedores pp JOIN proveedores pr ON pr.id = pp.proveedor_id
                                        WHERE pp.producto_id=%s ORDER BY pp.principal DESC, pp.prioridad""", (producto_id,))
        precios = db.filas(conn, "SELECT precio, desde, hasta, canal_id FROM precios WHERE producto_id=%s ORDER BY desde DESC LIMIT 12", (producto_id,))
        cantidad = float(actual["cantidad_sugerida"] or 0)
        return respuesta({
            "producto": p, "ubicacion_id": uid, "metricas": metricas, "actual": actual, "serie": serie, "pronostico": pron,
            "lotes": lotes, "proveedores": proveedores, "precios": precios, "hoy": hoy,
            "texto_sugerencia": explicar.sugerencia(e, cantidad, hoy, "kg" if p["unidad"] == "kg" else "unidades"),
            "texto_semaforo": explicar.semaforo(actual["semaforo"], actual["fecha_quiebre"], hoy, e),
        })


# ------------------------------------------------------------------------------ recuento guiado
CANTIDAD_RECUENTO = 12


def _lista_recuento(conn, ctx: db.Contexto, ubicacion_id: int, hoy: date) -> dict:
    """Lista corta del día (12 por defecto), priorizada: stock fantasma, stock negativo, marcados a mano, clase A,
    alto valor y diferencias en recuentos anteriores."""
    r = db.fila(conn, "SELECT * FROM recuentos WHERE ubicacion_id=%s AND fecha=%s", (ubicacion_id, hoy))
    if not r:
        r = db.fila(conn, "INSERT INTO recuentos (org_id, ubicacion_id, fecha, estado, created_by) VALUES (%s,%s,%s,'pendiente',%s) RETURNING *",
                    (ctx.org_id, ubicacion_id, hoy, ctx.usuario_id or None))
    existentes = db.filas(conn, "SELECT producto_id FROM recuentos_lineas WHERE recuento_id=%s", (r["id"],))
    if len(existentes) < CANTIDAD_RECUENTO and r["estado"] != "cerrado":
        ya = {f["producto_id"] for f in existentes}
        metricas = db.filas(conn, "SELECT producto_id, disponible, vpd, dias_sin_venta, clase_abc, capital FROM metricas_producto_actual "
                                  "WHERE ubicacion_id=%s", (ubicacion_id,))
        previas = {f["producto_id"] for f in db.filas(conn, "SELECT l.producto_id FROM recuentos_lineas l JOIN recuentos rc ON rc.id = l.recuento_id "
                                                           "WHERE rc.ubicacion_id=%s AND rc.fecha > %s AND l.diferencia <> 0",
                                                     (ubicacion_id, hoy - timedelta(days=60)))}
        contados_hace_poco = {f["producto_id"] for f in db.filas(conn, "SELECT l.producto_id FROM recuentos_lineas l JOIN recuentos rc ON rc.id = l.recuento_id "
                                                                       "WHERE rc.ubicacion_id=%s AND rc.fecha > %s AND rc.fecha < %s AND l.contado IS NOT NULL",
                                                                 (ubicacion_id, hoy - timedelta(days=7), hoy))}
        candidatos = []
        for m in metricas:
            pid = m["producto_id"]
            if pid in ya or pid in contados_hace_poco:
                continue
            disp = float(m["disponible"] or 0)
            if C.posible_stock_fantasma(disp, float(m["vpd"] or 0), m["dias_sin_venta"] or 0):
                candidatos.append((0, "stock_fantasma", pid))
            elif disp < 0:
                candidatos.append((1, "stock_negativo", pid))
            elif pid in previas:
                candidatos.append((2, "diferencia_previa", pid))
            elif m["clase_abc"] == "A":
                candidatos.append((3, "clase_a", pid))
            elif m["capital"] is not None:
                candidatos.append((4, "alto_valor", pid))
        valor = {m["producto_id"]: float(m["capital"] or 0) for m in metricas}
        candidatos.sort(key=lambda c: (c[0], -valor.get(c[2], 0)))
        with conn.cursor() as cur:
            for _, motivo, pid in candidatos[:CANTIDAD_RECUENTO - len(existentes)]:
                cur.execute("INSERT INTO recuentos_lineas (org_id, recuento_id, producto_id, motivo_seleccion) VALUES (%s,%s,%s,%s) "
                            "ON CONFLICT DO NOTHING", (ctx.org_id, r["id"], pid, motivo))
    lineas = db.filas(conn, """SELECT l.*, p.nombre, p.codigo_interno, p.ean, p.unidad, s.cantidad AS stock_actual FROM recuentos_lineas l
                               JOIN productos p ON p.id = l.producto_id
                               LEFT JOIN stock_actual s ON s.producto_id = l.producto_id AND s.ubicacion_id = %s
                               WHERE l.recuento_id=%s ORDER BY l.contado IS NOT NULL, array_position(ARRAY['stock_fantasma','stock_negativo',
                               'marcado','diferencia_previa','clase_a','alto_valor'], l.motivo_seleccion), p.nombre""", (ubicacion_id, r["id"]))
    return {"recuento": r, "lineas": lineas}


@api.get("/recuentos/hoy")
def recuento_de_hoy(ubicacion_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "recuentos")
    with db.transaccion(ctx) as conn:
        if not db.fila(conn, "SELECT 1 FROM ubicaciones WHERE id=%s", (ubicacion_id,)):
            raise HTTPException(status_code=404, detail="No tenés acceso a esa sucursal.")
        return respuesta(_lista_recuento(conn, ctx, ubicacion_id, _hoy_datos(conn)))


class Marcar(BaseModel):
    producto_id: int
    ubicacion_id: int


@api.post("/recuentos/marcar")
def marcar_para_recuento(datos: list[Marcar], request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "recuentos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        agregados = 0
        for d in datos:
            if not db.fila(conn, "SELECT 1 FROM ubicaciones WHERE id=%s", (d.ubicacion_id,)):
                raise HTTPException(status_code=404, detail="No tenés acceso a esa sucursal.")
            r = db.fila(conn, "SELECT id FROM recuentos WHERE ubicacion_id=%s AND fecha=%s", (d.ubicacion_id, hoy)) or \
                db.fila(conn, "INSERT INTO recuentos (org_id, ubicacion_id, fecha, created_by) VALUES (%s,%s,%s,%s) RETURNING id",
                        (ctx.org_id, d.ubicacion_id, hoy, ctx.usuario_id))
            with conn.cursor() as cur:
                cur.execute("INSERT INTO recuentos_lineas (org_id, recuento_id, producto_id, motivo_seleccion) VALUES (%s,%s,%s,'marcado') "
                            "ON CONFLICT DO NOTHING", (ctx.org_id, r["id"], d.producto_id))
                agregados += cur.rowcount
        sesiones.auditar(conn, ctx, ctx.usuario_id, "marcar_recuento", "recuento", None, {"items": [d.model_dump() for d in datos]},
                         sesiones.ip_de(request))
    return respuesta({"agregados": agregados})


class Conteo(BaseModel):
    contado: float = Field(ge=0)
    motivo: str | None = Field(default=None, max_length=200)


@api.put("/recuentos/lineas/{linea_id}")
def cargar_conteo(linea_id: int, datos: Conteo, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Carga lo contado: calcula la diferencia en unidades y en plata y ajusta el stock con motivo. Si el ajuste supera el
    límite del usuario para «ajustes de stock», queda esperando aprobación."""
    permisos.exigir(ctx, "recuentos")
    with db.transaccion(ctx) as conn:
        l = db.fila(conn, """SELECT l.*, r.ubicacion_id, r.estado AS estado_recuento FROM recuentos_lineas l JOIN recuentos r ON r.id = l.recuento_id
                             WHERE l.id=%s""", (linea_id,))
        if not l:
            raise HTTPException(status_code=404, detail="No existe esa línea de recuento.")
        if l["estado"] in ("ajustado", "sin_diferencia"):
            raise HTTPException(status_code=409, detail="Esa línea ya se contó y se ajustó.")
        st = db.fila(conn, "SELECT cantidad FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s FOR UPDATE", (l["producto_id"], l["ubicacion_id"]))
        sistema = Decimal(st["cantidad"]) if st else Decimal(0)
        contado = Decimal(str(datos.contado)).quantize(Decimal("0.001"))
        diferencia = contado - sistema
        costo = db.fila(conn, "SELECT costo FROM producto_proveedores WHERE producto_id=%s ORDER BY principal DESC, prioridad LIMIT 1",
                        (l["producto_id"],))
        pesos = (diferencia * (costo["costo"] if costo and costo["costo"] is not None else Decimal(0))).quantize(Decimal("0.01"))
        if diferencia != 0 and not (datos.motivo or "").strip():
            raise HTTPException(status_code=400, detail="Hay diferencia: indicá el motivo (rotura, vencido, faltante, error de carga…).")
        if diferencia == 0:
            estado = "sin_diferencia"
        elif permisos.puede_aprobar(conn, ctx, "ajuste_stock", abs(pesos)):
            estado = "ajustado"
        else:
            estado = "pendiente_aprobacion"
        with conn.cursor() as cur:
            cur.execute("UPDATE recuentos_lineas SET stock_sistema=%s, contado=%s, diferencia=%s, diferencia_pesos=%s, motivo_ajuste=%s, "
                        "contado_por=%s, contado_at=now(), estado=%s WHERE id=%s",
                        (sistema, contado, diferencia, pesos, datos.motivo, ctx.usuario_id, estado, linea_id))
            if estado == "ajustado":
                _aplicar_ajuste(cur, ctx, l["producto_id"], l["ubicacion_id"], diferencia, costo, datos.motivo, linea_id)
            cur.execute("UPDATE recuentos SET estado='en_curso' WHERE id=%s AND estado='pendiente'", (l["recuento_id"],))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "recuento", "stock", l["producto_id"],
                         {"ubicacion_id": l["ubicacion_id"], "sistema": sistema, "contado": contado, "diferencia": diferencia,
                          "pesos": pesos, "estado": estado, "motivo": datos.motivo}, sesiones.ip_de(request))
        return respuesta({"estado": estado, "diferencia": diferencia, "diferencia_pesos": pesos})


def _aplicar_ajuste(cur, ctx, producto_id, ubicacion_id, diferencia, costo, motivo, linea_id) -> None:
    cur.execute("UPDATE stock_actual SET cantidad = cantidad + %s, actualizado_at=now() WHERE producto_id=%s AND ubicacion_id=%s",
                (diferencia, producto_id, ubicacion_id))
    cur.execute("INSERT INTO movimientos_stock (org_id, producto_id, ubicacion_id, tipo, cantidad, costo_unitario, documento_tipo, documento_id, "
                "motivo, usuario_id) VALUES (%s,%s,%s,'ajuste',%s,%s,'recuento',%s,%s,%s)",
                (ctx.org_id, producto_id, ubicacion_id, diferencia, costo["costo"] if costo else None, linea_id, motivo, ctx.usuario_id))


class Decision(BaseModel):
    aprobar: bool


@api.post("/recuentos/lineas/{linea_id}/aprobacion")
def aprobar_ajuste(linea_id: int, datos: Decision, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        l = db.fila(conn, "SELECT l.*, r.ubicacion_id FROM recuentos_lineas l JOIN recuentos r ON r.id = l.recuento_id WHERE l.id=%s", (linea_id,))
        if not l or l["estado"] != "pendiente_aprobacion":
            raise HTTPException(status_code=404, detail="No hay un ajuste esperando aprobación con ese número.")
        if datos.aprobar and not permisos.puede_aprobar(conn, ctx, "ajuste_stock", abs(l["diferencia_pesos"] or 0)):
            raise HTTPException(status_code=403, detail="El ajuste supera tu límite de aprobación.")
        with conn.cursor() as cur:
            cur.execute("UPDATE recuentos_lineas SET estado=%s, aprobado_por=%s, aprobado_at=now() WHERE id=%s",
                        ("ajustado" if datos.aprobar else "rechazado", ctx.usuario_id, linea_id))
            if datos.aprobar:
                costo = db.fila(conn, "SELECT costo FROM producto_proveedores WHERE producto_id=%s ORDER BY principal DESC LIMIT 1", (l["producto_id"],))
                _aplicar_ajuste(cur, ctx, l["producto_id"], l["ubicacion_id"], l["diferencia"], costo, l["motivo_ajuste"], linea_id)
        sesiones.auditar(conn, ctx, ctx.usuario_id, "aprobar_ajuste" if datos.aprobar else "rechazar_ajuste", "stock", l["producto_id"],
                         {"linea": linea_id, "diferencia": l["diferencia"], "pesos": l["diferencia_pesos"]}, sesiones.ip_de(request))
    return respuesta({"ok": True})


@api.get("/recuentos/pendientes-aprobacion")
def ajustes_pendientes(ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        return respuesta(db.filas(conn, """SELECT l.*, p.nombre, u.nombre AS ubicacion, us.nombre AS contado_por_nombre FROM recuentos_lineas l
                                           JOIN recuentos r ON r.id = l.recuento_id JOIN productos p ON p.id = l.producto_id
                                           JOIN ubicaciones u ON u.id = r.ubicacion_id LEFT JOIN usuarios us ON us.id = l.contado_por
                                           WHERE l.estado='pendiente_aprobacion' ORDER BY abs(l.diferencia_pesos) DESC"""))
