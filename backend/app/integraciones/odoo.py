"""Integración con Odoo (12 o superior) por su API JSON-RPC, en solo lectura.

Lee Odoo y lo traduce al modelo estándar de la plataforma (app/erp/modelo.py):
las 35 tablas de Ventas, Inventario y Finanzas. Cada tabla se lee por separado:
si falta un módulo o un permiso, esa tabla queda vacía con un aviso y el resto
se sincroniza igual.

Solo usa métodos de lectura (version, authenticate, search_read, read,
read_group, search_count, check_access_rights, fields_get), bloqueado también
en el código: nunca crea ni modifica nada en Odoo.

Fechas: Odoo guarda fecha y hora en UTC; se convierten a la zona horaria del
usuario de la integración (o America/Montevideo si no tiene), igual que las
muestra Odoo en sus reportes.

Mapeo principal:
  stock.warehouse -> sucursales            res.users / crm.team -> vendedores (equipo)
  res.partner -> clientes / proveedores    product.product -> productos
  stock.quant + stock.lot -> stock         stock.move -> movimientos_stock
  sale.order -> ventas, pedidos, presupuestos (canal = equipo de ventas)
  pos.order -> ventas (tickets, id 1.000.000.000 + id)
  purchase.order -> compras                stock.valuation.layer -> costos_historial
  account.move (cliente) -> cxc, devoluciones   account.move (proveedor) -> cxp
  account.payment -> cobranzas / pagos     account.journal -> cuentas_bancarias
  account.bank.statement.line -> movimientos_bancarios
  account.move.line (gastos, impuestos) -> gastos, impuestos
  product.pricelist -> listas_precios, precios   loyalty.program -> promociones
  res.currency.rate -> tipos_cambio        mrp.bom (kits) -> componentes_kit
"""
from __future__ import annotations

import itertools
import json
import re
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Transporte = Callable[[str, dict], dict]
OFFSET_POS = 1_000_000_000  # los tickets de caja comparten tabla con los pedidos de venta
ZONA_POR_DEFECTO = "America/Montevideo"
_METODOS_LECTURA = {"search_read", "read", "read_group", "search_count", "search", "check_access_rights", "fields_get"}


class OdooError(RuntimeError):
    pass


def _http(url: str, payload: dict, timeout: float = 120) -> dict:
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


def _num(valor) -> float | None:
    return float(valor) if isinstance(valor, (int, float)) and not isinstance(valor, bool) else None


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
        self._permisos: dict[str, bool] = {}

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

    def agrupar(self, modelo: str, dominio: list, campos: list, grupos: list, contexto: dict | None = None) -> list[dict]:
        return self.ejecutar(modelo, "read_group", [dominio, campos, grupos],
                             {"lazy": False, **({"context": contexto} if contexto else {})})

    def puede_leer(self, modelo: str) -> bool:
        if modelo not in self._permisos:
            try:
                self._permisos[modelo] = bool(self.ejecutar(modelo, "check_access_rights", ["read"], {"raise_exception": False}))
            except OdooError:
                self._permisos[modelo] = False  # el módulo no está instalado
        return self._permisos[modelo]

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

    def zona_horaria(self) -> str:
        try:
            tz = self.leer_ids("res.users", [self.uid], ["tz"]).get(self.uid, {}).get("tz")
        except OdooError:
            tz = None
        return tz or ZONA_POR_DEFECTO


