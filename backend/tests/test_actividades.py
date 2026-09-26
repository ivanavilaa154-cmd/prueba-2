"""Actividades según el caso: catálogo, las 6 reglas sobre la demo, ciclo de vida de las tareas, permisos y API."""
import math
import statistics
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.actividades import catalogo, motor, reglas
from app.actividades.datos import Datos
from app.erp import conector
from app.permisos import obtener_usuario

HOY = date(2026, 9, 24)  # la base demo de las pruebas se genera con esta fecha
AHORA = datetime(2026, 9, 24, 6, 0)


@pytest.fixture
def base_tareas(base_demo_config, tmp_path, monkeypatch):
    monkeypatch.setattr(motor, "RUTA", tmp_path / "actividades.db")
    return base_demo_config


@pytest.fixture
def datos(base_demo_config):
    return Datos(HOY)


def _det(resultado, caso, texto=""):
    return [d for d in resultado.detecciones if d.caso == caso and texto in d.titulo]


def _ev(det, etiqueta):
    return next(v for e, v, _f in det.evidencia if e.startswith(etiqueta))


def _uno(sql, url):
    return conector.consultar(sql, url=url)["filas"][0][0]


# --- catálogo ---------------------------------------------------------------------

def test_catalogo_completo():
    acts = catalogo.actividades()
    assert list(acts) == ["ACT-01", "ACT-02", "ACT-03", "ACT-04", "ACT-05", "ACT-06"]
    assert sum(len(a["casos"]) for a in acts.values()) == 31
    assert sum(len(c["acciones"]) for a in acts.values() for c in a["casos"]) == 72
    assert set(acts) == set(reglas.REGLAS)


def test_caso_sin_accion_no_se_carga():
    doc = {"actividades": [{"id": "X", "casos": [{"codigo": "C1", "acciones": []}], "resoluciones": ["a"]}]}
    with pytest.raises(catalogo.CatalogoInvalido, match="ninguna alerta sin acción"):
        catalogo.validar(doc)


@pytest.mark.parametrize("plazo,dias", [("inmediato", 0), ("2 h hábiles", 0), ("mismo día", 0), ("24 h", 1), ("48 h", 2),
                                        ("7 días", 7), ("24 h desde la carga", 1), ("próximo pedido", None), ("al recibir", None)])
def test_plazos(plazo, dias):
    assert catalogo.plazo_dias(plazo) == dias


def test_politica_mas_especifica(monkeypatch):
    monkeypatch.setattr(catalogo, "empresa", lambda: {"politica_precio": [
        {"alcance_tipo": "todas", "margen_minimo_pct": 18},
        {"alcance_tipo": "categoria", "alcance_valor": "Bebidas", "margen_minimo_pct": 22},
        {"alcance_tipo": "producto", "alcance_valor": 10, "margen_minimo_pct": 30}]})
    assert catalogo.politica("politica_precio", {"id": 1, "categoria": "Lácteos"})["margen_minimo_pct"] == 18
    assert catalogo.politica("politica_precio", {"id": 11, "categoria": "Bebidas"})["margen_minimo_pct"] == 22
    assert catalogo.politica("politica_precio", {"id": 10, "categoria": "Bebidas"})["margen_minimo_pct"] == 30


# --- reglas sobre la demo ---------------------------------------------------------

def test_act01_quiebre_oculto(datos, base_demo_config):
    r = reglas.act01(datos, lambda *a, **k: [])
    det = _det(r, "C1", "Refresco cola 2 L en Centro")
    assert len(det) == 1
    d = det[0]
    assert d.prioridad == "critica" and d.entidad["clase_abc"] == "A"   # clase A → crítica
    k = _ev(d, "Días seguidos sin venta")
    lam = _ev(d, "Venta media")
    assert k >= 1 and math.exp(-lam * k) < 0.01
    # λ contra una cuenta directa: unidades en días abiertos de la sucursal (hoy-35 a hoy-8) / días abiertos
    desde, hasta = (HOY - timedelta(days=35)).isoformat(), (HOY - timedelta(days=8)).isoformat()
    abiertos = _uno(f"SELECT COUNT(DISTINCT fecha) FROM ventas WHERE sucursal_id = 1 AND anulada = 0 AND fecha >= '{desde}' AND fecha <= '{hasta}'",
                    base_demo_config)
    unidades = _uno("SELECT SUM(l.cantidad) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id WHERE v.sucursal_id = 1 AND v.anulada = 0 "
                    f"AND l.producto_id = 10 AND v.fecha >= '{desde}' AND v.fecha <= '{hasta}'", base_demo_config)
    assert lam == round(unidades / abiertos, 1)
    assert _ev(d, "Stock en sistema") == 48
    # Conteo con menos de la mitad del stock del sistema → stock fantasma
    assert _det(r, "C3", "Aceite girasol 900 ml en Norte")


