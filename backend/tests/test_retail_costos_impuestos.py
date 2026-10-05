"""SPEC v2 · costos de reposición e histórico, impuestos y descuentos de proveedor (sección 4 y criterios de la sección 17)."""
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.retail import api_ingesta, db, motor
from app.retail import calculos as C
from app.retail.semilla import CLAVE_DEMO


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def _producto():
    return _q("""SELECT p.id, p.categoria_id, pp.costo, pp.proveedor_id,
                        (SELECT precio FROM precios x WHERE x.producto_id = p.id AND x.ubicacion_id IS NULL AND x.canal_id IS NULL
                         ORDER BY desde DESC LIMIT 1) precio
                 FROM productos p JOIN producto_proveedores pp ON pp.producto_id = p.id AND pp.principal
                 WHERE pp.costo > 0 ORDER BY p.id LIMIT 1""")[0]


def _item(c, pid):
    items = c.get("/retail/api/precios/remarcacion", params={"filtro": "todos"}).json()["items"]
    return next(i for i in items if i["id"] == pid)


def test_margen_con_costo_de_reposicion_neto_de_impuestos(retail_demo, monkeypatch):
    monkeypatch.setattr(api_ingesta, "recalcular_en_segundo_plano", lambda org, desde=None: None)
    c = cliente()
    p = _producto()
    # Costos cargados sin IVA (responsable inscripto), producto con IVA 10,5 % y un 10 % de descuento del proveedor.
    assert c.put("/retail/api/costos/config", json={"costos_con_iva": False}).status_code == 200
    assert c.post("/retail/api/costos/impuestos", json={"producto_id": p["id"], "iva": "0.105"}).status_code == 200
    assert c.post("/retail/api/costos/descuentos", json={"proveedor_id": p["proveedor_id"], "producto_id": p["id"],
                                                          "tipo": "porcentaje", "porcentaje": "0.10"}).status_code == 200
    motor.recalcular(1)
    costo_rep = Decimal(p["costo"]) * Decimal("0.9")
    cp = _q("SELECT costo_reposicion, costo_historico, descuento_aplicado FROM costos_producto WHERE producto_id=%s", (p["id"],))[0]
    assert abs(cp["costo_reposicion"] - costo_rep) < Decimal("0.001") and cp["descuento_aplicado"] == Decimal("0.1")
    assert cp["costo_historico"] is not None                  # la demo tiene recepciones con costo
    item = _item(c, p["id"])
    esperado = (Decimal(p["precio"]) / Decimal("1.105") - costo_rep) / (Decimal(p["precio"]) / Decimal("1.105"))
    assert abs(Decimal(item["margen_actual"]) - esperado) < Decimal("0.0001")
    assert Decimal(item["iva"]) == Decimal("0.105")
    # La ganancia de los agregados también es neta: facturación sin IVA − costo.
    a = _q("SELECT sum(facturacion) f, sum(facturacion_neta) fn, sum(costo) co, sum(ganancia) g FROM agg_producto_ubicacion_dia WHERE producto_id=%s",
           (p["id"],))[0]
    assert abs(a["fn"] - a["f"] / Decimal("1.105")) < 1 and abs(a["g"] - (a["fn"] - a["co"])) < 1


def test_costos_cargados_con_iva_no_cambian_el_margen(retail_demo):
    """La demo carga los costos con IVA: precio y costo pierden el mismo IVA y el margen queda igual que el bruto."""
    c = cliente()
    p = _producto()
    item = _item(c, p["id"])
    assert abs(Decimal(item["margen_actual"]) - C.margen(Decimal(p["precio"]), Decimal(p["costo"]))) < Decimal("0.0001")


def test_validaciones_y_permisos(retail_demo, monkeypatch):
    monkeypatch.setattr(api_ingesta, "recalcular_en_segundo_plano", lambda org, desde=None: None)
    c = cliente()
    p = _producto()
    assert c.post("/retail/api/costos/impuestos", json={"producto_id": p["id"], "iva": "0.19"}).status_code == 400
    assert c.post("/retail/api/costos/impuestos", json={"iva": "0.21"}).status_code == 400
    assert c.post("/retail/api/costos/descuentos", json={"proveedor_id": p["proveedor_id"], "tipo": "bonificacion"}).status_code == 400
    r = c.post("/retail/api/costos/conversiones", json={"producto_id": p["id"], "unidad": "Cajas", "factor": "24"})
    assert r.status_code == 200 and r.json()["unidad"] == "caja"
    assert c.post("/retail/api/costos/conversiones", json={"producto_id": p["id"], "unidad": "unidad", "factor": "1"}).status_code == 400
    assert cliente("encargado.norte@norte.demo").put("/retail/api/costos/config", json={"costos_con_iva": True}).status_code == 403
