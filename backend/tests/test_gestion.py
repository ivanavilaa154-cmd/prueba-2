"""Gestión: procesos paso a paso, objetivos (validación, cascada, evaluación), ACT-07/ACT-08, permisos y API."""
import json
import math
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.actividades import motor
from app.erp import conector
from app.gestion import almacen, catalogo, metricas, objetivos, procesos
from app.permisos import obtener_usuario

HOY = date(2026, 9, 24)            # jueves; la base demo de las pruebas se genera con esta fecha
AHORA = datetime(2026, 9, 24, 14, 0)


@pytest.fixture
def g(base_demo_config, tmp_path, monkeypatch):
    monkeypatch.setattr(almacen, "RUTA", tmp_path / "gestion.db")
    monkeypatch.setattr(motor, "RUTA", tmp_path / "actividades.db")
    metricas._cache.clear()
    return base_demo_config


def _uno(sql, url):
    return conector.consultar(sql, url=url)["filas"][0][0]


DUENO = obtener_usuario("u1")


# --- catálogo y calendario ----------------------------------------------------------

def test_catalogo_gestion():
    ps = catalogo.procesos()
    assert list(ps) == ["PRC-VEN", "PRC-LOG", "PRC-COB", "PRC-COM", "PRC-CRM", "PRC-DEV"]
    assert sum(len(p["pasos"]) for p in ps.values()) == 36
    assert len(catalogo.plantillas()) == 24


def test_ningun_paso_ni_objetivo_sin_accion():
    with pytest.raises(catalogo.CatalogoInvalido, match="sin acción"):
        catalogo.validar({"procesos": [{"id": "X", "pasos": [{"codigo": "P1", "sla": {"dias": 1}}]}]}, {})
    with pytest.raises(catalogo.CatalogoInvalido, match="fuera de camino"):
        catalogo.validar({}, {"plantillas": [{"id": "OBJ-X", "si_en_riesgo": [{"accion": "a"}]}]})


def test_calendario():
    sabado = date(2026, 9, 26)
    assert catalogo.sumar_habiles(sabado, 1) == date(2026, 9, 28)          # el domingo no es hábil
    assert catalogo.plazo({"horas_habiles": 24}, sabado) == date(2026, 9, 30)   # 24 h hábiles = 3 días hábiles
    assert catalogo.plazo({"horas": 48}, sabado) == date(2026, 9, 28)
    assert catalogo.plazo({"dias": -3}, sabado) == date(2026, 9, 23)


# --- procesos --------------------------------------------------------------------

def test_cobranza_contra_sql(g):
    p = procesos.Proceso("PRC-COB", HOY, eventos={})
    desde = (HOY - timedelta(days=360)).isoformat()
    base = f"FROM cxc WHERE tipo = 'factura' AND importe > 0 AND fecha_emision >= '{desde}' AND fecha_emision <= '{HOY}'"
    vencidas = _uno(f"SELECT COUNT(*) {base} AND fecha_cobro IS NULL AND saldo > 0 AND fecha_vencimiento < '{HOY}'", g)
    assert sum(1 for c in p.casos if c.pasos["P5"]["estado"] == "pendiente_vencido") == vencidas
    abiertas = _uno(f"SELECT COUNT(*) {base} AND fecha_cobro IS NULL AND saldo > 0", g)
    assert sum(1 for c in p.casos if not c.cerrado) == abiertas
    # Cobradas tarde: fecha de cobro posterior al vencimiento (entre las que el proceso considera)
    ids = {c.key for c in p.casos}
    tarde = conector.consultar(f"SELECT id {base} AND fecha_cobro > fecha_vencimiento", url=g, max_filas=100000)["filas"]
    assert sum(1 for c in p.casos if c.pasos["P5"]["estado"] == "completado_fuera_de_sla") == sum(1 for (i,) in tarde if str(i) in ids)
    # Pasos sin dato en la integración nunca cuentan como omitidos
    assert all(c.pasos["P2"]["estado"] != "omitido" for c in p.casos)


