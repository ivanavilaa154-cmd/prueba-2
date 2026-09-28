"""Cálculos de Retail (secciones 6, 7, 10 y 11). Funciones puras: no tocan la base, se prueban con cuentas a mano.

Cada fórmula está documentada acá y repetida en lenguaje simple en la ayuda «¿Cómo se calcula esto?» de cada pantalla.
Los importes usan Decimal; las cantidades de pronóstico usan float (son estimaciones, no plata).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from statistics import mean, pstdev

# ------------------------------------------------------------------------------ parámetros por defecto (configurables)
VENTANA_VPD = 28                  # días hacia atrás para la venta promedio diaria
MINIMO_DIAS_CON_STOCK = 7         # por debajo: se usa la referencia de la categoría y se marca "baja confianza"
UMBRAL_SOBRESTOCK_DIAS = 30       # semáforo gris
Z_POR_CLASE = {"A": 1.65, "B": 1.28, "C": 0.84, None: 1.28}   # nivel de servicio ≈ 95 % / 90 % / 80 %
DIAS_REVISION_SIN_VISITA = 7      # proveedor sin días de visita: se asume un pedido por semana
DEMORA_SIN_DATO = 3               # proveedor sin demora cargada
CORTES_ABC = (Decimal("0.80"), Decimal("0.95"))
PESOS_SEMANAS = (0.4, 0.3, 0.2, 0.1)   # VPD ponderada: la semana más reciente pesa más


# ------------------------------------------------------------------------------ 1. venta promedio diaria
@dataclass
class ResultadoVPD:
    vpd: float
    dias_con_stock: int
    dias_sin_stock: int
    unidades: float
    confianza: str            # "normal" o "baja"
    usa_referencia: bool = False


def dias_sin_stock(ventas: dict[date, float], cierre: dict[date, float], desde: date, hasta: date) -> set[date]:
    """Un día cuenta como «sin stock» si no hubo ventas y el producto no tenía stock: cierre de ese día ≤ 0
    o cierre del día anterior ≤ 0 (arrancó el día sin mercadería). Un día con ventas siempre tuvo stock."""
    resultado = set()
    d = desde
    while d <= hasta:
        if ventas.get(d, 0) <= 0:
            hoy_c = cierre.get(d)
            ayer_c = cierre.get(d - timedelta(days=1))
            if (hoy_c is not None and hoy_c <= 0) or (ayer_c is not None and ayer_c <= 0):
                resultado.add(d)
        d += timedelta(days=1)
    return resultado


def venta_promedio_diaria(ventas: dict[date, float], sin_stock: set[date], hoy: date, ventana: int = VENTANA_VPD,
                          minimo_dias: int = MINIMO_DIAS_CON_STOCK, referencia: float | None = None,
                          desde_alta: date | None = None) -> ResultadoVPD:
    """VPD = unidades vendidas en los últimos `ventana` días ÷ días CON stock de ese período.
    Se cuenta desde ayer hacia atrás (hoy está incompleto). Si el producto se dio de alta hace poco, el período
    empieza en el alta. Con menos de `minimo_dias` días con stock se usa `referencia` (promedio de la categoría)
    y se marca baja confianza."""
    fin = hoy - timedelta(days=1)
    inicio = fin - timedelta(days=ventana - 1)
    if desde_alta and desde_alta > inicio:
        inicio = desde_alta
    dias = [inicio + timedelta(days=i) for i in range((fin - inicio).days + 1)]
    con = [d for d in dias if d not in sin_stock]
    unidades = max(0.0, sum(ventas.get(d, 0.0) for d in con))   # las devoluciones (negativas) restan
    if len(con) < minimo_dias:
        propio = unidades / len(con) if con else 0.0
        if referencia is not None:
            # mezcla: lo propio pesa según cuántos días hay, el resto es la referencia
            peso = len(con) / minimo_dias
            return ResultadoVPD(propio * peso + referencia * (1 - peso), len(con), len(dias) - len(con), unidades, "baja", True)
        return ResultadoVPD(propio, len(con), len(dias) - len(con), unidades, "baja")
    return ResultadoVPD(unidades / len(con), len(con), len(dias) - len(con), unidades, "normal")


def vpd_ponderada(ventas: dict[date, float], sin_stock: set[date], hoy: date, pesos: tuple = PESOS_SEMANAS) -> float | None:
    """Promedio diario de cada una de las últimas 4 semanas (solo días con stock), ponderado: 40 % la última,
    30 %, 20 % y 10 % las anteriores. Semanas sin días con stock no cuentan (se reparten sus pesos)."""
    fin = hoy - timedelta(days=1)
    total_peso, total = 0.0, 0.0
    for k, peso in enumerate(pesos):
        dias = [fin - timedelta(days=7 * k + i) for i in range(7)]
        con = [d for d in dias if d not in sin_stock]
        if not con:
            continue
        total += peso * max(0.0, sum(ventas.get(d, 0.0) for d in con)) / len(con)
        total_peso += peso
    return total / total_peso if total_peso else None


# ------------------------------------------------------------------------------ 2. pronóstico
@dataclass
class Factores:
    semana: list[float] = field(default_factory=lambda: [1.0] * 7)   # lunes … domingo
    inicio_mes: float = 1.0         # días 1 a 5 (cobro de sueldos)
    fin_mes: float = 1.0            # días 26 a 31
    feriado: float = 1.0
    estacional: dict[int, float] = field(default_factory=dict)   # mes → factor (solo con más de un año de historia)
    tendencia: float = 1.0
    origen: str = "producto"        # producto o categoria


def _mezclar(propio: float | None, referencia: float, n: int, k: int = 20) -> float:
    """Encoge el factor propio hacia el de referencia cuando hay pocos datos: peso n/(n+k)."""
    if propio is None or n == 0:
        return referencia
    return (n * propio + k * referencia) / (n + k)


def calcular_factores(ventas: dict[date, float], sin_stock: set[date], hoy: date, feriados: set[date],
                      referencia: Factores | None = None, dias_historia: int = 364, desde: date | None = None) -> Factores:
    """Factores del producto con su propia historia (días con stock, desde el primer dato conocido `desde`: antes de eso
    no hay información, no son días sin venta). Cada factor = promedio de los días de ese tipo ÷ promedio general.
    Con pocos datos se acercan a los de `referencia` (la categoría)."""
    ref = referencia or Factores(origen="categoria")
    fin = hoy - timedelta(days=1)
    if desde is None:
        desde = min(ventas) if ventas else fin
    dias = [fin - timedelta(days=i) for i in range(dias_historia)
            if (fin - timedelta(days=i)) not in sin_stock and fin - timedelta(days=i) >= desde]
    valores = [(d, max(0.0, ventas.get(d, 0.0))) for d in dias]
    if not valores:
        return Factores(semana=list(ref.semana), inicio_mes=ref.inicio_mes, fin_mes=ref.fin_mes, feriado=ref.feriado,
                        estacional=dict(ref.estacional), tendencia=1.0, origen="categoria")
    recientes = [v for d, v in valores if (fin - d).days < 112]      # 16 semanas para el patrón semanal
    base = mean(v for _, v in valores) or 0.0
    base_rec = mean(recientes) if recientes else base
    f = Factores(origen="producto")
    if base_rec > 0:
        for wd in range(7):
            vs = [v for d, v in valores if d.weekday() == wd and (fin - d).days < 112]
            f.semana[wd] = _mezclar(mean(vs) / base_rec if vs else None, ref.semana[wd], len(vs), 8)
    else:
        f.semana = list(ref.semana)
    if base > 0:
        ini = [v for d, v in valores if d.day <= 5 and d not in feriados]
        fin_m = [v for d, v in valores if d.day >= 26 and d not in feriados]
        fer = [v for d, v in valores if d in feriados]
        f.inicio_mes = _mezclar(mean(ini) / base if ini else None, ref.inicio_mes, len(ini))
        f.fin_mes = _mezclar(mean(fin_m) / base if fin_m else None, ref.fin_mes, len(fin_m))
        f.feriado = _mezclar(mean(fer) / base if fer else None, ref.feriado, len(fer), 5)
    else:
        f.inicio_mes, f.fin_mes, f.feriado = ref.inicio_mes, ref.fin_mes, ref.feriado
    # Estacionalidad: solo si hay más de un año de historia (mes del año ÷ promedio anual).
    primero = min(d for d, _ in valores)
    if (fin - primero).days >= 360 and base > 0:
        por_mes: dict[int, list[float]] = {}
        for d, v in valores:
            por_mes.setdefault(d.month, []).append(v)
        f.estacional = {m: mean(vs) / base for m, vs in por_mes.items() if len(vs) >= 10}
    else:
        f.estacional = dict(ref.estacional)
    # Tendencia: últimas 4 semanas vs. las 8 anteriores (sin estacionalidad de por medio), acotada entre 0,8 y 1,25.
    ult = [v for d, v in valores if (fin - d).days < 28]
    prev = [v for d, v in valores if 28 <= (fin - d).days < 84]
    if ult and prev and mean(prev) > 0:
        bruta = mean(ult) / mean(prev)
        if f.estacional:
            mes_ult = f.estacional.get(fin.month, 1.0)
            mes_prev = f.estacional.get((fin - timedelta(days=56)).month, 1.0)
            if mes_prev > 0 and mes_ult > 0:
                bruta = bruta / (mes_ult / mes_prev)
        f.tendencia = min(1.25, max(0.8, _mezclar(bruta, 1.0, len(ult), 14)))
    return f


def pronostico_dia(base: float, f: Factores, d: date, feriados: set[date]) -> float:
    """Pronóstico de un día = VPD ponderada × semana × inicio/fin de mes × feriado × estacional × tendencia.
    La VPD ponderada ya es un promedio de la semana, por eso el factor semanal se normaliza (promedio 1)."""
    prom_semana = sum(f.semana) / 7 or 1.0
    valor = base * (f.semana[d.weekday()] / prom_semana)
    if d.day <= 5:
        valor *= f.inicio_mes
    elif d.day >= 26:
        valor *= f.fin_mes
    if d in feriados:
        valor *= f.feriado
    if f.estacional:
        prom_est = sum(f.estacional.values()) / len(f.estacional) or 1.0
        hoy_est = f.estacional.get(d.month)
        if hoy_est is not None:
            valor *= hoy_est / prom_est
    return max(0.0, valor * f.tendencia)


def pronostico(base: float, f: Factores, desde: date, dias: int, feriados: set[date]) -> list[float]:
    return [pronostico_dia(base, f, desde + timedelta(days=i), feriados) for i in range(dias)]


# ------------------------------------------------------------------------------ 3-4. días de stock y quiebre
def dias_de_stock(disponible: float, pron: list[float]) -> float | None:
    """Días de stock = disponible ÷ pronóstico diario promedio de los próximos 28 días. None si no se vende."""
    promedio = sum(pron[:28]) / min(len(pron), 28) if pron else 0
    if promedio <= 0:
        return None
    return max(0.0, disponible) / promedio


def fecha_quiebre(disponible: float, pron: list[float], hoy: date, llegadas: list[tuple[int, float]] | None = None) -> date | None:
    """Recorre el pronóstico día por día: cada día se suma lo que llega ese día (pedidos ya aprobados o transferencias
    en tránsito, con su fecha) y se resta lo que se vende. Devuelve el primer día en que no alcanza."""
    llegan = defaultdict_float(llegadas)
    saldo = max(0.0, disponible)
    for i, v in enumerate(pron):
        saldo += llegan.get(i, 0.0)
        if saldo <= 0 and v > 0:
            return hoy + timedelta(days=i)
        saldo -= v
        if saldo < 0:
            return hoy + timedelta(days=i)
    return None


def defaultdict_float(llegadas: list[tuple[int, float]] | None) -> dict[int, float]:
    resultado: dict[int, float] = {}
    for dia, cantidad in llegadas or []:
        resultado[max(0, dia)] = resultado.get(max(0, dia), 0.0) + cantidad
    return resultado


# ------------------------------------------------------------------------------ 5. horizonte
@dataclass
class Horizonte:
    proxima_oportunidad: int      # días hasta que se puede pedir (0 = hoy)
    llegada_proxima: int          # días hasta que llega lo que se pide en esa oportunidad
    horizonte: int                # días a cubrir: hasta que llega el pedido SIGUIENTE
    supuesto: str | None = None   # si faltan datos del proveedor


def horizonte(hoy: date, dias_visita: list[int] | None, demora: int | None) -> Horizonte:
    """Horizonte de cobertura = días hasta la próxima visita del proveedor + demora de entrega.
    Se pide en la próxima oportunidad (hoy si hoy pasa el proveedor); lo pedido tiene que alcanzar hasta que llegue el
    pedido siguiente: días hasta la visita siguiente a esa oportunidad + demora.
    Proveedor sin días configurados: se asume revisión semanal y se avisa."""
    supuesto = None
    if demora is None:
        demora = DEMORA_SIN_DATO
        supuesto = f"El proveedor no tiene demora cargada: se asumen {DEMORA_SIN_DATO} días."
    if not dias_visita:
        texto = f"El proveedor no tiene días de visita: se asume un pedido cada {DIAS_REVISION_SIN_VISITA} días."
        supuesto = f"{supuesto} {texto}" if supuesto else texto
        return Horizonte(0, demora, DIAS_REVISION_SIN_VISITA + demora, supuesto)
    oportunidad = min((w - hoy.weekday()) % 7 for w in dias_visita)
    dia_op = (hoy.weekday() + oportunidad) % 7
    siguiente = min(((w - dia_op) % 7) or 7 for w in dias_visita)
    return Horizonte(oportunidad, oportunidad + demora, oportunidad + siguiente + demora, supuesto)


# ------------------------------------------------------------------------------ 6. stock de seguridad
def stock_seguridad(ventas_diarias: list[float], clase: str | None, horizonte_dias: int, manual: float | None = None) -> float:
    """SS = z(clase) × desvío estándar de la venta diaria × √(horizonte). z: A 1,65 · B 1,28 · C 0,84.
    Si el usuario cargó un stock de seguridad en las reglas, se usa ese."""
    if manual is not None:
        return float(manual)
    if len(ventas_diarias) < 2:
        return 0.0
    return Z_POR_CLASE.get(clase, 1.28) * pstdev(ventas_diarias) * math.sqrt(max(1, horizonte_dias))


# ------------------------------------------------------------------------------ 7. cantidad sugerida
@dataclass
class Sugerencia:
    cantidad: float
    necesidad: float
    bruto: float
    multiplo: int
    recortada_por_maximo: bool = False


def cantidad_sugerida(pron_horizonte: float, ss: float, disponible: float, en_transito: float, pedidos_abiertos: float,
                      unidades_por_bulto: int = 1, multiplo_compra: int = 1, stock_maximo: float | None = None) -> Sugerencia:
    """Cantidad = pronóstico acumulado del horizonte + stock de seguridad − disponible − en tránsito − pedidos aprobados.
    Si da ≤ 0, no se compra. Se redondea hacia arriba al múltiplo de compra (bultos × múltiplo) y no se pasa del máximo.
    Un stock negativo se toma como 0 (no se puede vender lo que no hay) y se marca para recuento."""
    disponible = max(0.0, disponible)
    necesidad = pron_horizonte + ss - disponible - en_transito - pedidos_abiertos
    multiplo = max(1, unidades_por_bulto) * max(1, multiplo_compra)
    if necesidad <= 1e-9:
        return Sugerencia(0.0, necesidad, necesidad, multiplo)
    cantidad = math.ceil(necesidad / multiplo - 1e-9) * multiplo
    recortada = False
    if stock_maximo is not None:
        tope = stock_maximo - disponible - en_transito - pedidos_abiertos
        if cantidad > tope:
            cantidad = max(0, math.floor(tope / multiplo)) * multiplo
            recortada = True
    return Sugerencia(float(cantidad), necesidad, necesidad, multiplo, recortada)


# ------------------------------------------------------------------------------ 8. semáforo
def semaforo(dias_stock: float | None, quiebre: date | None, hoy: date, h: Horizonte,
             umbral_sobrestock: int = UMBRAL_SOBRESTOCK_DIAS, disponible: float = 0.0) -> str:
    """Rojo: se agota antes de que llegue la próxima reposición posible (hoy + llegada_proxima).
    Amarillo: llega a esa reposición, pero se agota antes del horizonte: hay que incluirlo en el próximo pedido.
    Verde: cubierto todo el horizonte. Gris: sobrestock (cobertura mayor al umbral, 30 días por defecto)."""
    if dias_stock is None:
        return "gris" if disponible > 0 else "verde"
    if dias_stock > umbral_sobrestock:
        return "gris"
    if quiebre is not None and quiebre < hoy + timedelta(days=h.llegada_proxima):
        return "rojo"
    if quiebre is not None and quiebre < hoy + timedelta(days=h.horizonte):
        return "amarillo"
    return "verde"


# ------------------------------------------------------------------------------ góndola y stock fantasma
def prob_cero_ventas(esperado: float) -> float:
    """Poisson: probabilidad de no vender nada cuando se esperan `esperado` unidades en ese lapso = e^(−esperado)."""
    return math.exp(-max(0.0, esperado))


def posible_faltante_gondola(esperado_desde_ultima_venta: float, umbral: float = 0.05) -> bool:
    """Alerta si la probabilidad de haber pasado estas horas sin vender es menor al umbral (5 %)."""
    return prob_cero_ventas(esperado_desde_ultima_venta) < umbral


def posible_stock_fantasma(disponible: float, vpd: float, dias_sin_venta: int, minimo_dias: int = 4, umbral: float = 0.01) -> bool:
    """Hay stock según el sistema, pero no se vendió nada en varios días y eso sería muy improbable con su ritmo normal."""
    return disponible > 0 and dias_sin_venta >= minimo_dias and prob_cero_ventas(vpd * dias_sin_venta) < umbral


# ------------------------------------------------------------------------------ ABC y rol del producto
def clasificar_abc(valores: dict, cortes: tuple = CORTES_ABC) -> dict:
    """Pareto: se ordena de mayor a menor y se acumula el porcentaje. Un producto es A si lo acumulado ANTES de él es
    menor al 80 % (el que cruza el 80 % también es A), B hasta el 95 %, C el resto. Valores ≤ 0 van a C.
    Devuelve {id: (clase, participación, acumulado)} con Decimal; las participaciones suman exactamente 1."""
    positivos = {k: Decimal(v) for k, v in valores.items() if Decimal(v) > 0}
    total = sum(positivos.values(), Decimal(0))
    resultado = {}
    acumulado = Decimal(0)
    for k, v in sorted(positivos.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        antes = acumulado
        participacion = v / total
        acumulado += participacion
        clase = "A" if antes < cortes[0] else ("B" if antes < cortes[1] else "C")
        resultado[k] = (clase, participacion, acumulado)
    for k in valores:
        if k not in resultado:
            resultado[k] = ("C", Decimal(0), acumulado if positivos else Decimal(0))
    return resultado


def rol_producto(volumen: float, margen: float | None, mediana_volumen: float, mediana_margen: float) -> str:
    """Matriz volumen × margen: estrella (alto/alto), imán (alto volumen, bajo margen), joya (bajo volumen, alto margen),
    peso muerto (bajo/bajo)."""
    alto_v = volumen >= mediana_volumen
    alto_m = (margen if margen is not None else 0) >= mediana_margen
    return {(True, True): "estrella", (True, False): "iman", (False, True): "joya", (False, False): "peso_muerto"}[(alto_v, alto_m)]


# ------------------------------------------------------------------------------ inflación, ticket y tráfico
def deflactar(monto: Decimal, indice_mes: Decimal, indice_base: Decimal) -> Decimal:
    """Pesos del último mes = monto × índice del mes base ÷ índice del mes de la venta."""
    return (Decimal(monto) * Decimal(indice_base) / Decimal(indice_mes)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def efecto_precio_cantidad(ventas0: Decimal, unidades0: Decimal, ventas1: Decimal, unidades1: Decimal) -> dict:
    """Variación de facturación = efecto precio + efecto cantidad (suman exacto):
    precio promedio P = ventas ÷ unidades; efecto cantidad = (Q1 − Q0) × P0; efecto precio = (P1 − P0) × Q1."""
    ventas0, unidades0, ventas1, unidades1 = (Decimal(x) for x in (ventas0, unidades0, ventas1, unidades1))
    p0 = ventas0 / unidades0 if unidades0 else Decimal(0)
    p1 = ventas1 / unidades1 if unidades1 else Decimal(0)
    cantidad = (unidades1 - unidades0) * p0
    precio = (ventas1 - ventas0) - cantidad
    return {"variacion": ventas1 - ventas0, "efecto_precio": precio, "efecto_cantidad": cantidad, "precio0": p0, "precio1": p1}


def efecto_clientes_gasto(ventas0: Decimal, tickets0: int, ventas1: Decimal, tickets1: int) -> dict:
    """Variación = más o menos clientes (ΔT × ticket promedio anterior) + gasto por cliente (T1 × Δticket promedio)."""
    ventas0, ventas1 = Decimal(ventas0), Decimal(ventas1)
    a0 = ventas0 / tickets0 if tickets0 else Decimal(0)
    clientes = (Decimal(tickets1) - Decimal(tickets0)) * a0
    return {"variacion": ventas1 - ventas0, "efecto_clientes": clientes, "efecto_gasto": (ventas1 - ventas0) - clientes,
            "ticket0": a0, "ticket1": ventas1 / tickets1 if tickets1 else Decimal(0)}


# ------------------------------------------------------------------------------ precios
def precio_sugerido(costo: Decimal, margen: Decimal, costo_canal_pct: Decimal = Decimal(0)) -> Decimal:
    """Precio = costo ÷ (1 − margen objetivo − costos del canal en % del precio)."""
    divisor = Decimal(1) - Decimal(margen) - Decimal(costo_canal_pct)
    if divisor <= 0:
        raise ValueError("El margen objetivo más los costos del canal no pueden llegar al 100 %.")
    return Decimal(costo) / divisor


def redondear_precio(precio: Decimal, reglas: list[dict]) -> Decimal:
    """Aplica la regla del tramo: redondea hacia arriba al múltiplo y, si hay terminaciones permitidas, sube hasta la
    primera que coincida con la última cifra entera. Sin regla: al peso."""
    precio = Decimal(precio)
    regla = next((r for r in reglas if Decimal(r["desde_precio"]) <= precio and
                  (r.get("hasta_precio") is None or precio < Decimal(r["hasta_precio"]))), None)
    if not regla:
        return precio.quantize(Decimal("1"), ROUND_CEILING)
    paso = Decimal(regla["multiplo"])
    valor = (precio / paso).quantize(Decimal("1"), ROUND_CEILING) * paso
    terminaciones = regla.get("terminaciones") or []
    if terminaciones and paso < 10:
        while int(valor) % 10 not in terminaciones:
            valor += paso
    elif terminaciones:
        intentos = 0
        while int(valor) % 10 not in terminaciones and intentos < 20:
            valor += paso
            intentos += 1
    return valor.quantize(Decimal("0.01"))


def margen(precio: Decimal, costo: Decimal) -> Decimal | None:
    precio, costo = Decimal(precio), Decimal(costo)
    return (precio - costo) / precio if precio > 0 else None


# ------------------------------------------------------------------------------ rentabilidad del inventario
def gmroi(ganancia_bruta: Decimal, inventario_promedio_costo: Decimal) -> Decimal | None:
    """GMROI = ganancia bruta del período ÷ inversión promedio en stock a costo."""
    inv = Decimal(inventario_promedio_costo)
    return Decimal(ganancia_bruta) / inv if inv > 0 else None


def rotacion_anual(costo_vendido: Decimal, inventario_promedio_costo: Decimal, dias_periodo: int) -> Decimal | None:
    """Rotación anualizada = costo de lo vendido ÷ inventario promedio a costo × (365 ÷ días del período)."""
    inv = Decimal(inventario_promedio_costo)
    if inv <= 0 or dias_periodo <= 0:
        return None
    return Decimal(costo_vendido) / inv * Decimal(365) / Decimal(dias_periodo)


# ------------------------------------------------------------------------------ vencimientos
def unidades_que_no_llegan(lotes: list[dict], pron: list[float], hoy: date) -> list[dict]:
    """Por lote (el que vence antes se vende primero): unidades que no llegan a venderse antes de vencer =
    cantidad del lote − lo que queda del pronóstico acumulado hasta su vencimiento después de atender a los lotes anteriores."""
    resultado = []
    consumido = 0.0
    for lote in sorted(lotes, key=lambda x: (x["vencimiento"] or date.max)):
        if lote["vencimiento"] is None:
            resultado.append({**lote, "no_llegan": 0.0})
            continue
        dias = max(0, (lote["vencimiento"] - hoy).days)
        demanda = sum(pron[:dias])
        disponible_para_este = max(0.0, demanda - consumido)
        vende = min(float(lote["cantidad"]), disponible_para_este)
        consumido += vende
        resultado.append({**lote, "no_llegan": max(0.0, float(lote["cantidad"]) - vende), "dias": dias})
    return resultado


# ------------------------------------------------------------------------------ anomalías (control de caja)
def z_atipico(valor: float, otros: list[float]) -> float | None:
    """Cuántos desvíos estándar se aleja un cajero/turno del resto. None si no hay con qué comparar."""
    if len(otros) < 2:
        return None
    desvio = pstdev(otros)
    if desvio == 0:
        return None if valor == mean(otros) else math.copysign(10.0, valor - mean(otros))
    return (valor - mean(otros)) / desvio
