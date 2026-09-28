"""Precios y remarcación (sección 11).

Precio sugerido = costo ÷ (1 − margen objetivo − costos del canal en %), redondeado con las reglas del tramo.
Prioridad: primero los productos más vendidos con mayor aumento (mayor pérdida de margen por día).
Imanes (venden mucho con poco margen): se sugiere trasladar solo la mitad del aumento, para no espantar clientes.
La salida es un cambio de precio en la plataforma (historial con vigencia), un archivo para importar en la caja y
etiquetas de góndola solo de lo que cambió. La caja no se modifica desde acá (conexión de solo lectura).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import calculos as C
from . import db, pdf, permisos, sesiones
from .api_comprar import _hoy_datos
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])
MARGEN_DEFECTO = Decimal("0.30")
UMBRAL_EROSION = Decimal("0.02")      # margen real 2 puntos por debajo del objetivo = erosionado


def _margenes(conn) -> tuple[dict, dict, dict]:
    por_producto, por_categoria, por_canal = {}, {}, defaultdict(dict)
    for m in db.filas(conn, "SELECT * FROM margenes_objetivo"):
        if m["canal_id"]:
            por_canal[m["canal_id"]][m["producto_id"] or ("c", m["categoria_id"])] = m["margen"]
        elif m["producto_id"]:
            por_producto[m["producto_id"]] = m["margen"]
        elif m["categoria_id"]:
            por_categoria[m["categoria_id"]] = m["margen"]
    return por_producto, por_categoria, por_canal


def costo_canal_pct(conn, canal_codigo: str, hoy: date) -> Decimal:
    """Comisión + envío a cargo del vendedor + publicidad de los últimos 90 días, como % de lo vendido en el canal."""
    f = db.fila(conn, """SELECT coalesce(sum(cc.comision + cc.envio + cc.publicidad), 0) costos,
                                (SELECT coalesce(sum(t.total), 0) FROM tickets t JOIN canales c ON c.id = t.canal_id
                                 WHERE c.codigo=%s AND t.estado <> 'anulado' AND t.fecha_hora >= %s) ventas
                         FROM costos_canal cc JOIN plataformas p ON p.id = cc.plataforma_id JOIN canales c ON c.id = p.canal_id
                         WHERE c.codigo=%s AND cc.fecha >= %s""", (canal_codigo, hoy - timedelta(days=90), canal_codigo, hoy - timedelta(days=90)))
    return (f["costos"] / f["ventas"]).quantize(Decimal("0.0001")) if f and f["ventas"] else Decimal(0)


@api.get("/precios/remarcacion")
def remarcacion(canal: str | None = None, categoria: int | None = None, filtro: str = "todos", ctx: db.Contexto = Depends(sesiones.contexto)):
    """filtro: todos · aumentos (costo subió en 30 días) · erosionados (margen real bajo el objetivo) · a_remarcar."""
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        canal_id = None
        pct_canal = Decimal(0)
        if canal and canal != "todos" and canal != "fisico":
            c = db.fila(conn, "SELECT id FROM canales WHERE codigo=%s", (canal,))
            if c:
                canal_id = c["id"]
                pct_canal = costo_canal_pct(conn, canal, hoy)
        reglas = db.filas(conn, "SELECT * FROM reglas_redondeo ORDER BY desde_precio")
        umbral = Decimal(reglas[0]["umbral_minimo_cambio"]) if reglas else Decimal("0.01")
        por_producto, por_categoria, por_canal = _margenes(conn)
        filtro_cat = "AND (c.id = %(cat)s OR c.padre_id = %(cat)s)" if categoria else ""
        filas = db.filas(conn, f"""
            SELECT p.id, p.nombre, p.codigo_interno, p.ean, p.rol_producto, p.clase_abc, p.categoria_id, c.padre_id,
                   coalesce(cp.nombre, c.nombre) categoria, pp.costo, pr.razon_social proveedor, pr.id proveedor_id,
                   (SELECT precio FROM precios x WHERE x.producto_id = p.id AND x.ubicacion_id IS NULL
                      AND (x.canal_id IS NOT DISTINCT FROM %(canal)s) AND x.desde <= %(hoy)s AND (x.hasta IS NULL OR x.hasta >= %(hoy)s)
                    ORDER BY x.desde DESC LIMIT 1) precio_canal,
                   (SELECT precio FROM precios x WHERE x.producto_id = p.id AND x.ubicacion_id IS NULL AND x.canal_id IS NULL
                      AND x.desde <= %(hoy)s AND (x.hasta IS NULL OR x.hasta >= %(hoy)s) ORDER BY x.desde DESC LIMIT 1) precio_general,
                   (SELECT l.costo_anterior FROM listas_precios_proveedor_lineas l JOIN listas_precios_proveedor lp ON lp.id = l.lista_id
                    WHERE l.producto_id = p.id AND lp.vigencia_desde > %(hace30)s ORDER BY lp.vigencia_desde DESC LIMIT 1) costo_anterior,
                   (SELECT lp.vigencia_desde FROM listas_precios_proveedor_lineas l JOIN listas_precios_proveedor lp ON lp.id = l.lista_id
                    WHERE l.producto_id = p.id ORDER BY lp.vigencia_desde DESC LIMIT 1) fecha_lista,
                   (SELECT sum(m.pronostico_diario) FROM metricas_producto_actual m WHERE m.producto_id = p.id) venta_diaria,
                   (SELECT max(x.desde) FROM precios x WHERE x.producto_id = p.id AND x.canal_id IS NULL) ultimo_cambio
            FROM productos p LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
            LEFT JOIN producto_proveedores pp ON pp.producto_id = p.id AND pp.principal LEFT JOIN proveedores pr ON pr.id = pp.proveedor_id
            WHERE p.activo {filtro_cat}""", {"canal": canal_id, "hoy": hoy, "hace30": hoy - timedelta(days=30), "cat": categoria})
        items = []
        for f in filas:
            precio = f["precio_canal"] or f["precio_general"]
            costo = f["costo"]
            # Sin precio propio del canal se usa el general como referencia.
            # Margen objetivo: el del canal (producto o categoría), si no el del producto, la subcategoría o la categoría.
            del_canal = por_canal.get(canal_id, {}) if canal_id else {}
            objetivo = (del_canal.get(f["id"]) or del_canal.get(("c", f["categoria_id"])) or del_canal.get(("c", f["padre_id"]))
                        or por_producto.get(f["id"]) or por_categoria.get(f["categoria_id"]) or por_categoria.get(f["padre_id"]) or MARGEN_DEFECTO)
            item = {**{k: f[k] for k in ("id", "nombre", "codigo_interno", "ean", "rol_producto", "clase_abc", "categoria", "proveedor", "fecha_lista", "ultimo_cambio")},
                    "precio": precio, "costo": costo, "costo_anterior": f["costo_anterior"], "margen_objetivo": objetivo, "costo_canal_pct": pct_canal,
                    "venta_diaria": f["venta_diaria"] or Decimal(0)}
            if costo is None or precio is None:
                item.update({"estado": "sin_costo" if costo is None else "sin_precio", "sugerido": None, "margen_actual": None,
                             "perdida_diaria": Decimal(0), "aumento_pct": None, "motivo": "Falta el costo del producto" if costo is None else "No tiene precio vigente"})
                items.append(item)
                continue
            margen_actual = C.margen(precio, costo)
            try:
                bruto = C.precio_sugerido(costo, objetivo, pct_canal)
            except ValueError:
                bruto = None
            sugerido = C.redondear_precio(bruto, reglas) if bruto else None
            parcial = False
            if sugerido is not None and f["rol_producto"] == "iman" and sugerido > precio:
                sugerido = C.redondear_precio(precio + (sugerido - precio) / 2, reglas)     # imán: trasladar la mitad
                parcial = True
            aumento = (costo / f["costo_anterior"] - 1) if f["costo_anterior"] else None
            margen_perdido = (objetivo - margen_actual) if margen_actual is not None else Decimal(0)
            # Pérdida de margen por día: cuánto más cuesta el producto que el costo que daría el margen objetivo con el precio de
            # hoy, por las unidades que se venden por día.
            perdida_diaria = max(Decimal(0), (costo - precio * (1 - objetivo - pct_canal))) * Decimal(str(item["venta_diaria"]))
            cambio = (sugerido - precio) / precio if sugerido is not None and precio else Decimal(0)
            if sugerido is None:
                estado = "revisar"
            elif abs(cambio) < umbral:
                estado = "ok"
            elif cambio > 0:
                estado = "subir"
            else:
                estado = "podria_bajar" if margen_actual is not None and margen_actual > objetivo + Decimal("0.10") else "ok"
            erosionado = margen_actual is not None and margen_actual < objetivo - UMBRAL_EROSION
            motivo = []
            if aumento and aumento > Decimal("0.005"):
                motivo.append(f"el proveedor aumentó {aumento * 100:.1f} %".replace(".", ","))
            if erosionado:
                motivo.append(f"margen {margen_actual * 100:.1f} % contra {objetivo * 100:.0f} % objetivo".replace(".", ","))
            if parcial:
                motivo.append("es un imán: se sugiere trasladar la mitad del aumento")
            item.update({"sugerido": sugerido, "margen_actual": margen_actual, "margen_perdido": margen_perdido, "aumento_pct": aumento,
                         "perdida_diaria": perdida_diaria.quantize(Decimal("0.01"), ROUND_HALF_UP), "estado": estado, "erosionado": erosionado,
                         "parcial": parcial, "cambio_pct": cambio, "motivo": "; ".join(motivo) or None})
            items.append(item)
        if filtro == "aumentos":
            items = [i for i in items if i.get("aumento_pct") and i["aumento_pct"] > Decimal("0.005")]
        elif filtro == "erosionados":
            items = [i for i in items if i.get("erosionado")]
        elif filtro == "a_remarcar":
            items = [i for i in items if i["estado"] == "subir"]
        items.sort(key=lambda i: (i["estado"] != "subir", -(i["perdida_diaria"] or 0), i["nombre"]))
        # Sensibilidad al precio (10.10): para decidir cuánto trasladar del aumento.
        from .api_avanzado import sensibilidades
        sens = sensibilidades(conn, hoy)
        for i in items:
            s_ = sens.get(i["id"])
            i["sensibilidad"] = s_["clase"] if s_ else "sin_datos"
            i["elasticidad"] = s_["elasticidad"] if s_ else None
        listas = db.filas(conn, """SELECT lp.id, lp.vigencia_desde, pr.razon_social proveedor, count(l.id) productos,
                                          avg(CASE WHEN l.costo_anterior > 0 THEN l.costo / l.costo_anterior - 1 END) aumento_promedio
                                   FROM listas_precios_proveedor lp JOIN proveedores pr ON pr.id = lp.proveedor_id
                                   JOIN listas_precios_proveedor_lineas l ON l.lista_id = lp.id WHERE lp.vigencia_desde > %s
                                   GROUP BY 1, 2, 3 ORDER BY 2 DESC LIMIT 20""", (hoy - timedelta(days=45),))
        a_remarcar = [i for i in items if i["estado"] == "subir"]
        return respuesta({
            "items": items, "listas_recientes": listas, "canal_costo_pct": pct_canal, "hoy": hoy,
            "tarjetas": {"a_remarcar": len(a_remarcar), "perdida_diaria": sum((i["perdida_diaria"] for i in a_remarcar), Decimal(0)),
                         "erosionados": sum(1 for i in items if i.get("erosionado")),
                         "aumentos": sum(1 for i in items if i.get("aumento_pct") and i["aumento_pct"] > Decimal("0.005"))},
            "puede_remarcar": permisos.puede(ctx, "remarcar"),
        })


class CambioPrecio(BaseModel):
    producto_id: int
    precio: str
    canal: str | None = None


class Aplicar(BaseModel):
    cambios: list[CambioPrecio]
    desde: date | None = None


@api.post("/precios/aplicar")
def aplicar_precios(datos: Aplicar, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Registra los precios nuevos con vigencia (el anterior se cierra el día previo). No toca el sistema de caja: después se
    exporta el archivo o se imprimen las etiquetas."""
    permisos.exigir(ctx, "remarcar")
    if not datos.cambios:
        raise HTTPException(status_code=400, detail="No hay cambios para aplicar.")
    with db.transaccion(ctx) as conn:
        desde = datos.desde or _hoy_datos(conn)
        aplicados = []
        with conn.cursor() as cur:
            for c in datos.cambios:
                try:
                    precio = Decimal(c.precio).quantize(Decimal("0.01"))
                except Exception:
                    raise HTTPException(status_code=400, detail="Algún precio no es un número válido.")
                if precio <= 0:
                    raise HTTPException(status_code=400, detail="El precio tiene que ser mayor a cero.")
                canal_id = None
                if c.canal and c.canal not in ("todos", "fisico"):
                    canal_id = (db.fila(conn, "SELECT id FROM canales WHERE codigo=%s", (c.canal,)) or {}).get("id")
                anterior = db.fila(conn, "SELECT id, precio FROM precios WHERE producto_id=%s AND ubicacion_id IS NULL AND canal_id IS NOT DISTINCT FROM %s "
                                         "AND desde <= %s AND (hasta IS NULL OR hasta >= %s) ORDER BY desde DESC LIMIT 1",
                                   (c.producto_id, canal_id, desde, desde))
                if anterior:
                    cur.execute("UPDATE precios SET hasta=%s WHERE id=%s", (desde - timedelta(days=1), anterior["id"]))
                cur.execute("INSERT INTO precios (org_id, producto_id, canal_id, precio, desde, origen, created_by) VALUES (%s,%s,%s,%s,%s,'remarcacion',%s)",
                            (ctx.org_id, c.producto_id, canal_id, precio, desde, ctx.usuario_id))
                aplicados.append({"producto_id": c.producto_id, "antes": anterior["precio"] if anterior else None, "despues": precio, "canal": c.canal})
        sesiones.auditar(conn, ctx, ctx.usuario_id, "remarcar", "precio", None, {"cambios": aplicados, "desde": desde}, sesiones.ip_de(request))
        return respuesta({"aplicados": len(aplicados), "desde": desde})