def test_escalamiento_y_evento_manual(g):
    p = procesos.Proceso("PRC-COB", HOY, eventos={})
    c = max((c for c in p.casos if c.escalon), key=lambda c: c.escalon["dias"])
    assert c.escalon["dias_vencido"] == max(e["dias_vencido"] for e in catalogo.procesos()["PRC-COB"]["pasos"][4]["escalamiento"]
                                            if e["dias_vencido"] <= c.escalon["dias"])
    assert c.pasos["P3"]["estado"] == "pendiente_vencido"
    procesos.registrar_evento("PRC-COB", c.key, "gestion_cobranza_realizada", "Iván", fecha=HOY)
    p2 = procesos.Proceso("PRC-COB", HOY)
    c2 = next(x for x in p2.casos if x.key == c.key)
    assert c2.pasos["P3"]["estado"] in ("completado", "completado_fuera_de_sla")
    with pytest.raises(ValueError, match="no se registra a mano"):
        procesos.registrar_evento("PRC-COB", c.key, "cualquier_cosa", "Iván")


def test_venta_entrega_en_plazo_contra_sql(g):
    p = procesos.Proceso("PRC-VEN", HOY, eventos={})
    desde, hasta = HOY - timedelta(days=29), HOY
    m = p.metricas(desde, hasta)
    total = _uno(f"SELECT COUNT(*) FROM pedidos WHERE fecha_entrega >= '{desde}' AND fecha_entrega <= '{hasta}'", g)
    a_tiempo = _uno(f"SELECT COUNT(*) FROM pedidos WHERE fecha_entrega >= '{desde}' AND fecha_entrega <= '{hasta}' "
                    "AND fecha_entrega <= fecha_entrega_prometida", g)
    assert m["pasos"]["P6"]["cumplimiento_sla_pct"] == round(a_tiempo / total, 4)
    assert not m["pasos"]["P3"]["medible"]                     # facturado: la integración no vincula pedido con factura


def test_procesos_sin_datos_explican(g):
    for pid in ("PRC-LOG", "PRC-CRM", "PRC-DEV"):
        p = procesos.Proceso(pid, HOY)
        assert not p.activo and p.motivo


# --- objetivos: períodos, cascada, validación --------------------------------------

def test_periodos():
    assert objetivos.periodo("semanal", HOY) == (date(2026, 9, 21), date(2026, 9, 27))
    assert objetivos.periodo("mensual", HOY) == (date(2026, 9, 1), date(2026, 9, 30))
    assert objetivos.periodo("trimestral", HOY) == (date(2026, 7, 1), date(2026, 9, 30))
    assert objetivos.anterior("mensual", date(2026, 9, 1)) == (date(2026, 8, 1), date(2026, 8, 31))
    w = objetivos.pesos("dias_habiles", date(2026, 9, 1), date(2026, 9, 30), HOY)
    assert w[date(2026, 9, 6)] == 0 and sum(w.values()) == 26    # septiembre 2026: 4 domingos


def test_cascada_suma_la_meta(g):
    p = objetivos.proponer("OBJ-01", periodicidad="mensual", meta=900_000, cascada_tiempo=["semanal", "diario"],
                           cascada_alcance="sucursal", hoy=HOY)
    for t in p["cascada"]["tiempo"]:
        assert sum(x["meta"] for x in t["periodos"]) == pytest.approx(900_000, abs=1)
    assert len(p["cascada"]["tiempo"][1]["periodos"]) == 30
    assert sum(a["meta"] for a in p["cascada"]["alcance"]) == pytest.approx(900_000, abs=0.01)
    assert next(v for v in p["validacion"] if v["regla"].startswith("V4"))["severidad"] == "ok"