# Qué necesita la plataforma de Odoo y qué pasa si falta: (modelo, qué trae, crítico, rol en Odoo).
MODELOS = [
    ("res.partner", "clientes y proveedores", True, "Contactos"),
    ("product.product", "productos", True, "Inventario o Ventas"),
    ("sale.order", "pedidos de venta", False, "Ventas: Usuario (todos los documentos)"),
    ("pos.order", "ventas de caja", False, "Punto de Venta: Usuario"),
    ("account.move", "facturas de clientes y proveedores", False, "Facturación: Facturación"),
    ("account.payment", "cobranzas y pagos", False, "Facturación: Facturación"),
    ("stock.quant", "stock por almacén", False, "Inventario: Usuario"),
    ("stock.move", "movimientos de stock", False, "Inventario: Usuario"),
    ("stock.warehouse", "almacenes (sucursales)", False, "Inventario: Usuario"),
    ("purchase.order", "compras", False, "Compras: Usuario"),
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
    paso("Acceso", True, f"Usuario {cliente.usuario} (id {uid}) en la base {cliente.db}, hora de {cliente.zona_horaria()}")

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
        paso("Permisos", True, "Puede leer clientes, productos, ventas, caja, compras, facturas, pagos y stock")

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


_CATEGORIAS_GASTO = [
    ("personal", ("sueldo", "salario", "jornal", "aguinaldo", "cargas sociales", "bps", "personal", "vacacion")),
    ("alquiler", ("alquiler", "arrendamiento")),
    ("energia", ("energía", "energia", "luz", "ute", "gas", "agua", "ose")),
    ("logistica", ("flete", "combustible", "logística", "logistica", "transporte", "reparto")),
    ("mantenimiento", ("mantenimiento", "reparación", "reparacion")),
    ("seguros", ("seguro",)),
    ("comisiones", ("comisión", "comision")),
    ("marketing", ("publicidad", "marketing", "propaganda")),
    ("sistemas", ("software", "sistema", "licencia", "internet", "telefon")),
    ("servicios", ("honorario", "servicio", "limpieza", "vigilancia")),
]


def categoria_gasto(cuenta: str) -> str:
    texto = (cuenta or "").lower()
    return next((c for c, palabras in _CATEGORIAS_GASTO if any(p in texto for p in palabras)), "otros")


class Extraccion:
    """Lee Odoo y arma las filas de cada tabla del modelo estándar."""

    def __init__(self, cliente: ClienteOdoo, meses: int = 12, avisar: Callable[[str], None] | None = None,
                 hoy: date | None = None, zona: str | None = None):
        self.c = cliente
        self.hoy = hoy or date.today()
        self.desde = (self.hoy - timedelta(days=round(meses * 30.44))).isoformat()
        self.avisar = avisar or (lambda _texto: None)
        self.avisos: list[str] = []
        self.tablas: dict[str, list[dict]] = defaultdict(list)
        self._comercial: dict[int, int] = {}  # contacto -> empresa (commercial_partner_id)
        self._almacenes: list[dict] = []
        self._costo: dict[int, float] = {}
        self._proveedores_producto: dict = defaultdict(list)
        self._plantilla: dict[int, list[int]] = {}  # plantilla -> variantes
        self._zona_nombre = zona
        self.zona = None

    # --- utilidades ------------------------------------------------------------

    def _faltante(self, texto: str):
        self.avisos.append(texto)

    def _local(self, valor) -> tuple[str | None, str | None]:
        """Fecha y hora local a partir de un datetime UTC de Odoo ("AAAA-MM-DD HH:MM:SS")."""
        if not isinstance(valor, str) or not valor:
            return None, None
        try:
            momento = datetime.strptime(valor[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(self.zona)
        except ValueError:
            return valor[:10], None
        return momento.date().isoformat(), momento.strftime("%H:%M")

    def _desde_utc(self) -> str:
        """Medianoche local del primer día, expresada en UTC (para filtrar datetimes de Odoo)."""
        inicio = datetime.fromisoformat(self.desde).replace(tzinfo=self.zona)
        return inicio.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def _empresa_de(self, contactos) -> dict[int, int]:
        faltan = [c for c in set(contactos) if c and c not in self._comercial]
        for c, fila in self.c.leer_ids("res.partner", faltan, ["commercial_partner_id"]).items():
            self._comercial[c] = _id(fila.get("commercial_partner_id")) or c
        return self._comercial

    def _dias_de_plazo(self, terminos) -> dict[int, int]:
        """Días del último vencimiento de cada término de pago (30 días, 30/60...)."""
        terminos = [t for t in terminos if t]
        if not terminos or not self.c.puede_leer("account.payment.term"):
            return {}
        campo = "nb_days" if "nb_days" in self.c.campos("account.payment.term.line") else "days"
        leidos = self.c.leer_ids("account.payment.term", terminos, ["line_ids"])
        lineas = self.c.leer_ids("account.payment.term.line", [l for t in leidos.values() for l in t.get("line_ids") or []], [campo])
        return {t: max([int(lineas[l].get(campo) or 0) for l in fila.get("line_ids") or [] if l in lineas] or [0])
                for t, fila in leidos.items()}

    def _fechas_conciliacion(self, movimientos: list[int], tipo_cuenta: str, campo: str) -> dict[int, str]:
        """Fecha de la última conciliación de la cuenta a cobrar/pagar de cada comprobante."""
        if not movimientos:
            return {}
        campos_linea = self.c.campos("account.move.line")
        filtro = ("account_type", "=", tipo_cuenta) if "account_type" in campos_linea \
            else ("account_id.internal_type", "=", "receivable" if "receivable" in tipo_cuenta else "payable")
        salida = {}
        for lote in _lotes(movimientos):
            lineas = list(self.c.leer_todo("account.move.line", [("move_id", "in", lote), filtro], ["move_id", campo]))
            conc = self.c.leer_ids("account.partial.reconcile", [p for l in lineas for p in l.get(campo) or []], ["max_date"])
            for l in lineas:
                fechas = [conc[p]["max_date"] for p in l.get(campo) or [] if p in conc]
                if fechas:
                    salida[_id(l["move_id"])] = max(salida.get(_id(l["move_id"]), ""), max(fechas))
        return salida

    # --- orquestación --------------------------------------------------------------

    PASOS = [
        ("sucursales", "sucursales"), ("productos", "productos"), ("stock", "stock"), ("ventas", "ventas"),
        ("pedidos y presupuestos", "pedidos"), ("productos vendidos", "productos_vendidos"),
        ("facturas de clientes", "cxc"), ("cobranzas", "cobranzas"), ("clientes", "clientes"),
        ("vendedores", "vendedores"), ("proveedores", "proveedores"), ("compras", "compras"),
        ("facturas de proveedores", "cxp"), ("pagos", "pagos"), ("movimientos de stock", "movimientos_stock"),
        ("historial de costos", "costos_historial"), ("kits", "componentes_kit"), ("listas de precios", "precios"),
        ("promociones", "promociones"), ("bancos y cajas", "bancos"), ("gastos", "gastos"), ("impuestos", "impuestos"),
        ("tipos de cambio", "tipos_cambio"), ("préstamos", "prestamos"), ("presupuesto", "presupuesto"),
        ("cheques", "cheques"),
    ]
    SIN_EQUIVALENTE = {
        "visitas": "Odoo no registra visitas de vendedores.",
        "objetivos_vendedores": "Odoo no tiene objetivos de venta por vendedor (solo por equipo).",
        "conteos": "Los conteos de inventario de Odoo no guardan la cantidad que había en sistema.",
    }

    def ejecutar(self) -> dict[str, list[dict]]:
        self.c.uid  # sin acceso no se sigue: la base anterior queda intacta
        self.zona = self._zona(self._zona_nombre or self.c.zona_horaria())
        for titulo, metodo in self.PASOS:
            self.avisar(f"Leyendo {titulo}…")
            antes = {t: len(filas) for t, filas in self.tablas.items()}
            try:
                getattr(self, metodo)()
            except OSError:
                raise  # se cortó la conexión: se cancela todo y se conserva la base anterior
            except Exception as e:  # un módulo que falta o falla no frena al resto
                for t in list(self.tablas):  # se deshace lo que el paso alcanzó a cargar
                    del self.tablas[t][antes.get(t, 0):]
                self._faltante(f"No se pudo leer {titulo}: {e}")
        return dict(self.tablas)

    def _zona(self, nombre: str):
        try:
            return ZoneInfo(nombre)
        except (ZoneInfoNotFoundError, ValueError):
            self._faltante(f"Zona horaria desconocida «{nombre}»: se usa {ZONA_POR_DEFECTO}.")
            return ZoneInfo(ZONA_POR_DEFECTO)

    # --- inventario --------------------------------------------------------------

    def sucursales(self):
        if not self.c.puede_leer("stock.warehouse"):
            self._faltante("Sin acceso a almacenes: no hay sucursales ni stock por sucursal.")
            return
        self._almacenes = list(self.c.leer_todo("stock.warehouse", [], ["id", "name", "lot_stock_id"]))
        self.tablas["sucursales"] = [{"id": w["id"], "nombre": w["name"], "tipo": "sucursal"} for w in self._almacenes]

    def _fila_producto(self, f: dict, proveedores: dict, impuestos: dict, unidades: dict) -> dict:
        primero = proveedores.get((f.get("seller_ids") or [None])[0])
        unidad = unidades.get(_id(f.get("uom_id")), {})
        iva = [impuestos[t]["amount"] / 100 for t in f.get("taxes_id") or [] if t in impuestos
               and impuestos[t].get("amount_type") == "percent"]
        categoria = _nombre(f.get("categ_id")) or ""
        partes = [p.strip() for p in categoria.split("/") if p.strip()]
        return {
            "id": f["id"], "codigo": _texto(f.get("default_code")), "codigo_barras": _texto(f.get("barcode")),
            "descripcion": _CODIGO.sub("", f.get("display_name") or f.get("name") or ""),
            "categoria": partes[1] if len(partes) > 1 else (partes[0] if partes else None),
            "subcategoria": partes[-1] if len(partes) > 2 else None, "familia": partes[2] if len(partes) > 3 else None,
            "proveedor_id": _id(primero.get("partner_id")) if primero else None,
            "unidad": _nombre(f.get("uom_id")), "peso_kg": _num(f.get("weight")) or None, "volumen_m3": _num(f.get("volume")) or None,
            "pesable": 1 if unidad.get("categoria", "").lower() in ("weight", "peso") else 0,
            "perecedero": 1 if f.get("use_expiration_date") else 0,
            "vida_util_dias": int(f["expiration_time"]) if f.get("expiration_time") else None,
            "tasa_iva": iva[0] if iva else None, "estado": "activo" if f.get("active", True) else "archivado",
            "fecha_alta": self._local(f.get("create_date"))[0], "costo": float(f.get("standard_price") or 0),
            "precio": float(f.get("lst_price") or 0),
        }

    def _leer_productos(self, dominio: list, ids=None) -> list[dict]:
        campos = self.c._solo_existentes("product.product", [
            "id", "display_name", "name", "default_code", "barcode", "categ_id", "standard_price", "lst_price", "seller_ids",
            "uom_id", "weight", "volume", "use_expiration_date", "expiration_time", "taxes_id", "active", "create_date",
            "product_tmpl_id"])
        if ids is not None:
            filas = list(self.c.leer_ids("product.product", ids, campos).values())
        else:
            filas = list(self.c.leer_todo("product.product", dominio, campos, {"active_test": False}))
        proveedores = self.c.leer_ids("product.supplierinfo", [s for f in filas for s in (f.get("seller_ids") or [])[:1]],
                                      ["partner_id", "delay"]) if self.c.puede_leer("product.supplierinfo") else {}
        for s in proveedores.values():
            self._proveedores_producto[_id(s.get("partner_id"))].append(s.get("delay"))
        impuestos = self.c.leer_ids("account.tax", {t for f in filas for t in f.get("taxes_id") or []}, ["amount", "amount_type"]) \
            if self.c.puede_leer("account.tax") else {}
        unidades = {}
        uoms = self.c.leer_ids("uom.uom", {_id(f.get("uom_id")) for f in filas}, ["category_id"]) if self.c.puede_leer("uom.uom") else {}
        for u, fila in uoms.items():
            unidades[u] = {"categoria": _nombre(fila.get("category_id")) or ""}
        for f in filas:
            self._costo[f["id"]] = float(f.get("standard_price") or 0)
            self._plantilla.setdefault(_id(f.get("product_tmpl_id")), []).append(f["id"])
        return [self._fila_producto(f, proveedores, impuestos, unidades) for f in filas]

    def productos(self):
        self.tablas["productos"] = self._leer_productos([("sale_ok", "=", True)])

    def productos_vendidos(self):
        """Suma los productos que aparecen en ventas o pedidos pero no son vendibles hoy (archivados, etc.)."""
        conocidos = {p["id"] for p in self.tablas["productos"]}
        usados = {l["producto_id"] for t in ("ventas_lineas", "pedidos_lineas") for l in self.tablas[t]}
        faltan = usados - conocidos - {None}
        if faltan:
            self.tablas["productos"] += self._leer_productos([], ids=faltan)

    def stock(self):
        if not self._almacenes or not self.c.puede_leer("stock.quant"):
            return
        campos_quant = self.c._solo_existentes("stock.quant", ["product_id", "quantity", "reserved_quantity", "lot_id", "location_id"])
        vencimientos = {}
        for w in self._almacenes:
            ubicacion = _id(w.get("lot_stock_id"))
            if ubicacion is None:
                continue
            filas = defaultdict(lambda: [0.0, 0.0])
            for q in self.c.leer_todo("stock.quant", [("location_id", "child_of", ubicacion), ("location_id.usage", "=", "internal")],
                                      campos_quant):
                if _id(q.get("product_id")):
                    clave = (_id(q["product_id"]), _id(q.get("lot_id")), _nombre(q.get("lot_id")))
                    filas[clave][0] += float(q.get("quantity") or 0)
                    filas[clave][1] += float(q.get("reserved_quantity") or 0)
            lotes = {k[1] for k in filas if k[1]}
            if lotes and self.c.puede_leer("stock.lot") and "expiration_date" in self.c.campos("stock.lot"):
                for lid, lote in self.c.leer_ids("stock.lot", lotes - set(vencimientos), ["expiration_date"]).items():
                    vencimientos[lid] = self._local(lote.get("expiration_date"))[0]
            self.tablas["stock"] += [{"producto_id": p, "sucursal_id": w["id"], "lote": nombre_lote,
                                      "fecha_vencimiento": vencimientos.get(lote), "cantidad": c, "comprometido": r or None}
                                     for (p, lote, nombre_lote), (c, r) in filas.items()]
        # En tránsito: movimientos de entrada todavía no recibidos
        if self.c.puede_leer("stock.move"):
            transito = defaultdict(float)
            for m in self.c.leer_todo("stock.move", [("state", "in", ["confirmed", "waiting", "assigned", "partially_available"]),
                                                     ("location_id.usage", "in", ["supplier", "transit"]),
                                                     ("location_dest_id.usage", "=", "internal")],
                                      self.c._solo_existentes("stock.move", ["product_id", "product_qty", "warehouse_id", "location_dest_id"])):
                transito[(_id(m.get("product_id")), _id(m.get("warehouse_id")))] += float(m.get("product_qty") or 0)
            self.tablas["stock"] += [{"producto_id": p, "sucursal_id": w, "cantidad": 0, "en_transito": q}
                                     for (p, w), q in transito.items() if p]

    def movimientos_stock(self):
        if not self.c.puede_leer("stock.move"):
            return
        # Cantidad hecha: "quantity" en Odoo 17+, "quantity_done" hasta la 16.
        hecha = next((c for c in ("quantity", "quantity_done") if c in self.c.campos("stock.move")), "product_qty")
        campos = self.c._solo_existentes("stock.move", ["date", "product_id", hecha, "location_id", "location_dest_id",
                                                        "price_unit", "reference", "origin", "scrapped", "is_inventory", "picking_type_id"])
        movs = list(self.c.leer_todo("stock.move", [("state", "=", "done"), ("date", ">=", self._desde_utc())], campos))
        ubicaciones = self.c.leer_ids("stock.location", {_id(m.get(c)) for m in movs for c in ("location_id", "location_dest_id")},
                                      self.c._solo_existentes("stock.location", ["usage", "warehouse_id", "scrap_location"]))

        def tipo(origen, destino, m):
            o, d = origen.get("usage"), destino.get("usage")
            if destino.get("scrap_location") or m.get("scrapped"):
                return "merma"
            return {("supplier", "internal"): "compra", ("internal", "supplier"): "devolucion_proveedor",
                    ("internal", "customer"): "venta", ("customer", "internal"): "devolucion_cliente",
                    ("internal", "inventory"): "ajuste", ("inventory", "internal"): "ajuste",
                    ("internal", "production"): "consumo_interno", ("production", "internal"): "produccion"}.get((o, d))

        for i, m in enumerate(movs, start=1):
            origen = ubicaciones.get(_id(m.get("location_id")), {})
            destino = ubicaciones.get(_id(m.get("location_dest_id")), {})
            fecha = self._local(m.get("date"))[0]
            cantidad = float(m.get(hecha) or 0)
            costo = _num(m.get("price_unit")) or self._costo.get(_id(m.get("product_id")))
            base = {"fecha": fecha, "producto_id": _id(m.get("product_id")), "costo_unitario": costo,
                    "comprobante": _texto(m.get("reference")), "motivo": _texto(m.get("origin"))}
            if origen.get("usage") == "internal" and destino.get("usage") == "internal":
                if _id(origen.get("warehouse_id")) == _id(destino.get("warehouse_id")):
                    continue  # movimiento interno dentro del mismo depósito
                self.tablas["movimientos_stock"] += [
                    {**base, "tipo": "transferencia_salida", "sucursal_id": _id(origen.get("warehouse_id")), "cantidad": -cantidad},
                    {**base, "tipo": "transferencia_entrada", "sucursal_id": _id(destino.get("warehouse_id")), "cantidad": cantidad}]
                continue
            t = tipo(origen, destino, m)
            if not t:
                continue
            sale = origen.get("usage") == "internal"
            self.tablas["movimientos_stock"].append({**base, "tipo": t, "cantidad": -cantidad if sale else cantidad,
                                                     "sucursal_id": _id((origen if sale else destino).get("warehouse_id"))})
        for i, fila in enumerate(self.tablas["movimientos_stock"], start=1):
            fila["id"] = i

    def costos_historial(self):
        if not self.c.puede_leer("stock.valuation.layer"):
            return
        capas = self.c.leer_todo("stock.valuation.layer", [("create_date", ">=", self._desde_utc()), ("quantity", ">", 0)],
                                 ["product_id", "unit_cost", "create_date"])
        vistos = set()
        for c in capas:
            clave = (_id(c.get("product_id")), self._local(c.get("create_date"))[0])
            if clave in vistos or not clave[0]:
                continue
            vistos.add(clave)
            self.tablas["costos_historial"].append({"producto_id": clave[0], "fecha": clave[1], "costo": float(c.get("unit_cost") or 0)})

    def componentes_kit(self):
        if not self.c.puede_leer("mrp.bom"):
            return
        boms = list(self.c.leer_todo("mrp.bom", [("type", "=", "phantom")], ["product_tmpl_id", "product_id", "bom_line_ids"]))
        lineas = self.c.leer_ids("mrp.bom.line", [l for b in boms for l in b.get("bom_line_ids") or []], ["product_id", "product_qty"])
        for b in boms:
            kits = [_id(b["product_id"])] if _id(b.get("product_id")) else self._plantilla.get(_id(b.get("product_tmpl_id")), [])
            for kit in kits:
                for l in b.get("bom_line_ids") or []:
                    if l in lineas:
                        self.tablas["componentes_kit"].append({"kit_id": kit, "producto_id": _id(lineas[l]["product_id"]),
                                                               "cantidad": float(lineas[l].get("product_qty") or 0)})
        for p in self.tablas["productos"]:
            if p["id"] in {k["kit_id"] for k in self.tablas["componentes_kit"]}:
                p["es_kit"] = 1

    def compras(self):
        if not self.c.puede_leer("purchase.order"):
            return
        campos = self.c._solo_existentes("purchase.order", ["name", "partner_id", "picking_type_id", "date_order", "date_approve",
                                                            "date_planned", "effective_date", "state", "currency_id"])
        ordenes = list(self.c.leer_todo("purchase.order", [("date_order", ">=", self._desde_utc()),
                                                           ("state", "in", ["purchase", "done", "cancel"])], campos))
        tipos = self.c.leer_ids("stock.picking.type", {_id(o.get("picking_type_id")) for o in ordenes}, ["warehouse_id"])
        empresa = self._empresa_de(_id(o["partner_id"]) for o in ordenes)
        estados = {"purchase": "confirmada", "done": "cerrada", "cancel": "anulada"}
        for o in ordenes:
            self.tablas["compras"].append({
                "id": o["id"], "numero": o.get("name"), "proveedor_id": empresa.get(_id(o["partner_id"])),
                "sucursal_id": _id(tipos.get(_id(o.get("picking_type_id")), {}).get("warehouse_id")),
                "fecha": self._local(o.get("date_approve") or o.get("date_order"))[0],
                "fecha_prometida": self._local(o.get("date_planned"))[0], "fecha_recepcion": self._local(o.get("effective_date"))[0],
                "estado": estados.get(o["state"], o["state"]), "moneda": _nombre(o.get("currency_id"))})
        campos_l = self.c._solo_existentes("purchase.order.line", ["order_id", "product_id", "product_qty", "qty_received",
                                                                   "price_unit", "display_type"])
        for lote in _lotes([o["id"] for o in ordenes]):
            for l in self.c.leer_todo("purchase.order.line", [("order_id", "in", lote), ("product_id", "!=", False)], campos_l):
                if l.get("display_type"):
                    continue
                self.tablas["compras_lineas"].append({
                    "compra_id": _id(l["order_id"]), "producto_id": _id(l["product_id"]),
                    "cantidad_pedida": float(l.get("product_qty") or 0), "cantidad_recibida": _num(l.get("qty_received")),
                    "precio_pactado": _num(l.get("price_unit"))})

    # --- ventas --------------------------------------------------------------------

    def ventas(self):
        if self.c.puede_leer("sale.order"):
            self._ventas_pedidos()
        else:
            self._faltante("Sin acceso a pedidos de venta (rol Ventas: Usuario).")
        if self.c.puede_leer("pos.order"):
            self._ventas_caja()

    def _plazos_pedidos(self, pedidos) -> dict:
        return self._dias_de_plazo({_id(p.get("payment_term_id")) for p in pedidos})

    def _ventas_pedidos(self):
        campos = self.c._solo_existentes("sale.order", ["name", "date_order", "partner_id", "user_id", "warehouse_id", "state",
                                                        "team_id", "currency_id", "payment_term_id"])
        pedidos = list(self.c.leer_todo("sale.order", [("date_order", ">=", self._desde_utc()),
                                                       ("state", "in", ["sale", "done", "cancel"])], campos))
        empresa = self._empresa_de(_id(p["partner_id"]) for p in pedidos)
        plazos = self._plazos_pedidos(pedidos)
        for p in pedidos:
            fecha, hora = self._local(p["date_order"])
            self.tablas["ventas"].append({
                "id": p["id"], "tipo": "orden_venta", "numero": p.get("name"), "fecha": fecha, "hora": hora,
                "cliente_id": empresa.get(_id(p["partner_id"])), "vendedor_id": _id(p.get("user_id")),
                "sucursal_id": _id(p.get("warehouse_id")), "canal": _nombre(p.get("team_id")),
                "moneda": _nombre(p.get("currency_id")), "condicion_pago_dias": plazos.get(_id(p.get("payment_term_id"))),
                "anulada": 1 if p["state"] == "cancel" else 0})
        campos_l = self.c._solo_existentes("sale.order.line", ["order_id", "product_id", "product_uom_qty", "price_unit", "discount",
                                                               "price_subtotal", "price_total", "purchase_price", "display_type"])
        for lote in _lotes([p["id"] for p in pedidos]):
            for l in self.c.leer_todo("sale.order.line", [("order_id", "in", lote), ("product_id", "!=", False)], campos_l):
                if l.get("display_type"):
                    continue
                cantidad = float(l.get("product_uom_qty") or 0)
                producto = _id(l["product_id"])
                costo = l.get("purchase_price") if "purchase_price" in l else self._costo.get(producto, 0)
                neto = float(l.get("price_subtotal") or 0)
                self.tablas["ventas_lineas"].append({
                    "venta_id": _id(l["order_id"]), "producto_id": producto, "cantidad": cantidad,
                    "precio_lista": _num(l.get("price_unit")), "descuento_pct": (l.get("discount") or 0) / 100,
                    "precio_unitario": round(neto / cantidad, 6) if cantidad else 0, "costo_unitario": float(costo or 0),
                    "impuestos": round(float(l.get("price_total") or neto) - neto, 2)})
        if "purchase_price" not in self.c.campos("sale.order.line"):
            self._faltante("El costo de cada venta se toma del costo actual del producto (instalá el módulo "
                           "Márgenes en órdenes de venta para usar el costo del momento).")

    def _ventas_caja(self):
        campos = self.c._solo_existentes("pos.order", ["name", "date_order", "partner_id", "user_id", "config_id", "state",
                                                       "crm_team_id", "currency_id"])
        tickets = list(self.c.leer_todo("pos.order", [("date_order", ">=", self._desde_utc()),
                                                      ("state", "in", ["paid", "done", "invoiced", "cancel"])], campos))
        if not tickets:
            return
        configs = self.c.leer_ids("pos.config", [_id(t["config_id"]) for t in tickets], ["name", "picking_type_id"])
        tipos = self.c.leer_ids("stock.picking.type", [_id(c.get("picking_type_id")) for c in configs.values()], ["warehouse_id"])
        almacen = {cid: _id(tipos.get(_id(c.get("picking_type_id")), {}).get("warehouse_id")) for cid, c in configs.items()}
        empresa = self._empresa_de(_id(t["partner_id"]) for t in tickets)
        medios = {}
        if self.c.puede_leer("pos.payment"):
            for lote in _lotes([t["id"] for t in tickets]):
                for pago in self.c.leer_todo("pos.payment", [("pos_order_id", "in", lote)], ["pos_order_id", "payment_method_id"]):
                    medios.setdefault(_id(pago["pos_order_id"]), _nombre(pago.get("payment_method_id")))
        for t in tickets:
            fecha, hora = self._local(t["date_order"])
            self.tablas["ventas"].append({
                "id": OFFSET_POS + t["id"], "tipo": "ticket", "numero": t.get("name"), "fecha": fecha, "hora": hora,
                "cliente_id": empresa.get(_id(t["partner_id"])), "vendedor_id": _id(t.get("user_id")),
                "sucursal_id": almacen.get(_id(t["config_id"])), "canal": _nombre(t.get("crm_team_id")),
                "moneda": _nombre(t.get("currency_id")), "medio_pago": medios.get(t["id"]),
                "caja": configs.get(_id(t["config_id"]), {}).get("name"), "anulada": 1 if t["state"] == "cancel" else 0})
        campos_l = self.c._solo_existentes("pos.order.line", ["order_id", "product_id", "qty", "price_unit", "discount",
                                                              "price_subtotal", "price_subtotal_incl", "total_cost"])
        for lote in _lotes([t["id"] for t in tickets]):
            for l in self.c.leer_todo("pos.order.line", [("order_id", "in", lote)], campos_l):
                cantidad = float(l.get("qty") or 0)
                producto = _id(l["product_id"])
                costo = (float(l["total_cost"]) / cantidad if l.get("total_cost") and cantidad else self._costo.get(producto, 0))
                neto = float(l.get("price_subtotal") or 0)
                self.tablas["ventas_lineas"].append({
                    "venta_id": OFFSET_POS + _id(l["order_id"]), "producto_id": producto, "cantidad": cantidad,
                    "precio_lista": _num(l.get("price_unit")), "descuento_pct": (l.get("discount") or 0) / 100,
                    "precio_unitario": round(neto / cantidad, 6) if cantidad else 0, "costo_unitario": round(costo, 4),
                    "impuestos": round(float(l.get("price_subtotal_incl") or neto) - neto, 2)})

    def pedidos(self):
        """Pedidos (todo lo confirmado, con lo entregado) y presupuestos (todas las cotizaciones y si se aceptaron)."""
        if not self.c.puede_leer("sale.order"):
            return
        campos = self.c._solo_existentes("sale.order", ["name", "date_order", "partner_id", "user_id", "warehouse_id", "state",
                                                        "commitment_date", "expected_date", "effective_date", "delivery_status",
                                                        "amount_untaxed"])
        ordenes = list(self.c.leer_todo("sale.order", [("create_date", ">=", self._desde_utc())], campos))
        empresa = self._empresa_de(_id(o["partner_id"]) for o in ordenes)
        entrega = {"pending": "pendiente", "started": "parcial", "partial": "parcial", "full": "entregado"}
        for o in ordenes:
            cliente = empresa.get(_id(o["partner_id"]))
            fecha = self._local(o.get("date_order"))[0]
            aceptado = o["state"] in ("sale", "done")
            self.tablas["presupuestos"].append({
                "id": o["id"], "numero": o.get("name"), "cliente_id": cliente, "vendedor_id": _id(o.get("user_id")), "fecha": fecha,
                "importe": float(o.get("amount_untaxed") or 0),
                "estado": "aceptado" if aceptado else ("rechazado" if o["state"] == "cancel" else "enviado"),
                "venta_id": o["id"] if aceptado else None})
            if aceptado or o["state"] == "cancel":
                self.tablas["pedidos"].append({
                    "id": o["id"], "numero": o.get("name"), "cliente_id": cliente, "vendedor_id": _id(o.get("user_id")),
                    "sucursal_id": _id(o.get("warehouse_id")), "fecha_pedido": fecha,
                    "fecha_entrega_prometida": self._local(o.get("commitment_date") or o.get("expected_date"))[0],
                    "fecha_entrega": self._local(o.get("effective_date"))[0],
                    "estado": "anulado" if o["state"] == "cancel" else entrega.get(o.get("delivery_status"), "pendiente")})
        confirmados = [p["id"] for p in self.tablas["pedidos"]]
        for lote in _lotes(confirmados):
            for l in self.c.leer_todo("sale.order.line", [("order_id", "in", lote), ("product_id", "!=", False)],
                                      self.c._solo_existentes("sale.order.line", ["order_id", "product_id", "product_uom_qty",
                                                                                  "qty_delivered", "display_type"])):
                if not l.get("display_type"):
                    self.tablas["pedidos_lineas"].append({
                        "pedido_id": _id(l["order_id"]), "producto_id": _id(l["product_id"]),
                        "cantidad_pedida": float(l.get("product_uom_qty") or 0), "cantidad_entregada": _num(l.get("qty_delivered"))})

    def precios(self):
        if not self.c.puede_leer("product.pricelist"):
            return
        listas = list(self.c.leer_todo("product.pricelist", [], ["name", "currency_id"]))
        self.tablas["listas_precios"] = [{"id": l["id"], "nombre": l["name"], "moneda": _nombre(l.get("currency_id"))} for l in listas]
        if not self.c.puede_leer("product.pricelist.item"):
            return
        campos = self.c._solo_existentes("product.pricelist.item", ["pricelist_id", "applied_on", "product_id", "product_tmpl_id",
                                                                    "compute_price", "fixed_price", "date_start"])
        for it in self.c.leer_todo("product.pricelist.item", [("compute_price", "=", "fixed")], campos):
            if it.get("applied_on") == "0_product_variant" and _id(it.get("product_id")):
                productos = [_id(it["product_id"])]
            elif it.get("applied_on") == "1_product":
                productos = self._plantilla.get(_id(it.get("product_tmpl_id")), [])
            else:
                continue
            for p in productos:
                self.tablas["precios"].append({"lista_precios_id": _id(it["pricelist_id"]), "producto_id": p,
                                               "precio": float(it.get("fixed_price") or 0), "desde": _fecha(it.get("date_start"))})

    def promociones(self):
        if not self.c.puede_leer("loyalty.program"):
            return
        campos = self.c._solo_existentes("loyalty.program", ["name", "program_type", "date_from", "date_to"])
        for p in self.c.leer_todo("loyalty.program", [("program_type", "in", ["promotion", "buy_x_get_y", "promo_code", "next_order_coupons"])],
                                  campos):
            if p.get("date_to") and p["date_to"] < self.desde:
                continue
            self.tablas["promociones"].append({"id": p["id"], "nombre": p["name"], "tipo": p.get("program_type"),
                                               "desde": _fecha(p.get("date_from")) or self.desde,
                                               "hasta": _fecha(p.get("date_to")) or "9999-12-31"})

    # --- finanzas --------------------------------------------------------------------

    def cxc(self):
        if not self.c.puede_leer("account.move"):
            self._faltante("Sin acceso a facturas (rol Facturación): no hay deuda de clientes ni días de cobro.")
            return
        facturas = list(self.c.leer_todo("account.move", [
            ("move_type", "in", ["out_invoice", "out_refund"]), ("state", "=", "posted"),
            "|", ("invoice_date", ">=", self.desde), ("amount_residual", "!=", 0)],
            self.c._solo_existentes("account.move", ["name", "move_type", "partner_id", "commercial_partner_id", "invoice_user_id",
                                                     "invoice_date", "invoice_date_due", "currency_id", "amount_total_signed",
                                                     "amount_residual_signed", "amount_untaxed_signed", "payment_state", "ref"])))
        cobro = self._fechas_conciliacion([f["id"] for f in facturas if f.get("payment_state") in ("paid", "in_payment")],
                                          "asset_receivable", "matched_credit_ids")
        for f in facturas:
            saldo = float(f.get("amount_residual_signed") or 0)
            cliente = _id(f.get("commercial_partner_id")) or _id(f.get("partner_id"))
            nota = f.get("move_type") == "out_refund"
            self.tablas["cxc"].append({
                "id": f["id"], "tipo": "nota_credito" if nota else "factura", "numero": f.get("name"), "cliente_id": cliente,
                "vendedor_id": _id(f.get("invoice_user_id")), "fecha_emision": _fecha(f.get("invoice_date")),
                "fecha_vencimiento": _fecha(f.get("invoice_date_due")) or _fecha(f.get("invoice_date")),
                "fecha_cobro": cobro.get(f["id"]) if not saldo else None, "moneda": _nombre(f.get("currency_id")),
                "importe": float(f.get("amount_total_signed") or 0), "saldo": saldo})
            if nota and _fecha(f.get("invoice_date")) and _fecha(f["invoice_date"]) >= self.desde:
                self.tablas["devoluciones"].append({
                    "id": f["id"], "fecha": _fecha(f["invoice_date"]), "cliente_id": cliente,
                    "importe": abs(float(f.get("amount_untaxed_signed") or f.get("amount_total_signed") or 0)),
                    "motivo": _texto(f.get("ref"))})

    def _pagos(self, tipo: str) -> list[dict]:
        campos = self.c._solo_existentes("account.payment", ["date", "partner_id", "journal_id", "payment_method_line_id",
                                                             "amount_company_currency_signed", "amount", "currency_id",
                                                             "reconciled_invoice_ids", "reconciled_bill_ids", "state"])
        dominio = [("payment_type", "=", "inbound" if tipo == "cliente" else "outbound"),
                   ("partner_type", "=", "customer" if tipo == "cliente" else "supplier"),
                   ("date", ">=", self.desde)]
        if "state" in self.c.campos("account.payment"):
            dominio.append(("state", "in", ["posted", "paid", "in_process"]))
        pagos = list(self.c.leer_todo("account.payment", dominio, campos))
        diarios = self.c.leer_ids("account.journal", {_id(p.get("journal_id")) for p in pagos}, ["type"])
        empresa = self._empresa_de(_id(p.get("partner_id")) for p in pagos)
        salida = []
        for p in pagos:
            metodo = (_nombre(p.get("payment_method_line_id")) or "").lower()
            medio = "cheque" if "cheque" in metodo or "check" in metodo else \
                "efectivo" if diarios.get(_id(p.get("journal_id")), {}).get("type") == "cash" else \
                "tarjeta" if "tarjeta" in metodo or "card" in metodo else "transferencia"
            facturas = p.get("reconciled_invoice_ids" if tipo == "cliente" else "reconciled_bill_ids") or []
            salida.append({"id": p["id"], "fecha": _fecha(p.get("date")), "persona": empresa.get(_id(p.get("partner_id"))),
                           "medio": medio, "importe": abs(float(p.get("amount_company_currency_signed") or p.get("amount") or 0)),
                           "moneda": _nombre(p.get("currency_id")), "factura": facturas[0] if facturas else None})
        return salida

    def cobranzas(self):
        if not self.c.puede_leer("account.payment"):
            return
        self.tablas["cobranzas"] = [{"id": p["id"], "fecha": p["fecha"], "cliente_id": p["persona"], "medio": p["medio"],
                                     "importe": p["importe"], "moneda": p["moneda"], "cxc_id": p["factura"]}
                                    for p in self._pagos("cliente")]

    def pagos(self):
        if not self.c.puede_leer("account.payment"):
            return
        self.tablas["pagos"] = [{"id": p["id"], "fecha": p["fecha"], "proveedor_id": p["persona"], "medio": p["medio"],
                                 "importe": p["importe"], "moneda": p["moneda"], "cxp_id": p["factura"]} for p in self._pagos("proveedor")]

    def cxp(self):
        if not self.c.puede_leer("account.move"):
            return
        facturas = list(self.c.leer_todo("account.move", [
            ("move_type", "in", ["in_invoice", "in_refund"]), ("state", "=", "posted"),
            "|", ("invoice_date", ">=", self.desde), ("amount_residual", "!=", 0)],
            self.c._solo_existentes("account.move", ["name", "ref", "move_type", "partner_id", "commercial_partner_id", "invoice_date",
                                                     "invoice_date_due", "currency_id", "amount_total_signed",
                                                     "amount_residual_signed", "payment_state"])))
        pago = self._fechas_conciliacion([f["id"] for f in facturas if f.get("payment_state") in ("paid", "in_payment")],
                                         "liability_payable", "matched_debit_ids")
        for f in facturas:
            saldo = abs(float(f.get("amount_residual_signed") or 0))
            self.tablas["cxp"].append({
                "id": f["id"], "tipo": "nota_credito" if f.get("move_type") == "in_refund" else "factura",
                "numero": f.get("ref") or f.get("name"), "proveedor_id": _id(f.get("commercial_partner_id")) or _id(f.get("partner_id")),
                "fecha_emision": _fecha(f.get("invoice_date")),
                "fecha_vencimiento": _fecha(f.get("invoice_date_due")) or _fecha(f.get("invoice_date")),
                "fecha_pago": pago.get(f["id"]) if not saldo else None, "moneda": _nombre(f.get("currency_id")),
                # En Odoo las facturas de proveedor tienen signo negativo: se guardan en positivo (lo que se debe).
                "importe": -float(f.get("amount_total_signed") or 0), "saldo": saldo if f.get("move_type") == "in_invoice" else -saldo})

    def bancos(self):
        if not self.c.puede_leer("account.journal"):
            return
        diarios = list(self.c.leer_todo("account.journal", [("type", "in", ["bank", "cash"])],
                                        ["name", "type", "currency_id", "default_account_id"]))
        saldos = {}
        cuentas = [_id(d.get("default_account_id")) for d in diarios if _id(d.get("default_account_id"))]
        if cuentas and self.c.puede_leer("account.move.line"):
            for g in self.c.agrupar("account.move.line", [("account_id", "in", cuentas), ("parent_state", "=", "posted")],
                                    ["balance:sum"], ["account_id"]):
                saldos[_id(g.get("account_id"))] = float(g.get("balance") or 0)
        self.tablas["cuentas_bancarias"] = [{
            "id": d["id"], "nombre": d["name"], "tipo": "caja" if d["type"] == "cash" else "banco",
            "moneda": _nombre(d.get("currency_id")), "saldo": saldos.get(_id(d.get("default_account_id")), 0.0),
            "fecha_saldo": self.hoy.isoformat()} for d in diarios]
        if self.c.puede_leer("account.bank.statement.line"):
            campos = self.c._solo_existentes("account.bank.statement.line", ["journal_id", "date", "payment_ref", "amount", "is_reconciled"])
            for m in self.c.leer_todo("account.bank.statement.line", [("date", ">=", self.desde)], campos):
                self.tablas["movimientos_bancarios"].append({
                    "id": m["id"], "cuenta_id": _id(m.get("journal_id")), "fecha": _fecha(m.get("date")),
                    "concepto": _texto(m.get("payment_ref")), "importe": float(m.get("amount") or 0),
                    "conciliado": 1 if m.get("is_reconciled") else 0})

    def gastos(self):
        if not self.c.puede_leer("account.move.line") or "account_type" not in self.c.campos("account.move.line"):
            return
        grupos = self.c.agrupar("account.move.line", [("account_id.account_type", "=", "expense"), ("parent_state", "=", "posted"),
                                                      ("date", ">=", self.desde)], ["balance:sum"], ["account_id", "date:month"],
                                {"tz": str(self.zona)})
        for i, g in enumerate(grupos, start=1):
            rango = (g.get("__range") or {}).get("date:month") or {}
            cuenta = _nombre(g.get("account_id")) or ""
            self.tablas["gastos"].append({"id": i, "fecha": _fecha(rango.get("from")) or self.desde, "cuenta": cuenta,
                                          "categoria": categoria_gasto(cuenta), "importe": float(g.get("balance") or 0)})

    def impuestos(self):
        if not self.c.puede_leer("account.move.line") or "tax_line_id" not in self.c.campos("account.move.line"):
            return
        grupos = self.c.agrupar("account.move.line", [("tax_line_id", "!=", False), ("parent_state", "=", "posted"),
                                                      ("date", ">=", self.desde)], ["balance:sum"], ["tax_line_id", "date:month"],
                                {"tz": str(self.zona)})
        for i, g in enumerate(grupos, start=1):
            rango = (g.get("__range") or {}).get("date:month") or {}
            desde = _fecha(rango.get("from"))
            # Saldo acreedor (negativo en Odoo) = impuesto a pagar; deudor = crédito fiscal.
            self.tablas["impuestos"].append({"id": i, "impuesto": _nombre(g.get("tax_line_id")), "periodo": desde[:7] if desde else None,
                                             "importe": -float(g.get("balance") or 0)})

    def tipos_cambio(self):
        if not self.c.puede_leer("res.currency.rate"):
            return
        campos = self.c._solo_existentes("res.currency.rate", ["name", "currency_id", "rate", "inverse_company_rate"])
        for r in self.c.leer_todo("res.currency.rate", [("name", ">=", self.desde)], campos):
            cotizacion = r.get("inverse_company_rate") or (1 / r["rate"] if r.get("rate") else None)
            if cotizacion:
                self.tablas["tipos_cambio"].append({"fecha": _fecha(r.get("name")), "moneda": _nombre(r.get("currency_id")),
                                                    "cotizacion": float(cotizacion)})

    def prestamos(self):
        if not self.c.puede_leer("account.loan"):
            return
        campos = self.c._solo_existentes("account.loan", ["name", "amount_borrowed", "date", "duration", "outstanding_balance",
                                                          "currency_id"])
        for p in self.c.leer_todo("account.loan", [], campos):
            self.tablas["prestamos"].append({"id": p["id"], "entidad": p.get("name"), "capital": _num(p.get("amount_borrowed")),
                                             "fecha_inicio": _fecha(p.get("date")), "cuotas": p.get("duration") or None,
                                             "saldo": _num(p.get("outstanding_balance")) or 0, "moneda": _nombre(p.get("currency_id"))})

    def presupuesto(self):
        if not self.c.puede_leer("crossovered.budget.lines"):
            return
        campos = self.c._solo_existentes("crossovered.budget.lines", ["general_budget_id", "date_from", "planned_amount"])
        for l in self.c.leer_todo("crossovered.budget.lines", [("date_to", ">=", self.desde)], campos):
            self.tablas["presupuesto"].append({"mes": (_fecha(l.get("date_from")) or "")[:7], "concepto": _nombre(l.get("general_budget_id")),
                                               "importe": float(l.get("planned_amount") or 0)})

    def cheques(self):
        if not self.c.puede_leer("l10n_latam.check"):
            return  # solo con la localización argentina/uruguaya de cheques
        campos = self.c._solo_existentes("l10n_latam.check", ["name", "bank_id", "partner_id", "issue_date", "payment_date",
                                                              "amount", "currency_id", "payment_type", "current_journal_id"])
        for ch in self.c.leer_todo("l10n_latam.check", [("issue_date", ">=", self.desde)], campos):
            recibido = ch.get("payment_type") != "outbound"
            self.tablas["cheques"].append({
                "id": ch["id"], "tipo": "recibido" if recibido else "emitido", "numero": ch.get("name"), "banco": _nombre(ch.get("bank_id")),
                "cliente_id": _id(ch.get("partner_id")) if recibido else None, "proveedor_id": None if recibido else _id(ch.get("partner_id")),
                "fecha_emision": _fecha(ch.get("issue_date")), "fecha_cobro": _fecha(ch.get("payment_date")),
                "importe": float(ch.get("amount") or 0), "moneda": _nombre(ch.get("currency_id")),
                "estado": "cartera" if _id(ch.get("current_journal_id")) else "entregado"})

    # --- personas --------------------------------------------------------------------

    def clientes(self):
        usados = {v["cliente_id"] for t in ("ventas", "cxc", "pedidos", "cobranzas") for v in self.tablas[t]} - {None}
        dominio = ["|", ("customer_rank", ">", 0), ("id", "in", sorted(usados))]
        campos = self.c._solo_existentes("res.partner", [
            "id", "name", "is_company", "category_id", "street", "city", "state_id", "user_id", "team_id", "property_product_pricelist",
            "property_payment_term_id", "credit_limit", "create_date", "parent_id", "partner_latitude", "partner_longitude", "active"])
        filas = [f for f in self.c.leer_todo("res.partner", dominio, campos, {"active_test": False})
                 if not f.get("parent_id") or f["id"] in usados]
        plazos = self._dias_de_plazo([_id(f.get("property_payment_term_id")) for f in filas])
        categorias = self.c.leer_ids("res.partner.category", [c for f in filas for c in (f.get("category_id") or [])[:1]], ["name"]) \
            if any(f.get("category_id") for f in filas) else {}
        self.tablas["clientes"] = [{
            "id": f["id"], "razon_social": f["name"],
            "tipo": categorias.get((f.get("category_id") or [None])[0], {}).get("name") or ("empresa" if f.get("is_company") else "persona"),
            "canal": _nombre(f.get("team_id")), "zona": _nombre(f.get("state_id")) or _texto(f.get("city")),
            "direccion": _texto(f.get("street")), "ciudad": _texto(f.get("city")),
            "latitud": _num(f.get("partner_latitude")) or None, "longitud": _num(f.get("partner_longitude")) or None,
            "vendedor_id": _id(f.get("user_id")), "lista_precios_id": _id(f.get("property_product_pricelist")),
            "condicion_pago_dias": plazos.get(_id(f.get("property_payment_term_id")), 0),
            "limite_credito": float(f["credit_limit"]) if f.get("credit_limit") else None,
            "fecha_alta": self._local(f.get("create_date"))[0], "estado": "activo" if f.get("active", True) else "archivado",
        } for f in filas]
        sin_vendedor = sum(1 for c in self.tablas["clientes"] if c["vendedor_id"] is None)
        if sin_vendedor:
            self._faltante(f"{sin_vendedor} clientes no tienen «Vendedor» en su ficha de Odoo: ningún vendedor los va a ver en su cartera.")

    def vendedores(self):
        ids = {c["vendedor_id"] for c in self.tablas["clientes"]} | {v["vendedor_id"] for v in self.tablas["ventas"]}
        ids -= {None}
        campos = self.c._solo_existentes("res.users", ["name", "active", "sale_team_id"])
        filas = self.c.leer_ids("res.users", ids, campos) if ids else {}
        self.tablas["vendedores"] = [{"id": i, "nombre": f["name"], "equipo": _nombre(f.get("sale_team_id")),
                                      "activo": 1 if f.get("active", True) else 0} for i, f in filas.items()]

    def proveedores(self):
        usados = ({c["proveedor_id"] for c in self.tablas["compras"]} | {c["proveedor_id"] for c in self.tablas["cxp"]}
                  | {p["proveedor_id"] for p in self.tablas["pagos"]} | set(self._proveedores_producto)) - {None}
        dominio = ["|", ("supplier_rank", ">", 0), ("id", "in", sorted(usados))]
        campos = self.c._solo_existentes("res.partner", ["id", "name", "property_supplier_payment_term_id", "parent_id"])
        filas = [f for f in self.c.leer_todo("res.partner", dominio, campos, {"active_test": False}) if not f.get("parent_id") or f["id"] in usados]
        plazos = self._dias_de_plazo([_id(f.get("property_supplier_payment_term_id")) for f in filas])
        self.tablas["proveedores"] = [{
            "id": f["id"], "nombre": f["name"], "plazo_pago_dias": plazos.get(_id(f.get("property_supplier_payment_term_id"))),
            "plazo_entrega_dias": min((d for d in self._proveedores_producto.get(f["id"], []) if d is not None), default=None),
        } for f in filas]


def control_ventas(cliente: ClienteOdoo, tablas: dict[str, list[dict]], meses: int = 12, zona: str | None = None,
                   hoy: date | None = None) -> dict:
    """Compara lo sincronizado con el reporte "Análisis de ventas" de Odoo (sale.report), mes por mes y por equipo.

    Usa el mismo filtro que "Órdenes de venta" en Odoo (sin borradores, presupuestos enviados ni anuladas) y la
    misma zona horaria. Devuelve una fila por mes y equipo con los importes de los dos lados y si coinciden.
    """
    if not cliente.puede_leer("sale.report"):
        return {"disponible": False, "motivo": "El usuario no puede leer el reporte de ventas de Odoo."}
    zona = zona or cliente.zona_horaria()
    desde = ((hoy or date.today()) - timedelta(days=round(meses * 30.44))).replace(day=1)
    desde = (desde.replace(day=28) + timedelta(days=4)).replace(day=1)  # primer mes completo
    grupos = cliente.agrupar("sale.report", [("state", "not in", ["draft", "cancel", "sent"]), ("date", ">=", desde.isoformat())],
                             ["price_subtotal:sum", "price_total:sum", "product_uom_qty:sum", "nbr:sum"], ["date:month", "team_id"],
                             {"tz": zona})
    odoo = {}
    for g in grupos:
        rango = (g.get("__range") or {}).get("date:month") or {}
        mes = (_fecha(rango.get("from")) or "")[:7]
        odoo[(mes, _nombre(g.get("team_id")) or "Sin equipo")] = {
            "sin_impuestos": float(g.get("price_subtotal") or 0), "con_impuestos": float(g.get("price_total") or 0),
            "cantidad": float(g.get("product_uom_qty") or 0), "lineas": int(g.get("nbr") or 0)}
    ventas = {v["id"]: v for v in tablas.get("ventas", []) if not v.get("anulada")}
    nuestro = defaultdict(lambda: {"sin_impuestos": 0.0, "con_impuestos": 0.0, "cantidad": 0.0, "lineas": 0})
    for l in tablas.get("ventas_lineas", []):
        v = ventas.get(l["venta_id"])
        if not v or not v.get("fecha") or v["fecha"] < desde.isoformat():
            continue
        fila = nuestro[(v["fecha"][:7], v.get("canal") or "Sin equipo")]
        neto = (l.get("cantidad") or 0) * (l.get("precio_unitario") or 0)
        fila["sin_impuestos"] += neto
        fila["con_impuestos"] += neto + (l.get("impuestos") or 0)
        fila["cantidad"] += l.get("cantidad") or 0
        fila["lineas"] += 1
    filas = []
    for clave in sorted(set(odoo) | set(nuestro), reverse=True):
        o, n = odoo.get(clave, {}), nuestro.get(clave, {})
        dif = round(n.get("sin_impuestos", 0) - o.get("sin_impuestos", 0), 2)
        tolerancia = max(1.0, abs(o.get("sin_impuestos", 0)) * 0.001)
        filas.append({"mes": clave[0], "equipo": clave[1],
                      "odoo_sin_impuestos": round(o.get("sin_impuestos", 0), 2), "plataforma_sin_impuestos": round(n.get("sin_impuestos", 0), 2),
                      "odoo_con_impuestos": round(o.get("con_impuestos", 0), 2), "plataforma_con_impuestos": round(n.get("con_impuestos", 0), 2),
                      "odoo_cantidad": round(o.get("cantidad", 0), 2), "plataforma_cantidad": round(n.get("cantidad", 0), 2),
                      "odoo_lineas": o.get("lineas", 0), "plataforma_lineas": n.get("lineas", 0),
                      "diferencia": dif, "coincide": abs(dif) <= tolerancia})
    return {"disponible": True, "zona": zona, "filas": filas, "coinciden": all(f["coincide"] for f in filas)}
