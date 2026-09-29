"""Retail · 13.5 Privacidad y cumplimiento: política aceptada, acceso a los datos, baja de la empresa, supresión y copias."""
import csv
import io
import subprocess
import zipfile

from fastapi.testclient import TestClient

from app.main import app
from app.retail import db, privacidad
from app.retail.semilla import CLAVE_DEMO


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _q(sql, params=()):
    with db.transaccion(superadmin=True) as conn:
        return db.filas(conn, sql, params)


def test_politica_se_acepta_una_vez_por_version(retail_demo):
    c = cliente()
    assert c.get("/retail/api/privacidad").json()["aceptada"] is False
    assert c.post("/retail/api/privacidad/aceptar").status_code == 200
    r = c.get("/retail/api/privacidad").json()
    assert r["aceptada"] and r["version"] == privacidad.VERSION_POLITICA
    assert _q("SELECT count(*) n FROM auditoria WHERE accion='aceptar' AND objeto='politica_privacidad'")[0]["n"] == 1


def test_exportar_trae_solo_lo_propio_y_sin_secretos(retail_demo):
    c = cliente()
    r = c.get("/retail/api/empresa/exportar")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    nombres = set(z.namelist())
    assert {"organizaciones.csv", "tickets.csv", "productos.csv", "usuarios.csv", "LEEME.txt"} <= nombres
    usuarios = list(csv.DictReader(io.StringIO(z.read("usuarios.csv").decode())))
    assert usuarios and "hash_clave" not in usuarios[0] and "totp_secreto" not in usuarios[0]
    norte = _q("SELECT id FROM organizaciones WHERE nombre='Autoservicios del Norte'")[0]["id"]
    assert {u["org_id"] for u in usuarios} == {str(norte)}
    tickets = sum(1 for _ in csv.DictReader(io.StringIO(z.read("tickets.csv").decode())))
    assert tickets == _q("SELECT count(*) n FROM tickets WHERE org_id=%s", (norte,))[0]["n"]
    # Un comprador no exporta; el dueño de otra empresa exporta solo la suya.
    assert cliente("compras@norte.demo").get("/retail/api/empresa/exportar").status_code == 403
    otra = zipfile.ZipFile(io.BytesIO(cliente("dueno@esquina.demo").get("/retail/api/empresa/exportar").content))
    assert sum(1 for _ in csv.DictReader(io.StringIO(otra.read("tickets.csv").decode()))) == 0


def test_baja_con_plazo_para_arrepentirse(retail_demo):
    c = cliente("dueno@esquina.demo")
    assert c.post("/retail/api/empresa/baja", json={"confirmacion": "otra cosa"}).status_code == 400
    r = c.post("/retail/api/empresa/baja", json={"confirmacion": "minimercado la esquina"})
    assert r.status_code == 200 and r.json()["se_borra"]
    assert c.get("/retail/api/privacidad").json()["baja"]
    assert c.delete("/retail/api/empresa/baja").status_code == 200
    assert c.get("/retail/api/privacidad").json()["baja"] is None
    c.post("/retail/api/empresa/baja", json={"confirmacion": "Minimercado La Esquina"})
    assert privacidad.procesar_bajas() == []                                  # todavía dentro del plazo
    with db.transaccion(superadmin=True) as conn, conn.cursor() as cur:
        cur.execute("UPDATE organizaciones SET baja_solicitada_at = now() - interval '31 days' WHERE nombre='Minimercado La Esquina'")
    borradas = privacidad.procesar_bajas()
    assert len(borradas) == 1
    assert not _q("SELECT 1 FROM organizaciones WHERE nombre='Minimercado La Esquina'")
    assert not _q("SELECT 1 FROM usuarios WHERE email='dueno@esquina.demo'")
    assert _q("SELECT 1 FROM auditoria WHERE accion='borrar' AND objeto='empresa'")         # la auditoría queda
    assert _q("SELECT 1 FROM organizaciones WHERE nombre='Autoservicios del Norte'")          # las demás no se tocan


def test_suprimir_datos_de_un_cliente(retail_demo):
    c = cliente()
    encontrados = c.get("/retail/api/clientes/buscar", params={"q": "Rosa"}).json()
    assert encontrados
    cid = encontrados[0]["id"]
    ventas = _q("SELECT count(*) n FROM cuentas_clientes WHERE cliente_id=%s", (cid,))[0]["n"]
    assert c.post(f"/retail/api/clientes/{cid}/suprimir").status_code == 200
    f = _q("SELECT identificador, nombre, anonimizado_at FROM clientes WHERE id=%s", (cid,))[0]
    assert f["identificador"] is None and f["nombre"] is None and f["anonimizado_at"]
    assert _q("SELECT count(*) n FROM cuentas_clientes WHERE cliente_id=%s", (cid,))[0]["n"] == ventas     # los movimientos quedan
    assert c.post(f"/retail/api/clientes/{cid}/suprimir").status_code == 404
    assert not [x for x in c.get("/retail/api/clientes/buscar", params={"q": "Rosa"}).json() if x["id"] == cid]


def test_copia_de_seguridad_se_puede_restaurar(retail_demo, tmp_path, monkeypatch):
    monkeypatch.setattr(privacidad, "COPIAS_A_GUARDAR", 2)
    archivos = [privacidad.respaldar(tmp_path) for _ in range(3)]
    assert len(privacidad.copias(tmp_path)) == 2 and archivos[-1].exists()
    pg_restore = privacidad._pg_dump().replace("pg_dump", "pg_restore")
    listado = subprocess.run([pg_restore, "--list", str(archivos[-1])], capture_output=True, text=True, check=True).stdout
    assert "TABLE DATA public tickets" in listado and "TABLE DATA public organizaciones" in listado
