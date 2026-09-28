"""Datos de demostración de Retail (sección 16): «Autoservicios del Norte», 3 sucursales + 1 depósito en el NOA.

Simula día por día, de forma determinista (semilla fija):
- ~380 productos en 10 categorías, con código de barras, costo y precio; 12 proveedores con días de visita,
  demora y pedido mínimo (uno sin días configurados).
- Tickets con patrón semanal, picos de inicio de mes, feriados, aguinaldo, estacionalidad (bebidas y helados
  en verano, yerba y alfajores en invierno), inflación mensual en precios y costos, promociones, y faltantes
  que surgen de la reposición real (el proveedor pasa sus días y a veces falla).
- Stock al cierre de cada día, recepciones y órdenes de compra históricas, mermas, recuentos, lotes con vencimiento.
- Ventas online de Tiendanube y Mercado Libre en Salta Centro, con comisiones, envíos y publicidad.
- Anomalías de caja (un cajero de Salta Norte con muchas anulaciones y descuentos manuales).
- IPC mensual (valores de ejemplo) y calendario de feriados, cobros y fechas comerciales.

Casos conocidos para las pruebas de aceptación: ver CASOS.
"""
from __future__ import annotations

import calendar
import io
import json
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from . import catalogo_demo, db

ZONA = ZoneInfo("America/Argentina/Buenos_Aires")
EMPRESA = "Autoservicios del Norte"

# Inflación mensual de ejemplo (no son datos oficiales): últimos 14 meses, del más viejo al más nuevo.
INFLACION = [0.021, 0.019, 0.023, 0.025, 0.024, 0.028, 0.026, 0.031, 0.027, 0.022, 0.019, 0.020, 0.023, 0.021]

# Casos conocidos (códigos de producto y sucursal) que usan las pruebas de aceptación.
CASOS = {
    "faltante_conocido": {"producto": "P0002", "ubicacion": "Salta Centro", "desde_dias": 13, "hasta_dias": 6},
    "stock_fantasma": {"producto": "P0014", "ubicacion": "Salta Norte", "dias_sin_venta": 6, "stock": 24},
    "producto_nuevo": {"producto": "P0383", "dias": 5},
    "sin_costo": {"producto": "P0120"},
    "stock_negativo": {"producto": "P0200", "ubicacion": "San Salvador de Jujuy", "stock": -3},
    "sobrestock": {"producto": "P0067", "ubicacion": "San Salvador de Jujuy", "dias": 120},
    "vence_pronto": {"subcategoria": "Yogures", "ubicacion": "Salta Norte", "dias": 6, "exceso": 60},
    "aumento_sin_remarcar": {"proveedor": "Lácteos del Valle", "aumento": 0.12, "hace_dias": 6},
    "cajero_anomalo": {"ubicacion": "Salta Norte", "cajero": "Cajero N3"},
    "sobreventa": {"productos": ["P0001", "P0004"], "exceso": 6},
    "precio_distinto": {"productos": ["P0005", "P0006"], "ubicacion": "San Salvador de Jujuy", "recargo": 0.12, "hace_dias": 20},
}

ATRASO = {"Golosinas del Norte": 0.3, "Limpieza Total": 0.2}      # probabilidad de llegar un día tarde; el resto 6 %
TICKETS_BASE = {"Salta Centro": 190, "Salta Norte": 150, "San Salvador de Jujuy": 120}
PESO_CATEGORIA = {"Bebidas": 1.5, "Almacén": 1.2, "Lácteos": 1.6, "Fiambrería": 1.0, "Limpieza": 0.6, "Perfumería": 0.45,
                  "Golosinas": 1.1, "Cigarrillos": 1.4, "Congelados": 0.55, "Panadería y rotisería": 1.8}
FACTOR_SEMANA = [0.95, 0.9, 0.95, 1.0, 1.15, 1.3, 0.7]            # lunes … domingo
HORAS = list(range(8, 22))
PESO_HORA = [3, 5, 8, 10, 9, 6, 5, 5, 7, 9, 10, 8, 5, 2]
HORAS_DOMINGO = [9, 10, 11, 12]
PESO_HORA_DOMINGO = [4, 8, 9, 6]
VIDA_UTIL = {"Leches": 10, "Yogures": 25, "Quesos": 45, "Mantecas y cremas": 40, "Fiambres": 20, "Salchichas": 30,
             "Hamburguesas y rebozados": 180, "Helados": 240, "Vegetales congelados": 300, "Elaboración propia": 2}
MEDIOS = [("efectivo", 0.35, 0.0, 0), ("debito", 0.30, 0.008, 1), ("credito", 0.15, 0.018, 10), ("qr", 0.15, 0.006, 0),
          ("transferencia", 0.03, 0.0, 0), ("cuenta_corriente", 0.02, 0.0, 30)]

FERIADOS = {  # nacionales (con traslados aproximados) y locales de Salta/Jujuy; valores de ejemplo
    "2025-08-15": "Paso a la Inmortalidad del Gral. San Martín", "2025-10-10": "Día de la Diversidad Cultural",
    "2025-11-21": "Día de la Soberanía Nacional", "2025-12-08": "Inmaculada Concepción", "2025-12-25": "Navidad",
    "2026-01-01": "Año Nuevo", "2026-02-16": "Carnaval", "2026-02-17": "Carnaval", "2026-03-24": "Día de la Memoria",
    "2026-04-02": "Día de Malvinas", "2026-04-03": "Viernes Santo", "2026-05-01": "Día del Trabajador",
    "2026-05-25": "Revolución de Mayo", "2026-06-15": "Paso a la Inmortalidad del Gral. Güemes",
    "2026-06-20": "Día de la Bandera", "2026-07-09": "Día de la Independencia", "2026-08-17": "Paso a la Inmortalidad del Gral. San Martín",
    "2026-09-15": "Milagro de Salta (local)",
}
COMERCIALES = {"2025-10-19": "Día de la Madre", "2026-05-11": "Hot Sale", "2026-06-21": "Día del Padre", "2026-08-16": "Día del Niño",
               "2025-11-03": "CyberMonday"}
AGUINALDO = ["2025-12-18", "2026-06-30"]


@dataclass
class Escala:
    dias: int = 395                  # 13 meses
    tickets: float = 1.0             # multiplica TICKETS_BASE
    online_dias: int = 180
    productos: int | None = None     # recortar el catálogo (pruebas)


@dataclass
class _Prod:
    id: int
    codigo: str
    nombre: str
    categoria: str
    sub: str
    perecedero: bool
    precio_hoy: float
    margen: float
    proveedor: str
    estacion: str | None
    bulto: int
    peso: float
    kg: bool
    dia_remarca: int
    sin_costo: bool = False
    nuevo_desde: date | None = None
    precios: list = field(default_factory=list)   # [(desde, precio)]


def _copy(conn, tabla: str, columnas: list[str], filas: list[tuple]) -> None:
    db.copiar(conn, tabla, columnas, filas)


def _indices(meses: list[date]) -> dict[date, float]:
    """IPC de ejemplo: índice que crece con INFLACION; el último mes vale 9.850 (orden de magnitud realista)."""
    tasas = INFLACION[-len(meses):]
    valores = [1.0]
    for t in tasas[1:]:
        valores.append(valores[-1] * (1 + t))
    escala = 9850 / valores[-1]
    return {m: round(v * escala, 4) for m, v in zip(meses, valores)}


def _mes(d: date) -> date:
    return d.replace(day=1)


