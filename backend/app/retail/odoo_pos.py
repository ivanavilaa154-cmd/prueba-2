"""Conexión con Odoo Punto de Venta (sección 5.1), en solo lectura.

- Credenciales: URL, base, usuario y API key de Odoo. La clave se guarda cifrada (cifrado.py) y nunca se devuelve.
- Detección: se leen los almacenes y las cajas (pos.config) de Odoo y se propone a qué sucursal corresponde cada uno;
  la persona confirma antes de sincronizar nada.
- Sincronización: productos (product.product), tickets (pos.order + líneas + pagos) y stock (stock.quant).
  Idempotente: cada ticket se identifica por conexión + id de Odoo, así que resincronizar no duplica.
  Se sincroniza desde la última marca de agua menos dos días (tickets que se cierran tarde).
- Reutiliza el cliente JSON-RPC de la integración de Odoo del ERP, que bloquea en código cualquier escritura.
"""
from __future__ import annotations

import json
import time as _time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..integraciones.odoo import ClienteOdoo, OdooError, _id, _nombre
from . import catalogo, cifrado, db

FORMATO = "%Y-%m-%d %H:%M:%S"
HISTORIAL_DIAS = 400
SOLAPE = timedelta(days=2)
MEDIOS = [("efectivo", "efectivo"), ("cash", "efectivo"), ("debito", "debito"), ("débito", "debito"), ("debit", "debito"),
          ("credito", "credito"), ("crédito", "credito"), ("credit", "credito"), ("tarjeta", "credito"), ("card", "credito"),
          ("qr", "qr"), ("mercado", "qr"), ("modo", "qr"), ("transfer", "transferencia"), ("cuenta", "cuenta_corriente"),
          ("account", "cuenta_corriente"), ("fiado", "cuenta_corriente")]


def medio_de(nombre: str | None) -> str:
    n = (nombre or "").lower()
    return next((m for clave, m in MEDIOS if clave in n), "efectivo" if not n else "credito")


def cliente_de(datos: dict, transporte=None) -> ClienteOdoo:
    return ClienteOdoo(datos["url"], datos["base"], datos["usuario"], datos["api_key"], transporte=transporte)


def _utc(texto: str) -> datetime:
    return datetime.strptime(texto[:19], FORMATO).replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------------------ detección
def detectar(conn, c: ClienteOdoo) -> dict:
    """Prueba la conexión y lista almacenes y cajas de Odoo con la sucursal sugerida para cada uno."""
    try:
        version = c._llamar("common", "version").get("server_version")
        c.uid
    except OdooError as e:
        raise ValueError(str(e))
    except OSError as e:
        raise ValueError(f"No se pudo conectar con Odoo: revisá la URL ({e}).")
    if not c.puede_leer("pos.order"):
        raise ValueError("El usuario de Odoo no puede leer el Punto de Venta: dale el rol «Punto de Venta: Usuario».")
    almacenes = list(c.leer_todo("stock.warehouse", [], ["name", "code", "lot_stock_id"])) if c.puede_leer("stock.warehouse") else []
    cajas = list(c.leer_todo("pos.config", [], c._solo_existentes("pos.config", ["name", "picking_type_id"])))
    tipos = c.leer_ids("stock.picking.type", [_id(x.get("picking_type_id")) for x in cajas], ["warehouse_id"]) if cajas else {}
    ubicaciones = db.filas(conn, "SELECT id, nombre, codigo_externo FROM ubicaciones WHERE activa ORDER BY id")

    def sugerida(nombre: str, codigo: str | None, clave: str) -> int | None:
        for u in ubicaciones:
            if u["codigo_externo"] == clave:
                return u["id"]
        puntajes = sorted(((max(catalogo.similitud(nombre, u["nombre"]), catalogo.similitud(codigo, u["nombre"]) if codigo else 0), u)
                           for u in ubicaciones), key=lambda x: -x[0])
        return puntajes[0][1]["id"] if puntajes and puntajes[0][0] >= 0.5 else None
    return {
        "version": version,
        "almacenes": [{"id": a["id"], "nombre": a["name"], "codigo": a.get("code"), "ubicacion_sugerida": sugerida(a["name"], a.get("code"), f"odoo:almacen:{a['id']}")}
                      for a in almacenes],
        "cajas": [{"id": x["id"], "nombre": x["name"], "almacen_id": _id(tipos.get(_id(x.get("picking_type_id")), {}).get("warehouse_id"))} for x in cajas],
        "conteos": {"tickets": c.ejecutar("pos.order", "search_count", [[("state", "in", ["paid", "done", "invoiced"])]]),
                    "productos": c.ejecutar("product.product", "search_count", [[("sale_ok", "=", True)]])},
    }


