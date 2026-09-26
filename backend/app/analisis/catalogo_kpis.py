"""Catálogo de 111 KPIs estándar (docs/cerebro-ia) y cuáles se pueden calcular con los datos de la fuente activa.

Cada KPI del catálogo declara las tablas del modelo canónico que necesita (y
variantes alternativas). Acá se traducen a las tablas de la plataforma y se
revisa si la fuente activa las trae con filas. Es un control a nivel de tabla:
dice qué KPIs tienen sus datos base y cuáles no, y qué dato falta para cada uno.
"""
from __future__ import annotations

from functools import lru_cache

import yaml

from .. import config
from ..erp import conector

REGISTRO = config.RAIZ / "docs" / "cerebro-ia" / "kpis" / "registry"
AREAS = {"finanzas": "Finanzas", "ventas": "Ventas", "inventario": "Inventario", "logistica": "Logística", "marketing": "Marketing"}

# Tabla del modelo canónico → tabla de la plataforma (None = la plataforma todavía no la tiene).
EQUIVALENCIAS = {
    "fct_pedido": "ventas", "fct_pedido_linea": "ventas_lineas", "fct_comprobante": "ventas", "dim_cliente": "clientes",
    "dim_producto": "productos", "fct_devolucion": "devoluciones", "fct_presupuesto": "presupuesto",
    "fct_precio_venta": "precios", "dim_promocion": "promociones", "fct_promocion_producto": "promociones",
    "fct_stock_diario": "stock", "fct_stock_lote": "stock", "fct_movimiento_stock": "movimientos_stock",
    "fct_conteo_inventario": "conteos", "dim_deposito": "sucursales", "dim_proveedor": "proveedores",
    "fct_orden_compra": "compras", "fct_orden_compra_linea": "compras_lineas", "fct_recepcion": "compras",
    "fct_lista_precio_proveedor": "costos_historial", "fct_documento_cxc": "cxc", "fct_documento_cxp": "cxp",
    "fct_cobro": "cobranzas", "fct_aplicacion_cobro": "cobranzas", "fct_pago": "pagos",
    "fct_movimiento_tesoreria": "movimientos_bancarios", "dim_cuenta_tesoreria": "cuentas_bancarias",
    "ref.tipo_cambio": "tipos_cambio",
    # Sin equivalente todavía: contabilidad, logística de envíos, CRM y marketing digital.
    "fct_asiento_linea": None, "dim_cuenta_contable": None, "fct_envio": None, "fct_evento_envio": None,
    "fct_preparacion": None, "fct_oportunidad": None, "fct_oportunidad_historial_etapa": None, "fct_lead": None,
    "fct_ads_diario": None, "dim_campana": None, "fct_web_diario": None, "fct_email_campana": None,
    "fct_suscriptores_diario": None, "fct_atribucion_pedido": None, "fct_liquidacion_pasarela": None,
    "parametro_reposicion": None, "ref.indice_precios": None, "ref.feriado": None,
}

NOMBRE_CANONICO = {
    "fct_asiento_linea": "asientos contables", "dim_cuenta_contable": "plan de cuentas", "fct_envio": "envíos",
    "fct_evento_envio": "seguimiento de envíos", "fct_preparacion": "preparación de pedidos", "fct_oportunidad": "oportunidades (CRM)",
    "fct_oportunidad_historial_etapa": "etapas del CRM", "fct_lead": "contactos interesados (leads)", "fct_ads_diario": "publicidad paga",
    "dim_campana": "campañas", "fct_web_diario": "analítica web", "fct_email_campana": "email marketing",
    "fct_suscriptores_diario": "suscriptores", "fct_atribucion_pedido": "origen de cada venta (UTM)",
    "fct_liquidacion_pasarela": "liquidaciones de medios de pago", "parametro_reposicion": "parámetros de reposición",
    "ref.indice_precios": "índice de precios", "ref.feriado": "feriados",
}


def _tabla_canonica(columna: str) -> str:
    return columna.rpartition(".")[0]


@lru_cache
def catalogo() -> list[dict]:
    if not REGISTRO.exists():
        return []
    kpis = []
    for ruta in sorted(REGISTRO.glob("kpi_*.yml")):
        k = yaml.safe_load(ruta.read_text(encoding="utf-8"))
        kpis.append(k)
    orden = list(AREAS)
    return sorted(kpis, key=lambda k: (orden.index(k.get("area")) if k.get("area") in orden else 9, k["id"]))


def _falta(tablas_canonicas: set[str], filas: dict[str, int]) -> list[str]:
    """Datos que faltan para un conjunto de tablas canónicas (vacío = están todos)."""
    faltan = []
    for t in sorted(tablas_canonicas):
        propia = EQUIVALENCIAS.get(t)
        if propia is None:
            faltan.append(NOMBRE_CANONICO.get(t, t))
        elif not filas.get(propia):
            faltan.append(propia)
    return sorted(set(faltan))


def estado(filas: dict[str, int] | None = None) -> dict:
    """Por KPI: si tiene sus datos base en la fuente activa y, si no, qué falta."""
    if filas is None:
        filas = {}
        for t in {v for v in EQUIVALENCIAS.values() if v}:
            try:
                filas[t] = conector.consultar(f"SELECT COUNT(*) FROM {t}", max_filas=1)["filas"][0][0] or 0
            except Exception:
                filas[t] = 0
    resultado, por_area = [], {a: {"area": n, "total": 0, "disponibles": 0} for a, n in AREAS.items()}
    for k in catalogo():
        req = k.get("requisitos") or {}
        base = {_tabla_canonica(c) for c in req.get("obligatorias", [])}
        faltan = _falta(base, filas)
        variante = None
        alternativas = req.get("alternativas") or []
        if alternativas and not faltan:
            opciones = [(a.get("nombre"), _falta({_tabla_canonica(c) for c in a["obligatorias"]}, filas)) for a in alternativas]
            ok = next((n for n, f in opciones if not f), None)
            if ok:
                variante = ok
            else:   # alcanza con completar una de las variantes
                faltan = [" o ".join(dict.fromkeys(" + ".join(f) for _n, f in opciones))]
        disponible = not faltan
        area = k.get("area")
        if area in por_area:
            por_area[area]["total"] += 1
            por_area[area]["disponibles"] += disponible
        resultado.append({"id": k["id"], "area": AREAS.get(area, area), "nombre": k["nombre"], "pregunta": k.get("pregunta"),
                          "unidad": k.get("unidad"), "definicion": k.get("definicion"), "disponible": disponible,
                          "variante": variante, "faltan": faltan})
    return {"kpis": resultado, "areas": list(por_area.values()), "total": len(resultado),
            "disponibles": sum(1 for k in resultado if k["disponible"])}
