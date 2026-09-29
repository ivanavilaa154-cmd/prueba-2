"""Distribución y preventa: predicciones 33 a 39 del documento «Predicciones con IA para Retail».

Con los pedidos, ventas, devoluciones y clientes del ERP (Odoo u otro), para un distribuidor que vende a comercios:
33 pedido sugerido por cliente, 34 clientes en riesgo de dejar de comprar, 35 carga por zona y día, 36 entregas con riesgo de fallar,
37 devoluciones esperadas, 38 puntos de venta con potencial y 39 stock estimado en el canal.

Igual que el tablero: las consultas pasan por el conector con el usuario (el vendedor ve solo su cartera) y las cuentas se hacen acá,
en código. Cada bloque dice qué datos le faltan en lugar de inventarlos. Todos los pronósticos traen su rango (80 %).
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, timedelta

from ..permisos import Usuario
from .tablero import _kpi, _q, _seccion, _SinDatos

Z = 1.2816                          # 80 % de confianza, igual que en Retail
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _f(texto: str | None) -> date | None:
    return date.fromisoformat(texto[:10]) if texto else None


def _logistica(x: float) -> float:
    return 1 / (1 + math.exp(-x))


class Datos:
    """Lo que usan todos los bloques, leído una vez (con los permisos del usuario)."""

    def __init__(self, usuario: Usuario):
        self.u = usuario
        fin = _q(usuario, "SELECT MAX(fecha) FROM ventas WHERE anulada = 0")
        if not fin or not fin[0][0]:
            raise _SinDatos("No hay ventas cargadas.")
        self.hoy = _f(fin[0][0]) + timedelta(days=1)
        desde = (self.hoy - timedelta(days=180)).isoformat()
        self.clientes = {}
        for cid, rs, nf, zona, tipo, dia, estado in _q(usuario, "SELECT id, razon_social, nombre_fantasia, zona, tipo, dia_visita, estado FROM clientes"):
            self.clientes[cid] = {"nombre": nf or rs or f"Cliente {cid}", "zona": zona or "Sin zona", "tipo": tipo or "Sin tipo",
                                  "dia_visita": dia, "activo": (estado or "activo") != "inactivo"}
        self.productos = {}
        try:
            for pid, desc, cat, peso in _q(usuario, "SELECT id, descripcion, categoria, peso_kg FROM productos"):
                self.productos[pid] = {"nombre": desc or f"Producto {pid}", "categoria": cat or "Sin categoría", "peso": peso}
        except Exception:
            pass
        self.lineas = []                 # (cliente, fecha, producto, cantidad, importe)
        for cid, fecha, pid, cant, imp in _q(usuario, f"""
                SELECT v.cliente_id, v.fecha, l.producto_id, l.cantidad, l.cantidad * l.precio_unitario
                FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id
                WHERE v.anulada = 0 AND v.fecha >= '{desde}' AND v.cliente_id IS NOT NULL"""):
            self.lineas.append((cid, _f(fecha), pid, float(cant or 0), float(imp or 0)))
        if not self.lineas:
            raise _SinDatos("No hay ventas a clientes en los últimos 6 meses.")

    def nombre(self, cid) -> str:
        return self.clientes.get(cid, {}).get("nombre", f"Cliente {cid}")

    def producto(self, pid) -> str:
        return self.productos.get(pid, {}).get("nombre", f"Producto {pid}")

    def compras_por_cliente(self) -> dict:
        """cliente → {fechas de compra, importe por fecha, cantidades por producto y fecha}."""
        c = defaultdict(lambda: {"fechas": set(), "importe": defaultdict(float), "prod": defaultdict(lambda: defaultdict(float))})
        for cid, f, pid, cant, imp in self.lineas:
            x = c[cid]
            x["fechas"].add(f)
            x["importe"][f] += imp
            x["prod"][pid][f] += cant
        return c


def _ciclo(fechas: list[date]) -> float | None:
    if len(fechas) < 3:
        return None
    gaps = [(b - a).days for a, b in zip(fechas, fechas[1:]) if (b - a).days > 0]
    return max(1.0, statistics.median(gaps)) if gaps else None


# ------------------------------------------------------------------------------ 33 pedido sugerido
def pedido_sugerido(d: Datos) -> dict:
    filas, total = [], 0.0
    precios = defaultdict(lambda: [0.0, 0.0])                     # (cliente, producto) → [cantidad, importe]
    for cid, f, pid, cant, imp in d.lineas:
        precios[(cid, pid)][0] += cant
        precios[(cid, pid)][1] += imp
    for cid, x in d.compras_por_cliente().items():
        fechas = sorted(x["fechas"])
        ciclo = _ciclo(fechas)
        if not ciclo:
            continue
        ultima = fechas[-1]
        proxima = max(d.hoy, ultima + timedelta(days=round(ciclo)))
        recientes = [f for f in fechas if f >= d.hoy - timedelta(days=90)]
        if not recientes:
            continue
        sugerido, monto = [], 0.0
        for pid, por_fecha in x["prod"].items():
            en_90 = [por_fecha.get(f, 0.0) for f in recientes]
            veces = sum(1 for q in en_90 if q > 0)
            if veces / len(recientes) < 0.3:              # lo compra menos de 1 de cada 3 veces: no se sugiere
                continue
            # Promedio por pedido ponderando más los recientes; redondeado a unidad.
            pesos = [0.5 ** ((len(en_90) - 1 - i) / 4) for i in range(len(en_90))]
            q = sum(a * b for a, b in zip(en_90, pesos)) / sum(pesos)
            if q >= 0.5:
                precio = precios[(cid, pid)][1] / max(1e-9, precios[(cid, pid)][0])
                sugerido.append((d.producto(pid), round(q), round(q) * precio))
                monto += round(q) * precio
        if not sugerido:
            continue
        sugerido.sort(key=lambda s: -s[2])
        # Rango del monto: variación del importe de sus pedidos de los últimos 90 días.
        importes = [x["importe"][f] for f in recientes]
        desvio = statistics.pstdev(importes) if len(importes) > 1 else monto * 0.3
        texto = ", ".join(f"{n} × {q}" for n, q, _ in sugerido[:4]) + (f" y {len(sugerido) - 4} más" if len(sugerido) > 4 else "")
        c = d.clientes.get(cid, {})
        filas.append([d.nombre(cid), c.get("zona", "—"), proxima.isoformat(), round(ciclo), texto, round(monto, 2),
                      f"{round(max(0, monto - Z * desvio)):,} a {round(monto + Z * desvio):,}".replace(",", ".")])
        total += monto
    if not filas:
        raise _SinDatos("Hace falta al menos 3 compras por cliente para calcular su ciclo.")
    filas.sort(key=lambda f: (f[2], -f[5]))
    en_7 = [f for f in filas if f[2] <= (d.hoy + timedelta(days=6)).isoformat()]
    return {"titulo": "33 · Pedido sugerido por cliente",
            "descripcion": "Qué va a pedir cada cliente y cuándo, según su ciclo de compra y lo que suele llevar. Para que el preventista llegue con el pedido armado.",
            "kpis": [_kpi("Clientes que compran esta semana", len(en_7), "numero"),
                     _kpi("Pedido esperado esta semana", round(sum(f[5] for f in en_7), 2), "moneda"),
                     _kpi("Clientes con pedido sugerido", len(filas), "numero")],
            "paneles": [{"titulo": "Pedido sugerido", "ancho": True, "columnas": ["Cliente", "Zona", "Próxima compra", "Ciclo (días)", "Sugerido",
                                                                                 "Monto", "Rango 80 %"],
                         "tipos": ["t", "t", "t", "n", "t", "$", "t"], "filas": filas[:40], "vacio": "Sin clientes con ciclo de compra."}]}


# ------------------------------------------------------------------------------ 34 clientes en riesgo
def clientes_en_riesgo(d: Datos) -> dict:
    filas = []
    for cid, x in d.compras_por_cliente().items():
        fechas = sorted(x["fechas"])
        ciclo = _ciclo(fechas) or 30.0
        sin = (d.hoy - fechas[-1]).days
        r60 = sum(v for f, v in x["importe"].items() if f >= d.hoy - timedelta(days=60))
        p60 = sum(v for f, v in x["importe"].items() if d.hoy - timedelta(days=120) <= f < d.hoy - timedelta(days=60))
        caida = (r60 / p60 - 1) if p60 else 0.0
        atraso = sin / ciclo
        prob = _logistica(-2.5 + 1.6 * max(0.0, atraso - 1) + 3.0 * max(0.0, -caida - 0.1))
        mensual = sum(x["importe"].values()) / 6
        razones = []
        if atraso > 1.3:
            razones.append(f"no compra hace {sin} días (suele cada {round(ciclo)})")
        if caida < -0.15 and p60:
            razones.append(f"compró {round(-caida * 100)} % menos en los últimos 60 días")
        if prob >= 0.25:
            c = d.clientes.get(cid, {})
            filas.append([d.nombre(cid), c.get("zona", "—"), fechas[-1].isoformat(), round(prob, 3), round(mensual, 2), round(mensual * prob, 2),
                          "; ".join(razones) or "compra menos seguido que antes",
                          "Visita del supervisor esta semana" if prob >= 0.5 else "Llamar y ofrecer lo que dejó de llevar"])
    filas.sort(key=lambda f: -f[5])
    return {"titulo": "34 · Clientes comerciales en riesgo",
            "descripcion": "Probabilidad de que un cliente deje de comprar: atraso contra su propio ciclo y caída de lo que compra.",
            "kpis": [_kpi("Clientes en riesgo", len(filas), "numero", estado="alerta" if filas else "ok"),
                     _kpi("Venta mensual en riesgo", round(sum(f[5] for f in filas), 2), "moneda")],
            "paneles": [{"titulo": "Clientes en riesgo", "ancho": True, "columnas": ["Cliente", "Zona", "Última compra", "Probabilidad", "Compra mensual",
                                                                                      "En riesgo por mes", "Por qué", "Qué hacer"],
                         "tipos": ["t", "t", "t", "%", "$", "$", "t", "t"], "filas": filas, "vacio": "Ningún cliente muestra señales de abandono."}]}


# ------------------------------------------------------------------------------ pedidos (35 y 36)
def _pedidos(d: Datos, dias: int = 120) -> list[dict]:
    desde = (d.hoy - timedelta(days=dias)).isoformat()
    lineas = defaultdict(lambda: [0.0, 0.0, 0.0])
    for pid_ped, prod, ped, ent in _q(d.u, f"""SELECT l.pedido_id, l.producto_id, l.cantidad_pedida, l.cantidad_entregada FROM pedidos_lineas l
                                               JOIN pedidos p ON p.id = l.pedido_id WHERE p.fecha_pedido >= '{desde}'"""):
        x = lineas[pid_ped]
        x[0] += float(ped or 0)
        x[1] += float(ent if ent is not None else ped or 0)
        x[2] += float(ped or 0) * float(d.productos.get(prod, {}).get("peso") or 0)
    salida = []
    for pid, cid, fp, prometida, entrega, estado in _q(d.u, f"""SELECT id, cliente_id, fecha_pedido, fecha_entrega_prometida, fecha_entrega, estado
                                                               FROM pedidos WHERE fecha_pedido >= '{desde}'"""):
        ped, ent, kg = lineas.get(pid, [0.0, 0.0, 0.0])
        prom, real = _f(prometida), _f(entrega)
        estado = (estado or "").lower()
        abierto = estado not in ("entregado", "anulado", "cancelado", "rechazado") and not real
        fallo = None
        if not abierto:
            fallo = (estado in ("anulado", "cancelado", "rechazado") or (prom and real and real > prom) or (ped > 0 and ent < ped * 0.98))
        salida.append({"id": pid, "cliente": cid, "zona": d.clientes.get(cid, {}).get("zona", "Sin zona"), "pedido": _f(fp),
                       "dia": prom or _f(fp) + timedelta(days=1), "unidades": ped, "kg": kg, "abierto": abierto, "fallo": fallo,
                       "tarde": bool(prom and real and real > prom), "incompleto": bool(ped > 0 and ent < ped * 0.98)})
    return salida


def carga_por_zona(d: Datos) -> dict:
    pedidos = _pedidos(d, 70)
    if not pedidos:
        raise _SinDatos("No hay pedidos en los últimos 70 días.")
    # Por zona y día de la semana: pedidos, unidades y kg por fecha de entrega, en las últimas 8 semanas.
    por_fecha = defaultdict(lambda: [0, 0.0, 0.0])
    for p in pedidos:
        if p["dia"] < d.hoy - timedelta(days=56) or p["dia"] >= d.hoy:
            continue
        x = por_fecha[(p["zona"], p["dia"])]
        x[0] += 1
        x[1] += p["unidades"]
        x[2] += p["kg"]
    zonas = sorted({z for z, _ in por_fecha})
    abiertos = defaultdict(lambda: [0, 0.0, 0.0])
    for p in pedidos:
        if p["abierto"] and p["dia"] >= d.hoy:
            x = abiertos[(p["zona"], p["dia"])]
            x[0] += 1
            x[1] += p["unidades"]
            x[2] += p["kg"]
    filas, por_dia = [], defaultdict(float)
    for i in range(14):
        dia = d.hoy + timedelta(days=i)
        for z in zonas:
            hist = [por_fecha.get((z, dia - timedelta(days=7 * k)), [0, 0.0, 0.0]) for k in range(1, 9)]
            n = [h[0] for h in hist]
            media = statistics.mean(n)
            if media < 0.2 and not abiertos.get((z, dia)):
                continue
            desvio = max(math.sqrt(media), statistics.pstdev(n)) * math.sqrt(1 + 1 / len(n))
            ya = abiertos.get((z, dia), [0, 0.0, 0.0])
            esperado = max(media, ya[0])
            unidades = max(statistics.mean(h[1] for h in hist), ya[1])
            kg = max(statistics.mean(h[2] for h in hist), ya[2])
            filas.append([dia.isoformat(), DIAS[dia.weekday()], z, round(esperado, 1), f"{max(ya[0], round(esperado - Z * desvio))} a {round(esperado + Z * desvio)}",
                          ya[0], round(unidades), round(kg) if kg else None])
            por_dia[dia] += unidades
    pico = max(por_dia.items(), key=lambda x: x[1]) if por_dia else None
    return {"titulo": "35 · Carga por zona y día",
            "descripcion": "Pedidos, bultos y kilos esperados por zona para las próximas 2 semanas: para armar recorridos y camiones antes de que lleguen los pedidos.",
            "kpis": [_kpi("Día más cargado", f"{DIAS[pico[0].weekday()]} {pico[0].strftime('%d/%m')}" if pico else None, "texto",
                          nota=f"{round(pico[1])} unidades" if pico else None),
                     _kpi("Pedidos ya cargados para los próximos 14 días", sum(v[0] for v in abiertos.values()), "numero")],
            "paneles": [{"titulo": "Próximas 2 semanas", "ancho": True, "columnas": ["Fecha", "Día", "Zona", "Pedidos esperados", "Rango 80 %",
                                                                                      "Ya cargados", "Unidades", "Kg"],
                         "tipos": ["t", "t", "t", "n", "t", "n", "n", "n"], "filas": filas, "vacio": "Sin historia de entregas por zona."}]}


def entregas_fallidas(d: Datos) -> dict:
    pedidos = [p for p in _pedidos(d, 120)]
    cerrados = [p for p in pedidos if not p["abierto"]]
    if len(cerrados) < 20:
        raise _SinDatos("Hacen falta al menos 20 entregas con fecha prometida y real.")
    general = sum(1 for p in cerrados if p["fallo"]) / len(cerrados)
    zona = defaultdict(lambda: [0, 0])
    dia = defaultdict(lambda: [0, 0])
    cli = defaultdict(lambda: [0, 0])
    for p in cerrados:
        for dic, k in ((zona, p["zona"]), (dia, p["dia"].weekday()), (cli, p["cliente"])):
            dic[k][0] += 1 if p["fallo"] else 0
            dic[k][1] += 1
    K = 8                                                          # cuánto pesa la zona frente a la historia propia del cliente
    def prob_zona(z):
        f, n = zona[z]
        return (f + K * general) / (n + K)

    def prob_cliente(c, z):
        f, n = cli[c]
        return (f + K * prob_zona(z)) / (n + K)
    riesgo_cli = sorted(((c, prob_cliente(c, d.clientes.get(c, {}).get("zona", "Sin zona")), cli[c]) for c in cli), key=lambda x: -x[1])
    proximos = sorted((p for p in pedidos if p["abierto"]), key=lambda p: -prob_cliente(p["cliente"], p["zona"]))
    reciente = [p for p in cerrados if p["dia"] >= d.hoy - timedelta(days=30)]
    anterior = [p for p in cerrados if d.hoy - timedelta(days=60) <= p["dia"] < d.hoy - timedelta(days=30)]
    tasa = lambda ps: sum(1 for p in ps if p["fallo"]) / len(ps) if ps else None
    return {"titulo": "36 · Entregas con riesgo de fallar",
            "descripcion": "Probabilidad de que una entrega llegue tarde, incompleta o se rechace, por cliente, zona y día (con la historia de cada uno).",
            "kpis": [_kpi("Entregas con problema (30 días)", tasa(reciente), "porcentaje",
                          variacion=(tasa(reciente) - tasa(anterior)) if reciente and anterior else None),
                     _kpi("Llegaron tarde", sum(1 for p in reciente if p["tarde"]), "numero"),
                     _kpi("Incompletas", sum(1 for p in reciente if p["incompleto"]), "numero")],
            "paneles": [
                {"titulo": "Pedidos abiertos con más riesgo", "columnas": ["Pedido", "Cliente", "Zona", "Entrega", "Probabilidad de problema"],
                 "tipos": ["n", "t", "t", "t", "%"], "vacio": "No hay pedidos abiertos.",
                 "filas": [[p["id"], d.nombre(p["cliente"]), p["zona"], p["dia"].isoformat(), round(prob_cliente(p["cliente"], p["zona"]), 3)]
                           for p in proximos[:15]]},
                {"titulo": "Clientes con más problemas de entrega", "columnas": ["Cliente", "Entregas", "Con problema", "Probabilidad próxima"],
                 "tipos": ["t", "n", "n", "%"], "vacio": "Sin entregas.",
                 "filas": [[d.nombre(c), n[1], n[0], round(p, 3)] for c, p, n in riesgo_cli[:10]]},
                {"titulo": "Por zona y día", "columnas": ["Zona o día", "Entregas", "Con problema", "Tasa"], "tipos": ["t", "n", "n", "%"], "vacio": "—",
                 "filas": [[z, n, f, round(f / n, 3)] for z, (f, n) in sorted(zona.items())] +
                          [[DIAS[k].capitalize(), n, f, round(f / n, 3)] for k, (f, n) in sorted(dia.items())]},
            ]}


# ------------------------------------------------------------------------------ 37 devoluciones
def devoluciones(d: Datos) -> dict:
    desde = (d.hoy - timedelta(days=180)).isoformat()
    devs = _q(d.u, f"SELECT fecha, cliente_id, producto_id, cantidad, importe, motivo FROM devoluciones WHERE fecha >= '{desde}'")
    venta_prod, venta_cli, venta_30 = defaultdict(float), defaultdict(float), defaultdict(float)
    for cid, f, pid, cant, imp in d.lineas:
        venta_prod[pid] += imp
        venta_cli[cid] += imp
        if f >= d.hoy - timedelta(days=30):
            venta_30[pid] += imp
    total_venta = sum(venta_prod.values())
    if not devs:
        raise _SinDatos("No hay devoluciones registradas en los últimos 6 meses.")
    dev_prod, dev_cli, motivos = defaultdict(float), defaultdict(float), defaultdict(float)
    for f, cid, pid, cant, imp, motivo in devs:
        dev_prod[pid] += float(imp or 0)
        dev_cli[cid] += float(imp or 0)
        motivos[(motivo or "sin motivo").lower()] += float(imp or 0)
    tasa = sum(dev_prod.values()) / total_venta if total_venta else 0
    # Proyección a 30 días: tasa suavizada por producto × venta de los últimos 30 días de ese producto.
    K = 20000.0                                                    # pesos de venta que «pesan» como la tasa general
    esperado = 0.0
    prod_filas = []
    for pid in set(venta_prod) | set(dev_prod):
        t = (dev_prod[pid] + K * tasa) / (venta_prod[pid] + K)
        v30 = venta_30[pid]
        esperado += t * v30
        if dev_prod[pid]:
            prod_filas.append([d.producto(pid), round(venta_prod[pid], 2), round(dev_prod[pid], 2), round(dev_prod[pid] / venta_prod[pid], 4) if venta_prod[pid] else None,
                               round(t * v30, 2)])
    prod_filas.sort(key=lambda f: -f[4])
    n_meses = 6
    desvio = math.sqrt(max(esperado, 1.0) * (sum(float(x[4] or 0) for x in devs) / max(1, len(devs))))   # conteo de Poisson × importe medio
    return {"titulo": "37 · Devoluciones esperadas",
            "descripcion": "Cuánto van a devolver los clientes en los próximos 30 días y de qué productos, según la tasa de devolución de cada uno.",
            "kpis": [_kpi("Devoluciones esperadas (30 días)", round(esperado, 2), "moneda",
                          nota=f"entre $ {round(max(0, esperado - Z * desvio)):,} y $ {round(esperado + Z * desvio):,} (80 %)".replace(",", ".")),
                     _kpi("Tasa de devolución (6 meses)", round(tasa, 4), "porcentaje"),
                     _kpi("Promedio mensual devuelto", round(sum(dev_prod.values()) / n_meses, 2), "moneda")],
            "paneles": [
                {"titulo": "Productos", "columnas": ["Producto", "Vendido 6 meses", "Devuelto", "Tasa", "Esperado 30 días"], "tipos": ["t", "$", "$", "%", "$"],
                 "filas": prod_filas[:12], "vacio": "—"},
                {"titulo": "Motivos", "columnas": ["Motivo", "Importe", "Participación"], "tipos": ["t", "$", "%"], "vacio": "—",
                 "filas": [[m.capitalize(), round(v, 2), round(v / sum(motivos.values()), 4)] for m, v in sorted(motivos.items(), key=lambda x: -x[1])]},
                {"titulo": "Clientes que más devuelven", "columnas": ["Cliente", "Compró", "Devolvió", "Tasa"], "tipos": ["t", "$", "$", "%"], "vacio": "—",
                 "filas": sorted([[d.nombre(c), round(venta_cli[c], 2), round(v, 2), round(v / venta_cli[c], 4) if venta_cli[c] else None]
                                  for c, v in dev_cli.items()], key=lambda f: -(f[3] or 0))[:10]},
            ]}


# ------------------------------------------------------------------------------ 38 puntos con potencial
def potencial(d: Datos) -> dict:
    desde = d.hoy - timedelta(days=90)
    compra = defaultdict(lambda: defaultdict(float))          # cliente → categoría → $ por mes
    for cid, f, pid, cant, imp in d.lineas:
        if f >= desde:
            compra[cid][d.productos.get(pid, {}).get("categoria", "Sin categoría")] += imp / 3
    por_tipo = defaultdict(list)
    for cid in compra:
        por_tipo[d.clientes.get(cid, {}).get("tipo", "Sin tipo")].append(cid)
    filas = []
    for tipo, clientes in por_tipo.items():
        if len(clientes) < 3:
            continue
        categorias = {cat for c in clientes for cat in compra[c]}
        mediana = {cat: statistics.median([compra[c].get(cat, 0.0) for c in clientes]) for cat in categorias}
        for c in clientes:
            brechas = sorted(((cat, mediana[cat] - compra[c].get(cat, 0.0)) for cat in categorias if mediana[cat] > compra[c].get(cat, 0.0) * 1.2),
                             key=lambda x: -x[1])
            pot = sum(b for _, b in brechas)
            if pot <= 0:
                continue
            total = sum(compra[c].values())
            filas.append([d.nombre(c), tipo, d.clientes.get(c, {}).get("zona", "—"), round(total, 2), round(sum(mediana.values()), 2), round(pot, 2),
                          ", ".join(cat for cat, _ in brechas[:3])])
    filas.sort(key=lambda f: -f[5])
    if not filas:
        raise _SinDatos("Hacen falta al menos 3 clientes del mismo tipo para compararlos.")
    return {"titulo": "38 · Puntos de venta con potencial",
            "descripcion": "Cuánto más podría comprarte cada cliente si llevara lo mismo que la mitad de los comercios parecidos (mismo tipo), y en qué categorías.",
            "kpis": [_kpi("Potencial mensual sin explotar", round(sum(f[5] for f in filas), 2), "moneda"),
                     _kpi("Clientes con potencial", len(filas), "numero")],
            "paneles": [{"titulo": "Dónde crecer", "ancho": True, "columnas": ["Cliente", "Tipo", "Zona", "Compra mensual", "Mediana de su tipo",
                                                                                "Potencial mensual", "Categorías a ofrecer"],
                         "tipos": ["t", "t", "t", "$", "$", "$", "t"], "filas": filas[:25], "vacio": "—"}]}


# ------------------------------------------------------------------------------ 39 stock en el canal
def stock_en_canal(d: Datos) -> dict:
    compras = d.compras_por_cliente()
    por_prod = defaultdict(lambda: [0.0, 0.0])                 # producto → [stock estimado, consumo diario]
    alertas = []
    for cid, x in compras.items():
        ciclo = _ciclo(sorted(x["fechas"])) or 30.0
        for pid, por_fecha in x["prod"].items():
            en_90 = sum(q for f, q in por_fecha.items() if f >= d.hoy - timedelta(days=90))
            if en_90 <= 0:
                continue
            ritmo = en_90 / 90
            ultima = max(por_fecha)
            # Lo que le queda: lo que compró la última vez (más un sobrante del ciclo anterior acotado a medio ciclo) menos lo que vendió desde entonces.
            stock = max(0.0, por_fecha[ultima] - ritmo * (d.hoy - ultima).days)
            por_prod[pid][0] += stock
            por_prod[pid][1] += ritmo
            cobertura = stock / ritmo if ritmo else None
            if cobertura is not None and cobertura > max(2 * ciclo, 14) and stock >= 5:
                alertas.append([d.nombre(cid), d.producto(pid), round(stock), round(cobertura), "Sobrestock: no empujar, ofrecer rotación o promo"])
            elif (stock == 0 and (d.hoy - ultima).days >= max(7, 2 * ciclo)
                  and sum(1 for f in por_fecha if f >= d.hoy - timedelta(days=90)) >= 0.5 * sum(1 for f in x["fechas"] if f >= d.hoy - timedelta(days=90))):
                # Lo llevaba en la mitad de sus compras o más y hace dos ciclos que no lo pide: se le debe haber terminado.
                alertas.append([d.nombre(cid), d.producto(pid), 0, 0, "Probable quiebre en góndola: visitar y reponer"])
    if not por_prod:
        raise _SinDatos("No hay compras recientes de los clientes.")
    filas = sorted(([d.producto(p), round(s), round(r, 1), round(s / r, 1) if r else None] for p, (s, r) in por_prod.items()), key=lambda f: -f[1])
    total_s, total_r = sum(s for s, _ in por_prod.values()), sum(r for _, r in por_prod.values())
    return {"titulo": "39 · Stock estimado en el canal",
            "descripcion": "Cuánta mercadería tuya queda en los comercios (estimado con lo que compraron y su ritmo de venta) y dónde hay sobrestock o quiebre. "
                           "Es una estimación: con el sell-out real del Panel de marcas se afina.",
            "kpis": [_kpi("Unidades en el canal", round(total_s), "numero"),
                     _kpi("Días de canal", round(total_s / total_r, 1) if total_r else None, "dias"),
                     _kpi("Clientes con sobrestock o quiebre", len({a[0] for a in alertas}), "numero", estado="alerta" if alertas else "ok")],
            "paneles": [{"titulo": "Por producto", "columnas": ["Producto", "Unidades estimadas", "Venta diaria", "Días de canal"], "tipos": ["t", "n", "n", "n"],
                         "filas": filas[:15], "vacio": "—"},
                        {"titulo": "Dónde actuar", "columnas": ["Cliente", "Producto", "Stock estimado", "Días que cubre", "Qué hacer"],
                         "tipos": ["t", "t", "n", "n", "t"], "filas": sorted(alertas, key=lambda a: -a[3])[:20], "vacio": "Sin sobrestock ni quiebres estimados."}]}


BLOQUES = [pedido_sugerido, clientes_en_riesgo, carga_por_zona, entregas_fallidas, devoluciones, potencial, stock_en_canal]


def distribucion(usuario: Usuario) -> dict:
    d = _seccion(Datos, usuario)
    if isinstance(d, dict):                                        # sin acceso o sin datos: se dice por qué
        return {"grupos": [], **d}
    grupos = []
    for fn in BLOQUES:
        s = _seccion(fn, d)
        if "titulo" not in s:
            s = {"titulo": fn.__name__.replace("_", " ").capitalize(), "descripcion": s.get("mensaje"), "kpis": [], "paneles": []}
        grupos.append(s)
    return {"hoy": d.hoy.isoformat(), "ultimo_dato": (d.hoy - timedelta(days=1)).isoformat(), "grupos": grupos}
