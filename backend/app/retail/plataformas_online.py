"""Conectores de e-commerce (sección 5.4): Tiendanube y Mercado Libre, en solo lectura (solo pedidos GET).

Trae pedidos (con líneas, estado, comisión y envío a cargo del vendedor), publicaciones y stock publicado. Cada venta queda
con canal, plataforma y sucursal que despacha. Idempotente: cada pedido se identifica por plataforma + id del pedido; si el
pedido cambió de estado (despachado, cancelado, devuelto), se actualiza.
El token de acceso lo carga la persona y se guarda cifrado (cifrado.py); nunca se devuelve.
"""
from __future__ import annotations

import json
import time as _time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable
from zoneinfo import ZoneInfo

from . import catalogo, cifrado, db

Transporte = Callable[[str, dict], object]          # (url, headers) -> JSON
SOLAPE = timedelta(days=3)                          # los pedidos cambian de estado: se revisan los últimos días
HISTORIAL_DIAS = 180


class ErrorPlataforma(RuntimeError):
    pass


def _http(url: str, headers: dict, timeout: float = 60):
    pedido = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ErrorPlataforma("La plataforma rechazó el acceso: revisá o renová el token.")
        raise ErrorPlataforma(f"La plataforma respondió {e.code}.")


def _fecha(texto: str | None) -> datetime | None:
    if not texto:
        return None
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


# ------------------------------------------------------------------------------ clientes (solo GET)
class Tiendanube:
    tipo = "tiendanube"

    def __init__(self, store_id: str, token: str, transporte: Transporte | None = None):
        self.base = f"https://api.tiendanube.com/v1/{store_id}"
        self.headers = {"Authentication": f"bearer {token}", "User-Agent": "Retail IA (soporte@retail-ia.app)"}
        self._get = transporte or _http

    def _paginas(self, recurso: str, params: dict):
        pagina = 1
        while True:
            lote = self._get(f"{self.base}/{recurso}?{urllib.parse.urlencode({**params, 'per_page': 200, 'page': pagina})}", self.headers)
            if not lote:
                return
            yield from lote
            if len(lote) < 200:
                return
            pagina += 1

    def probar(self) -> dict:
        tienda = self._get(f"{self.base}/store", self.headers)
        nombre = tienda.get("name")
        return {"nombre": nombre.get("es") if isinstance(nombre, dict) else nombre, "id": tienda.get("id")}

    def publicaciones(self) -> list[dict]:
        salida = []
        for p in self._paginas("products", {}):
            titulo = p.get("name", {}).get("es") if isinstance(p.get("name"), dict) else p.get("name")
            for v in p.get("variants") or []:
                salida.append({"id_externo": str(v["id"]), "sku": v.get("sku") or None, "ean": v.get("barcode") or None, "titulo": titulo,
                               "precio": _dec(v.get("promotional_price") or v.get("price")), "stock": _dec(v.get("stock")) if v.get("stock") is not None else None,
                               "activa": bool(p.get("published", True))})
        return salida

    def pedidos(self, desde: datetime) -> list[dict]:
        salida = []
        for o in self._paginas("orders", {"created_at_min": desde.isoformat()}):
            estado = "cancelado" if o.get("status") == "cancelled" else \
                "entregado" if o.get("shipping_status") == "delivered" else \
                "despachado" if o.get("shipping_status") in ("shipped", "fulfilled") else "pendiente"
            if o.get("payment_status") == "refunded":
                estado = "devuelto"
            if o.get("payment_status") not in ("paid", "refunded", "authorized") and estado == "pendiente":
                continue                                     # pedido sin pagar: todavía no es venta
            salida.append({"id": str(o["id"]), "creado": _fecha(o["created_at"]), "estado": estado, "total": _dec(o.get("total")),
                           "despachado": _fecha(o.get("shipped_at")), "envio_vendedor": _dec(o.get("shipping_cost_owner")),
                           "comision": None,                 # Tiendanube cobra por plan: se usa el % configurado en la conexión
                           "lineas": [{"id_externo": str(l.get("variant_id") or l.get("product_id")), "sku": l.get("sku") or None,
                                       "titulo": l.get("name"), "cantidad": _dec(l.get("quantity")), "precio": _dec(l.get("price"))}
                                      for l in o.get("products") or []]})
        return salida


