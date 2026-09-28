"""Reglas de reposición, transferencias y órdenes de compra (sección 7). Corre después de cada cálculo de métricas.

Lógica de decisión, por producto × sucursal que llegó a su punto de pedido (semáforo rojo o amarillo, o stock ≤ punto de
pedido configurado):
1. Modelo de abastecimiento: el del proveedor, si no el de la categoría, si no el de la sucursal, si no el de la empresa.
2. Si el modelo permite transferencias (mixto o centralizado): se buscan orígenes con excedente (depósito, cobertura mayor
   al umbral o stock sobre el máximo), respetando el mínimo a conservar en origen y la cantidad mínima de traslado.
   Prioridad: el origen con lotes que vencen antes (rescate), después el de más excedente, después el de la misma localidad.
3. Excedente suficiente → transferencia. Parcial → transferencia por lo disponible + OC por la diferencia.
   Sin excedente o modelo descentralizado → OC.
4. Centralizado: las sucursales nunca generan OC; lo que falta se suma al pedido del depósito central.
5. Se agrupa por proveedor (y sucursal, o consolidado si así se configuró). Si una OC no llega al pedido mínimo, se
   adelantan productos del mismo proveedor que se van a necesitar pronto, mostrando el impacto.
6. Se valida contra el presupuesto de compra del mes.
7. Según el nivel de automatización: solo aviso, borrador o aprobada automáticamente si está bajo el límite (y dentro
   del presupuesto). El envío al proveedor lo confirma SIEMPRE una persona (CLAUDE.md, regla 4).
8. Escalamiento: una OC sin aprobar el día de visita del proveedor se escala al dueño.
9. Rescate de vencimientos: si un lote no se vende a tiempo donde está pero sí en otra sucursal, transferencia preventiva.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from . import calculos as C
from . import db

UMBRAL_EXCEDENTE_DIAS = C.UMBRAL_SOBRESTOCK_DIAS


def _parametro(conn, clave: str, defecto):
    f = db.fila(conn, "SELECT valor FROM parametros WHERE clave=%s", (clave,))
    return f["valor"] if f else defecto


def modelo_para(conn_cache: dict, org: dict, ubicacion_id: int, categoria_ids: tuple, proveedor_id: int | None) -> str:
    cfg = conn_cache["config_abastecimiento"]
    if proveedor_id and ("proveedor", proveedor_id) in cfg:
        return cfg[("proveedor", proveedor_id)]
    for c in categoria_ids:
        if c and ("categoria", c) in cfg:
            return cfg[("categoria", c)]
    if ("ubicacion", ubicacion_id) in cfg:
        return cfg[("ubicacion", ubicacion_id)]
    return org["modelo_abastecimiento"]


def _numero(conn, prefijo: str, tabla: str) -> str:
    n = db.fila(conn, f"SELECT count(*) + 1 AS n FROM {tabla}")["n"]
    while db.fila(conn, f"SELECT 1 FROM {tabla} WHERE numero=%s", (f"{prefijo}-{n:06d}",)):
        n += 1
    return f"{prefijo}-{n:06d}"


def generar(org_id: int, hoy: date) -> dict:
    from .motor import contexto_sistema
    ctx = contexto_sistema(org_id)
    with db.transaccion(ctx) as conn:
        return _generar(conn, org_id, hoy)


def _generar(conn, org_id: int, hoy: date) -> dict:
    org = db.fila(conn, "SELECT * FROM organizaciones WHERE id=%s", (org_id,))
    cache = {"config_abastecimiento": {(f["nivel"], f["referencia_id"]): f["modelo"] for f in
                                       db.filas(conn, "SELECT nivel, referencia_id, modelo FROM config_abastecimiento")}}
    automat = {f["tipo_documento"]: f for f in db.filas(conn, "SELECT * FROM config_automatizacion")}
    consolidada = bool(_parametro(conn, "compra_consolidada", False))
    ubic = {f["id"]: f for f in db.filas(conn, "SELECT * FROM ubicaciones WHERE activa")}
    deposito = next((u for u in ubic.values() if u["tipo"] == "deposito"), None)

    # Se regeneran las sugerencias automáticas (lo aprobado, en borrador editado o enviado no se toca).
    with conn.cursor() as cur:
        cur.execute("DELETE FROM ordenes_compra WHERE estado='sugerida' AND origen='sugerida'")
        cur.execute("DELETE FROM transferencias WHERE estado='sugerida' AND motivo IN ('reposicion', 'rescate_vencimiento')")

    metricas = db.filas(conn, """
        SELECT m.*, p.nombre, p.categoria_id, c.padre_id, p.perecedero, pp.costo, pp.unidades_por_bulto, pp.multiplo_compra,
               pr.razon_social, pr.pedido_minimo_monto, pr.pedido_minimo_bultos, pr.dias_visita, pr.demora_entrega_dias
        FROM metricas_producto_actual m JOIN productos p ON p.id = m.producto_id LEFT JOIN categorias c ON c.id = p.categoria_id
        LEFT JOIN producto_proveedores pp ON pp.producto_id = m.producto_id AND pp.proveedor_id = m.proveedor_id
        LEFT JOIN proveedores pr ON pr.id = m.proveedor_id""")
    por_clave = {(m["producto_id"], m["ubicacion_id"]): m for m in metricas}
    reglas = db.filas(conn, "SELECT * FROM reglas_reposicion")
    lotes = defaultdict(list)
    for f in db.filas(conn, "SELECT producto_id, ubicacion_id, lote, cantidad, vencimiento FROM stock_lotes WHERE cantidad > 0 AND vencimiento IS NOT NULL"):
        lotes[(f["producto_id"], f["ubicacion_id"])].append(f)
    # Lo que ya está pedido y sin recibir (OC y transferencias vivas) no se vuelve a sugerir.
    en_curso = defaultdict(float)
    for f in db.filas(conn, """SELECT l.producto_id, coalesce(l.ubicacion_id, o.ubicacion_id) u, sum(l.cantidad - l.cantidad_recibida) c
                               FROM ordenes_compra_lineas l JOIN ordenes_compra o ON o.id = l.orden_id
                               WHERE o.estado IN ('borrador', 'aprobada') GROUP BY 1, 2"""):
        en_curso[(f["producto_id"], f["u"])] += float(f["c"] or 0)
    for f in db.filas(conn, """SELECT l.producto_id, t.destino_id u, sum(l.cantidad) c FROM transferencias_lineas l
                               JOIN transferencias t ON t.id = l.transferencia_id WHERE t.estado IN ('aprobada') GROUP BY 1, 2"""):
        en_curso[(f["producto_id"], f["u"])] += float(f["c"] or 0)

    from .motor import _regla

    def pron_diario(m) -> float:
        return float(m["pronostico_diario"] or 0)

    def transferible(m_origen, pid) -> float:
        """Cuánto puede ceder un origen sin quedar por debajo de lo que necesita: el mínimo a conservar (días) o lo que
        necesita para su propio horizonte más su stock de seguridad."""
        u = ubic[m_origen["ubicacion_id"]]
        disp = float(m_origen["disponible"] or 0)
        if disp <= 0:
            return 0.0
        regla = _regla(reglas, pid, m_origen["categoria_id"], m_origen["padre_id"], m_origen["ubicacion_id"])
        minimo_dias = float(regla["minimo_en_origen_dias"]) if regla else 14.0
        reserva = max(minimo_dias * pron_diario(m_origen),
                      pron_diario(m_origen) * (m_origen["horizonte_dias"] or 0) + float(m_origen["stock_seguridad"] or 0))
        excedente = u["tipo"] == "deposito" or (m_origen["dias_stock"] is not None and float(m_origen["dias_stock"]) > UMBRAL_EXCEDENTE_DIAS)
        if regla and regla["stock_maximo"] is not None and disp > float(regla["stock_maximo"]):
            excedente = True
        if not excedente:
            return 0.0
        return max(0.0, disp - reserva - cedido.get((pid, m_origen["ubicacion_id"]), 0.0))

    cedido: dict = defaultdict(float)
    transferencias: dict = defaultdict(list)       # (origen, destino, motivo) → líneas
    compras: dict = defaultdict(list)              # (proveedor, ubicación de compra) → líneas
    necesidades_deposito: dict = defaultdict(float)
    resumen = defaultdict(int)

    necesitan = []
    for m in metricas:
        u = ubic.get(m["ubicacion_id"])
        if not u or u["tipo"] == "deposito":
            continue
        regla = _regla(reglas, m["producto_id"], m["categoria_id"], m["padre_id"], m["ubicacion_id"])
        punto = regla and regla["punto_pedido"] is not None and float(m["disponible"] or 0) <= float(regla["punto_pedido"])
        if (m["semaforo"] in ("rojo", "amarillo") or punto) and float(m["cantidad_sugerida"] or 0) > 0:
            necesitan.append(m)
    necesitan.sort(key=lambda m: (m["semaforo"] != "rojo", m["fecha_quiebre"] or date.max))

    for m in necesitan:
        pid, uid = m["producto_id"], m["ubicacion_id"]
        falta = max(0.0, math.ceil(float(m["explicacion"].get("necesidad") or m["cantidad_sugerida"])) - en_curso.get((pid, uid), 0.0))
        if falta <= 0:
            continue
        modelo = modelo_para(cache, org, uid, (m["categoria_id"], m["padre_id"]), m["proveedor_id"])
        explic = {"modelo": modelo, "necesidad": falta, "semaforo": m["semaforo"], "quiebre": str(m["fecha_quiebre"]) if m["fecha_quiebre"] else None}
        if modelo in ("mixto", "centralizado"):
            regla = _regla(reglas, pid, m["categoria_id"], m["padre_id"], uid)
            permitidos = set(regla["origenes_permitidos"] or []) if regla else set()
            minimo_traslado = float(regla["cantidad_minima_traslado"]) if regla else 1.0
            origenes = []
            for oid, u in ubic.items():
                if oid == uid or (permitidos and oid not in permitidos):
                    continue
                mo = por_clave.get((pid, oid))
                if not mo:
                    continue
                cant = transferible(mo, pid)
                if cant >= minimo_traslado:
                    venc = min((l["vencimiento"] for l in lotes.get((pid, oid), [])), default=date.max)
                    misma = (u.get("localidad") or "") == (ubic[uid].get("localidad") or "")
                    origenes.append((venc, -cant, not misma, oid, cant))
            origenes.sort()
            for venc, _, _, oid, cant in origenes:
                if falta <= 0:
                    break
                q = min(falta, math.floor(cant))
                if q < minimo_traslado:
                    continue
                transferencias[(oid, uid, "reposicion")].append({"producto_id": pid, "cantidad": q, "costo": m["costo"],
                                                                "explicacion": {**explic, "origen_excedente": cant,
                                                                                "vence_en_origen": None if venc == date.max else str(venc)}})
                cedido[(pid, oid)] += q
                falta -= q
                resumen["unidades_transferidas"] += q
        if falta <= 0:
            continue
        if modelo == "centralizado" and deposito:
            necesidades_deposito[pid] += falta          # la sucursal no compra: se suma al pedido del depósito
            resumen["derivadas_al_deposito"] += 1
            continue
        if not m["proveedor_id"]:
            resumen["sin_proveedor"] += 1
            continue
        multiplo = max(1, m["unidades_por_bulto"] or 1) * max(1, m["multiplo_compra"] or 1)
        q = math.ceil(falta / multiplo) * multiplo
        destino = None if consolidada else uid
        compras[(m["proveedor_id"], destino)].append({"producto_id": pid, "ubicacion_id": uid, "cantidad": q, "cantidad_sugerida": q,
                                                     "costo": m["costo"], "bultos": q / (m["unidades_por_bulto"] or 1),
                                                     "explicacion": explic, "m": m})

    # Centralizado: el depósito compra para todas las sucursales (lo que necesitan menos lo que tiene libre).
    if deposito:
        for pid, falta in necesidades_deposito.items():
            md = por_clave.get((pid, deposito["id"]))
            ms = next((m for m in metricas if m["producto_id"] == pid and m["proveedor_id"]), None)
            if not ms:
                continue
            libre = max(0.0, float(md["disponible"] or 0) - cedido.get((pid, deposito["id"]), 0.0)) if md else 0.0
            q_neto = falta - libre
            if q_neto <= 0:
                continue
            multiplo = max(1, ms["unidades_por_bulto"] or 1) * max(1, ms["multiplo_compra"] or 1)
            q = math.ceil(q_neto / multiplo) * multiplo
            compras[(ms["proveedor_id"], deposito["id"])].append({
                "producto_id": pid, "ubicacion_id": deposito["id"], "cantidad": q, "cantidad_sugerida": q, "costo": ms["costo"],
                "bultos": q / (ms["unidades_por_bulto"] or 1), "explicacion": {"modelo": "centralizado", "necesidad_sucursales": falta,
                                                                               "libre_en_deposito": libre}, "m": ms})

    # Rescate de vencimientos: lotes que no se venden a tiempo donde están, pero sí en otra sucursal.
    for (pid, oid), ls in lotes.items():
        mo = por_clave.get((pid, oid))
        if not mo:
            continue
        pron_o = mo["explicacion"].get("pronostico_14d") or []
        pron_o = pron_o + [pron_diario(mo)] * 120
        for l in C.unidades_que_no_llegan(ls, pron_o, hoy):
            if l["no_llegan"] < 1 or l["dias"] <= 1:
                continue
            mejor = None
            for did, u in ubic.items():
                if did == oid or u["tipo"] == "deposito":
                    continue
                md = por_clave.get((pid, did))
                if not md:
                    continue
                demanda = pron_diario(md) * max(0, l["dias"] - 1) - max(0.0, float(md["disponible"] or 0))
                if demanda >= 1 and (mejor is None or demanda > mejor[1]):
                    mejor = (did, demanda)
            if mejor:
                q = math.floor(min(l["no_llegan"], mejor[1]))
                if q >= 1:
                    transferencias[(oid, mejor[0], "rescate_vencimiento")].append({
                        "producto_id": pid, "cantidad": q, "costo": mo["costo"], "lote": l["lote"],
                        "explicacion": {"lote": l["lote"], "vence": str(l["vencimiento"]), "no_se_venden_en_origen": l["no_llegan"],
                                        "demanda_en_destino": round(mejor[1], 1)}})
                    resumen["rescates"] += 1

    # ---- presupuesto del mes
    mes = hoy.replace(day=1)
    presupuesto = db.fila(conn, "SELECT sum(monto) m FROM presupuestos_compra WHERE mes=%s AND ubicacion_id IS NULL", (mes,))["m"]
    comprometido = db.fila(conn, "SELECT coalesce(sum(total), 0) t FROM ordenes_compra WHERE estado IN ('aprobada','enviada','recibida_parcial','recibida') "
                                 "AND created_at >= %s", (mes,))["t"]
    disponible_presupuesto = (presupuesto - comprometido) if presupuesto is not None else None

    # ---- crear transferencias
    cfg_t = automat.get("transferencia", {"nivel": "borrador", "monto_limite": 0})
    for (oid, did, motivo), lineas in transferencias.items():
        valor = sum(Decimal(str(l["cantidad"])) * (l["costo"] or 0) for l in lineas).quantize(Decimal("0.01"))
        estado, aprobacion = _estado_inicial(cfg_t, valor, None)
        if estado == "borrador":
            estado = "sugerida"          # las transferencias no tienen borrador: sugerida → aprobada → enviada → recibida
        t = db.fila(conn, "INSERT INTO transferencias (org_id, numero, origen_id, destino_id, estado, motivo, valor, aprobacion, aprobada_at, explicacion) "
                          "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (org_id, _numero(conn, "TR", "transferencias"), oid, did, estado, motivo, valor, aprobacion,
                     None, json.dumps({"lineas": len(lineas), "valor": str(valor)})))
        with conn.cursor() as cur:
            if estado == "aprobada":
                cur.execute("UPDATE transferencias SET aprobada_at=now() WHERE id=%s", (t["id"],))
            for l in lineas:
                cur.execute("INSERT INTO transferencias_lineas (org_id, transferencia_id, producto_id, cantidad, lote, costo) VALUES (%s,%s,%s,%s,%s,%s)",
                            (org_id, t["id"], l["producto_id"], l["cantidad"], l.get("lote"), l["costo"]))
        resumen["transferencias"] += 1

    # ---- crear órdenes de compra (con pedido mínimo, adelantos y presupuesto)
    cfg_oc = automat.get("orden_compra", {"nivel": "borrador", "monto_limite": 0})
    for (prov_id, destino), lineas in compras.items():
        m0 = lineas[0]["m"]
        minimo_monto = Decimal(m0["pedido_minimo_monto"] or 0)
        minimo_bultos = int(m0["pedido_minimo_bultos"] or 0)
        total = sum(Decimal(str(l["cantidad"])) * (l["costo"] or 0) for l in lineas)
        bultos = sum(l["bultos"] for l in lineas)
        adelantos = []
        if total < minimo_monto or bultos < minimo_bultos:
            ya = {(l["producto_id"], l["ubicacion_id"]) for l in lineas}
            candidatos = [m for m in metricas if m["proveedor_id"] == prov_id and (destino is None or m["ubicacion_id"] == destino)
                          and (m["producto_id"], m["ubicacion_id"]) not in ya and ubic[m["ubicacion_id"]]["tipo"] != "deposito"
                          and m["semaforo"] in ("amarillo", "verde") and m["costo"] is not None]
            candidatos.sort(key=lambda m: m["fecha_quiebre"] or date.max)
            for m in candidatos:
                if total >= minimo_monto and bultos >= minimo_bultos:
                    break
                multiplo = max(1, m["unidades_por_bulto"] or 1) * max(1, m["multiplo_compra"] or 1)
                base = float(m["cantidad_sugerida"] or 0) or float(m["pronostico_diario"] or 0) * (m["horizonte_dias"] or 7)
                q = max(multiplo, math.ceil(base / multiplo) * multiplo)
                costo_l = Decimal(str(q)) * m["costo"]
                dias_extra = q / float(m["pronostico_diario"]) if m["pronostico_diario"] else None
                adelantos.append({"producto_id": m["producto_id"], "ubicacion_id": m["ubicacion_id"], "cantidad": q, "cantidad_sugerida": q,
                                  "costo": m["costo"], "bultos": q / (m["unidades_por_bulto"] or 1), "adelantada": True,
                                  "explicacion": {"adelantada": True, "motivo": "completar el pedido mínimo", "inversion_extra": str(costo_l.quantize(Decimal('0.01'))),
                                                  "dias_de_cobertura_extra": None if dias_extra is None else round(dias_extra, 1),
                                                  "se_agotaria": str(m["fecha_quiebre"]) if m["fecha_quiebre"] else None}})
                total += costo_l
                bultos += q / (m["unidades_por_bulto"] or 1)
        lineas = lineas + adelantos
        total = total.quantize(Decimal("0.01"))
        explicacion = {"proveedor": m0["razon_social"], "pedido_minimo_monto": str(minimo_monto), "pedido_minimo_bultos": minimo_bultos,
                       "adelantos": len(adelantos), "inversion_adelantos": str(sum(Decimal(a["explicacion"]["inversion_extra"]) for a in adelantos)),
                       "cumple_minimo": total >= minimo_monto and bultos >= minimo_bultos,
                       "falta_para_minimo": str(max(Decimal(0), minimo_monto - total))}
        dentro = disponible_presupuesto is None or total <= disponible_presupuesto
        explicacion["presupuesto"] = {"disponible": None if disponible_presupuesto is None else str(disponible_presupuesto), "dentro": dentro}
        estado, aprobacion = _estado_inicial(cfg_oc, total, dentro)
        if not explicacion["cumple_minimo"] and estado == "aprobada":
            estado, aprobacion = "borrador", None       # no se aprueba sola si no llega al mínimo
        h = C.horizonte(hoy, m0["dias_visita"], m0["demora_entrega_dias"])
        oc = db.fila(conn, "INSERT INTO ordenes_compra (org_id, numero, proveedor_id, ubicacion_id, estado, origen, total, fecha_esperada, aprobacion, "
                           "explicacion) VALUES (%s,%s,%s,%s,%s,'sugerida',%s,%s,%s,%s) RETURNING id",
                     (org_id, _numero(conn, "OC", "ordenes_compra"), prov_id, destino, estado, total,
                      hoy + timedelta(days=h.llegada_proxima), aprobacion, json.dumps(explicacion)))
        with conn.cursor() as cur:
            if estado == "aprobada":
                cur.execute("UPDATE ordenes_compra SET aprobada_at=now() WHERE id=%s", (oc["id"],))
                if disponible_presupuesto is not None:
                    disponible_presupuesto -= total
            for l in lineas:
                cur.execute("INSERT INTO ordenes_compra_lineas (org_id, orden_id, producto_id, ubicacion_id, cantidad, cantidad_sugerida, bultos, "
                            "costo, adelantada, explicacion) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            (org_id, oc["id"], l["producto_id"], l["ubicacion_id"], l["cantidad"], l["cantidad_sugerida"], l["bultos"],
                             l["costo"], l.get("adelantada", False), json.dumps(l["explicacion"], default=str)))
        resumen["ordenes"] += 1
        resumen[f"ordenes_{estado}"] += 1

    resumen["escaladas"] = escalar(conn, hoy)
    resumen["aprendizaje"] = aprender(conn, org_id)
    return dict(resumen)


def _estado_inicial(cfg: dict, total: Decimal, dentro_presupuesto: bool | None) -> tuple[str, str | None]:
    """solo_aviso → sugerida · borrador → borrador · automatico_con_limite → aprobada si total ≤ límite (y presupuesto)."""
    nivel = cfg["nivel"]
    if nivel == "solo_aviso":
        return "sugerida", None
    if nivel == "automatico_con_limite" and total <= Decimal(cfg["monto_limite"]) and dentro_presupuesto is not False:
        return "aprobada", "automatica"
    return "borrador", None


def escalar(conn, hoy: date) -> int:
    """OC sugeridas o en borrador que no se aprobaron y hoy pasa el proveedor: se escalan al dueño."""
    n = 0
    for o in db.filas(conn, """SELECT o.id, pr.dias_visita FROM ordenes_compra o JOIN proveedores pr ON pr.id = o.proveedor_id
                               WHERE o.estado IN ('sugerida', 'borrador') AND o.escalada_at IS NULL"""):
        if o["dias_visita"] and hoy.weekday() in o["dias_visita"]:
            with conn.cursor() as cur:
                cur.execute("UPDATE ordenes_compra SET escalada_at=now() WHERE id=%s", (o["id"],))
            n += 1
    return n


def aprender(conn, org_id: int) -> int:
    """Control posterior: si en las últimas 3 OC aprobadas de un producto la persona corrigió la cantidad sugerida siempre en
    el mismo sentido (más de 20 %), se ajusta su stock de seguridad por el promedio de la corrección y se deja registro."""
    ajustes = 0
    filas = db.filas(conn, """SELECT l.producto_id, l.ubicacion_id, l.cantidad, l.cantidad_sugerida, o.aprobada_at
                              FROM ordenes_compra_lineas l JOIN ordenes_compra o ON o.id = l.orden_id
                              WHERE o.origen='sugerida' AND o.aprobacion='manual' AND o.aprobada_at IS NOT NULL AND l.cantidad_sugerida > 0
                              ORDER BY l.producto_id, l.ubicacion_id, o.aprobada_at DESC""")
    grupos = defaultdict(list)
    for f in filas:
        grupos[(f["producto_id"], f["ubicacion_id"])].append(f)
    for (pid, uid), fs in grupos.items():
        ult = fs[:3]
        if len(ult) < 3:
            continue
        cambios = [(float(f["cantidad"]) - float(f["cantidad_sugerida"])) / float(f["cantidad_sugerida"]) for f in ult]
        if all(c > 0.2 for c in cambios) or all(c < -0.2 for c in cambios):
            delta = sum(float(f["cantidad"]) - float(f["cantidad_sugerida"]) for f in ult) / 3
            m = db.fila(conn, "SELECT stock_seguridad FROM metricas_producto_actual WHERE producto_id=%s AND ubicacion_id=%s", (pid, uid))
            antes = float(m["stock_seguridad"]) if m else 0.0
            despues = max(0.0, antes + delta)
            regla = db.fila(conn, "SELECT id FROM reglas_reposicion WHERE producto_id=%s AND ubicacion_id=%s", (pid, uid))
            with conn.cursor() as cur:
                if regla:
                    cur.execute("UPDATE reglas_reposicion SET stock_seguridad=%s, updated_at=now() WHERE id=%s", (despues, regla["id"]))
                else:
                    cur.execute("INSERT INTO reglas_reposicion (org_id, producto_id, ubicacion_id, stock_seguridad) VALUES (%s,%s,%s,%s)",
                                (org_id, pid, uid, despues))
                cur.execute("INSERT INTO ajustes_aprendizaje (org_id, producto_id, ubicacion_id, campo, antes, despues, motivo) "
                            "VALUES (%s,%s,%s,'stock_seguridad',%s,%s,%s)",
                            (org_id, pid, uid, antes, despues,
                             f"En las últimas 3 órdenes se corrigió la cantidad {'hacia arriba' if delta > 0 else 'hacia abajo'} "
                             f"en promedio {abs(delta):.1f} unidades."))
            ajustes += 1
    return ajustes
