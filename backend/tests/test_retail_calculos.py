"""Retail · cálculos de las secciones 6, 7, 10 y 11 contra cuentas hechas a mano (incluye los casos de borde de la sección 18:
producto nuevo sin historial, stock negativo, ventas con devoluciones, producto sin costo, proveedor sin días configurados)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.retail import calculos as C

HOY = date(2026, 9, 24)   # jueves


def dias_atras(n):
    return HOY - timedelta(days=n)


def test_vpd_excluye_dias_sin_stock():
    # 28 días: 10 sin stock (sin ventas y cierre en 0), 18 con 5 unidades por día → VPD = 90 / 18 = 5 (no 90 / 28 = 3,21).
    ventas, cierre = {}, {}
    for i in range(1, 29):
        d = dias_atras(i)
        if 5 <= i <= 14:
            cierre[d] = 0
        else:
            ventas[d] = 5
            cierre[d] = 20
    sin = C.dias_sin_stock(ventas, cierre, dias_atras(28), dias_atras(1))
    assert len(sin) == 10
    r = C.venta_promedio_diaria(ventas, sin, HOY)
    assert r.vpd == pytest.approx(5.0) and r.dias_con_stock == 18 and r.dias_sin_stock == 10 and r.confianza == "normal"


def test_dia_con_ventas_siempre_tuvo_stock():
    d = dias_atras(1)
    assert C.dias_sin_stock({d: 2}, {d: 0}, d, d) == set()        # vendió y quedó en 0: ese día hubo stock
    assert C.dias_sin_stock({}, {d - timedelta(days=1): 0, d: 5}, d, d) == {d}   # arrancó sin stock y no vendió


def test_producto_nuevo_usa_referencia_con_baja_confianza():
    ventas = {dias_atras(i): 2 for i in range(1, 4)}               # 3 días de historia, 2 por día
    r = C.venta_promedio_diaria(ventas, set(), HOY, referencia=9.0, desde_alta=dias_atras(3))
    # mezcla: propio 2 con peso 3/7, referencia 9 con peso 4/7 → 6
    assert r.confianza == "baja" and r.usa_referencia and r.vpd == pytest.approx(2 * 3 / 7 + 9 * 4 / 7)
    sin_ref = C.venta_promedio_diaria(ventas, set(), HOY, desde_alta=dias_atras(3))
    assert sin_ref.vpd == pytest.approx(2.0) and sin_ref.confianza == "baja"
    assert C.venta_promedio_diaria({}, set(), HOY, desde_alta=HOY).vpd == 0


def test_devoluciones_restan():
    ventas = {dias_atras(i): 3 for i in range(1, 29)}
    ventas[dias_atras(2)] = -3 + 3                                # devolvieron lo vendido ese día
    r = C.venta_promedio_diaria(ventas, set(), HOY)
    assert r.unidades == pytest.approx(81) and r.vpd == pytest.approx(81 / 28)


def test_horizonte_con_calculo_manual():
    # Proveedor lunes y jueves, demora 2. Hoy martes: se pide el jueves (2 días), llega el sábado (4);
    # lo pedido tiene que durar hasta que llegue el pedido del lunes siguiente (2 + 4 + 2 = 8).
    h = C.horizonte(date(2026, 9, 22), [0, 3], 2)
    assert (h.proxima_oportunidad, h.llegada_proxima, h.horizonte) == (2, 4, 8)
    # Hoy jueves (día de visita): se pide hoy, llega el sábado, el siguiente pedido es el lunes → 0 + 4 + 2 = 6
    h = C.horizonte(HOY, [0, 3], 2)
    assert (h.proxima_oportunidad, h.llegada_proxima, h.horizonte) == (0, 2, 6)


def test_proveedor_sin_dias_configurados():
    h = C.horizonte(HOY, [], None)
    assert h.horizonte == C.DIAS_REVISION_SIN_VISITA + C.DEMORA_SIN_DATO and "no tiene días de visita" in h.supuesto


def test_cantidad_sugerida_con_calculo_manual():
    # 48 de pronóstico + 6 de seguridad − 10 disponibles − 4 en tránsito − 12 ya pedidas = 28 → bultos de 12 → 36
    s = C.cantidad_sugerida(48, 6, 10, 4, 12, unidades_por_bulto=12)
    assert s.necesidad == pytest.approx(28) and s.cantidad == 36
    # con múltiplo de compra 2 bultos (24 u.) → 48
    assert C.cantidad_sugerida(48, 6, 10, 4, 12, unidades_por_bulto=12, multiplo_compra=2).cantidad == 48
    # máximo 50: tope = 50 − 10 − 4 − 12 = 24 → 24 (dos bultos), marcada como recortada
    s = C.cantidad_sugerida(48, 6, 10, 4, 12, unidades_por_bulto=12, stock_maximo=50)
    assert s.cantidad == 24 and s.recortada_por_maximo
    # ≤ 0: no se compra
    assert C.cantidad_sugerida(10, 2, 30, 0, 0, 6).cantidad == 0


def test_stock_negativo_se_toma_como_cero():
    assert C.cantidad_sugerida(20, 0, -3, 0, 0).cantidad == 20
    assert C.fecha_quiebre(-3, [1, 1], HOY) == HOY


def test_quiebre_y_semaforo():
    pron = [4.0] * 30
    assert C.fecha_quiebre(10, pron, HOY) == HOY + timedelta(days=2)       # 4 + 4 = 8, el tercer día no alcanza
    # llega un pedido de 20 el día 2: 10 − 4 − 4 + 20 = 22 → dura 5 días más y un poco
    assert C.fecha_quiebre(10, pron, HOY, [(2, 20)]) == HOY + timedelta(days=7)
    h = C.horizonte(HOY, [0, 3], 2)          # llega en 2 días, horizonte 6
    assert C.semaforo(C.dias_de_stock(6, pron), C.fecha_quiebre(6, pron, HOY), HOY, h) == "rojo"      # se agota mañana
    assert C.semaforo(C.dias_de_stock(12, pron), C.fecha_quiebre(12, pron, HOY), HOY, h) == "amarillo" # dura 3 días
    assert C.semaforo(C.dias_de_stock(30, pron), C.fecha_quiebre(30, pron, HOY), HOY, h) == "verde"
    assert C.semaforo(C.dias_de_stock(200, pron), C.fecha_quiebre(200, pron, HOY), HOY, h) == "gris"  # 50 días > 30
    assert C.semaforo(None, None, HOY, h, disponible=5) == "gris"      # hay stock y no se vende nada


def test_stock_de_seguridad_por_clase():
    ventas = [2, 4, 6, 4, 4, 2, 6]            # desvío poblacional = √(16/7)
    import math
    sigma = math.sqrt(16 / 7)
    assert C.stock_seguridad(ventas, "A", 9) == pytest.approx(1.65 * sigma * 3)
    assert C.stock_seguridad(ventas, "C", 9) == pytest.approx(0.84 * sigma * 3)
    assert C.stock_seguridad(ventas, "A", 9, manual=15) == 15
    assert C.stock_seguridad([], "A", 9) == 0


def test_pronostico_aplica_factores():
    f = C.Factores(semana=[1.0, 1.0, 1.0, 1.0, 1.0, 2.0, 0.0], inicio_mes=1.2, feriado=0.5, tendencia=1.1)
    sabado = date(2026, 9, 26)
    # promedio semanal = 1 → sábado 10 × 2 × tendencia 1,1 = 22
    assert C.pronostico_dia(10, f, sabado, set()) == pytest.approx(22)
    # jueves 1 de octubre, feriado: 10 × 1 × 1,2 (inicio de mes) × 0,5 (feriado) × 1,1
    assert C.pronostico_dia(10, f, date(2026, 10, 1), {date(2026, 10, 1)}) == pytest.approx(10 * 1.2 * 0.5 * 1.1)


def test_factores_no_cuentan_dias_previos_a_los_datos():
    ventas = {dias_atras(i): 5 for i in range(1, 61)}            # 60 días de historia pareja
    f = C.calcular_factores(ventas, set(), HOY, set())
    assert f.estacional == {} and all(x == pytest.approx(1, abs=0.01) for x in f.semana)
    assert f.inicio_mes == pytest.approx(1, abs=0.01) and f.tendencia == pytest.approx(1, abs=0.01)


def test_abc_suma_100_y_coincide_con_calculo_manual():
    valores = {"a": 50, "b": 30, "c": 10, "d": 5, "e": 3, "f": 2, "g": 0, "h": -4}
    r = C.clasificar_abc(valores)
    # a (antes 0 %) A · b (antes 50 %) A · c (antes 80 %) B · d (antes 90 %) B · e (antes 95 %) C · f C · sin ganancia C
    assert {k: v[0] for k, v in r.items()} == {"a": "A", "b": "A", "c": "B", "d": "B", "e": "C", "f": "C", "g": "C", "h": "C"}
    assert sum(v[1] for v in r.values()) == Decimal(1)
    assert r["f"][2] == Decimal(1)


def test_abc_con_decimales_suma_exacta():
    valores = {i: Decimal("1") / 3 for i in range(7)}
    assert sum(v[1] for v in C.clasificar_abc(valores).values()) == pytest.approx(Decimal(1), abs=Decimal("1e-25"))


def test_rol_del_producto():
    assert C.rol_producto(100, 0.1, 50, 0.2) == "iman"
    assert C.rol_producto(100, 0.3, 50, 0.2) == "estrella"
    assert C.rol_producto(10, 0.3, 50, 0.2) == "joya"
    assert C.rol_producto(10, None, 50, 0.2) == "peso_muerto"


def test_deflactar_y_descomposiciones():
    assert C.deflactar(Decimal("1000"), Decimal("9000"), Decimal("9850")) == Decimal("1094.44")
    e = C.efecto_precio_cantidad(Decimal("1000"), Decimal("100"), Decimal("1320"), Decimal("110"))
    # P0 = 10, P1 = 12: cantidad (110 − 100) × 10 = 100; precio 320 − 100 = 220 = (12 − 10) × 110
    assert e["efecto_cantidad"] == 100 and e["efecto_precio"] == 220 and e["efecto_precio"] + e["efecto_cantidad"] == e["variacion"]
    t = C.efecto_clientes_gasto(Decimal("10000"), 100, Decimal("12100"), 110)
    assert t["efecto_clientes"] == 1000 and t["efecto_gasto"] == 1100


def test_precio_sugerido_y_redondeo():
    reglas = [{"desde_precio": 0, "hasta_precio": 2000, "multiplo": 10, "terminaciones": [0, 5, 9]},
              {"desde_precio": 2000, "hasta_precio": None, "multiplo": 50, "terminaciones": [0]}]
    assert C.precio_sugerido(Decimal("700"), Decimal("0.30")) == Decimal("1000")
    assert C.redondear_precio(C.precio_sugerido(Decimal("701"), Decimal("0.30")), reglas) == Decimal("1010.00")
    assert C.redondear_precio(Decimal("2012"), reglas) == Decimal("2050.00")
    assert C.redondear_precio(Decimal("99.1"), []) == Decimal("100")
    with pytest.raises(ValueError):
        C.precio_sugerido(Decimal("10"), Decimal("0.7"), Decimal("0.3"))


def test_poisson_gondola_y_stock_fantasma():
    assert C.posible_faltante_gondola(3.0)          # e^-3 = 4,98 % < 5 %
    assert not C.posible_faltante_gondola(2.9)
    assert C.posible_stock_fantasma(disponible=24, vpd=4, dias_sin_venta=6)
    assert not C.posible_stock_fantasma(disponible=24, vpd=0.2, dias_sin_venta=6)   # vende poco: es normal
    assert not C.posible_stock_fantasma(disponible=0, vpd=4, dias_sin_venta=6)


def test_unidades_que_no_llegan_a_venderse():
    lotes = [{"lote": "B", "cantidad": 30, "vencimiento": HOY + timedelta(days=10)},
             {"lote": "A", "cantidad": 20, "vencimiento": HOY + timedelta(days=4)}]
    r = {x["lote"]: x["no_llegan"] for x in C.unidades_que_no_llegan(lotes, [3.0] * 30, HOY)}
    # A vence en 4 días: se venden 12 → sobran 8. B: hasta el día 10 se venden 30, menos los 12 que fueron para A → 18 → sobran 12.
    assert r == {"A": 8.0, "B": 12.0}


def test_gmroi_rotacion_y_atipicos():
    assert C.gmroi(Decimal("300"), Decimal("1000")) == Decimal("0.3")
    assert C.gmroi(Decimal("300"), Decimal("0")) is None
    assert C.rotacion_anual(Decimal("900"), Decimal("1000"), 90) == Decimal("3.65")
    assert C.z_atipico(10, [1, 1, 1, 1]) == 10.0
    assert C.z_atipico(3, [1, 2, 3]) == pytest.approx((3 - 2) / 0.816496580927726)


def test_prob_poisson_para_anomalias_de_caja():
    assert C.prob_poisson_al_menos(0, 5) == 1.0
    assert abs(C.prob_poisson_al_menos(12, 7.07) - 0.056) < 0.01        # 12 contra 7 esperadas: puede ser azar
    assert C.prob_poisson_al_menos(34, 4.5) < 1e-10                      # 34 contra 4,5: no es azar


def test_asociacion_soporte_confianza_lift():
    # 1.000 tickets; 100 con fernet, 200 con gaseosa, 60 con ambos.
    a = C.asociacion(60, 100, 200, 1000)
    assert a["soporte"] == 0.06 and a["confianza"] == 0.6 and abs(a["lift"] - 3.0) < 1e-9
    assert C.asociacion(20, 100, 200, 1000)["lift"] == 1.0           # independientes
    assert C.asociacion(0, 0, 10, 100)["lift"] == 0.0


def test_elasticidad_recupera_la_pendiente():
    import math as m
    puntos = [(p, 100 * p ** -2.0) for p in [0.8, 0.85, 0.9, 0.95, 1.0, 1.02, 1.05, 0.75, 0.9, 1.0, 0.97, 1.03, 0.88]]
    r = C.elasticidad(puntos)
    assert abs(r["elasticidad"] + 2.0) < 1e-6 and r["r2"] > 0.99 and r["clase"] == "sensible"
    assert C.elasticidad([(p, 50 * p ** -0.4) for p, _ in puntos])["clase"] == "poco_sensible"
    assert C.elasticidad(puntos[:5])["clase"] == "sin_datos"                       # pocas semanas
    assert C.elasticidad([(1.0, 10 + i) for i in range(20)])["clase"] == "sin_datos"  # el precio no cambió
    assert abs(C.factor_por_descuento(-2.0, 0.25) - (0.75 ** -2)) < 1e-12 and C.factor_por_descuento(None, 0.2) is None


def test_rfm():
    assert C.quintil(5, [1, 2, 3, 4]) == 5 and C.quintil(0, [1, 2, 3, 4]) == 1 and C.quintil(2.5, [1, 2, 3, 4]) == 3
    assert C.segmento_rfm(5, 5, 5) == "campeones" and C.segmento_rfm(2, 4, 3) == "en_riesgo" and C.segmento_rfm(1, 1, 1) == "perdidos"
    assert C.segmento_rfm(5, 1, 2) == "nuevos" and C.segmento_rfm(3, 4, 2) == "leales" and C.segmento_rfm(3, 2, 2) == "ocasionales"


def test_elasticidad_controla_el_efecto_de_la_promocion():
    # Semanas en promo: precio 20 % menor y además ×1,3 por exhibición. Sin controlar, la elasticidad sale exagerada.
    puntos = []
    for i in range(30):
        promo = i % 5 == 0
        precio = (0.8 if promo else 1.0) * (1 + 0.02 * ((i % 3) - 1))
        puntos.append((precio, 100 * precio ** -1.5 * (1.3 if promo else 1.0), 1.0 if promo else 0.0))
    con = C.elasticidad(puntos)
    sin = C.elasticidad([(p, u) for p, u, _ in puntos])
    assert abs(con["elasticidad"] + 1.5) < 1e-6 and sin["elasticidad"] < -2.0


def test_combinar_estimaciones_por_precision():
    # Producto con mucho error: se acerca a la categoría; con poco error, se queda cerca de lo propio.
    assert abs(C.combinar_estimaciones(-4.0, 2.0, -1.0, 0.2) - (-1.0297)) < 1e-3
    assert abs(C.combinar_estimaciones(-2.0, 0.1, -1.0, 1.0) - (-1.9901)) < 1e-3