@api.get("/precios/etiquetas")
def etiquetas(desde: date | None = None, productos: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    """PDF de etiquetas de góndola solo de los productos cuyo precio cambió desde la fecha (por defecto, hoy)."""
    with db.transaccion(ctx) as conn:
        desde = desde or _hoy_datos(conn)
        filtro = ""
        params: list = [desde]
        if productos:
            filtro = "AND x.producto_id = ANY(%s)"
            params.append([int(p) for p in productos.split(",") if p.strip()])
        filas = db.filas(conn, f"""SELECT p.nombre, p.ean, p.codigo_interno, x.precio FROM precios x JOIN productos p ON p.id = x.producto_id
                                   WHERE x.canal_id IS NULL AND x.ubicacion_id IS NULL AND x.hasta IS NULL AND x.desde >= %s {filtro} ORDER BY p.nombre""",
                           tuple(params))
        if not filas:
            raise HTTPException(status_code=404, detail="No hay precios nuevos desde esa fecha.")
        ruta = pdf.etiquetas(filas)
    return FileResponse(ruta, media_type="application/pdf", filename=ruta.name)


@api.get("/precios/historial/{producto_id}")
def historial(producto_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        precios = db.filas(conn, """SELECT x.precio, x.desde, x.hasta, x.origen, coalesce(c.nombre, 'Todos los canales') canal FROM precios x
                                    LEFT JOIN canales c ON c.id = x.canal_id WHERE x.producto_id=%s ORDER BY x.desde""", (producto_id,))
        costos = db.filas(conn, """SELECT lp.vigencia_desde fecha, l.costo, pr.razon_social proveedor FROM listas_precios_proveedor_lineas l
                                   JOIN listas_precios_proveedor lp ON lp.id = l.lista_id JOIN proveedores pr ON pr.id = lp.proveedor_id
                                   WHERE l.producto_id=%s ORDER BY lp.vigencia_desde""", (producto_id,))
        costos_venta = db.filas(conn, """SELECT date_trunc('week', fecha)::date semana, avg(costo_unitario) costo, avg(precio_cobrado) precio
                                         FROM tickets_lineas WHERE producto_id=%s AND cantidad > 0 GROUP BY 1 ORDER BY 1""", (producto_id,))
        return respuesta({"precios": precios, "costos_lista": costos, "semanal": costos_venta})


# ------------------------------------------------------------------------------ configuración de márgenes y redondeo
class Margen(BaseModel):
    categoria_id: int | None = None
    producto_id: int | None = None
    canal: str | None = None
    margen: str


@api.get("/config/precios")
def config_precios(ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        return respuesta({
            "margenes": db.filas(conn, """SELECT m.*, c.nombre categoria, p.nombre producto, ca.nombre canal FROM margenes_objetivo m
                                          LEFT JOIN categorias c ON c.id = m.categoria_id LEFT JOIN productos p ON p.id = m.producto_id
                                          LEFT JOIN canales ca ON ca.id = m.canal_id ORDER BY c.nombre NULLS LAST, p.nombre"""),
            "redondeo": db.filas(conn, "SELECT * FROM reglas_redondeo ORDER BY desde_precio"),
            "categorias": db.filas(conn, "SELECT id, nombre FROM categorias WHERE padre_id IS NULL ORDER BY nombre"),
            "margen_defecto": MARGEN_DEFECTO,
        })


@api.put("/config/margenes")
def guardar_margen(datos: Margen, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "remarcar")
    try:
        margen = Decimal(datos.margen.replace(",", ".")) / (100 if Decimal(datos.margen.replace(",", ".")) >= 1 else 1)
    except Exception:
        raise HTTPException(status_code=400, detail="El margen tiene que ser un número (por ejemplo 30 o 0,30).")
    if not Decimal(0) <= margen < Decimal("0.95"):
        raise HTTPException(status_code=400, detail="El margen tiene que estar entre 0 % y 95 %.")
    if (datos.categoria_id is None) == (datos.producto_id is None):
        raise HTTPException(status_code=400, detail="El margen es para una categoría o para un producto.")
    with db.transaccion(ctx) as conn:
        canal_id = (db.fila(conn, "SELECT id FROM canales WHERE codigo=%s", (datos.canal,)) or {}).get("id") if datos.canal else None
        existente = db.fila(conn, "SELECT id FROM margenes_objetivo WHERE categoria_id IS NOT DISTINCT FROM %s AND producto_id IS NOT DISTINCT FROM %s "
                                  "AND canal_id IS NOT DISTINCT FROM %s", (datos.categoria_id, datos.producto_id, canal_id))
        with conn.cursor() as cur:
            if existente:
                cur.execute("UPDATE margenes_objetivo SET margen=%s, updated_at=now() WHERE id=%s", (margen, existente["id"]))
            else:
                cur.execute("INSERT INTO margenes_objetivo (org_id, categoria_id, producto_id, canal_id, margen, created_by) VALUES (%s,%s,%s,%s,%s,%s)",
                            (ctx.org_id, datos.categoria_id, datos.producto_id, canal_id, margen, ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "guardar", "margen_objetivo", None, {**datos.model_dump(), "margen": margen}, sesiones.ip_de(request))
    return respuesta({"ok": True, "margen": margen})


class Redondeo(BaseModel):
    reglas: list[dict]


@api.put("/config/redondeo")
def guardar_redondeo(datos: Redondeo, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "remarcar")
    with db.transaccion(ctx) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM reglas_redondeo")
            for r in datos.reglas:
                try:
                    terminaciones = [int(x) for x in r.get("terminaciones", []) if 0 <= int(x) <= 9]
                    cur.execute("INSERT INTO reglas_redondeo (org_id, desde_precio, hasta_precio, multiplo, terminaciones, umbral_minimo_cambio) "
                                "VALUES (%s,%s,%s,%s,%s,%s)", (ctx.org_id, Decimal(str(r["desde_precio"])), None if r.get("hasta_precio") in (None, "") else Decimal(str(r["hasta_precio"])),
                                                              Decimal(str(r.get("multiplo") or 10)), terminaciones, Decimal(str(r.get("umbral_minimo_cambio") or "0.01"))))
                except (KeyError, ValueError, ArithmeticError):
                    raise HTTPException(status_code=400, detail="Revisá los tramos de redondeo: desde, hasta y múltiplo tienen que ser números.")
        sesiones.auditar(conn, ctx, ctx.usuario_id, "guardar", "reglas_redondeo", None, {"reglas": datos.reglas}, sesiones.ip_de(request))
    return respuesta({"ok": True})