def test_validaciones(g):
    exigente = objetivos.proponer("OBJ-01", periodicidad="mensual", meta=50_000_000, hoy=HOY)
    v5 = next(v for v in exigente["validacion"] if v["regla"].startswith("V5"))
    assert v5["severidad"] == "advierte" and "Muy exigente" in v5["mensaje"] and exigente["requiere_justificacion"]
    with pytest.raises(ValueError, match="justificación"):
        objetivos.guardar({"plantilla_id": "OBJ-01", "periodicidad": "mensual", "meta": 50_000_000}, DUENO, hoy=HOY)
    logistica = objetivos.proponer("OBJ-07", hoy=HOY)
    assert logistica["bloquea"] and logistica["validacion"][0]["regla"].startswith("V1")
    sin_valor = objetivos.proponer("OBJ-01", alcance_tipo="sucursal", periodicidad="mensual", meta=100, hoy=HOY)
    assert sin_valor["bloquea"] and "a qué sucursal" in next(v for v in sin_valor["validacion"] if v["regla"].startswith("V3"))["mensaje"]
    muestra = objetivos.proponer("OBJ-18", periodicidad="mensual", hoy=HOY)       # ~20 órdenes por mes < 30
    assert any(v["regla"].startswith("V9") for v in muestra["validacion"])


def test_meta_sugerida_no_usa_meses_incompletos(g):
    primera = date.fromisoformat(_uno("SELECT MIN(fecha) FROM ventas", g))
    hist = objetivos.historia("kpi:VEN-01", "empresa", None, "mensual", HOY)
    assert hist and all(date.fromisoformat(h["inicio"]) >= primera for h in hist)
    s = objetivos.sugerir("OBJ-01", "empresa", None, "mensual", HOY)
    assert s["meta"] > 0.5 * hist[0]["valor"]


# --- evaluación ---------------------------------------------------------------------

def test_evaluacion_acumulable(g):
    r = objetivos.guardar({"plantilla_id": "OBJ-01", "periodicidad": "mensual", "meta": 900_000}, DUENO, "prueba", hoy=HOY)
    o = objetivos.obtener(r["id"])
    ev = objetivos.evaluar(o, HOY, AHORA)
    ini, corte = date(2026, 9, 1), date(2026, 9, 23)
    venta = _uno(f"SELECT SUM(l.cantidad * l.precio_unitario) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id "
                 f"WHERE v.anulada = 0 AND v.fecha >= '{ini}' AND v.fecha <= '{corte}'", g)
    dev = _uno(f"SELECT COALESCE(SUM(importe), 0) FROM devoluciones WHERE fecha >= '{ini}' AND fecha <= '{corte}'", g)
    assert ev["valor_actual"] == pytest.approx(venta - dev, abs=0.01)
    c = ev["fraccion_periodo"]
    assert ev["valor_esperado"] == pytest.approx(900_000 * c, rel=1e-3)
    assert ev["ritmo"] == pytest.approx(ev["valor_actual"] / ev["valor_esperado"], abs=1e-3)
    assert ev["proyeccion_cierre"] == pytest.approx(ev["valor_actual"] / c, rel=1e-3)
    esperado = "en_camino" if ev["ritmo"] >= 0.95 else "en_riesgo" if ev["ritmo"] >= 0.85 else "fuera_de_camino"
    assert ev["estado"] == esperado
    o_bajo = dict(o, meta_base=1.0)
    with almacen.conectar() as con:
        con.execute("DELETE FROM objetivo_meta WHERE objetivo_id=?", (o["id"],))
    assert objetivos.evaluar(o_bajo, HOY, AHORA, guardar=False)["estado"] == "cumplido"


def test_cascada_diaria_recupera(g):
    r = objetivos.guardar({"plantilla_id": "OBJ-01", "periodicidad": "mensual", "meta": 900_000, "cascada_tiempo": ["diario"]},
                          DUENO, "prueba", hoy=HOY)
    diario = objetivos.obtener(r["hijos"][0])
    meta_hoy = objetivos.meta_de(diario, HOY, HOY, HOY)
    hecho = metricas.valor("kpi:VEN-01", "empresa", None, date(2026, 9, 1), HOY - timedelta(days=1), HOY)[0]
    w = objetivos.pesos("estacionalidad_historica", date(2026, 9, 1), date(2026, 9, 30), HOY)
    resto = sum(v for d, v in w.items() if d >= HOY)
    assert meta_hoy == pytest.approx((900_000 - hecho) * w[HOY] / resto, abs=0.05)


