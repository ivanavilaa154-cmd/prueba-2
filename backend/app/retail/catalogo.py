"""Normalización del catálogo (sección 5.5).

Emparejamiento de un producto que llega de afuera (archivo, caja, lista o factura del proveedor):
1. Código exacto: código de barras (EAN) o código interno.
2. Alias conocido: el mismo código o texto ya confirmado antes para ese origen (proveedor, caja, plataforma).
3. Similitud de texto: marca + presentación + contenido (palabras en común, números iguales, orden parecido).
4. Si la confianza no alcanza, queda para confirmar a mano; lo confirmado se guarda como alias para la próxima vez.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from . import db

UMBRAL_AUTOMATICO = 0.86     # desde acá se empareja solo
UMBRAL_SUGERENCIA = 0.45     # desde acá se sugiere
PALABRAS_VACIAS = {"de", "del", "la", "el", "x", "con", "sin", "en", "y", "para", "u", "un", "una"}
UNIDADES = {"lt": "l", "lts": "l", "litro": "l", "litros": "l", "ml": "ml", "cc": "ml", "gr": "g", "grs": "g", "gramos": "g", "g": "g",
            "kg": "kg", "kgs": "kg", "kilo": "kg", "un": "u", "unid": "u", "unidades": "u", "u": "u"}


@dataclass
class Emparejamiento:
    producto_id: int | None
    confianza: float
    metodo: str                       # ean, codigo, alias, similitud, ninguno
    candidatos: list[dict]


def normalizar(texto: str | None) -> str:
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"(\d),(\d)", r"\1.\2", texto)
    texto = re.sub(r"(\d)\s*(kg|kgs|g|gr|grs|ml|cc|l|lt|lts|u|un)\b", r"\1 \2", texto)
    return re.sub(r"[^a-z0-9. ]+", " ", texto).strip()


def fichas(texto: str | None) -> tuple[set[str], set[str]]:
    """(palabras significativas, cantidades normalizadas como '1.5 l', '500 g')."""
    t = normalizar(texto)
    partes = t.split()
    cantidades = set()
    for i, p in enumerate(partes):
        if re.fullmatch(r"\d+(\.\d+)?", p) and i + 1 < len(partes) and partes[i + 1] in UNIDADES:
            valor = float(p)
            unidad = UNIDADES[partes[i + 1]]
            if unidad == "l" and valor < 10:
                valor, unidad = valor * 1000, "ml"
            if unidad == "kg":
                valor, unidad = valor * 1000, "g"
            cantidades.add(f"{valor:g} {unidad}")
    palabras = {p for p in partes if p not in PALABRAS_VACIAS and not re.fullmatch(r"\d+(\.\d+)?", p) and p not in UNIDADES and len(p) > 1}
    return palabras, cantidades


def similitud(a: str | None, b: str | None) -> float:
    """0 a 1: palabras en común (Jaccard), mismas cantidades (1,5 L = 1500 ml) y orden de las letras."""
    pa, ca = fichas(a)
    pb, cb = fichas(b)
    if not pa or not pb:
        return 0.0
    jaccard = len(pa & pb) / len(pa | pb)
    if ca and cb:
        cantidades = 1.0 if ca & cb else 0.0
    else:
        cantidades = 0.5
    orden = SequenceMatcher(None, normalizar(a), normalizar(b)).ratio()
    return round(0.55 * jaccard + 0.25 * cantidades + 0.20 * orden, 4)


def emparejar(conn, *, ean: str | None = None, codigo: str | None = None, texto: str | None = None, origen: str = "archivo",
              origen_id: int | None = None, productos: list[dict] | None = None) -> Emparejamiento:
    ean = (ean or "").strip() or None
    codigo = (codigo or "").strip() or None
    if ean:
        f = db.fila(conn, "SELECT id FROM productos WHERE ean=%s", (ean,))
        if f:
            return Emparejamiento(f["id"], 1.0, "ean", [])
    if codigo:
        f = db.fila(conn, "SELECT id FROM productos WHERE codigo_interno=%s OR ean=%s", (codigo, codigo))
        if f:
            return Emparejamiento(f["id"], 1.0, "codigo", [])
        f = db.fila(conn, "SELECT producto_id FROM producto_proveedores WHERE codigo_proveedor=%s AND (%s::bigint IS NULL OR proveedor_id=%s) LIMIT 1",
                    (codigo, origen_id, origen_id))
        if f:
            return Emparejamiento(f["producto_id"], 1.0, "codigo", [])
        f = db.fila(conn, "SELECT producto_id FROM alias_producto WHERE codigo=%s AND origen=%s AND origen_id IS NOT DISTINCT FROM %s LIMIT 1",
                    (codigo, origen, origen_id))
        if f:
            return Emparejamiento(f["producto_id"], 0.99, "alias", [])
    if texto:
        f = db.fila(conn, "SELECT producto_id FROM alias_producto WHERE lower(texto)=lower(%s) AND origen=%s AND origen_id IS NOT DISTINCT FROM %s LIMIT 1",
                    (texto.strip(), origen, origen_id))
        if f:
            return Emparejamiento(f["producto_id"], 0.98, "alias", [])
        lista = productos if productos is not None else db.filas(conn, "SELECT id, nombre, marca, codigo_interno, ean FROM productos WHERE activo")
        puntajes = sorted(((similitud(texto, p["nombre"]), p) for p in lista), key=lambda x: -x[0])[:5]
        candidatos = [{"producto_id": p["id"], "nombre": p["nombre"], "codigo": p["codigo_interno"], "confianza": s}
                      for s, p in puntajes if s >= UMBRAL_SUGERENCIA]
        if candidatos and candidatos[0]["confianza"] >= UMBRAL_AUTOMATICO and \
                (len(candidatos) == 1 or candidatos[0]["confianza"] - candidatos[1]["confianza"] >= 0.05):
            return Emparejamiento(candidatos[0]["producto_id"], candidatos[0]["confianza"], "similitud", candidatos)
        return Emparejamiento(None, candidatos[0]["confianza"] if candidatos else 0.0, "ninguno", candidatos)
    return Emparejamiento(None, 0.0, "ninguno", [])


def guardar_alias(conn, org_id: int, producto_id: int, origen: str, origen_id: int | None, codigo: str | None, texto: str | None,
                  usuario_id: int | None) -> None:
    if not (codigo or texto):
        return
    existe = db.fila(conn, "SELECT 1 FROM alias_producto WHERE producto_id=%s AND origen=%s AND origen_id IS NOT DISTINCT FROM %s "
                           "AND codigo IS NOT DISTINCT FROM %s AND texto IS NOT DISTINCT FROM %s", (producto_id, origen, origen_id, codigo, texto))
    if not existe:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO alias_producto (org_id, producto_id, origen, origen_id, codigo, texto, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (org_id, producto_id, origen, origen_id, codigo, texto, usuario_id))


def vincular_maestro(conn, producto: dict) -> tuple[int | None, str]:
    """Vincula un producto de la empresa al catálogo maestro: por EAN exacto; si no hay EAN, queda como propio (a granel o
    elaboración propia); si hay EAN que el maestro no conoce, se sugiere el más parecido y queda «sin mapear»."""
    if not producto.get("ean"):
        return None, "propio"
    f = db.fila(conn, "SELECT id FROM productos_maestros WHERE ean=%s", (producto["ean"],))
    if f:
        return f["id"], "mapeado"
    return None, "sin_mapear"


def sugerencias_maestro(conn, texto: str, limite: int = 3) -> list[dict]:
    lista = db.filas(conn, "SELECT id, ean, nombre, marca FROM productos_maestros")
    puntajes = sorted(((similitud(texto, m["nombre"]), m) for m in lista), key=lambda x: -x[0])[:limite]
    return [{"maestro_id": m["id"], "ean": m["ean"], "nombre": m["nombre"], "confianza": s} for s, m in puntajes if s >= UMBRAL_SUGERENCIA]