def _sumar_meses(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


def _estacion(estacion: str | None, d: date) -> float:
    if not estacion:
        return 1.0
    angulo = 2 * math.pi * (d.timetuple().tm_yday - 15) / 365.25     # pico de verano a mediados de enero
    return 1 + 0.45 * math.cos(angulo) if estacion == "verano" else 1 - 0.28 * math.cos(angulo)


def _factor_dia(d: date) -> float:
    f = FACTOR_SEMANA[d.weekday()]
    if d.day <= 5:
        f *= 1.18              # cobro de sueldos
    elif d.day >= 26:
        f *= 0.9
    iso = d.isoformat()
    if iso in FERIADOS:
        f *= 0.72
    if (d + timedelta(days=1)).isoformat() in FERIADOS:
        f *= 1.12
    if iso in AGUINALDO or (d - timedelta(days=1)).isoformat() in AGUINALDO:
        f *= 1.1
    return f


def ya_cargada(conn, org_id: int) -> bool:
    return bool(db.fila(conn, "SELECT 1 FROM productos WHERE org_id=%s LIMIT 1", (org_id,)))


def cargar(org_id: int | None = None, hoy: date | None = None, escala: Escala | None = None, semilla: int = 20260928,
           calcular: bool = True) -> dict:
    """Carga la demo en la empresa «Autoservicios del Norte» (si todavía no tiene productos). Devuelve un resumen."""
    escala = escala or Escala()
    rng = random.Random(semilla)
    ahora = datetime.now(ZONA)
    hoy = hoy or ahora.date()
    hora_corte = ahora.hour if hoy == ahora.date() else 21      # hoy: tickets hasta la hora actual
    inicio = hoy - timedelta(days=escala.dias - 1)
    resumen: dict = {}

    with db.transaccion(superadmin=True) as conn:
        if org_id is None:
            fila = db.fila(conn, "SELECT id FROM organizaciones WHERE nombre=%s", (EMPRESA,))
            if not fila:
                raise RuntimeError(f"No existe la empresa «{EMPRESA}»: cargá primero la semilla.")
            org_id = fila["id"]
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))
        if ya_cargada(conn, org_id):
            return {"cargada": False, "motivo": "La empresa ya tiene productos."}

        ubic = {f["nombre"]: f["id"] for f in db.filas(conn, "SELECT id, nombre FROM ubicaciones WHERE org_id=%s", (org_id,))}
        sucursales = [n for n in TICKETS_BASE if n in ubic]
        deposito = next((n for n in ubic if n.startswith("Depósito")), None)
        canales = {f["codigo"]: f["id"] for f in db.filas(conn, "SELECT id, codigo FROM canales WHERE org_id=%s", (org_id,))}
        with conn.cursor() as cur:
            cur.execute("UPDATE canales SET activo=true WHERE org_id=%s AND codigo='ecommerce'", (org_id,))
        plataformas = {}
        for tipo, nombre, canal in (("tiendanube", "Tiendanube", "ecommerce"), ("mercadolibre", "Mercado Libre", "ecommerce"),
                                    ("caja_propia", "Cajas de los locales", "fisico")):
            plataformas[tipo] = db.fila(conn, "INSERT INTO plataformas (org_id, tipo, nombre, canal_id, ubicacion_despacho_id) "
                                              "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                                        (org_id, tipo, nombre, canales[canal], ubic.get("Salta Centro")))["id"]

        # ---------------------------------------------------------------- catálogo
        catalogo = catalogo_demo.productos()
        if escala.productos:
            fijos = {c["producto"] for c in CASOS.values() if "producto" in c} | {x for c in CASOS.values() for x in c.get("productos", [])}
            paso = max(1, len(catalogo) // escala.productos)
            catalogo = [p for i, p in enumerate(catalogo) if i % paso == 0 or p["codigo"] in fijos]
        cat_ids: dict[tuple, int] = {}
        for p in catalogo:
            if (p["categoria"], None) not in cat_ids:
                cat_ids[(p["categoria"], None)] = db.fila(conn, "INSERT INTO categorias (org_id, nombre) VALUES (%s,%s) RETURNING id",
                                                          (org_id, p["categoria"]))["id"]
            if (p["categoria"], p["subcategoria"]) not in cat_ids:
                cat_ids[(p["categoria"], p["subcategoria"])] = db.fila(
                    conn, "INSERT INTO categorias (org_id, nombre, padre_id) VALUES (%s,%s,%s) RETURNING id",
                    (org_id, p["subcategoria"], cat_ids[(p["categoria"], None)]))["id"]

        proveedores = {}
        for nombre, dias, demora, minimo, bultos, pago in catalogo_demo.PROVEEDORES:
            proveedores[nombre] = {"id": db.fila(conn, "INSERT INTO proveedores (org_id, razon_social, cuit, contacto, email_oc, dias_visita, "
                                                       "demora_entrega_dias, pedido_minimo_monto, pedido_minimo_bultos, condiciones_pago) "
                                                       "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                                                 (org_id, nombre, f"30-{rng.randint(50000000, 79999999)}-{rng.randint(0, 9)}",
                                                  "Preventista", f"pedidos@{nombre.lower().split()[0].replace('á', 'a').replace('í', 'i')}.demo",
                                                  dias, demora, minimo, bultos, pago))["id"],
                                   "dias": dias, "demora": demora}

        prods: list[_Prod] = []
        orden = list(range(len(catalogo)))
        rng.shuffle(orden)
        popularidad = {i: 1 / ((r + 1) ** 0.85) for r, i in enumerate(orden)}   # distribución tipo Pareto
        for i, p in enumerate(catalogo):
            maestro_id = None
            if p["ean"]:
                maestro_id = db.fila(conn, "INSERT INTO productos_maestros (ean, nombre, marca, fabricante, categoria, subcategoria, presentacion, "
                                           "unidad_medida, perecedero) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                                           "ON CONFLICT (ean) DO UPDATE SET nombre=EXCLUDED.nombre RETURNING id",
                                     (p["ean"], p["nombre"], p["marca"], p["marca"], p["categoria"], p["subcategoria"], p["presentacion"],
                                      "unidad", p["perecedero"]))["id"]
            pid = db.fila(conn, "INSERT INTO productos (org_id, maestro_id, codigo_interno, nombre, ean, marca, categoria_id, unidad, perecedero, "
                                "estado_mapeo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                          (org_id, maestro_id, p["codigo"], p["nombre"], p["ean"], p["marca"], cat_ids[(p["categoria"], p["subcategoria"])],
                           p.get("unidad", "unidad"), p["perecedero"], "mapeado" if p["ean"] else "propio"))["id"]
            prods.append(_Prod(id=pid, codigo=p["codigo"], nombre=p["nombre"], categoria=p["categoria"], sub=p["subcategoria"],
                               perecedero=p["perecedero"], precio_hoy=p["precio"], margen=p["margen"] + rng.uniform(-0.04, 0.04),
                               proveedor=p["proveedor"], estacion=p["estacion"], bulto=p["bulto"],
                               peso=popularidad[i] * PESO_CATEGORIA.get(p["categoria"], 1.0), kg=p.get("unidad") == "kg",
                               dia_remarca=rng.randint(1, 20)))
        por_codigo = {p.codigo: p for p in prods}
        por_id = {p.id: p for p in prods}
        f_oc_l_recibido: dict = {}
        if CASOS["sin_costo"]["producto"] in por_codigo:
            por_codigo[CASOS["sin_costo"]["producto"]].sin_costo = True
        if CASOS["producto_nuevo"]["producto"] in por_codigo:
            por_codigo[CASOS["producto_nuevo"]["producto"]].nuevo_desde = hoy - timedelta(days=CASOS["producto_nuevo"]["dias"])
        # El faltante conocido tiene que ser un producto de venta frecuente.
        if CASOS["faltante_conocido"]["producto"] in por_codigo:
            por_codigo[CASOS["faltante_conocido"]["producto"]].peso = max(p.peso for p in prods) * 0.6
        if CASOS["stock_fantasma"]["producto"] in por_codigo:
            por_codigo[CASOS["stock_fantasma"]["producto"]].peso = max(p.peso for p in prods) * 0.5

        # ---------------------------------------------------------------- precios, costos e IPC
        meses = [_sumar_meses(_mes(inicio), k) for k in range(0, (hoy.year - inicio.year) * 12 + hoy.month - inicio.month + 1)]
        ipc = _indices(meses)
        ultimo = ipc[meses[-1]]
        aumento = CASOS["aumento_sin_remarcar"]
        fecha_aumento = hoy - timedelta(days=aumento["hace_dias"])

        def precio_en(p: _Prod, d: date) -> float:
            m = _mes(d) if d.day >= p.dia_remarca else _sumar_meses(_mes(d), -1)
            m = min(max(m, meses[0]), meses[-1])
            return round(p.precio_hoy * ipc[m] / ultimo / 10) * 10 or 10

        def costo_en(p: _Prod, d: date) -> float | None:
            if p.sin_costo:
                return None
            ref = precio_en(p, d + timedelta(days=5))               # el proveedor aumenta unos días antes
            costo = ref * (1 - p.margen)
            if p.proveedor == aumento["proveedor"] and d >= fecha_aumento:
                costo *= 1 + aumento["aumento"]
            return round(costo, 2)

        filas_precios = []
        for p in prods:
            anterior = None
            d = inicio
            while d <= hoy:
                pr = precio_en(p, d)
                if pr != anterior:
                    if p.precios:
                        p.precios[-1] = (p.precios[-1][0], p.precios[-1][1], d - timedelta(days=1))
                    p.precios.append((d, pr, None))
                    anterior = pr
                d += timedelta(days=1)
            for desde, pr, hasta in p.precios:
                filas_precios.append((org_id, p.id, None, None, f"{pr:.2f}", desde, hasta, "demo"))
                if p.categoria in ("Bebidas", "Almacén", "Perfumería", "Limpieza") and desde >= hoy - timedelta(days=escala.online_dias):
                    filas_precios.append((org_id, p.id, None, canales["ecommerce"], f"{round(pr * 1.08 / 10) * 10:.2f}", desde, hasta, "demo"))
        # Caso conocido: en una sucursal se remarcaron a mano algunos productos (precio distinto al resto).
        pd_caso = CASOS["precio_distinto"]
        for cod in pd_caso["productos"]:
            if cod in por_codigo and pd_caso["ubicacion"] in ubic:
                p = por_codigo[cod]
                filas_precios.append((org_id, p.id, ubic[pd_caso["ubicacion"]], None,
                                      f"{round(float(precio_en(p, hoy)) * (1 + pd_caso['recargo']) / 10) * 10:.2f}",
                                      hoy - timedelta(days=pd_caso["hace_dias"]), None, "demo"))
        _copy(conn, "precios", ["org_id", "producto_id", "ubicacion_id", "canal_id", "precio", "desde", "hasta", "origen"], filas_precios)

        filas_pp = []
        for p in prods:
            c = costo_en(p, hoy)
            filas_pp.append((org_id, p.id, proveedores[p.proveedor]["id"], None if c is None else f"{c:.4f}", "bulto", p.bulto, 1, True, 1,
                             f"{p.proveedor[:3].upper()}-{p.codigo}"))
        _copy(conn, "producto_proveedores", ["org_id", "producto_id", "proveedor_id", "costo", "unidad_compra", "unidades_por_bulto",
                                             "multiplo_compra", "principal", "prioridad", "codigo_proveedor"], filas_pp)
        # Listas de precios del proveedor: una por mes, más la del aumento reciente sin remarcar.
        for nombre, prov in proveedores.items():
            suyos = [p for p in prods if p.proveedor == nombre and not p.sin_costo]
            fechas = [max(inicio, m + timedelta(days=5)) for m in meses[-3:]]
            if nombre == aumento["proveedor"]:
                fechas.append(fecha_aumento)
            for f in fechas:
                lista_id = db.fila(conn, "INSERT INTO listas_precios_proveedor (org_id, proveedor_id, vigencia_desde, origen) VALUES (%s,%s,%s,'demo') RETURNING id",
                                   (org_id, prov["id"], f))["id"]
                _copy(conn, "listas_precios_proveedor_lineas", ["org_id", "lista_id", "producto_id", "codigo", "descripcion", "costo", "costo_anterior"],
                      [(org_id, lista_id, p.id, f"{nombre[:3].upper()}-{p.codigo}", p.nombre, f"{costo_en(p, f):.4f}",
                        f"{costo_en(p, f - timedelta(days=20)):.4f}") for p in suyos])

        with conn.cursor() as cur:
            for m in meses:
                cur.execute("INSERT INTO indice_precios (periodo, indice, fuente) VALUES (%s,%s,'demo (valores de ejemplo)') "
                            "ON CONFLICT (periodo) DO NOTHING", (m, ipc[m]))
            for iso, nombre in FERIADOS.items():
                cur.execute("INSERT INTO calendario (org_id, fecha, tipo, nombre) SELECT NULL,%s,'feriado',%s "
                            "WHERE NOT EXISTS (SELECT 1 FROM calendario WHERE org_id IS NULL AND fecha=%s AND tipo='feriado')",
                            (iso, nombre, iso))
            for iso, nombre in COMERCIALES.items():
                cur.execute("INSERT INTO calendario (org_id, fecha, tipo, nombre) VALUES (%s,%s,'comercial',%s)", (org_id, iso, nombre))
            for iso in AGUINALDO:
                cur.execute("INSERT INTO calendario (org_id, fecha, tipo, nombre) VALUES (%s,%s,'cobro','Aguinaldo')", (org_id, iso))

        # ---------------------------------------------------------------- promociones (una tanda por mes)
        promos: list[tuple[date, date, set, float, int]] = []
        filas_promo = []
        for k, m in enumerate(meses):
            elegidos = rng.sample(prods, min(6, len(prods)))
            desde = max(m + timedelta(days=9), inicio)
            hasta = min(desde + timedelta(days=9), hoy + timedelta(days=4))
            if desde > hoy:
                continue
            pct = rng.choice([0.15, 0.2, 0.25, 0.3])
            promos.append((desde, hasta, {p.id for p in elegidos}, pct, k + 1))
            filas_promo.append((k + 1, org_id, f"Ofertas de {m.strftime('%m/%Y')}", "descuento_pct", json.dumps({"porcentaje": pct}),
                                "{" + ",".join(str(p.id) for p in elegidos) + "}", desde, hasta, "manual",
                                "activa" if hasta >= hoy else "finalizada"))
        base_promo = (db.fila(conn, "SELECT coalesce(max(id), 0) AS m FROM promociones")["m"])
        filas_promo = [(base_promo + f[0],) + f[1:] for f in filas_promo]
        promos = [(a, b, c, d, base_promo + e) for a, b, c, d, e in promos]
        _copy(conn, "promociones", ["id", "org_id", "nombre", "tipo", "parametros", "productos", "desde", "hasta", "origen", "estado"], filas_promo)

        # ---------------------------------------------------------------- simulación día por día
        ids = {t: db.fila(conn, f"SELECT coalesce(max(id), 0) AS m FROM {t}")["m"] for t in
               ("tickets", "ordenes_compra", "recepciones", "recuentos", "stock_lotes")}
        t_id = ids["tickets"]
        oc_id = ids["ordenes_compra"]
        rc_id = ids["recepciones"]
        f_tickets, f_lineas, f_pagos, f_anul, f_costos_canal = [], [], [], [], []
        f_stock_diario, f_mov, f_oc, f_oc_l, f_rc, f_rc_l = [], [], [], [], [], []
        stock = {s: {} for s in sucursales}
        pendientes = {s: [] for s in sucursales}            # (fecha_llegada, oc_id, proveedor, [(prod, cant)])
        pendientes_nums = {s: set() for s in sucursales}
        vendidos_dia = {s: {} for s in sucursales}
        from collections import deque
        recientes = {s: {p.id: deque(maxlen=14) for p in prods} for s in sucursales}
        cajeros = {s: [f"Cajero {s.split()[-1][0]}{k}" for k in (1, 2, 3)] for s in sucursales}
        caso_anomalo = CASOS["cajero_anomalo"]
        falt = CASOS["faltante_conocido"]
        fantasma = CASOS["stock_fantasma"]
        suma_pesos = sum(p.peso for p in prods)
        items_por_ticket = 3.2

        def vpd_esperada(p: _Prod, s: str) -> float:
            return TICKETS_BASE[s] * escala.tickets * items_por_ticket * p.peso / suma_pesos * 1.12

        for s in sucursales:
            for p in prods:
                stock[s][p.id] = 0 if p.nuevo_desde else round(vpd_esperada(p, s) * 12) + p.bulto

        def reponer(s: str, d: date) -> None:
            """El proveedor pasa (según sus días) y se le pide hasta cubrir el próximo ciclo; llega tras su demora."""
            for nombre, prov in proveedores.items():
                dias = prov["dias"] or []
                if dias and d.weekday() not in dias:
                    continue
                if not dias and (d - inicio).days % 10:
                    continue
                demora = prov["demora"] if prov["demora"] is not None else 3
                ciclo = 10 if not dias else min(((w - d.weekday()) % 7) or 7 for w in dias)
                en_camino = {}
                for _, _, pn, lineas in pendientes[s]:
                    if pn == nombre:
                        for pid, c in lineas:
                            en_camino[pid] = en_camino.get(pid, 0) + c
                lineas = []
                for p in prods:
                    if p.proveedor != nombre or (p.nuevo_desde and d < p.nuevo_desde):
                        continue
                    reciente = recientes[s][p.id]
                    ritmo = max(vpd_esperada(p, s) * _estacion(p.estacion, d), sum(reciente) / len(reciente) if reciente else 0)
                    # Sin sistema, el encargado pide «a ojo»: a veces corto, a veces largo (por eso hay faltantes y sobrestock).
                    objetivo = ritmo * (ciclo + demora + 1) * rng.uniform(0.7, 1.25)
                    falta = objetivo - stock[s][p.id] - en_camino.get(p.id, 0)
                    if falta > 0:
                        bultos = math.ceil(falta / p.bulto)
                        lineas.append((p, bultos * p.bulto))
                if not lineas:
                    continue
                nonlocal_ids["oc"] += 1
                num = nonlocal_ids["oc"]
                esperada = d + timedelta(days=demora)
                # Algunos proveedores llegan un día tarde de vez en cuando (puntualidad en el análisis de proveedores).
                llegada = esperada + timedelta(days=1 if rng.random() < ATRASO.get(nombre, 0.06) else 0)
                total = sum(c * (costo_en(p, d) or 0) for p, c in lineas)
                creada = datetime.combine(d, time(9, 30), ZONA)
                f_oc.append((num, org_id, f"OC-{num:06d}", prov["id"], ubic[s], "recibida" if llegada <= hoy else "enviada", "manual",
                             f"{total:.2f}", esperada, "manual", datetime.combine(d, time(10), ZONA), datetime.combine(d, time(10, 30), ZONA),
                             creada, datetime.combine(llegada, time(9), ZONA) if llegada <= hoy else creada))
                for p, c in lineas:
                    f_oc_l.append((org_id, num, p.id, ubic[s], c, c, c // p.bulto, None if costo_en(p, d) is None else f"{costo_en(p, d):.4f}"))
                pendientes[s].append((llegada, num, nombre, [(p.id, c) for p, c in lineas]))
                pendientes_nums[s].add(num)

        nonlocal_ids = {"oc": oc_id, "rc": rc_id}
        venc = CASOS["vence_pronto"]
        yogures = [p for p in prods if p.sub == venc["subcategoria"]]
        vence_caso = max(yogures, key=lambda p: p.peso) if yogures and venc["ubicacion"] in ubic else None

        def _casos_del_dia(s: str) -> None:
            """Casos conocidos del último día (se aplican antes de vender, así el cierre del día ya los refleja)."""
            if s == fantasma["ubicacion"] and fantasma["producto"] in por_codigo:
                stock[s][por_codigo[fantasma["producto"]].id] = fantasma["stock"]
            neg = CASOS["stock_negativo"]
            if s == neg["ubicacion"] and neg["producto"] in por_codigo:
                stock[s][por_codigo[neg["producto"]].id] = neg["stock"]
            sob = CASOS["sobrestock"]
            if sob["producto"] in por_codigo:
                p = por_codigo[sob["producto"]]
                if s == sob["ubicacion"]:
                    stock[s][p.id] = round(vpd_esperada(p, s) * sob["dias"])
                if s == "Salta Centro":
                    stock[s][p.id] = 0
                    _sin_pedidos(s, p.id)          # a Salta Centro le falta y no tiene nada en camino
            if vence_caso and s == venc["ubicacion"]:
                stock[s][vence_caso.id] += venc["exceso"]
            if vence_caso and s == "Salta Centro":
                stock[s][vence_caso.id] = 0         # en Salta Centro se vende y no hay: ahí se puede rescatar el lote
                _sin_pedidos(s, vence_caso.id)

        def _sin_pedidos(s: str, pid: int) -> None:
            pendientes[s] = [(ll, num, pn, [(x, c) for x, c in lineas if x != pid]) for ll, num, pn, lineas in pendientes[s]]
            for i, f in enumerate(f_oc_l):
                if f[2] == pid and f[3] == ubic[s] and f[1] in {num for _, num, _, _ in pendientes[s]} | pendientes_nums[s]:
                    f_oc_l[i] = f[:4] + (0, 0, 0) + f[7:]
        online_desde = hoy - timedelta(days=escala.online_dias)
        d = inicio
        while d <= hoy:
            f_dia = _factor_dia(d)
            crecimiento = 1 + 0.05 * (d - inicio).days / 365
            activos_promo = [(ids_, pct, pid_) for (a, b, ids_, pct, pid_) in promos if a <= d <= b]
            for s in sucursales:
                # 1) llegan las compras (a veces el proveedor falla y no entrega: así aparecen faltantes reales)
                quedan = []
                for llegada, num, nombre, lineas in pendientes[s]:
                    if llegada > d:
                        quedan.append((llegada, num, nombre, lineas))
                        continue
                    falla = rng.random() < 0.08
                    nonlocal_ids["rc"] += 1
                    rc = nonlocal_ids["rc"]
                    f_rc.append((rc, org_id, num, proveedores[nombre]["id"], ubic[s], datetime.combine(d, time(8, 30), ZONA), f"Remito {rc:07d}"))
                    for pid, c in lineas:
                        p = por_id[pid]
                        recibido = 0 if falla else (c if rng.random() > 0.05 else max(0, c - p.bulto))
                        if s == falt["ubicacion"] and p.codigo == falt["producto"] and \
                                hoy - timedelta(days=falt["desde_dias"] + 8) <= d <= hoy - timedelta(days=falt["hasta_dias"] + 1):
                            recibido = 0          # faltante conocido: el proveedor no entrega
                        costo = costo_en(p, d)
                        f_rc_l.append((org_id, rc, pid, recibido, None if costo is None else f"{costo:.4f}", c,
                                       None if costo is None else f"{costo:.4f}"))
                        f_oc_l_recibido[(num, pid)] = recibido
                        if recibido:
                            stock[s][pid] += recibido
                            f_mov.append((org_id, pid, ubic[s], datetime.combine(d, time(8, 30), ZONA), "compra", recibido,
                                          None if costo is None else f"{costo:.4f}", "recepcion", rc, None))
                pendientes[s] = quedan
                if d == hoy:
                    _casos_del_dia(s)
                for p in prods:
                    if p.nuevo_desde == d:   # llega la primera mercadería del producto nuevo
                        stock[s][p.id] = round(vpd_esperada(p, s) * 14) + p.bulto
                # faltante conocido: se vacía el stock al inicio del período
                if s == falt["ubicacion"] and d == hoy - timedelta(days=falt["desde_dias"]) and falt["producto"] in por_codigo:
                    pid = por_codigo[falt["producto"]].id
                    if stock[s][pid] > 0:
                        f_mov.append((org_id, pid, ubic[s], datetime.combine(d, time(7), ZONA), "merma", -stock[s][pid], None, None, None,
                                      "Rotura en depósito"))
                        stock[s][pid] = 0
                if s == falt["ubicacion"] and d == hoy - timedelta(days=falt["hasta_dias"]) and falt["producto"] in por_codigo:
                    p = por_codigo[falt["producto"]]
                    stock[s][p.id] += round(vpd_esperada(p, s) * 14)
                # 2) ventas del día
                cerrado = d.weekday() == 6 and d.isoformat() in FERIADOS
                n_tickets = 0 if cerrado else max(0, round(TICKETS_BASE[s] * escala.tickets * f_dia * crecimiento * rng.uniform(0.9, 1.1)))
                pesos = []
                for p in prods:
                    w = p.peso * _estacion(p.estacion, d)
                    if p.nuevo_desde and d < p.nuevo_desde:
                        w = 0
                    if s == fantasma["ubicacion"] and p.codigo == fantasma["producto"] and d > hoy - timedelta(days=fantasma["dias_sin_venta"]):
                        w = 0             # stock fantasma: el sistema dice que hay, pero no se vende (no está en góndola)
                    for ids_, pct, _ in activos_promo:
                        if p.id in ids_:
                            w *= 1.8
                    pesos.append(w)
                acumulados = []
                total_w = 0.0
                for w in pesos:
                    total_w += w
                    acumulados.append(total_w)
                domingo = d.weekday() == 6
                horas, pesos_h = (HORAS_DOMINGO, PESO_HORA_DOMINGO) if domingo else (HORAS, PESO_HORA)
                for _ in range(n_tickets):
                    hora = rng.choices(horas, pesos_h)[0]
                    if d == hoy and hora > hora_corte:
                        continue
                    minuto = rng.randint(0, 59)
                    cajero = cajeros[s][0 if hora < 14 else 1] if rng.random() < 0.8 else cajeros[s][2]
                    anomalo = s == caso_anomalo["ubicacion"] and cajero == caso_anomalo["cajero"]
                    k = 1 + min(12, _poisson(rng, items_por_ticket - 1))
                    elegidos = {}
                    for idx in (_elegir(rng, acumulados, total_w) for _ in range(k)):
                        if idx is None:
                            continue
                        p = prods[idx]
                        q = round(rng.uniform(0.25, 1.5), 3) if p.kg else rng.choices([1, 2, 3], [80, 15, 5])[0]
                        if p.categoria == "Bebidas" and rng.random() < 0.2:
                            q += 1
                        if stock[s][p.id] < q:
                            continue      # venta perdida por faltante
                        elegidos[p.id] = (p, elegidos.get(p.id, (p, 0))[1] + q)
                    if not elegidos:
                        continue
                    t_id += 1
                    fh = datetime.combine(d, time(hora, minuto), ZONA)
                    anulado = rng.random() < (0.04 if anomalo else 0.006)
                    total = 0.0
                    for pid, (p, q) in elegidos.items():
                        lista = precio_en(p, d)
                        cobrado = lista
                        promo_id = None
                        for ids_, pct, prid in activos_promo:
                            if pid in ids_:
                                cobrado = round(lista * (1 - pct), 2)
                                promo_id = prid
                        manual = rng.random() < (0.06 if anomalo else 0.008)
                        if manual:
                            cobrado = round(cobrado * rng.choice([0.9, 0.85, 0.8]), 2)
                        descuento = round((lista - cobrado) * q, 2)
                        costo = costo_en(p, d)
                        f_lineas.append((org_id, t_id, ubic[s], d, pid, q, f"{lista:.2f}", f"{cobrado:.2f}", f"{descuento:.2f}", manual,
                                         None if costo is None else f"{costo:.4f}", promo_id))
                        total += cobrado * q
                        if not anulado:
                            stock[s][pid] -= q
                            vendidos_dia[s][pid] = vendidos_dia[s].get(pid, 0) + q
                    f_tickets.append((t_id, org_id, ubic[s], canales["fisico"], plataformas["caja_propia"], f"PV{s[0]}{1 + (hora >= 14)}",
                                      cajero, fh, None, f"{total:.2f}", "anulado" if anulado else "confirmado", f"T{t_id:08d}", "demo"))
                    if anulado:
                        f_anul.append((org_id, t_id, ubic[s], "anulacion", cajero, rng.choice(["Error de carga", "Cliente desistió", "Sin motivo"]),
                                       fh + timedelta(minutes=2), f"{total:.2f}"))
                        continue
                    medio = rng.choices(MEDIOS, [m[1] for m in MEDIOS])[0]
                    f_pagos.append((org_id, t_id, ubic[s], medio[0], f"{total:.2f}", 3 if medio[0] == "credito" and rng.random() < 0.3 else 1,
                                    f"{total * medio[2]:.2f}", medio[3]))
                    # devolución ocasional, días después
                    if rng.random() < 0.004 and d < hoy:
                        pid, (p, q) = next(iter(elegidos.items()))
                        dd = min(hoy, d + timedelta(days=rng.randint(1, 3)))
                        t_id += 1
                        cobrado = precio_en(p, d)
                        f_tickets.append((t_id, org_id, ubic[s], canales["fisico"], plataformas["caja_propia"], f"PV{s[0]}1", cajero,
                                          datetime.combine(dd, time(11, 15), ZONA), None, f"{-cobrado * q:.2f}", "devuelto", f"T{t_id:08d}", "demo"))
                        costo = costo_en(p, d)
                        f_lineas.append((org_id, t_id, ubic[s], dd, pid, -q, f"{cobrado:.2f}", f"{cobrado:.2f}", "0.00", False,
                                         None if costo is None else f"{costo:.4f}", None))
                        f_anul.append((org_id, t_id, ubic[s], "devolucion", cajero, "Producto en mal estado", datetime.combine(dd, time(11, 15), ZONA),
                                       f"{cobrado * q:.2f}"))
                        f_pagos.append((org_id, t_id, ubic[s], "efectivo", f"{-cobrado * q:.2f}", 1, "0.00", 0))
                        stock[s][pid] += q
                # 3) online (Tiendanube y Mercado Libre, despacha Salta Centro, mismo stock)
                if s == "Salta Centro" and d >= online_desde:
                    for plat, media, comision in (("tiendanube", 6, 0.03), ("mercadolibre", 5, 0.14)):
                        for _ in range(_poisson(rng, media * escala.tickets * (1 + (d - online_desde).days / 360))):
                            hora = rng.randint(8, 23) if d < hoy else rng.randint(0, max(0, hora_corte))
                            candidatos = [i for i, p in enumerate(prods) if p.categoria in ("Bebidas", "Almacén", "Perfumería", "Limpieza")]
                            if not candidatos:
                                break
                            elegidos = {}
                            for i in rng.sample(candidatos, min(len(candidatos), rng.randint(1, 3))):
                                p = prods[i]
                                q = rng.choice([1, 1, 2])
                                if stock[s][p.id] >= q:
                                    elegidos[p.id] = (p, q)
                            if not elegidos:
                                continue
                            t_id += 1
                            fh = datetime.combine(d, time(min(hora, 23), rng.randint(0, 59)), ZONA)
                            total = 0.0
                            for pid, (p, q) in elegidos.items():
                                pr = round(precio_en(p, d) * 1.08 / 10) * 10
                                costo = costo_en(p, d)
                                f_lineas.append((org_id, t_id, ubic[s], d, pid, q, f"{pr:.2f}", f"{pr:.2f}", "0.00", False,
                                                 None if costo is None else f"{costo:.4f}", None))
                                total += pr * q
                                stock[s][pid] -= q
                                vendidos_dia[s][pid] = vendidos_dia[s].get(pid, 0) + q
                            f_tickets.append((t_id, org_id, ubic[s], canales["ecommerce"], plataformas[plat], plat, None, fh, None,
                                              f"{total:.2f}", "confirmado", f"{plat[:2].upper()}{t_id:08d}", plat))
                            f_pagos.append((org_id, t_id, ubic[s], "plataforma", f"{total:.2f}", 1, f"{total * comision:.2f}", 14))
                            # Envío gratis de Mercado Libre (desde $ 35.000): el costo lo paga el vendedor; por debajo lo paga el comprador.
                            envio = 3500.0 if plat == "mercadolibre" and total >= 35000 else 0.0
                            f_costos_canal.append((org_id, plataformas[plat], t_id, d, f"{total * comision:.2f}", f"{envio:.2f}", "0.00"))
                    if d.day == 1:
                        for plat, publicidad in (("tiendanube", 60000), ("mercadolibre", 90000)):
                            f_costos_canal.append((org_id, plataformas[plat], None, d, "0.00", "0.00", f"{publicidad * escala.tickets:.2f}"))
                # 4) cierre del día: stock y movimientos de venta agregados
                for p in prods:
                    v = vendidos_dia[s].pop(p.id, 0)
                    if stock[s][p.id] > 0 or v:
                        recientes[s][p.id].append(v)
                    if v:
                        f_mov.append((org_id, p.id, ubic[s], datetime.combine(d, time(22), ZONA), "venta", -v, None, "ventas_del_dia", None, None))
                    if p.nuevo_desde and d < p.nuevo_desde:
                        continue          # el producto nuevo todavía no existía
                    f_stock_diario.append((org_id, p.id, ubic[s], d, round(stock[s][p.id], 3), stock[s][p.id] > 0))
                # 5) pedidos a proveedores
                if d < hoy:
                    reponer(s, d)
                # 6) mermas semanales de perecederos
                if d.weekday() == 0 and d < hoy:
                    for p in rng.sample([x for x in prods if x.perecedero], min(3, len([x for x in prods if x.perecedero]))):
                        q = min(max(1, round(vpd_esperada(p, s) * 0.3)), max(0, math.floor(stock[s][p.id])))
                        if q > 0:
                            stock[s][p.id] -= q
                            costo = costo_en(p, d)
                            f_mov.append((org_id, p.id, ubic[s], datetime.combine(d, time(21), ZONA), rng.choice(["vencimiento", "merma"]),
                                          -q, None if costo is None else f"{costo:.4f}", None, None, rng.choice(["Vencido", "Rotura", "Mal estado"])))
            d += timedelta(days=1)

        # ---------------------------------------------------------------- estado final
        sob = CASOS["sobrestock"]
        filas_stock = []
        for s in sucursales:
            for p in prods:
                reservado = 1 if s == "Salta Centro" and p.categoria == "Bebidas" and rng.random() < 0.1 else 0
                filas_stock.append((org_id, p.id, ubic[s], round(stock[s][p.id], 3), reservado, 0))
        if deposito:
            for p in prods:
                if p.perecedero:
                    continue
                total = sum(vpd_esperada(p, s) for s in sucursales)
                cant = round(total * rng.uniform(8, 25))
                if p.codigo == sob["producto"]:
                    cant = round(total * 90)
                filas_stock.append((org_id, p.id, ubic[deposito], cant, 0, 0))
        _copy(conn, "stock_actual", ["org_id", "producto_id", "ubicacion_id", "cantidad", "reservado", "en_transito"], filas_stock)

        # Lotes con vencimiento de los perecederos (el lote más viejo primero).
        filas_lotes = []
        for s in sucursales:
            for p in prods:
                if not p.perecedero or stock[s][p.id] <= 0:
                    continue
                vida = VIDA_UTIL.get(p.sub, 30)
                restante = stock[s][p.id]
                if vence_caso is p and s == venc["ubicacion"]:
                    restante -= venc["exceso"]     # el lote por vencer va aparte
                if restante <= 0:
                    continue
                partes = [restante * 0.3, restante * 0.7] if restante > 10 else [restante]
                for k, q in enumerate(partes):
                    vence = hoy + timedelta(days=max(1, round(vida * (0.35 + 0.6 * k) * rng.uniform(0.8, 1.1))))
                    filas_lotes.append((org_id, p.id, ubic[s], f"L{p.codigo[1:]}{k}{s[0]}", round(q, 3), vence,
                                        vence - timedelta(days=vida)))
        if vence_caso:
            p = vence_caso
            filas_lotes.append((org_id, p.id, ubic[venc["ubicacion"]], "LVENCE01", venc["exceso"], hoy + timedelta(days=venc["dias"]),
                                hoy - timedelta(days=20)))
            resumen["vence_pronto"] = p.codigo
        _copy(conn, "stock_lotes", ["org_id", "producto_id", "ubicacion_id", "lote", "cantidad", "vencimiento", "ingreso"], filas_lotes)

        # Cantidades recibidas en las OC históricas.
        f_oc_l = [f + (f_oc_l_recibido.get((f[1], f[2]), 0),) for f in f_oc_l]
        _copy(conn, "ordenes_compra", ["id", "org_id", "numero", "proveedor_id", "ubicacion_id", "estado", "origen", "total", "fecha_esperada",
                                        "aprobacion", "aprobada_at", "enviada_at", "created_at", "updated_at"], f_oc)
        _copy(conn, "ordenes_compra_lineas", ["org_id", "orden_id", "producto_id", "ubicacion_id", "cantidad", "cantidad_sugerida", "bultos",
                                              "costo", "cantidad_recibida"], f_oc_l)
        with conn.cursor() as cur:
            cur.execute("UPDATE ordenes_compra o SET estado='recibida_parcial' WHERE org_id=%s AND estado='recibida' AND EXISTS "
                        "(SELECT 1 FROM ordenes_compra_lineas l WHERE l.orden_id=o.id AND l.cantidad_recibida < l.cantidad)", (org_id,))
        _copy(conn, "recepciones", ["id", "org_id", "orden_id", "proveedor_id", "ubicacion_id", "fecha", "documento"], f_rc)
        _copy(conn, "recepciones_lineas", ["org_id", "recepcion_id", "producto_id", "cantidad", "costo", "cantidad_esperada", "costo_esperado"], f_rc_l)
        _copy(conn, "tickets", ["id", "org_id", "ubicacion_id", "canal_id", "plataforma_id", "punto_venta", "cajero", "fecha_hora", "cliente",
                                "total", "estado", "numero_externo", "origen"], f_tickets)
        _copy(conn, "tickets_lineas", ["org_id", "ticket_id", "ubicacion_id", "fecha", "producto_id", "cantidad", "precio_lista", "precio_cobrado",
                                       "descuento", "descuento_manual", "costo_unitario", "promocion_id"], f_lineas)
        _copy(conn, "pagos", ["org_id", "ticket_id", "ubicacion_id", "medio", "monto", "cuotas", "comision_estimada", "plazo_acreditacion_dias"], f_pagos)
        _copy(conn, "anulaciones_devoluciones", ["org_id", "ticket_id", "ubicacion_id", "tipo", "cajero", "motivo", "fecha_hora", "monto"], f_anul)
        _copy(conn, "costos_canal", ["org_id", "plataforma_id", "ticket_id", "fecha", "comision", "envio", "publicidad"], f_costos_canal)
        _copy(conn, "stock_diario", ["org_id", "producto_id", "ubicacion_id", "fecha", "stock_cierre", "con_stock"], f_stock_diario)
        _copy(conn, "movimientos_stock", ["org_id", "producto_id", "ubicacion_id", "fecha", "tipo", "cantidad", "costo_unitario", "documento_tipo",
                                          "documento_id", "motivo"], f_mov)

        # Recuentos anteriores con diferencias (alimentan la prioridad «diferencias previas»).
        for s in sucursales:
            for hace in (40, 12):
                r = db.fila(conn, "INSERT INTO recuentos (org_id, ubicacion_id, fecha, estado, cerrado_at) VALUES (%s,%s,%s,'cerrado',%s) RETURNING id",
                            (org_id, ubic[s], hoy - timedelta(days=hace), datetime.combine(hoy - timedelta(days=hace), time(20), ZONA)))
                for p in rng.sample(prods, min(10, len(prods))):
                    sistema = max(0, round(vpd_esperada(p, s) * 8))
                    contado = sistema - rng.choice([0, 0, 0, 1, 2, 3])
                    costo = costo_en(p, hoy - timedelta(days=hace)) or 0
                    with conn.cursor() as cur:
                        cur.execute("INSERT INTO recuentos_lineas (org_id, recuento_id, producto_id, motivo_seleccion, stock_sistema, contado, "
                                    "diferencia, diferencia_pesos, motivo_ajuste, contado_at) VALUES (%s,%s,%s,'clase_a',%s,%s,%s,%s,%s,%s)",
                                    (org_id, r["id"], p.id, sistema, contado, contado - sistema, round((contado - sistema) * costo, 2),
                                     "Faltante sin explicar" if contado != sistema else None, datetime.combine(hoy - timedelta(days=hace), time(19), ZONA)))

        # Configuración inicial: márgenes objetivo, redondeo, automatización, presupuesto y comisiones.
        with conn.cursor() as cur:
            margenes = {}
            for p in catalogo:
                margenes.setdefault(p["categoria"], p["margen"])
            for cat, margen in margenes.items():
                cur.execute("INSERT INTO margenes_objetivo (org_id, categoria_id, margen) VALUES (%s,%s,%s)", (org_id, cat_ids[(cat, None)], margen))
            cur.execute("INSERT INTO reglas_redondeo (org_id, desde_precio, hasta_precio, multiplo, terminaciones) VALUES "
                        "(%s, 0, 2000, 10, '{0,5,9}'), (%s, 2000, 10000, 50, '{0}'), (%s, 10000, NULL, 100, '{0}')", (org_id, org_id, org_id))
            for tipo, nivel, limite in (("orden_compra", "automatico_con_limite", 300000), ("transferencia", "automatico_con_limite", 150000),
                                        ("precio", "borrador", 0), ("promocion", "solo_aviso", 0)):
                cur.execute("INSERT INTO config_automatizacion (org_id, tipo_documento, nivel, monto_limite) VALUES (%s,%s,%s,%s)",
                            (org_id, tipo, nivel, limite))
            # Presupuesto del mes: lo que se compró en promedio por mes en los últimos 90 días, más un 10 %.
            desde90 = hoy - timedelta(days=90)
            compras90 = sum(float(f[7]) for f in f_oc if f[12].date() >= desde90)
            presupuesto = round(compras90 / 3 * 1.10, -3) or 1000000
            cur.execute("INSERT INTO presupuestos_compra (org_id, mes, monto) VALUES (%s,%s,%s)", (org_id, _mes(hoy), presupuesto))
            # Impacto: para la demo, el comercio «se conectó» hace unos tres meses (la línea base son esas 4 semanas).
            cur.execute("INSERT INTO parametros (org_id, clave, valor) VALUES (%s,'linea_base',%s)",
                        (org_id, json.dumps({"desde": (hoy - timedelta(days=90)).isoformat(), "hasta": (hoy - timedelta(days=63)).isoformat()})))
            cur.execute("INSERT INTO parametros (org_id, clave, valor) VALUES (%s,'comisiones_medios',%s)",
                        (org_id, json.dumps({m[0]: {"comision": m[2], "acreditacion_dias": m[3]} for m in MEDIOS})))
        _fiado_y_metas(conn, org_id, hoy, rng, sucursales, ubic)
        _online(conn, org_id, hoy, rng, plataformas, ubic)
        with conn.cursor() as cur:
            # secuencias
            for tabla in ("tickets", "ordenes_compra", "recepciones", "promociones"):
                cur.execute(f"SELECT setval(pg_get_serial_sequence('{tabla}', 'id'), greatest((SELECT coalesce(max(id), 1) FROM {tabla}), 1))")
        resumen.update({"cargada": True, "org_id": org_id, "productos": len(prods), "tickets": len(f_tickets), "lineas": len(f_lineas),
                        "desde": inicio.isoformat(), "hasta": hoy.isoformat()})

    if calcular:
        from . import motor
        resumen["calculo"] = motor.recalcular(org_id, hoy=hoy, tipo="nocturno")
    return resumen


def preparar() -> dict | None:
    """Al arrancar: si «Autoservicios del Norte» todavía no tiene datos, carga la demo completa (unos 2 minutos).
    Si la demo quedó vieja (su último día es anterior a hoy), la vuelve a generar hasta hoy: son datos de ejemplo y así
    las pantallas siempre muestran «hoy». Lo que se haya hecho sobre la demo (OC, recuentos) se pierde al regenerarla."""
    with db.transaccion(superadmin=True) as conn:
        org = db.fila(conn, "SELECT id, zona_horaria FROM organizaciones WHERE nombre=%s", (EMPRESA,))
        if not org:
            return None
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.org_id', %s, true)", (str(org["id"]),))
        hoy = datetime.now(ZoneInfo(org["zona_horaria"])).date()
        ultimo = db.fila(conn, "SELECT max(fecha) m FROM tickets_lineas WHERE org_id=%s", (org["id"],))["m"]
        tiene = ya_cargada(conn, org["id"])
        solo_demo = not db.fila(conn, "SELECT 1 FROM tickets WHERE org_id=%s AND origen <> 'demo' AND origen NOT IN ('tiendanube','mercadolibre') LIMIT 1",
                                (org["id"],))
    if tiene and (ultimo is None or ultimo >= hoy or not solo_demo):
        return None
    if tiene:
        borrar(org["id"])
    return cargar(org["id"])


CLIENTES_FIADO = ["Rosa Tolaba", "Juan Mamaní", "Carmen Cruz", "Pedro Guanca", "Norma Vilte", "Luis Cardozo", "Elsa Quipildor",
                  "Hugo Condorí", "Marta Liquín", "Raúl Sajama", "Olga Chauque", "Sergio Burgos", "Ana Gutiérrez", "Víctor Flores"]
MOROSOS = {"Pedro Guanca", "Olga Chauque"}


def _fiado_y_metas(conn, org_id: int, hoy: date, rng: random.Random, sucursales: list[str], ubic: dict) -> None:
    """Clientes con cuenta corriente (fiado): cada venta a cuenta corriente es una compra del cliente con vencimiento a 30 días;
    los clientes pagan lo del mes a fin de mes, salvo dos morosos que dejaron de pagar hace dos meses.
    Metas del mes: ventas y ganancia por sucursal = lo del mes anterior por día × días del mes × 1,05."""
    ids = {}
    with conn.cursor() as cur:
        # Recién cargadas con COPY no tienen estadísticas: sin esto el planificador elige planes de minutos.
        for tabla in ("tickets", "tickets_lineas", "pagos", "stock_actual"):
            cur.execute(f"ANALYZE {tabla}")
        for i, nombre in enumerate(CLIENTES_FIADO):
            ids[nombre] = db.fila(conn, "INSERT INTO clientes (org_id, identificador, nombre, alta, consentimiento) VALUES (%s,%s,%s,%s,true) RETURNING id",
                                  (org_id, f"CC-{i + 1:03d}", nombre, hoy - timedelta(days=400)))["id"]
        ventas = db.filas(conn, """SELECT t.id, (t.fecha_hora AT TIME ZONE o.zona_horaria)::date fecha, p.monto
                                   FROM pagos p JOIN tickets t ON t.id = p.ticket_id JOIN organizaciones o ON o.id = t.org_id WHERE p.org_id=%s AND p.medio='cuenta_corriente' AND p.monto > 0""",
                           (org_id,))
        compras, por_cliente_mes = [], defaultdict(Decimal)
        for v in ventas:
            nombre = CLIENTES_FIADO[v["id"] % len(CLIENTES_FIADO)]
            compras.append((org_id, ids[nombre], v["fecha"], "compra", v["monto"], v["fecha"] + timedelta(days=30)))
            por_cliente_mes[(nombre, v["fecha"].replace(day=1))] += v["monto"]
            cur.execute("UPDATE tickets SET cliente=%s WHERE id=%s", (nombre, v["id"]))
        pagos = []
        for (nombre, mes), monto in por_cliente_mes.items():
            dia_pago = (mes + timedelta(days=32)).replace(day=1) + timedelta(days=rng.randint(2, 12))
            corte = hoy - timedelta(days=75) if nombre in MOROSOS else hoy
            if dia_pago <= corte:
                pagos.append((org_id, ids[nombre], dia_pago, "pago", -monto, None))
        _copy(conn, "cuentas_clientes", ["org_id", "cliente_id", "fecha", "tipo", "monto", "vencimiento"], compras + pagos)
        mes = hoy.replace(day=1)
        anterior = (mes - timedelta(days=1)).replace(day=1)
        dias_ant = (mes - anterior).days
        dias_mes = calendar.monthrange(hoy.year, hoy.month)[1]
        for f in db.filas(conn, """SELECT ubicacion_id, sum(precio_cobrado * cantidad) v, sum((precio_cobrado - coalesce(costo_unitario, 0)) * cantidad) g
                                   FROM tickets_lineas WHERE org_id=%s AND fecha >= %s AND fecha < %s GROUP BY 1""", (org_id, anterior, mes)):
            for metrica, valor in (("ventas", f["v"]), ("ganancia", f["g"])):
                cur.execute("INSERT INTO metas (org_id, periodo, ubicacion_id, metrica, valor) VALUES (%s,%s,%s,%s,%s)",
                            (org_id, mes, f["ubicacion_id"], metrica, round(valor / dias_ant * dias_mes * Decimal("1.05"), -3)))


CATEGORIAS_ONLINE = ("Bebidas", "Almacén", "Perfumería", "Limpieza")


def _online(conn, org_id: int, hoy: date, rng: random.Random, plataformas: dict, ubic: dict) -> None:
    """Estado de los pedidos online (pendientes de hoy, despachados, entregados, algunos cancelados, devueltos o con reclamo),
    stock reservado por lo no despachado y publicaciones en Tiendanube y Mercado Libre: se publica el stock de Salta Centro,
    salvo dos productos con más stock publicado que el disponible (sobreventa) y algunos que no se publicaron."""
    despacho = ubic["Salta Centro"]
    ids_plat = {plataformas[t]: t for t in ("tiendanube", "mercadolibre")}
    pedidos, anular = [], []
    for t in db.filas(conn, "SELECT id, fecha_hora, plataforma_id FROM tickets WHERE org_id=%s AND plataforma_id = ANY(%s) ORDER BY id",
                      (org_id, list(ids_plat))):
        dia = t["fecha_hora"].astimezone(ZONA).date()
        ml = ids_plat[t["plataforma_id"]] == "mercadolibre"
        r = rng.random()
        if dia == hoy and r < 0.7:
            estado = "pendiente"
        elif r < 0.03:
            estado = "cancelado"
            anular.append(t["id"])
        elif r < 0.05:
            estado = "devuelto"
        else:
            estado = "despachado" if dia >= hoy - timedelta(days=2) else "entregado"
        horas = rng.uniform(2, 20) if ml else rng.uniform(4, 40)
        pedidos.append((t["id"], org_id, despacho, t["plataforma_id"], estado, t["fecha_hora"],
                        None if estado in ("pendiente", "cancelado") else t["fecha_hora"] + timedelta(hours=horas),
                        rng.random() < (0.05 if ml else 0.02), "No llegó a tiempo" if estado == "devuelto" else None))
    _copy(conn, "pedidos_online", ["ticket_id", "org_id", "ubicacion_id", "plataforma_id", "estado", "creado_at", "despachado_at", "reclamo", "motivo"], pedidos)
    with conn.cursor() as cur:
        if anular:
            cur.execute("UPDATE tickets SET estado='anulado' WHERE id = ANY(%s)", (anular,))
        cur.execute("""UPDATE stock_actual s SET reservado = x.q FROM (
                           SELECT l.producto_id, sum(l.cantidad) q FROM pedidos_online po JOIN tickets_lineas l ON l.ticket_id = po.ticket_id
                           WHERE po.estado = 'pendiente' AND po.org_id = %s GROUP BY 1) x
                       WHERE s.producto_id = x.producto_id AND s.ubicacion_id = %s""", (org_id, despacho))
    stock = {f["producto_id"]: f for f in db.filas(conn, """
        SELECT p.id producto_id, p.codigo_interno, p.nombre, coalesce(s.cantidad - s.reservado, 0) disponible, c.nombre categoria,
               (SELECT precio FROM precios x WHERE x.producto_id = p.id AND x.canal_id IS NOT NULL AND x.hasta IS NULL LIMIT 1) precio_online,
               (SELECT precio FROM precios x WHERE x.producto_id = p.id AND x.canal_id IS NULL AND x.ubicacion_id IS NULL AND x.hasta IS NULL LIMIT 1) precio
        FROM productos p LEFT JOIN categorias sc ON sc.id = p.categoria_id LEFT JOIN categorias c ON c.id = sc.padre_id
        LEFT JOIN stock_actual s ON s.producto_id = p.id AND s.ubicacion_id = %s WHERE p.org_id = %s""", (despacho, org_id))}
    caso = CASOS["sobreventa"]
    publicaciones = []
    for n, (pid, f) in enumerate(sorted(stock.items())):
        if f["categoria"] not in CATEGORIAS_ONLINE or n % 9 == 4:      # algunos no se publicaron
            if f["codigo_interno"] not in caso["productos"]:
                continue
        publicado = max(0, float(f["disponible"])) + (caso["exceso"] if f["codigo_interno"] in caso["productos"] else 0)
        for tipo in ("tiendanube", "mercadolibre"):
            publicaciones.append((org_id, plataformas[tipo], pid, f"{tipo[:2].upper()}-{pid}", f["codigo_interno"], f["nombre"],
                                  f["precio_online"] or f["precio"], publicado, True))
    _copy(conn, "publicaciones", ["org_id", "plataforma_id", "producto_id", "id_externo", "sku", "titulo", "precio", "stock_publicado", "activa"], publicaciones)


def borrar(org_id: int) -> None:
    """Borra los datos operativos de la empresa demo (no toca usuarios, sucursales ni configuración de acceso)."""
    tablas = ["alertas", "emails", "metricas_producto_actual", "agg_ubicacion_hora", "agg_producto_ubicacion_dia", "stock_diario",
              "historial_abc", "periodos_sin_stock", "ajustes_aprendizaje", "ejecuciones_calculo", "recuentos_lineas", "recuentos",
              "costos_canal", "anulaciones_devoluciones", "pagos", "tickets_lineas", "tickets", "movimientos_stock", "stock_lotes",
              "stock_actual", "transferencias_lineas", "transferencias", "recepciones_lineas", "recepciones", "ordenes_compra_lineas",
              "ordenes_compra", "listas_precios_proveedor_lineas", "listas_precios_proveedor", "precios", "promociones",
              "margenes_objetivo", "reglas_redondeo", "reglas_reposicion", "config_automatizacion", "config_abastecimiento",
              "presupuestos_compra", "parametros", "metas", "alias_producto", "producto_proveedores", "documentos_leidos",
              "staging_filas", "lotes_importacion", "mapeos_columnas", "calendario", "cuentas_clientes", "clientes", "pedidos_online", "publicaciones"]
    with db.transaccion(superadmin=True, org_id=org_id) as conn, conn.cursor() as cur:
        for t in tablas:
            cur.execute(f"DELETE FROM {t} WHERE org_id=%s", (org_id,))
        cur.execute("DELETE FROM productos WHERE org_id=%s", (org_id,))
        cur.execute("DELETE FROM proveedores WHERE org_id=%s", (org_id,))
        cur.execute("DELETE FROM categorias WHERE org_id=%s AND padre_id IS NOT NULL", (org_id,))
        cur.execute("DELETE FROM categorias WHERE org_id=%s", (org_id,))
        cur.execute("DELETE FROM plataformas WHERE org_id=%s", (org_id,))


def _poisson(rng: random.Random, media: float) -> int:
    if media <= 0:
        return 0
    limite, k, p = math.exp(-media), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limite:
            return k
        k += 1


def _elegir(rng: random.Random, acumulados: list[float], total: float) -> int | None:
    if total <= 0:
        return None
    import bisect
    return bisect.bisect_left(acumulados, rng.random() * total)


if __name__ == "__main__":
    import sys
    from .. import config  # noqa: F401  (carga backend/.env)
    from . import semilla
    semilla.cargar()
    print(json.dumps(cargar(escala=Escala(tickets=float(sys.argv[1]) if len(sys.argv) > 1 else 1.0)), default=str, indent=1))
