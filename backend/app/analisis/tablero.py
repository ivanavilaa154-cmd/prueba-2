"""Tablero: indicadores clave de Ventas, Inventario y Finanzas.

Todas las cuentas se hacen acá, en código (regla 6), a partir de consultas que
pasan por el conector con el usuario: cada rol ve solo sus tablas y el vendedor
solo su cartera (regla 2). Si una sección no tiene datos o el rol no tiene
acceso, se dice; nunca se completa con supuestos (regla 3).

Las consultas usan SQL estándar (sin funciones de fecha propias de un motor) y
las fechas se comparan como texto AAAA-MM-DD; los cortes por mes se hacen en
Python. Los indicadores de los prompts que necesitan datos que el diccionario no
tiene (caja, cuentas por pagar, lotes, merma...) se listan como no disponibles.
"""
from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from ..erp import conector
from ..erp.conector import ConsultaNoPermitida
from ..permisos import AccesoDenegado, Usuario
from . import finanzas as finanzas_analisis
from . import indicadores

SIN_LIMITE = 1_000_000
TRAMOS = [("Al día", None, 0), ("1 a 15 días", 1, 15), ("16 a 30 días", 16, 30),
          ("31 a 60 días", 31, 60), ("61 a 90 días", 61, 90), ("Más de 90 días", 91, None)]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def nombre_mes(mes: str) -> str:
    """'2026-09' -> 'septiembre 2026'."""
    return f"{MESES[int(mes[5:7]) - 1]} {mes[:4]}"


@dataclass
class Periodo:
    """Un mes calendario. Si es el mes en curso, va hasta hoy y se compara con los mismos días del mes anterior."""
    mes: str
    desde: date
    hasta: date
    ant_desde: date
    ant_hasta: date
    en_curso: bool
    hoy: date

    @classmethod
    def crear(cls, mes: str, hoy: date) -> "Periodo":
        anio, m = int(mes[:4]), int(mes[5:7])
        desde = date(anio, m, 1)
        fin = date(anio, m, calendar.monthrange(anio, m)[1])
        en_curso = desde <= hoy <= fin
        hasta = hoy if en_curso else fin
        ant_hasta_mes = desde - timedelta(days=1)
        ant_desde = ant_hasta_mes.replace(day=1)
        ant_hasta = min(ant_desde + timedelta(days=(hasta - desde).days), ant_hasta_mes) if en_curso else ant_hasta_mes
        return cls(mes, desde, hasta, ant_desde, ant_hasta, en_curso, hoy)

    @property
    def dias(self) -> int:
        return (self.hasta - self.desde).days + 1

    @property
    def nombre(self) -> str:
        return nombre_mes(self.mes)

    @property
    def nombre_anterior(self) -> str:
        return nombre_mes(self.ant_desde.isoformat()[:7])

    def describir(self) -> str:
        if self.en_curso:
            return (f"{self.nombre.capitalize()} (en curso, del 1 al {self.hasta.day}), comparado con los mismos días de "
                    f"{self.nombre_anterior}")
        return f"{self.nombre.capitalize()}, comparado con {self.nombre_anterior}"


def _mas_meses(mes: str, n: int) -> str:
    anio, m = int(mes[:4]), int(mes[5:7]) - 1 + n
    return f"{anio + m // 12}-{m % 12 + 1:02d}"


class _SinDatos(Exception):
    pass


def _q(usuario: Usuario, sql: str) -> list[list]:
    return conector.consultar(sql, max_filas=SIN_LIMITE, usuario=usuario)["filas"]


