"""Copiloto con IA de Retail (sección 13.2).

- El modelo no escribe SQL: llama a herramientas predefinidas que corren con el contexto del usuario (RLS: empresa, sucursales
  y permisos), así nunca ve datos que el usuario no puede ver.
- Responde solo con cifras obtenidas de las herramientas y dice el período usado; si no hay datos, lo dice.
- Puede proponer acciones (borrador de OC, transferencia u oferta): la herramienta no las ejecuta, devuelve una propuesta que
  el usuario confirma con un botón en la pantalla.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .. import config
from . import db, explicar, permisos
from .api_comprar import _hoy_datos

MAX_VUELTAS = 10

SISTEMA = """Sos el copiloto de «Retail IA», una plataforma para comercios minoristas de Argentina. Respondés en español rioplatense,
claro y breve, a dueños, compradores y encargados de sucursal.

Reglas:
- Toda cifra que digas tiene que salir de una herramienta de esta conversación. Si no tenés una herramienta que la dé, o la herramienta
  no devuelve datos, decilo en lugar de estimar o inventar.
- Decí siempre el período y las sucursales que usaste (ej.: «del 1 al 24/09, todas las sucursales»).
- Montos en pesos con punto de miles y coma decimal ($ 1.234.567); fechas DD/MM/AAAA.
- Para «¿por qué me sugerís…?» usá explicar_sugerencia y contá el cálculo en palabras simples.
- Si conviene hacer algo (comprar, transferir, ofertar), usá proponer_accion: la persona lo confirma con un botón; vos no ejecutás nada.
- Si la pregunta no es sobre el negocio, respondé en una frase que solo podés ayudar con los datos del comercio."""


def _json(v):
    return json.loads(json.dumps(v, default=lambda x: float(x) if isinstance(x, Decimal) else str(x)))


HERRAMIENTAS = [
    {"name": "contexto", "description": "Fecha de hoy según los datos, sucursales que ve el usuario (con id) y canales. Usala primero si necesitás fechas o ids.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "ventas", "description": "Ventas de un rango de fechas: facturación, unidades, tickets, ticket promedio y ganancia (si el usuario ve costos), "
                                      "por sucursal y total. Opcionalmente compara con otro rango.",
     "input_schema": {"type": "object", "properties": {
         "desde": {"type": "string", "description": "AAAA-MM-DD"}, "hasta": {"type": "string", "description": "AAAA-MM-DD"},
         "comparar_desde": {"type": "string"}, "comparar_hasta": {"type": "string"},
         "ubicacion_id": {"type": "integer"}, "canal": {"type": "string", "enum": ["fisico", "ecommerce", "delivery", "mayorista"]}},
         "required": ["desde", "hasta"], "additionalProperties": False}},
    {"name": "ranking_productos", "description": "Productos más (o menos) vendidos de un rango, por unidades, facturación o ganancia.",
     "input_schema": {"type": "object", "properties": {
         "desde": {"type": "string"}, "hasta": {"type": "string"}, "criterio": {"type": "string", "enum": ["unidades", "facturacion", "ganancia"]},
         "orden": {"type": "string", "enum": ["mejores", "peores"]}, "limite": {"type": "integer", "minimum": 1, "maximum": 30},
         "ubicacion_id": {"type": "integer"}, "categoria": {"type": "string"}},
         "required": ["desde", "hasta", "criterio"], "additionalProperties": False}},
    {"name": "buscar_producto", "description": "Busca productos por nombre, código o código de barras. Devuelve id, nombre y código.",
     "input_schema": {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"], "additionalProperties": False}},
    {"name": "explicar_sugerencia", "description": "Para un producto (y sucursal): stock, venta diaria, días de stock, fecha de quiebre, horizonte, "
                                                  "stock de seguridad, cantidad sugerida y la explicación del cálculo.",
     "input_schema": {"type": "object", "properties": {"producto_id": {"type": "integer"}, "ubicacion_id": {"type": "integer"}},
                      "required": ["producto_id"], "additionalProperties": False}},
    {"name": "que_comprar", "description": "Productos que se agotan (semáforo rojo o amarillo) con cantidad sugerida, proveedor y plata a comprar.",
     "input_schema": {"type": "object", "properties": {"ubicacion_id": {"type": "integer"}, "proveedor": {"type": "string"},
                                                       "limite": {"type": "integer", "minimum": 1, "maximum": 50}}, "additionalProperties": False}},
    {"name": "alertas_abiertas", "description": "Avisos abiertos ordenados por prioridad e impacto en pesos, con explicación y acción sugerida.",
     "input_schema": {"type": "object", "properties": {"limite": {"type": "integer", "minimum": 1, "maximum": 20}}, "additionalProperties": False}},
    {"name": "plata_parada", "description": "Capital en stock: sano, sobrestock y stock muerto; plata en riesgo de vencimiento y los productos con más plata parada.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "proponer_accion", "description": "Propone una acción para que la persona la confirme con un botón (no la ejecuta): borrador de orden de compra, "
                                              "transferencia entre sucursales u oferta con descuento.",
     "input_schema": {"type": "object", "properties": {
         "tipo": {"type": "string", "enum": ["orden_compra", "transferencia", "oferta"]}, "motivo": {"type": "string"},
         "items": {"type": "array", "items": {"type": "object", "properties": {
             "producto_id": {"type": "integer"}, "ubicacion_id": {"type": "integer"}, "cantidad": {"type": "number"},
             "descuento": {"type": "number", "description": "Solo ofertas: 0,1 = 10 %"}, "hasta": {"type": "string", "description": "Solo ofertas: AAAA-MM-DD"}},
             "required": ["producto_id", "ubicacion_id"], "additionalProperties": False}}},
         "required": ["tipo", "motivo", "items"], "additionalProperties": False}},
]


def _fecha(v: str | None) -> date | None:
    return date.fromisoformat(v[:10]) if v else None


def _t_contexto(conn, ctx, e):
    return {"hoy": _hoy_datos(conn), "sucursales": db.filas(conn, "SELECT id, nombre, tipo FROM ubicaciones WHERE activa ORDER BY id"),
            "canales": [c["codigo"] for c in db.filas(conn, "SELECT codigo FROM canales WHERE activo")],
            "ve_costos": permisos.puede(ctx, "ver_costos")}


def _resumen_ventas(conn, ctx, d: date, h: date, ubicacion_id, canal) -> dict:
    filas = db.filas(conn, """
        SELECT u.nombre, sum(a.facturacion) facturacion, sum(a.unidades) unidades, sum(a.ganancia) ganancia
        FROM agg_producto_ubicacion_dia a JOIN ubicaciones u ON u.id = a.ubicacion_id JOIN canales c ON c.id = a.canal_id
        WHERE a.fecha BETWEEN %s AND %s AND (%s::bigint IS NULL OR a.ubicacion_id = %s) AND (%s::text IS NULL OR c.codigo = %s)
        GROUP BY 1 ORDER BY 1""", (d, h, ubicacion_id, ubicacion_id, canal, canal))
    tickets = {f["nombre"]: f["t"] for f in db.filas(conn, """
        SELECT u.nombre, sum(x.tickets) t FROM agg_ubicacion_hora x JOIN ubicaciones u ON u.id = x.ubicacion_id JOIN canales c ON c.id = x.canal_id
        WHERE x.fecha BETWEEN %s AND %s AND (%s::bigint IS NULL OR x.ubicacion_id = %s) AND (%s::text IS NULL OR c.codigo = %s) GROUP BY 1""",
        (d, h, ubicacion_id, ubicacion_id, canal, canal))}
    ver = permisos.puede(ctx, "ver_costos")
    por = [{"sucursal": f["nombre"], "facturacion": f["facturacion"], "unidades": f["unidades"], "tickets": tickets.get(f["nombre"], 0),
            **({"ganancia": f["ganancia"]} if ver else {})} for f in filas]
    total = {"facturacion": sum((f["facturacion"] for f in filas), Decimal(0)), "unidades": sum((f["unidades"] for f in filas), Decimal(0)),
             "tickets": sum(tickets.values())}
    total["ticket_promedio"] = (total["facturacion"] / total["tickets"]).quantize(Decimal("0.01")) if total["tickets"] else None
    if ver:
        total["ganancia"] = sum((f["ganancia"] for f in filas), Decimal(0))
    return {"desde": d, "hasta": h, "por_sucursal": por, "total": total}


def _t_ventas(conn, ctx, e):
    r = {"periodo": _resumen_ventas(conn, ctx, _fecha(e["desde"]), _fecha(e["hasta"]), e.get("ubicacion_id"), e.get("canal"))}
    if e.get("comparar_desde") and e.get("comparar_hasta"):
        r["comparado"] = _resumen_ventas(conn, ctx, _fecha(e["comparar_desde"]), _fecha(e["comparar_hasta"]), e.get("ubicacion_id"), e.get("canal"))
        a, b = r["periodo"]["total"]["facturacion"], r["comparado"]["total"]["facturacion"]
        r["variacion_facturacion"] = float(a / b - 1) if b else None
    if not r["periodo"]["por_sucursal"]:
        r["aviso"] = "No hay ventas en ese rango para lo que ve el usuario."
    return r


def _t_ranking(conn, ctx, e):
    criterio = e["criterio"]
    if criterio == "ganancia" and not permisos.puede(ctx, "ver_costos"):
        return {"error": "Tu rol no ve costos: no puedo ordenar por ganancia."}
    orden = "ASC" if e.get("orden") == "peores" else "DESC"
    return {"desde": e["desde"], "hasta": e["hasta"], "criterio": criterio, "productos": db.filas(conn, f"""
        SELECT p.id, p.nombre, p.codigo_interno, sum(a.unidades) unidades, sum(a.facturacion) facturacion
               {", sum(a.ganancia) ganancia" if permisos.puede(ctx, "ver_costos") else ""}
        FROM agg_producto_ubicacion_dia a JOIN productos p ON p.id = a.producto_id
        LEFT JOIN categorias c ON c.id = p.categoria_id LEFT JOIN categorias cp ON cp.id = c.padre_id
        WHERE a.fecha BETWEEN %s AND %s AND (%s::bigint IS NULL OR a.ubicacion_id = %s)
          AND (%s::text IS NULL OR coalesce(cp.nombre, c.nombre) ILIKE %s OR c.nombre ILIKE %s)
        GROUP BY 1, 2, 3 ORDER BY sum(a.{criterio}) {orden} LIMIT %s""",
        (_fecha(e["desde"]), _fecha(e["hasta"]), e.get("ubicacion_id"), e.get("ubicacion_id"), e.get("categoria"),
         f"%{e.get('categoria') or ''}%", f"%{e.get('categoria') or ''}%", int(e.get("limite") or 10)))}


def _t_buscar(conn, ctx, e):
    q = e["texto"].strip()
    return db.filas(conn, "SELECT id, nombre, codigo_interno, ean FROM productos WHERE activo AND (nombre ILIKE %s OR codigo_interno=%s OR ean=%s) "
                          "ORDER BY nombre LIMIT 10", (f"%{q}%", q, q))


def _t_explicar(conn, ctx, e):
    hoy = _hoy_datos(conn)
    filas = db.filas(conn, """SELECT m.*, p.nombre, u.nombre ubicacion, p.unidad FROM metricas_producto_actual m JOIN productos p ON p.id = m.producto_id
                              JOIN ubicaciones u ON u.id = m.ubicacion_id WHERE m.producto_id=%s AND (%s::bigint IS NULL OR m.ubicacion_id=%s)
                              AND u.tipo <> 'deposito' ORDER BY m.ubicacion_id""", (e["producto_id"], e.get("ubicacion_id"), e.get("ubicacion_id")))
    if not filas:
        return {"error": "No hay métricas de ese producto en las sucursales que ves."}
    salida = []
    for m in filas:
        x = m["explicacion"] or {}
        salida.append({"producto": m["nombre"], "sucursal": m["ubicacion"], "stock_disponible": m["disponible"], "venta_diaria": m["vpd"],
                       "pronostico_diario": m["pronostico_diario"], "dias_de_stock": m["dias_stock"], "fecha_quiebre": m["fecha_quiebre"],
                       "horizonte_dias": m["horizonte_dias"], "stock_seguridad": m["stock_seguridad"], "cantidad_sugerida": m["cantidad_sugerida"],
                       "semaforo": m["semaforo"], "clase_abc": m["clase_abc"], "dias_sin_stock_ultimos_28": x.get("dias_sin_stock"),
                       "en_transito": x.get("en_transito"), "pedidos_abiertos": x.get("pedidos_abiertos"), "multiplo_bulto": x.get("multiplo"),
                       "proveedor": x.get("proveedor"),
                       "explicacion": explicar.sugerencia(x, float(m["cantidad_sugerida"] or 0), hoy, "kg" if m["unidad"] == "kg" else "unidades") if x else None})
    return {"hoy": hoy, "detalle": salida}


def _t_comprar(conn, ctx, e):
    return {"productos": db.filas(conn, """
        SELECT m.producto_id, p.nombre, u.id ubicacion_id, u.nombre sucursal, m.semaforo, m.disponible, m.dias_stock, m.fecha_quiebre,
               m.cantidad_sugerida, pr.razon_social proveedor, (m.cantidad_sugerida * (m.explicacion->>'costo')::numeric)::numeric(16,2) plata
        FROM metricas_producto_actual m JOIN productos p ON p.id = m.producto_id JOIN ubicaciones u ON u.id = m.ubicacion_id
        LEFT JOIN proveedores pr ON pr.id = m.proveedor_id
        WHERE m.semaforo IN ('rojo', 'amarillo') AND m.cantidad_sugerida > 0 AND u.tipo <> 'deposito'
          AND (%s::bigint IS NULL OR m.ubicacion_id = %s) AND (%s::text IS NULL OR pr.razon_social ILIKE %s)
        ORDER BY m.semaforo = 'rojo' DESC, m.fecha_quiebre NULLS LAST LIMIT %s""",
        (e.get("ubicacion_id"), e.get("ubicacion_id"), e.get("proveedor"), f"%{e.get('proveedor') or ''}%", int(e.get("limite") or 20)))}


def _t_alertas(conn, ctx, e):
    return db.filas(conn, """SELECT tipo, prioridad, titulo, explicacion, impacto, tipo_impacto, accion->>'etiqueta' accion
                             FROM alertas WHERE estado IN ('nueva', 'vista', 'escalada')
                             ORDER BY CASE prioridad WHEN 'urgente' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, impacto DESC LIMIT %s""", (int(e.get("limite") or 10),))


def _t_plata(conn, ctx, e):
    if not permisos.puede(ctx, "ver_costos"):
        return {"error": "Tu rol no ve costos."}
    from .api_plata import estado_stock, parametro, red_de_venta
    sobre, muerto = int(parametro(conn, "umbral_sobrestock_dias")), int(parametro(conn, "umbral_muerto_dias"))
    red = red_de_venta(conn)
    dist = {"sano": Decimal(0), "sobrestock": Decimal(0), "muerto": Decimal(0)}
    top = []
    for m in db.filas(conn, """SELECT m.producto_id, p.nombre, u.nombre ubicacion, u.tipo tipo_ubicacion, m.disponible, m.dias_stock, m.dias_sin_venta,
                                      m.capital, m.riesgo_vencimiento FROM metricas_producto_actual m JOIN productos p ON p.id = m.producto_id
                               JOIN ubicaciones u ON u.id = m.ubicacion_id"""):
        est = estado_stock(m, sobre, muerto, red)
        if est:
            dist[est] += m["capital"] or 0
            if est != "sano":
                top.append({"producto": m["nombre"], "sucursal": m["ubicacion"], "estado": est, "capital": m["capital"], "dias_stock": m["dias_stock"]})
    riesgo = db.fila(conn, "SELECT coalesce(sum(riesgo_vencimiento), 0) r FROM metricas_producto_actual")["r"]
    return {"capital": dist, "riesgo_vencimiento": riesgo, "mas_plata_parada": sorted(top, key=lambda x: -(x["capital"] or 0))[:10],
            "umbrales_dias": {"sobrestock": sobre, "muerto": muerto}}


def _t_proponer(conn, ctx, e):
    permiso = {"orden_compra": "crear_oc", "transferencia": "aprobar_transferencias", "oferta": "remarcar"}[e["tipo"]]
    if not permisos.puede(ctx, permiso):
        return {"error": "Tu rol no puede crear esa acción; podés pedírselo al dueño o al comprador."}
    items = []
    for it in e["items"]:
        p = db.fila(conn, "SELECT nombre FROM productos WHERE id=%s", (it["producto_id"],))
        u = db.fila(conn, "SELECT nombre FROM ubicaciones WHERE id=%s", (it["ubicacion_id"],))
        if not p or not u:
            return {"error": f"No encontré el producto {it['producto_id']} o la sucursal {it['ubicacion_id']}."}
        items.append({**it, "producto": p["nombre"], "sucursal": u["nombre"]})
    return {"propuesta": {"tipo": e["tipo"], "motivo": e["motivo"], "items": items},
            "nota": "La propuesta se muestra con un botón para que la persona la confirme. Todavía no se hizo nada."}


EJECUTORES = {"contexto": _t_contexto, "ventas": _t_ventas, "ranking_productos": _t_ranking, "buscar_producto": _t_buscar,
              "explicar_sugerencia": _t_explicar, "que_comprar": _t_comprar, "alertas_abiertas": _t_alertas, "plata_parada": _t_plata,
              "proponer_accion": _t_proponer}


def ejecutar(ctx, nombre: str, entrada: dict):
    if nombre not in EJECUTORES:
        return {"error": f"Herramienta desconocida: {nombre}"}
    try:
        with db.transaccion(ctx) as conn:
            return _json(EJECUTORES[nombre](conn, ctx, entrada))
    except (ValueError, KeyError, TypeError) as e:
        return {"error": f"Datos inválidos para {nombre}: {e}"}


@dataclass
class Respuesta:
    texto: str
    herramientas: list[dict] = field(default_factory=list)
    propuestas: list[dict] = field(default_factory=list)
    historial: list[dict] = field(default_factory=list)


def _cliente():
    import anthropic  # importación diferida: las pruebas usan un cliente falso
    return anthropic.Anthropic()


def responder(ctx, mensaje: str, historial: list[dict] | None = None, cliente=None) -> Respuesta:
    import anthropic
    cliente = cliente or _cliente()
    mensajes = list(historial or []) + [{"role": "user", "content": mensaje}]
    usadas, propuestas = [], []
    for _ in range(MAX_VUELTAS):
        try:
            r = cliente.messages.create(model=config.ANTHROPIC_MODEL, max_tokens=16000, system=SISTEMA, tools=HERRAMIENTAS,
                                        output_config={"effort": "medium"}, messages=mensajes)
        except anthropic.AuthenticationError:
            return Respuesta("Falta configurar la clave de la IA (ANTHROPIC_API_KEY en backend/.env).", historial=list(historial or []))
        except anthropic.RateLimitError:
            return Respuesta("La IA está ocupada. Probá de nuevo en un minuto.", historial=list(historial or []))
        except (anthropic.APIConnectionError, anthropic.APIStatusError):
            return Respuesta("No pude conectarme con la IA. Probá de nuevo en un rato.", historial=list(historial or []))
        contenido = [b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else b for b in r.content]
        mensajes.append({"role": "assistant", "content": contenido})
        if r.stop_reason == "refusal":
            return Respuesta("No puedo responder eso.", usadas, propuestas, mensajes)
        if r.stop_reason != "tool_use":
            texto = "\n".join(b["text"] for b in contenido if b.get("type") == "text").strip()
            return Respuesta(texto or "No tengo una respuesta para eso.", usadas, propuestas, mensajes)
        resultados = []
        for b in contenido:
            if b.get("type") != "tool_use":
                continue
            salida = ejecutar(ctx, b["name"], b.get("input") or {})
            usadas.append({"herramienta": b["name"], "entrada": b.get("input") or {}})
            if b["name"] == "proponer_accion" and isinstance(salida, dict) and salida.get("propuesta"):
                propuestas.append(salida["propuesta"])
            resultados.append({"type": "tool_result", "tool_use_id": b["id"], "content": json.dumps(salida, ensure_ascii=False)})
        mensajes.append({"role": "user", "content": resultados})
    return Respuesta("No pude completar la respuesta en el límite de pasos. Probá con una pregunta más concreta.", usadas, propuestas, mensajes)
