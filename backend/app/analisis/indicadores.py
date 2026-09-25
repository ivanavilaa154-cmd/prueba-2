"""Indicadores que se habilitan cuando el sistema integrado trae más datos.

Cada bloque revisa si su tabla tiene datos: si los tiene, agrega indicadores y
paneles al pilar del tablero; si no, deja anotado qué falta (y nunca inventa).
Igual que el resto del tablero, las consultas pasan por el conector con el
usuario, así cada rol ve solo lo suyo; si el rol no tiene la tabla, el bloque
simplemente no aparece.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from ..erp import conector
from ..erp.conector import ConsultaNoPermitida
from ..permisos import AccesoDenegado, Usuario

SIN_LIMITE = 1_000_000


def _q(usuario: Usuario, sql: str) -> list[list] | None:
    """Filas, o None si el rol no tiene acceso a alguna tabla de la consulta."""
    try:
        return conector.consultar(sql, max_filas=SIN_LIMITE, usuario=usuario)["filas"]
    except (AccesoDenegado, ConsultaNoPermitida):
        return None


def _uno(usuario: Usuario, sql: str):
    filas = _q(usuario, sql)
    return filas[0][0] if filas else None


def _hay(usuario: Usuario, tabla: str, condicion: str = "") -> bool | None:
    n = _uno(usuario, f"SELECT COUNT(*) FROM {tabla}" + (f" WHERE {condicion}" if condicion else ""))
    return None if n is None else n > 0


def _kpi(nombre, valor, formato, nota=None, estado=None, variacion=None) -> dict:
    return {"nombre": nombre, "valor": valor, "formato": formato, "variacion": variacion, "nota": nota, "estado": estado}


def _panel(titulo, columnas, tipos, filas, vacio="Sin datos en el período.", ancho=False) -> dict:
    return {"titulo": titulo, "columnas": columnas, "tipos": tipos, "filas": filas, "vacio": vacio, "ancho": ancho}


def _pct(a, b):
    return round(a / b, 4) if b else None


class Bloque:
    """Lo que un pilar suma: indicadores, paneles y lo que falta para calcular más."""

    def __init__(self):
        self.kpis: list[dict] = []
        self.paneles: list[dict] = []
        self.faltan: list[dict] = []

    def falta(self, indicador: str, tabla: str, motivo: str):
        self.faltan.append({"indicador": indicador, "motivo": f"{motivo} (tabla {tabla})"})


def _rango(ref: date, dias: int) -> tuple[str, str]:
    return (ref - timedelta(days=dias - 1)).isoformat(), ref.isoformat()


# --- Ventas -----------------------------------------------------------------------

def ventas(usuario: Usuario, ref: date, dias: int, venta_neta: float | None) -> Bloque:
    b = Bloque()
    d0, hasta = _rango(ref, dias)
    periodo = f"v.anulada = 0 AND v.fecha >= '{d0}' AND v.fecha <= '{hasta}'"
    base = f"FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id WHERE {periodo}"

    imp = _q(usuario, f"SELECT SUM(l.impuestos), COUNT(l.impuestos) {base}")
    if imp and imp[0][1]:
        b.kpis.append(_kpi("Venta con impuestos", round((venta_neta or 0) + (imp[0][0] or 0), 2), "moneda",
                           "comparable con el «Total» de Odoo"))

    canales = _q(usuario, f"""SELECT v.canal, SUM(l.cantidad * l.precio_unitario), SUM(l.cantidad * l.precio_unitario + COALESCE(l.impuestos, 0)),
                               SUM(l.cantidad), COUNT(DISTINCT v.id) {base} GROUP BY v.canal""")
    if canales and any(c[0] for c in canales):
        b.paneles.append(_panel("Por canal o equipo de ventas", ["Canal", "Sin impuestos", "Con impuestos", "Cantidad", "Pedidos"],
                                ["t", "$", "$", "n", "n"],
                                sorted([[c[0] or "Sin equipo", c[1], c[2], c[3], c[4]] for c in canales], key=lambda f: -(f[1] or 0))))

    desc = _q(usuario, f"SELECT SUM(l.cantidad * l.precio_lista * l.descuento_pct), SUM(l.cantidad * l.precio_lista) {base} AND l.precio_lista IS NOT NULL")
    if desc and desc[0][1]:
        b.kpis.append(_kpi("Descuentos otorgados", _pct(desc[0][0] or 0, desc[0][1]), "porcentaje", "sobre la venta a precio de lista"))

    hay = _hay(usuario, "devoluciones")
    if hay:
        dev = _q(usuario, f"SELECT SUM(importe), COUNT(*) FROM devoluciones WHERE fecha >= '{d0}' AND fecha <= '{hasta}'")[0]
        tasa = _pct(dev[0] or 0, venta_neta) if venta_neta else None
        b.kpis.append(_kpi("Devoluciones", round(dev[0] or 0, 2), "moneda",
                           f"{dev[1]} notas de crédito" + (f", {tasa * 100:.1f} % de la venta".replace(".", ",") if tasa is not None else ""),
                           "alerta" if tasa and tasa > 0.03 else None))
    elif hay is False:
        b.falta("Devoluciones y notas de crédito", "devoluciones", "no hay notas de crédito")

    hay = _hay(usuario, "pedidos")
    if hay:
        p = _q(usuario, f"""SELECT COUNT(*), SUM(CASE WHEN estado = 'entregado' AND (fecha_entrega_prometida IS NULL
                                OR fecha_entrega IS NULL OR fecha_entrega <= fecha_entrega_prometida) THEN 1 ELSE 0 END)
                            FROM pedidos WHERE estado <> 'anulado' AND fecha_pedido >= '{d0}' AND fecha_pedido <= '{hasta}'""")[0]
        u = _q(usuario, f"""SELECT SUM(pl.cantidad_entregada), SUM(pl.cantidad_pedida) FROM pedidos_lineas pl
                            JOIN pedidos p ON p.id = pl.pedido_id WHERE p.estado <> 'anulado'
                            AND p.fecha_pedido >= '{d0}' AND p.fecha_pedido <= '{hasta}' AND pl.cantidad_entregada IS NOT NULL""")
        completos = _pct(p[1] or 0, p[0])
        b.kpis.append(_kpi("Pedidos completos y a tiempo", completos, "porcentaje", f"de {p[0]} pedidos del período",
                           "alerta" if completos is not None and completos < 0.9 else None))
        if u and u[0][1]:
            b.kpis.append(_kpi("Unidades entregadas", _pct(u[0][0] or 0, u[0][1]), "porcentaje", "de lo pedido (incluye pedidos en curso)"))
    elif hay is False:
        b.falta("Pedidos completos y a tiempo", "pedidos", "no hay pedidos con fecha de entrega")

    hay = _hay(usuario, "presupuestos")
    if hay:
        pr = _q(usuario, f"""SELECT COUNT(*), SUM(CASE WHEN estado = 'aceptado' THEN 1 ELSE 0 END), SUM(importe)
                             FROM presupuestos WHERE fecha >= '{d0}' AND fecha <= '{hasta}'""")[0]
        b.kpis.append(_kpi("Presupuestos aceptados", _pct(pr[1] or 0, pr[0]), "porcentaje", f"de {pr[0]} presupuestos del período"))
    elif hay is False:
        b.falta("Conversión de presupuestos", "presupuestos", "no hay presupuestos")

    hay = _hay(usuario, "objetivos_vendedores")
    if hay:
        mes = ref.isoformat()[:7]
        filas = _q(usuario, f"""SELECT o.vendedor_id, o.objetivo_venta,
                                  (SELECT SUM(l.cantidad * l.precio_unitario) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
                                   WHERE v.anulada = 0 AND v.vendedor_id = o.vendedor_id AND v.fecha >= '{mes}-01' AND v.fecha <= '{hasta}')
                                FROM objetivos_vendedores o WHERE o.mes = '{mes}'""") or []
        nombres = {f[0]: f[1] for f in (_q(usuario, "SELECT id, nombre FROM vendedores") or [])}
        if filas:
            total_obj, total_venta = sum(f[1] or 0 for f in filas), sum(f[2] or 0 for f in filas)
            b.kpis.append(_kpi("Cumplimiento de objetivos", _pct(total_venta, total_obj), "porcentaje", "del mes en curso"))
            b.paneles.append(_panel("Objetivos del mes por vendedor", ["Vendedor", "Objetivo", "Vendido", "Cumplimiento"], ["t", "$", "$", "%"],
                                    [[nombres.get(f[0], f"Vendedor {f[0]}"), f[1], f[2] or 0, _pct(f[2] or 0, f[1])] for f in filas]))
    elif hay is False:
        b.falta("Cumplimiento de objetivos por vendedor", "objetivos_vendedores", "no hay objetivos cargados")
    return b


# --- Inventario ---------------------------------------------------------------------

def inventario(usuario: Usuario, ref: date, dias: int) -> Bloque:
    b = Bloque()
    d0, hasta = _rango(ref, dias)

    hay = _hay(usuario, "movimientos_stock")
    if hay:
        merma = _q(usuario, f"""SELECT SUM(-m.cantidad * COALESCE(m.costo_unitario, p.costo)), COUNT(*)
                                FROM movimientos_stock m LEFT JOIN productos p ON p.id = m.producto_id
                                WHERE m.tipo IN ('merma', 'vencimiento') AND m.fecha >= '{d0}' AND m.fecha <= '{hasta}'""")[0]
        costo_venta = _uno(usuario, f"""SELECT SUM(l.cantidad * l.costo_unitario) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
                                        WHERE v.anulada = 0 AND v.fecha >= '{d0}' AND v.fecha <= '{hasta}'""")
        tasa = _pct(merma[0] or 0, costo_venta) if costo_venta else None
        b.kpis.append(_kpi("Merma", round(merma[0] or 0, 2), "moneda",
                           f"{merma[1]} bajas" + (f", {tasa * 100:.1f} % del costo vendido".replace(".", ",") if tasa is not None else ""),
                           "alerta" if tasa and tasa > 0.01 else None))
        detalle = _q(usuario, f"""SELECT p.descripcion, m.motivo, SUM(-m.cantidad), SUM(-m.cantidad * COALESCE(m.costo_unitario, p.costo))
                                  FROM movimientos_stock m LEFT JOIN productos p ON p.id = m.producto_id
                                  WHERE m.tipo IN ('merma', 'vencimiento') AND m.fecha >= '{d0}' AND m.fecha <= '{hasta}'
                                  GROUP BY p.descripcion, m.motivo""") or []
        b.paneles.append(_panel("Merma del período", ["Producto", "Motivo", "Unidades", "Valor"], ["t", "t", "n", "$"],
                                sorted(detalle, key=lambda f: -(f[3] or 0))[:10], "No hubo mermas en el período."))
    elif hay is False:
        b.falta("Merma y tasa de merma", "movimientos_stock", "no hay movimientos de stock")

    hay = _hay(usuario, "stock", "fecha_vencimiento IS NOT NULL")
    if hay:
        limite = (ref + timedelta(days=30)).isoformat()
        filas = _q(usuario, f"""SELECT p.descripcion, s.lote, s.fecha_vencimiento, s.cantidad, s.cantidad * p.costo
                               FROM stock s JOIN productos p ON p.id = s.producto_id
                               WHERE s.fecha_vencimiento IS NOT NULL AND s.fecha_vencimiento <= '{limite}' AND s.cantidad > 0
                               ORDER BY s.fecha_vencimiento""") or []
        vencidos = [f for f in filas if f[2] < ref.isoformat()]
        b.kpis.append(_kpi("Por vencer en 30 días", round(sum(f[4] or 0 for f in filas if f[2] >= ref.isoformat()), 2), "moneda",
                           "a costo", "alerta" if filas else "ok"))
        if vencidos:
            b.kpis.append(_kpi("Mercadería vencida en stock", round(sum(f[4] or 0 for f in vencidos), 2), "moneda",
                               f"{len(vencidos)} lotes", "critico"))
        b.paneles.append(_panel("Lotes por vencer o vencidos", ["Producto", "Lote", "Vence", "Unidades", "Valor"], ["t", "t", "t", "n", "$"],
                                filas[:15], "No hay lotes por vencer en los próximos 30 días."))
    elif hay is False:
        b.falta("Mercadería por vencer", "stock", "no hay lotes con fecha de vencimiento")

    transito = _q(usuario, "SELECT SUM(s.en_transito * p.costo), COUNT(*) FROM stock s JOIN productos p ON p.id = s.producto_id WHERE s.en_transito > 0")
    if transito and transito[0][1]:
        b.kpis.append(_kpi("Mercadería en tránsito", round(transito[0][0] or 0, 2), "moneda", "compras y transferencias sin recibir"))

    hay = _hay(usuario, "compras")
    if hay:
        d90 = (ref - timedelta(days=89)).isoformat()
        prov = _q(usuario, f"""SELECT c.proveedor_id, COUNT(DISTINCT c.id),
                                 SUM(CASE WHEN cl.cantidad_recibida >= cl.cantidad_pedida THEN 1 ELSE 0 END), COUNT(cl.compra_id),
                                 SUM(CASE WHEN c.fecha_recepcion IS NOT NULL AND c.fecha_prometida IS NOT NULL
                                          AND c.fecha_recepcion <= c.fecha_prometida THEN 1 ELSE 0 END),
                                 SUM(CASE WHEN c.fecha_recepcion IS NOT NULL AND c.fecha_prometida IS NOT NULL THEN 1 ELSE 0 END)
                               FROM compras c JOIN compras_lineas cl ON cl.compra_id = c.id
                               WHERE c.estado <> 'anulada' AND c.fecha >= '{d90}' AND c.fecha <= '{hasta}'
                               GROUP BY c.proveedor_id""") or []
        nombres = {f[0]: f[1] for f in (_q(usuario, "SELECT id, nombre FROM proveedores") or [])}
        completas, lineas = sum(f[2] or 0 for f in prov), sum(f[3] or 0 for f in prov)
        a_tiempo, con_fecha = sum(f[4] or 0 for f in prov), sum(f[5] or 0 for f in prov)
        if lineas:
            b.kpis.append(_kpi("Compras recibidas completas", _pct(completas, lineas), "porcentaje", "líneas de compra, últimos 90 días",
                               "alerta" if completas / lineas < 0.9 else None))
        if con_fecha:
            b.kpis.append(_kpi("Proveedores a tiempo", _pct(a_tiempo, con_fecha), "porcentaje", "entregas en la fecha prometida"))
        b.paneles.append(_panel("Cumplimiento de proveedores (90 días)", ["Proveedor", "Órdenes", "Líneas completas", "A tiempo"],
                                ["t", "n", "%", "%"],
                                [[nombres.get(f[0], f"Proveedor {f[0]}"), f[1], _pct(f[2] or 0, f[3]), _pct(f[4] or 0, f[5])] for f in prov],
                                "No hubo compras en los últimos 90 días."))
    elif hay is False:
        b.falta("Cumplimiento de proveedores", "compras", "no hay órdenes de compra")

    hay = _hay(usuario, "conteos")
    if hay:
        c = _q(usuario, "SELECT COUNT(*), SUM(CASE WHEN cantidad_contada = cantidad_sistema THEN 1 ELSE 0 END) FROM conteos "
                        "WHERE cantidad_sistema IS NOT NULL")[0]
        if c[0]:
            b.kpis.append(_kpi("Exactitud de inventario", _pct(c[1] or 0, c[0]), "porcentaje", f"{c[0]} conteos"))
    elif hay is False:
        b.falta("Exactitud de inventario", "conteos", "no hay conteos físicos")
    return b


# --- Finanzas ------------------------------------------------------------------------

def finanzas(usuario: Usuario, ref: date, dias: int, margen_bruto: float | None) -> Bloque:
    b = Bloque()
    d0, hasta = _rango(ref, dias)
    d90 = (ref - timedelta(days=89)).isoformat()

    caja = None
    hay = _hay(usuario, "cuentas_bancarias")
    if hay:
        cuentas = _q(usuario, "SELECT nombre, tipo, moneda, saldo FROM cuentas_bancarias ORDER BY saldo DESC")
        caja = sum(c[3] or 0 for c in cuentas)
        b.kpis.append(_kpi("Caja y bancos", round(caja, 2), "moneda", "saldo contable", "critico" if caja < 0 else None))
        b.paneles.append(_panel("Bancos y cajas", ["Cuenta", "Tipo", "Moneda", "Saldo"], ["t", "t", "t", "$"], cuentas))
    elif hay is False:
        b.falta("Saldo de caja y flujo de 13 semanas", "cuentas_bancarias", "no hay saldos de bancos ni cajas")

    deuda_prov = None
    hay = _hay(usuario, "cxp")
    if hay:
        cxp = _q(usuario, f"""SELECT SUM(saldo), SUM(CASE WHEN fecha_vencimiento < '{hasta}' THEN saldo ELSE 0 END) FROM cxp WHERE saldo <> 0""")[0]
        deuda_prov = cxp[0] or 0
        compras_90 = _uno(usuario, f"SELECT SUM(importe) FROM cxp WHERE tipo <> 'nota_credito' AND fecha_emision >= '{d90}' AND fecha_emision <= '{hasta}'")
        b.kpis.append(_kpi("Deuda con proveedores", round(deuda_prov, 2), "moneda", "saldo a pagar"))
        b.kpis.append(_kpi("Deuda con proveedores vencida", round(cxp[1] or 0, 2), "moneda", None, "alerta" if cxp[1] else "ok"))
        b.kpis.append(_kpi("DPO", round(deuda_prov / (compras_90 / 90), 1) if compras_90 else None, "dias", "días de compras que se deben"))
        prox = _q(usuario, f"""SELECT p.nombre, x.numero, x.fecha_vencimiento, x.saldo FROM cxp x LEFT JOIN proveedores p ON p.id = x.proveedor_id
                               WHERE x.saldo > 0 ORDER BY x.fecha_vencimiento""") or []
        prox = prox[:10]
        b.paneles.append(_panel("Próximos pagos a proveedores", ["Proveedor", "Factura", "Vence", "Saldo"], ["t", "t", "t", "$"], prox,
                                "No hay facturas de proveedores pendientes."))
    elif hay is False:
        b.falta("Cuentas por pagar y DPO", "cxp", "no hay facturas de proveedores")

    hay = _hay(usuario, "cobranzas")
    if hay:
        medios = _q(usuario, f"SELECT medio, SUM(importe), COUNT(*) FROM cobranzas WHERE fecha >= '{d0}' AND fecha <= '{hasta}' GROUP BY medio") or []
        total = sum(m[1] or 0 for m in medios)
        b.kpis.append(_kpi("Cobrado en el período", round(total, 2), "moneda", f"{sum(m[2] for m in medios)} cobranzas"))
        b.paneles.append(_panel("Cobranzas por medio de pago", ["Medio", "Importe", "Cantidad"], ["t", "$", "n"],
                                sorted([[m[0] or "Sin dato", m[1], m[2]] for m in medios], key=lambda f: -(f[1] or 0))))
    elif hay is False:
        b.falta("Cobranzas por medio de pago", "cobranzas", "no hay cobranzas registradas")

    hay = _hay(usuario, "cheques")
    if hay:
        ch = {(f[0], f[1]): (f[2] or 0, f[3]) for f in _q(usuario, "SELECT tipo, estado, SUM(importe), COUNT(*) FROM cheques GROUP BY tipo, estado")}
        cartera = ch.get(("recibido", "cartera"), (0, 0))
        rechazados = ch.get(("recibido", "rechazado"), (0, 0))
        b.kpis.append(_kpi("Cheques en cartera", round(cartera[0], 2), "moneda", f"{cartera[1]} cheques"))
        b.kpis.append(_kpi("Cheques rechazados", round(rechazados[0], 2), "moneda", f"{rechazados[1]} cheques", "critico" if rechazados[1] else "ok"))
    elif hay is False:
        b.falta("Cheques en cartera y rechazados", "cheques", "no hay cheques")

    gastos_periodo = None
    hay = _hay(usuario, "gastos")
    if hay:
        # Los gastos se contabilizan una vez por mes: una ventana de 30 días puede no tomar ningún asiento.
        # Se usa el promedio diario de los últimos 90 días llevado al período.
        cats = _q(usuario, f"SELECT categoria, SUM(importe) FROM gastos WHERE fecha >= '{d90}' AND fecha <= '{hasta}' GROUP BY categoria") or []
        cats = [[c[0], (c[1] or 0) / 90 * dias] for c in cats]
        gastos_periodo = sum(c[1] for c in cats)
        b.kpis.append(_kpi("Gastos operativos", round(gastos_periodo, 2), "moneda", f"de {dias} días, según el promedio de los últimos 90"))
        if margen_bruto is not None:
            b.kpis.append(_kpi("Resultado operativo (aprox. EBITDA)", round(margen_bruto - gastos_periodo, 2), "moneda",
                               "margen bruto menos gastos", "critico" if margen_bruto - gastos_periodo < 0 else None))
        b.paneles.append(_panel(f"Gastos por categoría ({dias} días)", ["Categoría", "Importe"], ["t", "$"],
                                sorted([[c[0] or "otros", c[1]] for c in cats], key=lambda f: -(f[1] or 0))))
    elif hay is False:
        b.falta("EBITDA y resultado operativo", "gastos", "no hay gastos operativos")

    hay = _hay(usuario, "impuestos")
    if hay:
        ultimo = _q(usuario, "SELECT periodo, SUM(importe) FROM impuestos GROUP BY periodo ORDER BY periodo DESC")
        if ultimo:
            b.kpis.append(_kpi("Impuestos del último período", round(ultimo[0][1] or 0, 2), "moneda", f"período {ultimo[0][0]}"))
    elif hay is False:
        b.falta("Impuestos a pagar", "impuestos", "no hay impuestos registrados")

    hay = _hay(usuario, "prestamos")
    if hay:
        b.kpis.append(_kpi("Deuda financiera", round(_uno(usuario, "SELECT SUM(saldo) FROM prestamos") or 0, 2), "moneda", "préstamos"))
    elif hay is False:
        b.falta("Deuda financiera", "prestamos", "no hay préstamos")

    if caja is not None:
        flujo = flujo_13_semanas(usuario, ref, caja)
        if flujo:
            minimo = min(flujo, key=lambda s: s["saldo_final"])
            b.kpis.append(_kpi("Punto más bajo de caja (13 semanas)", round(minimo["saldo_final"], 2), "moneda",
                               f"semana del {minimo['desde']}, estimado", "critico" if minimo["saldo_final"] < 0 else None))
            b.paneles.append(_panel("Flujo de caja estimado, 13 semanas", ["Semana", "Cobros", "Pagos a proveedores", "Gastos", "Saldo final"],
                                    ["t", "$", "$", "$", "$"],
                                    [[f"{s['desde']}", s["cobros"], s["pagos"], s["gastos"], s["saldo_final"]] for s in flujo], ancho=True))
    return b


def flujo_13_semanas(usuario: Usuario, ref: date, caja: float) -> list[dict]:
    """Proyección simple: cobros según vencimiento más el atraso real, pagos según vencimiento y gastos promedio.

    Lo vencido se proyecta en la primera semana. Es una estimación para ver con tiempo si falta caja.
    """
    cobradas = _q(usuario, "SELECT fecha_cobro, fecha_vencimiento FROM cxc WHERE fecha_cobro IS NOT NULL AND fecha_vencimiento IS NOT NULL") or []
    atrasos = [(date.fromisoformat(f[0][:10]) - date.fromisoformat(f[1][:10])).days for f in cobradas]
    atraso = max(0, round(sum(atrasos) / len(atrasos))) if atrasos else 0
    cobros = _q(usuario, "SELECT fecha_vencimiento, saldo FROM cxc WHERE saldo > 0") or []
    pagos = _q(usuario, "SELECT fecha_vencimiento, saldo FROM cxp WHERE saldo > 0") or []
    d90 = (ref - timedelta(days=89)).isoformat()
    gastos_90 = _uno(usuario, f"SELECT SUM(importe) FROM gastos WHERE fecha >= '{d90}' AND fecha <= '{ref.isoformat()}'") or 0
    semana_gasto = gastos_90 / 90 * 7

    def semana(fecha: str | None, corrimiento: int = 0) -> int:
        if not fecha:
            return 0
        dias = (date.fromisoformat(fecha[:10]) + timedelta(days=corrimiento) - ref).days
        return min(12, max(0, dias // 7))

    entradas, salidas = defaultdict(float), defaultdict(float)
    for f in cobros:
        entradas[semana(f[0], atraso)] += f[1] or 0
    for f in pagos:
        salidas[semana(f[0])] += f[1] or 0
    saldo, filas = caja, []
    for i in range(13):
        saldo += entradas[i] - salidas[i] - semana_gasto
        filas.append({"desde": (ref + timedelta(days=7 * i)).isoformat(), "cobros": round(entradas[i], 2),
                      "pagos": round(salidas[i], 2), "gastos": round(semana_gasto, 2), "saldo_final": round(saldo, 2)})
    return filas
