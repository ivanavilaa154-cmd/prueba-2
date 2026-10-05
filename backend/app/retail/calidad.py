"""Diagnóstico de calidad de datos (SPEC v2, sección 5.6).

Antes de confiar en una recomendación hay que saber si los datos de la empresa sirven. Cada chequeo devuelve los productos
afectados; con eso se arma un puntaje de 0 a 100 (ponderado por lo que vende cada producto) y la confianza de los datos de cada
producto (alta, media o baja), que se muestra junto a sus recomendaciones. Corre al conectar los datos, cada semana y a pedido.

Chequeos:
- stock_negativo: stock actual menor que cero en alguna sucursal.
- stock_inmovil: el stock no cambió en 30 días aunque el producto se vendió (el sistema de caja no descuenta stock).
- compras_no_registradas: en 60 días se vendió más que el stock que había más lo que entró (faltan compras cargadas).
- duplicado: mismo código de barras o mismo nombre (sin acentos, mayúsculas ni espacios) en dos productos.
- sin_costo: sin costo o con costo cero.
- costo_viejo: el costo no se actualizó en más de N días (60 por defecto; con inflación se desactualiza rápido).
- sin_categoria / sin_proveedor.
- conversion_dudosa: margen absurdo (costo mayor a 2,5 veces el precio o precio mayor a 8 veces el costo): bulto cargado como unidad.
- venta_bajo_costo: ventas de 30 días a precio cero o a menos de la mitad del costo.

Herramienta comercial: «perdiste $X en faltantes en 90 días y tenés $Y parados», con los datos del prospecto.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from . import db

DIAS_COSTO_VIEJO = 60
GRAVES = {"stock_negativo", "stock_inmovil", "compras_no_registradas", "conversion_dudosa", "sin_costo"}
TITULOS = {
    "stock_negativo": ("Stock negativo", "El sistema dice que hay menos de cero: faltan compras o recepciones cargadas.",
                       "Cargá las compras que falten o hacé un recuento."),
    "stock_inmovil": ("Stock que no se mueve aunque se vende", "El stock quedó igual 30 días pese a tener ventas: la caja no lo descuenta.",
                      "Revisá que la caja descuente stock al vender o importá el stock actualizado."),
    "compras_no_registradas": ("Compras no registradas", "Se vendió más de lo que había más lo que entró en 60 días.",
                               "Cargá las facturas o remitos que falten (Datos → Leer facturas)."),
    "duplicado": ("Productos duplicados", "Mismo código de barras o el mismo nombre en dos productos: las ventas y el stock se parten.",
                  "Unificalos en Datos → Catálogo."),
    "sin_costo": ("Sin costo", "Sin costo no se puede calcular margen, ganancia ni plata parada.",
                  "Importá la lista de precios del proveedor o leela con IA."),
    "costo_viejo": ("Costo desactualizado", f"El costo no cambia hace más de {DIAS_COSTO_VIEJO} días: con inflación, el margen que ves es mayor que el real.",
                    "Cargá la lista de precios vigente del proveedor."),
    "sin_categoria": ("Sin categoría", "Sin categoría no entra en los análisis por categoría ni toma la referencia de productos parecidos.",
                      "Asignale categoría en Datos → Catálogo."),
    "sin_proveedor": ("Sin proveedor", "Sin proveedor no se puede sugerir a quién comprarle ni cuándo llega.",
                      "Asignale proveedor (importando la lista de precios se asigna solo)."),
    "conversion_dudosa": ("Unidad dudosa (bulto o unidad)", "El margen es absurdo: probablemente el costo es por bulto y el precio por unidad, o al revés.",
                          "Revisá las unidades por bulto en Configuración → Unidades e impuestos."),
    "venta_bajo_costo": ("Ventas a precio cero o bajo costo", "Hay tickets de 30 días con precio cero o a menos de la mitad del costo.",
                         "Revisá el precio en la caja o si es un error de carga."),
}


def _norm(texto: str | None) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", t)


def chequear(conn, hoy: date) -> dict[str, set[int]]:
    """Productos activos afectados por cada chequeo."""
    r: dict[str, set[int]] = {}
    ids = lambda sql, p=(): {f["id"] for f in db.filas(conn, sql, p)}         # noqa: E731
    r["stock_negativo"] = ids("SELECT DISTINCT s.producto_id id FROM stock_actual s JOIN productos p ON p.id = s.producto_id WHERE p.activo AND s.cantidad < 0")
    r["stock_inmovil"] = ids("""
        SELECT d.producto_id id FROM stock_diario d
        WHERE d.fecha >= %s AND d.fecha < %s
          AND EXISTS (SELECT 1 FROM agg_producto_ubicacion_dia a WHERE a.producto_id = d.producto_id AND a.ubicacion_id = d.ubicacion_id
                      AND a.fecha >= %s AND a.unidades > 0)
        GROUP BY d.producto_id, d.ubicacion_id
        HAVING count(*) >= 20 AND max(d.stock_cierre) = min(d.stock_cierre) AND max(d.stock_cierre) > 0""",
                                (hoy - timedelta(days=30), hoy, hoy - timedelta(days=30)))
    r["compras_no_registradas"] = ids("""
        WITH ini AS (SELECT producto_id, ubicacion_id, stock_cierre FROM stock_diario WHERE fecha = %(d)s),
             vend AS (SELECT producto_id, ubicacion_id, sum(unidades) u FROM agg_producto_ubicacion_dia WHERE fecha > %(d)s GROUP BY 1, 2),
             entr AS (SELECT producto_id, ubicacion_id, sum(cantidad) q FROM movimientos_stock
                      WHERE tipo IN ('compra', 'transferencia_entrada', 'devolucion', 'ajuste', 'inicial') AND fecha::date > %(d)s AND cantidad > 0
                      GROUP BY 1, 2)
        SELECT v.producto_id id FROM vend v JOIN ini i USING (producto_id, ubicacion_id) LEFT JOIN entr e USING (producto_id, ubicacion_id)
        WHERE v.u > greatest(i.stock_cierre, 0) + coalesce(e.q, 0) + greatest(1, 0.05 * v.u)""", {"d": hoy - timedelta(days=60)})
    duplicados = set()
    por_ean, por_nombre = defaultdict(list), defaultdict(list)
    for p in db.filas(conn, "SELECT id, ean, nombre FROM productos WHERE activo"):
        if p["ean"]:
            por_ean[p["ean"]].append(p["id"])
        por_nombre[_norm(p["nombre"])].append(p["id"])
    for grupo in list(por_ean.values()) + list(por_nombre.values()):
        if len(grupo) > 1:
            duplicados.update(grupo)
    r["duplicado"] = duplicados
    r["sin_costo"] = ids("""SELECT p.id FROM productos p WHERE p.activo AND NOT EXISTS
                            (SELECT 1 FROM producto_proveedores pp WHERE pp.producto_id = p.id AND pp.costo > 0)""")
    r["costo_viejo"] = ids("""SELECT p.id FROM productos p JOIN producto_proveedores pp ON pp.producto_id = p.id AND pp.principal
                              WHERE p.activo AND pp.costo > 0 AND pp.updated_at < %s""", (hoy - timedelta(days=DIAS_COSTO_VIEJO),))
    r["sin_categoria"] = ids("SELECT id FROM productos WHERE activo AND categoria_id IS NULL")
    r["sin_proveedor"] = ids("SELECT p.id FROM productos p WHERE p.activo AND NOT EXISTS (SELECT 1 FROM producto_proveedores pp WHERE pp.producto_id = p.id)")
    con_iva = db.fila(conn, "SELECT costos_con_iva FROM organizaciones WHERE id = app_org()")["costos_con_iva"]
    r["conversion_dudosa"] = ids(f"""
        SELECT p.id FROM productos p JOIN producto_proveedores pp ON pp.producto_id = p.id AND pp.principal
        JOIN LATERAL (SELECT precio FROM precios x WHERE x.producto_id = p.id AND x.ubicacion_id IS NULL AND x.canal_id IS NULL
                      AND x.desde <= %s ORDER BY x.desde DESC LIMIT 1) pr ON true
        WHERE p.activo AND pp.costo > 0 AND pr.precio > 0
          AND (pp.costo / {'(1 + p.iva)' if con_iva else '1'} > 2.5 * pr.precio / (1 + p.iva)
               OR pr.precio / (1 + p.iva) > 8 * pp.costo / {'(1 + p.iva)' if con_iva else '1'})""", (hoy,))
    r["venta_bajo_costo"] = ids(f"""
        SELECT DISTINCT l.producto_id id FROM tickets_lineas l JOIN productos p ON p.id = l.producto_id
        WHERE l.fecha >= %s AND l.cantidad > 0
          AND (l.precio_cobrado = 0 OR (l.costo_unitario > 0 AND l.precio_cobrado / (1 + p.iva)
               < 0.5 * l.costo_unitario / {'(1 + p.iva)' if con_iva else '1'}))""", (hoy - timedelta(days=30),))
    return r


def comercial(conn, hoy: date) -> dict:
    """«Perdiste $X en faltantes y tenés $Y parados»: faltantes de 90 días a precio de venta y capital en stock sin rotación."""
    faltantes = db.fila(conn, """
        WITH dias AS (SELECT producto_id, ubicacion_id, count(*) n FROM stock_diario WHERE fecha >= %s AND fecha < %s AND NOT con_stock GROUP BY 1, 2),
             precio AS (SELECT producto_id, sum(facturacion) / nullif(sum(unidades), 0) p FROM agg_producto_ubicacion_dia WHERE fecha >= %s GROUP BY 1)
        SELECT coalesce(sum(d.n * m.vpd * pr.p), 0) v FROM dias d JOIN metricas_producto_actual m USING (producto_id, ubicacion_id)
        JOIN precio pr USING (producto_id) WHERE m.vpd > 0""", (hoy - timedelta(days=90), hoy, hoy - timedelta(days=90)))["v"]
    parada = db.fila(conn, "SELECT coalesce(sum(capital) FILTER (WHERE semaforo = 'gris' OR dias_sin_venta >= 90), 0) v FROM metricas_producto_actual")["v"]
    return {"faltantes_90_dias": round(Decimal(faltantes), 2), "plata_parada": round(Decimal(parada), 2)}


def revisar(conn, org_id: int, hoy: date, origen: str = "manual") -> dict:
    """Corre todos los chequeos, guarda el resultado y la confianza de cada producto. Devuelve el diagnóstico."""
    problemas = chequear(conn, hoy)
    venta = {f["producto_id"]: Decimal(f["v"]) for f in db.filas(conn, """SELECT producto_id, sum(facturacion) v FROM agg_producto_ubicacion_dia
                                                                          WHERE fecha >= %s GROUP BY 1""", (hoy - timedelta(days=90),))}
    activos = {f["id"]: f for f in db.filas(conn, "SELECT id, nombre, codigo_interno FROM productos WHERE activo")}
    if not activos:
        puntaje = Decimal(100)
    else:
        piso = (sum(venta.values()) / len(activos) * Decimal("0.1")) if venta else Decimal(1)
        peso = {pid: venta.get(pid, Decimal(0)) + piso for pid in activos}
        castigo = Decimal(0)
        for pid in activos:
            suyos = {c for c, ps in problemas.items() if pid in ps}
            castigo += peso[pid] * (Decimal(1) if suyos & GRAVES else Decimal("0.5") if suyos else Decimal(0))
        puntaje = (100 * (1 - castigo / sum(peso.values()))).quantize(Decimal("0.01"))
    detalle = []
    for codigo, ps in problemas.items():
        if not ps:
            continue
        titulo, explicacion, accion = TITULOS[codigo]
        orden = sorted(ps, key=lambda p: -venta.get(p, Decimal(0)))
        detalle.append({"codigo": codigo, "titulo": titulo, "explicacion": explicacion, "accion": accion, "grave": codigo in GRAVES,
                        "cantidad": len(ps), "venta_90_dias": round(sum(venta.get(p, Decimal(0)) for p in ps), 2),
                        "productos": [{"id": p, "nombre": activos[p]["nombre"], "codigo": activos[p]["codigo_interno"]} for p in orden[:50] if p in activos]})
    detalle.sort(key=lambda d: (not d["grave"], -d["venta_90_dias"]))
    resultado = {"fecha": hoy, "puntaje": puntaje, "productos": len(activos), "problemas": detalle, "comercial": comercial(conn, hoy)}
    filas = []
    for pid in activos:
        suyos = sorted(c for c, ps in problemas.items() if pid in ps)
        filas.append((org_id, pid, suyos, "baja" if set(suyos) & GRAVES else "media" if suyos else "alta"))
    with conn.cursor() as cur:
        cur.execute("DELETE FROM calidad_productos WHERE org_id = %s", (org_id,))
        cur.execute("INSERT INTO chequeos_calidad (org_id, fecha, puntaje, detalle, origen) VALUES (%s,%s,%s,%s,%s)",
                    (org_id, hoy, puntaje, json.dumps(resultado, default=str), origen))
    db.copiar(conn, "calidad_productos", ["org_id", "producto_id", "problemas", "confianza"], filas)
    return resultado


def toca_revisar(conn) -> bool:
    """Semanal: si nunca se revisó o pasaron 7 días."""
    u = db.fila(conn, "SELECT max(created_at) u FROM chequeos_calidad")["u"]
    from datetime import datetime, timezone
    return u is None or datetime.now(timezone.utc) - u >= timedelta(days=7)
