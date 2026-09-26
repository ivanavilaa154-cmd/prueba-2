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

from collections import defaultdict
from datetime import date, timedelta

from ..erp import conector
from ..erp.conector import ConsultaNoPermitida
from ..permisos import AccesoDenegado, Usuario
from . import indicadores

SIN_LIMITE = 1_000_000
TRAMOS = [("Al día", None, 0), ("1 a 15 días", 1, 15), ("16 a 30 días", 16, 30),
          ("31 a 60 días", 31, 60), ("61 a 90 días", 61, 90), ("Más de 90 días", 91, None)]
NO_DISPONIBLES = [
    ("Saldo de caja y flujo de 13 semanas", "no hay movimientos de caja ni bancos"),
    ("Cuentas por pagar y DPO", "no hay facturas de proveedores"),
    ("EBITDA y resultado neto", "no hay gastos operativos"),
    ("Mercadería por vencer", "no hay lotes con fecha de vencimiento"),
    ("Merma y exactitud de inventario", "no hay ajustes ni conteos de inventario"),
]


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


def fecha_de_referencia(usuario: Usuario, hoy: date | None = None) -> tuple[date, bool]:
    """Hoy, salvo que no haya ventas recientes (datos importados viejos): entonces el último día con ventas."""
    hoy = hoy or date.today()
    try:
        ultima = _q(usuario, "SELECT MAX(fecha) FROM ventas WHERE anulada = 0")[0][0]
    except Exception:
        return hoy, False
    if ultima and date.fromisoformat(ultima[:10]) < hoy - timedelta(days=30):
        return date.fromisoformat(ultima[:10]), True
    return hoy, False


# --- Ventas ---------------------------------------------------------------------

def ventas(usuario: Usuario, ref: date, dias: int) -> dict:
    d0, d1, d365 = (ref - timedelta(days=dias - 1)).isoformat(), (ref - timedelta(days=2 * dias - 1)).isoformat(), \
        (ref - timedelta(days=364)).isoformat()
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
    ped_a, venta_a, costo_a, _ = sumar(d1, (ref - timedelta(days=dias)).isoformat())
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
              "en_curso": m == ref.isoformat()[:7]} for m, (v, c) in sorted(meses.items())]

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
            _kpi("Clientes activos", len(activos), "numero", nota=f"compraron en los últimos {dias} días"),
            _kpi("Clientes nuevos", len(nuevos), "numero", nota="primera compra del año en el período"),
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

def inventario(usuario: Usuario, ref: date, dias: int) -> dict:
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


# --- Finanzas -------------------------------------------------------------------