def _dias(a: str, b: str) -> int:
    return (date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days


def _variacion(actual: float, anterior: float) -> float | None:
    return round((actual - anterior) / anterior, 4) if anterior else None


def _kpi(nombre, valor, formato, variacion=None, nota=None, estado=None) -> dict:
    return {"nombre": nombre, "valor": valor, "formato": formato, "variacion": variacion, "nota": nota, "estado": estado}


def _seccion(fn, *args) -> dict:
    try:
        return fn(*args)
    except (AccesoDenegado, ConsultaNoPermitida):
        return {"sin_acceso": True, "mensaje": "Tu perfil no tiene acceso a estos datos."}
    except _SinDatos as e:
        return {"sin_datos": True, "mensaje": str(e)}
    except Exception as e:  # nunca un error 500: el pilar avisa y el resto del tablero se muestra
        return {"sin_datos": True, "mensaje": f"No se pudo calcular esta sección ({type(e).__name__}: {str(e).splitlines()[0][:160]})."}


def _nombres(usuario: Usuario, sql: str, prefijo: str) -> dict:
    """Nombres para mostrar; si el rol no ve la tabla, se usa "<prefijo> <id>"."""
    try:
        return {f[0]: f[1] for f in _q(usuario, sql)}
    except Exception:  # sin acceso o sin esa tabla: se muestran los identificadores
        return {}


def meses_disponibles(usuario: Usuario, hoy: date) -> list[dict]:
    """Meses para elegir (hasta 24 hacia atrás), el más reciente primero, marcando los que tienen ventas."""
    actual = hoy.isoformat()[:7]
    try:
        filas = _q(usuario, "SELECT MIN(fecha), MAX(fecha) FROM ventas WHERE anulada = 0")
        primero, ultimo = filas[0] if filas else (None, None)
    except Exception:
        primero = ultimo = None
    con_ventas = set()
    try:
        desde = _mas_meses(actual, -23) + "-01"
        for (fecha,) in _q(usuario, f"SELECT DISTINCT fecha FROM ventas WHERE anulada = 0 AND fecha >= '{desde}'"):
            con_ventas.add(fecha[:7])
    except Exception:
        pass
    fin = max(actual, ultimo[:7]) if ultimo else actual
    inicio = max(primero[:7] if primero else fin, _mas_meses(fin, -23))
    meses, m = [], fin
    while m >= inicio:
        meses.append({"valor": m, "nombre": nombre_mes(m), "en_curso": m == actual, "con_ventas": m in con_ventas})
        m = _mas_meses(m, -1)
    return meses


# --- Ventas ---------------------------------------------------------------------

def ventas(usuario: Usuario, p: Periodo) -> dict:
    ref = p.hasta
    d0, d1, d365 = p.desde.isoformat(), p.ant_desde.isoformat(), min((ref - timedelta(days=364)), p.ant_desde).isoformat()
    hasta = ref.isoformat()
    por_dia = _q(usuario, f"""
        SELECT v.fecha, COUNT(DISTINCT v.id), SUM(l.cantidad * l.precio_unitario), SUM(l.cantidad * l.costo_unitario), COUNT(*)
        FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
        WHERE v.anulada = 0 AND v.fecha >= '{d365}' AND v.fecha <= '{hasta}' GROUP BY v.fecha""")
    if not por_dia:
        raise _SinDatos("No hay ventas en los últimos 12 meses.")

    def sumar(desde, hasta_):
        filas = [f for f in por_dia if desde <= f[0][:10] <= hasta_]
        return (sum(f[1] for f in filas), sum(f[2] or 0 for f in filas), sum(f[3] or 0 for f in filas), sum(f[4] for f in filas))

    ped, venta, costo, lineas = sumar(d0, hasta)
    ped_a, venta_a, costo_a, _ = sumar(d1, p.ant_hasta.isoformat())
    margen, margen_a = venta - costo, venta_a - costo_a

    # Serie de 12 meses: desde el primer mes completo; el mes actual se marca "en curso".
    inicio = ref.replace(day=1)
    for _ in range(11):
        inicio = (inicio - timedelta(days=1)).replace(day=1)
    meses = defaultdict(lambda: [0.0, 0.0])
    for f in por_dia:
        if f[0][:10] >= inicio.isoformat():
            meses[f[0][:7]][0] += f[2] or 0
            meses[f[0][:7]][1] += f[3] or 0
    serie = [{"mes": m, "venta": round(v, 2), "margen_pct": round((v - c) / v, 4) if v else None,
              "en_curso": m == p.hoy.isoformat()[:7], "elegido": m == p.mes} for m, (v, c) in sorted(meses.items())]

    # Clientes: activos, nuevos y en riesgo (compraban seguido y dejaron de comprar)
    clientes = _q(usuario, f"""
        SELECT v.cliente_id, MIN(v.fecha), MAX(v.fecha), COUNT(DISTINCT v.id), SUM(l.cantidad * l.precio_unitario),
               SUM(CASE WHEN v.fecha >= '{d0}' THEN l.cantidad * l.precio_unitario ELSE 0 END)
        FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
        WHERE v.anulada = 0 AND v.fecha >= '{d365}' AND v.fecha <= '{hasta}' AND v.cliente_id IS NOT NULL
        GROUP BY v.cliente_id""")
    nombres = _nombres(usuario, "SELECT id, razon_social FROM clientes", "Cliente")
    activos = [c for c in clientes if c[2][:10] >= d0]
    nuevos = [c for c in clientes if c[1][:10] >= d0]
    riesgo = []
    for c in clientes:
        sin_comprar = _dias(hasta, c[2])
        meses_activo = max(1, _dias(c[2], c[1]) / 30)
        if c[3] >= 3 and 60 <= sin_comprar <= 365:
            riesgo.append({"cliente": nombres.get(c[0], f"Cliente {c[0]}"), "dias_sin_comprar": sin_comprar,
                           "compra_mensual": round(c[4] / meses_activo, 2)})
    riesgo.sort(key=lambda r: -r["compra_mensual"])

    top_clientes = sorted((c for c in clientes if c[5]), key=lambda c: -c[5])[:10]
    vendedores = _q(usuario, f"""
        SELECT v.vendedor_id, SUM(l.cantidad * l.precio_unitario), SUM(l.cantidad * l.costo_unitario), COUNT(DISTINCT v.cliente_id)
        FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
        WHERE v.anulada = 0 AND v.fecha >= '{d0}' AND v.fecha <= '{hasta}' GROUP BY v.vendedor_id""")
    nombre_vendedor = _nombres(usuario, "SELECT id, nombre FROM vendedores", "Vendedor")
    sucursales = _q(usuario, f"""
        SELECT v.sucursal_id, SUM(l.cantidad * l.precio_unitario), COUNT(DISTINCT v.id)
        FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
        WHERE v.anulada = 0 AND v.fecha >= '{d0}' AND v.fecha <= '{hasta}' GROUP BY v.sucursal_id""")
    nombre_sucursal = _nombres(usuario, "SELECT id, nombre FROM sucursales", "Sucursal")

    return {
        "kpis": [
            _kpi("Venta neta", round(venta, 2), "moneda", _variacion(venta, venta_a), "sin impuestos"),
            _kpi("Margen bruto", round(margen, 2), "moneda", _variacion(margen, margen_a)),
            _kpi("Margen %", round(margen / venta, 4) if venta else None, "porcentaje",
                 round(margen / venta - margen_a / venta_a, 4) if venta and venta_a else None, "variación en puntos"),
            _kpi("Pedidos", ped, "numero", _variacion(ped, ped_a)),
            _kpi("Pedido promedio", round(venta / ped, 2) if ped else None, "moneda"),
            _kpi("Líneas por pedido", round(lineas / ped, 1) if ped else None, "numero"),
            _kpi("Clientes activos", len(activos), "numero", nota="compraron en el mes"),
            _kpi("Clientes nuevos", len(nuevos), "numero", nota="primera compra del año en el mes"),
            _kpi("Venta en riesgo", round(sum(r["compra_mensual"] for r in riesgo), 2), "moneda",
                 nota=(f"{len(riesgo)} cliente que dejó" if len(riesgo) == 1 else f"{len(riesgo)} clientes que dejaron") + " de comprar (por mes)", estado="alerta" if riesgo else None),
        ],
        "serie_mensual": serie,
        "top_clientes": [{"cliente": nombres.get(c[0], f"Cliente {c[0]}"), "venta": round(c[5], 2)} for c in top_clientes],
        "clientes_en_riesgo": riesgo[:10],
        "vendedores": sorted([{"vendedor": nombre_vendedor.get(v[0], f"Vendedor {v[0]}" if v[0] is not None else "Sin vendedor"),
                               "venta": round(v[1] or 0, 2), "margen_pct": round((v[1] - v[2]) / v[1], 4) if v[1] else None,
                               "clientes": v[3]} for v in vendedores], key=lambda v: -v["venta"]),
        "sucursales": sorted([{"sucursal": nombre_sucursal.get(s[0], f"Sucursal {s[0]}" if s[0] is not None else "Sin sucursal"),
                               "venta": round(s[1] or 0, 2), "pedidos": s[2]} for s in sucursales], key=lambda s: -s["venta"]),
    }


# --- Inventario -----------------------------------------------------------------

def inventario(usuario: Usuario, p: Periodo) -> dict:
    ref = p.hasta
    productos = {p[0]: p for p in _q(usuario, "SELECT id, descripcion, categoria, costo, precio FROM productos")}
    stock = {s[0]: s[1] or 0 for s in _q(usuario, "SELECT producto_id, SUM(cantidad) FROM stock GROUP BY producto_id")}
    if not productos:
        raise _SinDatos("No hay productos cargados.")
    if not stock:
        raise _SinDatos("No hay stock cargado: sincronizá los almacenes o cargá el archivo de stock.")
    d90, d365, hasta = (ref - timedelta(days=89)).isoformat(), (ref - timedelta(days=364)).isoformat(), ref.isoformat()
    try:
        vendido = {f[0]: f for f in _q(usuario, f"""
            SELECT l.producto_id, SUM(CASE WHEN v.fecha >= '{d90}' THEN l.cantidad ELSE 0 END),
                   SUM(CASE WHEN v.fecha >= '{d90}' THEN l.cantidad * l.costo_unitario ELSE 0 END),
                   SUM(l.cantidad * l.costo_unitario), MAX(v.fecha)
            FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
            WHERE v.anulada = 0 AND v.fecha >= '{d365}' AND v.fecha <= '{hasta}' GROUP BY l.producto_id""")}
    except (AccesoDenegado, ConsultaNoPermitida):
        vendido = {}

    valor = inmovilizado = 0.0
    quiebres, por_quebrar, sin_venta = [], [], []
    for pid, (_, desc, categoria, costo, precio) in productos.items():
        cantidad = stock.get(pid, 0)
        v = vendido.get(pid)
        diaria = (v[1] or 0) / 90 if v else 0
        valor_prod = max(cantidad, 0) * (costo or 0)
        valor += valor_prod
        if diaria > 0 and cantidad <= 0:
            quiebres.append({"producto": desc, "venta_diaria": round(diaria, 2),
                             "venta_perdida_diaria": round(diaria * (precio or 0), 2)})
        elif diaria > 0 and cantidad / diaria < 7:
            por_quebrar.append({"producto": desc, "stock": cantidad, "dias_cobertura": round(cantidad / diaria, 1)})
        if cantidad > 0 and (not v or (v[4] and v[4][:10] < d90) or not v[1]):
            inmovilizado += valor_prod
            sin_venta.append({"producto": desc, "stock": cantidad, "valor": round(valor_prod, 2),
                              "ultima_venta": v[4][:10] if v and v[4] else None})
    costo_90 = sum((f[2] or 0) for f in vendido.values())
    costo_anual = sum((f[3] or 0) for f in vendido.values())
    hay_ventas = bool(vendido)
    if usuario.filtros_fila:
        # Vendedor: el stock es de toda la empresa pero la demanda es solo de su cartera, así que la
        # cobertura y la rotación no tienen sentido. Se muestra lo que le sirve: qué le falta para vender.
        return {
            "kpis": [
                _kpi("Quiebres de stock", len(quiebres), "numero", nota="productos que tus clientes compran y están en 0",
                     estado="critico" if quiebres else "ok"),
                _kpi("Venta perdida por quiebres", round(sum(q["venta_perdida_diaria"] for q in quiebres), 2), "moneda",
                     nota="estimada por día, de tu cartera", estado="critico" if quiebres else None),
            ],
            "quiebres": sorted(quiebres, key=lambda q: -q["venta_perdida_diaria"])[:10],
            "por_quebrar": [], "inmovilizado": [], "sin_ventas": not hay_ventas,
            "nota": "El stock es de toda la empresa; la demanda es la de tu cartera.",
        }
    return {
        "kpis": [
            _kpi("Valor del inventario", round(valor, 2), "moneda", nota="a costo"),
            _kpi("Días de inventario", round(valor / (costo_90 / 90), 1) if costo_90 else None, "dias",
                 nota="al ritmo de venta de 90 días"),
            _kpi("Rotación anual", round(costo_anual / valor, 1) if valor and hay_ventas else None, "veces"),
            _kpi("Quiebres de stock", len(quiebres), "numero", nota="productos que se venden y están en 0",
                 estado="critico" if quiebres else "ok"),
            _kpi("Venta perdida por quiebres", round(sum(q["venta_perdida_diaria"] for q in quiebres), 2), "moneda",
                 nota="estimada por día", estado="critico" if quiebres else None),
            _kpi("Por quebrar", len(por_quebrar), "numero", nota="menos de 7 días de stock", estado="alerta" if por_quebrar else "ok"),
            _kpi("Capital inmovilizado", round(inmovilizado, 2), "moneda", nota="sin venta en más de 90 días",
                 estado="alerta" if inmovilizado else None),
        ],
        "quiebres": sorted(quiebres, key=lambda q: -q["venta_perdida_diaria"])[:10],
        "por_quebrar": sorted(por_quebrar, key=lambda q: q["dias_cobertura"])[:10],
        "inmovilizado": sorted(sin_venta, key=lambda q: -q["valor"])[:10],
        "sin_ventas": not hay_ventas,
    }


def _valor(seccion: dict, nombre: str):
    return next((k["valor"] for k in seccion.get("kpis", []) if k["nombre"] == nombre), None)


def _sumar(seccion: dict, bloque) -> None:
    """Agrega al pilar los indicadores que se habilitan con más datos (app/analisis/indicadores.py)."""
    if "kpis" not in seccion:
        return
    seccion["kpis"] += bloque.kpis
    seccion["paneles_extra"] = bloque.paneles


def tablero(usuario: Usuario, mes: str | None = None, hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    meses = meses_disponibles(usuario, hoy)
    validos = [m["valor"] for m in meses]
    if mes not in validos:  # por defecto, el mes más reciente con ventas
        mes = next((m["valor"] for m in meses if m["con_ventas"]), validos[0])
    p = Periodo.crear(mes, hoy)
    v = _seccion(ventas, usuario, p)
    i = _seccion(inventario, usuario, p)

    def bloque(fn, *args):
        try:
            return fn(*args)
        except Exception:  # un bloque que no se puede calcular se omite; el resto del tablero se muestra
            return indicadores.Bloque()

    bloques = [bloque(indicadores.ventas, usuario, p.hasta, p.dias, _valor(v, "Venta neta")),
               bloque(indicadores.inventario, usuario, p.hasta, p.dias)]
    for seccion, b in zip((v, i), bloques):
        _sumar(seccion, b)
    if not p.en_curso and "kpis" in i:
        i["nota"] = "El stock y los lotes son los de hoy; las ventas y mermas, las del mes elegido."
    try:
        f = finanzas_analisis.finanzas(usuario, p)
    except Exception as e:  # nunca un error 500
        f = {"sin_datos": True, "mensaje": f"No se pudo calcular Finanzas ({type(e).__name__}: {str(e).splitlines()[0][:160]})."}
    return {
        "mes": p.mes,
        "nombre": p.nombre,
        "periodo": p.describir(),
        "desde": p.desde.isoformat(),
        "hasta": p.hasta.isoformat(),
        "en_curso": p.en_curso,
        "meses": meses,
        "ventas": v,
        "inventario": i,
        "finanzas": f,
        "no_disponibles": [x for b in bloques for x in b.faltan] + f.pop("faltan", []),
    }
