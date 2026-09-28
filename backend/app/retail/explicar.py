"""Explicaciones en lenguaje simple de cada número (principio 4: «Explicable»)."""
from __future__ import annotations

from datetime import date, timedelta

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def num(x, decimales: int = 1) -> str:
    """1234.5 → «1.234,5» (formato argentino)."""
    if x is None:
        return "—"
    texto = f"{float(x):,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if decimales and texto.endswith("," + "0" * decimales):
        texto = texto[: -(decimales + 1)]
    return texto


def pesos(x) -> str:
    return "—" if x is None else f"$ {num(x, 2) if float(x) % 1 else num(x, 0)}"


def dia(hoy: date, dias: int) -> str:
    if dias <= 0:
        return "hoy"
    if dias == 1:
        return "mañana"
    d = hoy + timedelta(days=dias)
    return f"el {DIAS[d.weekday()]} {d.strftime('%d/%m')}"


def sugerencia(e: dict, cantidad: float, hoy: date, unidad: str = "unidades") -> str:
    """«Te sugiero 48 porque vendés 6 por día, el proveedor vuelve en 7 días y tarda 2 en entregar…»"""
    partes = []
    vpd = e.get("vpd") or 0
    base = f"vendés {num(vpd)} por día"
    detalle = []
    if e.get("dias_sin_stock"):
        detalle.append(f"sin contar {e['dias_sin_stock']} día{'s' if e['dias_sin_stock'] != 1 else ''} en que no hubo stock")
    if e.get("confianza") == "baja":
        detalle.append("con poca historia: se completó con el promedio de la categoría" if e.get("usa_referencia_categoria")
                       else "con poca historia")
    if detalle:
        base += f" ({', '.join(detalle)})"
    partes.append(base)
    prov = e.get("proveedor")
    if prov:
        if e.get("supuesto_proveedor"):
            partes.append(e["supuesto_proveedor"].rstrip(".").lower().replace("el proveedor", prov, 1))
        else:
            vuelve = e.get("proxima_oportunidad", 0)
            partes.append(f"{prov} {'pasa hoy' if vuelve == 0 else 'vuelve ' + dia(hoy, vuelve)} y tarda "
                          f"{e.get('demora')} día{'s' if e.get('demora') != 1 else ''} en entregar")
    cubrir = f"lo que pidas tiene que alcanzar {e.get('horizonte')} días ({num(e.get('pronostico_horizonte'))} {unidad} según el pronóstico)"
    if e.get("stock_seguridad"):
        cubrir += f" más {num(e['stock_seguridad'])} de seguridad"
    partes.append(cubrir)
    tiene = f"tenés {num(max(0, e.get('stock', 0) - e.get('reservado', 0)))} disponibles"
    if e.get("stock_negativo"):
        tiene = f"el sistema marca {num(e.get('stock'))} (stock negativo: se toma como 0 y conviene contarlo)"
    extras = []
    if e.get("en_transito"):
        extras.append(f"{num(e['en_transito'])} en tránsito")
    if e.get("pedidos_abiertos"):
        extras.append(f"{num(e['pedidos_abiertos'])} ya pedidas")
    if extras:
        tiene += " y " + " y ".join(extras)
    partes.append(tiene)
    if cantidad <= 0:
        return "No hace falta comprar: " + "; ".join(partes) + "."
    texto = f"Te sugiero {num(cantidad, 0)} porque " + ", ".join(partes[:2]) + ": " + "; ".join(partes[2:]) + "."
    if e.get("multiplo", 1) > 1:
        texto += f" Se redondeó hacia arriba al múltiplo de compra ({e['multiplo']} por bulto)."
    if e.get("recortada_por_maximo"):
        texto += " Se recortó para no pasar el stock máximo configurado."
    return texto


def semaforo(sem: str, quiebre: date | None, hoy: date, e: dict) -> str:
    llegada = e.get("llegada_proxima", 0)
    if sem == "rojo":
        return (f"Se agota {dia(hoy, (quiebre - hoy).days) if quiebre else 'ya'} y la próxima reposición posible llega "
                f"{dia(hoy, llegada)}: vas a tener días sin mercadería.")
    if sem == "amarillo":
        return f"Alcanza hasta la próxima reposición ({dia(hoy, llegada)}), pero hay que incluirlo en ese pedido."
    if sem == "gris":
        return "Sobrestock: tenés más de 30 días de venta (o no se vende). No compres y evaluá transferir o liquidar."
    return "Cubierto hasta el pedido siguiente."