class MercadoLibre:
    tipo = "mercadolibre"
    BASE = "https://api.mercadolibre.com"

    def __init__(self, token: str, transporte: Transporte | None = None):
        self.headers = {"Authorization": f"Bearer {token}"}
        self._get = transporte or _http
        self._yo = None

    def yo(self) -> dict:
        if self._yo is None:
            self._yo = self._get(f"{self.BASE}/users/me", self.headers)
        return self._yo

    def probar(self) -> dict:
        y = self.yo()
        return {"nombre": y.get("nickname"), "id": y.get("id")}

    def publicaciones(self) -> list[dict]:
        uid = self.yo()["id"]
        ids, offset = [], 0
        while True:
            r = self._get(f"{self.BASE}/users/{uid}/items/search?offset={offset}&limit=100", self.headers)
            ids += r.get("results") or []
            offset += 100
            if offset >= (r.get("paging") or {}).get("total", 0) or not r.get("results"):
                break
        salida = []
        for i in range(0, len(ids), 20):
            for x in self._get(f"{self.BASE}/items?ids={','.join(ids[i:i + 20])}", self.headers):
                b = x.get("body") or {}
                if x.get("code") != 200:
                    continue
                sku = b.get("seller_custom_field") or next((a.get("value_name") for a in b.get("attributes") or [] if a.get("id") == "SELLER_SKU"), None)
                ean = next((a.get("value_name") for a in b.get("attributes") or [] if a.get("id") == "GTIN"), None)
                salida.append({"id_externo": b["id"], "sku": sku, "ean": ean, "titulo": b.get("title"), "precio": _dec(b.get("price")),
                               "stock": _dec(b.get("available_quantity")), "activa": b.get("status") == "active"})
        return salida

    def pedidos(self, desde: datetime) -> list[dict]:
        uid = self.yo()["id"]
        salida, offset = [], 0
        desde_txt = desde.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000-00:00")
        while True:
            r = self._get(f"{self.BASE}/orders/search?seller={uid}&order.date_created.from={urllib.parse.quote(desde_txt)}"
                          f"&sort=date_asc&offset={offset}&limit=50", self.headers)
            for o in r.get("results") or []:
                if o.get("status") not in ("paid", "cancelled", "partially_refunded", "refunded"):
                    continue
                envio_vendedor = Decimal(0)
                envio = (o.get("shipping") or {}).get("id")
                estado_envio = None
                despachado = None
                if envio:
                    try:
                        costos = self._get(f"{self.BASE}/shipments/{envio}/costs", self.headers)
                        envio_vendedor = sum((_dec(s.get("cost")) for s in costos.get("senders") or []), Decimal(0))
                        sh = self._get(f"{self.BASE}/shipments/{envio}", self.headers)
                        estado_envio = sh.get("status")
                        despachado = _fecha((sh.get("status_history") or {}).get("date_shipped"))
                    except ErrorPlataforma:
                        pass
                estado = "cancelado" if o["status"] == "cancelled" else "devuelto" if o["status"] in ("refunded", "partially_refunded") else \
                    "entregado" if estado_envio == "delivered" else "despachado" if estado_envio == "shipped" else "pendiente"
                salida.append({"id": str(o["id"]), "creado": _fecha(o["date_created"]), "estado": estado, "total": _dec(o.get("total_amount")),
                               "despachado": despachado, "envio_vendedor": envio_vendedor,
                               "comision": sum((_dec(i.get("sale_fee")) * _dec(i.get("quantity")) for i in o.get("order_items") or []), Decimal(0)),
                               "lineas": [{"id_externo": (i.get("item") or {}).get("id"), "sku": (i.get("item") or {}).get("seller_sku"),
                                           "titulo": (i.get("item") or {}).get("title"), "cantidad": _dec(i.get("quantity")), "precio": _dec(i.get("unit_price"))}
                                          for i in o.get("order_items") or []]})
            offset += 50
            if offset >= (r.get("paging") or {}).get("total", 0) or not r.get("results"):
                return salida


def cliente_de(tipo: str, config: dict, credenciales: dict, transporte: Transporte | None = None):
    if tipo == "tiendanube":
        return Tiendanube(config["store_id"], credenciales["token"], transporte)
    if tipo == "mercadolibre":
        return MercadoLibre(credenciales["token"], transporte)
    raise ErrorPlataforma("Plataforma no soportada todavía.")