def test_no_acumulable_muestra_chica(g):
    r = objetivos.guardar({"plantilla_id": "OBJ-18", "periodicidad": "mensual", "meta": 0.9}, DUENO, "prueba", hoy=HOY)
    ev = objetivos.evaluar(objetivos.obtener(r["id"]), HOY, AHORA)
    assert ev["estado"] == "no_evaluable" and "Muestra chica" in ev["advertencias"][0]


def test_permisos_objetivos(g):
    objetivos.guardar({"plantilla_id": "OBJ-01", "periodicidad": "mensual", "meta": 900_000}, DUENO, "x", hoy=HOY)
    objetivos.guardar({"plantilla_id": "OBJ-06", "periodicidad": "mensual", "alcance_tipo": "vendedor", "alcance_valor": "1"}, DUENO, "x", hoy=HOY)
    objetivos.guardar({"plantilla_id": "OBJ-17", "periodicidad": "mensual", "meta": 12}, DUENO, "x", hoy=HOY)
    laura = objetivos.tablero(obtener_usuario("u2"), hoy=HOY, ahora=AHORA)
    assert [x["objetivo"]["plantilla_id"] for x in laura["objetivos"]] == ["OBJ-06"]
    otra = objetivos.tablero(obtener_usuario("vendedor:2") if False else
                             __import__("app.permisos", fromlist=["x"]).Usuario("v2", "Diego", "vendedor", 2), hoy=HOY, ahora=AHORA)
    assert otra["objetivos"] == []
    compras = objetivos.tablero(obtener_usuario("u3"), hoy=HOY, ahora=AHORA)
    assert {x["objetivo"]["area"] for x in compras["objetivos"]} == {"inventario"}
    with pytest.raises(PermissionError):
        objetivos.guardar({"plantilla_id": "OBJ-01", "periodicidad": "mensual"}, obtener_usuario("u3"), "x", hoy=HOY)


# --- ACT-07 y ACT-08 --------------------------------------------------------------

def test_act07_casos_trabados(g):
    motor.ejecutar(HOY, AHORA, solo=["ACT-07"])
    tareas = [t for t in motor.listar(DUENO) if t["tipo"] == "ACT-07"]
    p = procesos.Proceso("PRC-COB", HOY)
    assert len([t for t in tareas if t["entidad"]["proceso"] == "PRC-COB"]) == sum(1 for c in p.casos if c.trabado)
    t = next(t for t in tareas if t["caso"] == "C1" and t["prioridad"] == "critica")    # con escalón alcanzado
    textos = " ".join(a["accion"] for a in t["acciones"])
    assert "Escalón" in textos and "causa del atraso" in textos
    assert t["acciones"][0]["responsable"] == "cobrador" and t["rol_plataforma"] == "administracion"
    # La vendedora ve solo las de su cartera donde tiene una acción
    for x in motor.listar(obtener_usuario("u2")):
        assert x["entidad"].get("vendedor_id") == 1


def test_act08_objetivo_en_rojo_y_vuelta(g):
    r = objetivos.guardar({"plantilla_id": "OBJ-01", "periodicidad": "mensual", "meta": 5_000_000}, DUENO, "prueba", hoy=HOY)
    motor.ejecutar(HOY, AHORA, solo=["ACT-08"])
    t = next(t for t in motor.listar(DUENO) if t["tipo"] == "ACT-08" and t["caso"] == "C2")
    assert t["entidad"]["objetivo_id"] == r["id"]
    # 5 M contra una historia de menos de 1 M por mes: además, meta descalibrada (C5)
    assert any(x["caso"] == "C5" for x in motor.listar(DUENO) if x["tipo"] == "ACT-08")
    pl = catalogo.plantillas()["OBJ-01"]
    assert [a["accion"] for a in t["acciones"][:len(pl["si_fuera_de_camino"])]] == [a["accion"] for a in pl["si_fuera_de_camino"]]
    assert t["impacto_estimado"] > 0 and any("hace falta" in n for n in t["notas"])
    # Sin cambio de estado no se duplica; al volver a camino se cierra sola
    motor.ejecutar(HOY, AHORA + timedelta(minutes=15), solo=["ACT-08"])
    assert len([x for x in motor.listar(DUENO) if x["tipo"] == "ACT-08" and x["caso"] == "C2"]) == 1
    with almacen.conectar() as con:
        con.execute("UPDATE objetivo_meta SET meta = 1 WHERE objetivo_id = ?", (r["id"],))
    motor.ejecutar(HOY, AHORA + timedelta(minutes=30), solo=["ACT-08"])
    cerrada = next(x for x in motor.listar(DUENO, "cerradas") if x["id"] == t["id"])
    assert cerrada["estado"] == "cerrada_automatica"


