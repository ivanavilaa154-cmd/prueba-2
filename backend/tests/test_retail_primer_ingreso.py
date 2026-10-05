"""SPEC v2 · paso 10 (sección 15): primer ingreso guiado de 6 pasos."""
from fastapi.testclient import TestClient

from app.main import app
from app.retail import db
from app.retail.semilla import CLAVE_DEMO


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _sql(sql, params=()):
    with db.transaccion(superadmin=True) as conn, conn.cursor() as cur:
        cur.execute(sql, params)


def test_empresa_nueva_arranca_por_la_guia(retail):
    c = cliente()
    r = c.get("/retail/api/primer-ingreso").json()
    assert [p["paso"] for p in r["pasos"]] == ["datos", "sucursales", "productos", "proveedores", "modelo", "recomendaciones"]
    assert r["listos"] == 0 and r["mostrar"] and r["actual"] == "datos"
    assert c.post("/retail/api/primer-ingreso/datos").status_code == 400                 # se completa solo con los datos
    assert c.post("/retail/api/primer-ingreso/recomendaciones").status_code == 409       # todavía no hay recomendaciones
    assert c.post("/retail/api/primer-ingreso/proveedores").status_code == 409
    r = c.post("/retail/api/primer-ingreso/sucursales").json()
    assert next(p for p in r["pasos"] if p["paso"] == "sucursales")["listo"] and r["listos"] == 1
    r = c.post("/retail/api/primer-ingreso/modelo").json()
    assert r["listos"] == 2 and r["actual"] == "datos" and not r["completo_at"]
    assert cliente("compras@norte.demo").get("/retail/api/primer-ingreso").status_code == 403
    r = c.put("/retail/api/primer-ingreso", json={"omitir": True}).json()
    assert not r["mostrar"] and r["omitido"]


def test_con_datos_se_completa_y_queda_la_fecha(retail_demo):
    c = cliente()
    assert not c.get("/retail/api/primer-ingreso").json()["mostrar"]                    # la demo ya está puesta en marcha
    _sql("UPDATE organizaciones SET primer_ingreso_completo_at = NULL, primer_ingreso = '{}' WHERE nombre = 'Autoservicios del Norte'")
    _sql("UPDATE productos SET estado_mapeo = 'propio' WHERE estado_mapeo = 'sin_mapear'")
    r = c.get("/retail/api/primer-ingreso").json()
    pasos = {p["paso"]: p for p in r["pasos"]}
    assert pasos["datos"]["listo"] and pasos["productos"]["listo"] and r["mostrar"]
    for paso in ("sucursales", "proveedores", "modelo"):
        assert c.post(f"/retail/api/primer-ingreso/{paso}").status_code == 200
    r = c.post("/retail/api/primer-ingreso/recomendaciones").json()
    assert r["listos"] == 6 and r["completo_at"] and not r["mostrar"]
    admin = cliente("admin@plataforma.demo")
    norte = next(e for e in admin.get("/retail/api/plataforma/costo-de-servir").json()["empresas"] if e["nombre"] == "Autoservicios del Norte")
    assert norte["primer_ingreso_completo_at"] and norte["primer_ingreso_confirmados"] == 4
