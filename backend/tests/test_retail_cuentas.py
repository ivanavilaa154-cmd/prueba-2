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
