"""Integración con Odoo (12 o superior) por su API JSON-RPC, en solo lectura.

Lee los datos de Odoo y los convierte a las tablas del diccionario de la
plataforma (clientes, vendedores, productos, ventas, cxc...). Así el chat, los
permisos por rol y los análisis funcionan igual que con cualquier otra fuente.

Solo usa métodos de lectura de Odoo (version, authenticate, search_read, read,
search_count, check_access_rights, fields_get): nunca crea ni modifica nada.

Mapeo:
  stock.warehouse                  -> sucursales
  res.users (vendedor del cliente) -> vendedores
  res.partner (clientes)           -> clientes (vendedor = "Vendedor" de la ficha)
  res.partner (proveedores)        -> proveedores
  product.product (vendibles)      -> productos
  stock.quant (por almacén)        -> stock
  sale.order + pos.order           -> ventas (tickets de caja con id 1.000.000.000 + id)
  sale.order.line + pos.order.line -> ventas_lineas (precio neto sin impuestos)
  account.move (facturas cliente)  -> cxc (fecha_cobro = última conciliación)
"""
from __future__ import annotations

import itertools
import json
import re
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from typing import Callable, Iterable

Transporte = Callable[[str, dict], dict]
OFFSET_POS = 1_000_000_000  # los tickets de caja comparten tabla con los pedidos de venta
_METODOS_LECTURA = {"search_read", "read", "search_count", "search", "check_access_rights", "fields_get"}


class OdooError(RuntimeError):
    pass


def _http(url: str, payload: dict, timeout: float = 90) -> dict:
    pedido = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=timeout) as respuesta:
        return json.loads(respuesta.read())


def _id(valor):
    """Los many2one de Odoo llegan como [id, "nombre"] o False."""
    return valor[0] if isinstance(valor, (list, tuple)) and valor else None


def _nombre(valor) -> str | None:
    return valor[1] if isinstance(valor, (list, tuple)) and len(valor) > 1 else None


def _texto(valor) -> str | None:
    return valor if isinstance(valor, str) and valor else None


def _fecha(valor) -> str | None:
    return valor[:10] if isinstance(valor, str) and valor else None


_CODIGO = re.compile(r"^\[[^\]]*\]\s*")


def _lotes(ids, tamano: int = 500):
    ids = sorted({i for i in ids if i})
    for i in range(0, len(ids), tamano):
        yield ids[i:i + tamano]


class ClienteOdoo:
    def __init__(self, url: str, db: str, usuario: str, api_key: str,
                 transporte: Transporte | None = None, pagina: int = 500):
        if not re.match(r"^https?://", url or ""):
            raise OdooError("La URL tiene que empezar con https:// (o http:// si es un servidor local).")
        self.endpoint = url.rstrip("/") + "/jsonrpc"
        self.db, self.usuario, self.api_key = db, usuario, api_key
        self._transporte = transporte or _http
        self._uid = None
        self._ids = itertools.count(1)
        self.pagina = pagina
        self._campos: dict[str, set] = {}

    # --- RPC --------------------------------------------------------------

    def _llamar(self, servicio: str, metodo: str, *args):
        payload = {"jsonrpc": "2.0", "method": "call", "id": next(self._ids),
                   "params": {"service": servicio, "method": metodo, "args": list(args)}}
        respuesta = self._transporte(self.endpoint, payload)
        if respuesta.get("error"):
            err = respuesta["error"]
            detalle = (err.get("data") or {}).get("message") or err.get("message")
            raise OdooError(f"{servicio}.{metodo}: {detalle}")
        return respuesta.get("result")

    @property
    def uid(self) -> int:
        if self._uid is None:
            uid = self._llamar("common", "authenticate", self.db, self.usuario, self.api_key, {})
            if not uid:
                raise OdooError("Odoo rechazó el acceso: revisá base de datos, usuario y API key.")
            self._uid = uid
        return self._uid

    def ejecutar(self, modelo: str, metodo: str, args: list, kwargs: dict | None = None):
        if metodo not in _METODOS_LECTURA:  # solo lectura, también a nivel de código
            raise OdooError(f"Método no permitido en solo lectura: {metodo}")
        return self._llamar("object", "execute_kw", self.db, self.uid, self.api_key, modelo, metodo, args, kwargs or {})

    def leer_todo(self, modelo: str, dominio: list, campos: list, contexto: dict | None = None) -> Iterable[dict]:
        offset = 0
        while True:
            kwargs = {"fields": campos, "limit": self.pagina, "offset": offset, "order": "id"}
            if contexto:
                kwargs["context"] = contexto
            lote = self.ejecutar(modelo, "search_read", [dominio], kwargs)
            yield from lote
            if len(lote) < self.pagina:
                return
            offset += self.pagina

    def leer_ids(self, modelo: str, ids, campos: list) -> dict[int, dict]:
        salida = {}
        for lote in _lotes(ids):
            for fila in self.ejecutar(modelo, "read", [lote], {"fields": campos, "context": {"active_test": False}}):
                salida[fila["id"]] = fila
        return salida

    def puede_leer(self, modelo: str) -> bool:
        try:
            return bool(self.ejecutar(modelo, "check_access_rights", ["read"], {"raise_exception": False}))
        except OdooError:
            return False  # el módulo no está instalado

    def campos(self, modelo: str) -> set:
        if modelo not in self._campos:
            try:
                self._campos[modelo] = set(self.ejecutar(modelo, "fields_get", [], {"attributes": ["type"]}))
            except OdooError:
                self._campos[modelo] = set()
        return self._campos[modelo]

    def _solo_existentes(self, modelo: str, campos: list) -> list:
        disponibles = self.campos(modelo)
        return [c for c in campos if c in disponibles] if disponibles else campos


