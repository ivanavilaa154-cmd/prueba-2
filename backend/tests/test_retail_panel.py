"""Retail · Fase 3 (13.3): panel para distribuidores y marcas, agregado y anónimo, y portal de pedidos."""
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app
from app.retail import api_panel, db, demo, demo_panel
from app.retail.semilla import CLAVE_DEMO

from conftest import DEMO_HOY


def cliente(email):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _q(sql, params=()):
    with db.transaccion(superadmin=True) as conn:
        return db.filas(conn, sql, params)


@pytest.fixture
def panel(retail_demo):
    return demo_panel.cargar(hoy=DEMO_HOY)


def test_particion_con_supresion_complementaria(monkeypatch):
    monkeypatch.setattr(config, "PANEL_MIN_COMERCIOS", 3)
    monkeypatch.setattr(config, "PANEL_MAX_PARTICIPACION", 0.6)
    g = {"A": {1: 10, 2: 10, 3: 10}, "B": {1: 5, 2: 5, 3: 5, 4: 5}, "C": {9: 20}}
    ok, resto = api_panel.particion(g)
    # C lo vende un solo comercio: se reserva, y como solo no pasa, se reserva también el publicado más chico (B)
    # para que el resto (B + C) tenga al menos 3 comercios y nadie despeje C restando.
    assert ok == {"A"} and resto
    assert api_panel.pasa(api_panel._unir([g["B"], g["C"]]))
    # Un comercio con el 70 % no se publica aunque haya 3.
    assert not api_panel.pasa({1: 70, 2: 15, 3: 15})
    # Sin forma de juntar un resto que pase: no se publica nada (tampoco el total).
    assert api_panel.particion({"A": {1: 10, 2: 10, 3: 10}, "C": {9: 50}}) == (set(), False)


def test_panel_agregado_y_anonimo(panel):
    c = cliente(demo_panel.USUARIO_DISTRIBUIDOR[0])
    r = c.get("/retail/api/panel").json()
    texto = json.dumps(r, ensure_ascii=False)
    for nombre, *_ in demo_panel.COMERCIOS:
        assert nombre not in texto                                  # nunca aparece un comercio
    assert demo.EMPRESA not in texto and "Salta Centro" not in texto
    assert r["kpis"]["comercios"] >= config.PANEL_MIN_COMERCIOS
    zonas = {z["zona"]: z for z in r["zonas"]}
    # Salta: Norte + 8 comercios con consentimiento (el que no dio consentimiento no cuenta). Jujuy tiene 3: queda afuera.
    assert zonas["Salta"]["comercios"] == 9 and not zonas["Salta"].get("reservado")
    assert "San Salvador de Jujuy" not in zonas and r["kpis"]["zonas_reservadas"] == 1
    # La cifra de Salta es la suma de los comercios con consentimiento (sin «Autoservicio Yala»).
    esperado = _q("""SELECT sum(a.facturacion) f FROM agg_producto_ubicacion_dia a JOIN organizaciones o ON o.id=a.org_id
                     JOIN productos p ON p.id=a.producto_id JOIN productos_maestros pm ON pm.id=p.maestro_id JOIN ubicaciones u ON u.id=a.ubicacion_id
                     WHERE o.consentimiento_datos AND o.tipo='comercio' AND u.localidad='Salta' AND pm.marca = ANY(%s) AND a.fecha BETWEEN %s AND %s""",
                  (demo_panel.MARCAS, r["desde"], r["hasta"]))[0]["f"]
    assert abs(float(esperado) - zonas["Salta"]["facturacion"]) < 1
    # La marca propia de Autoservicios del Norte la vende un solo comercio: va dentro de «Otras marcas».
    for sub in r["mercado"]:
        marcas = {m["marca"] for m in sub.get("marcas", [])}
        assert "Norte Selección" not in marcas
        assert abs(sum(m["participacion"] for m in sub.get("marcas", [])) - 1) < 1e-6 or sub.get("reservado")
    assert any(m["tuya"] for sub in r["mercado"] for m in sub.get("marcas", []))
    semanas = [s for s in r["serie"] if not s.get("reservado")]
    assert len(semanas) == r["semanas"]


