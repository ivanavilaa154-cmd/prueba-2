"""Odoo para el modo distribuidor (SPEC v2, 5.1 y 12B), en solo lectura y con la misma conexión que el Punto de Venta.

- Vendedores: los usuarios de Odoo que figuran como vendedor de clientes o pedidos (res.users), codigo_externo odoo:usuario:<id>.
- Clientes: res.partner con ventas (customer_rank > 0) y sin empresa padre; los contactos hijos se cuentan como su empresa.
- Pedidos: sale.order confirmados (state sale/done) o cancelados, con sus líneas. Lo entregado sale de qty_delivered; si un pedido
  cambia (entregas posteriores), se actualiza en la siguiente sincronización.
- Cuenta corriente: facturas y notas de crédito publicadas (account.move) con su saldo pendiente (amount_residual) y los cobros
  (account.payment) como recibos ya aplicados (saldo 0: el saldo pendiente ya está en cada factura).
"""
from __future__ import annotations

from datetime import date, datetime

from ..integraciones.odoo import ClienteOdoo, _id, _nombre
from . import db

FORMATO = "%Y-%m-%d %H:%M:%S"


def _fecha(texto) -> date | None:
    if not texto:
        return None
    return datetime.strptime(str(texto)[:10], "%Y-%m-%d").date()


def _vendedor(conn, ctx, cache: dict, m2o) -> int | None:
    uid = _id(m2o)
    if not uid:
        return None
    if uid not in cache:
        clave = f"odoo:usuario:{uid}"
        f = db.fila(conn, """INSERT INTO vendedores (org_id, nombre, codigo_externo, created_by) VALUES (%s,%s,%s,%s)
                             ON CONFLICT (org_id, codigo_externo) DO UPDATE SET nombre = EXCLUDED.nombre RETURNING id""",
                    (ctx.org_id, _nombre(m2o) or f"Vendedor {uid}", clave, ctx.usuario_id or None))
        cache[uid] = f["id"]
    return cache[uid]


def sincronizar(conn, ctx, c: ClienteOdoo, plataforma_id: int, almacenes: dict, productos: dict, desde: datetime) -> dict:
    vendedores: dict[int, int] = {}
    clientes = _clientes(conn, ctx, c, vendedores)
    pedidos = _pedidos(conn, ctx, c, plataforma_id, almacenes, productos, clientes, vendedores, desde)
    cc = _cuenta_corriente(conn, ctx, c, plataforma_id, clientes, desde)
    return {"clientes_nuevos": clientes["nuevos"], **pedidos, **cc}


def _clientes(conn, ctx, c: ClienteOdoo, vendedores: dict) -> dict:
    campos = c._solo_existentes("res.partner", ["name", "vat", "street", "city", "state_id", "user_id", "credit_limit", "category_id",
                                                "customer_rank", "property_payment_term_id", "commercial_partner_id"])
    dominio = [("parent_id", "=", False)] + ([("customer_rank", ">", 0)] if "customer_rank" in campos else [])
    mapa = {int(f["codigo_externo"].split(":")[2]): f["id"] for f in
            db.filas(conn, "SELECT id, codigo_externo FROM clientes_b2b WHERE codigo_externo LIKE 'odoo:partner:%%'")}
    nuevos = 0
    for p in c.leer_todo("res.partner", dominio, campos, {"active_test": False}):
        etiquetas = p.get("category_id") or []
        canal = None
        if etiquetas and isinstance(etiquetas, list) and isinstance(etiquetas[0], (list, tuple)):
            canal = str(etiquetas[0][1]).lower()
        f = db.fila(conn, """
            INSERT INTO clientes_b2b (org_id, codigo_externo, razon_social, cuit, direccion, localidad, zona, canal, limite_credito, vendedor_id, alta, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (org_id, codigo_externo) DO UPDATE SET razon_social = EXCLUDED.razon_social, cuit = EXCLUDED.cuit, direccion = EXCLUDED.direccion,
                localidad = EXCLUDED.localidad, zona = coalesce(clientes_b2b.zona, EXCLUDED.zona), canal = coalesce(clientes_b2b.canal, EXCLUDED.canal),
                limite_credito = EXCLUDED.limite_credito, vendedor_id = coalesce(EXCLUDED.vendedor_id, clientes_b2b.vendedor_id), updated_at = now()
            RETURNING id, (xmax = 0) AS nuevo""",
                    (ctx.org_id, f"odoo:partner:{p['id']}", p["name"], p.get("vat") or None, p.get("street") or None, p.get("city") or None,
                     _nombre(p.get("state_id")) or p.get("city") or None, canal, p.get("credit_limit") or None,
                     _vendedor(conn, ctx, vendedores, p.get("user_id")), date.today(), ctx.usuario_id or None))
        mapa[p["id"]] = f["id"]
        nuevos += f["nuevo"]
    return {"mapa": mapa, "nuevos": nuevos}