def test_act02_pedido_sugerido(datos):
    r = reglas.act02(datos, lambda *a, **k: [])
    casos = {d.caso for d in r.detecciones}
    assert {"C1", "C2", "C3"} <= casos
    # El proveedor con día de pedido "lunes" no genera pedido regular un jueves
    assert HOY.weekday() == 3 and not [d for d in r.detecciones if d.caso in ("C2", "C3") and d.entidad["proveedor_id"] == 3]
    for d in r.detecciones:
        if d.detalle:
            for f in d.detalle["filas"]:
                bulto = datos.productos[next(p for p, x in datos.productos.items() if x["descripcion"] == f[0])]["unidades_bulto"] or 1
                assert f[7] % bulto == 0                       # múltiplo del bulto
                assert f[10] == round(f[7] * f[9], 2)          # importe = cantidad × costo
    c3 = next(d for d in r.detecciones if d.caso == "C3")
    assert _ev(c3, "Importe sugerido") < _ev(c3, "Pedido mínimo")


def test_act02_cantidad(datos):
    """La cantidad sale de d×(LT+R) + SS − (stock + tránsito), redondeada al bulto."""
    pid = 4
    prod = datos.productos[pid]
    demanda = datos.vdp(pid, None, 56)
    disp, trans = datos.stock_de(pid)
    trans = max(trans, datos.pendiente_compra.get(pid, 0))
    lt = datos.lead_time(prod["proveedor_id"])
    ss = {"A": 1.65, "B": 1.28, "C": 0.84}[datos.abc[pid]] * datos.sigma(pid) * math.sqrt(lt)
    bulto = prod["unidades_bulto"]
    esperado = math.ceil(max(0.0, demanda * (lt + 7) + ss - disp - trans) / bulto) * bulto
    tope = 21 * 1.5 * demanda - disp - trans
    if esperado > tope > 0:
        esperado = max(bulto, math.floor(tope / bulto) * bulto)
    r = reglas.act02(datos, lambda *a, **k: [])
    filas = [f for d in r.detecciones if d.detalle for f in d.detalle["filas"] if f[0] == prod["descripcion"]]
    assert (filas[0][7] if filas else 0) == esperado


def test_act03_rotacion(datos):
    r = reglas.act03(datos, lambda *a, **k: [])
    sin_mov = _det(r, "C1", "Jabón de tocador x3 en Norte")
    assert sin_mov and _ev(sin_mov[0], "Valor a costo") == 90 * 64
    transferir = _det(r, "C4", "Cerveza 1 L de Norte a Centro")
    assert transferir and transferir[0].entidad["destino"] == "Centro"
    assert {d.caso for d in r.detecciones} >= {"C1", "C2", "C4"}


def test_act04_remarcacion(datos):
    r = reglas.act04(datos, lambda *a, **k: [])
    lista = _det(r, "C1", "Bebidas Río")
    assert lista and lista[0].detalle and len(lista[0].detalle["filas"]) >= 2
    assert 0.07 <= _ev(lista[0], "Variación promedio") <= 0.10
    for f in lista[0].detalle["filas"]:
        # sostener el margen anterior: precio sugerido ≈ costo nuevo / (1 − margen con el costo anterior)
        margen_ant = (f[1] - f[2]) / f[1]
        assert f[6] == math.ceil(f[3] / (1 - margen_ant))
    assert _det(r, "C3", "Lavandina")                       # precio 25 < costo
    assert _det(r, "C7", "Yerba")                           # listas con 45 % de diferencia
    minimo = _det(r, "C2")
    assert all(_ev(d, "Margen actual") < 0.18 for d in minimo)
    assert any(desc == ("ACT-04|7") for desc, _m in r.descartes)   # salsa en promoción: no se remarca


def test_act05_promociones(datos):
    r = reglas.act05(datos, lambda *a, **k: [])
    por_promo = {d.entidad["promocion_id"]: d.caso for d in r.detecciones}
    assert por_promo == {1: "C6", 2: "C3", 3: "C1"}
    fideos = next(d for d in r.detecciones if d.entidad["promocion_id"] == 2)
    assert _ev(fideos, "Margen incremental neto") < 0 and "Descuento máximo" in fideos.notas[0]


