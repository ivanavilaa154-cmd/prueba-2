"""Ingesta de datos (secciones 5.2 y 5.5): importar Excel o CSV y normalizar el catálogo.

Importar es en tres pasos (analizar → validar → confirmar) para que la persona vea qué columna es cada dato y qué filas
tienen problemas antes de cargar nada. Al confirmar se recalculan los indicadores en segundo plano.
"""
from __future__ import annotations

import csv
import io
import threading
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from . import catalogo, db, importar, permisos, sesiones
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])
TAMANO_MAXIMO = 40 * 1024 * 1024
TITULOS = {"ventas": "Ventas (tickets)", "stock": "Stock actual", "productos": "Productos", "compras": "Compras (facturas o remitos)",
           "precios": "Lista de precios de un proveedor"}


def recalcular_en_segundo_plano(org_id: int, desde: date | None = None) -> None:
    from . import motor

    def correr():
        try:
            motor.recalcular(org_id, tipo="manual", desde=desde)
        except Exception as e:                  # el recálculo no debe romper la importación; queda en el log
            print(f"[retail] recálculo después de importar falló: {e}")
    threading.Thread(target=correr, daemon=True).start()


# ------------------------------------------------------------------------------ importar
@api.get("/importar/tipos")
def tipos(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "importar_datos")
    return respuesta([{"tipo": t, "titulo": TITULOS[t], "campos": [{"campo": c, "etiqueta": e, "obligatorio": o} for c, e, o in campos]}
                      for t, campos in importar.CAMPOS.items()])


