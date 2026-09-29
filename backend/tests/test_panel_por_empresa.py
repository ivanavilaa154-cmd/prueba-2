"""Panel ERP por empresa (regla 8): cada empresa ve solo sus datos, sus tareas y su conexión de Odoo, que es la misma de Retail."""
import shutil
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import empresas
from app.integraciones import odoo
from app.main import app
from app.retail import cuentas, db, odoo_pos
from app.retail.motor import contexto_sistema
from test_integraciones import OdooFalso

CLAVE = "Clave-de-prueba-2026"


def _login(email, clave=CLAVE):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": clave}).status_code == 200
    return c


@pytest.fixture
def dos_empresas(retail_demo, base_demo, tmp_path, monkeypatch):
    monkeypatch.setenv("RETAIL_CUENTAS", "reales")
    monkeypatch.setattr(empresas, "CARPETA", tmp_path / "empresas")
    with db.transaccion(superadmin=True) as conn:
        cuentas.administrador(conn, "admin@plataforma.test", "Administración", CLAVE)
        a = cuentas.empresa_con_dueno(conn, "Pulpo Azul", None, "dueno@pulpo.test", "Dueña Pulpo", CLAVE)
        b = cuentas.empresa_con_dueno(conn, "Otra Empresa", None, "dueno@otra.test", "Dueño Otra", CLAVE)
    # La empresa A ya sincronizó su Odoo: su base es la demo del panel ERP.
    shutil.copy(base_demo.replace("sqlite:///", ""), empresas.carpeta(a) / "erp.db")
    return a, b


def test_cada_dueno_ve_solo_su_empresa(dos_empresas):
    a, b = dos_empresas
    pulpo, otra = _login("dueno@pulpo.test"), _login("dueno@otra.test")
    s = pulpo.get("/salud").json()
    assert s["empresa"] == "Pulpo Azul" and s["org_id"] == a and s["con_datos"] and not s["con_odoo"]
    assert pulpo.get("/usuarios").json()[0] == {"id": "yo", "nombre": "Dueña Pulpo", "rol": "dueno"}
    t = pulpo.get("/tablero", params={"usuario_id": "yo"}).json()
    assert "kpis" in t["ventas"]
    assert pulpo.get("/distribucion", params={"usuario_id": "yo"}).json()["grupos"]
    # Los usuarios de la demostración (roles.yaml) no existen en una empresa.
    assert pulpo.get("/tablero", params={"usuario_id": "u1"}).status_code == 403
    # La otra empresa no ve nada de Pulpo Azul: su panel está vacío y dice que conecte Odoo.
    s = otra.get("/salud").json()
    assert s["empresa"] == "Otra Empresa" and not s["con_datos"] and not s["con_odoo"]
    assert otra.get("/tablero", params={"usuario_id": "yo"}).json()["ventas"].get("sin_datos")
    assert otra.post("/fuente", json={"fuente": "demo"}).status_code == 400
    assert not (empresas.carpeta(b) / "erp.db").read_bytes() == (empresas.carpeta(a) / "erp.db").read_bytes()


def test_tareas_y_objetivos_separados_por_empresa(dos_empresas):
    a, b = dos_empresas
    pulpo, otra = _login("dueno@pulpo.test"), _login("dueno@otra.test")
    assert pulpo.post("/actividades/revisar", params={"usuario_id": "yo"}).status_code == 200
    assert (empresas.carpeta(a) / "actividades.db").exists()
    tareas_a = pulpo.get("/actividades", params={"usuario_id": "yo"}).json()
    tareas_b = otra.get("/actividades", params={"usuario_id": "yo"}).json()
    assert tareas_a["abiertas"] and not tareas_b["abiertas"]


def test_la_administracion_elige_la_empresa(dos_empresas):
    a, _ = dos_empresas
    admin = _login("admin@plataforma.test")
    assert admin.get("/salud").json()["org_id"] is None                  # sin empresa elegida: la demostración
    assert admin.post("/retail/api/plataforma/entrar", json={"org_id": a}).status_code == 200
    s = admin.get("/salud").json()
    assert s["org_id"] == a and s["empresa"] == "Pulpo Azul" and s["con_datos"]
    # El centro de pruebas es solo para la administración.
    assert _login("dueno@pulpo.test").get("/pruebas/api/estado").status_code == 403


def test_la_conexion_de_retail_alimenta_el_panel_erp(dos_empresas, monkeypatch):
    _, b = dos_empresas
    ctx = contexto_sistema(b)
    with db.transaccion(ctx) as conn:
        odoo_pos.guardar(conn, ctx, {"url": "https://odoo.test", "base": "empresa", "usuario": "integracion@empresa.com",
                                     "api_key": "secreta"}, {})
    monkeypatch.setattr(odoo, "_http", OdooFalso())
    otra = _login("dueno@otra.test")
    s = otra.get("/salud").json()
    assert s["con_odoo"] and not s["con_datos"]
    i = otra.get("/integraciones").json()["odoo"]
    assert i["config"]["por_empresa"] and i["config"]["clave_guardada"] and i["config"]["url"] == "https://odoo.test"
    assert "secreta" not in otra.get("/integraciones").text                 # la clave nunca sale del servidor
    entrada = empresas.sincronizar(b)
    assert entrada["ok"], entrada
    con = sqlite3.connect(empresas.carpeta(b) / "erp.db")
    assert con.execute("SELECT COUNT(*) FROM ventas").fetchone()[0] > 0
    con.close()
    assert otra.get("/salud").json()["con_datos"]
    assert otra.get("/integraciones").json()["odoo"]["ultima_ok"]["ok"]
    # Una clave equivocada no borra lo ya sincronizado.
    monkeypatch.setattr(odoo, "_http", OdooFalso(clave="cambiada"))
    assert not empresas.sincronizar(b)["ok"] and otra.get("/salud").json()["con_datos"]


def test_exportar_y_baja_incluyen_el_panel_erp(dos_empresas):
    import io
    import zipfile
    from app.retail import privacidad
    a, _ = dos_empresas
    with db.transaccion(superadmin=True) as conn:
        z = zipfile.ZipFile(io.BytesIO(privacidad.exportar(conn, a)))
    assert "panel_erp/erp.db" in z.namelist()
    with db.transaccion(superadmin=True) as conn, conn.cursor() as cur:
        cur.execute("UPDATE organizaciones SET baja_solicitada_at = now() - interval '31 days' WHERE id=%s", (a,))
    assert a in privacidad.procesar_bajas()
    assert not (empresas.CARPETA / str(a)).exists()
