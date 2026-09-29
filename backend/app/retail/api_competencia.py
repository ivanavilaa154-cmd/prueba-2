"""Precios de la competencia (predicción 16) y rendimiento por metro de góndola (predicción 24).

Los dos necesitan un dato que el sistema de caja no tiene: el relevamiento de precios de otros comercios y cuánto espacio ocupa cada
producto. Se cargan a mano o con un archivo (CSV o Excel guardado como CSV) y desde ahí:

- Competencia: el precio del competidor hoy se estima llevando su último precio relevado con la inflación mensual (su precio «se
  mueve» aunque no lo hayas vuelto a mirar). Diferencia contra tu precio y, con la sensibilidad al precio de cada producto, cuántas
  unidades más venderías si igualaras al más barato. Solo sugiere: cambiar un precio lo decide una persona en Precios.
- Góndola: ganancia por metro por semana de cada producto contra la mediana de su categoría en la sucursal. Sugiere sacar frentes a
  los que rinden poco y dárselos a los que rinden mucho, con la ganancia estimada del cambio (elasticidad venta-espacio de 0,2, un
  valor típico de la literatura de gestión por categorías).
"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import db, permisos, sesiones, suscripcion
from .api_avanzado import sensibilidades
from .api_comprar import _hoy_datos
from .api_predicciones import inflacion_mensual
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"], dependencies=[Depends(suscripcion.modulo("completo"))])
ELASTICIDAD_ESPACIO = 0.2
VIGENCIA_RELEVAMIENTO = 90                    # días: un precio relevado hace más de esto no se usa


def _leer_csv(contenido: bytes) -> list[dict]:
    texto = contenido.decode("utf-8-sig", errors="replace")
    try:
        dialecto = csv.Sniffer().sniff(texto[:2000], delimiters=",;\t")
    except csv.Error:
        dialecto = csv.excel
    filas = list(csv.DictReader(io.StringIO(texto), dialect=dialecto))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in f.items()} for f in filas]


def _producto_por_codigo(conn, codigo: str) -> int | None:
    f = db.fila(conn, "SELECT id FROM productos WHERE ean = %s OR codigo_interno = %s ORDER BY ean = %s DESC LIMIT 1", (codigo, codigo, codigo))
    return f["id"] if f else None


def _numero(texto: str) -> float:
    t = texto.replace("$", "").replace(" ", "")
    if "," in t:                                                   # 1.234,56 → 1234.56
        t = t.replace(".", "").replace(",", ".")
    return float(t)


# ------------------------------------------------------------------------------ (16) competencia
class Relevamiento(BaseModel):
    producto_id: int
    competidor: str = Field(min_length=1, max_length=80)
    precio: float = Field(gt=0)
    fecha: date
    ubicacion_id: int | None = None


def _guardar_relevamiento(conn, ctx, r: Relevamiento, fuente: str) -> None:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO precios_competencia (org_id, producto_id, ubicacion_id, competidor, precio, fecha, fuente, created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (org_id, producto_id, competidor, fecha) DO UPDATE SET precio = EXCLUDED.precio, ubicacion_id = EXCLUDED.ubicacion_id""",
                    (ctx.org_id, r.producto_id, r.ubicacion_id, r.competidor.strip(), r.precio, r.fecha, fuente, ctx.usuario_id))


@api.post("/competencia")
def cargar_competencia(datos: list[Relevamiento], ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "remarcar")
    with db.transaccion(ctx) as conn:
        for r in datos:
            _guardar_relevamiento(conn, ctx, r, "manual")
        sesiones.auditar(conn, ctx.org_id, ctx.usuario_id, "crear", "precios_competencia", None, {"filas": len(datos)})
    return respuesta({"ok": True, "cargados": len(datos)})


