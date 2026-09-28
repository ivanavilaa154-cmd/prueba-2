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


# ------------------------------------------------------------------------------ lector de documentos con IA
def _permiso_documento(ctx, tipo: str) -> None:
    permisos.exigir(ctx, "gestionar_proveedores" if tipo == "lista_precios" else "recepciones")


@api.post("/lector/leer")
async def leer_documento(request: Request, tipo: str = Form(...), ubicacion_id: int | None = Form(None), archivo: UploadFile = File(...),
                         ctx: db.Contexto = Depends(sesiones.contexto)):
    from . import lector
    if tipo not in ("factura", "remito", "lista_precios"):
        raise HTTPException(status_code=400, detail="Tipo de documento no válido.")
    _permiso_documento(ctx, tipo)
    contenido = await archivo.read()
    if len(contenido) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="El archivo pesa más de 20 MB.")
    try:
        with db.transaccion(ctx) as conn:
            r = lector.leer(conn, ctx, contenido, archivo.filename or "documento.pdf", tipo, ubicacion_id)
            sesiones.auditar(conn, ctx, ctx.usuario_id, "leer", "documento", r["id"], {"tipo": tipo, "lineas": len(r["lineas"])}, sesiones.ip_de(request))
    except lector.ErrorLector as e:
        raise HTTPException(status_code=400, detail=str(e))
    return respuesta(r)


@api.get("/lector")
def documentos_leidos(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "recepciones")
    with db.transaccion(ctx) as conn:
        return respuesta(db.filas(conn, """
            SELECT d.id, d.tipo, d.estado, d.nombre_archivo, d.created_at, pr.razon_social AS proveedor, u.nombre AS usuario,
                   d.extraido->>'numero' AS numero, jsonb_array_length(d.extraido->'lineas') AS lineas, d.resultado->>'mensaje' AS mensaje
            FROM documentos_leidos d LEFT JOIN proveedores pr ON pr.id = d.proveedor_id LEFT JOIN usuarios u ON u.id = d.created_by
            ORDER BY d.created_at DESC LIMIT 50"""))


@api.get("/lector/{documento_id}")
def documento_leido(documento_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "recepciones")
    with db.transaccion(ctx) as conn:
        d = db.fila(conn, "SELECT id, tipo, estado, nombre_archivo, proveedor_id, ubicacion_id, extraido, resultado, created_at FROM documentos_leidos WHERE id=%s",
                    (documento_id,))
        if not d:
            raise HTTPException(status_code=404, detail="No existe ese documento.")
        return respuesta(d)


class LineaConfirmada(BaseModel):
    producto_id: int | None = None
    codigo: str | None = None
    descripcion: str | None = None
    cantidad: float | None = None
    costo_unitario: float | None = None
    lote: str | None = None
    vencimiento: str | None = None


class ConfirmarDocumento(BaseModel):
    proveedor_id: int
    ubicacion_id: int | None = None
    orden_id: int | None = None
    lineas: list[LineaConfirmada]


@api.post("/lector/{documento_id}/confirmar")
def confirmar_documento(documento_id: int, datos: ConfirmarDocumento, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    from . import lector
    with db.transaccion(ctx) as conn:
        d = db.fila(conn, "SELECT tipo FROM documentos_leidos WHERE id=%s", (documento_id,))
        if not d:
            raise HTTPException(status_code=404, detail="No existe ese documento.")
        _permiso_documento(ctx, d["tipo"])
        try:
            r = lector.confirmar(conn, ctx, documento_id, datos.proveedor_id, datos.ubicacion_id, [l.model_dump() for l in datos.lineas], datos.orden_id)
        except lector.ErrorLector as e:
            raise HTTPException(status_code=400, detail=str(e))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "confirmar", "documento", documento_id, {"mensaje": r["mensaje"]}, sesiones.ip_de(request))
    recalcular_en_segundo_plano(ctx.org_id)
    return respuesta(r)


@api.post("/lector/{documento_id}/descartar")
def descartar_documento(documento_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "recepciones")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("UPDATE documentos_leidos SET estado='descartado' WHERE id=%s AND estado='leido'", (documento_id,))
    return respuesta({"ok": True})


@api.get("/proveedores")
def proveedores(ctx: db.Contexto = Depends(sesiones.contexto)):
    """Proveedores con sus órdenes abiertas (para recibir una factura o remito contra su OC)."""
    permisos.exigir(ctx, "recepciones")
    with db.transaccion(ctx) as conn:
        lista = db.filas(conn, "SELECT id, razon_social, cuit FROM proveedores ORDER BY razon_social")
        abiertas: dict[int, list] = {}
        for o in db.filas(conn, "SELECT id, numero, proveedor_id, ubicacion_id, total FROM ordenes_compra "
                                "WHERE estado IN ('aprobada', 'enviada', 'recibida_parcial') ORDER BY created_at DESC"):
            abiertas.setdefault(o["proveedor_id"], []).append(o)
        for p in lista:
            p["ordenes_abiertas"] = abiertas.get(p["id"], [])
        return respuesta(lista)


