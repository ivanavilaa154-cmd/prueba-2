"""Conectores de e-commerce (sección 5.4): Tiendanube, Mercado Libre, WooCommerce, Shopify y VTEX.

Leen con pedidos GET. La única escritura es actualizar_stock() y solo la llama stock_publicado.aplicar() después de que una
persona aprobó la propuesta (CLAUDE.md, regla 4: ninguna comunicación externa sale sin confirmación humana).

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
Enviador = Callable[[str, str, dict, dict], object]  # (método, url, headers, cuerpo) -> JSON; solo para el stock aprobado
SOLAPE = timedelta(days=3)                          # los pedidos cambian de estado: se revisan los últimos días
HISTORIAL_DIAS = 180


class ErrorPlataforma(RuntimeError):
    pass


def _http(url: str, headers: dict, timeout: float = 60, metodo: str = "GET", cuerpo: dict | None = None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    pedido = urllib.request.Request(url, headers={**headers, **({"Content-Type": "application/json"} if datos else {})}, method=metodo, data=datos)
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as r:
            texto = r.read()
            return json.loads(texto) if texto else {}
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ErrorPlataforma("La plataforma rechazó el acceso: revisá o renová el token (y que tenga permiso de escritura de stock si lo vas a actualizar).")
        raise ErrorPlataforma(f"La plataforma respondió {e.code}.")


def _enviar(metodo: str, url: str, headers: dict, cuerpo: dict):
    return _http(url, headers, metodo=metodo, cuerpo=cuerpo)


def _url_publica(url: str) -> str:
    """WooCommerce vive en el dominio del comercio: solo https y nunca una dirección interna (la consulta sale de nuestro servidor)."""
    import ipaddress
    import socket
    partes = urllib.parse.urlparse((url or "").strip().rstrip("/"))
    if partes.scheme != "https" or not partes.hostname:
        raise ErrorPlataforma("La dirección de la tienda tiene que empezar con https://")
    try:
        direcciones = {i[4][0] for i in socket.getaddrinfo(partes.hostname, 443)}
    except OSError:
        raise ErrorPlataforma("No se encontró esa dirección de tienda.")
    for d in direcciones:
        ip = ipaddress.ip_address(d)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ErrorPlataforma("Esa dirección no es pública.")
    return f"https://{partes.netloc}{partes.path}"


def _fecha(texto: str | None) -> datetime | None:
    if not texto:
        return None
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


def _dec(v) -> Decimal:
    return Decimal(str(v or 0))


# ------------------------------------------------------------------------------ clientes (solo GET)
class Tiendanube:
    tipo = "tiendanube"

    def __init__(self, store_id: str, token: str, transporte: Transporte | None = None, enviador: Enviador | None = None):
        self.base = f"https://api.tiendanube.com/v1/{store_id}"
        self.headers = {"Authentication": f"bearer {token}", "User-Agent": "Retail IA (soporte@retail-ia.app)"}
        self._get = transporte or _http
        self._enviar = enviador or _enviar

    def actualizar_stock(self, pub: dict, cantidad: int) -> None:
        self._enviar("PUT", f"{self.base}/products/{pub['id_padre']}/variants/{pub['id_externo']}", self.headers, {"stock": cantidad})

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
                salida.append({"id_externo": str(v["id"]), "id_padre": str(p["id"]), "sku": v.get("sku") or None, "ean": v.get("barcode") or None, "titulo": titulo,
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

    def __init__(self, token: str, transporte: Transporte | None = None, enviador: Enviador | None = None):
        self.headers = {"Authorization": f"Bearer {token}"}
        self._get = transporte or _http
        self._enviar = enviador or _enviar
        self._yo = None

    def actualizar_stock(self, pub: dict, cantidad: int) -> None:
        self._enviar("PUT", f"{self.BASE}/items/{pub['id_externo']}", self.headers, {"available_quantity": cantidad})

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


class WooCommerce:
    tipo = "woocommerce"

    def __init__(self, url: str, clave: str, secreto: str, transporte: Transporte | None = None, enviador: Enviador | None = None):
        import base64
        self.base = f"{url.rstrip('/')}/wp-json/wc/v3"
        self.headers = {"Authorization": "Basic " + base64.b64encode(f"{clave}:{secreto}".encode()).decode()}
        self._get = transporte or _http
        self._enviar = enviador or _enviar

    def _paginas(self, recurso: str, params: dict):
        pagina = 1
        while True:
            lote = self._get(f"{self.base}/{recurso}?{urllib.parse.urlencode({**params, 'per_page': 100, 'page': pagina})}", self.headers)
            if not lote:
                return
            yield from lote
            if len(lote) < 100:
                return
            pagina += 1

    def probar(self) -> dict:
        self._get(f"{self.base}/orders?per_page=1", self.headers)
        return {"nombre": urllib.parse.urlparse(self.base).hostname, "id": None}

    @staticmethod
    def _item(x: dict, titulo: str, padre: str | None, activa: bool) -> dict:
        ean = x.get("global_unique_id") or next((m.get("value") for m in x.get("meta_data") or [] if m.get("key") in ("_ean", "_gtin", "ean")), None)
        return {"id_externo": str(x["id"]), "id_padre": padre, "sku": x.get("sku") or None, "ean": ean or None, "titulo": titulo,
                "precio": _dec(x.get("price")), "stock": _dec(x.get("stock_quantity")) if x.get("manage_stock") else None, "activa": activa}

    def publicaciones(self) -> list[dict]:
        salida = []
        for p in self._paginas("products", {}):
            activa = p.get("status") == "publish"
            if p.get("type") == "variable":
                for v in self._paginas(f"products/{p['id']}/variations", {}):
                    salida.append(self._item(v, p.get("name"), str(p["id"]), activa))
            else:
                salida.append(self._item(p, p.get("name"), None, activa))
        return salida

    def pedidos(self, desde: datetime) -> list[dict]:
        estados = {"processing": "pendiente", "completed": "entregado", "cancelled": "cancelado", "refunded": "devuelto"}
        salida = []
        for o in self._paginas("orders", {"after": desde.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")}):
            if o.get("status") not in estados:
                continue                                     # pendiente de pago, en espera o fallido: todavía no es venta
            salida.append({"id": str(o["id"]), "creado": _fecha((o.get("date_created_gmt") or o["date_created"]) + ("Z" if o.get("date_created_gmt") else "")),
                           "estado": estados[o["status"]], "total": _dec(o.get("total")),
                           "despachado": _fecha(o["date_completed_gmt"] + "Z") if o.get("date_completed_gmt") else None,
                           "envio_vendedor": Decimal(0), "comision": None,
                           "lineas": [{"id_externo": str(l.get("variation_id") or l.get("product_id")), "sku": l.get("sku") or None, "titulo": l.get("name"),
                                       "cantidad": _dec(l.get("quantity")), "precio": _dec(l.get("price"))} for l in o.get("line_items") or []]})
        return salida

    def actualizar_stock(self, pub: dict, cantidad: int) -> None:
        ruta = f"products/{pub['id_padre']}/variations/{pub['id_externo']}" if pub.get("id_padre") else f"products/{pub['id_externo']}"
        self._enviar("PUT", f"{self.base}/{ruta}", self.headers, {"manage_stock": True, "stock_quantity": cantidad})


class Shopify:
    tipo = "shopify"
    VERSION = "2024-10"

    def __init__(self, tienda: str, token: str, transporte: Transporte | None = None, enviador: Enviador | None = None):
        self.base = f"https://{tienda}/admin/api/{self.VERSION}"
        self.headers = {"X-Shopify-Access-Token": token}
        self._get = transporte or _http
        self._enviar = enviador or _enviar

    def _todos(self, recurso: str, clave: str, params: dict):
        desde_id = 0
        while True:
            lote = self._get(f"{self.base}/{recurso}.json?{urllib.parse.urlencode({**params, 'limit': 250, 'since_id': desde_id})}", self.headers).get(clave) or []
            yield from lote
            if len(lote) < 250:
                return
            desde_id = lote[-1]["id"]

    def probar(self) -> dict:
        tienda = self._get(f"{self.base}/shop.json", self.headers).get("shop") or {}
        return {"nombre": tienda.get("name"), "id": tienda.get("id")}

    def publicaciones(self) -> list[dict]:
        salida = []
        for p in self._todos("products", "products", {}):
            for v in p.get("variants") or []:
                titulo = p.get("title") if v.get("title") in (None, "Default Title") else f"{p.get('title')} {v.get('title')}"
                salida.append({"id_externo": str(v["id"]), "id_padre": str(v.get("inventory_item_id") or ""), "sku": v.get("sku") or None,
                               "ean": v.get("barcode") or None, "titulo": titulo, "precio": _dec(v.get("price")),
                               "stock": _dec(v.get("inventory_quantity")) if v.get("inventory_management") else None, "activa": p.get("status") == "active"})
        return salida

    def pedidos(self, desde: datetime) -> list[dict]:
        salida = []
        for o in self._todos("orders", "orders", {"status": "any", "created_at_min": desde.isoformat()}):
            if o.get("financial_status") not in ("paid", "partially_refunded", "refunded") and not o.get("cancelled_at"):
                continue
            envios = o.get("fulfillments") or []
            estado = "cancelado" if o.get("cancelled_at") else "devuelto" if o.get("financial_status") == "refunded" else \
                "despachado" if o.get("fulfillment_status") == "fulfilled" else "pendiente"
            salida.append({"id": str(o["id"]), "creado": _fecha(o["created_at"]), "estado": estado, "total": _dec(o.get("total_price")),
                           "despachado": _fecha(envios[0].get("created_at")) if envios else None, "envio_vendedor": Decimal(0), "comision": None,
                           "lineas": [{"id_externo": str(l.get("variant_id") or l.get("product_id")), "sku": l.get("sku") or None, "titulo": l.get("title"),
                                       "cantidad": _dec(l.get("quantity")), "precio": _dec(l.get("price"))} for l in o.get("line_items") or []]})
        return salida

    def actualizar_stock(self, pub: dict, cantidad: int) -> None:
        ubicaciones = [u for u in self._get(f"{self.base}/locations.json", self.headers).get("locations") or [] if u.get("active")]
        if not ubicaciones or not pub.get("id_padre"):
            raise ErrorPlataforma("Shopify no informó el depósito o el artículo de inventario de esta publicación.")
        self._enviar("POST", f"{self.base}/inventory_levels/set.json", self.headers,
                     {"location_id": ubicaciones[0]["id"], "inventory_item_id": int(pub["id_padre"]), "available": cantidad})


class Vtex:
    tipo = "vtex"

    def __init__(self, cuenta: str, clave: str, secreto: str, transporte: Transporte | None = None, enviador: Enviador | None = None):
        self.base = f"https://{cuenta}.vtexcommercestable.com.br/api"
        self.headers = {"X-VTEX-API-AppKey": clave, "X-VTEX-API-AppToken": secreto, "Accept": "application/json"}
        self._get = transporte or _http
        self._enviar = enviador or _enviar

    def probar(self) -> dict:
        r = self._get(f"{self.base}/catalog_system/pvt/products/GetProductAndSkuIds?_from=1&_to=1", self.headers)
        return {"nombre": self.base.split("//")[1].split(".")[0], "id": (r.get("range") or {}).get("total")}

    def publicaciones(self) -> list[dict]:
        ids, pagina = [], 1
        while True:
            lote = self._get(f"{self.base}/catalog_system/pvt/sku/stockkeepingunitids?page={pagina}&pagesize=1000", self.headers) or []
            ids += lote
            if len(lote) < 1000:
                break
            pagina += 1
        salida = []
        for sku in ids:
            x = self._get(f"{self.base}/catalog_system/pvt/sku/stockkeepingunitbyid/{sku}", self.headers)
            inv = self._get(f"{self.base}/logistics/pvt/inventory/skus/{sku}", self.headers).get("balance") or []
            precio = next((s.get("Price") for s in (x.get("SkuSellers") or [])), None)
            salida.append({"id_externo": str(sku), "id_padre": inv[0].get("warehouseId") if inv else None,
                           "sku": x.get("RefId") or None, "ean": (x.get("AlternateIds") or {}).get("Ean") or None,
                           "titulo": x.get("NameComplete") or x.get("SkuName"), "precio": _dec(precio),
                           "stock": sum((_dec(b.get("totalQuantity")) - _dec(b.get("reservedQuantity")) for b in inv), Decimal(0)) if inv else None,
                           "activa": bool(x.get("IsActive"))})
        return salida

    def pedidos(self, desde: datetime) -> list[dict]:
        rango = f"creationDate:[{desde.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')} TO {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')}]"
        salida, pagina = [], 1
        while True:
            r = self._get(f"{self.base}/oms/pvt/orders?{urllib.parse.urlencode({'f_creationDate': rango, 'per_page': 100, 'page': pagina})}", self.headers)
            for resumen in r.get("list") or []:
                if resumen.get("status") in ("payment-pending", "waiting-for-sellers-confirmation", "incomplete"):
                    continue
                o = self._get(f"{self.base}/oms/pvt/orders/{resumen['orderId']}", self.headers)
                st = o.get("status")
                estado = "cancelado" if st in ("canceled", "cancel") else "entregado" if st == "delivered" else "despachado" if st == "invoiced" else "pendiente"
                salida.append({"id": o["orderId"], "creado": _fecha(o["creationDate"]), "estado": estado, "total": _dec(o.get("value")) / 100,
                               "despachado": _fecha(o.get("invoicedDate")), "envio_vendedor": Decimal(0), "comision": None,
                               "lineas": [{"id_externo": str(i.get("id")), "sku": i.get("refId") or None, "titulo": i.get("name"),
                                           "cantidad": _dec(i.get("quantity")), "precio": _dec(i.get("sellingPrice")) / 100} for i in o.get("items") or []]})
            if pagina >= (r.get("paging") or {}).get("pages", 1):
                return salida
            pagina += 1

    def actualizar_stock(self, pub: dict, cantidad: int) -> None:
        if not pub.get("id_padre"):
            raise ErrorPlataforma("VTEX no informó el depósito de este SKU.")
        self._enviar("PUT", f"{self.base}/logistics/pvt/inventory/skus/{pub['id_externo']}/warehouses/{pub['id_padre']}", self.headers,
                     {"unlimitedQuantity": False, "quantity": cantidad})


# Qué pide cada plataforma: datos de la conexión (config) y claves (se guardan cifradas y nunca se devuelven).
TIENDAS: dict[str, dict] = {
    "tiendanube": {"nombre": "Tiendanube", "config": ["store_id"], "credenciales": ["token"], "plazo": 7},
    "mercadolibre": {"nombre": "Mercado Libre", "config": [], "credenciales": ["token"], "plazo": 14},
    "woocommerce": {"nombre": "WooCommerce", "config": ["url"], "credenciales": ["clave", "secreto"], "plazo": 7},
    "shopify": {"nombre": "Shopify", "config": ["tienda"], "credenciales": ["token"], "plazo": 7},
    "vtex": {"nombre": "VTEX", "config": ["cuenta"], "credenciales": ["clave", "secreto"], "plazo": 14},
}


def validar_config(tipo: str, config: dict) -> dict:
    import re
    if tipo not in TIENDAS:
        raise ErrorPlataforma("Plataforma no soportada todavía.")
    faltan = [c for c in TIENDAS[tipo]["config"] if not config.get(c)]
    if faltan:
        raise ErrorPlataforma({"store_id": "Falta el número de tienda de Tiendanube.", "url": "Falta la dirección de la tienda WooCommerce.",
                               "tienda": "Falta la tienda de Shopify (tutienda.myshopify.com).", "cuenta": "Falta el nombre de cuenta de VTEX."}[faltan[0]])
    if tipo == "tiendanube" and not str(config["store_id"]).isdigit():
        raise ErrorPlataforma("El número de tienda de Tiendanube son solo dígitos.")
    if tipo == "shopify":
        config["tienda"] = str(config["tienda"]).strip().lower().removeprefix("https://").rstrip("/")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.myshopify\.com", config["tienda"]):
            raise ErrorPlataforma("La tienda de Shopify tiene la forma tutienda.myshopify.com.")
    if tipo == "vtex":
        config["cuenta"] = str(config["cuenta"]).strip().lower()
        if not re.fullmatch(r"[a-z0-9-]{2,60}", config["cuenta"]):
            raise ErrorPlataforma("El nombre de cuenta de VTEX son letras, números y guiones.")
    return config


def cliente_de(tipo: str, config: dict, credenciales: dict, transporte: Transporte | None = None, enviador: Enviador | None = None):
    config = validar_config(tipo, dict(config))
    faltan = [c for c in TIENDAS[tipo]["credenciales"] if not credenciales.get(c)]
    if faltan:
        raise ErrorPlataforma("Faltan las claves de acceso.")
    if tipo == "tiendanube":
        return Tiendanube(config["store_id"], credenciales["token"], transporte, enviador)
    if tipo == "mercadolibre":
        return MercadoLibre(credenciales["token"], transporte, enviador)
    if tipo == "woocommerce":
        url = config["url"] if transporte else _url_publica(config["url"])
        return WooCommerce(url, credenciales["clave"], credenciales["secreto"], transporte, enviador)
    if tipo == "shopify":
        return Shopify(config["tienda"], credenciales["token"], transporte, enviador)
    return Vtex(config["cuenta"], credenciales["clave"], credenciales["secreto"], transporte, enviador)


# ------------------------------------------------------------------------------ guardar y sincronizar
def guardar(conn, ctx, tipo: str, datos: dict, plataforma_id: int | None = None) -> int:
    """datos: nombre, ubicacion_despacho_id, comision_pct, los datos de la conexión (TIENDAS[tipo]['config']) y las claves
    (TIENDAS[tipo]['credenciales']; al editar, las vacías se mantienen)."""
    info = TIENDAS[tipo]
    config = {k: datos[k] for k in info["config"] + ["comision_pct"] if datos.get(k) is not None}
    nuevas = {k: datos[k] for k in info["credenciales"] if datos.get(k)}
    with conn.cursor() as cur:
        if plataforma_id:
            actual = db.fila(conn, "SELECT credenciales_cifradas, config FROM plataformas WHERE id=%s AND tipo=%s", (plataforma_id, tipo))
            if not actual:
                raise ValueError("No existe esa conexión.")
            credenciales = {**(cifrado.descifrar(actual["credenciales_cifradas"]) if actual["credenciales_cifradas"] else {}), **nuevas}
            cur.execute("UPDATE plataformas SET nombre=%s, ubicacion_despacho_id=%s, config=%s, credenciales_cifradas=%s, activa=true, updated_at=now() WHERE id=%s",
                        (datos.get("nombre") or info["nombre"], datos["ubicacion_despacho_id"], json.dumps({**(actual["config"] or {}), **config}),
                         cifrado.cifrar(credenciales), plataforma_id))
            return plataforma_id
        canal = db.fila(conn, "SELECT id FROM canales WHERE codigo='ecommerce'")
        if not canal:
            canal = db.fila(conn, "INSERT INTO canales (org_id, codigo, nombre, created_by) VALUES (%s,'ecommerce','Tienda online',%s) RETURNING id",
                            (ctx.org_id, ctx.usuario_id))
        cur.execute("UPDATE canales SET activo=true WHERE id=%s", (canal["id"],))
        return db.fila(conn, "INSERT INTO plataformas (org_id, tipo, nombre, canal_id, ubicacion_despacho_id, config, credenciales_cifradas, estado_sincronizacion, created_by) "
                             "VALUES (%s,%s,%s,%s,%s,%s,%s,'sin_probar',%s) RETURNING id",
                       (ctx.org_id, tipo, datos.get("nombre") or info["nombre"], canal["id"], datos["ubicacion_despacho_id"], json.dumps(config),
                        cifrado.cifrar(nuevas), ctx.usuario_id))["id"]


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
    if not p or p["tipo"] not in TIENDAS:
        raise ValueError("No existe esa conexión.")
    if not p["ubicacion_despacho_id"]:
        raise ValueError("Elegí la sucursal que despacha los pedidos de esta plataforma.")
    try:
        c = cliente_de(p["tipo"], p["config"] or {}, cifrado.descifrar(p["credenciales_cifradas"]), transporte)
    except ErrorPlataforma as e:
        raise ValueError(str(e))
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
            cur.execute("""INSERT INTO publicaciones (org_id, plataforma_id, producto_id, id_externo, id_padre, sku, titulo, precio, stock_publicado,
                                                      controla_stock, activa, actualizado_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (plataforma_id, id_externo) DO UPDATE SET
                           producto_id = coalesce(EXCLUDED.producto_id, publicaciones.producto_id), id_padre=EXCLUDED.id_padre, sku=EXCLUDED.sku,
                           titulo=EXCLUDED.titulo, precio=EXCLUDED.precio, stock_publicado=EXCLUDED.stock_publicado,
                           controla_stock=EXCLUDED.controla_stock, activa=EXCLUDED.activa, actualizado_at=now()""",
                        (ctx.org_id, plataforma_id, pid, pub["id_externo"], pub.get("id_padre"), pub.get("sku"), pub.get("titulo"), pub.get("precio"),
                         pub.get("stock") or 0, pub.get("stock") is not None, pub["activa"]))
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
                        (ctx.org_id, t["id"], uid, o["total"], comision, TIENDAS[p["tipo"]]["plazo"]))
            cur.execute("INSERT INTO costos_canal (org_id, plataforma_id, ticket_id, fecha, comision, envio) VALUES (%s,%s,%s,%s,%s,%s)",
                        (ctx.org_id, plataforma_id, t["id"], fecha, comision, o["envio_vendedor"]))
            cur.execute("INSERT INTO pedidos_online (ticket_id, org_id, ubicacion_id, plataforma_id, estado, creado_at, despachado_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (t["id"], ctx.org_id, uid, plataforma_id, o["estado"], o["creado"], o["despachado"]))
            nuevos += 1
        recalcular_reservado(conn, uid)
        hasta = max((o["creado"] for o in pedidos), default=None)
        cur.execute("UPDATE plataformas SET estado_sincronizacion='ok', error_sincronizacion=NULL, ultima_sincronizacion=now(), "
                    "sincronizado_hasta=greatest(coalesce(sincronizado_hasta, %s), %s) WHERE id=%s", (hasta or desde, hasta or desde, plataforma_id))
    from . import stock_publicado
    propuestas = stock_publicado.proponer(conn, plataforma_id)
    resultado = {"propuestas_stock": propuestas["pendientes"], "pedidos_nuevos": nuevos, "pedidos_actualizados": actualizados, "publicaciones": len(pubs), "publicaciones_sin_emparejar": sin_emparejar,
                 "lineas_sin_producto": lineas_sin_producto, "desde": min(fechas) if fechas else None, "segundos": round(_time.time() - t0, 1)}
    resultado["mensaje"] = (f"{nuevos} pedidos nuevos, {actualizados} actualizados y {len(pubs)} publicaciones"
                            + (f"; {sin_emparejar} publicaciones sin emparejar (revisalas en Catálogo)" if sin_emparejar else "")
                            + (f"; {propuestas['pendientes']} publicaciones con el stock para corregir (aprobalas en Canales)" if propuestas["pendientes"] else ""))
    return resultado
