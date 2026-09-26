"""Lo que las reglas necesitan del ERP, leído una sola vez por ejecución.

Todo pasa por el conector de solo lectura. Las reglas corren como proceso del
sistema (ven todo el negocio); lo que ve cada persona se filtra después, al
listar sus tareas. Si una tabla no existe o está vacía, queda vacía acá y la
regla dice qué dato falta en lugar de inventarlo.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, timedelta
from functools import cached_property

from ..erp import conector

SIN_LIMITE = 5_000_000
DIAS_HISTORIA = 130


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _fecha(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


class Datos:
    def __init__(self, hoy: date | None = None, url: str | None = None):
        self.url = url
        self.errores: list[str] = []
        ultima = self._uno("SELECT MAX(v.fecha) FROM ventas v")
        ultima = _fecha(ultima)
        real = hoy or date.today()
        # Las reglas miran "hasta ayer". Si la base llega hasta antes, se toma su último día.
        self.hoy = real if not ultima or hoy or ultima >= real - timedelta(days=1) else ultima + timedelta(days=1)
        self.datos_hasta = ultima
        self.desde = self.hoy - timedelta(days=DIAS_HISTORIA)

    # --- acceso -------------------------------------------------------------------------
    def q(self, sql: str) -> list[list]:
        try:
            return conector.consultar(sql, max_filas=SIN_LIMITE, url=self.url)["filas"]
        except Exception as e:  # tabla o columna que esta base no tiene
            self.errores.append(f"{type(e).__name__}: {str(e).splitlines()[0][:160]}")
            return []

    def _uno(self, sql: str):
        filas = self.q(sql)
        return filas[0][0] if filas else None

    def dias(self, n: int, hasta: date | None = None) -> list[date]:
        """Los n días anteriores a `hasta` (por defecto hoy), del más viejo al más nuevo."""
        hasta = hasta or self.hoy
        return [hasta - timedelta(days=i) for i in range(n, 0, -1)]

    # --- maestros -----------------------------------------------------------------------
    @cached_property
    def productos(self) -> dict[int, dict]:
        cols = ["id", "codigo", "descripcion", "marca", "categoria", "proveedor_id", "unidades_bulto", "perecedero",
                "vida_util_dias", "estado", "fecha_alta", "costo", "precio"]
        return {int(f[0]): dict(zip(cols, f)) for f in self.q(f"SELECT {', '.join(cols)} FROM productos") if f[0] is not None}

    @cached_property
    def sucursales(self) -> dict[int, str]:
        return {int(i): n or f"Sucursal {i}" for i, n in self.q("SELECT id, nombre FROM sucursales") if i is not None}

    @cached_property
    def proveedores(self) -> dict[int, dict]:
        cols = ["id", "nombre", "plazo_entrega_dias", "pedido_minimo", "dias_pedido", "acepta_devolucion_vencidos"]
        return {int(f[0]): dict(zip(cols, f)) for f in self.q(f"SELECT {', '.join(cols)} FROM proveedores") if f[0] is not None}

    def nombre_producto(self, pid) -> str:
        p = self.productos.get(pid) or {}
        return p.get("descripcion") or p.get("codigo") or f"Producto {pid}"

    def nombre_sucursal(self, sid) -> str:
        return self.sucursales.get(sid) or ("Sin sucursal" if sid is None else f"Sucursal {sid}")

    def nombre_proveedor(self, pid) -> str:
        return (self.proveedores.get(pid) or {}).get("nombre") or f"Proveedor {pid}"

    def costo(self, pid) -> float:
        """Costo de reposición: el último del historial; si no hay, el del producto."""
        hist = self.costos.get(pid)
        return hist[-1][1] if hist else _f((self.productos.get(pid) or {}).get("costo"))

    # --- ventas -------------------------------------------------------------------------
    @cached_property
    def _ventas(self):
        """Unidades, importe y costo por producto × sucursal × día, y tickets por sucursal × día."""
        filas = self.q(
            "SELECT l.producto_id, v.sucursal_id, v.fecha, SUM(l.cantidad), SUM(l.cantidad * l.precio_unitario), "
            "SUM(l.cantidad * COALESCE(l.costo_unitario, 0)), SUM(CASE WHEN l.costo_unitario IS NULL THEN 0 ELSE l.cantidad END) "
            "FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id "
            f"WHERE COALESCE(v.anulada, 0) = 0 AND v.fecha >= '{self.desde.isoformat()}' "
            f"AND v.fecha < '{self.hoy.isoformat()}' GROUP BY l.producto_id, v.sucursal_id, v.fecha")
        unidades = defaultdict(dict)
        importe = defaultdict(float)
        cant_imp = defaultdict(float)
        costo = defaultdict(float)
        cant_costo = defaultdict(float)
        ultima = {}
        for prod, suc, fecha, u, imp, cos, uc in filas:
            d = _fecha(fecha)
            if d is None or prod is None:
                continue
            clave = (int(prod), suc)
            unidades[clave][d] = unidades[clave].get(d, 0) + _f(u)
            if _f(u) > 0:
                ultima[clave] = max(ultima.get(clave, d), d)
            if d >= self.desde:
                importe[clave] += _f(imp)
                cant_imp[clave] += _f(u)
                costo[clave] += _f(cos)
                cant_costo[clave] += _f(uc)
        tickets = defaultdict(dict)
        for suc, fecha, n in self.q(
                "SELECT v.sucursal_id, v.fecha, COUNT(*) FROM ventas v "
                f"WHERE COALESCE(v.anulada, 0) = 0 AND v.fecha >= '{self.desde.isoformat()}' AND v.fecha < '{self.hoy.isoformat()}' "
                "GROUP BY v.sucursal_id, v.fecha"):
            d = _fecha(fecha)
            if d:
                tickets[suc][d] = tickets[suc].get(d, 0) + int(n or 0)
        por_prod = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])  # importe, unidades, costo, unidades con costo
        for (pid, _s), v in importe.items():
            t = por_prod[pid]
            t[0] += v
            t[1] += cant_imp[(pid, _s)]
            t[2] += costo[(pid, _s)]
            t[3] += cant_costo[(pid, _s)]
        self._por_suc = defaultdict(list)
        for clave in unidades:
            self._por_suc[clave[0]].append(clave)
        return unidades, importe, cant_imp, costo, cant_costo, ultima, tickets, por_prod

    @property
    def unidades(self) -> dict[tuple, dict[date, float]]:
        return self._ventas[0]

    @property
    def tickets(self) -> dict:
        return self._ventas[6]

    def ultima_venta(self, pid, suc) -> date | None:
        return self._ventas[5].get((pid, suc))

    def precio_medio(self, pid, suc=None) -> float:
        """Precio neto medio de venta (130 días); si no hay ventas, el precio de lista."""
        if suc is not None:
            imp, cant = self._ventas[1].get((pid, suc), 0.0), self._ventas[2].get((pid, suc), 0.0)
        else:
            imp, cant = self._ventas[7][pid][0], self._ventas[7][pid][1]
        return imp / cant if cant else self.precio_actual(pid)

    def costo_medio_vendido(self, pid) -> float:
        t = self._ventas[7][pid]
        return t[2] / t[3] if t[3] else self.costo(pid)

    def puntos(self) -> set:
        """Sucursales con ventas (puntos de venta)."""
        return {s for s, dias in self.tickets.items() if dias}

    def dias_abiertos(self, suc, dias: list[date]) -> list[date]:
        t = self.tickets.get(suc, {})
        return [d for d in dias if t.get(d, 0) > 0]

    def serie(self, pid, suc=None, dias: list[date] = ()) -> list[float]:
        """Unidades por día (suc=None suma todas las sucursales)."""
        if suc is not None:
            u = self.unidades.get((pid, suc), {})
            return [u.get(d, 0.0) for d in dias]
        claves = self._claves(pid)
        return [sum(self.unidades[k].get(d, 0.0) for k in claves) for d in dias]

    def _claves(self, pid) -> list[tuple]:
        self._ventas  # noqa: B018  (arma el índice por producto)
        return self._por_suc.get(pid, [])

    def vdp(self, pid, suc=None, n: int = 28, hasta: date | None = None) -> float:
        """Venta diaria promedio en los últimos n días corridos."""
        return sum(self.serie(pid, suc, self.dias(n, hasta))) / n

    def sigma(self, pid, n: int = 56) -> float:
        s = self.serie(pid, None, self.dias(n))
        return statistics.pstdev(s) if len(s) > 1 else 0.0

    @cached_property
    def abc(self) -> dict[int, str]:
        """Clase ABC por venta de los últimos 90 días: A hasta el 80 % acumulado, B hasta el 95 %, C el resto."""
        valor = defaultdict(float)
        desde = self.hoy - timedelta(days=90)
        for (pid, _suc), dias in self.unidades.items():
            valor[pid] += sum(u for d, u in dias.items() if d >= desde) * self.precio_medio(pid)
        total = sum(valor.values())
        clase, acum = {}, 0.0
        for pid, v in sorted(valor.items(), key=lambda x: -x[1]):
            acum += v
            clase[pid] = "A" if total and acum - v < 0.8 * total else ("B" if total and acum - v < 0.95 * total else "C")
        for pid in self.productos:
            clase.setdefault(pid, "C")
        return clase

    # --- stock --------------------------------------------------------------------------
    @cached_property
    def stock(self) -> list[dict]:
        cols = ["producto_id", "sucursal_id", "ubicacion", "lote", "fecha_vencimiento", "cantidad", "comprometido", "en_transito"]
        return [dict(zip(cols, f)) for f in self.q(f"SELECT {', '.join(cols)} FROM stock") if f[0] is not None]

    @cached_property
    def _stock_por_prod(self) -> dict[int, list[dict]]:
        res = defaultdict(list)
        for s in self.stock:
            res[s["producto_id"]].append(s)
        return res

    def stock_de(self, pid, suc=None) -> tuple[float, float]:
        """(disponible, en tránsito) del producto; suc=None suma todas las sucursales."""
        disp = trans = 0.0
        for s in self._stock_por_prod.get(pid, []):
            if suc is None or s["sucursal_id"] == suc:
                disp += _f(s["cantidad"]) - _f(s["comprometido"])
                trans += _f(s["en_transito"])
        return disp, trans

    def fisico(self, pid, suc) -> float:
        return sum(_f(s["cantidad"]) for s in self._stock_por_prod.get(pid, []) if s["sucursal_id"] == suc)

    @cached_property
    def puntos_stock(self) -> set[tuple]:
        return {(s["producto_id"], s["sucursal_id"]) for s in self.stock}

    # --- compras y costos ---------------------------------------------------------------
    @cached_property
    def costos(self) -> dict[int, list[tuple[date, float]]]:
        """Historial de costos (listas del proveedor) por producto, del más viejo al más nuevo, hasta hoy."""
        hist = defaultdict(list)
        for pid, fecha, costo in self.q("SELECT producto_id, fecha, costo FROM costos_historial"):
            d = _fecha(fecha)
            if pid is not None and d and d <= self.hoy and costo is not None:
                hist[int(pid)].append((d, _f(costo)))
        for v in hist.values():
            v.sort()
        return hist

    @cached_property
    def pendiente_compra(self) -> dict[int, float]:
        """Unidades pedidas a proveedores que todavía no llegaron."""
        pend = defaultdict(float)
        for pid, pedida, recibida in self.q(
                "SELECT l.producto_id, l.cantidad_pedida, l.cantidad_recibida FROM compras c JOIN compras_lineas l ON l.compra_id = c.id "
                "WHERE c.fecha_recepcion IS NULL AND COALESCE(c.estado, '') NOT IN ('recibida', 'cancelada', 'anulada')"):
            if pid is not None:
                pend[int(pid)] += max(0.0, _f(pedida) - _f(recibida))
        return pend

    @cached_property
    def ultima_compra(self) -> dict[int, tuple[date, float]]:
        """Fecha y precio facturado de la última compra de cada producto."""
        res = {}
        for pid, fecha, precio in self.q(
                "SELECT l.producto_id, c.fecha, COALESCE(l.precio_facturado, l.precio_pactado) FROM compras c "
                "JOIN compras_lineas l ON l.compra_id = c.id"):
            d = _fecha(fecha)
            if pid is None or d is None or precio is None:
                continue
            if int(pid) not in res or d > res[int(pid)][0]:
                res[int(pid)] = (d, _f(precio))
        return res

    @cached_property
    def lead_time_real(self) -> dict[int, float]:
        """Mediana de días entre la orden y la recepción, por proveedor."""
        dias = defaultdict(list)
        for prov, f1, f2 in self.q("SELECT proveedor_id, fecha, fecha_recepcion FROM compras WHERE fecha_recepcion IS NOT NULL"):
            a, b = _fecha(f1), _fecha(f2)
            if prov is not None and a and b and b >= a:
                dias[int(prov)].append((b - a).days)
        return {p: statistics.median(v) for p, v in dias.items() if v}

    def lead_time(self, prov) -> float:
        estandar = (self.proveedores.get(prov) or {}).get("plazo_entrega_dias")
        if estandar:
            return _f(estandar)
        return self.lead_time_real.get(prov, 7.0)

    # --- precios y promociones ----------------------------------------------------------
    @cached_property
    def precios(self) -> dict[int, dict]:
        """Por producto: {lista: [(desde, precio), ...]} ordenado por fecha."""
        res = defaultdict(lambda: defaultdict(list))
        nombres = {i: n for i, n in self.q("SELECT id, nombre FROM listas_precios")}
        for lista, pid, precio, desde in self.q("SELECT lista_precios_id, producto_id, precio, desde FROM precios"):
            if pid is None or precio is None:
                continue
            d = _fecha(desde) or date(1900, 1, 1)
            if d <= self.hoy:
                res[int(pid)][nombres.get(lista) or f"Lista {lista}"].append((d, _f(precio)))
        for listas in res.values():
            for v in listas.values():
                v.sort()
        return res

    def precio_actual(self, pid) -> float:
        p = _f((self.productos.get(pid) or {}).get("precio"))
        if p:
            return p
        listas = self.precios.get(pid) or {}
        vigentes = [v[-1][1] for v in listas.values() if v]
        return min(vigentes) if vigentes else 0.0

    @cached_property
    def promociones(self) -> list[dict]:
        cols = ["id", "nombre", "producto_id", "desde", "hasta", "tipo", "precio_promocional", "descuento_pct", "financia_proveedor"]
        res = []
        for f in self.q(f"SELECT {', '.join(cols)} FROM promociones"):
            p = dict(zip(cols, f))
            p["desde"], p["hasta"] = _fecha(p["desde"]), _fecha(p["hasta"])
            if p["desde"] and p["hasta"]:
                res.append(p)
        return res

    def en_promocion(self, pid, d: date | None = None) -> bool:
        d = d or self.hoy
        return any(p["producto_id"] == pid and p["desde"] <= d <= p["hasta"] for p in self.promociones)

    # --- conteos ------------------------------------------------------------------------
    @cached_property
    def conteos(self) -> list[dict]:
        cols = ["fecha", "producto_id", "sucursal_id", "cantidad_contada", "cantidad_sistema"]
        return [dict(zip(cols, f)) for f in self.q(f"SELECT {', '.join(cols)} FROM conteos")]


def cv_semanal(serie: list[float]) -> float:
    """Coeficiente de variación de la demanda semanal (serie diaria agrupada de a 7)."""
    semanas = [sum(serie[i:i + 7]) for i in range(0, len(serie) - len(serie) % 7, 7)]
    if len(semanas) < 2:
        return 0.0
    media = statistics.mean(semanas)
    return statistics.pstdev(semanas) / media if media else math.inf