# Qué necesita la plataforma de Odoo y qué pasa si falta.
MODELOS = [
    ("res.partner", "clientes y proveedores", True, "Contactos"),
    ("product.product", "productos", True, "Inventario o Ventas"),
    ("sale.order", "pedidos de venta", False, "Ventas: Usuario (todos los documentos)"),
    ("pos.order", "ventas de caja", False, "Punto de Venta: Usuario"),
    ("account.move", "facturas y cobranzas", False, "Facturación: Facturación"),
    ("stock.quant", "stock por almacén", False, "Inventario: Usuario"),
    ("stock.warehouse", "almacenes (sucursales)", False, "Inventario: Usuario"),
]


def diagnosticar(cliente: ClienteOdoo) -> dict:
    """Revisa paso a paso servidor, acceso, permisos y datos. Se frena en el primer paso crítico que falla."""
    pasos = []
    resultado = {"ok": False, "pasos": pasos}

    def paso(nombre, ok, detalle, aviso=False):
        pasos.append({"paso": nombre, "ok": ok, "aviso": aviso, "detalle": detalle})
        return ok

    try:
        version = (cliente._llamar("common", "version") or {}).get("server_version", "desconocida")
    except OdooError as e:
        paso("Servidor", False, f"Odoo respondió con un error: {e}")
        return resultado
    except Exception as e:
        paso("Servidor", False, f"No responde {cliente.endpoint} ({type(e).__name__}: {e}). Revisá la URL.")
        return resultado
    resultado["version"] = version
    paso("Servidor", True, f"Odoo {version}")

    try:
        uid = cliente.uid
    except Exception as e:
        paso("Acceso", False, str(e))
        return resultado
    paso("Acceso", True, f"Usuario {cliente.usuario} (id {uid}) en la base {cliente.db}")

    faltan_criticos, faltan = [], []
    for modelo, que, critico, rol in MODELOS:
        if not cliente.puede_leer(modelo):
            (faltan_criticos if critico else faltan).append(f"{que} (rol {rol})")
    if faltan_criticos:
        paso("Permisos", False, "El usuario no puede leer: " + "; ".join(faltan_criticos) + ".")
        return resultado
    if faltan:
        paso("Permisos", True, "Sin acceso a: " + "; ".join(faltan) + ". Esas tablas quedan vacías.", aviso=True)
    else:
        paso("Permisos", True, "Puede leer clientes, productos, ventas, facturas y stock")

    try:
        conteos = {
            "clientes": cliente.ejecutar("res.partner", "search_count", [[("customer_rank", ">", 0)]]),
            "productos": cliente.ejecutar("product.product", "search_count", [[("sale_ok", "=", True)]]),
        }
        if cliente.puede_leer("sale.order"):
            conteos["pedidos"] = cliente.ejecutar("sale.order", "search_count", [[("state", "in", ["sale", "done"])]])
        if cliente.puede_leer("account.move"):
            conteos["facturas"] = cliente.ejecutar("account.move", "search_count",
                                                   [[("move_type", "=", "out_invoice"), ("state", "=", "posted")]])
    except Exception as e:
        paso("Datos", False, f"{type(e).__name__}: {e}")
        return resultado
    resultado["conteos"] = conteos
    detalle = ", ".join(f"{v:,} {k}".replace(",", ".") for k, v in conteos.items())
    ok = conteos["clientes"] > 0 or conteos.get("pedidos", 0) > 0
    paso("Datos", ok, detalle if ok else detalle + ". No hay clientes ni pedidos para analizar.")
    resultado["ok"] = ok
    return resultado