# ------------------------------------------------------------------------------ guardar la conexión
def guardar(conn, ctx, datos: dict, almacenes: dict[int, int | None], plataforma_id: int | None = None) -> int:
    """datos: url, base, usuario, api_key (opcional al editar). almacenes: {almacén de Odoo: sucursal}."""
    config = {"url": datos["url"].rstrip("/"), "base": datos["base"], "usuario": datos["usuario"],
              "almacenes": {str(k): v for k, v in almacenes.items() if v}}
    with conn.cursor() as cur:
        if plataforma_id:
            actual = db.fila(conn, "SELECT credenciales_cifradas FROM plataformas WHERE id=%s AND tipo='odoo'", (plataforma_id,))
            if not actual:
                raise ValueError("No existe esa conexión.")
            clave = datos.get("api_key") or cifrado.descifrar(actual["credenciales_cifradas"]).get("api_key")
            cur.execute("UPDATE plataformas SET config=%s, credenciales_cifradas=%s, activa=true, updated_at=now() WHERE id=%s",
                        (json.dumps(config), cifrado.cifrar({"api_key": clave}), plataforma_id))
        else:
            canal = db.fila(conn, "SELECT id FROM canales WHERE codigo='fisico'")["id"]
            plataforma_id = db.fila(conn, "INSERT INTO plataformas (org_id, tipo, nombre, canal_id, config, credenciales_cifradas, estado_sincronizacion, created_by) "
                                          "VALUES (%s,'odoo',%s,%s,%s,%s,'sin_probar',%s) RETURNING id",
                                    (ctx.org_id, f"Odoo · {config['base']}", canal, json.dumps(config), cifrado.cifrar({"api_key": datos["api_key"]}),
                                     ctx.usuario_id))["id"]
        for almacen, ubicacion in almacenes.items():
            if ubicacion:
                cur.execute("UPDATE ubicaciones SET codigo_externo=%s, updated_at=now() WHERE id=%s", (f"odoo:almacen:{almacen}", ubicacion))
    return plataforma_id


def cliente_guardado(plataforma: dict, transporte=None) -> ClienteOdoo:
    cfg = plataforma["config"]
    return cliente_de({**cfg, "api_key": cifrado.descifrar(plataforma["credenciales_cifradas"]).get("api_key")}, transporte)


