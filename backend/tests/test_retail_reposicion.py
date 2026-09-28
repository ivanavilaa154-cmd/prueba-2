"""Retail · parte 9: reposición, transferencias y OC contra los criterios de aceptación de la sección 17."""
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.retail import db, demo, motor, reposicion
from app.retail.semilla import CLAVE_DEMO

HOY = date(2026, 9, 24)


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def _x(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn, conn.cursor() as cur:
        cur.execute(sql, params)


def cliente(email):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def test_mixto_transfiere_antes_de_comprar_sin_dejar_al_origen_bajo_su_minimo(retail_demo):
    """Criterio: en modelo mixto se propone transferencia antes que OC y el origen no queda por debajo de su mínimo."""
    caso = demo.CASOS["sobrestock"]      # sobra en Jujuy (y el depósito tiene), falta en Salta Centro
    pid = _q("SELECT id FROM productos WHERE codigo_interno=%s", (caso["producto"],))[0]["id"]
    trs = _q("""SELECT t.origen_id, t.destino_id, l.cantidad, o.nombre origen, d.nombre destino FROM transferencias t
                JOIN transferencias_lineas l ON l.transferencia_id = t.id JOIN ubicaciones o ON o.id = t.origen_id JOIN ubicaciones d ON d.id = t.destino_id
                WHERE l.producto_id=%s AND t.motivo='reposicion'""", (pid,))
    assert any(t["destino"] == "Salta Centro" for t in trs)
    trs = [t for t in trs if t["destino"] == "Salta Centro"]
    oc_centro = _q("""SELECT l.cantidad FROM ordenes_compra_lineas l JOIN ordenes_compra o ON o.id=l.orden_id JOIN ubicaciones u ON u.id=l.ubicacion_id
                      WHERE l.producto_id=%s AND u.nombre='Salta Centro' AND o.origen='sugerida'""", (pid,))
    necesidad = _q("""SELECT (m.explicacion->>'necesidad')::numeric n FROM metricas_producto_actual m JOIN ubicaciones u ON u.id=m.ubicacion_id
                      WHERE m.producto_id=%s AND u.nombre='Salta Centro'""", (pid,))[0]["n"]
    transferido = sum(t["cantidad"] for t in trs)
    assert transferido > 0
    if transferido >= necesidad:
        assert not oc_centro, "si la transferencia cubre, no se compra"
    # El origen conserva al menos su mínimo (14 días de venta por defecto) y lo que necesita para su horizonte.
    cedido = {}
    for t in _q("""SELECT t.origen_id, sum(l.cantidad) c FROM transferencias t JOIN transferencias_lineas l ON l.transferencia_id=t.id
                   WHERE l.producto_id=%s AND t.motivo='reposicion' GROUP BY 1""", (pid,)):
        cedido[t["origen_id"]] = t["c"]
    for t in [{"origen_id": o, "cantidad": c} for o, c in cedido.items()]:
        m = _q("SELECT disponible, pronostico_diario, horizonte_dias, stock_seguridad FROM metricas_producto_actual WHERE producto_id=%s AND ubicacion_id=%s",
               (pid, t["origen_id"]))[0]
        reserva = max(14 * m["pronostico_diario"], m["pronostico_diario"] * m["horizonte_dias"] + m["stock_seguridad"])
        assert m["disponible"] - t["cantidad"] >= reserva - Decimal("0.001")


def test_centralizado_ninguna_sucursal_genera_oc(retail_demo):
    """Criterio: en modelo centralizado, ninguna sucursal genera OC (compra el depósito)."""
    _x("UPDATE organizaciones SET modelo_abastecimiento='centralizado' WHERE id=1")
    _x("DELETE FROM ordenes_compra WHERE origen='sugerida'")     # las aprobadas antes con el modelo mixto no se tocan al regenerar
    reposicion.generar(1, HOY)
    ocs = _q("""SELECT u.tipo, count(*) c FROM ordenes_compra o JOIN ubicaciones u ON u.id=o.ubicacion_id WHERE o.origen='sugerida'
                GROUP BY 1""")
    tipos = {o["tipo"]: o["c"] for o in ocs}
    assert tipos.get("venta", 0) == 0 and tipos.get("ambos", 0) == 0
    assert tipos.get("deposito", 0) > 0
    assert _q("SELECT count(*) c FROM ordenes_compra WHERE origen='sugerida' AND ubicacion_id IS NULL")[0]["c"] == 0


def test_descentralizado_no_transfiere(retail_demo):
    _x("UPDATE organizaciones SET modelo_abastecimiento='descentralizado' WHERE id=1")
    reposicion.generar(1, HOY)
    assert _q("SELECT count(*) c FROM transferencias WHERE motivo='reposicion' AND estado='sugerida'")[0]["c"] == 0
    assert _q("SELECT count(*) c FROM ordenes_compra WHERE origen='sugerida'")[0]["c"] > 0


def test_oc_respeta_pedido_minimo_o_propone_completarlo(retail_demo):
    """Criterio: las OC por proveedor respetan el pedido mínimo o proponen completarlo (y lo explican)."""
    ocs = _q("""SELECT o.id, o.total, o.explicacion, pr.pedido_minimo_monto FROM ordenes_compra o JOIN proveedores pr ON pr.id=o.proveedor_id
                WHERE o.origen='sugerida'""")
    assert ocs
    for o in ocs:
        e = o["explicacion"]
        if o["total"] >= o["pedido_minimo_monto"]:
            continue
        # No llega: tiene que haber intentado completarlo con adelantos o avisar cuánto falta, y nunca aprobarse sola.
        assert e["cumple_minimo"] is False and Decimal(e["falta_para_minimo"]) > 0
    con_adelantos = [o for o in ocs if o["explicacion"]["adelantos"] > 0]
    for o in con_adelantos:
        lineas = _q("SELECT adelantada, explicacion FROM ordenes_compra_lineas WHERE orden_id=%s AND adelantada", (o["id"],))
        assert lineas and all("inversion_extra" in l["explicacion"] for l in lineas)
    aprobadas_bajo_minimo = _q("""SELECT count(*) c FROM ordenes_compra o JOIN proveedores pr ON pr.id=o.proveedor_id
                                  WHERE o.origen='sugerida' AND o.estado='aprobada' AND o.total < pr.pedido_minimo_monto""")
    assert aprobadas_bajo_minimo[0]["c"] == 0


def test_automatizacion_aprueba_bajo_el_limite_pero_nunca_envia(retail_demo):
    ocs = _q("SELECT estado, aprobacion, total FROM ordenes_compra WHERE origen='sugerida'")
    limite = _q("SELECT monto_limite FROM config_automatizacion WHERE tipo_documento='orden_compra'")[0]["monto_limite"]
    for o in ocs:
        if o["estado"] == "aprobada":
            assert o["aprobacion"] == "automatica" and o["total"] <= limite
    assert not any(o["estado"] == "enviada" for o in ocs)


def test_aprobacion_respeta_limites_por_rol(retail_demo):
    """Criterio: los flujos de aprobación respetan los límites de monto por rol."""
    _x("UPDATE config_automatizacion SET nivel='borrador'")
    reposicion.generar(1, HOY)
    grande = _q("SELECT id, total FROM ordenes_compra WHERE origen='sugerida' AND estado='borrador' ORDER BY total DESC LIMIT 1")[0]
    _x("UPDATE limites_aprobacion SET monto_maximo=%s WHERE rol='comprador' AND tipo_documento='orden_compra'", (grande["total"] - 1,))
    comprador, dueno, encargado = cliente("compras@norte.demo"), cliente("dueno@norte.demo"), cliente("encargado.norte@norte.demo")
    r = comprador.post(f"/retail/api/ordenes/{grande['id']}/aprobar")
    assert r.status_code == 403 and "límite" in r.json()["detail"]
    assert encargado.post(f"/retail/api/ordenes/{grande['id']}/aprobar").status_code in (403, 404)
    assert dueno.post(f"/retail/api/ordenes/{grande['id']}/aprobar").status_code == 200
    _x("UPDATE limites_aprobacion SET monto_maximo=%s WHERE rol='comprador' AND tipo_documento='orden_compra'", (grande["total"],))
    otra = _q("SELECT id FROM ordenes_compra WHERE origen='sugerida' AND estado='borrador' AND total <= %s LIMIT 1", (grande["total"],))[0]
    assert comprador.post(f"/retail/api/ordenes/{otra['id']}/aprobar").status_code == 200


def test_envio_y_recepcion_con_diferencias(retail_demo, tmp_path, monkeypatch):
    from app.retail import emails, pdf
    monkeypatch.setattr(emails, "CARPETA", tmp_path / "emails")
    monkeypatch.setattr(pdf, "CARPETA", tmp_path / "docs")
    dueno = cliente("dueno@norte.demo")
    oc = _q("SELECT id FROM ordenes_compra WHERE origen='sugerida' AND ubicacion_id IS NOT NULL ORDER BY id LIMIT 1")[0]["id"]
    detalle = dueno.get(f"/retail/api/ordenes/{oc}").json()
    if detalle["estado"] != "aprobada":
        assert dueno.post(f"/retail/api/ordenes/{oc}/aprobar").status_code == 200
    r = dueno.post(f"/retail/api/ordenes/{oc}/enviar", json={})
    assert r.status_code == 200 and r.json()["orden"]["estado"] == "enviada" and r.json()["email"]["guardados"] == 1
    assert list((tmp_path / "docs").glob("*.pdf")) and list((tmp_path / "emails").glob("*.html"))
    lineas = r.json()["orden"]["lineas"]
    primera = lineas[0]
    stock_antes = _q("SELECT cantidad FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (primera["producto_id"], primera["ubicacion_id"]))[0]["cantidad"]
    recibo = [{"producto_id": l["producto_id"], "ubicacion_id": l["ubicacion_id"], "cantidad": float(l["cantidad"]) - (2 if i == 0 else 0),
               "costo": str(l["costo"]) if l["costo"] is not None else None} for i, l in enumerate(lineas)]
    if recibo[0]["costo"]:
        recibo[0]["costo"] = str(Decimal(recibo[0]["costo"]) * Decimal("1.1"))
    r = dueno.post(f"/retail/api/ordenes/{oc}/recepcion", json={"lineas": recibo, "documento": "Remito 0001-123"})
    assert r.status_code == 200, r.text
    difs = r.json()["diferencias"]
    assert difs and "faltante" in difs[0]["tipo"]
    assert r.json()["orden"]["estado"] == "recibida_parcial"
    stock_despues = _q("SELECT cantidad FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (primera["producto_id"], primera["ubicacion_id"]))[0]["cantidad"]
    assert stock_despues == stock_antes + Decimal(str(recibo[0]["cantidad"]))


def test_transferencia_enviar_y_recibir_mueve_stock(retail_demo):
    dueno = cliente("dueno@norte.demo")
    t = _q("SELECT id FROM transferencias WHERE estado IN ('sugerida','aprobada') ORDER BY id LIMIT 1")[0]["id"]
    det = dueno.get(f"/retail/api/transferencias/{t}").json()
    if det["estado"] == "sugerida":
        assert dueno.post(f"/retail/api/transferencias/{t}/aprobar").status_code == 200
    l = det["lineas"][0]
    l = {**l, "cantidad": Decimal(l["cantidad"])}
    antes_o = _q("SELECT cantidad FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (l["producto_id"], det["origen_id"]))[0]["cantidad"]
    assert dueno.post(f"/retail/api/transferencias/{t}/enviar").status_code == 200
    destino = _q("SELECT cantidad, en_transito FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (l["producto_id"], det["destino_id"]))[0]
    assert destino["en_transito"] >= l["cantidad"]
    assert _q("SELECT cantidad FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (l["producto_id"], det["origen_id"]))[0]["cantidad"] == antes_o - l["cantidad"]
    r = dueno.post(f"/retail/api/transferencias/{t}/recibir", json={"lineas": [{"id": l["id"], "cantidad_recibida": float(l["cantidad"]) - 1}]})
    assert r.status_code == 200 and r.json()["diferencias"]
    despues = _q("SELECT cantidad, en_transito FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (l["producto_id"], det["destino_id"]))[0]
    assert despues["cantidad"] == destino["cantidad"] + l["cantidad"] - 1


def test_rescate_de_vencimientos(retail_demo):
    caso = demo.CASOS["vence_pronto"]
    rescates = _q("""SELECT t.*, l.lote FROM transferencias t JOIN transferencias_lineas l ON l.transferencia_id=t.id
                     JOIN ubicaciones o ON o.id=t.origen_id WHERE t.motivo='rescate_vencimiento' AND o.nombre=%s""", (caso["ubicacion"],))
    assert any(r["lote"] == "LVENCE01" for r in rescates)


def test_escalamiento_el_dia_de_visita(retail_demo):
    """Una OC sin aprobar el día que pasa el proveedor se escala al dueño; la de otro proveedor no."""
    jueves = _q("SELECT id FROM proveedores WHERE 3 = ANY(dias_visita) LIMIT 1")[0]["id"]
    otro = _q("SELECT id FROM proveedores WHERE NOT (3 = ANY(dias_visita)) AND dias_visita <> '{}' LIMIT 1")[0]["id"]
    for prov, num in ((jueves, "OC-T1"), (otro, "OC-T2")):
        _x("INSERT INTO ordenes_compra (org_id, numero, proveedor_id, ubicacion_id, estado, origen) "
           "VALUES (1, %s, %s, (SELECT id FROM ubicaciones WHERE nombre='Salta Centro'), 'borrador', 'manual')", (num, prov))
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        reposicion.escalar(conn, HOY)          # HOY es jueves
    estado = {r["numero"]: r["escalada_at"] is not None for r in _q("SELECT numero, escalada_at FROM ordenes_compra WHERE numero IN ('OC-T1','OC-T2')")}
    assert estado == {"OC-T1": True, "OC-T2": False}


def test_comprar_y_reponer_api(retail_demo):
    c = cliente("dueno@norte.demo")
    r = c.get("/retail/api/comprar").json()
    assert r["filas"] and {"productos_en_rojo", "plata_a_comprar", "ventas_en_riesgo"} <= set(r["tarjetas"])
    rojo = next((f for f in r["filas"] if f["semaforo"] in ("rojo", "amarillo")), r["filas"][0])
    d = c.get(f"/retail/api/productos/{rojo['producto_id']}?ubicacion_id={rojo['ubicacion_id']}").json()
    assert d["texto_sugerencia"].startswith(("Te sugiero", "No hace falta")) and len(d["serie"]) > 100
    assert "por día" in d["texto_sugerencia"]
    enc = cliente("encargado.norte@norte.demo").get("/retail/api/comprar").json()
    assert {f["ubicacion"] for f in enc["filas"]} == {"Salta Norte"}


def test_recuento_guiado(retail_demo):
    enc = cliente("encargado.norte@norte.demo")
    uid = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Norte'")[0]["id"]
    r = enc.get(f"/retail/api/recuentos/hoy?ubicacion_id={uid}").json()
    assert 1 <= len(r["lineas"]) <= 12
    motivos = [l["motivo_seleccion"] for l in r["lineas"]]
    assert motivos[0] == "stock_fantasma"          # el caso de stock fantasma de Salta Norte va primero
    otra = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Centro'")[0]["id"]
    assert enc.get(f"/retail/api/recuentos/hoy?ubicacion_id={otra}").status_code == 404
    linea = r["lineas"][0]
    assert enc.put(f"/retail/api/recuentos/lineas/{linea['id']}", json={"contado": 0}).status_code == 400   # hay diferencia: falta motivo
    res = enc.put(f"/retail/api/recuentos/lineas/{linea['id']}", json={"contado": 0, "motivo": "No estaba en góndola ni en depósito"}).json()
    assert Decimal(res["diferencia"]) == -Decimal(str(linea["stock_actual"]))
    # sin límite para ajustes, el encargado no puede ajustar: queda para el dueño
    assert res["estado"] == "pendiente_aprobacion"
    dueno = cliente("dueno@norte.demo")
    pend = dueno.get("/retail/api/recuentos/pendientes-aprobacion").json()
    assert any(p["id"] == linea["id"] for p in pend)
    assert dueno.post(f"/retail/api/recuentos/lineas/{linea['id']}/aprobacion", json={"aprobar": True}).status_code == 200
    assert _q("SELECT cantidad FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (linea["producto_id"], uid))[0]["cantidad"] == 0