def _cliente_de(conn, ctx, c: ClienteOdoo, clientes: dict, m2o) -> int | None:
    """Un pedido puede estar a nombre de un contacto hijo: se busca su empresa (commercial_partner_id)."""
    pid = _id(m2o)
    if not pid:
        return None
    if pid not in clientes["mapa"]:
        p = c.leer_ids("res.partner", [pid], c._solo_existentes("res.partner", ["commercial_partner_id", "name"])).get(pid, {})
        padre = _id(p.get("commercial_partner_id"))
        if padre and padre in clientes["mapa"]:
            clientes["mapa"][pid] = clientes["mapa"][padre]
        else:
            clientes["mapa"][pid] = db.fila(conn, """INSERT INTO clientes_b2b (org_id, codigo_externo, razon_social, alta, created_by)
                                                     VALUES (%s,%s,%s,%s,%s) ON CONFLICT (org_id, codigo_externo) DO UPDATE SET updated_at = now()
                                                     RETURNING id""",
                                            (ctx.org_id, f"odoo:partner:{pid}", p.get("name") or _nombre(m2o) or f"Cliente {pid}", date.today(),
                                             ctx.usuario_id or None))["id"]
    return clientes["mapa"][pid]


def _pedidos(conn, ctx, c: ClienteOdoo, plataforma_id: int, almacenes: dict, productos: dict, clientes: dict, vendedores: dict, desde: datetime) -> dict:
    campos = c._solo_existentes("sale.order", ["name", "partner_id", "user_id", "date_order", "state", "warehouse_id", "amount_untaxed", "commitment_date"])
    ordenes = list(c.leer_todo("sale.order", [("state", "in", ["sale", "done", "cancel"]), ("write_date", ">=", desde.strftime(FORMATO))], campos))
    if not ordenes:
        return {"pedidos_nuevos": 0, "pedidos_actualizados": 0, "entregas": 0, "desde_pedidos": None}
    campos_l = c._solo_existentes("sale.order.line", ["order_id", "product_id", "product_uom_qty", "qty_delivered", "price_unit", "discount",
                                                      "price_subtotal", "purchase_price", "display_type"])
    lineas: dict[int, list] = {}
    ids = [o["id"] for o in ordenes]
    for i in range(0, len(ids), 500):
        for l in c.leer_todo("sale.order.line", [("order_id", "in", ids[i:i + 500])], campos_l):
            if l.get("display_type") or not _id(l.get("product_id")):
                continue
            lineas.setdefault(_id(l["order_id"]), []).append(l)
    nuevos = actualizados = 0
    fechas = []
    estados: dict[int, tuple[int, str]] = {}
    mapa_productos = productos["mapa"]
    with conn.cursor() as cur:
        for o in ordenes:
            cliente_id = _cliente_de(conn, ctx, c, clientes, o.get("partner_id"))
            if not cliente_id:
                continue
            detalle = []
            for l in lineas.get(o["id"], []):
                pid = mapa_productos.get(_id(l["product_id"]))
                if not pid:
                    continue
                pedida = float(l.get("product_uom_qty") or 0)
                entregada = float(l.get("qty_delivered") or 0)
                lista = float(l.get("price_unit") or 0)
                precio = float(l["price_subtotal"]) / pedida if pedida and l.get("price_subtotal") is not None else lista * (1 - float(l.get("discount") or 0) / 100)
                detalle.append((pid, pedida, entregada, lista, precio, l.get("purchase_price") or None))
            if o["state"] == "cancel":
                estado = "anulado"
            elif not detalle or all(d[2] == 0 for d in detalle):
                estado = "tomado"
            elif all(d[2] >= d[1] for d in detalle):
                estado = "entregado"
            else:
                estado = "entregado_parcial"
            fecha = _fecha(o["date_order"])
            total = sum(d[1] * d[4] for d in detalle)
            total_entregado = sum(min(d[2], d[1]) * d[4] for d in detalle)
            r = db.fila(conn, """
                INSERT INTO pedidos_venta (org_id, numero, cliente_id, vendedor_id, ubicacion_id, fecha, fecha_entrega_prometida, estado, total,
                                           total_entregado, descuento, origen, numero_externo, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'odoo',%s,%s)
                ON CONFLICT (org_id, origen, numero_externo) DO UPDATE SET estado = EXCLUDED.estado, total = EXCLUDED.total,
                    total_entregado = EXCLUDED.total_entregado, updated_at = now()
                RETURNING id, (xmax = 0) AS nuevo""",
                        (ctx.org_id, o["name"], cliente_id, _vendedor(conn, ctx, vendedores, o.get("user_id")), almacenes.get(_id(o.get("warehouse_id"))),
                         fecha, _fecha(o.get("commitment_date")), estado, total, total_entregado, sum(max(0, d[3] - d[4]) * d[1] for d in detalle),
                         f"odoo:{plataforma_id}:{o['id']}", ctx.usuario_id or None))
            if not r["nuevo"]:
                cur.execute("DELETE FROM pedidos_venta_lineas WHERE pedido_id = %s", (r["id"],))
            for pid, pedida, entregada, lista, precio, costo in detalle:
                cur.execute("""INSERT INTO pedidos_venta_lineas (org_id, pedido_id, producto_id, cantidad_pedida, cantidad_entregada, precio_lista, precio,
                                                                 descuento, costo_unitario) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (ctx.org_id, r["id"], pid, pedida, min(entregada, pedida), lista, precio, max(0, lista - precio) * pedida, costo))
            nuevos += r["nuevo"]
            actualizados += not r["nuevo"]
            fechas.append(fecha)
            estados[o["id"]] = (r["id"], estado)
    entregas = _entregas(conn, ctx, c, estados)
    return {"pedidos_nuevos": nuevos, "pedidos_actualizados": actualizados, "entregas": entregas, "desde_pedidos": min(fechas) if fechas else None}


def _entregas(conn, ctx, c: ClienteOdoo, estados: dict[int, tuple[int, str]]) -> int:
    """Fecha real de entrega (12B.5): la última salida terminada (stock.picking de tipo «outgoing», state done) de cada pedido entregado."""
    entregados = {oid: v for oid, v in estados.items() if v[1] in ("entregado", "entregado_parcial")}
    if not entregados or "date_done" not in c.campos("stock.picking"):      # Odoo sin el módulo de inventario
        return 0
    campos = c._solo_existentes("stock.picking", ["sale_id", "date_done", "state", "picking_type_code"])
    ultima: dict[int, date] = {}
    ids = list(entregados)
    for i in range(0, len(ids), 500):
        for pk in c.leer_todo("stock.picking", [("sale_id", "in", ids[i:i + 500]), ("state", "=", "done")], campos):
            if pk.get("picking_type_code", "outgoing") != "outgoing" or not pk.get("date_done"):
                continue
            oid, cuando = _id(pk["sale_id"]), _fecha(pk["date_done"])
            if oid in entregados and (oid not in ultima or cuando > ultima[oid]):
                ultima[oid] = cuando
    with conn.cursor() as cur:
        for oid, cuando in ultima.items():
            pedido_id, estado = entregados[oid]
            cur.execute("DELETE FROM entregas WHERE pedido_id = %s", (pedido_id,))
            cur.execute("INSERT INTO entregas (org_id, pedido_id, fecha, resultado, created_by) VALUES (%s,%s,%s,%s,%s)",
                        (ctx.org_id, pedido_id, cuando, "entregado" if estado == "entregado" else "parcial", ctx.usuario_id or None))
    return len(ultima)


def _cuenta_corriente(conn, ctx, c: ClienteOdoo, plataforma_id: int, clientes: dict, desde: datetime) -> dict:
    campos = c._solo_existentes("account.move", ["name", "partner_id", "move_type", "invoice_date", "invoice_date_due", "amount_total",
                                                 "amount_residual", "state"])
    dominio = [("move_type", "in", ["out_invoice", "out_refund"]), ("state", "=", "posted"),
               "|", ("amount_residual", "!=", 0), ("write_date", ">=", desde.strftime(FORMATO))]
    documentos = 0
    vistos = []
    for m in c.leer_todo("account.move", dominio, campos):
        cliente_id = _cliente_de(conn, ctx, c, clientes, m.get("partner_id"))
        if not cliente_id:
            continue
        signo = -1 if m["move_type"] == "out_refund" else 1
        _guardar_doc(conn, ctx, cliente_id, "nota_credito" if signo < 0 else "factura", m["name"], _fecha(m.get("invoice_date")),
                     _fecha(m.get("invoice_date_due")), signo * float(m.get("amount_total") or 0), signo * float(m.get("amount_residual") or 0),
                     f"odoo:{plataforma_id}:move:{m['id']}")
        vistos.append(f"odoo:{plataforma_id}:move:{m['id']}")
        documentos += 1
    # Las facturas que ya no aparecen con saldo y no cambiaron desde la marca de agua quedan como estaban; las que se pagaron después
    # de la última sincronización vienen por write_date y se actualizan arriba.
    cobros = 0
    campos_p = c._solo_existentes("account.payment", ["name", "partner_id", "date", "amount", "partner_type", "state", "payment_type"])
    dominio_p = [("partner_type", "=", "customer"), ("state", "=", "posted"), ("date", ">=", desde.strftime("%Y-%m-%d"))]
    for p in c.leer_todo("account.payment", dominio_p, campos_p):
        cliente_id = _cliente_de(conn, ctx, c, clientes, p.get("partner_id"))
        if not cliente_id or p.get("payment_type", "inbound") != "inbound":
            continue
        _guardar_doc(conn, ctx, cliente_id, "recibo", p.get("name") or f"Cobro {p['id']}", _fecha(p.get("date")), None, -float(p.get("amount") or 0), 0,
                     f"odoo:{plataforma_id}:pago:{p['id']}")
        cobros += 1
    return {"comprobantes": documentos, "cobros": cobros}


def _guardar_doc(conn, ctx, cliente_id: int, tipo: str, numero: str, fecha: date | None, vence: date | None, importe: float, saldo: float, externo: str):
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO documentos_cc (org_id, cliente_id, tipo, numero, fecha, vencimiento, importe, saldo, origen, numero_externo, created_by)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'odoo',%s,%s)
                       ON CONFLICT (org_id, origen, numero_externo) DO UPDATE SET saldo = EXCLUDED.saldo, vencimiento = EXCLUDED.vencimiento,
                           importe = EXCLUDED.importe, updated_at = now()""",
                    (ctx.org_id, cliente_id, tipo, numero, fecha or date.today(), vence, importe, saldo, externo, ctx.usuario_id or None))