# ------------------------------------------------------------------------------ sincronizar
def sincronizar(conn, ctx, plataforma_id: int, transporte=None, hoy: date | None = None) -> dict:
    t0 = _time.time()
    p = db.fila(conn, "SELECT * FROM plataformas WHERE id=%s AND tipo='odoo' AND activa", (plataforma_id,))
    if not p:
        raise ValueError("No existe esa conexión o está desactivada.")
    c = cliente_guardado(p, transporte)
    almacenes = {int(k): v for k, v in (p["config"].get("almacenes") or {}).items()}
    if not almacenes:
        raise ValueError("Primero confirmá a qué sucursal corresponde cada almacén de Odoo.")
    zona = ZoneInfo(db.fila(conn, "SELECT zona_horaria FROM organizaciones WHERE id = app_org()")["zona_horaria"])
    hoy = hoy or datetime.now(zona).date()
    desde = (p["sincronizado_hasta"] - SOLAPE) if p["sincronizado_hasta"] else datetime.combine(hoy - timedelta(days=HISTORIAL_DIAS), datetime.min.time(), timezone.utc)
    try:
        productos = _productos(conn, ctx, c, plataforma_id)
        ventas = _tickets(conn, ctx, c, plataforma_id, almacenes, productos, desde, zona)
        stock = _stock(conn, ctx, c, almacenes, productos)
    except OdooError as e:
        raise ValueError(f"Odoo respondió con un error: {e}")
    except OSError as e:
        raise ValueError(f"No se pudo conectar con Odoo ({e}).")
    resultado = {**ventas, **stock, "productos_nuevos": productos["nuevos"], "segundos": round(_time.time() - t0, 1)}
    resultado["mensaje"] = (f"{ventas['tickets_nuevos']} tickets nuevos" + (f" ({ventas['tickets_repetidos']} ya estaban)" if ventas["tickets_repetidos"] else "")
                            + f", stock de {stock['stock_actualizado']} productos × sucursal"
                            + (f", {productos['nuevos']} productos nuevos" if productos["nuevos"] else ""))
    with conn.cursor() as cur:
        cur.execute("UPDATE plataformas SET estado_sincronizacion='ok', error_sincronizacion=NULL, ultima_sincronizacion=now(), "
                    "sincronizado_hasta=greatest(coalesce(sincronizado_hasta, %s), %s) WHERE id=%s",
                    (ventas["hasta"] or desde, ventas["hasta"] or desde, plataforma_id))
        cur.execute("INSERT INTO lotes_importacion (org_id, tipo, origen, nombre_archivo, huella, estado, filas_total, filas_ok, filas_duplicadas, resultado, created_by) "
                    "VALUES (%s,'sincronizacion','odoo',%s,%s,'importado',%s,%s,%s,%s,%s)",
                    (ctx.org_id, p["nombre"], f"odoo:{plataforma_id}:{_time.time()}", ventas["tickets_nuevos"] + ventas["tickets_repetidos"],
                     ventas["tickets_nuevos"], ventas["tickets_repetidos"], json.dumps(resultado, default=str), ctx.usuario_id or None))
    return resultado


def _productos(conn, ctx, c: ClienteOdoo, plataforma_id: int) -> dict:
    """Mapa id de Odoo → producto. Empareja por alias guardado, código de barras o código interno; si no existe, lo crea."""
    conocidos = {int(a["codigo"].split(":")[1]): a["producto_id"] for a in
                 db.filas(conn, "SELECT codigo, producto_id FROM alias_producto WHERE origen='caja' AND origen_id=%s AND codigo LIKE 'odoo:%%'", (plataforma_id,))}
    campos = c._solo_existentes("product.product", ["default_code", "barcode", "name", "lst_price", "uom_id", "categ_id"])
    por_ean = {p["ean"]: p["id"] for p in db.filas(conn, "SELECT id, ean FROM productos WHERE ean IS NOT NULL")}
    por_codigo = {p["codigo_interno"]: p["id"] for p in db.filas(conn, "SELECT id, codigo_interno FROM productos")}
    nuevos = 0
    hoy = date.today()
    with conn.cursor() as cur:
        for o in c.leer_todo("product.product", [("sale_ok", "=", True)], campos, {"active_test": False}):
            if o["id"] in conocidos:
                continue
            ean = o.get("barcode") or None
            codigo = o.get("default_code") or None
            pid = por_ean.get(ean) if ean else None
            pid = pid or (por_codigo.get(codigo) if codigo else None)
            if not pid:
                codigo_nuevo = codigo if codigo and codigo not in por_codigo else f"ODOO-{o['id']}"
                maestro, estado = catalogo.vincular_maestro(conn, {"ean": ean})
                unidad = "kg" if "kg" in (_nombre(o.get("uom_id")) or "").lower() else "unidad"
                pid = db.fila(conn, "INSERT INTO productos (org_id, maestro_id, codigo_interno, nombre, ean, unidad, estado_mapeo, created_by) "
                                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                              (ctx.org_id, maestro, codigo_nuevo, o["name"], ean, unidad, estado, ctx.usuario_id or None))["id"]
                por_codigo[codigo_nuevo] = pid
                if o.get("lst_price"):
                    cur.execute("INSERT INTO precios (org_id, producto_id, precio, desde, origen, created_by) VALUES (%s,%s,%s,%s,'importado',%s)",
                                (ctx.org_id, pid, Decimal(str(o["lst_price"])), hoy, ctx.usuario_id or None))
                nuevos += 1
            cur.execute("INSERT INTO alias_producto (org_id, producto_id, origen, origen_id, codigo, texto, created_by) VALUES (%s,%s,'caja',%s,%s,%s,%s)",
                        (ctx.org_id, pid, plataforma_id, f"odoo:{o['id']}", o["name"], ctx.usuario_id or None))
            conocidos[o["id"]] = pid
    return {"mapa": conocidos, "nuevos": nuevos}


