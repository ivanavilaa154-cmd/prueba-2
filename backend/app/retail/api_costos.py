"""Configuración de unidades, impuestos y descuentos de proveedor (SPEC v2, sección 4).

- Cómo vienen cargados los costos (con o sin IVA) y las reglas de IVA e impuestos internos por categoría o producto.
- Conversiones exactas de unidades de compra (bulto, caja, pack…) a la unidad base del producto.
- Descuentos y bonificaciones de cada proveedor, que bajan el costo de reposición.
Cada cambio recalcula en segundo plano los costos y los márgenes de la empresa.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import db, permisos, sesiones
from .rutas import respuesta
from .unidades import normalizar

api = APIRouter(prefix="/retail/api", tags=["retail"])
IVA_ADMITIDOS = (Decimal("0.21"), Decimal("0.105"), Decimal("0.27"), Decimal("0.025"), Decimal("0"))


def _recalcular(ctx: db.Contexto) -> None:
    from .api_ingesta import recalcular_en_segundo_plano
    recalcular_en_segundo_plano(ctx.org_id)


@api.get("/costos/config")
def ver_config(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        return respuesta({
            "costos_con_iva": db.fila(conn, "SELECT costos_con_iva FROM organizaciones WHERE id = app_org()")["costos_con_iva"],
            "reglas": db.filas(conn, """SELECT r.id, r.iva, r.impuestos_internos, r.categoria_id, r.producto_id,
                                              coalesce(c.nombre, p.nombre) nombre, CASE WHEN r.producto_id IS NULL THEN 'categoria' ELSE 'producto' END nivel
                                       FROM reglas_impuesto r LEFT JOIN categorias c ON c.id = r.categoria_id LEFT JOIN productos p ON p.id = r.producto_id
                                       ORDER BY nivel, nombre"""),
            "categorias": db.filas(conn, """SELECT c.id, CASE WHEN p.id IS NULL THEN c.nombre ELSE p.nombre || ' › ' || c.nombre END nombre
                                            FROM categorias c LEFT JOIN categorias p ON p.id = c.padre_id ORDER BY 2"""),
            "conversiones": db.filas(conn, """SELECT x.id, x.producto_id, p.nombre producto, p.unidad base, x.unidad, x.factor, x.proveedor_id,
                                                     pr.razon_social proveedor
                                              FROM conversiones_unidad x JOIN productos p ON p.id = x.producto_id
                                              LEFT JOIN proveedores pr ON pr.id = x.proveedor_id ORDER BY p.nombre, x.unidad"""),
            "descuentos": db.filas(conn, """SELECT d.*, pr.razon_social proveedor, p.nombre producto, c.nombre categoria
                                            FROM descuentos_proveedor d JOIN proveedores pr ON pr.id = d.proveedor_id
                                            LEFT JOIN productos p ON p.id = d.producto_id LEFT JOIN categorias c ON c.id = d.categoria_id
                                            ORDER BY pr.razon_social, d.vigente_desde DESC"""),
            "proveedores": db.filas(conn, "SELECT id, razon_social FROM proveedores WHERE activo ORDER BY razon_social"),
        })


class Config(BaseModel):
    costos_con_iva: bool


@api.put("/costos/config")
def guardar_config(datos: Config, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("UPDATE organizaciones SET costos_con_iva=%s, updated_at=now() WHERE id=%s", (datos.costos_con_iva, ctx.org_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "modificar", "costos_con_iva", ctx.org_id, datos.model_dump(), sesiones.ip_de(request))
    _recalcular(ctx)
    return respuesta({"ok": True})


class Regla(BaseModel):
    categoria_id: int | None = None
    producto_id: int | None = None
    iva: Decimal
    impuestos_internos: Decimal = Decimal(0)


@api.post("/costos/impuestos")
def guardar_regla(datos: Regla, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    if (datos.categoria_id is None) == (datos.producto_id is None):
        raise HTTPException(status_code=400, detail="Elegí una categoría o un producto.")
    if datos.iva not in IVA_ADMITIDOS:
        raise HTTPException(status_code=400, detail="IVA admitido: 21 %, 10,5 %, 27 %, 2,5 % o exento (0).")
    if not Decimal(0) <= datos.impuestos_internos < 1:
        raise HTTPException(status_code=400, detail="Los impuestos internos van de 0 a 99 %.")
    with db.transaccion(ctx) as conn:
        tabla, ident = ("categorias", datos.categoria_id) if datos.categoria_id else ("productos", datos.producto_id)
        if not db.fila(conn, f"SELECT 1 FROM {tabla} WHERE id=%s", (ident,)):
            raise HTTPException(status_code=404, detail="No existe.")
        r = db.fila(conn, """INSERT INTO reglas_impuesto (org_id, categoria_id, producto_id, iva, impuestos_internos, created_by) VALUES (%s,%s,%s,%s,%s,%s)
                             ON CONFLICT (org_id, categoria_id, producto_id) DO UPDATE SET iva=EXCLUDED.iva, impuestos_internos=EXCLUDED.impuestos_internos
                             RETURNING id""", (ctx.org_id, datos.categoria_id, datos.producto_id, datos.iva, datos.impuestos_internos, ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "guardar", "regla_impuesto", r["id"], datos.model_dump(mode="json"), sesiones.ip_de(request))
    _recalcular(ctx)
    return respuesta({"id": r["id"]})


@api.delete("/costos/impuestos/{regla_id}")
def borrar_regla(regla_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM reglas_impuesto WHERE id=%s", (regla_id,))
    _recalcular(ctx)
    return respuesta({"ok": True})


class Conversion(BaseModel):
    producto_id: int
    unidad: str = Field(min_length=1, max_length=20)
    factor: Decimal = Field(gt=0)
    proveedor_id: int | None = None


@api.post("/costos/conversiones")
def guardar_conversion(datos: Conversion, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_proveedores")
    unidad = normalizar(datos.unidad)
    with db.transaccion(ctx) as conn:
        p = db.fila(conn, "SELECT unidad FROM productos WHERE id=%s", (datos.producto_id,))
        if not p:
            raise HTTPException(status_code=404, detail="No existe ese producto.")
        if unidad == p["unidad"]:
            raise HTTPException(status_code=400, detail="Esa es la unidad base del producto (factor 1).")
        r = db.fila(conn, """INSERT INTO conversiones_unidad (org_id, producto_id, unidad, factor, proveedor_id, created_by) VALUES (%s,%s,%s,%s,%s,%s)
                             ON CONFLICT (producto_id, unidad, proveedor_id) DO UPDATE SET factor=EXCLUDED.factor RETURNING id""",
                    (ctx.org_id, datos.producto_id, unidad, datos.factor, datos.proveedor_id, ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "guardar", "conversion_unidad", r["id"], datos.model_dump(mode="json"), sesiones.ip_de(request))
    return respuesta({"id": r["id"], "unidad": unidad})


@api.delete("/costos/conversiones/{conversion_id}")
def borrar_conversion(conversion_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_proveedores")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM conversiones_unidad WHERE id=%s", (conversion_id,))
    return respuesta({"ok": True})


class Descuento(BaseModel):
    proveedor_id: int
    producto_id: int | None = None
    categoria_id: int | None = None
    tipo: str
    porcentaje: Decimal | None = None
    compra_unidades: int | None = None
    bonifica_unidades: int | None = None
    desde_cantidad: Decimal = Decimal(0)
    vigente_desde: date | None = None
    vigente_hasta: date | None = None
    descripcion: str | None = Field(default=None, max_length=200)


@api.post("/costos/descuentos")
def guardar_descuento(datos: Descuento, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_proveedores")
    if datos.tipo not in ("porcentaje", "bonificacion", "nota_credito"):
        raise HTTPException(status_code=400, detail="Tipo: porcentaje, bonificación o nota de crédito.")
    if datos.tipo == "bonificacion" and not (datos.compra_unidades and datos.bonifica_unidades):
        raise HTTPException(status_code=400, detail="Bonificación: cuántas se compran y cuántas vienen sin cargo (por ejemplo 12 + 1).")
    if datos.tipo != "bonificacion" and not (datos.porcentaje and Decimal(0) < datos.porcentaje < 1):
        raise HTTPException(status_code=400, detail="El porcentaje va de 0 a 99 % (por ejemplo 0,05 = 5 %).")
    with db.transaccion(ctx) as conn:
        try:
            r = db.fila(conn, """INSERT INTO descuentos_proveedor (org_id, proveedor_id, producto_id, categoria_id, tipo, porcentaje, compra_unidades,
                                 bonifica_unidades, desde_cantidad, vigente_desde, vigente_hasta, descripcion, created_by)
                                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,coalesce(%s, current_date),%s,%s,%s) RETURNING id""",
                        (ctx.org_id, datos.proveedor_id, datos.producto_id, datos.categoria_id, datos.tipo,
                         datos.porcentaje if datos.tipo != "bonificacion" else None, datos.compra_unidades if datos.tipo == "bonificacion" else None,
                         datos.bonifica_unidades if datos.tipo == "bonificacion" else None, datos.desde_cantidad, datos.vigente_desde,
                         datos.vigente_hasta, datos.descripcion, ctx.usuario_id))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"No se pudo guardar: {str(e).splitlines()[0][:160]}")
        sesiones.auditar(conn, ctx, ctx.usuario_id, "guardar", "descuento_proveedor", r["id"], datos.model_dump(mode="json"), sesiones.ip_de(request))
    _recalcular(ctx)
    return respuesta({"id": r["id"]})


@api.delete("/costos/descuentos/{descuento_id}")
def borrar_descuento(descuento_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_proveedores")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM descuentos_proveedor WHERE id=%s", (descuento_id,))
    _recalcular(ctx)
    return respuesta({"ok": True})


@api.get("/costos/producto/{producto_id}")
def costos_de(producto_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Los dos costos (reposición e histórico) y el IVA del producto, para mostrar ambos en los reportes."""
    permisos.exigir(ctx, "ver_costos")
    with db.transaccion(ctx) as conn:
        f = db.fila(conn, """SELECT p.iva, p.impuestos_internos, p.unidad, c.* FROM productos p LEFT JOIN costos_producto c ON c.producto_id = p.id
                             WHERE p.id = %s""", (producto_id,))
        if not f:
            raise HTTPException(status_code=404, detail="No existe ese producto.")
        return respuesta(f)
