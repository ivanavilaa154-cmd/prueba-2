"""Retail: cuentas reales creadas desde la terminal (administración de la plataforma y dueño de una empresa)."""
from fastapi.testclient import TestClient

from app.main import app
from app.retail import cuentas, db
from app.retail.semilla import CLAVE_DEMO

CLAVE = "Pulpo-Azul-2026"


def _login(email, clave):
    c = TestClient(app)
    return c, c.post("/retail/api/sesion", json={"email": email, "clave": clave}).status_code


def test_admin_y_dueno_de_su_empresa(retail_demo):
    with db.transaccion(superadmin=True) as conn:
        assert cuentas.administrador(conn, "yo@ejemplo.com", "Yo", CLAVE) == "creada"
        org = cuentas.empresa_con_dueno(conn, "Pulpo Azul", "30-11111111-1", "dueno@pulpoazul.com", "Dueño Pulpo", CLAVE)
    admin, st = _login("yo@ejemplo.com", CLAVE)
    assert st == 200
    empresas = {e["nombre"] for e in admin.get("/retail/api/plataforma/empresas").json()}
    assert {"Pulpo Azul", "Autoservicios del Norte"} <= empresas                     # el administrador ve todas

    dueno, st = _login("dueno@pulpoazul.com", CLAVE)
    assert st == 200
    yo = dueno.get("/retail/api/yo").json()
    assert yo["empresa"]["id"] == org and yo["usuario"]["rol"] == "dueno" and "gestionar_conexiones" in yo["permisos"]
    assert dueno.get("/retail/api/plataforma/empresas").status_code == 403           # no ve otras empresas

    with db.transaccion(superadmin=True) as conn:
        assert cuentas.desactivar_demo(conn) >= 5
        try:
            cuentas.empresa_con_dueno(conn, "pulpo azul", None, "otro@x.com", "Otro", CLAVE)
            raise AssertionError("debía rechazar el nombre repetido")
        except ValueError:
            pass
    assert _login("dueno@norte.demo", CLAVE_DEMO)[1] != 200
    assert _login("admin@plataforma.demo", CLAVE_DEMO)[1] != 200
    assert _login("yo@ejemplo.com", CLAVE)[1] == 200


def test_solo_cuentas_reales_borra_la_demo(retail_demo):
    from app.retail import demo_panel
    demo_panel.cargar()
    with db.transaccion(superadmin=True) as conn:
        cuentas.administrador(conn, "yo@ejemplo.com", "Yo", CLAVE)          # una cuenta propia creada antes: no se toca
        otra = cuentas.empresa_con_dueno(conn, "Mi Otra Empresa", None, "otra@ejemplo.com", "Otra", CLAVE)
    r = cuentas.dejar_solo_reales()
    assert set(r["creadas"]) == {cuentas.ADMIN[0], cuentas.PULPO["email"]}
    assert "Autoservicios del Norte" in r["borradas"] and "Distribuidora Andina" in r["borradas"]
    with db.transaccion(superadmin=True) as conn:
        empresas = {o["nombre"] for o in db.filas(conn, "SELECT nombre FROM organizaciones")}
        assert empresas == {"Pulpo Azul", "Mi Otra Empresa"}
        assert not db.filas(conn, "SELECT 1 FROM usuarios WHERE email LIKE '%%.demo'")
        assert not db.filas(conn, "SELECT 1 FROM tickets") and not db.filas(conn, "SELECT 1 FROM productos")
    admin, st = _login(cuentas.ADMIN[0], cuentas.ADMIN[2])
    assert st == 200 and {e["nombre"] for e in admin.get("/retail/api/plataforma/empresas").json()} == {"Pulpo Azul", "Mi Otra Empresa"}
    dueno, st = _login(cuentas.PULPO["email"], cuentas.PULPO["clave"])
    assert st == 200 and dueno.get("/retail/api/yo").json()["empresa"]["nombre"] == "Pulpo Azul"
    assert _login("yo@ejemplo.com", CLAVE)[1] == 200 and otra
    # Idempotente: una clave cambiada no se pisa al volver a arrancar.
    assert dueno.post("/retail/api/yo/clave", json={"actual": cuentas.PULPO["clave"], "nueva": "Otra-clave-2026"}).status_code == 200
    assert cuentas.dejar_solo_reales() == {"creadas": [], "borradas": []}
    assert _login(cuentas.PULPO["email"], "Otra-clave-2026")[1] == 200


def test_mismo_usuario_para_retail_y_panel_erp(retail_demo, monkeypatch):
    monkeypatch.setenv("RETAIL_CUENTAS", "reales")
    with db.transaccion(superadmin=True) as conn:
        cuentas.administrador(conn, *cuentas.ADMIN)
        cuentas.empresa_con_dueno(conn, "Pulpo Azul", None, cuentas.PULPO["email"], cuentas.PULPO["nombre"], cuentas.PULPO["clave"])
    anonimo = TestClient(app)
    r = anonimo.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/retail/ingresar/?volver=/")
    assert anonimo.get("/salud").status_code == 200 and anonimo.get("/salud").json()["cuentas_unificadas"]
    assert anonimo.get("/login", follow_redirects=False).headers["location"].startswith("/retail/ingresar/")
    for email, clave in ((cuentas.ADMIN[0], cuentas.ADMIN[2]), (cuentas.PULPO["email"], cuentas.PULPO["clave"])):
        c, st = _login(email, clave)
        assert st == 200
        assert c.get("/", headers={"accept": "text/html"}, follow_redirects=False).status_code == 200    # el panel ERP abre
        assert c.get("/retail/api/yo").status_code == 200                                              # y Retail también
    # Un rol que no es dueño no entra al panel ERP; al salir se cierra la sesión de los dos lados.
    c, st = _login("compras@norte.demo", CLAVE_DEMO)
    assert st == 200 and c.get("/", headers={"accept": "text/html"}, follow_redirects=False).status_code == 303
    c, _ = _login(cuentas.ADMIN[0], cuentas.ADMIN[2])
    c.get("/salir", follow_redirects=False)
    assert c.get("/retail/api/yo").status_code == 401
