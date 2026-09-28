"""Motor de alertas y avisos (sección 13.1). Corre después de cada cálculo.

Cada alerta tiene prioridad, impacto en pesos (perdido, en riesgo o recuperable), explicación y una acción con botón.
- Deduplicación: una alerta abierta con la misma clave se actualiza (no se repite).
- Si la condición desaparece, se resuelve sola («resuelta automáticamente»).
- Si vence sin resolverse, se escala al dueño.
Tipos de la Fase 1: quiebre, posible faltante en góndola, stock fantasma, transferencia sugerida, OC sugerida, OC por
escalar, sobrestock, stock muerto, vencimiento, margen erosionado, aumento de proveedor, anomalía de caja, diferencia de
inventario, caída de producto A. (Sobreventa online y meta en riesgo llegan con la Fase 2.)
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from . import calculos as C
from . import db
from .explicar import num, pesos

ETIQUETAS = {
    "quiebre": "Quiebre de stock", "gondola": "Posible faltante en góndola", "stock_fantasma": "Posible stock fantasma",
    "transferencia": "Transferencia sugerida", "orden_compra": "Orden de compra para aprobar", "oc_escalada": "OC sin aprobar",
    "sobrestock": "Sobrestock", "stock_muerto": "Stock muerto", "vencimiento": "Vencimiento", "margen": "Margen erosionado",
    "aumento_proveedor": "Aumento de proveedor", "caja": "Anomalía de caja", "inventario": "Diferencia de inventario",
    "caida_a": "Caída de un producto A",
}
DESTINOS = {
    "quiebre": ["dueno", "comprador", "encargado"], "gondola": ["encargado", "dueno"], "stock_fantasma": ["encargado", "dueno"],
    "transferencia": ["encargado", "dueno"], "orden_compra": ["comprador", "dueno"], "oc_escalada": ["dueno"],
    "sobrestock": ["comprador", "dueno"], "stock_muerto": ["comprador", "dueno"], "vencimiento": ["encargado", "comprador", "dueno"],
    "margen": ["comprador", "dueno"], "aumento_proveedor": ["comprador", "dueno"], "caja": ["dueno"], "inventario": ["dueno", "encargado"],
    "caida_a": ["comprador", "dueno"],
}
MINIMO_IMPACTO = Decimal("1000")      # por debajo de esto, no vale la pena molestar (configurable en parámetros)


def _nueva(tipo, prioridad, titulo, explicacion, impacto, tipo_impacto, accion, clave, ubicacion_id=None, producto_id=None,
           vence=None, grupo=None, datos=None) -> dict:
    return {"tipo": tipo, "prioridad": prioridad, "titulo": titulo, "explicacion": explicacion,
            "impacto": Decimal(impacto).quantize(Decimal("0.01")), "tipo_impacto": tipo_impacto, "accion": accion,
            "clave": clave, "ubicacion_id": ubicacion_id, "producto_id": producto_id, "vence": vence, "grupo": grupo or tipo,
            "datos": datos or {}}


def generar(org_id: int, hoy: date) -> dict:
    from .motor import contexto_sistema
    with db.transaccion(contexto_sistema(org_id)) as conn:
        return _generar(conn, org_id, hoy)


def _generar(conn, org_id: int, hoy: date) -> dict:
    param = db.fila(conn, "SELECT valor FROM parametros WHERE clave='alertas_minimo_impacto'")
    minimo = Decimal(str(param["valor"])) if param else MINIMO_IMPACTO
    zona = db.fila(conn, "SELECT zona_horaria FROM organizaciones WHERE id=%s", (org_id,))["zona_horaria"]
    ahora = datetime.now(ZoneInfo(zona))
    alertas: list[dict] = []
    metricas = db.filas(conn, """SELECT m.*, p.nombre, p.clase_abc AS clase, u.nombre AS ubicacion, u.tipo AS tipo_ubicacion, pp.costo,
                                        (SELECT precio FROM precios x WHERE x.producto_id = m.producto_id AND x.canal_id IS NULL AND x.ubicacion_id IS NULL
                                         AND x.hasta IS NULL ORDER BY x.desde DESC LIMIT 1) AS precio
                                 FROM metricas_producto_actual m JOIN productos p ON p.id = m.producto_id JOIN ubicaciones u ON u.id = m.ubicacion_id
                                 LEFT JOIN producto_proveedores pp ON pp.producto_id = m.producto_id AND pp.principal""")

    # --- quiebres
    for m in metricas:
        if m["semaforo"] != "rojo" or m["tipo_ubicacion"] == "deposito":
            continue
        impacto = m["ventas_en_riesgo"] or Decimal(0)
        if impacto < minimo and m["clase"] != "A":
            continue
        cuando = "ya no tiene stock" if not m["fecha_quiebre"] or m["fecha_quiebre"] <= hoy else f"se agota el {m['fecha_quiebre'].strftime('%d/%m')}"
        alertas.append(_nueva("quiebre", "urgente" if m["clase"] == "A" or impacto > 50000 else "normal",
                              f"{m['nombre']} {cuando} en {m['ubicacion']}",
                              f"Vende {num(m['vpd'])} por día y la próxima reposición no llega a tiempo: dejarías de vender {pesos(impacto)}. "
                              f"Sugerido: {num(m['cantidad_sugerida'], 0)} unidades.",
                              impacto, "perdida", {"etiqueta": "Ver y pedir", "tipo": "ir", "destino": f"/comprar/?producto={m['producto_id']}&u={m['ubicacion_id']}"},
                              f"quiebre:{m['producto_id']}:{m['ubicacion_id']}", m["ubicacion_id"], m["producto_id"], m["fecha_quiebre"] or hoy))

    # --- stock fantasma y stock muerto / sobrestock
    muertos = defaultdict(lambda: {"capital": Decimal(0), "productos": 0})
    fantasmas: dict = defaultdict(list)
    for m in metricas:
        disp = float(m["disponible"] or 0)
        capital = m["capital"] or Decimal(0)
        if m["tipo_ubicacion"] != "deposito" and C.posible_stock_fantasma(disp, float(m["vpd"] or 0), m["dias_sin_venta"] or 0):
            fantasmas[m["ubicacion_id"]].append(m)
        if disp > 0 and (m["dias_sin_venta"] or 0) >= 90 and capital > 0:
            muertos[m["ubicacion_id"]]["capital"] += capital
            muertos[m["ubicacion_id"]]["productos"] += 1
            muertos[m["ubicacion_id"]]["ubicacion"] = m["ubicacion"]
    for uid, ms in fantasmas.items():
        capital = sum((m["capital"] or Decimal(0) for m in ms), Decimal(0))
        nombres = ", ".join(m["nombre"] for m in sorted(ms, key=lambda m: -(m["capital"] or 0))[:3])
        alertas.append(_nueva("stock_fantasma", "normal", f"{len(ms)} producto(s) con posible stock fantasma en {ms[0]['ubicacion']}",
                              f"El sistema dice que hay stock pero no se venden hace días, algo muy raro con su ritmo normal ({nombres}"
                              f"{'…' if len(ms) > 3 else ''}). Pueden no estar en góndola, estar mal ubicados o no existir. Ya están en el recuento de hoy.",
                              capital, "en_riesgo", {"etiqueta": "Contar ahora", "tipo": "ir", "destino": "/comprar/#recuento"},
                              f"fantasma:{uid}", uid, None, hoy + timedelta(days=1), datos={"productos": [m["producto_id"] for m in ms]}))
    for uid, d in muertos.items():
        if d["capital"] >= minimo:
            alertas.append(_nueva("stock_muerto", "preventiva", f"{d['productos']} productos sin ventas hace más de 90 días en {d['ubicacion']}",
                                  f"Tienen {pesos(d['capital'])} parados. Conviene liquidarlos, cambiarlos con el proveedor o sacarlos del surtido.",
                                  d["capital"], "en_riesgo", {"etiqueta": "Ver productos", "tipo": "ir", "destino": "/comprar/?semaforo=gris"},
                                  f"muerto:{uid}", uid, None, hoy + timedelta(days=7)))
    sobre = defaultdict(lambda: {"capital": Decimal(0), "productos": 0})
    for m in metricas:
        if m["semaforo"] == "gris" and m["tipo_ubicacion"] != "deposito" and m["dias_stock"] is not None and float(m["dias_stock"]) > 60 and m["costo"]:
            exceso = Decimal(str(max(0.0, float(m["disponible"] or 0) - 30 * float(m["pronostico_diario"] or 0)))) * m["costo"]
            sobre[m["ubicacion_id"]]["capital"] += exceso
            sobre[m["ubicacion_id"]]["productos"] += 1
            sobre[m["ubicacion_id"]]["ubicacion"] = m["ubicacion"]
    for uid, d in sobre.items():
        if d["capital"] >= minimo * 10:
            alertas.append(_nueva("sobrestock", "preventiva", f"{pesos(d['capital'])} de más en {d['productos']} productos de {d['ubicacion']}",
                                  "Tienen más de 60 días de venta. Lo que excede 30 días es plata que podría estar en otra cosa: dejá de comprarlos "
                                  "y evaluá transferirlos a otra sucursal.",
                                  d["capital"], "recuperable", {"etiqueta": "Ver sobrestock", "tipo": "ir", "destino": "/comprar/?semaforo=gris"},
                                  f"sobrestock:{uid}", uid, None, hoy + timedelta(days=7)))

    # --- vencimientos: un aviso por sucursal con el total, y aparte los casos grandes
    por_sucursal = defaultdict(list)
    grandes = defaultdict(list)
    for m in sorted(metricas, key=lambda m: -(m["riesgo_vencimiento"] or 0)):
        if (m["riesgo_vencimiento"] or 0) >= minimo * 10 and len(grandes[m["ubicacion_id"]]) < 5:   # los 5 más grandes de cada sucursal
            grandes[m["ubicacion_id"]].append(m["producto_id"])
    for m in metricas:
        riesgo = m["riesgo_vencimiento"] or Decimal(0)
        if riesgo <= 0:
            continue
        if m["producto_id"] in grandes[m["ubicacion_id"]]:
            alertas.append(_nueva("vencimiento", "urgente", f"{m['nombre']}: {pesos(riesgo)} que vencen sin venderse en {m['ubicacion']}",
                                  "Con el ritmo de venta actual no llega a venderse antes de vencer. Si otra sucursal lo vende, hay una transferencia "
                                  "de rescate sugerida; si no, conviene ofertarlo ya.",
                                  riesgo, "en_riesgo", {"etiqueta": "Ver transferencias", "tipo": "ir", "destino": "/transferencias/#tr"},
                                  f"vence:{m['producto_id']}:{m['ubicacion_id']}", m["ubicacion_id"], m["producto_id"], hoy + timedelta(days=2)))
        else:
            por_sucursal[m["ubicacion_id"]].append(m)
    for uid, ms in por_sucursal.items():
        total = sum((m["riesgo_vencimiento"] for m in ms), Decimal(0))
        if total >= minimo:
            alertas.append(_nueva("vencimiento", "normal", f"{len(ms)} productos con mercadería que vence sin venderse en {ms[0]['ubicacion']}",
                                  f"En total {pesos(total)} a costo. Revisá los lotes más próximos y ofertalos o transferilos antes de que venzan.",
                                  total, "en_riesgo", {"etiqueta": "Ver lotes en riesgo", "tipo": "ir", "destino": "/transferencias/#tr"},
                                  f"vence:grupo:{uid}", uid, None, hoy + timedelta(days=3), datos={"productos": [m["producto_id"] for m in ms]}))

    # --- faltante en góndola (hoy: horas abiertas sin ventas de un producto que vende seguido)
    alertas.extend(_gondola(conn, metricas, hoy, ahora, minimo))

    # --- documentos: transferencias y OC para aprobar, OC escaladas
    for t in db.filas(conn, """SELECT t.id, t.numero, t.valor, t.motivo, t.origen_id, t.destino_id, o.nombre origen, d.nombre destino,
                                      (SELECT count(*) FROM transferencias_lineas l WHERE l.transferencia_id = t.id) lineas
                               FROM transferencias t JOIN ubicaciones o ON o.id = t.origen_id JOIN ubicaciones d ON d.id = t.destino_id
                               WHERE t.estado = 'sugerida'"""):
        rescate = t["motivo"] == "rescate_vencimiento"
        alertas.append(_nueva("transferencia", "normal", f"Transferir {t['lineas']} producto(s) de {t['origen']} a {t['destino']}"
                              + (" (rescate de vencimiento)" if rescate else ""),
                              f"{'Evita que venzan' if rescate else 'En vez de comprar, usás lo que sobra en ' + t['origen']}: {pesos(t['valor'])} a costo.",
                              t["valor"], "recuperable", {"etiqueta": "Revisar y aprobar", "tipo": "ir", "destino": f"/transferencias/#tr-{t['id']}"},
                              f"transferencia:{t['id']}", t["destino_id"], None, hoy + timedelta(days=1)))
    for o in db.filas(conn, """SELECT o.id, o.numero, o.total, o.estado, o.escalada_at, o.ubicacion_id, pr.razon_social, coalesce(u.nombre, 'consolidada') ubicacion
                               FROM ordenes_compra o JOIN proveedores pr ON pr.id = o.proveedor_id LEFT JOIN ubicaciones u ON u.id = o.ubicacion_id
                               WHERE o.estado IN ('sugerida', 'borrador')"""):
        if o["escalada_at"]:
            alertas.append(_nueva("oc_escalada", "urgente", f"Hoy pasa {o['razon_social']} y la {o['numero']} no está aprobada",
                                  f"Orden por {pesos(o['total'])} para {o['ubicacion']}. Si no se aprueba hoy, se pierde la visita y pueden faltar productos.",
                                  o["total"], "en_riesgo", {"etiqueta": "Aprobar ahora", "tipo": "ir", "destino": f"/transferencias/#oc-{o['id']}"},
                                  f"oc_escalada:{o['id']}", o["ubicacion_id"], None, hoy))
        else:
            alertas.append(_nueva("orden_compra", "normal", f"{o['numero']} a {o['razon_social']} para aprobar",
                                  f"Orden sugerida por {pesos(o['total'])} para {o['ubicacion']}.", o["total"], "en_riesgo",
                                  {"etiqueta": "Revisar y aprobar", "tipo": "ir", "destino": f"/transferencias/#oc-{o['id']}"},
                                  f"oc:{o['id']}", o["ubicacion_id"], None, hoy + timedelta(days=1)))

    for o in db.filas(conn, """SELECT o.id, o.numero, o.total, o.aprobacion, o.ubicacion_id, pr.razon_social, coalesce(u.nombre, 'consolidada') ubicacion
                               FROM ordenes_compra o JOIN proveedores pr ON pr.id = o.proveedor_id LEFT JOIN ubicaciones u ON u.id = o.ubicacion_id
                               WHERE o.estado = 'aprobada'"""):
        alertas.append(_nueva("orden_compra", "normal", f"{o['numero']} a {o['razon_social']} está aprobada: falta enviarla",
                              f"Orden por {pesos(o['total'])} para {o['ubicacion']}"
                              + (", aprobada automáticamente por estar bajo el límite" if o["aprobacion"] == "automatica" else "")
                              + ". El envío al proveedor siempre lo confirma una persona.",
                              o["total"], "en_riesgo", {"etiqueta": "Revisar y enviar", "tipo": "ir", "destino": f"/transferencias/#oc-{o['id']}"},
                              f"oc_enviar:{o['id']}", o["ubicacion_id"], None, hoy + timedelta(days=1)))
    for t in db.filas(conn, """SELECT t.id, t.valor, o.nombre origen, d.nombre destino, t.origen_id FROM transferencias t
                               JOIN ubicaciones o ON o.id = t.origen_id JOIN ubicaciones d ON d.id = t.destino_id WHERE t.estado = 'aprobada'"""):
        alertas.append(_nueva("transferencia", "normal", f"Preparar y enviar la transferencia de {t['origen']} a {t['destino']}",
                              f"Está aprobada ({pesos(t['valor'])} a costo). Al marcarla como enviada se descuenta de {t['origen']}.",
                              t["valor"], "recuperable", {"etiqueta": "Ver transferencia", "tipo": "ir", "destino": f"/transferencias/#tr-{t['id']}"},
                              f"transferencia_enviar:{t['id']}", t["origen_id"], None, hoy + timedelta(days=1)))

    # --- precios: aumentos de proveedor y margen erosionado
    for l in db.filas(conn, """SELECT lp.id, lp.vigencia_desde, pr.razon_social, count(*) productos,
                                      sum((l.costo - l.costo_anterior) * coalesce((SELECT sum(m.pronostico_diario) FROM metricas_producto_actual m
                                          WHERE m.producto_id = l.producto_id), 0) * 30) extra_mensual,
                                      avg(l.costo / nullif(l.costo_anterior, 0) - 1) aumento
                               FROM listas_precios_proveedor lp JOIN listas_precios_proveedor_lineas l ON l.lista_id = lp.id
                               JOIN proveedores pr ON pr.id = lp.proveedor_id
                               WHERE lp.vigencia_desde > %s AND l.costo_anterior > 0 GROUP BY 1, 2, 3""", (hoy - timedelta(days=10),)):
        if l["aumento"] and l["aumento"] > Decimal("0.03"):
            alertas.append(_nueva("aumento_proveedor", "urgente" if l["aumento"] > Decimal("0.08") else "normal",
                                  f"{l['razon_social']} aumentó {num(l['aumento'] * 100)} % en {l['productos']} productos",
                                  f"Lista vigente desde el {l['vigencia_desde'].strftime('%d/%m')}. Si no remarcás, son {pesos(l['extra_mensual'])} "
                                  "de costo extra por mes que salen de tu margen.",
                                  l["extra_mensual"] or 0, "recuperable", {"etiqueta": "Remarcar", "tipo": "ir", "destino": "/precios/?filtro=aumentos"},
                                  f"aumento:{l['id']}", None, None, hoy + timedelta(days=3)))
    erosion = db.fila(conn, """SELECT count(*) n, coalesce(sum(greatest(0, pp.costo - x.precio * (1 - coalesce(mo.margen, 0.30))) *
                                      coalesce((SELECT sum(m.pronostico_diario) FROM metricas_producto_actual m WHERE m.producto_id = p.id), 0)), 0) perdida
                               FROM productos p JOIN producto_proveedores pp ON pp.producto_id = p.id AND pp.principal
                               JOIN precios x ON x.producto_id = p.id AND x.canal_id IS NULL AND x.ubicacion_id IS NULL AND x.hasta IS NULL
                               LEFT JOIN categorias c ON c.id = p.categoria_id
                               LEFT JOIN margenes_objetivo mo ON mo.categoria_id = coalesce(c.padre_id, c.id) AND mo.canal_id IS NULL
                               WHERE pp.costo IS NOT NULL AND (x.precio - pp.costo) / x.precio < coalesce(mo.margen, 0.30) - 0.02""")
    if erosion and erosion["n"] and erosion["perdida"] * 30 >= minimo:
        alertas.append(_nueva("margen", "normal", f"{erosion['n']} productos se venden por debajo del margen objetivo",
                              f"Pierden {pesos(erosion['perdida'])} de margen por día ({pesos(erosion['perdida'] * 30)} por mes) respecto del objetivo.",
                              erosion["perdida"] * 30, "recuperable", {"etiqueta": "Ver remarcación", "tipo": "ir", "destino": "/precios/?filtro=erosionados"},
                              "margen:general", None, None, hoy + timedelta(days=3)))

    # --- control de caja (últimos 30 días) y diferencias de inventario
    alertas.extend(_caja(conn, hoy))
    for d in db.filas(conn, """SELECT r.ubicacion_id, u.nombre, count(*) n, -sum(l.diferencia_pesos) monto FROM recuentos_lineas l
                               JOIN recuentos r ON r.id = l.recuento_id JOIN ubicaciones u ON u.id = r.ubicacion_id
                               WHERE r.fecha > %s AND l.diferencia < 0 GROUP BY 1, 2""", (hoy - timedelta(days=7),)):
        if d["monto"] and d["monto"] >= minimo:
            alertas.append(_nueva("inventario", "normal", f"Faltantes en recuentos de {d['nombre']}: {pesos(d['monto'])}",
                                  f"{d['n']} productos contados con menos stock que el sistema en la última semana.", d["monto"], "perdida",
                                  {"etiqueta": "Ver control", "tipo": "ir", "destino": "/caja/"}, f"inventario:{d['ubicacion_id']}:{hoy.isocalendar()[1]}",
                                  d["ubicacion_id"], None, hoy + timedelta(days=3)))

    # --- caída de productos A
    for c in db.filas(conn, """SELECT a.producto_id, p.nombre, sum(a.ganancia) FILTER (WHERE a.fecha > %(h14)s) g14,
                                      sum(a.ganancia) FILTER (WHERE a.fecha <= %(h14)s) g_prev,
                                      count(DISTINCT a.fecha) FILTER (WHERE a.fecha > %(h14)s) d14
                               FROM agg_producto_ubicacion_dia a JOIN productos p ON p.id = a.producto_id
                               WHERE p.clase_abc = 'A' AND a.fecha > %(h42)s AND a.fecha < %(hoy)s GROUP BY 1, 2""",
                      {"h14": hoy - timedelta(days=15), "h42": hoy - timedelta(days=43), "hoy": hoy}):
        if c["g_prev"] and c["g14"] is not None and c["g_prev"] > 0:
            diario_prev, diario = c["g_prev"] / 28, c["g14"] / 14
            if diario < diario_prev * Decimal("0.6"):
                perdida = (diario_prev - diario) * 30
                if perdida >= minimo:
                    alertas.append(_nueva("caida_a", "normal", f"{c['nombre']} (clase A) cayó {num((1 - diario / diario_prev) * 100, 0)} % en dos semanas",
                                          f"Deja {pesos(diario)} de ganancia por día contra {pesos(diario_prev)} antes. Revisá precio, stock y competencia.",
                                          perdida, "perdida", {"etiqueta": "Ver producto", "tipo": "ir", "destino": f"/comprar/?producto={c['producto_id']}"},
                                          f"caida_a:{c['producto_id']}", None, c["producto_id"], hoy + timedelta(days=3)))
    return _guardar(conn, org_id, alertas, hoy)


def _gondola(conn, metricas, hoy: date, ahora: datetime, minimo: Decimal) -> list[dict]:
    """Horas del día ya transcurridas sin ventas de un producto que vende seguido: si la probabilidad (Poisson) de que eso pase
    con su ritmo normal es menor al 5 %, probablemente no está en góndola."""
    if ahora.date() != hoy or ahora.hour < 10:
        return []
    perfil = defaultdict(dict)
    for f in db.filas(conn, """SELECT ubicacion_id, hora, sum(tickets)::numeric / nullif(sum(sum(tickets)) OVER (PARTITION BY ubicacion_id), 0) parte
                               FROM agg_ubicacion_hora WHERE fecha > %s AND fecha < %s AND extract(isodow FROM fecha) = %s GROUP BY 1, 2""",
                      (hoy - timedelta(days=36), hoy, hoy.isoweekday())):
        perfil[f["ubicacion_id"]][f["hora"]] = float(f["parte"] or 0)
    vendidos_hoy = {(f["producto_id"], f["ubicacion_id"]) for f in db.filas(
        conn, "SELECT DISTINCT producto_id, ubicacion_id FROM tickets_lineas WHERE fecha = %s AND cantidad > 0", (hoy,))}
    resultado = []
    for m in metricas:
        if m["tipo_ubicacion"] == "deposito" or (m["producto_id"], m["ubicacion_id"]) in vendidos_hoy or float(m["disponible"] or 0) <= 0:
            continue
        transcurrido = sum(v for h, v in perfil.get(m["ubicacion_id"], {}).items() if h < ahora.hour)
        esperado = float(m["pronostico_diario"] or 0) * transcurrido
        if esperado < 3 or not C.posible_faltante_gondola(esperado):
            continue
        resto = float(m["pronostico_diario"] or 0) * max(0.0, 1 - transcurrido)
        impacto = Decimal(str(resto)) * (m["precio"] or Decimal(0))
        if impacto < minimo / 2:
            continue
        resultado.append(_nueva("gondola", "urgente", f"{m['nombre']}: no se vendió nada hoy en {m['ubicacion']}",
                                f"Normalmente a esta hora ya se vendieron {num(esperado)} unidades; que no se venda ninguna tiene "
                                f"{num(C.prob_cero_ventas(esperado) * 100)} % de probabilidad. El sistema dice que hay {num(m['disponible'], 0)}: "
                                "revisá la góndola.", impacto, "en_riesgo", {"etiqueta": "Marcar para recuento", "tipo": "recuento",
                                                                             "datos": {"producto_id": m["producto_id"], "ubicacion_id": m["ubicacion_id"]}},
                                f"gondola:{m['producto_id']}:{m['ubicacion_id']}:{hoy}", m["ubicacion_id"], m["producto_id"], hoy))
    return resultado


def _caja(conn, hoy: date) -> list[dict]:
    filas = db.filas(conn, """SELECT t.ubicacion_id, u.nombre ubicacion, t.cajero, count(*) tickets,
                                     count(*) FILTER (WHERE t.estado='anulado') anul, coalesce(sum(t.total) FILTER (WHERE t.estado='anulado'), 0) monto
                              FROM tickets t JOIN ubicaciones u ON u.id = t.ubicacion_id
                              WHERE t.cajero IS NOT NULL AND t.fecha_hora > %s GROUP BY 1, 2, 3""", (hoy - timedelta(days=30),))
    grupos = defaultdict(list)
    for f in filas:
        f["tasa"] = f["anul"] / f["tickets"] * 100 if f["tickets"] else 0
        grupos[f["ubicacion_id"]].append(f)
    resultado = []
    for g in grupos.values():
        for f in g:
            otros = [float(x["tasa"]) for x in g if x is not f]
            z = C.z_atipico(float(f["tasa"]), otros)
            base = sum(x["anul"] for x in g if x is not f) / max(1, sum(x["tickets"] for x in g if x is not f))
            raro = C.prob_poisson_al_menos(int(f["anul"]), base * f["tickets"]) < 0.001      # que no sea azar
            if z is not None and z >= 2 and otros and float(f["tasa"]) > 1.5 * (sum(otros) / len(otros)) and raro:
                resultado.append(_nueva("caja", "urgente", f"{f['cajero']} anula mucho más que el resto en {f['ubicacion']}",
                                        f"{num(f['tasa'])} % de sus tickets anulados en 30 días contra {num(sum(otros) / len(otros))} % del resto "
                                        f"({pesos(f['monto'])}). Revisá esos tickets.", f["monto"], "en_riesgo",
                                        {"etiqueta": "Ver detalle", "tipo": "ir", "destino": "/caja/"},
                                        f"caja:{f['ubicacion_id']}:{f['cajero']}", f["ubicacion_id"], None, hoy + timedelta(days=2)))
    return resultado


def _guardar(conn, org_id: int, alertas: list[dict], hoy: date) -> dict:
    abiertas = {a["clave_dedupe"]: a for a in db.filas(conn, "SELECT * FROM alertas WHERE estado IN ('nueva', 'vista', 'escalada')")}
    claves = set()
    nuevas = actualizadas = 0
    with conn.cursor() as cur:
        for a in alertas:
            if a["clave"] in claves:
                continue
            claves.add(a["clave"])
            previa = abiertas.get(a["clave"])
            if previa:
                cur.execute("UPDATE alertas SET titulo=%s, explicacion=%s, impacto=%s, prioridad=%s, accion=%s, vence=%s, datos=%s, updated_at=now() WHERE id=%s",
                            (a["titulo"], a["explicacion"], a["impacto"], a["prioridad"], json.dumps(a["accion"]), a["vence"],
                             json.dumps(a["datos"], default=str), previa["id"]))
                actualizadas += 1
            else:
                cur.execute("INSERT INTO alertas (org_id, tipo, prioridad, ubicacion_id, producto_id, titulo, explicacion, impacto, tipo_impacto, accion, "
                            "vence, destinatarios, clave_dedupe, grupo, datos) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (org_id, a["tipo"], a["prioridad"], a["ubicacion_id"], a["producto_id"], a["titulo"], a["explicacion"], a["impacto"],
                             a["tipo_impacto"], json.dumps(a["accion"]), a["vence"], DESTINOS.get(a["tipo"], ["dueno"]), a["clave"], a["grupo"],
                             json.dumps(a["datos"], default=str)))
                nuevas += 1
        # La condición desapareció: se resuelve sola.
        resueltas = [a["id"] for c, a in abiertas.items() if c not in claves]
        if resueltas:
            cur.execute("UPDATE alertas SET estado='resuelta', datos = datos || '{\"automatica\": true}', updated_at=now() WHERE id = ANY(%s)", (resueltas,))
        # Vencida sin resolver: se escala al dueño.
        cur.execute("""UPDATE alertas SET estado='escalada', prioridad='urgente', destinatarios = array(SELECT DISTINCT unnest(destinatarios || '{dueno}')),
                       updated_at=now() WHERE estado IN ('nueva', 'vista') AND vence < %s""", (hoy,))
        escaladas = cur.rowcount
    return {"nuevas": nuevas, "actualizadas": actualizadas, "resueltas_solas": len(resueltas), "escaladas": escaladas}
