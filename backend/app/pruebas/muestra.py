"""Verificación por muestra: 20 registros al azar, lado a lado el origen (tal cual lo devuelve Odoo) y la plataforma."""
from __future__ import annotations

import json
import random
import uuid
from datetime import date
from decimal import Decimal

from ..erp import conector, fuente
from ..integraciones import gestor, odoo
from . import almacen, incidencias

METRICAS = {"ventas": "Ventas (pedidos y tickets)", "facturas": "Facturas y notas de crédito de clientes"}
TAMANO = 20


def _plataforma(metrica: str, desde: str, hasta: str) -> list[dict]:
    if metrica == "ventas":
        filas = conector.consultar(
            "SELECT v.id, v.numero, v.fecha, v.tipo, COALESCE(v.anulada, 0), SUM(l.cantidad * l.precio_unitario), SUM(COALESCE(l.impuestos, 0)), "
            "COUNT(l.venta_id) FROM ventas v LEFT JOIN ventas_lineas l ON l.venta_id = v.id "
            f"WHERE v.fecha >= '{desde}' AND v.fecha <= '{hasta}' GROUP BY v.id, v.numero, v.fecha, v.tipo, v.anulada",
            max_filas=1_000_000)["filas"]
        res = []
        for i, n, f, t, a, neto, imp, lineas in filas:
            neto_d, imp_d = Decimal(str(neto or 0)), Decimal(str(imp or 0))
            res.append({"clave": str(i), "numero": n, "fecha": f, "tipo": t, "anulada": bool(a), "lineas": lineas,
                        "sin_impuestos": float(round(neto_d, 2)), "impuestos": float(round(imp_d, 2)), "total": float(round(neto_d + imp_d, 2))})
        return res
    filas = conector.consultar(f"SELECT id, numero, tipo, fecha_emision, importe_sin_impuestos, impuestos, importe, saldo FROM cxc "
                               f"WHERE fecha_emision >= '{desde}' AND fecha_emision <= '{hasta}'", max_filas=1_000_000)["filas"]
    return [{"clave": str(i), "numero": n, "tipo": t, "fecha": f, "sin_impuestos": s, "impuestos": im, "total": tot, "saldo": sal}
            for i, n, t, f, s, im, tot, sal in filas]


def _origen(metrica: str, claves: list[str]) -> tuple[dict, str | None]:
    """Payload crudo de Odoo para cada clave (lectura en vivo, solo lectura)."""
    if fuente.actual() != "odoo" or not gestor.config_odoo()["clave_guardada"]:
        return {}, "La fuente activa no tiene un sistema de origen para comparar (la demo es la propia base de la plataforma)."
    c = gestor.cliente_odoo()
    res = {}
    if metrica == "ventas":
        ped = [int(k) for k in claves if int(k) < odoo.OFFSET_POS]
        pos = [int(k) - odoo.OFFSET_POS for k in claves if int(k) >= odoo.OFFSET_POS]
        if ped:
            campos = c._solo_existentes("sale.order", ["name", "date_order", "state", "amount_untaxed", "amount_tax", "amount_total",
                                                       "currency_id", "currency_rate", "team_id", "write_date"])
            for i, p in c.leer_ids("sale.order", ped, campos).items():
                res[str(i)] = p
        if pos:
            campos = c._solo_existentes("pos.order", ["name", "date_order", "state", "amount_tax", "amount_total", "currency_id",
                                                      "currency_rate", "crm_team_id", "write_date"])
            for i, t in c.leer_ids("pos.order", pos, campos).items():
                res[str(odoo.OFFSET_POS + i)] = t
    else:
        campos = c._solo_existentes("account.move", ["name", "move_type", "state", "invoice_date", "amount_untaxed_signed",
                                                     "amount_tax_signed", "amount_total_signed", "amount_residual_signed", "write_date"])
        for i, m in c.leer_ids("account.move", [int(k) for k in claves], campos).items():
            res[str(i)] = m
    return res, None


def _sugerencia(metrica: str, origen: dict | None, plataforma: dict) -> str | None:
    """Pista para el tester (no decide por él): ¿los importes sin impuestos coinciden al centavo?"""
    if not origen:
        return None
    if metrica == "ventas":
        tasa = Decimal(str(origen.get("currency_rate") or 1)) or Decimal(1)
        sin = (Decimal(str(origen.get("amount_untaxed"))) if "amount_untaxed" in origen
               else Decimal(str(origen.get("amount_total") or 0)) - Decimal(str(origen.get("amount_tax") or 0))) / tasa
    else:
        sin = Decimal(str(origen.get("amount_untaxed_signed") or 0))
    plat = Decimal(str(plataforma.get("sin_impuestos") or 0))
    return "coincide" if abs(sin - plat) <= Decimal("0.01") else "difiere"