# --- API y chat -------------------------------------------------------------------

def test_api_gestion(g):
    from app.main import app
    c = TestClient(app)
    p = c.post("/gestion/objetivos/proponer", json={"usuario_id": "u1", "plantilla_id": "OBJ-02", "periodicidad": "mensual"})
    assert p.status_code == 200 and p.json()["meta"] and not p.json()["bloquea"]
    ok = c.post("/gestion/objetivos", json={"usuario_id": "u1", "plantilla_id": "OBJ-02", "periodicidad": "mensual", "justificacion": "x",
                                            "cascada_tiempo": ["semanal"]})
    assert ok.status_code == 200 and len(ok.json()["hijos"]) == 1
    assert c.post("/gestion/objetivos", json={"usuario_id": "u2", "plantilla_id": "OBJ-02", "periodicidad": "mensual"}).status_code == 403
    tab = c.get("/gestion/objetivos", params={"usuario_id": "u1"}).json()
    assert len(tab["objetivos"]) == 2
    det = c.get(f"/gestion/objetivos/{ok.json()['id']}", params={"usuario_id": "u1"}).json()
    assert det["hijos"] and det["acciones"]["en_riesgo"]
    assert c.get("/gestion/objetivos/9999", params={"usuario_id": "u1"}).status_code == 404
    pr = c.get("/gestion/procesos", params={"usuario_id": "u3"}).json()["procesos"]
    assert {x["id"] for x in pr} == {"PRC-COM", "PRC-LOG"}                     # compras: inventario y logística
    caso = next(x for x in c.get("/gestion/procesos", params={"usuario_id": "u1"}).json()["procesos"] if x["id"] == "PRC-COB")["trabados"][0]
    body = {"usuario_id": "u3", "caso_key": caso["caso_key"], "codigo": "gestion_cobranza_realizada"}
    assert c.post("/gestion/procesos/PRC-COB/eventos", json=body).status_code == 403
    assert c.post("/gestion/procesos/PRC-COB/eventos", json={**body, "usuario_id": "u1"}).status_code == 200


def test_herramientas_chat_gestion(g):
    from app.chat import herramientas
    objetivos.guardar({"plantilla_id": "OBJ-01", "periodicidad": "mensual", "meta": 900_000}, DUENO, "x", hoy=HOY)
    r = json.loads(herramientas.ejecutar("consultar_objetivos", {}, DUENO))
    assert r["objetivos"] and "ritmo" in r["objetivos"][0]
    prop = json.loads(herramientas.ejecutar("proponer_objetivo", {"plantilla_id": "OBJ-02"}, DUENO))
    assert "validacion" in prop and not objetivos.listar_objetivos()[1:]      # proponer no guarda
    trab = json.loads(herramientas.ejecutar("casos_trabados", {"proceso": "PRC-COB"}, DUENO))
    assert trab[0]["total"] > 0
    assert json.loads(herramientas.ejecutar("registrar_evento_proceso", {"proceso": "PRC-COB", "caso_key": "1", "codigo_evento": "x"},
                                            obtener_usuario("u3")))["tipo"] == "no_permitido"


def test_curva_intradia(g, monkeypatch):
    """Con la hora de cada venta, la parte esperada del día sale de las mismas horas de las 8 semanas anteriores."""
    assert objetivos.fraccion_intradia(HOY, AHORA) is None           # la demo no trae hora
    monkeypatch.setattr(metricas, "_q", lambda sql: [["09:30", 100.0], ["13:00", 300.0], ["18:00", 600.0]] if "v.hora" in sql else [])
    assert objetivos.fraccion_intradia(HOY, AHORA) == pytest.approx(0.4)   # a las 14:00 va el 40 %