def test_act06_vencimientos(datos, base_demo_config):
    r = reglas.act06(datos, lambda *a, **k: [])
    vencido = _det(r, "C1")
    assert len(vencido) == 1
    cant, costo = vencido[0].evidencia[0][1], datos.costo(vencido[0].entidad["producto_id"])
    assert _ev(vencido[0], "Valor a costo") == round(cant * costo, 2)
    pronto = _det(r, "C2", "L0102N")
    assert pronto and 0 < _ev(pronto[0], "Descuento sugerido") <= 0.5
    mult = _ev(pronto[0], "Velocidad necesaria")
    pid = pronto[0].entidad["producto_id"]
    tope_costo = 1 - datos.costo(pid) / datos.precio_actual(pid)          # nunca por debajo del costo
    assert 1.2 <= mult <= 4
    assert _ev(pronto[0], "Descuento sugerido") == pytest.approx(min(0.5, 1 - mult ** -0.5, tope_costo), abs=0.01)
    assert _det(r, "C5", "Queso colonia kg en Norte")
    assert _det(r, "C4", "Leche entera")   # dos lotes de leche con problemas


def test_sin_datos_dice_que_falta(datos, monkeypatch):
    monkeypatch.setattr(Datos, "promociones", [])
    r = reglas.act05(datos, lambda *a, **k: [])
    assert not r.detecciones and r.faltan


# --- ciclo de vida ----------------------------------------------------------------

def test_ejecutar_y_no_duplicar(base_tareas):
    r1 = motor.ejecutar(HOY, AHORA)
    assert all(a["nuevas"] == a["detectadas"] for a in r1["actividades"].values())
    total = sum(a["nuevas"] for a in r1["actividades"].values())
    r2 = motor.ejecutar(HOY, AHORA + timedelta(hours=2))
    assert sum(a["nuevas"] for a in r2["actividades"].values()) == 0
    assert sum(a["actualizadas"] for a in r2["actividades"].values()) == total
    assert len(motor.listar(obtener_usuario("u1"))) == total


def test_tarea_completa(base_tareas):
    motor.ejecutar(HOY, AHORA)
    t = next(t for t in motor.listar(obtener_usuario("u1")) if t["tipo"] == "ACT-01" and t["caso"] == "C1")
    assert t["prioridad"] == "critica" and t["puntaje"] == pytest.approx(t["impacto_estimado"] * 3, abs=0.05)
    assert [a["responsable"] for a in t["acciones"]] == ["repositor", "repositor", "encargado_sucursal"]
    assert t["fecha_limite"] == HOY.isoformat()           # "2 h hábiles" / "mismo día"
    assert t["evidencia"] and t["estado"] == "nueva"


def test_resolucion_obligatoria_y_seguimiento(base_tareas):
    dueno = obtener_usuario("u1")
    motor.ejecutar(HOY, AHORA)
    t = next(t for t in motor.listar(dueno) if t["tipo"] == "ACT-01" and t["caso"] == "C1")
    with pytest.raises(ValueError, match="resolución"):
        motor.cambiar_estado(t["id"], dueno, "resuelta")
    assert motor.cambiar_estado(t["id"], dueno, "en_curso")["estado"] == "en_curso"
    r = motor.cambiar_estado(t["id"], dueno, "resuelta", "no_hay_stock_fisico_ajustado", "Contamos 0", ahora=AHORA)
    assert r["estado"] == "resuelta" and r["resuelta_por"] == "Iván" and r["seguimiento_id"]
    seg = motor.obtener(r["seguimiento_id"], dueno)
    assert seg["caso"] == "C3" and seg["origen"] == "seguimiento"
    with pytest.raises(ValueError, match="cerrada"):
        motor.cambiar_estado(t["id"], dueno, "en_curso")
    # El seguimiento no se cierra solo aunque la regla no lo vuelva a detectar
    motor.ejecutar(HOY, AHORA + timedelta(hours=1))
    assert motor.obtener(seg["id"], dueno)["estado"] == "nueva"


def test_falso_positivo_se_descarta_y_no_vuelve(base_tareas):
    dueno = obtener_usuario("u1")
    motor.ejecutar(HOY, AHORA)
    t = next(t for t in motor.listar(dueno) if t["tipo"] == "ACT-03" and t["caso"] == "C1")
    assert motor.cambiar_estado(t["id"], dueno, "resuelta", "falso_positivo", ahora=AHORA)["estado"] == "descartada"
    motor.ejecutar(HOY, AHORA + timedelta(hours=1))
    assert not [x for x in motor.listar(dueno) if x["clave_dedupe"] == t["clave_dedupe"]]
    p = motor.precision(dueno, HOY)["ACT-03"]
    assert p["cerradas"] == 1 and p["confirmadas"] == 0 and p["precision"] == 0