# ------------------------------------------------------------------------------ guardar y sincronizar
def guardar(conn, ctx, tipo: str, datos: dict, plataforma_id: int | None = None) -> int:
    """datos: nombre, ubicacion_despacho_id, token (opcional al editar), store_id (Tiendanube), comision_pct (Tiendanube)."""
    config = {k: datos[k] for k in ("store_id", "comision_pct") if datos.get(k) is not None}
    with conn.cursor() as cur:
        if plataforma_id:
            actual = db.fila(conn, "SELECT credenciales_cifradas, config FROM plataformas WHERE id=%s AND tipo=%s", (plataforma_id, tipo))
            if not actual:
                raise ValueError("No existe esa conexión.")
            token = datos.get("token") or cifrado.descifrar(actual["credenciales_cifradas"]).get("token")
            cur.execute("UPDATE plataformas SET nombre=%s, ubicacion_despacho_id=%s, config=%s, credenciales_cifradas=%s, activa=true, updated_at=now() WHERE id=%s",
                        (datos.get("nombre") or tipo, datos["ubicacion_despacho_id"], json.dumps({**(actual["config"] or {}), **config}),
                         cifrado.cifrar({"token": token}), plataforma_id))
            return plataforma_id
        canal = db.fila(conn, "SELECT id FROM canales WHERE codigo='ecommerce'")
        if not canal:
            canal = db.fila(conn, "INSERT INTO canales (org_id, codigo, nombre, created_by) VALUES (%s,'ecommerce','Tienda online',%s) RETURNING id",
                            (ctx.org_id, ctx.usuario_id))
        return db.fila(conn, "INSERT INTO plataformas (org_id, tipo, nombre, canal_id, ubicacion_despacho_id, config, credenciales_cifradas, estado_sincronizacion, created_by) "
                             "VALUES (%s,%s,%s,%s,%s,%s,%s,'sin_probar',%s) RETURNING id",
                       (ctx.org_id, tipo, datos.get("nombre") or {"tiendanube": "Tiendanube", "mercadolibre": "Mercado Libre"}[tipo], canal["id"],
                        datos["ubicacion_despacho_id"], json.dumps(config), cifrado.cifrar({"token": datos["token"]}), ctx.usuario_id))["id"]


def recalcular_reservado(conn, ubicacion_id: int) -> None:
    """Stock unificado: lo reservado en la sucursal que despacha = unidades de los pedidos online sin despachar."""
    with conn.cursor() as cur:
        cur.execute("""UPDATE stock_actual s SET reservado = coalesce((
                           SELECT sum(l.cantidad) FROM pedidos_online po JOIN tickets_lineas l ON l.ticket_id = po.ticket_id
                           WHERE po.estado = 'pendiente' AND po.ubicacion_id = s.ubicacion_id AND l.producto_id = s.producto_id), 0)
                       WHERE s.ubicacion_id = %s""", (ubicacion_id,))


def _emparejar(conn, cat: dict, plataforma_id: int, item: dict) -> int | None:
    clave = (item.get("id_externo"), item.get("sku"))
    if clave not in cat["memo"]:
        e = catalogo.emparejar(conn, ean=item.get("ean"), codigo=item.get("sku") or None, texto=None if item.get("sku") else item.get("titulo"),
                               origen="plataforma", origen_id=plataforma_id, productos=cat["productos"])
        if not e.producto_id and item.get("id_externo"):
            f = db.fila(conn, "SELECT producto_id FROM alias_producto WHERE origen='plataforma' AND origen_id=%s AND codigo=%s LIMIT 1",
                        (plataforma_id, f"id:{item['id_externo']}"))
            e.producto_id = f["producto_id"] if f else None
        cat["memo"][clave] = e.producto_id
    return cat["memo"][clave]