def tomar(metrica: str, desde: str, hasta: str, usuario: str, semilla: int | None = None) -> dict:
    if metrica not in METRICAS:
        raise ValueError("Métrica inválida.")
    date.fromisoformat(desde), date.fromisoformat(hasta)
    todos = _plataforma(metrica, desde, hasta)
    if not todos:
        raise ValueError("No hay registros en ese período.")
    elegidos = random.Random(semilla).sample(todos, min(TAMANO, len(todos)))
    origen, aviso = _origen(metrica, [e["clave"] for e in elegidos])
    lote = uuid.uuid4().hex[:10]
    with almacen.conectar() as con:
        for e in elegidos:
            o = origen.get(e["clave"])
            con.execute("INSERT INTO verificacion_muestra (lote_id, fuente, metrica, desde, hasta, registro_clave, origen_payload, plataforma, "
                        "usuario, creado_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (lote, fuente.actual(), metrica, desde, hasta, e["clave"],
                         json.dumps(o if o is not None else ({"aviso": "No está en el origen (¿borrado?)"} if not aviso else None),
                                    ensure_ascii=False, default=str), json.dumps(e, ensure_ascii=False, default=str), usuario, almacen.ahora()))
    return {**ver(lote), "aviso": aviso}


def ver(lote: str) -> dict:
    filas = almacen.filas("SELECT * FROM verificacion_muestra WHERE lote_id=? ORDER BY id", (lote,))
    if not filas:
        raise KeyError("No existe esa muestra.")
    registros = []
    for f in filas:
        o = json.loads(f["origen_payload"]) if f["origen_payload"] else None
        p = json.loads(f["plataforma"])
        registros.append({**{k: f[k] for k in ("id", "registro_clave", "resultado", "comentario", "incidencia_id", "marcado_at", "usuario")},
                          "origen": o, "plataforma": p, "espejo": p, "sugerencia": _sugerencia(f["metrica"], o if o and "aviso" not in o else None, p)})
    return {"lote": lote, "metrica": filas[0]["metrica"], "nombre": METRICAS.get(filas[0]["metrica"]), "desde": filas[0]["desde"],
            "hasta": filas[0]["hasta"], "fuente": filas[0]["fuente"], "registros": registros,
            "marcados": sum(1 for r in registros if r["resultado"] != "pendiente"),
            "no_coinciden": sum(1 for r in registros if r["resultado"] == "no_coincide")}


def marcar(id_: int, resultado: str, comentario: str | None, usuario: str) -> dict:
    if resultado not in ("coincide", "no_coincide"):
        raise ValueError("El resultado es «coincide» o «no_coincide».")
    f = almacen.filas("SELECT * FROM verificacion_muestra WHERE id=?", (id_,))
    if not f:
        raise KeyError("No existe ese registro de muestra.")
    f = f[0]
    incidencia_id = f["incidencia_id"]
    if resultado == "no_coincide" and not incidencia_id:
        incidencia_id = incidencias.crear(
            "muestra", f"No coincide {METRICAS.get(f['metrica'], f['metrica']).lower()} · registro {f['registro_clave']}", usuario,
            tipo="datos", descripcion=comentario or "", metrica=f["metrica"], fuente=f["fuente"], fecha_dato=f["desde"],
            registro_clave=f["registro_clave"],
            evidencia={"origen": json.loads(f["origen_payload"] or "null"), "plataforma": json.loads(f["plataforma"])})
    with almacen.conectar() as con:
        con.execute("UPDATE verificacion_muestra SET resultado=?, comentario=?, usuario=?, marcado_at=?, incidencia_id=? WHERE id=?",
                    (resultado, comentario, usuario, almacen.ahora(), incidencia_id, id_))
    return ver(f["lote_id"])


def lotes() -> list[dict]:
    return almacen.filas("SELECT lote_id, metrica, desde, hasta, MIN(creado_at) AS creado_at, COUNT(*) AS n, "
                         "SUM(resultado <> 'pendiente') AS marcados, SUM(resultado = 'no_coincide') AS no_coinciden "
                         "FROM verificacion_muestra GROUP BY lote_id ORDER BY MIN(id) DESC LIMIT 20")