@api.post("/competencia/archivo")
async def archivo_competencia(archivo: UploadFile = File(...), ctx: db.Contexto = Depends(sesiones.contexto)):
    """Columnas: codigo (EAN o código interno), competidor, precio y fecha (AAAA-MM-DD o DD/MM/AAAA)."""
    permisos.exigir(ctx, "remarcar")
    filas = _leer_csv(await archivo.read())
    ok, errores = 0, []
    with db.transaccion(ctx) as conn:
        for i, f in enumerate(filas, start=2):
            try:
                pid = _producto_por_codigo(conn, f.get("codigo") or f.get("ean") or "")
                if not pid:
                    raise ValueError("no encuentro el producto")
                texto = f.get("fecha") or ""
                fecha = date.fromisoformat(texto) if "-" in texto else date(*reversed([int(x) for x in texto.split("/")]))
                _guardar_relevamiento(conn, ctx, Relevamiento(producto_id=pid, competidor=f.get("competidor") or "", precio=_numero(f.get("precio") or ""),
                                                              fecha=fecha), "archivo")
                ok += 1
            except Exception as e:                                  # una fila mala no frena el resto: se informa
                errores.append({"fila": i, "error": str(e).split("\n")[0][:120]})
        sesiones.auditar(conn, ctx.org_id, ctx.usuario_id, "importar", "precios_competencia", None, {"filas": ok, "errores": len(errores)})
    return respuesta({"cargados": ok, "errores": errores[:50]})


@api.delete("/competencia/{relevamiento_id}")
def borrar_competencia(relevamiento_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "remarcar")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM precios_competencia WHERE id=%s", (relevamiento_id,))
        if not cur.rowcount:
            raise HTTPException(status_code=404, detail="No existe ese relevamiento.")
    return respuesta({"ok": True})