def sincronizar(conn, ctx, plataforma_id: int, transporte: Transporte | None = None) -> dict:
    t0 = _time.time()
    p = db.fila(conn, "SELECT * FROM plataformas WHERE id=%s AND activa", (plataforma_id,))
    if not p or p["tipo"] not in ("tiendanube", "mercadolibre"):
        raise ValueError("No existe esa conexión.")
    if not p["ubicacion_despacho_id"]:
        raise ValueError("Elegí la sucursal que despacha los pedidos de esta plataforma.")
    c = cliente_de(p["tipo"], p["config"] or {}, cifrado.descifrar(p["credenciales_cifradas"]), transporte)
    zona = ZoneInfo(db.fila(conn, "SELECT zona_horaria FROM organizaciones WHERE id = app_org()")["zona_horaria"])
    ahora = datetime.now(timezone.utc)
    desde = (p["sincronizado_hasta"] - SOLAPE) if p["sincronizado_hasta"] else ahora - timedelta(days=HISTORIAL_DIAS)
    cat = {"productos": db.filas(conn, "SELECT id, nombre, marca, codigo_interno, ean FROM productos WHERE activo"), "memo": {}}
    uid = p["ubicacion_despacho_id"]
    try:
        pubs = c.publicaciones()
        pedidos = c.pedidos(desde)
    except ErrorPlataforma as e:
        raise ValueError(str(e))
    except OSError as e:
        raise ValueError(f"No se pudo conectar con la plataforma ({e}).")
    sin_emparejar = 0
    with conn.cursor() as cur:
        for pub in pubs:
            pid = _emparejar(conn, cat, plataforma_id, pub)
            sin_emparejar += pid is None
            cur.execute("""INSERT INTO publicaciones (org_id, plataforma_id, producto_id, id_externo, sku, titulo, precio, stock_publicado, activa, actualizado_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (plataforma_id, id_externo) DO UPDATE SET
                           producto_id = coalesce(EXCLUDED.producto_id, publicaciones.producto_id), sku=EXCLUDED.sku, titulo=EXCLUDED.titulo,
                           precio=EXCLUDED.precio, stock_publicado=EXCLUDED.stock_publicado, activa=EXCLUDED.activa, actualizado_at=now()""",
                        (ctx.org_id, plataforma_id, pid, pub["id_externo"], pub.get("sku"), pub.get("titulo"), pub.get("precio"), pub.get("stock") or 0, pub["activa"]))
        comision_pct = _dec((p["config"] or {}).get("comision_pct"))
        nuevos = actualizados = lineas_sin_producto = 0
        fechas = []
        for o in pedidos:
            numero = f"{plataforma_id}-{o['id']}"
            existente = db.fila(conn, "SELECT id FROM tickets WHERE origen=%s AND numero_externo=%s", (p["tipo"], numero))
            estado_ticket = "anulado" if o["estado"] == "cancelado" else "confirmado"
            if existente:
                cur.execute("UPDATE tickets SET estado=%s WHERE id=%s AND estado <> %s", (estado_ticket, existente["id"], estado_ticket))
                cur.execute("UPDATE pedidos_online SET estado=%s, despachado_at=coalesce(%s, despachado_at) WHERE ticket_id=%s AND estado <> %s",
                            (o["estado"], o["despachado"], existente["id"], o["estado"]))
                actualizados += cur.rowcount
                continue
            t = db.fila(conn, "INSERT INTO tickets (org_id, ubicacion_id, canal_id, plataforma_id, punto_venta, fecha_hora, total, estado, numero_externo, origen) "
                              "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (org_id, origen, numero_externo) DO NOTHING RETURNING id",
                        (ctx.org_id, uid, p["canal_id"], plataforma_id, p["tipo"], o["creado"], o["total"], estado_ticket, numero, p["tipo"]))
            if not t:
                continue
            fecha = o["creado"].astimezone(zona).date()
            fechas.append(fecha)
            for l in o["lineas"]:
                pid = _emparejar(conn, cat, plataforma_id, l)
                if not pid or not l["cantidad"]:
                    lineas_sin_producto += 1
                    continue
                costo = db.fila(conn, "SELECT costo FROM producto_proveedores WHERE producto_id=%s ORDER BY principal DESC LIMIT 1", (pid,))
                cur.execute("INSERT INTO tickets_lineas (org_id, ticket_id, ubicacion_id, fecha, producto_id, cantidad, precio_lista, precio_cobrado, descuento, costo_unitario) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0,%s)", (ctx.org_id, t["id"], uid, fecha, pid, l["cantidad"], l["precio"], l["precio"],
                                                                     costo["costo"] if costo else None))
            comision = o["comision"] if o["comision"] is not None else (o["total"] * comision_pct).quantize(Decimal("0.01"))
            cur.execute("INSERT INTO pagos (org_id, ticket_id, ubicacion_id, medio, monto, comision_estimada, plazo_acreditacion_dias) VALUES (%s,%s,%s,'plataforma',%s,%s,%s)",
                        (ctx.org_id, t["id"], uid, o["total"], comision, 14 if p["tipo"] == "mercadolibre" else 7))
            cur.execute("INSERT INTO costos_canal (org_id, plataforma_id, ticket_id, fecha, comision, envio) VALUES (%s,%s,%s,%s,%s,%s)",
                        (ctx.org_id, plataforma_id, t["id"], fecha, comision, o["envio_vendedor"]))
            cur.execute("INSERT INTO pedidos_online (ticket_id, org_id, ubicacion_id, plataforma_id, estado, creado_at, despachado_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (t["id"], ctx.org_id, uid, plataforma_id, o["estado"], o["creado"], o["despachado"]))
            nuevos += 1
        recalcular_reservado(conn, uid)
        hasta = max((o["creado"] for o in pedidos), default=None)
        cur.execute("UPDATE plataformas SET estado_sincronizacion='ok', error_sincronizacion=NULL, ultima_sincronizacion=now(), "
                    "sincronizado_hasta=greatest(coalesce(sincronizado_hasta, %s), %s) WHERE id=%s", (hasta or desde, hasta or desde, plataforma_id))
    resultado = {"pedidos_nuevos": nuevos, "pedidos_actualizados": actualizados, "publicaciones": len(pubs), "publicaciones_sin_emparejar": sin_emparejar,
                 "lineas_sin_producto": lineas_sin_producto, "desde": min(fechas) if fechas else None, "segundos": round(_time.time() - t0, 1)}
    resultado["mensaje"] = (f"{nuevos} pedidos nuevos, {actualizados} actualizados y {len(pubs)} publicaciones"
                            + (f"; {sin_emparejar} publicaciones sin emparejar (revisalas en Catálogo)" if sin_emparejar else ""))
    return resultado
