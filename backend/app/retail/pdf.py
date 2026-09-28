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