def test_cierre_automatico_y_vencimiento(base_tareas, monkeypatch):
    dueno = obtener_usuario("u1")
    motor.ejecutar(HOY, AHORA)
    abiertas = {t["id"] for t in motor.listar(dueno) if t["tipo"] == "ACT-05"}
    monkeypatch.setitem(motor.REGLAS, "ACT-05", lambda d, h: reglas.Resultado())
    motor.ejecutar(HOY, AHORA + timedelta(hours=1))
    cerradas = {t["id"]: t for t in motor.listar(dueno, "cerradas")}
    assert abiertas <= set(cerradas) and all(cerradas[i]["estado"] == "cerrada_automatica" for i in abiertas)
    # Días después, lo que pasó el plazo sin resolver queda vencido y sube al dueño
    motor.ejecutar(HOY + timedelta(days=10), AHORA + timedelta(days=10))
    vencidas = [t for t in motor.listar(dueno) if t["estado"] == "vencida"]
    assert vencidas and all(t["rol_plataforma"] == "dueno" for t in vencidas)


def test_permisos_por_rol(base_tareas):
    motor.ejecutar(HOY, AHORA)
    todas = motor.listar(obtener_usuario("u1"))
    compras = motor.listar(obtener_usuario("u3"))
    assert not motor.listar(obtener_usuario("u2"))                       # la vendedora no recibe estas tareas
    assert compras and len(compras) < len(todas)
    assert all(t["rol_plataforma"] == "compras" or any(a["rol_plataforma"] == "compras" for a in t["acciones"]) for t in compras)
    ajena = next(t for t in todas if t["tipo"] == "ACT-04" and t["caso"] == "C3")   # solo comercial
    with pytest.raises(PermissionError):
        motor.cambiar_estado(ajena["id"], obtener_usuario("u3"), "en_curso")


def test_notificar_respeta_tope(base_tareas, monkeypatch):
    monkeypatch.setattr(catalogo, "tope_diario", lambda: 2)
    motor.ejecutar(HOY, AHORA)
    for rol in ("compras", "gerente_comercial", "dueno"):
        tareas = [t for t in motor.listar(obtener_usuario("u1")) if t["rol_plataforma"] == rol]
        avisadas = [t for t in tareas if t["notificar"]]
        assert len(avisadas) == min(2, len(tareas))
        if len(tareas) > 2:   # las avisadas son las de mayor puntaje
            assert min(t["puntaje"] for t in avisadas) >= max(t["puntaje"] for t in tareas if not t["notificar"])


# --- API --------------------------------------------------------------------------

def test_api(base_tareas):
    from app.main import app
    motor.ejecutar(HOY, AHORA)
    c = TestClient(app)
    r = c.get("/actividades", params={"usuario_id": "u3"})
    assert r.status_code == 200
    d = r.json()
    assert d["totales"]["abiertas"] == len(d["abiertas"]) > 0 and len(d["catalogo"]) == 6
    pedido = next(t for t in d["abiertas"] if t["tipo"] == "ACT-02" and t["detalle"])
    csv = c.get(f"/actividades/{pedido['id']}/archivo.csv", params={"usuario_id": "u3"})
    assert csv.status_code == 200 and csv.text.lstrip("﻿").startswith("Producto;Clase;Stock")
    assert c.post(f"/actividades/{pedido['id']}", json={"usuario_id": "u3", "estado": "resuelta"}).status_code == 400
    ok = c.post(f"/actividades/{pedido['id']}", json={"usuario_id": "u3", "estado": "resuelta",
                                                       "resolucion": "pedido_emitido_corregido", "comentario": "Menos queso"})
    assert ok.status_code == 200 and ok.json()["estado"] == "resuelta"
    assert c.get("/actividades/999999/archivo.csv", params={"usuario_id": "u3"}).status_code == 404
    comercial = next(t for t in motor.listar(obtener_usuario("u1")) if t["rol_plataforma"] == "gerente_comercial"
                     and all(a["rol_plataforma"] != "compras" for a in t["acciones"]))
    assert c.post(f"/actividades/{comercial['id']}", json={"usuario_id": "u3", "estado": "en_curso"}).status_code == 403


def test_herramienta_del_chat(base_tareas):
    import json
    from app.chat import herramientas
    motor.ejecutar(HOY, AHORA)
    salida = json.loads(herramientas.ejecutar("ver_actividades", {}, obtener_usuario("u3")))
    assert salida and all({"titulo", "acciones", "evidencia"} <= set(t) for t in salida)
    assert json.loads(herramientas.ejecutar("ver_actividades", {}, obtener_usuario("u2"))) == []


def test_catalogo_kpis(base_demo_config):
    from app.analisis import catalogo_kpis
    e = catalogo_kpis.estado()
    assert e["total"] == 111
    por_id = {k["id"]: k for k in e["kpis"]}
    assert por_id["INV-06"]["disponible"]                          # quiebre: stock + ventas
    assert not por_id["FIN-06"]["disponible"] and "asientos contables" in por_id["FIN-06"]["faltan"]
    from app.erp import modelo
    propias = {t for tablas in modelo.PILARES.values() for t in tablas}
    assert {t for t in catalogo_kpis.EQUIVALENCIAS.values() if t} <= propias   # toda equivalencia apunta a una tabla real
