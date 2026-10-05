"""Unidades y conversiones exactas (SPEC v2, sección 4): toda cantidad se guarda en la unidad base del producto.

La unidad base es la unidad en que se vende (unidad o kg). Las de compra (bulto, caja, pack, display…) se convierten con el factor
cargado en conversiones_unidad (por proveedor si difiere) o, para «bulto», con las unidades por bulto del proveedor. Nunca se adivina:
si no hay factor, se avisa para que una persona lo cargue.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from . import calculos as C
from . import db

SINONIMOS = {
    "u": "unidad", "un": "unidad", "und": "unidad", "uni": "unidad", "unid": "unidad", "unidad": "unidad", "unidades": "unidad",
    "kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "kilogramo": "kg", "kilogramos": "kg",
    "g": "g", "gr": "g", "grs": "g", "gramo": "g", "gramos": "g",
    "bulto": "bulto", "bultos": "bulto", "blt": "bulto", "bto": "bulto",
    "caja": "caja", "cajas": "caja", "cj": "caja", "pack": "pack", "packs": "pack", "display": "display", "displays": "display",
    "fardo": "fardo", "fardos": "fardo", "docena": "docena", "docenas": "docena",
}


class SinConversion(ValueError):
    pass


def normalizar(unidad: str | None) -> str:
    if not unidad:
        return "unidad"
    texto = unicodedata.normalize("NFKD", unidad.strip().lower()).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-z ]", "", texto).strip()
    return SINONIMOS.get(texto, texto or "unidad")


def factor(conn, producto_id: int, unidad: str | None, proveedor_id: int | None = None) -> Decimal:
    """Unidades base por 1 de `unidad`. Lanza SinConversion si no hay forma exacta de saberlo."""
    u = normalizar(unidad)
    base = db.fila(conn, "SELECT unidad FROM productos WHERE id=%s", (producto_id,))
    base = base["unidad"] if base else "unidad"
    if u == base or (u == "unidad" and base == "unidad"):
        return Decimal(1)
    if u == "g" and base == "kg":
        return Decimal("0.001")
    if u == "kg" and base == "unidad":
        raise SinConversion("El producto se vende por unidad: no se puede convertir kilos sin un factor cargado.")
    if u == "docena" and base == "unidad":
        return Decimal(12)
    f = db.fila(conn, """SELECT factor FROM conversiones_unidad WHERE producto_id=%s AND unidad=%s
                         AND (proveedor_id = %s OR proveedor_id IS NULL) ORDER BY proveedor_id IS NULL LIMIT 1""",
                (producto_id, u, proveedor_id))
    if f:
        return Decimal(f["factor"])
    if u == "bulto":
        pp = db.fila(conn, """SELECT unidades_por_bulto FROM producto_proveedores WHERE producto_id=%s
                              ORDER BY (proveedor_id = %s) DESC NULLS LAST, principal DESC LIMIT 1""", (producto_id, proveedor_id))
        if pp and pp["unidades_por_bulto"]:
            return Decimal(pp["unidades_por_bulto"])
    raise SinConversion(f"Falta cuántas unidades trae un/a «{u}» de este producto (Configuración → Unidades e impuestos).")


def a_base(conn, producto_id: int, cantidad, unidad: str | None, proveedor_id: int | None = None) -> tuple[Decimal, Decimal]:
    """(cantidad en unidad base, factor usado)."""
    f = factor(conn, producto_id, unidad, proveedor_id)
    return C.a_unidad_base(Decimal(str(cantidad)), f), f
