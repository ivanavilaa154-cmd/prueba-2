"""Pantallas del modo distribuidor (SPEC v2, 12B.7): clientes que dejaron de comprar, rendimiento por vendedor, cuenta corriente
vencida, Pareto de clientes y productos, pedidos y entregas, y «Mi cartera» del vendedor. «Qué comprar hoy» es la pantalla
Comprar y reponer de siempre: los pedidos entran a sus cálculos por el canal mayorista (ver motor._agregar)."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import db, distribuidor, permisos, sesiones
from .api_comprar import hoy_empresa
from .rutas import respuesta

api = APIRouter(prefix="/retail/api/distribuidor", tags=["retail"])


def _hoy(conn) -> date:
    """El «hoy» de los datos: el último día con pedidos (la demo o una importación pueden terminar antes que el calendario)."""
    # De toda la empresa, no de la cartera visible: para un vendedor, sus pedidos pueden terminar antes (y su ruta sería la de otro día).
    f = db.fila(conn, "SELECT greatest((SELECT max(fecha) FROM pedidos_venta), (SELECT max(fecha) FROM agg_producto_ubicacion_dia)) m")
    return f["m"] if f and f["m"] else hoy_empresa(conn)


@api.get("/clientes")
def clientes(estado: str | None = None, vendedor: int | None = None, zona: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_clientes_b2b")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        hoy = _hoy(conn)
        filas = distribuidor.estado_clientes(conn, hoy)
        resumen = distribuidor.resumen_clientes(filas)
        if vendedor:
            filas = [f for f in filas if f["vendedor_id"] == vendedor]
        if zona:
            filas = [f for f in filas if f["zona"] == zona]
        if estado:
            filas = [f for f in filas if f["estado"] == estado]
        orden = {"perdido": 0, "en_riesgo": 1, "activo": 2, "sin_compras": 3}
        filas.sort(key=lambda f: (orden[f["estado"]], -f["deja_de_facturar_mes"]))
        return respuesta({"hoy": hoy, "resumen": resumen, "filas": filas, "umbrales": distribuidor.umbrales(conn),
                          "zonas": sorted({f["zona"] for f in filas if f["zona"]}),
                          "vendedores": db.filas(conn, "SELECT id, nombre FROM vendedores WHERE activo ORDER BY nombre")
                          if permisos.puede(ctx, "ver_vendedores") else []})


@api.get("/clientes/{cliente_id}")
def cliente(cliente_id: int, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_clientes_b2b")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        c = db.fila(conn, """SELECT c.*, v.nombre vendedor, lp.nombre lista_precios FROM clientes_b2b c LEFT JOIN vendedores v ON v.id = c.vendedor_id
                             LEFT JOIN listas_precios_clientes lp ON lp.id = c.lista_precios_id WHERE c.id = %s""", (cliente_id,))
        if not c:
            raise HTTPException(status_code=404, detail="No existe ese cliente o no es de tu cartera.")
        hoy = _hoy(conn)
        estado = next((e for e in distribuidor.estado_clientes(conn, hoy) if e["cliente_id"] == cliente_id), None)
        meses = db.filas(conn, f"""SELECT date_trunc('month', p.fecha)::date mes, count(DISTINCT p.id) pedidos, sum(l.precio * {distribuidor.FACTURABLE}) venta
                                   FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id
                                   WHERE p.cliente_id = %s AND {distribuidor.COMPRA} AND p.fecha > %s::date - 400 GROUP BY 1 ORDER BY 1""", (cliente_id, hoy))
        pedidos = db.filas(conn, """SELECT id, numero, fecha, estado, total, total_entregado FROM pedidos_venta WHERE cliente_id = %s
                                    ORDER BY fecha DESC, id DESC LIMIT 12""", (cliente_id,))
        deuda = db.filas(conn, """SELECT tipo, numero, fecha, vencimiento, importe, saldo FROM documentos_cc WHERE cliente_id = %s AND saldo <> 0
                                  ORDER BY coalesce(vencimiento, fecha)""", (cliente_id,))
        compromisos = db.filas(conn, "SELECT id, fecha, monto, estado, nota FROM compromisos_pago WHERE cliente_id = %s ORDER BY fecha DESC LIMIT 10",
                               (cliente_id,))
        ops = distribuidor.oportunidades(conn, hoy, [cliente_id]).get(cliente_id, [])
        return respuesta({"cliente": c, "estado": estado, "meses": meses, "pedidos": pedidos, "deuda": deuda, "compromisos": compromisos,
                          "oportunidades": ops})


@api.get("/vendedores")
def vendedores(periodo: str = "mes_actual", ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_vendedores")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        hoy = _hoy(conn)
        desde, hasta = distribuidor.periodo(periodo, hoy)
        return respuesta(distribuidor.rendimiento_vendedores(conn, desde, hasta, hoy))


@api.get("/cuenta-corriente")
def cuenta_corriente(vendedor: int | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_cuenta_corriente")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        r = distribuidor.cuenta_corriente(conn, _hoy(conn))
        if vendedor:
            r["clientes"] = [c for c in r["clientes"] if c["vendedor_id"] == vendedor]
        return respuesta(r)


@api.get("/pareto")
def pareto(periodo: str = "90d", ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        desde, hasta = distribuidor.periodo(periodo, _hoy(conn))
        return respuesta(distribuidor.pareto(conn, desde, hasta))


@api.get("/pedidos")
def pedidos(periodo: str = "mes", ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_ventas")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        desde, hasta = distribuidor.periodo(periodo, _hoy(conn))
        return respuesta(distribuidor.pedidos(conn, desde, hasta))


@api.get("/mi-cartera")
def mi_cartera(vendedor: int | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    """El vendedor ve la suya; el jefe de ventas o el dueño pueden ver la de cualquier vendedor (?vendedor=)."""
    if ctx.rol == "vendedor":
        vendedor = ctx.vendedor_id
        if not vendedor:
            raise HTTPException(status_code=409, detail="Tu usuario no tiene una ficha de vendedor asignada: pedísela al dueño.")
    else:
        permisos.exigir(ctx, "ver_vendedores")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        r = distribuidor.mi_cartera(conn, vendedor, _hoy(conn))
        r["vendedor"] = db.fila(conn, "SELECT id, nombre, zona FROM vendedores WHERE id = %s", (vendedor,)) if vendedor else None
        return respuesta(r)


class Visita(BaseModel):
    cliente_id: int
    resultado: str = Field(pattern="^(pedido|sin_pedido|cerrado|no_atendio)$")
    motivo: str | None = Field(default=None, max_length=300)


@api.post("/visitas")
def registrar_visita(datos: Visita, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """El vendedor marca la visita desde la ruta del día (la RLS no lo deja marcar clientes de otra cartera)."""
    permisos.exigir(ctx, "ver_cartera")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        c = db.fila(conn, "SELECT id, vendedor_id FROM clientes_b2b WHERE id = %s", (datos.cliente_id,))
        if not c or not ctx.vendedor_id:
            raise HTTPException(status_code=404, detail="Ese cliente no es de tu cartera.")
        hoy = _hoy(conn)
        with conn.cursor() as cur:
            cur.execute("""UPDATE visitas SET realizada = true, resultado = %s, motivo = %s
                           WHERE vendedor_id = %s AND cliente_id = %s AND fecha = %s""", (datos.resultado, datos.motivo, ctx.vendedor_id, c["id"], hoy))
            if not cur.rowcount:
                cur.execute("""INSERT INTO visitas (org_id, vendedor_id, cliente_id, fecha, planificada, realizada, resultado, motivo, created_by)
                               VALUES (%s,%s,%s,%s,false,true,%s,%s,%s)""",
                            (ctx.org_id, ctx.vendedor_id, c["id"], hoy, datos.resultado, datos.motivo, ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "visita", "cliente_b2b", c["id"], {"resultado": datos.resultado}, sesiones.ip_de(request))
    return respuesta({"ok": True})


class Compromiso(BaseModel):
    cliente_id: int
    fecha: date
    monto: float = Field(gt=0)
    nota: str | None = Field(default=None, max_length=300)


@api.post("/compromisos")
def registrar_compromiso(datos: Compromiso, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_cobranza")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        if not db.fila(conn, "SELECT 1 FROM clientes_b2b WHERE id = %s", (datos.cliente_id,)):
            raise HTTPException(status_code=404, detail="No existe ese cliente.")
        c = db.fila(conn, "INSERT INTO compromisos_pago (org_id, cliente_id, fecha, monto, nota, created_by) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                    (ctx.org_id, datos.cliente_id, datos.fecha, datos.monto, datos.nota, ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "crear", "compromiso_pago", c["id"], {"monto": datos.monto}, sesiones.ip_de(request))
    return respuesta({"id": c["id"]}, 201)


class Umbrales(BaseModel):
    riesgo: float = Field(ge=1, le=10)
    perdido: float = Field(ge=1, le=20)
    min_dias: int = Field(ge=7, le=365)


@api.put("/umbrales")
def guardar_umbrales(datos: Umbrales, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_vendedores")
    if datos.perdido < datos.riesgo:
        raise HTTPException(status_code=400, detail="El umbral de «dejó de comprar» tiene que ser mayor o igual al de «en riesgo».")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        cur.execute("""UPDATE organizaciones SET cliente_factor_riesgo = %s, cliente_factor_perdido = %s, cliente_perdido_min_dias = %s
                       WHERE id = %s""", (datos.riesgo, datos.perdido, datos.min_dias, ctx.org_id))
    return respuesta({"ok": True})


# ------------------------------------------------------------------------------------------------ Fase 2 · rutas y cobertura (12B.3)
@api.get("/rutas")
def rutas(periodo: str = "mes", vendedor: int | None = None, dias: int | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_vendedores")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        hoy = _hoy(conn)
        desde, hasta = distribuidor.periodo(periodo, hoy)
        vendedores = db.filas(conn, "SELECT id, nombre, zona FROM vendedores WHERE activo ORDER BY nombre")
        return respuesta({"hoy": hoy, "cumplimiento": distribuidor.cumplimiento_visitas(conn, desde, hasta),
                          "sin_visita": distribuidor.sin_visita(conn, hoy, dias), "cobertura": distribuidor.cobertura(conn, hoy),
                          "vendedores": vendedores, "rutas": distribuidor.rutas_de(conn, vendedor) if vendedor else None})


class Ruta(BaseModel):
    clientes: list[int] = Field(max_length=500)


@api.put("/rutas/{vendedor_id}/{dia}")
def guardar_ruta(vendedor_id: int, dia: int, datos: Ruta, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_vendedores")
    if not 0 <= dia <= 5:
        raise HTTPException(status_code=400, detail="El día va de lunes (0) a sábado (5).")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        if not db.fila(conn, "SELECT 1 FROM vendedores WHERE id = %s", (vendedor_id,)):
            raise HTTPException(status_code=404, detail="No existe ese vendedor.")
        try:
            n = distribuidor.guardar_ruta(conn, ctx.org_id, vendedor_id, dia, datos.clientes, ctx.usuario_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "modificar", "ruta", vendedor_id, {"dia": dia, "clientes": n}, sesiones.ip_de(request))
        return respuesta({"ok": True, "rutas": distribuidor.rutas_de(conn, vendedor_id)})


@api.get("/prospectos")
def prospectos(zona: str | None = None, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_vendedores")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        return respuesta(db.filas(conn, """SELECT id, razon_social, direccion, localidad, zona, canal, fuente, created_at FROM prospectos
                                           WHERE cliente_id IS NULL AND (%s::text IS NULL OR zona = %s) ORDER BY zona, razon_social LIMIT 500""",
                                  (zona, zona)))


class Convertir(BaseModel):
    vendedor_id: int


@api.post("/prospectos/{prospecto_id}/convertir")
def convertir(prospecto_id: int, datos: Convertir, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """El comercio relevado empezó a comprar: pasa a ser cliente del vendedor elegido."""
    permisos.exigir(ctx, "gestionar_vendedores")
    with db.transaccion(ctx) as conn:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        p = db.fila(conn, "SELECT * FROM prospectos WHERE id = %s AND cliente_id IS NULL", (prospecto_id,))
        if not p:
            raise HTTPException(status_code=404, detail="No existe ese comercio o ya es cliente.")
        if not db.fila(conn, "SELECT 1 FROM vendedores WHERE id = %s", (datos.vendedor_id,)):
            raise HTTPException(status_code=404, detail="No existe ese vendedor.")
        c = db.fila(conn, """INSERT INTO clientes_b2b (org_id, razon_social, direccion, localidad, zona, canal, vendedor_id, alta, codigo_externo, created_by)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (ctx.org_id, p["razon_social"], p["direccion"], p["localidad"], p["zona"], p["canal"], datos.vendedor_id, _hoy(conn),
                     f"prospecto:{p['id']}", ctx.usuario_id))
        with conn.cursor() as cur:
            cur.execute("UPDATE prospectos SET cliente_id = %s WHERE id = %s", (c["id"], prospecto_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "convertir", "prospecto", prospecto_id, {"cliente_id": c["id"]}, sesiones.ip_de(request))
    return respuesta({"cliente_id": c["id"]}, 201)


class DiasSinVisita(BaseModel):
    dias: int = Field(ge=3, le=120)


@api.put("/rutas/dias-sin-visita")
def dias_sin_visita(datos: DiasSinVisita, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_vendedores")
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        permisos.exigir_modo(conn, ctx, "distribuidor")
        cur.execute("UPDATE organizaciones SET dias_sin_visita = %s WHERE id = %s", (datos.dias, ctx.org_id))
    return respuesta({"ok": True})