def test_panel_cobertura_quiebres_promociones_y_oportunidades(panel):
    r = cliente(demo_panel.USUARIO_DISTRIBUIDOR[0]).get("/retail/api/panel").json()
    prods = {p["producto"]: p for p in r["productos"]}
    con_quiebre = [p for p in prods.values() if p.get("quiebres") is not None]
    assert con_quiebre
    # La entrega que falla en el último mes (Cola Norte 1,5 L también: es el faltante conocido de Salta Centro).
    peores = sorted(con_quiebre, key=lambda p: -p["quiebres"])[:2]
    assert demo_panel.QUIEBRE["producto"] in {p["producto"] for p in peores}
    otros = sorted(p["quiebres"] for p in con_quiebre)
    assert prods[demo_panel.QUIEBRE["producto"]]["quiebres"] > 2 * otros[len(otros) // 2]
    assert all(0 < p["cobertura"] <= 1 for p in prods.values() if "cobertura" in p)
    promo = next(p for p in r["promociones"] if p["producto"] == demo_panel.CAMPANA["producto"])
    assert promo["comercios"] >= config.PANEL_MIN_COMERCIOS and 0.3 < promo["incremento"] < 1.2
    assert r["oportunidades"]
    for o in r["oportunidades"]:
        assert 0 < o["comercios_sin"] < o["comercios_categoria"] and o["comercios_categoria"] >= config.PANEL_MIN_COMERCIOS


def test_panel_respeta_el_umbral_y_los_permisos(panel, monkeypatch):
    monkeypatch.setattr(config, "PANEL_MIN_COMERCIOS", 20)
    r = cliente(demo_panel.USUARIO_DISTRIBUIDOR[0]).get("/retail/api/panel").json()
    assert r["reservado"] and "productos" not in r and "zonas" not in r
    # Un comercio no ve el panel; el distribuidor no ve las pantallas de un comercio.
    assert cliente("dueno@norte.demo").get("/retail/api/panel").status_code == 403
    d = cliente(demo_panel.USUARIO_DISTRIBUIDOR[0])
    assert d.get("/retail/api/ventas/canasta").status_code == 403


def test_portal_de_pedidos(panel):
    c = cliente(demo_panel.USUARIO_DISTRIBUIDOR[0])
    r = c.get("/retail/api/panel/pedidos").json()["pedidos"]
    pendientes = [p for p in r if p["estado"] == "enviada"]
    assert pendientes and all(p["lineas"] for p in r)
    assert {p["comercio"] for p in r} <= {n for n, *_ in demo_panel.COMERCIOS} | {demo.EMPRESA}
    p = pendientes[0]
    entrega = (date.today() + timedelta(days=2)).isoformat()
    ok = c.post(f"/retail/api/panel/pedidos/{p['id']}/confirmar", json={"entrega_prometida": entrega, "nota": "Sale en el reparto del jueves"})
    assert ok.status_code == 200 and ok.json()["confirmada_proveedor_at"] and ok.json()["entrega_prometida"] == entrega
    aud = _q("SELECT org_id FROM auditoria WHERE accion='confirmar_proveedor' AND objeto_id=%s", (str(p["id"]),))
    assert aud
    # Una OC a otro proveedor no se puede tocar.
    ajena = _q("""SELECT oc.id FROM ordenes_compra oc JOIN proveedores pr ON pr.id=oc.proveedor_id
                  WHERE pr.razon_social <> %s AND oc.estado='enviada' LIMIT 1""", (demo_panel.DISTRIBUIDOR,))
    if ajena:
        assert c.post(f"/retail/api/panel/pedidos/{ajena[0]['id']}/confirmar", json={}).status_code == 404
    # Una recibida no se confirma.
    recibida = next(x for x in r if x["estado"] == "recibida")
    assert c.post(f"/retail/api/panel/pedidos/{recibida['id']}/confirmar", json={}).status_code == 409


def test_alta_de_distribuidor_solo_la_plataforma(retail_demo):
    esquina = _q("SELECT id FROM organizaciones WHERE nombre='Minimercado La Esquina'")[0]["id"]
    assert cliente("dueno@norte.demo").put(f"/retail/api/plataforma/empresas/{esquina}/distribuidor", json={"marcas": ["Cola Norte"]}).status_code == 403
    admin = cliente("admin@plataforma.demo")
    norte = _q("SELECT id FROM organizaciones WHERE nombre=%s", (demo.EMPRESA,))[0]["id"]
    assert admin.put(f"/retail/api/plataforma/empresas/{norte}/distribuidor", json={"marcas": ["Cola Norte"]}).status_code == 409
    r = admin.put(f"/retail/api/plataforma/empresas/{esquina}/distribuidor", json={"marcas": [" Cola Norte ", "Lima Sol", ""]})
    assert r.status_code == 200 and r.json()["marcas"] == ["Cola Norte", "Lima Sol"]
    assert _q("SELECT tipo FROM organizaciones WHERE id=%s", (esquina,))[0]["tipo"] == "distribuidor"
    assert {f["rol"] for f in _q("SELECT rol FROM usuarios WHERE org_id=%s", (esquina,))} == {"distribuidor"}
