"""PDF de la orden de compra y etiquetas de góndola (fpdf2, fuentes base: se limpia lo que no entra en Latin-1)."""
from __future__ import annotations

from pathlib import Path

from .explicar import num

CARPETA = Path(__file__).resolve().parents[2] / "documentos"


def _t(texto) -> str:
    return str(texto if texto is not None else "").replace("—", "-").replace("–", "-").replace("“", '"').replace("”", '"') \
        .encode("latin-1", "replace").decode("latin-1")


def orden_compra(empresa: dict, oc: dict, proveedor: dict, lineas: list[dict], destino: str) -> Path:
    from fpdf import FPDF
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _t(f"Orden de compra {oc['numero']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for linea in (f"{empresa['nombre']} - CUIT {empresa.get('cuit') or '-'}", f"Proveedor: {proveedor['razon_social']} - CUIT {proveedor.get('cuit') or '-'}",
                  f"Entregar en: {destino}", f"Fecha esperada: {oc['fecha_esperada'].strftime('%d/%m/%Y') if oc.get('fecha_esperada') else '-'}",
                  f"Condiciones de pago: {proveedor.get('condiciones_pago') or '-'}"):
        pdf.cell(0, 6, _t(linea), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 9)
    anchos = [22, 78, 22, 18, 25, 25]
    for w, h in zip(anchos, ["Código", "Producto", "Cantidad", "Bultos", "Costo unit.", "Subtotal"]):
        pdf.cell(w, 7, _t(h), border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    total = 0
    for l in lineas:
        sub = float(l["cantidad"]) * float(l["costo"] or 0)
        total += sub
        valores = [l.get("codigo_proveedor") or l["codigo_interno"], l["nombre"][:48] + (f" ({l['ubicacion']})" if l.get("ubicacion") and not destino.startswith(l["ubicacion"]) else ""),
                   num(l["cantidad"], 0), num(l.get("bultos") or 0, 1), f"$ {num(l['costo'] or 0, 2)}", f"$ {num(sub, 2)}"]
        for w, v in zip(anchos, valores):
            pdf.cell(w, 6, _t(v), border=1)
        pdf.ln()
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(sum(anchos[:-1]), 8, "Total", border=1)
    pdf.cell(anchos[-1], 8, _t(f"$ {num(total, 2)}"), border=1)
    CARPETA.mkdir(exist_ok=True)
    ruta = CARPETA / f"{oc['numero']}.pdf"
    pdf.output(str(ruta))
    return ruta


def etiquetas(productos: list[dict], titulo: str = "Precios actualizados") -> Path:
    """Etiquetas de góndola (3 × 8 por hoja A4): nombre, precio grande y fecha."""
    from datetime import date

    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(False)
    ancho, alto = 63, 34
    for i, p in enumerate(productos):
        if i % 24 == 0:
            pdf.add_page()
        col, fila = i % 3, (i % 24) // 3
        x, y = 7 + col * (ancho + 2), 10 + fila * (alto + 1)
        pdf.rect(x, y, ancho, alto)
        pdf.set_xy(x + 2, y + 2)
        pdf.set_font("Helvetica", "", 8)
        pdf.multi_cell(ancho - 4, 3.6, _t(p["nombre"][:70]))
        pdf.set_xy(x + 2, y + 13)
        pdf.set_font("Helvetica", "B", 22)
        pdf.cell(ancho - 4, 11, _t(f"$ {num(p['precio'], 2 if float(p['precio']) % 1 else 0)}"), align="C")
        pdf.set_xy(x + 2, y + 27)
        pdf.set_font("Helvetica", "", 6)
        pdf.cell(ancho - 4, 4, _t(f"{p.get('ean') or p.get('codigo_interno') or ''}   {date.today().strftime('%d/%m/%Y')}"))
    CARPETA.mkdir(exist_ok=True)
    ruta = CARPETA / f"etiquetas-{date.today().isoformat()}-{len(productos)}.pdf"
    pdf.output(str(ruta))
    return ruta


def cartel_oferta(nombre: str, oferta: dict, tamano: str = "a5") -> Path:
    """Cartel de góndola de una oferta: producto, precio normal tachado, precio de oferta grande y hasta cuándo."""
    from fpdf import FPDF
    p = oferta["parametros"]
    pdf = FPDF(orientation="L", format={"a4": (210, 297), "a5": (148, 210), "a6": (105, 148)}[tamano])   # mm
    pdf.set_auto_page_break(False)
    pdf.add_page()
    escala = {"a4": 1.4, "a5": 1.0, "a6": 0.7}[tamano]
    ancho = pdf.w - 20
    pdf.set_xy(10, 10 * escala)
    pdf.set_font("Helvetica", "B", int(34 * escala))
    pdf.cell(ancho, 16 * escala, "OFERTA", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", int(18 * escala))
    pdf.multi_cell(ancho, 9 * escala, _t(nombre[:80]), align="C")
    if oferta["tipo"] == "segunda_unidad":
        pdf.set_font("Helvetica", "B", int(26 * escala))
        pdf.cell(ancho, 14 * escala, _t(f"2.ª unidad {num(float(p['descuento']) * 100, 0)} % OFF"), align="C", new_x="LMARGIN", new_y="NEXT")
    antes = f"$ {num(p['precio_normal'], 0)}"
    pdf.set_font("Helvetica", "", int(20 * escala))
    y = pdf.get_y() + 3
    pdf.set_xy(10, y)
    pdf.cell(ancho, 10 * escala, _t(f"Antes {antes}"), align="C")
    w = pdf.get_string_width(f"Antes {antes}")
    pdf.line(10 + (ancho - w) / 2, y + 5 * escala, 10 + (ancho + w) / 2, y + 5 * escala)
    pdf.set_xy(10, y + 12 * escala)
    pdf.set_font("Helvetica", "B", int(64 * escala))
    pdf.cell(ancho, 28 * escala, _t(f"$ {num(p['precio_oferta'], 0)}"), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", int(12 * escala))
    pdf.cell(ancho, 8 * escala, _t(f"Válido hasta el {oferta['hasta'].strftime('%d/%m/%Y')} o hasta agotar stock"), align="C")
    CARPETA.mkdir(exist_ok=True)
    ruta = CARPETA / f"oferta-{oferta['id']}-{tamano}.pdf"
    pdf.output(str(ruta))
    return ruta
