"""Primer ingreso guiado (SPEC v2, sección 15): conectar datos → confirmar sucursales → mapear productos → configurar proveedores →
modelo de abastecimiento y márgenes → ver las primeras recomendaciones.

Lo que se puede saber de los datos se marca solo (hay productos y ventas, productos sin mapear, proveedores sin datos); lo que es una
decisión del dueño (sus sucursales, el modelo y los márgenes, haber visto las recomendaciones) lo confirma él. Al completar los 6 pasos
queda la fecha: la usa el panel interno para medir la implementación.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import db, permisos, sesiones
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])
PASOS = ["datos", "sucursales", "productos", "proveedores", "modelo", "recomendaciones"]
CONFIRMABLES = {"sucursales", "proveedores", "modelo", "recomendaciones"}


def estado(conn, org_id: int) -> dict:
    o = db.fila(conn, """SELECT modos, modelo_abastecimiento, primer_ingreso, primer_ingreso_completo_at, primer_ingreso_omitido
                         FROM organizaciones WHERE id = %s""", (org_id,))
    d = db.fila(conn, """SELECT (SELECT count(*) FROM productos WHERE activo) productos,
                                (SELECT count(*) FROM productos WHERE activo AND estado_mapeo = 'sin_mapear') sin_mapear,
                                (SELECT count(*) FROM tickets) + (SELECT count(*) FROM pedidos_venta) ventas,
                                (SELECT count(*) FROM plataformas WHERE activa AND tipo <> 'caja_propia') conexiones,
                                (SELECT count(*) FROM agentes_sincronizacion WHERE activo) agentes,
                                (SELECT count(*) FROM ubicaciones WHERE activa AND tipo <> 'deposito') sucursales,
                                (SELECT count(*) FROM ubicaciones WHERE activa AND tipo = 'deposito') depositos,
                                (SELECT count(*) FROM proveedores) proveedores,
                                (SELECT count(*) FROM proveedores WHERE coalesce(cardinality(dias_visita), 0) = 0 OR demora_entrega_dias IS NULL) proveedores_incompletos,
                                (SELECT count(*) FROM productos p WHERE activo AND NOT EXISTS (SELECT 1 FROM producto_proveedores pp WHERE pp.producto_id = p.id)) sin_proveedor,
                                (SELECT count(*) FROM margenes_objetivo) margenes,
                                (SELECT max(calculado_at) FROM metricas_producto_actual) calculado_at""")
    hecho = o["primer_ingreso"] or {}
    distribuidor = "distribuidor" in o["modos"]
    pasos = []

    def paso(clave, titulo, listo, detalle, ir, accion):
        pasos.append({"paso": clave, "titulo": titulo, "listo": bool(listo), "confirmado": hecho.get(clave), "detalle": detalle, "ir": ir,
                      "accion": accion, "se_confirma": clave in CONFIRMABLES})

    datos_ok = d["productos"] > 0 and d["ventas"] > 0
    paso("datos", "Conectá tus datos", datos_ok,
         f"{d['productos']} productos y {d['ventas']} {'pedidos y tickets' if distribuidor else 'tickets'} cargados." if datos_ok else
         "Conectá Odoo, tu tienda online o el agente de la PC de la caja, o importá un Excel/CSV de ventas, stock y productos.",
         "/datos/#conexiones", "Conectar o importar")
    paso("sucursales", "Confirmá tus sucursales y depósitos", d["sucursales"] + d["depositos"] > 0 and "sucursales" in hecho,
         f"{d['sucursales']} sucursal(es) y {d['depositos']} depósito(s). Revisá nombres y que cada caja o almacén esté en la sucursal correcta.",
         "/configuracion/#sucursales", "Revisar sucursales")
    paso("productos", "Mapeá tus productos", d["productos"] > 0 and d["sin_mapear"] == 0,
         "Todos los productos están vinculados al catálogo." if d["productos"] and not d["sin_mapear"] else
         f"{d['sin_mapear']} productos esperan que confirmes con cuál del catálogo se corresponden (por código de barras o nombre)." if d["productos"]
         else "Primero cargá tus productos.", "/datos/#catalogo", "Emparejar productos")
    paso("proveedores", "Configurá tus proveedores", d["proveedores"] > 0 and (d["proveedores_incompletos"] == 0 or "proveedores" in hecho),
         f"{d['proveedores']} proveedores; {d['proveedores_incompletos']} sin días de visita o demora; {d['sin_proveedor']} productos sin proveedor."
         if d["proveedores"] else "Cargá tus proveedores con días de visita, demora de entrega y pedido mínimo: con eso se calcula cuánto comprar.",
         "/proveedores/", "Completar proveedores")
    paso("modelo", "Elegí cómo te abastecés y tus márgenes", "modelo" in hecho,
         f"Modelo actual: {o['modelo_abastecimiento']}. {d['margenes']} márgenes objetivo cargados (si no, se usa el margen por defecto).",
         "/configuracion/#empresa", "Revisar modelo y márgenes")
    paso("recomendaciones", "Mirá tus primeras recomendaciones", d["calculado_at"] is not None and "recomendaciones" in hecho,
         "Qué te falta, cuánto comprar y a quién, con el porqué de cada número." if d["calculado_at"] else
         "Se calculan solas cuando hay datos (unos minutos después de conectar).",
         "/clientes/" if distribuidor else "/comprar/", "Ver recomendaciones")
    listos = sum(p["listo"] for p in pasos)
    actual = next((p["paso"] for p in pasos if not p["listo"]), None)
    return {"pasos": pasos, "listos": listos, "total": len(pasos), "actual": actual, "completo_at": o["primer_ingreso_completo_at"],
            "omitido": o["primer_ingreso_omitido"], "mostrar": not o["primer_ingreso_omitido"] and o["primer_ingreso_completo_at"] is None}


@api.get("/primer-ingreso")
def ver(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    with db.transaccion(ctx) as conn:
        return respuesta(estado(conn, ctx.org_id))


def _cerrar_si_completo(conn, org_id: int) -> dict:
    e = estado(conn, org_id)
    if e["listos"] == e["total"] and not e["completo_at"]:
        with conn.cursor() as cur:
            cur.execute("UPDATE organizaciones SET primer_ingreso_completo_at = now() WHERE id = %s", (org_id,))
        e = estado(conn, org_id)
    return e


@api.post("/primer-ingreso/{paso}")
def confirmar(paso: str, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    if paso not in CONFIRMABLES:
        raise HTTPException(status_code=400, detail="Ese paso se completa solo con los datos.")
    with db.transaccion(ctx) as conn:
        actual = {p["paso"]: p for p in estado(conn, ctx.org_id)["pasos"]}
        if paso == "recomendaciones" and not actual["datos"]["listo"]:
            raise HTTPException(status_code=409, detail="Todavía no hay recomendaciones: primero conectá tus datos.")
        if paso == "proveedores" and not db.fila(conn, "SELECT 1 FROM proveedores LIMIT 1"):
            raise HTTPException(status_code=409, detail="Cargá al menos un proveedor.")
        with conn.cursor() as cur:
            cur.execute("UPDATE organizaciones SET primer_ingreso = primer_ingreso || %s::jsonb WHERE id = %s",
                        (json.dumps({paso: datetime.now(timezone.utc).isoformat()}), ctx.org_id))
        return respuesta(_cerrar_si_completo(conn, ctx.org_id))


class Omitir(BaseModel):
    omitir: bool = True


@api.put("/primer-ingreso")
def omitir(datos: Omitir, ctx: db.Contexto = Depends(sesiones.contexto)):
    """«Lo hago después»: la guía deja de abrirse sola (sigue en Inicio). Con omitir=false vuelve a mostrarse."""
    permisos.exigir(ctx, "configurar_empresa")
    with db.transaccion(ctx) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE organizaciones SET primer_ingreso_omitido = %s WHERE id = %s", (datos.omitir, ctx.org_id))
        return respuesta(_cerrar_si_completo(conn, ctx.org_id))