class Extraccion:
    """Lee Odoo y arma las filas de cada tabla del diccionario."""

    def __init__(self, cliente: ClienteOdoo, meses: int = 12, avisar: Callable[[str], None] | None = None,
                 hoy: date | None = None):
        self.c = cliente
        self.desde = ((hoy or date.today()) - timedelta(days=round(meses * 30.44))).isoformat()
        self.avisar = avisar or (lambda _texto: None)
        self.avisos: list[str] = []
        self.tablas: dict[str, list[dict]] = {}
        self._comercial: dict[int, int] = {}  # contacto -> empresa (commercial_partner_id)

    def _faltante(self, texto: str):
        self.avisos.append(texto)

    def ejecutar(self) -> dict[str, list[dict]]:
        pasos = [
            ("sucursales", self.sucursales), ("productos", self.productos), ("stock", self.stock),
            ("ventas", self.ventas), ("productos", self.productos_vendidos), ("cxc", self.cxc), ("clientes", self.clientes),
            ("vendedores", self.vendedores), ("proveedores", self.proveedores),
        ]
        for nombre, funcion in pasos:
            self.avisar(f"Leyendo {nombre.replace('_', ' ')}…")
            funcion()
        return self.tablas

    # --- maestros ----------------------------------------------------------

    def sucursales(self):
        if not self.c.puede_leer("stock.warehouse"):
            self._faltante("Sin acceso a almacenes: no hay sucursales ni stock por sucursal.")
            self.tablas["sucursales"], self._almacenes = [], []
            return
        self._almacenes = list(self.c.leer_todo("stock.warehouse", [], ["id", "name", "lot_stock_id"]))
        self.tablas["sucursales"] = [{"id": w["id"], "nombre": w["name"]} for w in self._almacenes]

    def productos(self):
        campos = self.c._solo_existentes("product.product", [
            "id", "display_name", "name", "categ_id", "standard_price", "lst_price", "seller_ids", "use_expiration_date"])
        filas = list(self.c.leer_todo("product.product", [("sale_ok", "=", True)], campos, {"active_test": False}))
        proveedores = self.c.leer_ids("product.supplierinfo", [s for f in filas for s in (f.get("seller_ids") or [])[:1]],
                                      ["partner_id", "delay"]) if self.c.puede_leer("product.supplierinfo") else {}
        self._proveedores_producto = defaultdict(list)
        for s in proveedores.values():
            self._proveedores_producto[_id(s.get("partner_id"))].append(s.get("delay"))
        self._costo = {}
        self.tablas["productos"] = []
        for f in filas:
            primero = proveedores.get(((f.get("seller_ids") or [None])[0]))
            self._costo[f["id"]] = float(f.get("standard_price") or 0)
            self.tablas["productos"].append({
                "id": f["id"],
                "descripcion": _CODIGO.sub("", f.get("display_name") or f.get("name") or ""),
                "categoria": _nombre(f.get("categ_id")),
                "proveedor_id": _id(primero.get("partner_id")) if primero else None,
                "costo": float(f.get("standard_price") or 0),
                "precio": float(f.get("lst_price") or 0),
                "unidades_bulto": None,
                "perecedero": 1 if f.get("use_expiration_date") else 0,
            })

    def productos_vendidos(self):
        """Suma los productos que aparecen en ventas pero no son vendibles hoy (archivados, etc.)."""
        conocidos = {p["id"] for p in self.tablas["productos"]}
        faltan = {l["producto_id"] for l in self.tablas["ventas_lineas"]} - conocidos
        campos = self.c._solo_existentes("product.product", ["display_name", "name", "categ_id", "standard_price", "lst_price"])
        for pid, f in self.c.leer_ids("product.product", faltan, campos).items():
            self.tablas["productos"].append({
                "id": pid, "descripcion": _CODIGO.sub("", f.get("display_name") or f.get("name") or ""),
                "categoria": _nombre(f.get("categ_id")), "proveedor_id": None, "costo": float(f.get("standard_price") or 0),
                "precio": float(f.get("lst_price") or 0), "unidades_bulto": None, "perecedero": 0})

    def stock(self):
        self.tablas["stock"] = []
        if not self._almacenes or not self.c.puede_leer("stock.quant"):
            return
        for w in self._almacenes:
            ubicacion = _id(w.get("lot_stock_id"))
            if ubicacion is None:
                continue
            totales = defaultdict(float)
            for q in self.c.leer_todo("stock.quant", [("location_id", "child_of", ubicacion),
                                                      ("location_id.usage", "=", "internal")],
                                      ["product_id", "quantity"]):
                if _id(q.get("product_id")):
                    totales[_id(q["product_id"])] += float(q.get("quantity") or 0)
            self.tablas["stock"] += [{"producto_id": p, "sucursal_id": w["id"], "cantidad": c} for p, c in totales.items()]

    # --- movimientos ---------------------------------------------------------

    def _empresa_de(self, contactos) -> dict[int, int]:
        faltan = [c for c in set(contactos) if c and c not in self._comercial]
        for c, fila in self.c.leer_ids("res.partner", faltan, ["commercial_partner_id"]).items():
            self._comercial[c] = _id(fila.get("commercial_partner_id")) or c
        return self._comercial

    def ventas(self):
        self.tablas["ventas"], self.tablas["ventas_lineas"] = [], []
        if self.c.puede_leer("sale.order"):
            self._ventas_pedidos()
        else:
            self._faltante("Sin acceso a pedidos de venta (rol Ventas: Usuario).")
        if self.c.puede_leer("pos.order"):
            self._ventas_caja()

    def _ventas_pedidos(self):
        pedidos = list(self.c.leer_todo("sale.order", [("date_order", ">=", self.desde), ("state", "in", ["sale", "done", "cancel"])],
                                        ["id", "date_order", "partner_id", "user_id", "warehouse_id", "state"]))
        empresa = self._empresa_de(_id(p["partner_id"]) for p in pedidos)
        for p in pedidos:
            self.tablas["ventas"].append({
                "id": p["id"], "fecha": _fecha(p["date_order"]), "cliente_id": empresa.get(_id(p["partner_id"])),
                "vendedor_id": _id(p.get("user_id")), "sucursal_id": _id(p.get("warehouse_id")),
                "anulada": 1 if p["state"] == "cancel" else 0})
        campos = self.c._solo_existentes("sale.order.line", ["order_id", "product_id", "product_uom_qty", "price_subtotal",
                                                             "purchase_price", "display_type"])
        ids = [p["id"] for p in pedidos]
        for lote in _lotes(ids):
            for l in self.c.leer_todo("sale.order.line", [("order_id", "in", lote), ("product_id", "!=", False)], campos):
                if l.get("display_type"):
                    continue
                cantidad = float(l.get("product_uom_qty") or 0)
                producto = _id(l["product_id"])
                costo = l.get("purchase_price") if "purchase_price" in l else self._costo.get(producto, 0)
                self.tablas["ventas_lineas"].append({
                    "venta_id": _id(l["order_id"]), "producto_id": producto, "cantidad": cantidad,
                    "precio_unitario": round(float(l.get("price_subtotal") or 0) / cantidad, 4) if cantidad else 0,
                    "costo_unitario": float(costo or 0)})
        if "purchase_price" not in self.c.campos("sale.order.line"):
            self._faltante("El costo de cada venta se toma del costo actual del producto (instalá el módulo "
                           "Márgenes en órdenes de venta para usar el costo del momento).")

    def _ventas_caja(self):
        tickets = list(self.c.leer_todo("pos.order", [("date_order", ">=", self.desde),
                                                      ("state", "in", ["paid", "done", "invoiced", "cancel"])],
                                        ["id", "date_order", "partner_id", "user_id", "config_id", "state"]))
        if not tickets:
            return
        configs = self.c.leer_ids("pos.config", [_id(t["config_id"]) for t in tickets], ["picking_type_id"])
        tipos = self.c.leer_ids("stock.picking.type", [_id(c.get("picking_type_id")) for c in configs.values()], ["warehouse_id"])
        almacen = {cid: _id(tipos.get(_id(c.get("picking_type_id")), {}).get("warehouse_id")) for cid, c in configs.items()}
        empresa = self._empresa_de(_id(t["partner_id"]) for t in tickets)
        for t in tickets:
            self.tablas["ventas"].append({
                "id": OFFSET_POS + t["id"], "fecha": _fecha(t["date_order"]), "cliente_id": empresa.get(_id(t["partner_id"])),
                "vendedor_id": _id(t.get("user_id")), "sucursal_id": almacen.get(_id(t["config_id"])),
                "anulada": 1 if t["state"] == "cancel" else 0})
        campos = self.c._solo_existentes("pos.order.line", ["order_id", "product_id", "qty", "price_subtotal", "total_cost"])
        for lote in _lotes([t["id"] for t in tickets]):
            for l in self.c.leer_todo("pos.order.line", [("order_id", "in", lote)], campos):
                cantidad = float(l.get("qty") or 0)
                producto = _id(l["product_id"])
                costo = (float(l["total_cost"]) / cantidad if l.get("total_cost") and cantidad else self._costo.get(producto, 0))
                self.tablas["ventas_lineas"].append({
                    "venta_id": OFFSET_POS + _id(l["order_id"]), "producto_id": producto, "cantidad": cantidad,
                    "precio_unitario": round(float(l.get("price_subtotal") or 0) / cantidad, 4) if cantidad else 0,
                    "costo_unitario": round(costo, 4)})

    def cxc(self):
        self.tablas["cxc"] = []
        if not self.c.puede_leer("account.move"):
            self._faltante("Sin acceso a facturas (rol Facturación): no hay deuda de clientes ni días de cobro.")
            return
        facturas = list(self.c.leer_todo("account.move", [
            ("move_type", "in", ["out_invoice", "out_refund"]), ("state", "=", "posted"),
            "|", ("invoice_date", ">=", self.desde), ("amount_residual", "!=", 0)],
            ["id", "partner_id", "commercial_partner_id", "invoice_date", "invoice_date_due",
             "amount_total_signed", "amount_residual_signed", "payment_state"]))
        cobro = self._fechas_de_cobro([f["id"] for f in facturas if f.get("payment_state") in ("paid", "in_payment")])
        for f in facturas:
            saldo = float(f.get("amount_residual_signed") or 0)
            self.tablas["cxc"].append({
                "id": f["id"], "cliente_id": _id(f.get("commercial_partner_id")) or _id(f.get("partner_id")),
                "fecha_emision": _fecha(f.get("invoice_date")), "fecha_vencimiento": _fecha(f.get("invoice_date_due")) or _fecha(f.get("invoice_date")),
                "fecha_cobro": cobro.get(f["id"]) if not saldo else None,
                "importe": float(f.get("amount_total_signed") or 0), "saldo": saldo})

    def _fechas_de_cobro(self, facturas: list[int]) -> dict[int, str]:
        """Fecha de la última conciliación de la cuenta a cobrar de cada factura pagada."""
        if not facturas:
            return {}
        campos_linea = self.c.campos("account.move.line")
        filtro = ("account_type", "=", "asset_receivable") if "account_type" in campos_linea \
            else ("account_id.internal_type", "=", "receivable")
        salida = {}
        try:
            for lote in _lotes(facturas):
                lineas = list(self.c.leer_todo("account.move.line", [("move_id", "in", lote), filtro],
                                               ["move_id", "matched_credit_ids"]))
                conciliaciones = self.c.leer_ids("account.partial.reconcile",
                                                 [p for l in lineas for p in l.get("matched_credit_ids") or []], ["max_date"])
                for l in lineas:
                    fechas = [conciliaciones[p]["max_date"] for p in l.get("matched_credit_ids") or [] if p in conciliaciones]
                    if fechas:
                        salida[_id(l["move_id"])] = max(salida.get(_id(l["move_id"]), ""), max(fechas))
        except OdooError as e:
            self._faltante(f"No se pudo leer la fecha de cobro de las facturas pagadas ({e}).")
        return salida

    # --- personas ------------------------------------------------------------

    def clientes(self):
        usados = {v["cliente_id"] for v in self.tablas["ventas"]} | {x["cliente_id"] for x in self.tablas["cxc"]}
        dominio = ["|", ("customer_rank", ">", 0), ("id", "in", sorted(i for i in usados if i))]
        campos = self.c._solo_existentes("res.partner", [
            "id", "name", "is_company", "category_id", "city", "state_id", "user_id",
            "property_payment_term_id", "credit_limit", "create_date", "parent_id"])
        filas = [f for f in self.c.leer_todo("res.partner", dominio, campos, {"active_test": False})
                 if not f.get("parent_id") or f["id"] in usados]
        plazos = self._dias_de_plazo([_id(f.get("property_payment_term_id")) for f in filas])
        categorias = self.c.leer_ids("res.partner.category", [c for f in filas for c in (f.get("category_id") or [])[:1]], ["name"]) \
            if any(f.get("category_id") for f in filas) else {}
        self.tablas["clientes"] = [{
            "id": f["id"], "razon_social": f["name"],
            "tipo": categorias.get((f.get("category_id") or [None])[0], {}).get("name") or ("empresa" if f.get("is_company") else "persona"),
            "zona": _texto(f.get("city")) or _nombre(f.get("state_id")),
            "vendedor_id": _id(f.get("user_id")),
            "condicion_pago_dias": plazos.get(_id(f.get("property_payment_term_id")), 0),
            "limite_credito": float(f["credit_limit"]) if f.get("credit_limit") else None,
            "fecha_alta": _fecha(f.get("create_date")),
        } for f in filas]
        sin_vendedor = sum(1 for c in self.tablas["clientes"] if c["vendedor_id"] is None)
        if sin_vendedor:
            self._faltante(f"{sin_vendedor} clientes no tienen «Vendedor» en su ficha de Odoo: ningún vendedor los va a ver en su cartera.")

    def _dias_de_plazo(self, terminos) -> dict[int, int]:
        """Días del último vencimiento de cada término de pago (30 días, 30/60...)."""
        if not any(terminos) or not self.c.puede_leer("account.payment.term"):
            return {}
        campo = "nb_days" if "nb_days" in self.c.campos("account.payment.term.line") else "days"
        terminos_leidos = self.c.leer_ids("account.payment.term", terminos, ["line_ids"])
        lineas = self.c.leer_ids("account.payment.term.line", [l for t in terminos_leidos.values() for l in t.get("line_ids") or []], [campo])
        return {t: max([int(lineas[l].get(campo) or 0) for l in fila.get("line_ids") or [] if l in lineas] or [0])
                for t, fila in terminos_leidos.items()}

    def vendedores(self):
        ids = {c["vendedor_id"] for c in self.tablas["clientes"]} | {v["vendedor_id"] for v in self.tablas["ventas"]}
        filas = self.c.leer_ids("res.users", ids, ["name"]) if ids - {None} else {}
        self.tablas["vendedores"] = [{"id": i, "nombre": f["name"], "sucursal_id": None} for i, f in filas.items()]

    def proveedores(self):
        ids = set(self._proveedores_producto) - {None}
        dominio = ["|", ("supplier_rank", ">", 0), ("id", "in", sorted(ids))]
        campos = self.c._solo_existentes("res.partner", ["id", "name", "property_supplier_payment_term_id", "parent_id"])
        filas = [f for f in self.c.leer_todo("res.partner", dominio, campos, {"active_test": False}) if not f.get("parent_id") or f["id"] in ids]
        plazos = self._dias_de_plazo([_id(f.get("property_supplier_payment_term_id")) for f in filas])
        self.tablas["proveedores"] = [{
            "id": f["id"], "nombre": f["name"],
            "plazo_pago_dias": plazos.get(_id(f.get("property_supplier_payment_term_id"))),
            "plazo_entrega_dias": min((d for d in self._proveedores_producto.get(f["id"], []) if d is not None), default=None),
            "pedido_minimo": None,
        } for f in filas]
