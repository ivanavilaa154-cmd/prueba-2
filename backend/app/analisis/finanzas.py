"""Finanzas del tablero, completo: los bloques de prompts/03_finanzas.md que el modelo de datos permite.

Grupos (cada uno aparece solo si hay datos y el rol tiene acceso):
  1. Resultados del mes: estado de resultados de 12 meses, punto de equilibrio, crecimiento real, presupuesto.
  2. Cobranzas y crédito: deuda y antigüedad, DSO, efectividad de cobranza, riesgo por cliente, límites
     excedidos, agenda de cobranza, cobranzas por medio de pago, cheques.
  3. Pagos a proveedores: deuda, vencimientos de la semana y del mes, DPO, próximos pagos.
  4. Tesorería: caja y bancos, semanas de cobertura, flujo de 13 semanas y faltante contra la caja mínima.
  5. Capital de trabajo y salud: ciclo de conversión de caja, capital de trabajo, liquidez, monedas.
  6. Impuestos.
  7. Controles y alertas.

Las cuentas se hacen en código (regla 6). Los saldos (deuda, caja) son los de hoy aunque se elija un mes
anterior: el modelo guarda el saldo actual, no su historia. Lo que depende del mes (ventas, gastos,
cobranzas, pagos) usa el mes elegido.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from .. import config
from ..permisos import Usuario
from .indicadores import _q, _uno, flujo_13_semanas

TRAMOS = [("Al día", None, 0), ("1 a 15 días", 1, 15), ("16 a 30 días", 16, 30),
          ("31 a 60 días", 31, 60), ("61 a 90 días", 61, 90), ("Más de 90 días", 91, None)]


def _kpi(nombre, valor, formato, nota=None, estado=None, variacion=None) -> dict:
    return {"nombre": nombre, "valor": valor, "formato": formato, "variacion": variacion, "nota": nota, "estado": estado}


def _panel(titulo, columnas, tipos, filas, vacio="Sin datos.", ancho=False) -> dict:
    return {"titulo": titulo, "columnas": columnas, "tipos": tipos, "filas": filas, "vacio": vacio, "ancho": ancho}


def _pct(a, b):
    return round(a / b, 4) if b else None


def _var(a, b):
    return round((a - b) / abs(b), 4) if b else None


def _n(cantidad: int, singular: str, plural: str) -> str:
    return f"{cantidad} {singular if cantidad == 1 else plural}"


def _dias(a: str, b: str) -> int:
    return (date.fromisoformat(a[:10]) - date.fromisoformat(b[:10])).days


def _mes(mes: str, n: int) -> str:
    anio, m = int(mes[:4]), int(mes[5:7]) - 1 + n
    return f"{anio + m // 12}-{m % 12 + 1:02d}"


def _fin_de_mes(mes: str) -> str:
    return (date.fromisoformat(_mes(mes, 1) + "-01") - timedelta(days=1)).isoformat()


class Grupo:
    def __init__(self, titulo: str, descripcion: str = ""):
        self.titulo, self.descripcion = titulo, descripcion
        self.kpis: list[dict] = []
        self.paneles: list[dict] = []

    def a_dict(self) -> dict:
        return {"titulo": self.titulo, "descripcion": self.descripcion, "kpis": self.kpis, "paneles": self.paneles}


class Finanzas:
    def __init__(self, usuario: Usuario, p):
        self.u, self.p = usuario, p
        self.hoy = p.hoy.isoformat()
        self.desde, self.hasta = p.desde.isoformat(), p.hasta.isoformat()
        self.ant_desde, self.ant_hasta = p.ant_desde.isoformat(), p.ant_hasta.isoformat()
        self.fin = config.empresa().get("finanzas", {})
        self.faltan: list[dict] = []
        self.valores: dict = {}  # cifras que usan varios grupos

    def falta(self, indicador: str, motivo: str):
        self.faltan.append({"indicador": indicador, "motivo": motivo})

    def q(self, sql: str):
        return _q(self.u, sql)

    def uno(self, sql: str):
        return _uno(self.u, sql)

    def hay(self, tabla: str) -> bool | None:
        n = self.uno(f"SELECT COUNT(*) FROM {tabla}")
        return None if n is None else n > 0

    # --- 1. Resultados ------------------------------------------------------------

    def _ventas_por_mes(self, desde: str, hasta: str) -> dict[str, list[float]] | None:
        filas = self.q(f"""SELECT v.fecha, SUM(l.cantidad * l.precio_unitario), SUM(l.cantidad * l.costo_unitario)
                           FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
                           WHERE v.anulada = 0 AND v.fecha >= '{desde}' AND v.fecha <= '{hasta}' GROUP BY v.fecha""")
        if filas is None:
            return None
        meses = defaultdict(lambda: [0.0, 0.0])
        for f in filas:
            meses[f[0][:7]][0] += f[1] or 0
            meses[f[0][:7]][1] += f[2] or 0
        return meses

    def _venta_rango(self, desde: str, hasta: str) -> tuple[float, float] | None:
        f = self.q(f"""SELECT SUM(l.cantidad * l.precio_unitario), SUM(l.cantidad * l.costo_unitario)
                      FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
                      WHERE v.anulada = 0 AND v.fecha >= '{desde}' AND v.fecha <= '{hasta}'""")
        return None if f is None else (f[0][0] or 0, f[0][1] or 0)

    def resultados(self) -> Grupo | None:
        hay_gastos = self.hay("gastos")
        if hay_gastos is None:  # el rol no ve los gastos: el resultado es de la empresa, no se muestra
            return None
        mes = self.p.mes
        primer_mes = _mes(mes, -11)
        ventas = self._ventas_por_mes(primer_mes + "-01", self.hasta)
        actual = self._venta_rango(self.desde, self.hasta)
        anterior = self._venta_rango(self.ant_desde, self.ant_hasta)
        if ventas is None or actual is None:
            return None
        g = Grupo("Resultados del mes", "Estado de resultados: ventas, costo, gastos y resultado operativo.")
        gastos = defaultdict(float)
        cats_mes, cats_prev = defaultdict(float), defaultdict(float)
        if hay_gastos:
            for fecha, cat, importe in self.q(f"""SELECT fecha, categoria, importe FROM gastos
                                                 WHERE fecha >= '{_mes(mes, -14)}-01' AND fecha <= '{self.hasta}'"""):
                gastos[fecha[:7]] += importe or 0
                if fecha[:7] == mes:
                    cats_mes[cat or "otros"] += importe or 0
                elif _mes(mes, -3) <= fecha[:7] < mes:
                    cats_prev[cat or "otros"] += (importe or 0) / 3
        promedio_3 = sum(gastos.get(_mes(mes, -k), 0) for k in (1, 2, 3)) / 3
        # Mes en curso: los gastos suelen asentarse a fin de mes; si todavía no están, se estiman con el promedio.
        gasto_mes, estimado = gastos.get(mes, 0), False
        if self.p.en_curso and hay_gastos and not gasto_mes:
            gasto_mes, estimado = promedio_3 * self.p.dias / 30, True
        venta, costo = actual
        venta_a, costo_a = anterior
        margen, margen_a = venta - costo, venta_a - costo_a
        margen_pct = _pct(margen, venta)
        resultado = margen - gasto_mes if hay_gastos else None
        self.valores.update(venta_mes=venta, costo_mes=costo, gastos_mes=gasto_mes)
        g.kpis += [
            _kpi("Ventas netas", round(venta, 2), "moneda", "sin impuestos", variacion=_var(venta, venta_a)),
            _kpi("Costo de ventas", round(costo, 2), "moneda", variacion=_var(costo, costo_a)),
            _kpi("Margen bruto", round(margen, 2), "moneda", f"{margen_pct * 100:.1f} % de la venta".replace(".", ",") if margen_pct else None,
                 variacion=_var(margen, margen_a)),
        ]
        if hay_gastos:
            margen_op = _pct(resultado, venta)
            g.kpis += [
                _kpi("Gastos operativos", round(gasto_mes, 2), "moneda",
                     "estimado con el promedio de 3 meses (todavía sin asientos)" if estimado else "del mes"),
                _kpi("Resultado operativo", round(resultado, 2), "moneda",
                     (f"{margen_op * 100:.1f} % de la venta".replace(".", ",") if margen_op is not None else "") + " (aprox. EBITDA)",
                     "critico" if resultado < 0 else "ok"),
            ]
            if margen_pct and margen_pct > 0 and gasto_mes:
                equilibrio = gasto_mes / (margen / venta)  # con el margen sin redondear
                g.kpis.append(_kpi("Punto de equilibrio", round(equilibrio, 2), "moneda",
                                   f"venta necesaria para cubrir gastos; vas al {venta / equilibrio * 100:.0f} %".replace(".", ","),
                                   "ok" if venta >= equilibrio else "alerta"))
        else:
            self.falta("Resultado operativo (EBITDA) y punto de equilibrio", "no hay gastos operativos (tabla gastos)")
        # Crecimiento real contra el mismo mes del año anterior, descontando la inflación configurada
        desde_anterior = f"{int(mes[:4]) - 1}{self.desde[4:]}"
        primera_venta = self.uno("SELECT MIN(fecha) FROM ventas WHERE anulada = 0")
        cubierto = bool(primera_venta) and primera_venta[:10] <= desde_anterior  # el mes del año pasado tiene que estar completo
        hace_un_anio = self._venta_rango(desde_anterior, f"{int(mes[:4]) - 1}{self.hasta[4:]}") if cubierto else None
        inflacion = self.fin.get("inflacion_mensual")
        if hace_un_anio and hace_un_anio[0] and inflacion is not None:
            real = venta / (1 + inflacion) ** 12 / hace_un_anio[0] - 1
            g.kpis.append(_kpi("Crecimiento real (vs. año anterior)", round(real, 4), "porcentaje",
                               f"mismo mes del año pasado, descontando {inflacion * 100:.1f} % de inflación mensual".replace(".", ","),
                               "ok" if real >= 0 else "alerta"))
        presupuesto = self.uno(f"SELECT SUM(importe) FROM presupuesto WHERE mes = '{mes}' AND concepto = 'venta'")
        if presupuesto:
            dias_mes = int(_fin_de_mes(mes)[8:10])
            objetivo = presupuesto * self.p.dias / dias_mes
            g.kpis.append(_kpi("Cumplimiento del presupuesto", _pct(venta, objetivo), "porcentaje",
                               "de la venta presupuestada" + (" a la fecha" if self.p.en_curso else ""),
                               "ok" if venta >= objetivo else "alerta"))
        elif self.hay("presupuesto") is False:
            self.falta("Cumplimiento del presupuesto", "no hay presupuesto cargado (tabla presupuesto)")
        # Estado de resultados de 12 meses
        cobros = self._cobrado_por_mes(primer_mes)
        filas = []
        for k in range(12):
            m = _mes(primer_mes, k)
            v, c = ventas.get(m, (0.0, 0.0))
            gm = gastos.get(m) if hay_gastos else None
            filas.append([m + (" (en curso)" if m == self.hoy[:7] else ""), v, c, v - c, _pct(v - c, v), gm,
                          (v - c - gm) if gm is not None else None, cobros.get(m) if cobros is not None else None])
        g.paneles.append(_panel("Estado de resultados, últimos 12 meses",
                                ["Mes", "Ventas", "Costo", "Margen bruto", "Margen %", "Gastos", "Resultado", "Cobrado"],
                                ["t", "$", "$", "$", "%", "$", "$", "$"], filas[::-1], ancho=True))
        if hay_gastos and estimado and cats_prev:
            g.paneles.append(_panel("Gastos por categoría (promedio mensual de los últimos 3 meses)", ["Categoría", "Promedio mensual"],
                                    ["t", "$"], sorted([[c, v] for c, v in cats_prev.items()], key=lambda f: -f[1]),
                                    "Sin gastos en los últimos 3 meses."))
        elif hay_gastos and (cats_mes or cats_prev):
            cats = sorted(set(cats_mes) | set(cats_prev), key=lambda c: -(cats_mes.get(c, 0)))
            g.paneles.append(_panel("Gastos por categoría", ["Categoría", "Este mes", "Promedio 3 meses", "Variación"], ["t", "$", "$", "%"],
                                    [[c, cats_mes.get(c, 0), cats_prev.get(c, 0), _var(cats_mes.get(c, 0), cats_prev.get(c, 0))] for c in cats],
                                    "Todavía no hay gastos asentados este mes."))
        return g

    def _cobrado_por_mes(self, primer_mes: str) -> dict | None:
        filas = self.q(f"SELECT fecha, importe FROM cobranzas WHERE fecha >= '{primer_mes}-01' AND fecha <= '{self.hasta}'")
        if not filas:
            filas = self.q(f"SELECT fecha_cobro, importe FROM cxc WHERE fecha_cobro >= '{primer_mes}-01' AND fecha_cobro <= '{self.hasta}'")
        if filas is None:
            return None
        meses = defaultdict(float)
        for fecha, importe in filas:
            meses[fecha[:7]] += importe or 0
        return meses

    # --- 2. Cobranzas y crédito ------------------------------------------------------

    def cobranzas(self) -> Grupo | None:
        facturas = self.q("SELECT id, cliente_id, numero, fecha_emision, fecha_vencimiento, fecha_cobro, importe, saldo, vendedor_id FROM cxc")
        if facturas is None:
            return None
        if not facturas:
            self.falta("Cuentas por cobrar, riesgo de crédito y cobranza", "no hay facturas de clientes (tabla cxc)")
            return None
        g = Grupo("Cobranzas y crédito", "Deuda de clientes al día de hoy y cobranza del mes.")
        hoy = self.hoy
        abiertas = [f for f in facturas if f[7]]
        total = sum(f[7] for f in abiertas)
        tramos = {n: 0.0 for n, _, _ in TRAMOS}
        por_cliente = defaultdict(lambda: {"saldo": 0.0, "vencido": 0.0, "atraso_max": 0})
        for f in abiertas:
            atraso = _dias(hoy, f[4]) if f[4] else 0
            for nombre, d, h in TRAMOS:
                if (d is None and atraso <= 0) or (d is not None and atraso >= d and (h is None or atraso <= h)):
                    tramos[nombre] += f[7]
                    break
            c = por_cliente[f[1]]
            c["saldo"] += f[7]
            if atraso > 0:
                c["vencido"] += f[7]
                c["atraso_max"] = max(c["atraso_max"], atraso)
        vencida = total - tramos["Al día"]
        en_riesgo = tramos["61 a 90 días"] + tramos["Más de 90 días"]
        d90 = (self.p.hoy - timedelta(days=89)).isoformat()
        cobradas_90 = [f for f in facturas if f[5] and f[3] and d90 <= f[5][:10] <= hoy]
        dias_cobro = sum(_dias(f[5], f[3]) for f in cobradas_90) / len(cobradas_90) if cobradas_90 else None
        atraso_prom = sum(_dias(f[5], f[4]) for f in cobradas_90 if f[4]) / len(cobradas_90) if cobradas_90 else None
        venta_90 = self._venta_rango(d90, hoy)
        dso = round(total / (venta_90[0] / 90), 1) if venta_90 and venta_90[0] else None
        self.valores.update(cxc=total, dso=dso)
        # Efectividad de cobranza del mes: de lo que había para cobrar (vencido al inicio + lo que vencía en el mes), cuánto se cobró
        candidatas = [f for f in facturas if f[3] and f[3] < self.desde and f[4] and f[4] <= self.hasta
                      and (not f[5] or f[5][:10] >= self.desde)]
        cobradas = [f for f in candidatas if f[5] and self.desde <= f[5][:10] <= self.hasta]
        cei = _pct(sum(f[6] or 0 for f in cobradas), sum(f[6] or 0 for f in candidatas))
        cobrado = self.uno(f"SELECT SUM(importe) FROM cobranzas WHERE fecha >= '{self.desde}' AND fecha <= '{self.hasta}'")
        cobrado_a = self.uno(f"SELECT SUM(importe) FROM cobranzas WHERE fecha >= '{self.ant_desde}' AND fecha <= '{self.ant_hasta}'")
        if not cobrado:
            cobrado = sum(f[6] or 0 for f in facturas if f[5] and self.desde <= f[5][:10] <= self.hasta)
            cobrado_a = sum(f[6] or 0 for f in facturas if f[5] and self.ant_desde <= f[5][:10] <= self.ant_hasta)
        g.kpis += [
            _kpi("Deuda de clientes", round(total, 2), "moneda", "saldo a cobrar hoy"),
            _kpi("Deuda vencida", round(vencida, 2), "moneda", f"{(vencida / total * 100 if total else 0):.1f} % del total".replace(".", ","),
                 "critico" if total and vencida / total > 0.3 else ("alerta" if vencida else "ok")),
            _kpi("Deuda en riesgo", round(en_riesgo, 2), "moneda", "más de 60 días vencida", "critico" if en_riesgo else "ok"),
            _kpi("Cobrado en el mes", round(cobrado or 0, 2), "moneda", variacion=_var(cobrado or 0, cobrado_a or 0)),
            _kpi("Efectividad de cobranza", cei, "porcentaje", "de lo vencido y lo que vencía en el mes, cuánto se cobró",
                 None if cei is None else ("ok" if cei >= 0.85 else "alerta")),
            _kpi("DSO", dso, "dias", "días de venta en la calle"),
            _kpi("Días reales de cobro", round(dias_cobro, 1) if dias_cobro is not None else None, "dias", "facturas cobradas en 90 días"),
            _kpi("Atraso promedio", round(atraso_prom, 1) if atraso_prom is not None else None, "dias", "sobre el vencimiento",
                 "alerta" if atraso_prom and atraso_prom > 7 else None),
        ]
        g.antiguedad = [{"tramo": n, "saldo": round(v, 2)} for n, v in tramos.items()]
        clientes = {f[0]: f for f in (self.q("SELECT id, razon_social, limite_credito, condicion_pago_dias FROM clientes") or [])}
        nombre = lambda c: clientes.get(c, (c, f"Cliente {c}"))[1]  # noqa: E731
        historico = defaultdict(list)
        for f in facturas:
            if f[5] and f[4]:
                historico[f[1]].append(_dias(f[5], f[4]))
        # Límites de crédito excedidos
        excedidos = [[nombre(c), clientes[c][2], d["saldo"], _pct(d["saldo"], clientes[c][2])] for c, d in por_cliente.items()
                     if c in clientes and clientes[c][2] and d["saldo"] > clientes[c][2]]
        g.kpis.append(_kpi("Clientes sobre su límite", len(excedidos), "numero", "deben más que su límite de crédito",
                           "alerta" if excedidos else "ok"))
        # Riesgo de crédito por cliente (reglas simples y explicables)
        riesgo = []
        for c, d in por_cliente.items():
            prom = sum(historico[c]) / len(historico[c]) if historico[c] else None
            limite = clientes.get(c, (None, None, None))[2]
            uso = _pct(d["saldo"], limite) if limite else None
            motivos = []
            if d["atraso_max"] > 60:
                motivos.append(f"vencido hace {d['atraso_max']} días")
            if uso and uso > 1.2:
                motivos.append(f"usa {uso * 100:.0f} % del límite")
            if prom and prom > 30:
                motivos.append(f"paga con {prom:.0f} días de atraso")
            nivel = "Alto" if motivos else ("Medio" if d["atraso_max"] > 15 or (prom and prom > 10) or (uso and uso > 1) else "Bajo")
            if nivel != "Bajo":
                if not motivos:
                    motivos.append(f"atraso de {d['atraso_max']} días" if d["atraso_max"] > 15 else f"atraso habitual {prom or 0:.0f} días")
                riesgo.append([nombre(c), nivel, d["saldo"], d["vencido"], d["atraso_max"], round(prom, 1) if prom is not None else None,
                               "; ".join(motivos)])
        riesgo.sort(key=lambda r: (r[1] != "Alto", -r[3]))
        g.kpis.append(_kpi("Clientes de riesgo alto", sum(1 for r in riesgo if r[1] == "Alto"), "numero",
                           "vencidos más de 60 días, sobre el límite o que pagan muy tarde",
                           "critico" if any(r[1] == "Alto" for r in riesgo) else "ok"))
        g.deudores = [{"cliente": nombre(c), "vencido": round(d["vencido"], 2), "dias_max_atraso": d["atraso_max"]}
                      for c, d in sorted(por_cliente.items(), key=lambda x: -x[1]["vencido"]) if d["vencido"]][:10]
        g.paneles.append(_panel("Riesgo de crédito por cliente", ["Cliente", "Riesgo", "Saldo", "Vencido", "Días de atraso", "Atraso habitual", "Motivo"],
                                ["t", "t", "$", "$", "n", "n", "t"], riesgo[:15], "Ningún cliente con riesgo medio o alto.", ancho=True))
        # Agenda de cobranza: lo vencido y lo que vence en 7 días, priorizado por importe y atraso
        semana = (self.p.hoy + timedelta(days=7)).isoformat()
        vendedores = {f[0]: f[1] for f in (self.q("SELECT id, nombre FROM vendedores") or [])}
        agenda = [[nombre(f[1]), f[2] or f[0], f[4], max(0, _dias(hoy, f[4])), f[7], vendedores.get(f[8], "")]
                  for f in abiertas if f[4] and f[4] <= semana]
        agenda.sort(key=lambda a: -(a[4] * (1 + a[3] / 30)))
        g.paneles.append(_panel("Agenda de cobranza (vencido y próximos 7 días)", ["Cliente", "Factura", "Vence", "Días de atraso", "Saldo", "Vendedor"],
                                ["t", "t", "t", "n", "$", "t"], agenda[:20], "No hay nada vencido ni por vencer esta semana.", ancho=True))
        if excedidos:
            g.paneles.append(_panel("Clientes sobre su límite de crédito", ["Cliente", "Límite", "Saldo", "Uso"], ["t", "$", "$", "%"],
                                    sorted(excedidos, key=lambda e: -e[3])))
        medios = self.q(f"SELECT medio, SUM(importe), COUNT(*) FROM cobranzas WHERE fecha >= '{self.desde}' AND fecha <= '{self.hasta}' GROUP BY medio")
        if medios:
            g.paneles.append(_panel("Cobranzas del mes por medio de pago", ["Medio", "Importe", "Cantidad"], ["t", "$", "n"],
                                    sorted([[m[0] or "Sin dato", m[1], m[2]] for m in medios], key=lambda f: -(f[1] or 0))))
        elif self.hay("cobranzas") is False:
            self.falta("Cobranzas por medio de pago", "no hay cobranzas registradas (tabla cobranzas)")
        cheques = self.q("SELECT tipo, estado, SUM(importe), COUNT(*) FROM cheques GROUP BY tipo, estado")
        if cheques:
            ch = {(f[0], f[1]): (f[2] or 0, f[3]) for f in cheques}
            cartera, rechazados = ch.get(("recibido", "cartera"), (0, 0)), ch.get(("recibido", "rechazado"), (0, 0))
            g.kpis += [_kpi("Cheques en cartera", round(cartera[0], 2), "moneda", _n(cartera[1], "cheque", "cheques")),
                       _kpi("Cheques rechazados", round(rechazados[0], 2), "moneda", _n(rechazados[1], "cheque", "cheques"),
                            "critico" if rechazados[1] else "ok")]
            proximos = self.q(f"""SELECT fecha_cobro, banco, importe FROM cheques WHERE tipo = 'recibido' AND estado = 'cartera'
                                  AND fecha_cobro >= '{hoy}' ORDER BY fecha_cobro""") or []
            if proximos:
                g.paneles.append(_panel("Cheques en cartera por fecha de cobro", ["Fecha de cobro", "Banco", "Importe"], ["t", "t", "$"], proximos[:15]))
        elif cheques is not None:
            self.falta("Cheques en cartera y rechazados", "no hay cheques (tabla cheques)")
        return g

    # --- 3. Pagos a proveedores -------------------------------------------------------

    def pagos(self) -> Grupo | None:
        cxp = self.q("SELECT x.proveedor_id, x.numero, x.fecha_emision, x.fecha_vencimiento, x.importe, x.saldo, x.tipo FROM cxp x")
        if cxp is None:
            return None
        if not cxp:
            self.falta("Cuentas por pagar, DPO y agenda de pagos", "no hay facturas de proveedores (tabla cxp)")
            return None
        g = Grupo("Pagos a proveedores", "Deuda con proveedores al día de hoy y pagos del mes.")
        hoy = self.hoy
        abiertas = [f for f in cxp if f[5]]
        total = sum(f[5] for f in abiertas)
        vencida = sum(f[5] for f in abiertas if f[3] and f[3] < hoy)
        semana = (self.p.hoy + timedelta(days=7)).isoformat()
        mes = (self.p.hoy + timedelta(days=30)).isoformat()
        d90 = (self.p.hoy - timedelta(days=89)).isoformat()
        compras_90 = sum(f[4] or 0 for f in cxp if f[6] != "nota_credito" and f[2] and d90 <= f[2] <= hoy)
        dpo = round(total / (compras_90 / 90), 1) if compras_90 else None
        pagado = self.uno(f"SELECT SUM(importe) FROM pagos WHERE fecha >= '{self.desde}' AND fecha <= '{self.hasta}'")
        pagado_a = self.uno(f"SELECT SUM(importe) FROM pagos WHERE fecha >= '{self.ant_desde}' AND fecha <= '{self.ant_hasta}'")
        self.valores.update(cxp=total, dpo=dpo)
        g.kpis += [
            _kpi("Deuda con proveedores", round(total, 2), "moneda", "saldo a pagar hoy"),
            _kpi("Vencida", round(vencida, 2), "moneda", None, "alerta" if vencida else "ok"),
            _kpi("A pagar en 7 días", round(sum(f[5] for f in abiertas if f[3] and hoy <= f[3] <= semana), 2), "moneda"),
            _kpi("A pagar en 30 días", round(sum(f[5] for f in abiertas if f[3] and hoy <= f[3] <= mes), 2), "moneda"),
            _kpi("DPO", dpo, "dias", "días de compras que se deben"),
        ]
        if pagado is not None:
            g.kpis.append(_kpi("Pagado en el mes", round(pagado or 0, 2), "moneda", variacion=_var(pagado or 0, pagado_a or 0)))
        nombres = {f[0]: f[1] for f in (self.q("SELECT id, nombre FROM proveedores") or [])}
        prox = sorted([[nombres.get(f[0], f"Proveedor {f[0]}"), f[1], f[3], f[5], "vencida" if f[3] and f[3] < hoy else ""]
                       for f in abiertas], key=lambda f: f[2] or "")
        g.paneles.append(_panel("Próximos pagos a proveedores", ["Proveedor", "Factura", "Vence", "Saldo", ""], ["t", "t", "t", "$", "t"],
                                prox[:15], "No hay facturas de proveedores pendientes."))
        por_prov = defaultdict(float)
        for f in abiertas:
            por_prov[nombres.get(f[0], f"Proveedor {f[0]}")] += f[5]
        g.paneles.append(_panel("Deuda por proveedor", ["Proveedor", "Saldo"], ["t", "$"],
                                sorted([[k, v] for k, v in por_prov.items()], key=lambda f: -f[1])[:10]))
        return g

    # --- 4. Tesorería --------------------------------------------------------------------

    def tesoreria(self) -> Grupo | None:
        cuentas = self.q("SELECT nombre, tipo, moneda, saldo FROM cuentas_bancarias ORDER BY saldo DESC")
        if cuentas is None:
            return None
        if not cuentas:
            self.falta("Saldo de caja, semanas de cobertura y flujo de 13 semanas", "no hay saldos de bancos ni cajas (tabla cuentas_bancarias)")
            return None
        g = Grupo("Tesorería", "Caja disponible y proyección de 13 semanas.")
        caja = sum(c[3] or 0 for c in cuentas)
        self.valores["caja"] = caja
        d90 = (self.p.hoy - timedelta(days=89)).isoformat()
        egresos_90 = (self.uno(f"SELECT SUM(importe) FROM pagos WHERE fecha >= '{d90}' AND fecha <= '{self.hoy}'") or 0) + \
                     (self.uno(f"SELECT SUM(importe) FROM gastos WHERE fecha >= '{d90}' AND fecha <= '{self.hoy}'") or 0)
        semanas = round(caja / (egresos_90 / 90 * 7), 1) if egresos_90 else None
        g.kpis += [_kpi("Caja y bancos", round(caja, 2), "moneda", "saldo contable hoy", "critico" if caja < 0 else None),
                   _kpi("Semanas de cobertura", semanas, "numero", "semanas de pagos y gastos que cubre la caja",
                        None if semanas is None else ("alerta" if semanas < 4 else "ok"))]
        flujo = flujo_13_semanas(self.u, self.p.hoy, caja)
        if flujo:
            minimo = min(flujo, key=lambda s: s["saldo_final"])
            caja_minima = self.fin.get("caja_minima") or 0
            margen = minimo["saldo_final"] - caja_minima
            g.kpis.append(_kpi("Punto más bajo (13 semanas)", round(minimo["saldo_final"], 2), "moneda",
                               f"semana del {minimo['desde']}, estimado", "critico" if minimo["saldo_final"] < 0 else None))
            g.kpis.append(_kpi("Faltante de caja" if margen < 0 else "Excedente de caja", round(abs(margen), 2), "moneda",
                               f"contra la caja mínima de $ {caja_minima:,.0f}".replace(",", "."), "critico" if margen < 0 else "ok"))
            g.paneles.append(_panel("Flujo de caja estimado, 13 semanas", ["Semana del", "Cobros", "Pagos a proveedores", "Gastos", "Saldo final"],
                                    ["t", "$", "$", "$", "$"],
                                    [[s["desde"], s["cobros"], s["pagos"], s["gastos"], s["saldo_final"]] for s in flujo], ancho=True))
        g.paneles.append(_panel("Bancos y cajas", ["Cuenta", "Tipo", "Moneda", "Saldo"], ["t", "t", "t", "$"], cuentas))
        prestamos = self.q("SELECT entidad, moneda, saldo, cuota_importe, proximo_vencimiento FROM prestamos")
        if prestamos:
            g.kpis.append(_kpi("Deuda financiera", round(sum(p[2] or 0 for p in prestamos), 2), "moneda", _n(len(prestamos), "préstamo", "préstamos")))
            g.paneles.append(_panel("Préstamos", ["Entidad", "Moneda", "Saldo", "Cuota", "Próximo vencimiento"], ["t", "t", "$", "$", "t"], prestamos))
        elif prestamos is not None:
            self.falta("Deuda financiera", "no hay préstamos cargados (tabla prestamos)")
        return g

    # --- 5. Capital de trabajo y salud -----------------------------------------------------

    def capital_de_trabajo(self) -> Grupo | None:
        cxc, cxp, caja = self.valores.get("cxc"), self.valores.get("cxp"), self.valores.get("caja")
        if cxc is None and cxp is None:
            return None
        g = Grupo("Capital de trabajo y salud financiera", "Cuánta plata queda inmovilizada en la operación y si alcanza para pagar lo corriente.")
        inventario = self.uno("SELECT SUM(s.cantidad * p.costo) FROM stock s JOIN productos p ON p.id = s.producto_id WHERE s.cantidad > 0")
        d90 = (self.p.hoy - timedelta(days=89)).isoformat()
        costo_90 = self._venta_rango(d90, self.hoy)
        dio = round(inventario / (costo_90[1] / 90), 1) if inventario and costo_90 and costo_90[1] else None
        dso, dpo = self.valores.get("dso"), self.valores.get("dpo")
        if None not in (dso, dio, dpo):
            ciclo = round(dso + dio - dpo, 1)
            g.kpis.append(_kpi("Ciclo de conversión de caja", ciclo, "dias", f"{dso:.0f} de cobro + {dio:.0f} de stock − {dpo:.0f} de pago".replace(".", ","),
                               "alerta" if ciclo > 60 else "ok"))
        g.kpis += [_kpi("Días de inventario (DIO)", dio, "dias", "al ritmo de venta de 90 días")]
        impuestos = self.uno("SELECT SUM(importe) FROM impuestos WHERE estado = 'pendiente'") or 0
        cuotas = self.uno("SELECT SUM(CASE WHEN cuota_importe * 12 < saldo THEN cuota_importe * 12 ELSE saldo END) FROM prestamos") or 0
        activo = (caja or 0) + (cxc or 0) + (inventario or 0)
        pasivo = (cxp or 0) + impuestos + cuotas
        g.kpis.append(_kpi("Capital de trabajo", round(activo - pasivo, 2), "moneda", "caja + a cobrar + stock − a pagar en el año",
                           "critico" if activo - pasivo < 0 else "ok"))
        if pasivo:
            liquidez = round(activo / pasivo, 2)
            g.kpis.append(_kpi("Liquidez corriente", liquidez, "veces", "activo corriente sobre pasivo corriente (sano: más de 1,5)",
                               "critico" if liquidez < 1 else ("alerta" if liquidez < 1.5 else "ok")))
        g.paneles.append(_panel("Composición del capital de trabajo", ["Concepto", "Importe"], ["t", "$"],
                                [["Caja y bancos", caja], ["Cuentas a cobrar", cxc], ["Inventario a costo", inventario],
                                 ["Cuentas a pagar", -(cxp or 0)], ["Impuestos pendientes", -impuestos],
                                 ["Cuotas de préstamos (12 meses)", -cuotas]]))
        monedas = self.q("""SELECT moneda, SUM(saldo) FROM cxc WHERE saldo <> 0 AND moneda IS NOT NULL GROUP BY moneda""") or []
        monedas_p = {m[0]: m[1] for m in (self.q("SELECT moneda, SUM(saldo) FROM cxp WHERE saldo <> 0 AND moneda IS NOT NULL GROUP BY moneda") or [])}
        todas = sorted({m[0] for m in monedas} | set(monedas_p))
        if len(todas) > 1:
            cobrar = {m[0]: m[1] for m in monedas}
            g.paneles.append(_panel("Saldos por moneda", ["Moneda", "A cobrar", "A pagar", "Posición neta"], ["t", "$", "$", "$"],
                                    [[m, cobrar.get(m, 0), monedas_p.get(m, 0), cobrar.get(m, 0) - monedas_p.get(m, 0)] for m in todas]))
        return g

    # --- 6. Impuestos ----------------------------------------------------------------------

    def impuestos(self) -> Grupo | None:
        filas = self.q("SELECT impuesto, periodo, vencimiento, importe, estado FROM impuestos ORDER BY periodo DESC")
        if filas is None:
            return None
        if not filas:
            self.falta("Impuestos a pagar y vencimientos", "no hay impuestos registrados (tabla impuestos)")
            return None
        g = Grupo("Impuestos")
        pendientes = [f for f in filas if f[4] == "pendiente"]
        proximo = min((f[2] for f in pendientes if f[2]), default=None)
        vencido = bool(proximo) and proximo < self.hoy
        g.kpis += [_kpi("Impuestos pendientes", round(sum(f[3] or 0 for f in pendientes), 2), "moneda",
                        (f"venció el {proximo}" if vencido else f"próximo vencimiento {proximo}") if proximo else None,
                        "critico" if vencido else None),
                   _kpi("Impuestos del último período", round(sum(f[3] or 0 for f in filas if f[1] == filas[0][1]), 2), "moneda",
                        f"período {filas[0][1]}")]
        g.paneles.append(_panel("Impuestos por período", ["Impuesto", "Período", "Vence", "Importe", "Estado"], ["t", "t", "t", "$", "t"], filas[:12]))
        return g

    # --- 7. Controles y alertas --------------------------------------------------------------

    def controles(self) -> Grupo | None:
        if self.hay("cxc") is None:  # los controles financieros son para quien ve las finanzas
            return None
        alertas = []

        def alerta(nivel, texto, cantidad=None, importe=None):
            alertas.append([nivel, texto, cantidad, importe])

        d, h = self.desde, self.hasta
        duplicadas = self.q("""SELECT cliente_id, fecha_emision, importe, COUNT(*) FROM cxc WHERE tipo <> 'nota_credito' OR tipo IS NULL
                               GROUP BY cliente_id, fecha_emision, importe HAVING COUNT(*) > 1""")
        if duplicadas:
            alerta("Revisar", "Facturas de cliente posiblemente duplicadas (mismo cliente, fecha e importe)",
                   sum(f[3] - 1 for f in duplicadas), sum((f[3] - 1) * (f[2] or 0) for f in duplicadas))
        venta = self.valores.get("venta_mes") or (self._venta_rango(d, h) or (0, 0))[0]
        notas = self.uno(f"SELECT SUM(importe) FROM devoluciones WHERE fecha >= '{d}' AND fecha <= '{h}'")
        if notas and venta and notas / venta > 0.05:
            alerta("Atención", f"Notas de crédito altas: {notas / venta * 100:.1f} % de la venta del mes".replace(".", ","), None, notas)
        anuladas = self.q(f"""SELECT COUNT(DISTINCT v.id), SUM(l.cantidad * l.precio_unitario) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
                              WHERE v.anulada = 1 AND v.fecha >= '{d}' AND v.fecha <= '{h}'""")
        if anuladas and anuladas[0][0]:
            alerta("Info", "Ventas anuladas en el mes", anuladas[0][0], anuladas[0][1])
        descuentos = self.q(f"""SELECT COUNT(*), SUM(l.cantidad * l.precio_lista * l.descuento_pct) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
                                WHERE v.anulada = 0 AND v.fecha >= '{d}' AND v.fecha <= '{h}' AND l.descuento_pct > 0.2""")
        if descuentos and descuentos[0][0]:
            alerta("Revisar", "Líneas con descuento mayor al 20 %", descuentos[0][0], descuentos[0][1])
        bajo_costo = self.q(f"""SELECT COUNT(*), SUM(l.cantidad * (l.costo_unitario - l.precio_unitario)) FROM ventas v
                                JOIN ventas_lineas l ON l.venta_id = v.id
                                WHERE v.anulada = 0 AND v.fecha >= '{d}' AND v.fecha <= '{h}' AND l.precio_unitario < l.costo_unitario""")
        if bajo_costo and bajo_costo[0][0]:
            alerta("Atención", "Ventas por debajo del costo", bajo_costo[0][0], bajo_costo[0][1])
        sin_factura = self.q(f"SELECT COUNT(*), SUM(importe) FROM pagos WHERE cxp_id IS NULL AND fecha >= '{d}' AND fecha <= '{h}'")
        if sin_factura and sin_factura[0][0]:
            alerta("Revisar", "Pagos a proveedores sin factura asociada", sin_factura[0][0], sin_factura[0][1])
        morosos = self.q(f"""SELECT COUNT(DISTINCT v.cliente_id) FROM ventas v WHERE v.anulada = 0 AND v.fecha >= '{d}' AND v.fecha <= '{h}'
                             AND v.cliente_id IN (SELECT cliente_id FROM cxc WHERE saldo > 0 AND fecha_vencimiento <
                             '{(self.p.hoy - timedelta(days=60)).isoformat()}')""")
        if morosos and morosos[0][0]:
            alerta("Atención", "Clientes con deuda vencida hace más de 60 días que siguieron comprando en el mes", morosos[0][0])
        rechazados = self.q("SELECT COUNT(*), SUM(importe) FROM cheques WHERE estado = 'rechazado'")
        if rechazados and rechazados[0][0]:
            alerta("Atención", "Cheques rechazados sin resolver", rechazados[0][0], rechazados[0][1])
        if not alertas and duplicadas is None and anuladas is None:
            return None
        g = Grupo("Controles y alertas", "Situaciones para revisar: posibles errores de carga, pérdidas o riesgos.")
        g.kpis.append(_kpi("Alertas para revisar", len(alertas), "numero", None, "alerta" if alertas else "ok"))
        g.paneles.append(_panel("Alertas", ["Nivel", "Qué pasa", "Cantidad", "Importe"], ["t", "t", "n", "$"], alertas,
                                "No se encontraron situaciones para revisar.", ancho=True))
        return g


def finanzas(usuario: Usuario, p) -> dict:
    f = Finanzas(usuario, p)
    grupos, antiguedad, deudores = [], [], []
    for metodo in (f.resultados, f.cobranzas, f.pagos, f.tesoreria, f.capital_de_trabajo, f.impuestos, f.controles):
        try:
            g = metodo()
        except Exception:  # un grupo que no se puede calcular se omite; el resto se muestra
            g = None
        if g:
            antiguedad = getattr(g, "antiguedad", antiguedad)
            deudores = getattr(g, "deudores", deudores)
            grupos.append(g.a_dict())
    f.falta("Costo de medios de pago", "no hay comisiones de tarjetas ni de procesadores de pago en el modelo")
    if not grupos:
        return {"sin_acceso": True, "mensaje": "Tu perfil no tiene acceso a los datos financieros.", "faltan": f.faltan}
    return {"grupos": grupos, "antiguedad": antiguedad, "deudores": deudores, "faltan": f.faltan}