def _tickets(conn, ctx, c: ClienteOdoo, plataforma_id: int, almacenes: dict, productos: dict, desde: datetime, zona) -> dict:
    cajas = list(c.leer_todo("pos.config", [], c._solo_existentes("pos.config", ["name", "picking_type_id"])))
    tipos = c.leer_ids("stock.picking.type", [_id(x.get("picking_type_id")) for x in cajas], ["warehouse_id"]) if cajas else {}
    caja_ubicacion = {x["id"]: almacenes.get(_id(tipos.get(_id(x.get("picking_type_id")), {}).get("warehouse_id"))) for x in cajas}
    caja_nombre = {x["id"]: x["name"] for x in cajas}
    mapeadas = [k for k, v in caja_ubicacion.items() if v]
    if not mapeadas:
        return {"tickets_nuevos": 0, "tickets_repetidos": 0, "lineas": 0, "desde": None, "hasta": None, "cajas_sin_sucursal": len(cajas)}
    campos = c._solo_existentes("pos.order", ["name", "date_order", "config_id", "user_id", "amount_total", "state", "partner_id"])
    ordenes = list(c.leer_todo("pos.order", [("date_order", ">=", desde.astimezone(timezone.utc).strftime(FORMATO)),
                                             ("state", "in", ["paid", "done", "invoiced"]), ("config_id", "in", mapeadas)], campos))
    existentes = {t["numero_externo"] for t in db.filas(conn, "SELECT numero_externo FROM tickets WHERE origen='odoo' AND numero_externo LIKE %s",
                                                            (f"{plataforma_id}-%",))}
    nuevas = [o for o in ordenes if f"{plataforma_id}-{o['id']}" not in existentes]
    canal = db.fila(conn, "SELECT id FROM canales WHERE codigo='fisico'")["id"]
    campos_l = c._solo_existentes("pos.order.line", ["order_id", "product_id", "qty", "price_unit", "discount", "price_subtotal",
                                                     "price_subtotal_incl", "total_cost"])
    lineas = defaultdict(list)
    pagos = defaultdict(list)
    for lote in [nuevas[i:i + 500] for i in range(0, len(nuevas), 500)]:
        ids = [o["id"] for o in lote]
        for l in c.leer_todo("pos.order.line", [("order_id", "in", ids)], campos_l):
            lineas[_id(l["order_id"])].append(l)
        if c.puede_leer("pos.payment"):
            for pg in c.leer_todo("pos.payment", [("pos_order_id", "in", ids)], ["pos_order_id", "amount", "payment_method_id"]):
                pagos[_id(pg["pos_order_id"])].append(pg)
    n_lineas = 0
    fechas = []
    with conn.cursor() as cur:
        for o in nuevas:
            uid = caja_ubicacion[_id(o["config_id"])]
            fh = _utc(o["date_order"])
            fecha = fh.astimezone(zona).date()
            ls = [l for l in lineas.get(o["id"], []) if _id(l.get("product_id")) in productos["mapa"]]
            total = Decimal(str(o["amount_total"])) if o.get("amount_total") is not None else \
                sum((Decimal(str(l.get("price_subtotal_incl", l.get("price_subtotal")) or 0)) for l in ls), Decimal(0))
            t = db.fila(conn, "INSERT INTO tickets (org_id, ubicacion_id, canal_id, punto_venta, cajero, fecha_hora, total, estado, numero_externo, origen) "
                              "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'odoo') ON CONFLICT (org_id, origen, numero_externo) DO NOTHING RETURNING id",
                        (ctx.org_id, uid, canal, caja_nombre.get(_id(o["config_id"])), _nombre(o.get("user_id")), fh, total,
                         "devuelto" if total < 0 else "confirmado", f"{plataforma_id}-{o['id']}"))
            if not t:
                continue
            fechas.append(fh)
            for l in ls:
                cant = Decimal(str(l.get("qty") or 0))
                if not cant:
                    continue
                con_iva = Decimal(str(l.get("price_subtotal_incl", l.get("price_subtotal")) or 0))
                cobrado = (con_iva / cant).quantize(Decimal("0.0001"))
                lista = max(Decimal(str(l.get("price_unit") or 0)), cobrado) if cant > 0 else cobrado
                descuento = ((lista - cobrado) * cant).quantize(Decimal("0.01")) if cant > 0 else Decimal(0)
                costo = (Decimal(str(l["total_cost"])) / cant).quantize(Decimal("0.0001")) if l.get("total_cost") else None
                cur.execute("INSERT INTO tickets_lineas (org_id, ticket_id, ubicacion_id, fecha, producto_id, cantidad, precio_lista, precio_cobrado, descuento, costo_unitario) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (ctx.org_id, t["id"], uid, fecha, productos["mapa"][_id(l["product_id"])], cant, lista, cobrado, descuento, costo))
                n_lineas += 1
            for pg in pagos.get(o["id"], []):
                cur.execute("INSERT INTO pagos (org_id, ticket_id, ubicacion_id, medio, monto) VALUES (%s,%s,%s,%s,%s)",
                            (ctx.org_id, t["id"], uid, medio_de(_nombre(pg.get("payment_method_id"))), Decimal(str(pg.get("amount") or 0))))
    todas = [_utc(o["date_order"]) for o in ordenes]
    return {"tickets_nuevos": len(fechas), "tickets_repetidos": len(ordenes) - len(fechas), "lineas": n_lineas,
            "desde": min(fechas).astimezone(zona).date() if fechas else None, "hasta": max(todas) if todas else None,
            "cajas_sin_sucursal": len(cajas) - len(mapeadas)}


def _stock(conn, ctx, c: ClienteOdoo, almacenes: dict, productos: dict) -> dict:
    if not c.puede_leer("stock.quant"):
        return {"stock_actualizado": 0}
    lotes_stock = {_id(a.get("lot_stock_id")): a["id"] for a in c.leer_todo("stock.warehouse", [], ["lot_stock_id"])}
    quants = list(c.leer_todo("stock.quant", [("location_id.usage", "=", "internal")], ["product_id", "quantity", "location_id"]))
    ubic_ids = {_id(q["location_id"]) if isinstance(q["location_id"], list) else q["location_id"] for q in quants}
    ubic = c.leer_ids("stock.location", ubic_ids, c._solo_existentes("stock.location", ["warehouse_id"])) if c.puede_leer("stock.location") else {}
    total: dict = defaultdict(Decimal)
    for q in quants:
        loc = _id(q["location_id"]) if isinstance(q["location_id"], list) else q["location_id"]
        almacen = _id(ubic.get(loc, {}).get("warehouse_id")) or lotes_stock.get(loc)
        destino = almacenes.get(almacen)
        pid = productos["mapa"].get(_id(q["product_id"]))
        if destino and pid:
            total[(pid, destino)] += Decimal(str(q.get("quantity") or 0))
    anteriores = {(s["producto_id"], s["ubicacion_id"]): s["cantidad"] for s in db.filas(conn, "SELECT producto_id, ubicacion_id, cantidad FROM stock_actual")}
    destinos = set(almacenes.values())
    # Lo que Odoo ya no tiene en esas sucursales queda en cero.
    for (pid, uid), cant in anteriores.items():
        if uid in destinos and (pid, uid) not in total and cant and pid in set(productos["mapa"].values()):
            total[(pid, uid)] = Decimal(0)
    n = 0
    with conn.cursor() as cur:
        for (pid, uid), cant in total.items():
            antes = anteriores.get((pid, uid))
            if antes == cant:
                continue
            cur.execute("INSERT INTO stock_actual (org_id, producto_id, ubicacion_id, cantidad) VALUES (%s,%s,%s,%s) ON CONFLICT (producto_id, ubicacion_id) "
                        "DO UPDATE SET cantidad=EXCLUDED.cantidad, actualizado_at=now()", (ctx.org_id, pid, uid, cant))
            cur.execute("INSERT INTO movimientos_stock (org_id, producto_id, ubicacion_id, tipo, cantidad, documento_tipo, motivo, usuario_id) "
                        "VALUES (%s,%s,%s,%s,%s,'sincronizacion','Stock de Odoo',%s)",
                        (ctx.org_id, pid, uid, "inicial" if antes is None else "ajuste", cant - (antes or 0), ctx.usuario_id or None))
            n += 1
    return {"stock_actualizado": n}


def sincronizar_todas(org_id: int) -> date | None:
    from .plataformas_online import TIENDAS
    """Sincroniza cada conexión activa de la empresa (Odoo y tiendas online) (lo usa el programador cada hora). Devuelve la fecha más vieja
    con tickets nuevos, para reagregar desde ahí."""
    from .motor import contexto_sistema
    ctx = contexto_sistema(org_id)
    with db.transaccion(ctx) as conn:
        conexiones = db.filas(conn, "SELECT id, tipo FROM plataformas WHERE activa AND ((tipo='odoo' AND config ? 'almacenes') "
                                    "OR (tipo = ANY(%s) AND credenciales_cifradas IS NOT NULL))", (list(TIENDAS),))
    desde = None
    for x in conexiones:
        pid = x["id"]
        try:
            with db.transaccion(ctx) as conn:
                if x["tipo"] == "odoo":
                    r = sincronizar(conn, ctx, pid)
                else:
                    from . import plataformas_online
                    r = plataformas_online.sincronizar(conn, ctx, pid)
            if r.get("desde") and (desde is None or r["desde"] < desde):
                desde = r["desde"]
        except Exception as e:           # una conexión caída no frena a las demás; el error queda en la conexión
            marcar_error(ctx, pid, e)
    if conexiones:
        from . import stock_publicado      # el stock del local cambió con las ventas de la caja: revisar lo publicado
        with db.transaccion(ctx) as conn:
            stock_publicado.proponer(conn)
    return desde


def marcar_error(ctx, plataforma_id: int, error: Exception) -> None:
    """En una transacción aparte: la de la sincronización se deshizo."""
    with db.transaccion(ctx) as conn, conn.cursor() as cur:
        cur.execute("UPDATE plataformas SET estado_sincronizacion='error', error_sincronizacion=%s, ultima_sincronizacion=now() WHERE id=%s",
                    (str(error)[:500], plataforma_id))
