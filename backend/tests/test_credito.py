"""El simulador debe reproducir el ejemplo resuelto del documento de prompts."""
import pytest

from app.decisiones.credito import ParametrosCredito, simular

EJEMPLO = dict(
    compra_mensual_cliente=400_000, margen_bruto=0.22, dias_cobro_reales=42,
    dias_inventario=20, dias_pago_proveedores=21, costo_servir=0.04, incobrabilidad=0.02,
    costo_dinero_mensual=0.03, punto_mas_bajo_caja=2_600_000, caja_minima=1_500_000,
    descubierto_disponible=1_000_000, clientes_solicitados=5,
)


@pytest.fixture
def r():
    return simular(ParametrosCredito(**EJEMPLO))


def test_caja_inmovilizada_por_cliente(r):
    assert r.base.cuentas_por_cobrar == pytest.approx(560_000)
    assert r.base.inventario == pytest.approx(208_000)
    assert r.base.deuda_proveedores == pytest.approx(218_400)
    assert r.base.caja_inmovilizada_por_cliente == pytest.approx(549_600)


def test_rentabilidad(r):
    assert r.base.resultado_mensual_por_cliente == pytest.approx(47_512)
    assert r.base.retorno_mensual == pytest.approx(0.0864, abs=1e-4)
    assert r.base.meses_recupero == pytest.approx(11.6)
    assert r.pruebas["rentabilidad"]["pasa"]


def test_limites_de_caja(r):
    assert r.base.max_clientes_sin_descubierto == 2
    assert r.base.max_clientes_con_descubierto == 3
    assert r.limite_base == 3 and r.usa_descubierto_base


def test_escenario_pesimista(r):
    # cobro a 57 días y punto más bajo 1.900.000 → solo 1 cliente, con descubierto
    assert r.pesimista.caja_inmovilizada_por_cliente == pytest.approx(749_600)
    assert r.pesimista.max_clientes_sin_descubierto == 0
    assert r.limite_seguro_pesimista == 1


def test_punto_de_quiebre_y_exposicion(r):
    assert r.punto_quiebre_incobrabilidad == pytest.approx(0.1388, abs=1e-4)
    assert r.exposicion_maxima_por_cliente == pytest.approx(560_000)


def test_palancas(r):
    actual, cobrar, pagar = r.palancas
    assert (actual["clientes_sin_descubierto"], actual["clientes_con_descubierto"]) == (2, 3)
    assert cobrar["caja_por_cliente"] == pytest.approx(389_600)
    assert (cobrar["clientes_sin_descubierto"], cobrar["clientes_con_descubierto"]) == (2, 5)
    assert pagar["caja_por_cliente"] == pytest.approx(296_000)
    assert (pagar["clientes_sin_descubierto"], pagar["clientes_con_descubierto"]) == (3, 7)


def test_veredicto_con_condiciones_si_pide_5(r):
    assert r.veredicto == "SÍ CON CONDICIONES"
    assert r.tabla_clientes[4]["estado"].startswith("No pasa")


def test_veredicto_si_pide_1():
    r = simular(ParametrosCredito(**{**EJEMPLO, "clientes_solicitados": 1, "pesimista_baja_caja": 0}))
    assert r.veredicto == "SÍ"


def test_no_rentable():
    r = simular(ParametrosCredito(**{**EJEMPLO, "incobrabilidad": 0.15}))
    assert r.veredicto == "NO"
    assert not r.pruebas["rentabilidad"]["pasa"]
