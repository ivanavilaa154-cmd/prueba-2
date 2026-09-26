"""Métricas que puede usar un objetivo, calculadas siempre por la plataforma (nunca cargadas a mano).

Cada métrica sabe: si es acumulable (venta, pedidos: se suman en el período) o no
(%, tiempos, saldos), su dirección, qué alcances admite y si se puede calcular para
períodos pasados (las fotos de hoy, como la caja o el stock, solo existen hoy).
Las que la plataforma todavía no puede calcular quedan como no disponibles (V1).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta

from ..erp import conector
from . import procesos as procesos_mod

SIN_LIMITE = 2_000_000


@dataclass(frozen=True)
class Metrica:
    codigo: str
    nombre: str
    unidad: str           # moneda | cantidad | porcentaje | dias
    direccion: str        # mayor_mejor | menor_mejor
    acumulable: bool
    alcances: tuple
    historica: bool = True   # se puede calcular para períodos pasados
    con_muestra: bool = False


def _q(sql: str) -> list[list]:
    return conector.consultar(sql, max_filas=SIN_LIMITE)["filas"]


def _uno(sql: str):
    filas = _q(sql)
    return filas[0][0] if filas else None


def _texto(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


VENTAS_ALCANCES = ("empresa", "sucursal", "canal", "vendedor", "categoria")

METRICAS: dict[str, Metrica] = {m.codigo: m for m in [
    Metrica("kpi:VEN-01", "Venta neta", "moneda", "mayor_mejor", True, VENTAS_ALCANCES),
    Metrica("kpi:VEN-02", "Cantidad de pedidos", "cantidad", "mayor_mejor", True, ("empresa", "sucursal", "canal", "vendedor")),
    Metrica("kpi:VEN-03", "Ticket promedio", "moneda", "mayor_mejor", False, ("empresa", "sucursal", "canal", "vendedor"), con_muestra=True),
    Metrica("kpi:VEN-08", "Margen bruto %", "porcentaje", "mayor_mejor", False, VENTAS_ALCANCES, con_muestra=True),
    Metrica("kpi:VEN-11", "Clientes nuevos", "cantidad", "mayor_mejor", True, ("empresa", "sucursal", "canal", "vendedor")),
    Metrica("kpi:VEN-07", "Cumplimiento de cuota", "porcentaje", "mayor_mejor", True, ("vendedor",)),
    Metrica("kpi:FIN-15", "Efectividad de cobranza (CEI)", "porcentaje", "mayor_mejor", False, ("empresa", "vendedor")),
    Metrica("kpi:FIN-10", "Cartera vencida (% de lo que se debe)", "porcentaje", "menor_mejor", False, ("empresa", "vendedor")),
    Metrica("kpi:FIN-04", "Gastos operativos", "moneda", "menor_mejor", True, ("empresa", "sucursal")),
    Metrica("kpi:FIN-07", "Caja disponible", "moneda", "mayor_mejor", False, ("empresa",), historica=False),
    Metrica("kpi:INV-06", "Quiebre de stock (% de productos)", "porcentaje", "menor_mejor", False, ("empresa", "sucursal"),
            historica=False, con_muestra=True),
    Metrica("kpi:INV-04", "Días de inventario", "dias", "menor_mejor", False, ("empresa",), historica=False),
    Metrica("kpi:INV-20", "Stock en riesgo de vencimiento", "moneda", "menor_mejor", False, ("empresa", "sucursal"), historica=False),
    Metrica("actividad:todas.tareas_resueltas_en_plazo_pct", "Tareas resueltas en plazo", "porcentaje", "mayor_mejor", False,
            ("empresa",), con_muestra=True),
]}

# Métricas de proceso (proceso:PRC-XXX[.Pn].<metrica>): se arman a pedido.
_PROCESO_UNIDAD = {"cumplimiento_sla_pct": ("porcentaje", "mayor_mejor", False), "conformidad_pct": ("porcentaje", "mayor_mejor", False),
                   "tiempo_ciclo_p50": ("dias", "menor_mejor", False), "tiempo_ciclo_p90": ("dias", "menor_mejor", False),
                   "tiempo_paso_p50": ("dias", "menor_mejor", False), "casos_completados": ("cantidad", "mayor_mejor", True),
                   "casos_iniciados": ("cantidad", "mayor_mejor", True), "casos_trabados": ("cantidad", "menor_mejor", False),
                   "casos_vencidos_abiertos": ("cantidad", "menor_mejor", False), "casos_en_curso": ("cantidad", "menor_mejor", False)}


def metrica(codigo: str) -> Metrica | None:
    if codigo in METRICAS:
        return METRICAS[codigo]
    if codigo.startswith("proceso:"):
        partes = codigo.split(":", 1)[1].split(".")
        base = partes[-1]
        if base in _PROCESO_UNIDAD:
            unidad, direccion, acum = _PROCESO_UNIDAD[base]
            return Metrica(codigo, codigo.split(":", 1)[1], unidad, direccion, acum, ("empresa",), con_muestra=not acum)
    return None


# --- caché de procesos por corrida (evita reconstruirlos para cada objetivo) ----------------
_cache: dict = {}


def proceso(pid: str, hoy: date) -> procesos_mod.Proceso:
    from . import almacen
    clave = (pid, hoy, almacen.fuente_actual(), int(time.time() // 60))
    if clave not in _cache:
        _cache.clear() if len(_cache) > 20 else None
        _cache[clave] = procesos_mod.Proceso(pid, hoy)
    return _cache[clave]


def disponible(codigo: str, hoy: date) -> tuple[bool, str | None]:
    """V1: la métrica existe y se puede calcular con los datos de la fuente activa."""
    m = metrica(codigo)
    if not m:
        area = codigo.split(":")[-1][:3]
        motivo = {"LOG": "Logística: la plataforma todavía no tiene envíos.", "MKT": "Marketing: la plataforma todavía no tiene "
                  "publicidad ni analítica web."}.get(area, "La plataforma todavía no calcula esta métrica.")
        return False, motivo
    if codigo.startswith("proceso:"):
        partes = codigo.split(":", 1)[1].split(".")
        pid = partes[0]
        p = proceso(pid, hoy)
        if not p.activo:
            return False, p.motivo or p.error or f"El proceso {pid} no está activo."
        if len(partes) == 3:
            info = p.metricas(hoy - timedelta(days=90), hoy)["pasos"].get(partes[1])
            if not info or not (info["medible"] or info["manual"]):
                return False, f"El paso {partes[1]} de {pid} no se puede medir con los datos de la integración."
        return True, None
    if codigo.startswith("actividad:"):
        return True, None   # la mide la plataforma con sus propias tareas
    if codigo == "kpi:VEN-07":
        n = _uno("SELECT COUNT(*) FROM objetivos_vendedores")
        return bool(n), (None if n else "No hay cuotas por vendedor cargadas (objetivos_vendedores).")
    try:
        v, _n = valor(codigo, "empresa", None, hoy - timedelta(days=90), hoy - timedelta(days=1), hoy)
    except Exception as e:
        return False, f"Faltan datos: {str(e).splitlines()[0][:120]}"
    return (v is not None), (None if v is not None else "La fuente activa no tiene datos para esta métrica.")


# --- cálculo ------------------------------------------------------------------------------

def _filtro_ventas(tipo: str, valor_) -> tuple[str, str]:
    """(join extra, condición) para ventas v / líneas l según el alcance."""
    if tipo in (None, "empresa") or valor_ in (None, ""):
        return "", ""
    if tipo == "categoria":
        return " JOIN productos p ON p.id = l.producto_id", f" AND p.categoria = {_texto(valor_)}"
    columna = {"sucursal": "v.sucursal_id", "canal": "v.canal", "vendedor": "v.vendedor_id"}[tipo]
    return "", f" AND {columna} = {_texto(valor_) if tipo == 'canal' else int(valor_)}"


def _venta(desde: date, hasta: date, tipo, valor_, neta=True) -> tuple[float, int]:
    join, cond = _filtro_ventas(tipo, valor_)
    fila = _q(f"SELECT SUM(l.cantidad * l.precio_unitario), COUNT(DISTINCT v.id) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id{join} "
              f"WHERE COALESCE(v.anulada, 0) = 0 AND v.fecha >= '{desde}' AND v.fecha <= '{hasta}'{cond}")[0]
    venta, pedidos = float(fila[0] or 0), int(fila[1] or 0)
    if neta:
        if tipo in (None, "empresa") or valor_ in (None, ""):
            dev = _uno(f"SELECT SUM(importe) FROM devoluciones WHERE fecha >= '{desde}' AND fecha <= '{hasta}'")
        elif tipo == "categoria":
            dev = _uno(f"SELECT SUM(d.importe) FROM devoluciones d JOIN productos p ON p.id = d.producto_id WHERE d.fecha >= '{desde}' "
                       f"AND d.fecha <= '{hasta}' AND p.categoria = {_texto(valor_)}")
        else:
            _j, c = _filtro_ventas(tipo, valor_)
            dev = _uno(f"SELECT SUM(d.importe) FROM devoluciones d JOIN ventas v ON v.id = d.venta_id WHERE d.fecha >= '{desde}' "
                       f"AND d.fecha <= '{hasta}'{c}")
        venta -= float(dev or 0)
    return venta, pedidos


def _cxc_saldo(corte: date, vendedor=None) -> tuple[float, float]:
    """(saldo total, saldo vencido) de CxC reconstruido a una fecha de corte."""
    cond = f" AND vendedor_id = {int(vendedor)}" if vendedor not in (None, "") else ""
    fila = _q("SELECT SUM(importe), SUM(CASE WHEN fecha_vencimiento < '{c}' THEN importe ELSE 0 END) FROM cxc "
              "WHERE COALESCE(tipo, 'factura') = 'factura' AND fecha_emision <= '{c}' AND (fecha_cobro IS NULL OR fecha_cobro > '{c}'){f}"
              .format(c=corte.isoformat(), f=cond))[0]
    return float(fila[0] or 0), float(fila[1] or 0)


def valor(codigo: str, alcance_tipo: str | None, alcance_valor, desde: date, hasta: date, hoy: date) -> tuple[float | None, int]:
    """(valor de la métrica en [desde, hasta], tamaño de la muestra)."""
    tipo, v = alcance_tipo, alcance_valor
    if codigo == "kpi:VEN-01":
        venta, n = _venta(desde, hasta, tipo, v)
        return venta, n
    if codigo == "kpi:VEN-02":
        _venta_, n = _venta(desde, hasta, tipo, v, neta=False)
        return float(n), n
    if codigo == "kpi:VEN-03":
        venta, n = _venta(desde, hasta, tipo, v, neta=False)
        return (venta / n if n else None), n
    if codigo == "kpi:VEN-08":
        join, cond = _filtro_ventas(tipo, v)
        fila = _q(f"SELECT SUM(l.cantidad * l.precio_unitario), SUM(l.cantidad * l.costo_unitario), COUNT(*) FROM ventas v "
                  f"JOIN ventas_lineas l ON l.venta_id = v.id{join} WHERE COALESCE(v.anulada, 0) = 0 AND l.costo_unitario IS NOT NULL "
                  f"AND v.fecha >= '{desde}' AND v.fecha <= '{hasta}'{cond}")[0]
        venta, costo, n = float(fila[0] or 0), float(fila[1] or 0), int(fila[2] or 0)
        return ((venta - costo) / venta if venta else None), n
    if codigo == "kpi:VEN-11":
        _j, cond = _filtro_ventas(tipo, v)
        n = _uno(f"SELECT COUNT(*) FROM (SELECT v.cliente_id, MIN(v.fecha) AS primera FROM ventas v WHERE COALESCE(v.anulada, 0) = 0 "
                 f"AND v.cliente_id IS NOT NULL{cond} GROUP BY v.cliente_id) x WHERE primera >= '{desde}' AND primera <= '{hasta}'")
        return float(n or 0), int(n or 0)
    if codigo == "kpi:VEN-07":
        if tipo != "vendedor" or v in (None, ""):
            return None, 0
        venta, _n = _venta(desde, hasta, "vendedor", v)
        cuota = _uno(f"SELECT SUM(objetivo_venta) FROM objetivos_vendedores WHERE vendedor_id = {int(v)} AND mes = '{desde.isoformat()[:7]}'")
        if not cuota:
            return None, 0
        from . import catalogo
        inicio_mes = desde.replace(day=1)
        fin_mes = (inicio_mes + timedelta(days=32)).replace(day=1)
        parte = catalogo.habiles_entre(desde, hasta + timedelta(days=1)) / max(1, catalogo.habiles_entre(inicio_mes, fin_mes))
        return venta / (float(cuota) * min(1.0, parte)), 1
    if codigo == "kpi:FIN-15":
        inicial, _ = _cxc_saldo(desde - timedelta(days=1), v if tipo == "vendedor" else None)
        final, vencido = _cxc_saldo(hasta, v if tipo == "vendedor" else None)
        cond = f" AND vendedor_id = {int(v)}" if tipo == "vendedor" and v not in (None, "") else ""
        credito = float(_uno(f"SELECT SUM(importe) FROM cxc WHERE COALESCE(tipo, 'factura') = 'factura' AND fecha_emision >= '{desde}' "
                             f"AND fecha_emision <= '{hasta}'{cond}") or 0)
        corriente = final - vencido
        base = inicial + credito - corriente
        return ((inicial + credito - final) / base if base > 0 else None), 1
    if codigo == "kpi:FIN-10":
        total, vencido = _cxc_saldo(hasta, v if tipo == "vendedor" else None)
        return (vencido / total if total else 0.0), 1
    if codigo == "kpi:FIN-04":
        cond = f" AND sucursal_id = {int(v)}" if tipo == "sucursal" and v not in (None, "") else ""
        g = _uno(f"SELECT SUM(importe) FROM gastos WHERE fecha >= '{desde}' AND fecha <= '{hasta}'{cond}")
        return (float(g) if g is not None else None), 1
    if codigo == "kpi:FIN-07":
        c = _uno("SELECT SUM(saldo) FROM cuentas_bancarias")
        return (float(c) if c is not None else None), 1
    if codigo in ("kpi:INV-06", "kpi:INV-04", "kpi:INV-20"):
        return _inventario(codigo, tipo, v, desde, hasta, hoy)
    if codigo == "actividad:todas.tareas_resueltas_en_plazo_pct":
        from ..actividades import motor
        return motor.en_plazo(desde, hasta)
    if codigo.startswith("proceso:"):
        partes = codigo.split(":", 1)[1].split(".", 1)
        return proceso(partes[0], hoy).valor(partes[1], desde, hasta)
    return None, 0


def _inventario(codigo, tipo, v, desde, hasta, hoy) -> tuple[float | None, int]:
    from ..actividades.datos import Datos
    d = Datos(hoy)
    suc = int(v) if tipo == "sucursal" and v not in (None, "") else None
    if codigo == "kpi:INV-06":
        con_demanda = quebrados = 0
        for pid, prod in d.productos.items():
            if (prod.get("estado") or "activo") != "activo" or d.vdp(pid, suc, 28) <= 0:
                continue
            con_demanda += 1
            quebrados += d.stock_de(pid, suc)[0] <= 0
        return (quebrados / con_demanda if con_demanda else None), con_demanda
    if codigo == "kpi:INV-04":
        valor_stock = sum(max(0.0, float(s["cantidad"] or 0)) * d.costo(s["producto_id"]) for s in d.stock)
        cmv = _uno(f"SELECT SUM(l.cantidad * l.costo_unitario) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id "
                   f"WHERE COALESCE(v.anulada, 0) = 0 AND v.fecha >= '{hoy - timedelta(days=30)}' AND v.fecha < '{hoy}'")
        return ((valor_stock / (float(cmv) / 30)) if cmv else None), 1
    # INV-20: valor a costo de lo que no se vende antes de su fecha límite (FEFO) + lo ya vencido
    total, consumo = 0.0, {}
    lotes = sorted((s for s in d.stock if s["fecha_vencimiento"] and float(s["cantidad"] or 0) > 0 and (suc is None or s["sucursal_id"] == suc)),
                   key=lambda s: (s["producto_id"], str(s["sucursal_id"]), str(s["fecha_vencimiento"])))
    for s in lotes:
        venc = date.fromisoformat(str(s["fecha_vencimiento"])[:10])
        dias = (venc - d.hoy).days
        cant = float(s["cantidad"])
        clave = (s["producto_id"], s["sucursal_id"])
        previos = consumo.get(clave, 0.0)
        esperada = max(0.0, d.vdp(s["producto_id"], s["sucursal_id"], 28) * max(0, dias) - previos)
        consumo[clave] = previos + min(cant, esperada)
        total += (cant if dias <= 0 else max(0.0, cant - esperada)) * d.costo(s["producto_id"])
    return (round(total, 2) if lotes else 0.0), len(lotes)


# Tabla que marca desde cuándo hay datos de cada métrica (para no comparar contra meses incompletos).
ORIGEN = {"kpi:VEN-01": ("ventas", "fecha"), "kpi:VEN-02": ("ventas", "fecha"), "kpi:VEN-03": ("ventas", "fecha"),
          "kpi:VEN-08": ("ventas", "fecha"), "kpi:VEN-11": ("ventas", "fecha"), "kpi:VEN-07": ("ventas", "fecha"),
          "kpi:FIN-15": ("cxc", "fecha_emision"), "kpi:FIN-10": ("cxc", "fecha_emision"), "kpi:FIN-04": ("gastos", "fecha")}


def primera_fecha(codigo: str) -> date | None:
    t = ORIGEN.get(codigo)
    if not t:
        return None
    try:
        f = _uno(f"SELECT MIN({t[1]}) FROM {t[0]}")
        return date.fromisoformat(str(f)[:10]) if f else None
    except Exception:
        return None


def desglose(codigo: str, dimension: str, desde: date, hasta: date) -> dict:
    """Valor por sucursal / canal / categoría / vendedor (para explicar la brecha de métricas de venta)."""
    if codigo not in ("kpi:VEN-01", "kpi:VEN-02"):
        return {}
    medida = "SUM(l.cantidad * l.precio_unitario)" if codigo == "kpi:VEN-01" else "COUNT(DISTINCT v.id)"
    if dimension == "categoria":
        sql = (f"SELECT p.categoria, {medida} FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id JOIN productos p ON p.id = l.producto_id "
               f"WHERE COALESCE(v.anulada, 0) = 0 AND v.fecha >= '{desde}' AND v.fecha <= '{hasta}' GROUP BY p.categoria")
    else:
        col = {"sucursal": "v.sucursal_id", "canal": "v.canal", "vendedor": "v.vendedor_id"}[dimension]
        sql = (f"SELECT {col}, {medida} FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id WHERE COALESCE(v.anulada, 0) = 0 "
               f"AND v.fecha >= '{desde}' AND v.fecha <= '{hasta}' GROUP BY {col}")
    return {k: float(x or 0) for k, x in _q(sql) if k is not None}


def opciones_alcance() -> dict[str, list[dict]]:
    """Valores posibles de cada alcance (para el formulario de objetivos)."""
    def lista(sql):
        try:
            return [{"valor": str(a), "nombre": str(b if b is not None else a)} for a, b in _q(sql) if a is not None]
        except Exception:
            return []
    return {
        "sucursal": lista("SELECT id, nombre FROM sucursales ORDER BY nombre"),
        "vendedor": lista("SELECT id, nombre FROM vendedores ORDER BY nombre"),
        "canal": lista("SELECT DISTINCT canal, canal FROM ventas WHERE canal IS NOT NULL ORDER BY canal"),
        "categoria": lista("SELECT DISTINCT categoria, categoria FROM productos WHERE categoria IS NOT NULL ORDER BY categoria"),
    }
