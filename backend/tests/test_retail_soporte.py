"""SPEC v2 · paso 9 (13.7): precisión medida por empresa y medición de soporte (tiempo de implementación y tickets)."""
from fastapi.testclient import TestClient

from app.main import app
from app.retail import db
from app.retail.semilla import CLAVE_DEMO, SUPERADMIN


def cliente(email):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _q(sql, params=()):
    with db.transaccion(superadmin=True) as conn:
        return db.filas(conn, sql, params)


def test_precision_e_implementacion_se_registran_al_calcular(retail_demo):
    p = _q("""SELECT p.* FROM precision_pronosticos p JOIN organizaciones o ON o.id = p.org_id WHERE o.nombre = 'Autoservicios del Norte'""")
    assert p and p[0]["evaluados"] > 0
    assert 0 < p[0]["wape"] < 2 and 0 < p[0]["mape"] < 5 and 0 <= p[0]["cobertura"] <= 1
    o = _q("SELECT created_at, implementacion_lista_at FROM organizaciones WHERE nombre = 'Autoservicios del Norte'")[0]
    assert o["implementacion_lista_at"] and o["implementacion_lista_at"] >= o["created_at"]
    assert _q("SELECT implementacion_lista_at FROM organizaciones WHERE nombre = 'Minimercado La Esquina'")[0]["implementacion_lista_at"] is None


def test_pedir_ayuda_y_panel_de_la_plataforma(retail_demo):
    dueno = cliente("dueno@norte.demo")
    r = dueno.post("/retail/api/soporte", json={"asunto": "No sé cómo cargar una factura", "tema": "datos"})
    assert r.status_code == 201
    tid = r.json()["id"]
    assert [t["id"] for t in dueno.get("/retail/api/soporte").json()] == [tid]
    assert cliente("dueno@esquina.demo").get("/retail/api/soporte").json() == []           # cada empresa ve solo lo suyo
    assert dueno.get("/retail/api/plataforma/costo-de-servir").status_code == 403

    admin = cliente(SUPERADMIN[0])
    panel = admin.get("/retail/api/plataforma/costo-de-servir").json()
    norte = next(e for e in panel["empresas"] if e["nombre"] == "Autoservicios del Norte")
    assert norte["precision"]["wape"] is not None and norte["dias_implementacion"] is not None and norte["abiertos"] == 1
    assert panel["resumen"]["abiertos"] >= 1 and panel["resumen"]["sin_implementar"] >= 1
    assert any(t["id"] == tid and t["origen"] == "cliente" for t in panel["tickets"])
    assert admin.put(f"/retail/api/plataforma/soporte/{tid}", json={"minutos": 25, "respuesta": "Datos → Leer facturas."}).status_code == 200
    org = norte["id"]
    assert admin.post("/retail/api/plataforma/soporte", json={"org_id": org, "asunto": "Llamada por la conexión", "tema": "conexion",
                                                              "minutos": 35, "resuelto": True}).status_code == 201
    assert admin.put(f"/retail/api/plataforma/empresas/{org}/implementacion", json={"horas": 4.5}).status_code == 200
    norte = next(e for e in admin.get("/retail/api/plataforma/costo-de-servir").json()["empresas"] if e["id"] == org)
    assert norte["abiertos"] == 0 and norte["tickets_90"] == 2 and norte["horas_soporte_90"] == 1.0 and float(norte["implementacion_horas"]) == 4.5
    mio = dueno.get("/retail/api/soporte").json()
    assert next(t for t in mio if t["id"] == tid)["respuesta"] == "Datos → Leer facturas."


def test_el_vendedor_tambien_puede_pedir_ayuda(retail_distribuidora):
    assert cliente("carla@valle.demo").post("/retail/api/soporte", json={"asunto": "No veo un cliente", "tema": "uso"}).status_code == 201
    assert _q("SELECT count(*) n FROM tickets_soporte t JOIN organizaciones o ON o.id = t.org_id WHERE o.nombre = 'Distribuidora del Valle'")[0]["n"] == 4
