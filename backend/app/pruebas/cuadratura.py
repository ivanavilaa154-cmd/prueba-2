"""Cuadratura con el sistema de origen (Odoo), como la ve el Centro de pruebas.

- Cada sincronización guarda el control contra el reporte «Análisis de ventas» de Odoo
  (calidad_cuadratura): de ahí salen el sello, los días cuadrados y la marcha blanca.
- Las diferencias registro por registro y la reconciliación de IDs se calculan en vivo
  contra Odoo (solo lectura), comparando cada pedido con lo que tiene la plataforma.

Lo que depende de docs/16 (descubrimiento automático de la definición espejo, DQ-25 a
DQ-27, streams de control de facturación, tesorería y stock) queda marcado como pendiente.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from ..erp import conector, fuente
from ..integraciones import gestor, odoo
from . import almacen

OFFSET_POS = odoo.OFFSET_POS
METRICAS = [
    {"id": "ventas", "nombre": "Ventas sin impuestos", "referencia": "Odoo «Análisis de ventas» · Subtotal"},
    {"id": "ventas_con_impuestos", "nombre": "Ventas con impuestos", "referencia": "Odoo «Análisis de ventas» · Total"},
    {"id": "facturacion", "nombre": "Facturación", "referencia": None},
    {"id": "cobranzas", "nombre": "Cobranzas", "referencia": None},
    {"id": "cuentas_por_cobrar", "nombre": "Cuentas por cobrar", "referencia": None},
    {"id": "stock", "nombre": "Stock valorizado", "referencia": None},
]
PENDIENTE_DOC16 = "Sin control de origen todavía: se agrega con los streams de control de docs/16."
DEFINICION_VENTAS = ("Pedidos de venta y de caja en estado confirmado (sin cotizaciones, presupuestos enviados ni anulados), "
                     "por fecha del pedido en la hora local de Odoo, importes de cada línea con producto, en la moneda de la "
                     "empresa con la cotización del pedido. Igual que el filtro «Órdenes de venta» del reporte de Odoo.")


# --- registro de cada verificación -----------------------------------------------------

def registrar_control(entrada: dict, fuente_: str = "odoo") -> int:
    """Guarda el control de una sincronización (una fila por mes, equipo y métrica). Devuelve cuántas filas."""
    ctl = entrada.get("control_ventas") or {}
    if not entrada.get("ok") or not ctl.get("disponible"):
        return 0
    cuando = entrada.get("fecha") or almacen.ahora()
    el_dia = cuando[:10]
    n = 0
    with almacen.conectar() as con:
        con.execute("DELETE FROM calidad_cuadratura WHERE fuente=? AND verificado_el=?", (fuente_, el_dia))   # la última del día manda
        for f in ctl.get("filas", []):
            for metrica, o, p in (("ventas", f["odoo_sin_impuestos"], f["plataforma_sin_impuestos"]),
                                  ("ventas_con_impuestos", f["odoo_con_impuestos"], f["plataforma_con_impuestos"])):
                oc, pc = almacen.centesimos(o), almacen.centesimos(p)
                tolerancia = max(100, abs(oc) // 10000)   # 0,01 % o $ 1
                con.execute("INSERT INTO calidad_cuadratura (fuente, metrica, periodo, grupo, verificado_el, origen_centesimos, "
                            "plataforma_centesimos, origen_lineas, plataforma_lineas, cuadra, verificado_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (fuente_, metrica, f["mes"], f["equipo"], el_dia, oc, pc, f.get("odoo_lineas"), f.get("plataforma_lineas"),
                             int(abs(oc - pc) <= tolerancia), cuando))
                n += 1
    return n


def _dias(fuente_: str, metrica: str = "ventas") -> list[dict]:
    """Un resumen por día verificado: si todos los meses y equipos cuadraron ese día."""
    filas = almacen.filas("SELECT verificado_el, MIN(cuadra) AS cuadra, COUNT(*) AS n, MAX(verificado_at) AS at FROM calidad_cuadratura "
                          "WHERE fuente=? AND metrica=? GROUP BY verificado_el ORDER BY verificado_el", (fuente_, metrica))
    return filas


def marcha_blanca(fuente_: str = "odoo") -> dict:
    dias = _dias(fuente_)
    racha = 0
    for d in reversed(dias):
        if not d["cuadra"]:
            break
        racha += 1
    return {"inicio": dias[0]["verificado_el"] if dias else None, "dias_en_paralelo": len(dias), "racha_sin_diferencias": racha,
            "dias_necesarios": 14, "racha_necesaria": 7,
            "en_produccion": len(dias) >= 14 and racha >= 7}


def sello(metrica: str, fuente_: str | None = None, hoy: date | None = None) -> dict:
    """✔ Cuadrado (verificado hoy y sin diferencias), ⚠ En revisión, o — Sin referencia."""
    fuente_ = fuente_ or fuente.actual()
    hoy = hoy or date.today()
    ref = next((m for m in METRICAS if m["id"] == metrica), {})
    if fuente_ != "odoo" or not ref.get("referencia"):
        return {"sello": "sin_referencia", "texto": "— Sin referencia",
                "motivo": "La fuente activa no es Odoo." if fuente_ != "odoo" else PENDIENTE_DOC16}
    dias = _dias(fuente_, metrica)
    if not dias:
        return {"sello": "sin_referencia", "texto": "— Sin referencia", "motivo": "Todavía no se verificó: sincronizá Odoo."}
    ultimo = dias[-1]
    if ultimo["verificado_el"] != hoy.isoformat():
        return {"sello": "en_revision", "texto": "⚠ En revisión", "motivo": f"La última verificación es del {ultimo['verificado_el']}; falta la de hoy.",
                "verificado_at": ultimo["at"]}
    if not ultimo["cuadra"]:
        return {"sello": "en_revision", "texto": "⚠ En revisión", "motivo": "Hay meses o equipos con diferencia en la verificación de hoy.",
                "verificado_at": ultimo["at"]}
    return {"sello": "cuadrado", "texto": "✔ Cuadrado con tu sistema", "verificado_at": ultimo["at"], "motivo": None}


def ficha(metrica: str, fuente_: str | None = None) -> dict:
    """Todo lo de una métrica para la pantalla Cuadratura."""
    fuente_ = fuente_ or fuente.actual()
    ref = next((m for m in METRICAS if m["id"] == metrica), None)
    if not ref:
        raise KeyError("Métrica desconocida.")
    ultimo = almacen.filas("SELECT MAX(verificado_el) AS d FROM calidad_cuadratura WHERE fuente=? AND metrica=?", (fuente_, metrica))[0]["d"]
    evidencia = almacen.filas("SELECT periodo, grupo, origen_centesimos, plataforma_centesimos, origen_lineas, plataforma_lineas, cuadra "
                              "FROM calidad_cuadratura WHERE fuente=? AND metrica=? AND verificado_el=? ORDER BY periodo DESC, grupo",
                              (fuente_, metrica, ultimo)) if ultimo else []
    definiciones = almacen.filas("SELECT * FROM cuadratura_definicion WHERE fuente=? AND metrica=? ORDER BY id DESC", (fuente_, metrica))
    return {"metrica": ref, "sello": sello(metrica, fuente_), "definicion": DEFINICION_VENTAS if ref["referencia"] else None,
            "descubrimiento": "pendiente", "definiciones_registradas": definiciones,
            "evidencia": [{**e, "origen": almacen.pesos(e["origen_centesimos"]), "plataforma": almacen.pesos(e["plataforma_centesimos"]),
                           "diferencia": almacen.pesos(e["plataforma_centesimos"] - e["origen_centesimos"])} for e in evidencia],
            "historial": _dias(fuente_, metrica), "verificado_el": ultimo}


# --- en vivo contra Odoo ------------------------------------------------------------------

def _cliente():
    if fuente.actual() != "odoo":
        raise ValueError("La fuente activa no es Odoo: no hay un sistema de origen contra el cual comparar.")
    if not gestor.config_odoo()["clave_guardada"]:
        raise ValueError("Falta la conexión con Odoo (Integraciones → Odoo).")
    return gestor.cliente_odoo()


def _rango_utc(desde: date, hasta: date, zona: str) -> tuple[str, str]:
    tz = ZoneInfo(zona)
    ini = datetime.combine(desde, datetime.min.time(), tz).astimezone(timezone.utc)
    fin = datetime.combine(hasta + timedelta(days=1), datetime.min.time(), tz).astimezone(timezone.utc)
    return ini.strftime("%Y-%m-%d %H:%M:%S"), fin.strftime("%Y-%m-%d %H:%M:%S")


def _local(valor: str, zona: str) -> str | None:
    try:
        return datetime.strptime(valor[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).astimezone(ZoneInfo(zona)).date().isoformat()
    except (TypeError, ValueError):
        return None


def _tasa(valor) -> Decimal:
    """Cotización del documento (Odoo: currency_rate); vacía o 0 = misma moneda que la empresa."""
    try:
        v = Decimal(str(valor or 0))
    except Exception:
        return Decimal(1)
    return v if v > 0 else Decimal(1)


def _plataforma_pedidos(desde: date, hasta: date) -> dict[int, dict]:
    filas = conector.consultar(
        "SELECT v.id, v.numero, v.fecha, v.tipo, SUM(l.cantidad * l.precio_unitario), SUM(COALESCE(l.impuestos, 0)), COUNT(l.venta_id) "
        "FROM ventas v LEFT JOIN ventas_lineas l ON l.venta_id = v.id "
        f"WHERE COALESCE(v.anulada, 0) = 0 AND v.fecha >= '{desde}' AND v.fecha <= '{hasta}' GROUP BY v.id, v.numero, v.fecha, v.tipo",
        max_filas=1_000_000)["filas"]
    return {int(i): {"numero": n, "fecha": f, "tipo": t, "neto": Decimal(str(s or 0)), "impuestos": Decimal(str(im or 0)), "lineas": c}
            for i, n, f, t, s, im, c in filas}


def diferencias(mes: str, limite: int = 300) -> dict:
    """Pedidos de un mes que faltan, sobran o tienen otro importe, con la causa probable. Es el «¿Por qué difiere?»."""
    c = _cliente()
    zona = c.zona_horaria()
    desde = date.fromisoformat(mes + "-01")
    hasta = (desde + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    ini, fin = _rango_utc(desde, hasta, zona)
    campos = c._solo_existentes("sale.order", ["name", "date_order", "state", "amount_untaxed", "amount_tax", "currency_rate", "write_date"])
    origen = {}
    for p in c.leer_todo("sale.order", [("date_order", ">=", ini), ("date_order", "<", fin)], campos):
        origen[p["id"]] = {"numero": p.get("name"), "fecha": _local(p.get("date_order"), zona), "estado": p.get("state"),
                           "neto": Decimal(str(p.get("amount_untaxed") or 0)) / _tasa(p.get("currency_rate")),
                           "cotizacion": p.get("currency_rate"), "modificado": p.get("write_date"), "tipo": "orden_venta"}
    if c.puede_leer("pos.order"):
        campos_pos = c._solo_existentes("pos.order", ["name", "date_order", "state", "amount_total", "amount_tax", "currency_rate", "write_date"])
        for t in c.leer_todo("pos.order", [("date_order", ">=", ini), ("date_order", "<", fin)], campos_pos):
            tasa = _tasa(t.get("currency_rate"))
            origen[OFFSET_POS + t["id"]] = {"numero": t.get("name"), "fecha": _local(t.get("date_order"), zona), "estado": t.get("state"),
                                            "neto": (Decimal(str(t.get("amount_total") or 0)) - Decimal(str(t.get("amount_tax") or 0))) / tasa,
                                            "cotizacion": t.get("currency_rate"), "modificado": t.get("write_date"), "tipo": "ticket"}
    validos = {"sale", "done", "paid", "invoiced"}
    plataforma = _plataforma_pedidos(desde, hasta)
    ultima = next((h for h in gestor._leer_estado().get("historial", []) if h.get("ok")), {})
    sincronizado = (ultima.get("fecha") or "").replace("T", " ")
    filas = []
    for i, o in origen.items():
        if o["estado"] not in validos:
            if i in plataforma:
                filas.append({"tipo": "sobra", "id": i, "numero": o["numero"], "fecha": o["fecha"], "origen": 0.0,
                              "plataforma": float(plataforma[i]["neto"]),
                              "causa": f"En Odoo está «{o['estado']}» (no confirmado o anulado); cambió después de sincronizar"})
            continue
        p = plataforma.get(i)
        if not p:
            filas.append({"tipo": "falta", "id": i, "numero": o["numero"], "fecha": o["fecha"], "origen": float(o["neto"]), "plataforma": 0.0,
                          "causa": "Confirmado en Odoo después de la última sincronización" if (o["modificado"] or "") > sincronizado
                          else "No llegó en la sincronización (revisar permisos o reintentar)"})
            continue
        dif = p["neto"] - o["neto"]
        if abs(dif) > Decimal("0.01"):
            causa = ("Pedido en otra moneda: revisar la cotización" if o["cotizacion"] and float(o["cotizacion"]) not in (0.0, 1.0)
                     else "Modificado en Odoo después de sincronizar" if (o["modificado"] or "") > sincronizado
                     else "Líneas sin producto o de anticipo que la plataforma no suma")
            filas.append({"tipo": "importe_distinto", "id": i, "numero": o["numero"], "fecha": o["fecha"], "origen": float(o["neto"]),
                          "plataforma": float(p["neto"]), "causa": causa})
    for i, p in plataforma.items():
        if i not in origen and p["tipo"] in ("orden_venta", "ticket"):
            filas.append({"tipo": "sobra", "id": i, "numero": p["numero"], "fecha": p["fecha"], "origen": 0.0, "plataforma": float(p["neto"]),
                          "causa": "Ya no está en Odoo en ese mes: se borró o se le cambió la fecha"})
    total_origen = sum((o["neto"] for o in origen.values() if o["estado"] in validos), Decimal(0))
    total_plataforma = sum((p["neto"] for p in plataforma.values() if p["tipo"] in ("orden_venta", "ticket")), Decimal(0))
    # Puente: del total de Odoo a la plataforma, un paso por causa, con la cantidad de registros de cada paso
    pasos = defaultdict(lambda: [Decimal(0), 0])
    for f in filas:
        pasos[f["causa"]][0] += Decimal(str(f["plataforma"])) - Decimal(str(f["origen"]))
        pasos[f["causa"]][1] += 1
    puente = [{"paso": "Total en Odoo (pedidos confirmados del mes, sin impuestos)", "importe": float(total_origen),
               "registros": sum(1 for o in origen.values() if o["estado"] in validos)}]
    puente += [{"paso": causa, "importe": float(v[0]), "registros": v[1]} for causa, v in sorted(pasos.items(), key=lambda x: -abs(x[1][0]))]
    puente.append({"paso": "Total en la plataforma", "importe": float(total_plataforma),
                   "registros": sum(1 for p in plataforma.values() if p["tipo"] in ("orden_venta", "ticket"))})
    explicado = total_origen + sum((v[0] for v in pasos.values()), Decimal(0))
    return {"mes": mes, "zona": zona, "diferencias": filas[:limite], "total_diferencias": len(filas), "puente": puente,
            "sin_explicar": float(total_plataforma - explicado), "sincronizado": ultima.get("fecha")}


def reconciliar_claves(dias: int = 90, hoy: date | None = None) -> dict:
    """IDs de los últimos 90 días en Odoo contra la plataforma: faltantes, borrados en origen y duplicados."""
    c = _cliente()
    hoy = hoy or date.today()
    zona = c.zona_horaria()
    desde = hoy - timedelta(days=dias)
    ini, _fin = _rango_utc(desde, hoy, zona)
    en_origen = {p["id"] for p in c.leer_todo("sale.order", [("date_order", ">=", ini), ("state", "in", ["sale", "done", "cancel"])], ["id"])}
    if c.puede_leer("pos.order"):
        en_origen |= {OFFSET_POS + t["id"] for t in c.leer_todo("pos.order", [("date_order", ">=", ini),
                                                                             ("state", "in", ["paid", "done", "invoiced", "cancel"])], ["id"])}
    filas = conector.consultar(f"SELECT id, numero FROM ventas WHERE fecha >= '{desde}' AND tipo IN ('orden_venta', 'ticket')",
                               max_filas=5_000_000)["filas"]
    propios = [int(i) for i, _n in filas]
    numeros = Counter(n for _i, n in filas if n)
    faltantes = sorted(set(en_origen) - set(propios))
    sobrantes = sorted(set(propios) - en_origen)
    # Un sobrante puede estar borrado en Odoo o haber cambiado de fecha: se confirma leyéndolo
    existen = set()
    ped = [i for i in sobrantes if i < OFFSET_POS]
    if ped:
        existen |= {p["id"] for p in c.leer_todo("sale.order", [("id", "in", ped)], ["id"])}
    pos = [i - OFFSET_POS for i in sobrantes if i >= OFFSET_POS]
    if pos:
        existen |= {OFFSET_POS + t["id"] for t in c.leer_todo("pos.order", [("id", "in", pos)], ["id"])}
    borrados = [i for i in sobrantes if i not in existen]
    duplicados = sorted(n for n, k in numeros.items() if k > 1)
    res = {"desde": desde.isoformat(), "en_origen": len(en_origen), "en_plataforma": len(propios), "faltantes": faltantes,
           "borrados": borrados, "fuera_de_rango": sorted(set(sobrantes) - set(borrados)), "duplicados": duplicados}
    with almacen.conectar() as con:
        con.execute("INSERT INTO reconciliacion_claves (fuente, stream, desde, ejecutado_at, en_origen, en_plataforma, faltantes, borrados, "
                    "duplicados) VALUES (?,?,?,?,?,?,?,?,?)", ("odoo", "ventas", res["desde"], almacen.ahora(), res["en_origen"],
                                                                res["en_plataforma"], json.dumps(faltantes), json.dumps(borrados),
                                                                json.dumps(duplicados)))
    return res


def ultima_reconciliacion() -> dict | None:
    r = almacen.filas("SELECT * FROM reconciliacion_claves ORDER BY id DESC LIMIT 1")
    if not r:
        return None
    r = r[0]
    for k in ("faltantes", "borrados", "duplicados"):
        r[k] = json.loads(r[k] or "[]")
    return r