def finanzas(usuario: Usuario, ref: date, dias: int) -> dict:
    hasta, d90 = ref.isoformat(), (ref - timedelta(days=89)).isoformat()
    facturas = _q(usuario, f"""
        SELECT cliente_id, fecha_emision, fecha_vencimiento, fecha_cobro, importe, saldo FROM cxc
        WHERE saldo <> 0 OR (fecha_cobro >= '{d90}' AND fecha_cobro <= '{hasta}')""")
    if not facturas:
        raise _SinDatos("No hay facturas a cobrar: sincronizá Facturación en Odoo o cargá el archivo cxc.")
    abiertas = [f for f in facturas if f[5]]
    total = sum(f[5] for f in abiertas)
    tramos = {nombre: 0.0 for nombre, _, _ in TRAMOS}
    vencida_cliente = defaultdict(lambda: [0.0, 0])
    for f in abiertas:
        atraso = _dias(hasta, f[2]) if f[2] else 0
        for nombre, desde, hasta_ in TRAMOS:
            if (desde is None and atraso <= 0) or (desde is not None and atraso >= desde and (hasta_ is None or atraso <= hasta_)):
                tramos[nombre] += f[5]
                break
        if atraso > 0:
            vencida_cliente[f[0]][0] += f[5]
            vencida_cliente[f[0]][1] = max(vencida_cliente[f[0]][1], atraso)
    vencida = total - tramos["Al día"]
    cobradas = [f for f in facturas if f[3] and f[1] and d90 <= f[3][:10] <= hasta]
    dias_cobro = sum(_dias(f[3], f[1]) for f in cobradas) / len(cobradas) if cobradas else None
    atraso_prom = sum(_dias(f[3], f[2]) for f in cobradas if f[2]) / len(cobradas) if cobradas else None
    try:
        venta_90 = _q(usuario, f"""SELECT SUM(l.cantidad * l.precio_unitario) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
                                   WHERE v.anulada = 0 AND v.fecha >= '{d90}' AND v.fecha <= '{hasta}'""")[0][0] or 0
    except (AccesoDenegado, ConsultaNoPermitida):
        venta_90 = 0
    nombres = _nombres(usuario, "SELECT id, razon_social FROM clientes", "Cliente")
    en_riesgo = sum(v for n, v in tramos.items() if n in ("61 a 90 días", "Más de 90 días"))
    return {
        "kpis": [
            _kpi("Deuda de clientes", round(total, 2), "moneda", nota="saldo pendiente"),
            _kpi("Deuda vencida", round(vencida, 2), "moneda", nota=f"{(vencida / total * 100 if total else 0):.1f} % del total".replace(".", ","),
                 estado="critico" if total and vencida / total > 0.3 else ("alerta" if vencida else "ok")),
            _kpi("Deuda en riesgo", round(en_riesgo, 2), "moneda", nota="más de 60 días vencida", estado="critico" if en_riesgo else None),
            _kpi("DSO", round(total / (venta_90 / 90), 1) if venta_90 else None, "dias", nota="días de venta en la calle"),
            _kpi("Días reales de cobro", round(dias_cobro, 1) if dias_cobro is not None else None, "dias",
                 nota="facturas cobradas en 90 días"),
            _kpi("Atraso promedio", round(atraso_prom, 1) if atraso_prom is not None else None, "dias",
                 nota="sobre el vencimiento", estado="alerta" if atraso_prom and atraso_prom > 7 else None),
        ],
        "antiguedad": [{"tramo": n, "saldo": round(v, 2)} for n, v in tramos.items()],
        "deudores": [{"cliente": nombres.get(c, f"Cliente {c}"), "vencido": round(v[0], 2), "dias_max_atraso": v[1]}
                     for c, v in sorted(vencida_cliente.items(), key=lambda x: -x[1][0])[:10]],
    }


def _valor(seccion: dict, nombre: str):
    return next((k["valor"] for k in seccion.get("kpis", []) if k["nombre"] == nombre), None)


def _sumar(seccion: dict, bloque) -> None:
    """Agrega al pilar los indicadores que se habilitan con más datos (app/analisis/indicadores.py)."""
    if "kpis" not in seccion:
        return
    seccion["kpis"] += bloque.kpis
    seccion["paneles_extra"] = bloque.paneles


def tablero(usuario: Usuario, dias: int = 30, hoy: date | None = None) -> dict:
    ref, ajustada = fecha_de_referencia(usuario, hoy)
    v = _seccion(ventas, usuario, ref, dias)
    i = _seccion(inventario, usuario, ref, dias)
    f = _seccion(finanzas, usuario, ref, dias)
    def bloque(fn, *args):
        try:
            return fn(*args)
        except Exception:  # un bloque que no se puede calcular se omite; el resto del tablero se muestra
            return indicadores.Bloque()

    bloques = [bloque(indicadores.ventas, usuario, ref, dias, _valor(v, "Venta neta")),
               bloque(indicadores.inventario, usuario, ref, dias),
               bloque(indicadores.finanzas, usuario, ref, dias, _valor(v, "Margen bruto"))]
    for seccion, bloque in zip((v, i, f), bloques):
        _sumar(seccion, bloque)
    if f.get("sin_datos") and bloques[2].kpis:  # sin facturas de clientes, pero con otros datos financieros
        f = {"kpis": bloques[2].kpis, "paneles_extra": bloques[2].paneles, "antiguedad": [], "deudores": [],
             "nota": "Sin facturas de clientes: se muestran los demás datos financieros."}
    return {
        "fecha": ref.isoformat(),
        "fecha_ajustada": ajustada,
        "dias": dias,
        "ventas": v,
        "inventario": i,
        "finanzas": f,
        "no_disponibles": [x for b in bloques for x in b.faltan],
    }