# ------------------------------------------------------------------------------ conexión con Odoo Punto de Venta
class CredencialesOdoo(BaseModel):
    url: str
    base: str
    usuario: str
    api_key: str | None = None           # al editar, vacía = se mantiene la guardada


def _credenciales(conn, datos: CredencialesOdoo, plataforma_id: int | None) -> dict:
    from . import cifrado, odoo_pos  # noqa: F401
    clave = datos.api_key
    if not clave and plataforma_id:
        p = db.fila(conn, "SELECT credenciales_cifradas FROM plataformas WHERE id=%s AND tipo='odoo'", (plataforma_id,))
        clave = cifrado.descifrar(p["credenciales_cifradas"]).get("api_key") if p else None
    if not clave:
        raise HTTPException(status_code=400, detail="Falta la API key de Odoo.")
    return {**datos.model_dump(), "api_key": clave}


@api.get("/conexiones")
def conexiones(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_conexiones")
    with db.transaccion(ctx) as conn:
        filas = db.filas(conn, """SELECT id, tipo, nombre, activa, config, ultima_sincronizacion, sincronizado_hasta, estado_sincronizacion,
                                         error_sincronizacion, credenciales_cifradas IS NOT NULL AS tiene_clave
                                  FROM plataformas WHERE tipo='odoo' ORDER BY id""")
        return respuesta(filas)


@api.post("/conexiones/odoo/probar")
def probar_odoo(datos: CredencialesOdoo, plataforma_id: int | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Prueba el acceso y detecta almacenes y cajas, con la sucursal sugerida para cada uno. No guarda nada."""
    from . import odoo_pos
    permisos.exigir(ctx, "gestionar_conexiones")
    with db.transaccion(ctx) as conn:
        try:
            return respuesta(odoo_pos.detectar(conn, odoo_pos.cliente_de(_credenciales(conn, datos, plataforma_id))))
        except (ValueError, odoo_pos.OdooError) as e:
            raise HTTPException(status_code=400, detail=str(e))


class ConexionOdoo(CredencialesOdoo):
    almacenes: dict[int, int | None]      # {almacén de Odoo: sucursal}; None = no se sincroniza


@api.post("/conexiones/odoo")
def guardar_odoo(datos: ConexionOdoo, request: Request, plataforma_id: int | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    from . import odoo_pos
    permisos.exigir(ctx, "gestionar_conexiones")
    with db.transaccion(ctx) as conn:
        ubicaciones = {u["id"] for u in db.filas(conn, "SELECT id FROM ubicaciones")}
        if any(v and v not in ubicaciones for v in datos.almacenes.values()):
            raise HTTPException(status_code=400, detail="Alguna sucursal elegida no existe.")
        try:
            pid = odoo_pos.guardar(conn, ctx, _credenciales(conn, datos, plataforma_id), datos.almacenes, plataforma_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "guardar", "conexion", pid,
                         {"url": datos.url, "base": datos.base, "usuario": datos.usuario, "almacenes": datos.almacenes}, sesiones.ip_de(request))
    return respuesta({"id": pid})


_sincronizando: set = set()


@api.post("/conexiones/{plataforma_id}/sincronizar")
def sincronizar_ahora(plataforma_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Corre en segundo plano (la primera vez trae más de un año de tickets); el estado se ve en la lista de conexiones."""
    from . import odoo_pos
    permisos.exigir(ctx, "gestionar_conexiones")
    if plataforma_id in _sincronizando:
        return respuesta({"en_curso": True, "mensaje": "Ya se está sincronizando."})
    with db.transaccion(ctx) as conn:
        if not db.fila(conn, "SELECT 1 FROM plataformas WHERE id=%s AND tipo='odoo' AND activa", (plataforma_id,)):
            raise HTTPException(status_code=404, detail="No existe esa conexión.")
        with conn.cursor() as cur:
            cur.execute("UPDATE plataformas SET estado_sincronizacion='sincronizando' WHERE id=%s", (plataforma_id,))
    _sincronizando.add(plataforma_id)

    def correr():
        try:
            with db.transaccion(ctx) as conn:
                r = odoo_pos.sincronizar(conn, ctx, plataforma_id)
            recalcular_en_segundo_plano(ctx.org_id, r.get("desde"))
        except Exception as e:
            odoo_pos.marcar_error(ctx, plataforma_id, e)
        finally:
            _sincronizando.discard(plataforma_id)
    threading.Thread(target=correr, daemon=True).start()
    return respuesta({"en_curso": True, "mensaje": "Sincronizando: puede tardar unos minutos la primera vez."})


@api.delete("/conexiones/{plataforma_id}")
def desconectar(plataforma_id: int, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Desactiva la conexión y borra la clave guardada. Los datos ya sincronizados quedan."""
    permisos.exigir(ctx, "gestionar_conexiones")
    with db.transaccion(ctx) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE plataformas SET activa=false, credenciales_cifradas=NULL, updated_at=now() WHERE id=%s AND tipo='odoo'", (plataforma_id,))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "desconectar", "conexion", plataforma_id, {}, sesiones.ip_de(request))
    return respuesta({"ok": True})
