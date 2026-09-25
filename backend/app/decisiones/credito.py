"""Centro de Decisiones — simulador de crédito a clientes.

Responde: "¿Hasta cuántos clientes más puedo financiar a N días? ¿Es rentable?
¿Me deja sin caja?" con las tres pruebas: rentabilidad, caja y riesgo.

Todo el cálculo es determinista y probado. El modelo de IA solo obtiene los
parámetros del ERP, llama a esta función y explica el resultado.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace

DIAS_MES = 30


def _m(x: float) -> str:
    """Importe con formato rioplatense: 1.234.567"""
    return f"${x:,.0f}".replace(",", ".")


def _p(x: float) -> str:
    """Porcentaje con coma decimal: 13,9 %"""
    return f"{x * 100:.1f}".replace(".", ",") + " %"


@dataclass
class ParametrosCredito:
    compra_mensual_cliente: float          # venta mensual esperada por cliente nuevo
    margen_bruto: float                    # 0.22 = 22 %
    dias_cobro_reales: float               # plazo pactado + atraso real de clientes similares
    dias_inventario: float
    dias_pago_proveedores: float
    costo_servir: float                    # % de la venta (reparto, visitas)
    incobrabilidad: float                  # % de la venta
    costo_dinero_mensual: float            # tasa mensual del descubierto o préstamo
    punto_mas_bajo_caja: float             # mínimo de la proyección de 13 semanas SIN la decisión
    caja_minima: float                     # política de caja mínima de seguridad
    descubierto_disponible: float = 0.0
    clientes_solicitados: int | None = None
    # Escenario pesimista (ajustes sobre el escenario base)
    pesimista_dias_cobro_extra: float = 15
    pesimista_incobrabilidad_factor: float = 2.0
    pesimista_baja_caja: float = 700_000


@dataclass
class ResultadoEscenario:
    caja_inmovilizada_por_cliente: float
    cuentas_por_cobrar: float
    inventario: float
    deuda_proveedores: float
    resultado_mensual_por_cliente: float
    retorno_mensual: float
    meses_recupero: float | None
    max_clientes_sin_descubierto: int
    max_clientes_con_descubierto: int


@dataclass
class ResultadoCredito:
    veredicto: str
    limite_base: int
    limite_seguro_pesimista: int
    usa_descubierto_base: bool
    pruebas: dict
    base: ResultadoEscenario
    pesimista: ResultadoEscenario
    tabla_clientes: list[dict]
    palancas: list[dict]
    punto_quiebre_incobrabilidad: float
    exposicion_maxima_por_cliente: float
    condiciones: list[str]
    senales_de_frenado: list[str]
    supuestos: dict = field(default_factory=dict)

    def a_dict(self) -> dict:
        return asdict(self)


def _max_clientes(margen_caja: float, caja_por_cliente: float) -> int:
    if caja_por_cliente <= 0:
        return 10**6
    return max(0, math.floor(margen_caja / caja_por_cliente + 1e-9))


def _escenario(p: ParametrosCredito) -> ResultadoEscenario:
    venta_diaria = p.compra_mensual_cliente / DIAS_MES
    costo_diario = venta_diaria * (1 - p.margen_bruto)

    cxc = venta_diaria * p.dias_cobro_reales
    inventario = costo_diario * p.dias_inventario
    proveedores = costo_diario * p.dias_pago_proveedores
    caja = cxc + inventario - proveedores

    margen = p.compra_mensual_cliente * p.margen_bruto
    resultado = (
        margen
        - p.compra_mensual_cliente * p.costo_servir
        - p.compra_mensual_cliente * p.incobrabilidad
        - caja * p.costo_dinero_mensual
    )
    holgura = p.punto_mas_bajo_caja - p.caja_minima
    return ResultadoEscenario(
        caja_inmovilizada_por_cliente=round(caja, 2),
        cuentas_por_cobrar=round(cxc, 2),
        inventario=round(inventario, 2),
        deuda_proveedores=round(proveedores, 2),
        resultado_mensual_por_cliente=round(resultado, 2),
        retorno_mensual=round(resultado / caja, 4) if caja > 0 else float("inf"),
        meses_recupero=round(caja / resultado, 1) if resultado > 0 else None,
        max_clientes_sin_descubierto=_max_clientes(holgura, caja),
        max_clientes_con_descubierto=_max_clientes(holgura + p.descubierto_disponible, caja),
    )


def _pesimista(p: ParametrosCredito) -> ParametrosCredito:
    return replace(
        p,
        dias_cobro_reales=p.dias_cobro_reales + p.pesimista_dias_cobro_extra,
        incobrabilidad=p.incobrabilidad * p.pesimista_incobrabilidad_factor,
        punto_mas_bajo_caja=p.punto_mas_bajo_caja - p.pesimista_baja_caja,
    )


def simular(p: ParametrosCredito) -> ResultadoCredito:
    base = _escenario(p)
    pes = _escenario(_pesimista(p))

    rentable = base.resultado_mensual_por_cliente > 0 and base.retorno_mensual > p.costo_dinero_mensual
    rentable_pes = pes.resultado_mensual_por_cliente > 0

    # Límite: máximo que pasa la prueba de caja (con descubierto como último recurso)
    limite_base = base.max_clientes_con_descubierto if rentable else 0
    usa_descubierto = limite_base > base.max_clientes_sin_descubierto
    limite_seguro = pes.max_clientes_con_descubierto if rentable_pes else 0

    # Punto de quiebre de rentabilidad: incobrabilidad que lleva el resultado a cero
    quiebre = (
        p.margen_bruto - p.costo_servir
        - base.caja_inmovilizada_por_cliente * p.costo_dinero_mensual / p.compra_mensual_cliente
    )

    tabla = []
    holgura = p.punto_mas_bajo_caja - p.caja_minima
    tope = max(limite_base + 2, (p.clientes_solicitados or 0), 3)
    for n in range(1, tope + 1):
        caja_n = n * base.caja_inmovilizada_por_cliente
        punto_bajo = p.punto_mas_bajo_caja - caja_n
        necesita_desc = max(0.0, caja_n - holgura)
        if necesita_desc == 0:
            estado = "Pasa"
        elif necesita_desc <= p.descubierto_disponible:
            estado = f"Pasa usando {_m(necesita_desc)} de descubierto"
        else:
            estado = "No pasa: supera la caja mínima y el descubierto disponible"
        tabla.append({
            "clientes": n,
            "caja_inmovilizada": round(caja_n, 2),
            "punto_mas_bajo_caja": round(punto_bajo, 2),
            "resultado_mensual": round(n * base.resultado_mensual_por_cliente, 2),
            "estado": estado,
        })

    # Palancas: qué pasa si se cobra en término y si se estira el pago a proveedores
    palancas = []
    for nombre, cambios in [
        ("Situación actual", {}),
        ("Cobrar en el plazo pactado (sin atraso)", {"dias_cobro_reales": DIAS_MES}),
        ("Además, pagar a proveedores a 30 días", {"dias_cobro_reales": DIAS_MES, "dias_pago_proveedores": 30}),
    ]:
        esc = _escenario(replace(p, **cambios))
        palancas.append({
            "palanca": nombre,
            "caja_por_cliente": esc.caja_inmovilizada_por_cliente,
            "clientes_sin_descubierto": esc.max_clientes_sin_descubierto,
            "clientes_con_descubierto": esc.max_clientes_con_descubierto,
        })

    pide = p.clientes_solicitados
    if not rentable:
        veredicto = "NO"
    elif limite_base == 0:
        veredicto = "NO"
    elif pide is not None and pide <= base.max_clientes_sin_descubierto and pide <= limite_seguro:
        veredicto = "SÍ"
    else:
        veredicto = "SÍ CON CONDICIONES"

    pruebas = {
        "rentabilidad": {
            "pasa": rentable,
            "detalle": (
                f"Cada cliente deja {_m(base.resultado_mensual_por_cliente)} por mes; "
                f"retorno {_p(base.retorno_mensual)} mensual vs costo del dinero {_p(p.costo_dinero_mensual)}."
            ),
        },
        "caja": {
            "pasa": limite_base > 0,
            "detalle": (
                f"Cada cliente inmoviliza {_m(base.caja_inmovilizada_por_cliente)}. "
                f"Entran {base.max_clientes_sin_descubierto} sin descubierto y "
                f"{base.max_clientes_con_descubierto} usándolo."
            ),
        },
        "riesgo": {
            "pasa": limite_seguro > 0,
            "detalle": (
                f"En el escenario pesimista entran {limite_seguro}. "
                f"Deja de ser rentable con incobrabilidad mayor a {_p(quiebre)}. "
                f"Pérdida máxima si un cliente no paga: {_m(base.cuentas_por_cobrar)}."
            ),
        },
    }

    condiciones = [
        "Incorporar un cliente por mes para medir el comportamiento de pago real.",
        f"Límite de crédito inicial de {_m(p.compra_mensual_cliente)} (un mes de compra) por cliente.",
        "Primeros 2 pedidos a 15 días; pasar al plazo completo después de dos pagos puntuales.",
        "Bloqueo automático de pedidos con más de 15 días de atraso.",
        "Priorizar clientes con buen puntaje de riesgo y consultar información crediticia externa.",
    ]
    senales = [
        f"Días reales de cobro de clientes nuevos por encima de {p.dias_cobro_reales:.0f}.",
        f"Punto más bajo de caja proyectado por debajo de {_m(p.caja_minima * 1.2)}.",
        f"Incobrabilidad de clientes nuevos por encima de {_p(min(p.incobrabilidad * 2.5, quiebre))}.",
    ]

    return ResultadoCredito(
        veredicto=veredicto,
        limite_base=limite_base,
        limite_seguro_pesimista=limite_seguro,
        usa_descubierto_base=usa_descubierto,
        pruebas=pruebas,
        base=base,
        pesimista=pes,
        tabla_clientes=tabla,
        palancas=palancas,
        punto_quiebre_incobrabilidad=round(quiebre, 4),
        exposicion_maxima_por_cliente=base.cuentas_por_cobrar,
        condiciones=condiciones,
        senales_de_frenado=senales,
        supuestos=asdict(p),
    )
