"""Demo del panel para distribuidores y marcas (sección 13.3).

- «Distribuidora Andina» como empresa distribuidora (usuario distribuidor@andina.demo), con sus marcas de bebidas.
- Diez comercios chicos del NOA que venden bebidas (sin usuarios: solo aportan datos al panel) y uno más que no dio consentimiento.
  Con «Autoservicios del Norte» (que da su consentimiento) quedan 9 comercios en Salta (se muestra) y 3 en San Salvador de Jujuy
  (menos de 5: el panel la reserva).
- 26 semanas de ventas diarias y stock al cierre, una campaña del distribuidor (Cola Norte 1,5 L con 20 % de descuento),
  quiebres por entregas que no llegan (Agua Cumbre 2 L no se entrega hace 5 semanas) y pedidos enviados al distribuidor.
Los ritmos de venta salen de los de Autoservicios del Norte (por producto y sucursal), así los tamaños quedan proporcionados.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from . import catalogo_demo, db, seguridad
from .demo import EMPRESA, FACTOR_SEMANA, ZONA, _poisson
from .rutas import ETIQUETA_CANAL

DISTRIBUIDOR = "Distribuidora Andina"
CUIT_DISTRIBUIDOR = "30-70987654-3"
USUARIO_DISTRIBUIDOR = ("distribuidor@andina.demo", "Pablo Aramayo")
SUBCATEGORIAS = ("Gaseosas", "Aguas", "Jugos", "Vinos y aperitivos")
MARCAS = [m for cat in catalogo_demo.CATEGORIAS.values() for sub, *_r, marcas, _v in cat if sub in SUBCATEGORIAS for m in marcas]
# (nombre, localidad, tamaño relativo a una sucursal de Autoservicios del Norte, consentimiento)
COMERCIOS = [
    ("Almacén Don Ramón", "Salta", 0.6, True),
    ("Despensa La Merced", "Salta", 0.5, True),
    ("Autoservicio Tres Cerritos", "Salta", 0.8, True),
    ("Almacén El Cerrito", "Salta", 0.35, True),
    ("Minimercado Castañares", "Salta", 0.55, True),
    ("Supermercado Limache", "Salta", 0.9, True),
    ("Almacén Villa Las Rosas", "Salta", 0.6, True),
    ("Despensa Grand Bourg", "Salta", 0.5, True),
    ("Almacén Los Perales", "San Salvador de Jujuy", 0.5, True),
    ("Despensa Alto Comedero", "San Salvador de Jujuy", 0.45, True),
    ("Autoservicio Yala", "Salta", 0.5, False),
]
SEMANAS = 26
CAMPANA = {"producto": "Cola Norte 1,5 L", "desde_dias": 34, "hasta_dias": 21, "descuento": 0.20, "efecto": 1.6}
QUIEBRE = {"producto": "Agua Cumbre sin gas 2 L", "dias": 35, "prob_falla": 1.0}   # la distribuidora no lo entrega hace 5 semanas
PROB_FALLA = 0.05          # entrega que no llega
PROB_SURTIDO = 0.75        # cada comercio trabaja 3 de cada 4 productos de las marcas líderes


def _borrar(conn, org_id: int) -> None:
    with conn.cursor() as cur:
        for tabla in ("agg_producto_ubicacion_dia", "stock_diario", "promociones", "ordenes_compra_lineas", "ordenes_compra",
                      "producto_proveedores", "productos", "proveedores", "categorias"):
            if tabla == "categorias":
                cur.execute("DELETE FROM categorias WHERE org_id=%s AND padre_id IS NOT NULL", (org_id,))
            cur.execute(f"DELETE FROM {tabla} WHERE org_id=%s", (org_id,))


def _org(conn, nombre: str, localidad: str, consentimiento: bool) -> tuple[int, int, int]:
    """(org, ubicación, canal físico); la crea si no existe."""
    org = db.fila(conn, "SELECT id FROM organizaciones WHERE nombre=%s", (nombre,))
    if not org:
        org = db.fila(conn, "INSERT INTO organizaciones (nombre, modelo_abastecimiento, consentimiento_datos, consentimiento_fecha) "
                            "VALUES (%s, 'descentralizado', %s, CASE WHEN %s THEN now() END) RETURNING id",
                      (nombre, consentimiento, consentimiento))
        with conn.cursor() as cur:
            for codigo, etiqueta in ETIQUETA_CANAL.items():
                cur.execute("INSERT INTO canales (org_id, codigo, nombre, activo) VALUES (%s,%s,%s,%s)",
                            (org["id"], codigo, etiqueta, codigo == "fisico"))
            cur.execute("INSERT INTO ubicaciones (org_id, nombre, tipo, localidad) VALUES (%s,%s,'ambos',%s)", (org["id"], nombre, localidad))
    ubic = db.fila(conn, "SELECT id FROM ubicaciones WHERE org_id=%s ORDER BY id LIMIT 1", (org["id"],))["id"]
    canal = db.fila(conn, "SELECT id FROM canales WHERE org_id=%s AND codigo='fisico'", (org["id"],))["id"]
    return org["id"], ubic, canal


def _distribuidor(conn) -> int:
    org = db.fila(conn, "SELECT id FROM organizaciones WHERE nombre=%s", (DISTRIBUIDOR,))
    if org:
        return org["id"]
    from .semilla import CLAVE_DEMO
    org = db.fila(conn, "INSERT INTO organizaciones (nombre, cuit, tipo, modelo_abastecimiento, plan, pagado_hasta) "
                        "VALUES (%s,%s,'distribuidor','centralizado','cadena','2099-12-31') RETURNING id", (DISTRIBUIDOR, CUIT_DISTRIBUIDOR))
    with conn.cursor() as cur:
        for codigo, etiqueta in ETIQUETA_CANAL.items():
            cur.execute("INSERT INTO canales (org_id, codigo, nombre, activo) VALUES (%s,%s,%s,%s)",
                        (org["id"], codigo, etiqueta, codigo == "mayorista"))
        cur.execute("INSERT INTO usuarios (org_id, email, nombre, rol, hash_clave) VALUES (%s,%s,%s,'distribuidor',%s) ON CONFLICT DO NOTHING",
                    (org["id"], USUARIO_DISTRIBUIDOR[0], USUARIO_DISTRIBUIDOR[1], seguridad.hash_clave(CLAVE_DEMO)))
        for marca in MARCAS:
            cur.execute("INSERT INTO marcas_distribuidor (org_id, marca) VALUES (%s,%s)", (org["id"], marca))
    return org["id"]


def _ritmos(conn, hoy: date) -> dict[str, float]:
    """Unidades diarias por EAN en una sucursal típica de Autoservicios del Norte (últimas 26 semanas, días con stock)."""
    filas = db.filas(conn, """
        SELECT p.ean, sum(a.unidades) / greatest(count(DISTINCT (a.ubicacion_id, a.fecha)), 1) diaria
        FROM agg_producto_ubicacion_dia a JOIN productos p ON p.id = a.producto_id JOIN organizaciones o ON o.id = a.org_id
        JOIN ubicaciones u ON u.id = a.ubicacion_id
        WHERE o.nombre = %s AND u.tipo <> 'deposito' AND a.fecha > %s AND p.ean IS NOT NULL GROUP BY 1""", (EMPRESA, hoy - timedelta(days=182)))
    return {f["ean"]: float(f["diaria"]) for f in filas}


def cargar(hoy: date | None = None, semilla: int = 20260929) -> dict:
    """Crea (o regenera hasta hoy) el distribuidor y los comercios del panel. Idempotente."""
    rng = random.Random(semilla)
    with db.transaccion(superadmin=True) as conn:
        norte = db.fila(conn, "SELECT id FROM organizaciones WHERE nombre=%s", (EMPRESA,))
        if hoy is None:
            hoy = (db.fila(conn, "SELECT max(fecha) f FROM agg_producto_ubicacion_dia WHERE org_id=%s", (norte["id"],))["f"]
                   if norte else None) or datetime.now(ZONA).date()
        dist = _distribuidor(conn)
        with conn.cursor() as cur:
            # Autoservicios del Norte da su consentimiento y le compra a la distribuidora con su CUIT real.
            cur.execute("UPDATE organizaciones SET consentimiento_datos=true, consentimiento_fecha=coalesce(consentimiento_fecha, now()) "
                        "WHERE nombre=%s", (EMPRESA,))
            cur.execute("UPDATE proveedores SET cuit=%s WHERE razon_social=%s AND org_id IN (SELECT id FROM organizaciones WHERE nombre=%s)",
                        (CUIT_DISTRIBUIDOR, DISTRIBUIDOR, EMPRESA))
        ritmos = _ritmos(conn, hoy)
        catalogo = [p for p in catalogo_demo.productos() if p["subcategoria"] in SUBCATEGORIAS and p["marca"] != "Norte Selección"]
        maestros = {}
        for p in catalogo:
            maestros[p["ean"]] = db.fila(conn, "INSERT INTO productos_maestros (ean, nombre, marca, fabricante, categoria, subcategoria, presentacion, "
                                               "unidad_medida) VALUES (%s,%s,%s,%s,%s,%s,%s,'unidad') "
                                               "ON CONFLICT (ean) DO UPDATE SET nombre=EXCLUDED.nombre RETURNING id",
                                         (p["ean"], p["nombre"], p["marca"], p["marca"], p["categoria"], p["subcategoria"], p["presentacion"]))["id"]
        inicio = hoy - timedelta(days=SEMANAS * 7 - 1)
        resumen = {"distribuidor": dist, "comercios": 0, "filas": 0}
        for k, (nombre, localidad, tamano, consentimiento) in enumerate(COMERCIOS):
            org, ubic, canal = _org(conn, nombre, localidad, consentimiento)
            _borrar(conn, org)
            resumen["comercios"] += 1
            resumen["filas"] += _simular(conn, rng, org, ubic, canal, k, tamano, catalogo, maestros, ritmos, inicio, hoy)
    return resumen


def _simular(conn, rng, org, ubic, canal, k, tamano, catalogo, maestros, ritmos, inicio, hoy) -> int:
    cats: dict = {}
    prov = db.fila(conn, "INSERT INTO proveedores (org_id, razon_social, cuit, email_oc, dias_visita, demora_entrega_dias) "
                         "VALUES (%s,%s,%s,'pedidos@andina.demo',%s,1) RETURNING id", (org, DISTRIBUIDOR, CUIT_DISTRIBUIDOR, [k % 6]))["id"]
    otro = db.fila(conn, "INSERT INTO proveedores (org_id, razon_social, cuit, dias_visita, demora_entrega_dias) "
                         "VALUES (%s,'Mayorista Económico','30-65432198-7',%s,2) RETURNING id", (org, [(k + 3) % 6]))["id"]
    prods = []
    for p in catalogo:
        lider = p["marca"] not in ("Precio Justo",)
        if lider and rng.random() > PROB_SURTIDO and p["nombre"] not in (CAMPANA["producto"], QUIEBRE["producto"]):
            continue
        for clave in ((p["categoria"], None), (p["categoria"], p["subcategoria"])):
            if clave not in cats:
                cats[clave] = db.fila(conn, "INSERT INTO categorias (org_id, nombre, padre_id) VALUES (%s,%s,%s) RETURNING id",
                                      (org, clave[1] or clave[0], cats.get((p["categoria"], None))))["id"]
        pid = db.fila(conn, "INSERT INTO productos (org_id, maestro_id, codigo_interno, nombre, ean, marca, categoria_id) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                      (org, maestros.get(p["ean"]), p["codigo"], p["nombre"], p["ean"], p["marca"],
                       cats[(p["categoria"], p["subcategoria"])]))["id"]
        with conn.cursor() as cur:
            cur.execute("INSERT INTO producto_proveedores (org_id, producto_id, proveedor_id, costo, unidades_por_bulto) VALUES (%s,%s,%s,%s,%s)",
                        (org, pid, prov if lider else otro, round(p["precio"] * (1 - p["margen"]), 2), p["bulto"]))
        base = ritmos.get(p["ean"], 0.8) * tamano * rng.uniform(0.7, 1.3)
        prods.append((pid, p, max(base, 0.05), lider))

    campana = next((pid for pid, p, _b, _l in prods if p["nombre"] == CAMPANA["producto"]), None)
    c_desde, c_hasta = hoy - timedelta(days=CAMPANA["desde_dias"]), hoy - timedelta(days=CAMPANA["hasta_dias"])
    if campana and COMERCIOS[k][3]:          # la campaña la hicieron los que comparten datos
        with conn.cursor() as cur:
            cur.execute("INSERT INTO promociones (org_id, nombre, tipo, parametros, productos, desde, hasta, estado) "
                        "VALUES (%s,%s,'descuento_pct',%s,%s,%s,%s,'finalizada')",
                        (org, f"{CAMPANA['producto']} −20 % (campaña del distribuidor)", '{"porcentaje": 20}', [campana], c_desde, c_hasta))
    visita = {True: k % 6, False: (k + 3) % 6}
    f_agg, f_stock, entregas = [], [], []
    for pid, p, base, lider in prods:
        stock = math.ceil(base * 8)
        d = inicio
        while d <= hoy:
            if d.weekday() == visita[lider]:
                falla = PROB_FALLA
                if p["nombre"] == QUIEBRE["producto"] and (hoy - d).days < QUIEBRE["dias"]:
                    falla = QUIEBRE["prob_falla"]
                if rng.random() >= falla:
                    objetivo = base * 8      # una semana y un día de margen: con picos a veces falta
                    pedido = max(0, math.ceil((objetivo - stock) / p["bulto"])) * p["bulto"]
                    if pedido:
                        stock += pedido
                        entregas.append((d, pid, pedido, lider, p))
            promo = campana == pid and c_desde <= d <= c_hasta and COMERCIOS[k][3]
            estacion = 1 + (0.25 if p["subcategoria"] != "Vinos y aperitivos" else -0.2) * math.cos(2 * math.pi * (d.timetuple().tm_yday - 15) / 365)
            demanda = _poisson(rng, base * FACTOR_SEMANA[d.weekday()] * estacion * (CAMPANA["efecto"] if promo else 1))
            vendido = min(demanda, int(stock))
            stock -= vendido
            meses = (hoy.year - d.year) * 12 + hoy.month - d.month
            precio = p["precio"] / (1.022 ** meses) * (1 - CAMPANA["descuento"] if promo else 1)
            if vendido:
                fact = round(vendido * precio, 2)
                costo = round(vendido * p["precio"] * (1 - p["margen"]) / (1.022 ** meses), 2)
                f_agg.append((org, pid, ubic, canal, d, vendido, fact, costo, round(fact - costo, 2), vendido, vendido if promo else 0))
            f_stock.append((org, pid, ubic, d, stock, stock > 0))
            d += timedelta(days=1)
    db.copiar(conn, "agg_producto_ubicacion_dia", ["org_id", "producto_id", "ubicacion_id", "canal_id", "fecha", "unidades", "facturacion",
                                                   "costo", "ganancia", "tickets", "unidades_promo"], f_agg)
    db.copiar(conn, "stock_diario", ["org_id", "producto_id", "ubicacion_id", "fecha", "stock_cierre", "con_stock"], f_stock)

    # Pedidos al distribuidor de las últimas 4 semanas (recibidos) y el de la próxima visita (enviado, sin confirmar).
    por_dia = defaultdict(list)
    for d, pid, cant, lider, p in entregas:
        if lider and (hoy - d).days < 28:
            por_dia[d].append((pid, cant, p))
    proxima = hoy + timedelta(days=(visita[True] - hoy.weekday()) % 7 or 7)
    por_dia[proxima] = [(pid, p["bulto"] * rng.randint(1, 3), p) for pid, p, _b, lider in prods if lider and rng.random() < 0.5]
    for n, (d, lineas) in enumerate(sorted(por_dia.items()), start=1):
        if not lineas:
            continue
        # El próximo pedido ya se envió (hoy o ayer); los anteriores, el día antes de la entrega.
        enviada = (datetime.combine(d - timedelta(days=1), time(10), ZONA) if d <= hoy
                   else datetime.combine(hoy - timedelta(days=k % 2), time(8), ZONA))
        total = sum(c * p["precio"] * (1 - p["margen"]) for _pid, c, p in lineas)
        oc = db.fila(conn, "INSERT INTO ordenes_compra (org_id, numero, proveedor_id, ubicacion_id, estado, origen, total, fecha_esperada, "
                           "aprobacion, aprobada_at, enviada_at, confirmada_proveedor_at, entrega_prometida, created_at) "
                           "VALUES (%s,%s,%s,%s,%s,'sugerida',%s,%s,'manual',%s,%s,%s,%s,%s) RETURNING id",
                     (org, f"OC-{n:06d}", prov, ubic, "enviada" if d > hoy else "recibida", round(total, 2), d, enviada, enviada,
                      None if d > hoy else enviada + timedelta(hours=2), None if d > hoy else d, enviada))["id"]
        with conn.cursor() as cur:
            for pid, c, p in lineas:
                cur.execute("INSERT INTO ordenes_compra_lineas (org_id, orden_id, producto_id, ubicacion_id, cantidad, bultos, costo, "
                            "cantidad_recibida) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (org, oc, pid, ubic, c, c // p["bulto"], round(p["precio"] * (1 - p["margen"]), 4), 0 if d > hoy else c))
    return len(f_agg)


def preparar() -> dict | None:
    """Al arrancar: carga o regenera la demo del panel si quedó atrás de Autoservicios del Norte."""
    with db.transaccion(superadmin=True) as conn:
        norte = db.fila(conn, "SELECT max(fecha) f FROM agg_producto_ubicacion_dia a JOIN organizaciones o ON o.id=a.org_id WHERE o.nombre=%s",
                        (EMPRESA,))
        panel = db.fila(conn, "SELECT max(fecha) f FROM agg_producto_ubicacion_dia a JOIN organizaciones o ON o.id=a.org_id WHERE o.nombre=%s",
                        (COMERCIOS[0][0],))
    if not norte or not norte["f"] or (panel and panel["f"] and panel["f"] >= norte["f"]):
        return None
    return cargar(norte["f"])