@api.get("/competencia")
def competencia(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        infl = inflacion_mensual(conn)
        relev = db.filas(conn, """SELECT DISTINCT ON (r.producto_id, r.competidor) r.id, r.producto_id, r.competidor, r.precio::float precio, r.fecha,
                                         r.fuente, p.nombre, p.codigo_interno,
                                         (SELECT x.precio::float FROM precios x WHERE x.producto_id = p.id AND x.ubicacion_id IS NULL AND x.canal_id IS NULL
                                            AND x.desde <= %s AND (x.hasta IS NULL OR x.hasta >= %s) ORDER BY x.desde DESC LIMIT 1) propio,
                                         (SELECT sum(m.pronostico_diario)::float FROM metricas_producto_actual m WHERE m.producto_id = p.id) venta_diaria
                                  FROM precios_competencia r JOIN productos p ON p.id = r.producto_id
                                  WHERE r.fecha >= %s ORDER BY r.producto_id, r.competidor, r.fecha DESC""",
                         (hoy, hoy, hoy - timedelta(days=VIGENCIA_RELEVAMIENTO)))
        sens = sensibilidades(conn, hoy) if relev else {}
        por_prod = defaultdict(list)
        for r in relev:
            meses = max(0, (hoy - r["fecha"]).days) / 30.4
            r["estimado_hoy"] = round(r["precio"] * (1 + infl) ** meses, 2)          # (16) su precio probable hoy
            por_prod[r["producto_id"]].append(r)
        filas = []
        for pid, rs in por_prod.items():
            propio = rs[0]["propio"]
            barato = min(rs, key=lambda x: x["estimado_hoy"])
            e = (sens.get(pid) or {}).get("elasticidad")
            diferencia = (propio / barato["estimado_hoy"] - 1) if propio else None
            unidades = None
            if diferencia is not None and diferencia > 0 and e is not None and rs[0]["venta_diaria"]:
                # Si bajaras a su precio: variación de unidades = (precio nuevo / actual) ^ elasticidad − 1.
                unidades = round(rs[0]["venta_diaria"] * 30 * ((barato["estimado_hoy"] / propio) ** e - 1), 1)
            if diferencia is None:
                sugerencia = "Cargá tu precio en Precios para comparar"
            elif diferencia > 0.05 and e is not None and e <= -1:
                sugerencia = "Sos más caro y el producto es sensible: revisá el precio"
            elif diferencia > 0.05:
                sugerencia = "Sos más caro, pero el producto es poco sensible: podés mantenerlo"
            elif diferencia < -0.05:
                sugerencia = "Sos más barato: hay margen para subir si el costo lo pide"
            else:
                sugerencia = "Parejo con la competencia"
            filas.append({"producto_id": pid, "producto": rs[0]["nombre"], "codigo": rs[0]["codigo_interno"], "propio": propio,
                          "competidores": [{"id": r["id"], "competidor": r["competidor"], "precio": r["precio"], "fecha": r["fecha"],
                                            "estimado_hoy": r["estimado_hoy"]} for r in sorted(rs, key=lambda x: x["estimado_hoy"])],
                          "mas_barato": barato["competidor"], "precio_mas_barato_hoy": barato["estimado_hoy"],
                          "diferencia": round(diferencia, 4) if diferencia is not None else None, "elasticidad": e,
                          "unidades_30d_si_igualas": unidades, "sugerencia": sugerencia})
        filas.sort(key=lambda f: -(f["diferencia"] or 0))
        caros = [f for f in filas if (f["diferencia"] or 0) > 0.05]
        return respuesta({"hoy": hoy, "inflacion_mensual": infl, "productos": filas, "relevados": len(filas), "mas_caros": len(caros),
                          "competidores": sorted({r["competidor"] for r in relev})})


# ------------------------------------------------------------------------------ (24) góndola
class Espacio(BaseModel):
    producto_id: int
    ubicacion_id: int
    frentes: int = Field(ge=1, le=200)
    metros: float = Field(gt=0, le=100)


def _guardar_espacio(conn, ctx, e: Espacio) -> None:
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO espacio_gondola (org_id, producto_id, ubicacion_id, frentes, metros, updated_by) VALUES (%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (producto_id, ubicacion_id) DO UPDATE SET frentes = EXCLUDED.frentes, metros = EXCLUDED.metros,
                       updated_by = EXCLUDED.updated_by, updated_at = now()""",
                    (ctx.org_id, e.producto_id, e.ubicacion_id, e.frentes, e.metros, ctx.usuario_id))


@api.put("/gondola")
def cargar_gondola(datos: list[Espacio], ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "recuentos")                               # lo carga quien recorre el local
    with db.transaccion(ctx) as conn:
        visibles = {f["id"] for f in db.filas(conn, "SELECT id FROM ubicaciones")}
        for e in datos:
            if e.ubicacion_id not in visibles:
                raise HTTPException(status_code=403, detail="No tenés acceso a esa sucursal.")
            _guardar_espacio(conn, ctx, e)
        sesiones.auditar(conn, ctx.org_id, ctx.usuario_id, "actualizar", "espacio_gondola", None, {"filas": len(datos)})
    return respuesta({"ok": True, "cargados": len(datos)})


@api.post("/gondola/archivo")
async def archivo_gondola(archivo: UploadFile = File(...), ctx: db.Contexto = Depends(sesiones.contexto)):
    """Columnas: codigo (EAN o código interno), sucursal (nombre), frentes y metros."""
    permisos.exigir(ctx, "recuentos")
    filas = _leer_csv(await archivo.read())
    ok, errores = 0, []
    with db.transaccion(ctx) as conn:
        sucursales = {f["nombre"].lower(): f["id"] for f in db.filas(conn, "SELECT id, nombre FROM ubicaciones")}
        for i, f in enumerate(filas, start=2):
            try:
                pid = _producto_por_codigo(conn, f.get("codigo") or f.get("ean") or "")
                uid = sucursales.get((f.get("sucursal") or "").lower())
                if not pid or not uid:
                    raise ValueError("no encuentro el producto" if not pid else "no encuentro la sucursal (o no tenés acceso)")
                _guardar_espacio(conn, ctx, Espacio(producto_id=pid, ubicacion_id=uid, frentes=int(_numero(f.get("frentes") or "1")),
                                                    metros=_numero(f.get("metros") or "")))
                ok += 1
            except Exception as e:
                errores.append({"fila": i, "error": str(e).split("\n")[0][:120]})
        sesiones.auditar(conn, ctx.org_id, ctx.usuario_id, "importar", "espacio_gondola", None, {"filas": ok, "errores": len(errores)})
    return respuesta({"cargados": ok, "errores": errores[:50]})


@api.get("/gondola")
def gondola(ubicacion_id: int | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    ver_ganancia = permisos.puede(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        hoy = _hoy_datos(conn)
        sucursales = db.filas(conn, """SELECT u.id, u.nombre, count(e.producto_id) productos FROM ubicaciones u
                                       LEFT JOIN espacio_gondola e ON e.ubicacion_id = u.id WHERE u.activa AND u.tipo <> 'deposito' GROUP BY 1, 2 ORDER BY 2""")
        if not sucursales:
            return respuesta({"sucursales": [], "productos": [], "movimientos": []})
        elegida = next((s for s in sucursales if s["id"] == ubicacion_id), None) or max(sucursales, key=lambda s: s["productos"])
        filas = db.filas(conn, """
            SELECT e.producto_id, p.nombre, coalesce(cp.nombre, c.nombre, 'Sin categoría') categoria, e.frentes, e.metros::float metros,
                   coalesce(sum(a.facturacion), 0)::float / 4 venta_semana, coalesce(sum(a.ganancia), 0)::float / 4 ganancia_semana,
                   m.dias_stock::float dias_stock, m.semaforo
            FROM espacio_gondola e JOIN productos p ON p.id = e.producto_id
            LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
            LEFT JOIN metricas_producto_actual m ON m.producto_id = e.producto_id AND m.ubicacion_id = e.ubicacion_id
            LEFT JOIN agg_producto_ubicacion_dia a ON a.producto_id = e.producto_id AND a.ubicacion_id = e.ubicacion_id AND a.fecha >= %s AND a.fecha < %s
            WHERE e.ubicacion_id = %s GROUP BY 1, 2, 3, 4, 5, m.dias_stock, m.semaforo""", (hoy - timedelta(days=28), hoy, elegida["id"]))
        medida = "ganancia_semana" if ver_ganancia else "venta_semana"
        por_cat = defaultdict(list)
        for f in filas:
            f["por_metro"] = round(f[medida] / f["metros"], 2)
            por_cat[f["categoria"]].append(f["por_metro"])
        mediana = {c: median(v) for c, v in por_cat.items()}
        for f in filas:
            m = mediana[f["categoria"]]
            f["indice"] = round(f["por_metro"] / m, 2) if m else None
            f["estado"] = ("rinde_poco" if f["indice"] is not None and f["indice"] < 0.5 and f["frentes"] > 1 else
                           "le_falta_espacio" if f["indice"] is not None and f["indice"] > 1.5 else
                           "normal")
        # Movimientos sugeridos dentro de cada categoría: un frente del que menos rinde al que más rinde.
        movimientos = []
        for cat in por_cat:
            dan = sorted((f for f in filas if f["categoria"] == cat and f["estado"] == "rinde_poco"), key=lambda f: f["indice"])
            reciben = sorted((f for f in filas if f["categoria"] == cat and f["estado"] == "le_falta_espacio"), key=lambda f: -f["indice"])
            for a, b in zip(dan, reciben):
                metro_frente_a = a["metros"] / a["frentes"]
                gana = b[medida] * ELASTICIDAD_ESPACIO * metro_frente_a / b["metros"]
                pierde = a[medida] * ELASTICIDAD_ESPACIO * metro_frente_a / a["metros"]
                movimientos.append({"categoria": cat, "sacar_de": a["nombre"], "dar_a": b["nombre"], "metros": round(metro_frente_a, 2),
                                    "efecto_semana": round(gana - pierde, 2)})
        filas.sort(key=lambda f: (f["categoria"], -(f["indice"] or 0)))
        return respuesta({"hoy": hoy, "sucursales": sucursales, "ubicacion": elegida, "medida": "ganancia" if ver_ganancia else "venta",
                          "productos": filas, "movimientos": sorted(movimientos, key=lambda m: -m["efecto_semana"]),
                          "metros_totales": round(sum(f["metros"] for f in filas), 2)})