@api.get("/importar/plantilla/{tipo}")
def plantilla(tipo: str, ctx: db.Contexto = Depends(sesiones.contexto)):
    """CSV vacío con los encabezados que reconoce el asistente (para quien no tiene un formato propio)."""
    permisos.exigir(ctx, "importar_datos")
    if tipo not in importar.CAMPOS:
        raise HTTPException(status_code=404, detail="No existe ese tipo de importación.")
    salida = io.StringIO()
    csv.writer(salida, delimiter=";").writerow([e for _, e, _ in importar.CAMPOS[tipo]])
    return Response(("﻿" + salida.getvalue()).encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="plantilla-{tipo}.csv"'})


@api.post("/importar/analizar")
async def analizar(request: Request, tipo: str = Form(...), archivo: UploadFile = File(...), ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "importar_datos")
    contenido = await archivo.read()
    if len(contenido) > TAMANO_MAXIMO:
        raise HTTPException(status_code=413, detail="El archivo pesa más de 40 MB: dividilo en partes.")
    nombre = archivo.filename or "archivo.csv"
    if not nombre.lower().endswith((".xlsx", ".xlsm", ".csv", ".txt")):
        raise HTTPException(status_code=400, detail="Subí un Excel (.xlsx) o un CSV.")
    try:
        with db.transaccion(ctx) as conn:
            r = importar.analizar(conn, ctx, tipo, nombre, contenido)
            sesiones.auditar(conn, ctx, ctx.usuario_id, "analizar", "importacion", r["lote_id"], {"tipo": tipo, "archivo": nombre, "filas": r["filas"]},
                             sesiones.ip_de(request))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:                                   # archivo dañado o formato raro
        if "zip" in str(e).lower() or "workbook" in str(e).lower():
            raise HTTPException(status_code=400, detail="No se pudo leer el Excel. Guardalo de nuevo como .xlsx o como CSV.")
        raise
    return respuesta(r)


class Mapeo(BaseModel):
    mapeo: dict[str, str | None]


@api.post("/importar/{lote_id}/validar")
def validar(lote_id: int, datos: Mapeo, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "importar_datos")
    try:
        with db.transaccion(ctx) as conn:
            return respuesta(importar.validar(conn, ctx, lote_id, datos.mapeo))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@api.post("/importar/{lote_id}/confirmar")
def confirmar(lote_id: int, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "importar_datos")
    try:
        with db.transaccion(ctx) as conn:
            r = importar.confirmar(conn, ctx, lote_id)
            sesiones.auditar(conn, ctx, ctx.usuario_id, "importar", "importacion", lote_id,
                             {k: v for k, v in r.items() if k in ("importadas", "duplicadas", "mensaje")}, sesiones.ip_de(request))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    recalcular_en_segundo_plano(ctx.org_id, r.get("desde"))
    return respuesta(r)


@api.get("/importar/lotes")
def lotes(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "importar_datos")
    with db.transaccion(ctx) as conn:
        return respuesta(db.filas(conn, """
            SELECT l.id, l.tipo, l.origen, l.nombre_archivo, l.estado, l.filas_total, l.filas_ok, l.filas_error, l.filas_duplicadas,
                   l.resultado->>'mensaje' AS mensaje, l.created_at, u.nombre AS usuario
            FROM lotes_importacion l LEFT JOIN usuarios u ON u.id = l.created_by
            ORDER BY l.created_at DESC LIMIT 50"""))


@api.get("/importar/{lote_id}/errores.csv")
def errores_csv(lote_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Las filas con error, con el motivo, para corregirlas en el Excel y volver a subir solo esas."""
    permisos.exigir(ctx, "importar_datos")
    with db.transaccion(ctx) as conn:
        filas = db.filas(conn, "SELECT numero, datos, error FROM staging_filas WHERE lote_id=%s AND error IS NOT NULL ORDER BY numero", (lote_id,))
    salida = io.StringIO()
    w = csv.writer(salida, delimiter=";")
    columnas = list(filas[0]["datos"].keys()) if filas else []
    w.writerow(["Fila", "Error"] + columnas)
    for f in filas:
        w.writerow([f["numero"], f["error"]] + [f["datos"].get(c) for c in columnas])
    return Response(("﻿" + salida.getvalue()).encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="errores-importacion-{lote_id}.csv"'})


# ------------------------------------------------------------------------------ catálogo
@api.get("/catalogo/pendientes")
def pendientes(ctx: db.Contexto = Depends(sesiones.contexto)):
    """Lo que falta emparejar: productos con código de barras que el maestro no conoce y líneas de listas de proveedor
    que no se pudieron asociar a un producto."""
    permisos.exigir(ctx, "gestionar_proveedores")
    with db.transaccion(ctx) as conn:
        productos = db.filas(conn, "SELECT id, codigo_interno, nombre, ean, marca FROM productos WHERE estado_mapeo='sin_mapear' AND activo ORDER BY nombre LIMIT 200")
        for p in productos:
            p["sugerencias"] = catalogo.sugerencias_maestro(conn, p["nombre"])
        lista_productos = db.filas(conn, "SELECT id, nombre, marca, codigo_interno, ean FROM productos WHERE activo")
        lineas = db.filas(conn, """
            SELECT l.id, l.codigo, l.descripcion, l.costo, lp.vigencia_desde, pr.id proveedor_id, pr.razon_social proveedor
            FROM listas_precios_proveedor_lineas l JOIN listas_precios_proveedor lp ON lp.id = l.lista_id
            JOIN proveedores pr ON pr.id = lp.proveedor_id
            WHERE l.producto_id IS NULL ORDER BY lp.vigencia_desde DESC, l.id LIMIT 200""")
        for l in lineas:
            e = catalogo.emparejar(conn, texto=l["descripcion"], origen="proveedor", origen_id=l["proveedor_id"], productos=lista_productos) \
                if l["descripcion"] else None
            l["sugerencias"] = e.candidatos[:3] if e else []
        return respuesta({"productos_sin_mapear": productos, "lineas_sin_producto": lineas})


@api.get("/catalogo/buscar")
def buscar(q: str, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_proveedores")
    q = q.strip()
    if len(q) < 2:
        return respuesta([])
    with db.transaccion(ctx) as conn:
        exactos = db.filas(conn, "SELECT id, nombre, codigo_interno, ean FROM productos WHERE activo AND (codigo_interno=%s OR ean=%s) LIMIT 5", (q, q))
        parecidos = db.filas(conn, "SELECT id, nombre, codigo_interno, ean FROM productos WHERE activo AND nombre ILIKE %s ORDER BY nombre LIMIT 20",
                             (f"%{q}%",))
        vistos = set()
        return respuesta([p for p in exactos + parecidos if not (p["id"] in vistos or vistos.add(p["id"]))])


class EmparejarLinea(BaseModel):
    producto_id: int


@api.post("/catalogo/lineas/{linea_id}")
def emparejar_linea(linea_id: int, datos: EmparejarLinea, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Asocia una línea de la lista del proveedor a un producto: se guarda como alias (la próxima lista se empareja sola)
    y se actualiza el costo del producto con ese proveedor."""
    permisos.exigir(ctx, "gestionar_proveedores")
    with db.transaccion(ctx) as conn:
        l = db.fila(conn, """SELECT l.*, lp.proveedor_id FROM listas_precios_proveedor_lineas l
                             JOIN listas_precios_proveedor lp ON lp.id = l.lista_id WHERE l.id=%s""", (linea_id,))
        if not l or l["producto_id"]:
            raise HTTPException(status_code=404, detail="Esa línea ya está emparejada o no existe.")
        if not db.fila(conn, "SELECT 1 FROM productos WHERE id=%s", (datos.producto_id,)):
            raise HTTPException(status_code=404, detail="No existe ese producto.")
        anterior = db.fila(conn, "SELECT costo FROM producto_proveedores WHERE producto_id=%s AND proveedor_id=%s", (datos.producto_id, l["proveedor_id"]))
        with conn.cursor() as cur:
            cur.execute("UPDATE listas_precios_proveedor_lineas SET producto_id=%s, costo_anterior=%s WHERE id=%s",
                        (datos.producto_id, anterior["costo"] if anterior else None, linea_id))
            cur.execute("INSERT INTO producto_proveedores (org_id, producto_id, proveedor_id, costo, codigo_proveedor) VALUES (%s,%s,%s,%s,%s) "
                        "ON CONFLICT (producto_id, proveedor_id) DO UPDATE SET costo=EXCLUDED.costo, "
                        "codigo_proveedor=coalesce(EXCLUDED.codigo_proveedor, producto_proveedores.codigo_proveedor), updated_at=now()",
                        (ctx.org_id, datos.producto_id, l["proveedor_id"], l["costo"], l["codigo"]))
        catalogo.guardar_alias(conn, ctx.org_id, datos.producto_id, "proveedor", l["proveedor_id"], l["codigo"], l["descripcion"], ctx.usuario_id)
        sesiones.auditar(conn, ctx, ctx.usuario_id, "emparejar", "producto", datos.producto_id,
                         {"linea": linea_id, "codigo": l["codigo"], "descripcion": l["descripcion"]}, sesiones.ip_de(request))
    return respuesta({"ok": True})


@api.delete("/catalogo/lineas/{linea_id}")
def descartar_linea(linea_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Productos de la lista que el comercio no vende: se descartan de la cola."""
    permisos.exigir(ctx, "gestionar_proveedores")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM listas_precios_proveedor_lineas WHERE id=%s AND producto_id IS NULL", (linea_id,))
    return respuesta({"ok": True})


class Maestro(BaseModel):
    maestro_id: int | None = None        # None = queda como producto propio (sin vínculo al maestro)


@api.post("/catalogo/productos/{producto_id}/maestro")
def vincular(producto_id: int, datos: Maestro, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_proveedores")
    with db.transaccion(ctx) as conn:
        if datos.maestro_id and not db.fila(conn, "SELECT 1 FROM productos_maestros WHERE id=%s", (datos.maestro_id,)):
            raise HTTPException(status_code=404, detail="No existe ese producto en el catálogo maestro.")
        with conn.cursor() as cur:
            cur.execute("UPDATE productos SET maestro_id=%s, estado_mapeo=%s, updated_at=now() WHERE id=%s",
                        (datos.maestro_id, "mapeado" if datos.maestro_id else "propio", producto_id))
            if not cur.rowcount:
                raise HTTPException(status_code=404, detail="No existe ese producto.")
        sesiones.auditar(conn, ctx, ctx.usuario_id, "vincular_maestro", "producto", producto_id, {"maestro_id": datos.maestro_id}, sesiones.ip_de(request))
    return respuesta({"ok": True})
