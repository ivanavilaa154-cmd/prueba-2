"""Retail · parte 13: criterios de aceptación de la Fase 1 que no tienen una prueba propia en otro archivo.

El mapa completo criterio → prueba está en docs/retail/aceptacion.md.
"""
from fastapi.testclient import TestClient

from app.main import app
from app.retail import tiempos
from app.retail.semilla import CLAVE_DEMO


def test_todas_las_pantallas_cargan_en_menos_de_3_segundos(retail_demo):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": "dueno@norte.demo", "clave": CLAVE_DEMO}).status_code == 200
    filas = tiempos.medir(c.get)
    assert len(filas) == len(tiempos.PANTALLAS)
    for f in filas:
        assert f["ok"], f


# ------------------------------------------------------------------------------------------- SPEC v2 (sección 17, criterios nuevos)
def _entrar(email):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def test_el_reporte_de_clientes_perdidos_detecta_a_los_de_la_demo(retail_distribuidora):
    perdidos = set(retail_distribuidora["perdidos"])
    assert len(perdidos) >= 3
    filas = {f["razon_social"]: f for f in _entrar("dueno@valle.demo").get("/retail/api/distribuidor/clientes").json()["filas"]}
    no_detectados = [(n, filas[n]["estado"], filas[n]["dias_sin_comprar"]) for n in perdidos if filas[n]["estado"] != "perdido"]
    assert not no_detectados, no_detectados
    assert all(filas[n]["deja_de_facturar_mes"] > 0 for n in perdidos)


def test_una_distribuidora_no_ve_clientes_de_otra_empresa(retail_distribuidora):
    from app.retail import db
    with db.transaccion(superadmin=True) as conn, conn.cursor() as cur:
        norte = db.fila(conn, "SELECT id FROM organizaciones WHERE nombre = 'Autoservicios del Norte'")["id"]
        cur.execute("UPDATE organizaciones SET modos = '{comercio,distribuidor}' WHERE id = %s", (norte,))
        cur.execute("INSERT INTO clientes_b2b (org_id, razon_social, codigo_externo) VALUES (%s, 'Cliente secreto del Norte', 'x:1')", (norte,))
    valle = _entrar("dueno@valle.demo").get("/retail/api/distribuidor/clientes").json()["filas"]
    assert "Cliente secreto del Norte" not in {f["razon_social"] for f in valle}
    norte_ve = _entrar("dueno@norte.demo").get("/retail/api/distribuidor/clientes").json()["filas"]
    assert {f["razon_social"] for f in norte_ve} == {"Cliente secreto del Norte"}
