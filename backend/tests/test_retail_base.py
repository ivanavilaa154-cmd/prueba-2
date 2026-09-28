"""Retail · parte 1: ingreso, roles, aislamiento por empresa y sucursal (RLS), límites y auditoría.

Criterio de aceptación (sección 17): "Un encargado no ve sucursales no asignadas; un usuario no ve datos
de otra empresa". Se prueba por la API y también con SQL directo contra la base, para que el aislamiento
no dependa de que cada ruta filtre bien.
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.retail import db, permisos, seguridad
from app.retail.semilla import CLAVE_DEMO


def cliente(email: str | None = None, clave: str = CLAVE_DEMO) -> TestClient:
    c = TestClient(app)
    if email:
        r = c.post("/retail/api/sesion", json={"email": email, "clave": clave})
        assert r.status_code == 200, r.text
    return c


def ids_ubicaciones(c: TestClient) -> set[str]:
    return {u["nombre"] for u in c.get("/retail/api/ubicaciones").json()}


def test_la_app_no_saltea_rls(retail):
    with db.conectar() as conn:
        rol = db.fila(conn, "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        forzadas = db.filas(conn, "SELECT relname FROM pg_class WHERE relkind='r' AND relrowsecurity AND relforcerowsecurity")
    assert rol == {"rolsuper": False, "rolbypassrls": False}
    assert {"organizaciones", "ubicaciones", "canales", "plataformas", "usuarios", "usuario_ubicaciones",
            "limites_aprobacion", "auditoria"} <= {f["relname"] for f in forzadas}


def test_sin_contexto_la_base_no_devuelve_nada(retail):
    with db.transaccion() as conn:
        for tabla in ("organizaciones", "ubicaciones", "usuarios", "canales", "auditoria", "limites_aprobacion"):
            assert db.filas(conn, f"SELECT * FROM {tabla}") == [], tabla


def test_ingreso_y_datos_del_usuario(retail):
    c = cliente("dueno@norte.demo")
    yo = c.get("/retail/api/yo").json()
    assert yo["usuario"]["rol"] == "dueno" and yo["empresa"]["nombre"] == "Autoservicios del Norte"
    assert yo["empresa"]["zona_horaria"] == "America/Argentina/Buenos_Aires" and yo["empresa"]["moneda"] == "ARS"
    assert len(yo["ubicaciones"]) == 4
    assert [x["codigo"] for x in yo["canales"]] == ["fisico"]          # canales presentes; solo física activa
    assert "gestionar_usuarios" in yo["permisos"]
    assert "hash_clave" not in str(yo)


def test_clave_incorrecta_email_inexistente_y_bloqueo(retail):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": "nadie@x.demo", "clave": "x"}).status_code == 401
    for _ in range(5):
        r = c.post("/retail/api/sesion", json={"email": "compras@norte.demo", "clave": "mala-clave-1"})
        assert r.status_code == 401
    r = c.post("/retail/api/sesion", json={"email": "compras@norte.demo", "clave": CLAVE_DEMO})
    assert r.status_code == 423 and "minutos" in r.json()["detail"]
    dueno = cliente("dueno@norte.demo")
    acciones = [a["accion"] for a in dueno.get("/retail/api/auditoria").json()]
    assert acciones.count("ingreso_fallido") == 5


def test_sin_sesion_o_cookie_falsa(retail):
    c = TestClient(app)
    assert c.get("/retail/api/yo").status_code == 401
    c.cookies.set("retail_sesion", "inventada")
    assert c.get("/retail/api/yo").status_code == 401


def test_salir_revoca_la_sesion(retail):
    c = cliente("dueno@norte.demo")
    token = c.cookies.get("retail_sesion")
    assert c.delete("/retail/api/sesion").status_code == 200
    otro = TestClient(app)
    otro.cookies.set("retail_sesion", token)
    assert otro.get("/retail/api/yo").status_code == 401


def test_encargado_solo_ve_sus_sucursales(retail):
    c = cliente("encargado.norte@norte.demo")
    yo = c.get("/retail/api/yo").json()
    assert [u["nombre"] for u in yo["ubicaciones"]] == ["Salta Norte"]
    assert ids_ubicaciones(c) == {"Salta Norte"}
    # Por SQL directo con su contexto: la base tampoco le devuelve las otras.
    dueno = cliente("dueno@norte.demo")
    todas = {u["nombre"]: u["id"] for u in dueno.get("/retail/api/ubicaciones").json()}
    from app.retail import sesiones
    s = {"usuario_id": yo["usuario"]["id"], "org_activa": None}
    ctx = sesiones.contexto_de_sesion(s)
    with db.transaccion(ctx) as conn:
        assert [f["nombre"] for f in db.filas(conn, "SELECT nombre FROM ubicaciones")] == ["Salta Norte"]
        assert db.filas(conn, "SELECT * FROM ubicaciones WHERE id=%s", (todas["Salta Centro"],)) == []
        with conn.cursor() as cur:
            cur.execute("UPDATE ubicaciones SET nombre='x' WHERE id=%s", (todas["Salta Centro"],))
            assert cur.rowcount == 0
    # Y no puede administrar
    assert c.put(f"/retail/api/ubicaciones/{todas['Salta Norte']}", json={"nombre": "Otra"}).status_code == 403
    assert c.get("/retail/api/usuarios").status_code == 403
    assert c.get("/retail/api/auditoria").status_code == 403


def test_cajero_y_comprador(retail):
    assert ids_ubicaciones(cliente("caja.centro@norte.demo")) == {"Salta Centro"}
    comprador = cliente("compras@norte.demo")
    assert len(ids_ubicaciones(comprador)) == 4
    assert comprador.put("/retail/api/empresa", json={"nombre": "Otra empresa"}).status_code == 403


def test_una_empresa_no_ve_a_otra(retail):
    norte, esquina = cliente("dueno@norte.demo"), cliente("dueno@esquina.demo")
    ubic_norte = norte.get("/retail/api/ubicaciones").json()
    assert ids_ubicaciones(esquina) == {"La Esquina — Yerba Buena"}
    assert {u["email"] for u in esquina.get("/retail/api/usuarios").json()["usuarios"]} == {"dueno@esquina.demo"}
    ajena = ubic_norte[0]["id"]
    r = esquina.put(f"/retail/api/ubicaciones/{ajena}", json={"nombre": "Robada", "tipo": "venta"})
    assert r.status_code == 404
    usuario_ajeno = norte.get("/retail/api/usuarios").json()["usuarios"][0]["id"]
    assert esquina.put(f"/retail/api/usuarios/{usuario_ajeno}", json={"nombre": "Intruso", "rol": "dueno"}).status_code == 404
    assert esquina.post(f"/retail/api/usuarios/{usuario_ajeno}/clave").status_code == 404
    assert all(a["org_id"] == esquina.get("/retail/api/yo").json()["empresa"]["id"] for a in esquina.get("/retail/api/auditoria").json())
    # Con SQL directo: insertar una fila en otra empresa lo rechaza la política RLS.
    import psycopg
    org_esquina = esquina.get("/retail/api/yo").json()["empresa"]["id"]
    org_norte = norte.get("/retail/api/yo").json()["empresa"]["id"]
    ctx = db.Contexto(usuario_id=0, org_id=org_esquina, rol="dueno", todas_ubicaciones=True)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaccion(ctx) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO ubicaciones (org_id, nombre) VALUES (%s, 'Intrusa')", (org_norte,))
    with db.transaccion(ctx) as conn:
        assert {f["org_id"] for f in db.filas(conn, "SELECT org_id FROM usuarios")} == {org_esquina}
        assert db.filas(conn, "SELECT * FROM organizaciones WHERE id=%s", (org_norte,)) == []


def test_limites_de_aprobacion(retail):
    norte = cliente("dueno@norte.demo")
    usuarios = {u["email"]: u for u in norte.get("/retail/api/usuarios").json()["usuarios"]}
    from app.retail import sesiones

    def ctx_de(email):
        return sesiones.contexto_de_sesion({"usuario_id": usuarios[email]["id"], "org_activa": None})

    comprador, encargado, cajero, dueno = (ctx_de(e) for e in ("compras@norte.demo", "encargado.norte@norte.demo",
                                                                "caja.centro@norte.demo", "dueno@norte.demo"))
    with db.transaccion(comprador) as conn:
        assert permisos.limite_aprobacion(conn, comprador, "orden_compra") == Decimal("500000.00")
        assert permisos.puede_aprobar(conn, comprador, "orden_compra", Decimal("500000.00"))
        assert not permisos.puede_aprobar(conn, comprador, "orden_compra", Decimal("500000.01"))
        assert not permisos.puede_aprobar(conn, comprador, "transferencia", Decimal("1"))   # no es su permiso
    with db.transaccion(dueno) as conn:
        assert permisos.puede_aprobar(conn, dueno, "orden_compra", Decimal("99999999"))
    with db.transaccion(encargado) as conn:
        assert permisos.puede_aprobar(conn, encargado, "transferencia", Decimal("300000"))
        assert not permisos.puede_aprobar(conn, encargado, "orden_compra", Decimal("1"))
    with db.transaccion(cajero) as conn:
        assert permisos.limite_aprobacion(conn, cajero, "transferencia") == Decimal("0")
    # Un límite propio del usuario pisa el de su rol; los montos viajan como texto, nunca float.
    r = norte.put("/retail/api/limites", json={"tipo_documento": "orden_compra", "usuario_id": usuarios["compras@norte.demo"]["id"],
                                               "monto_maximo": "750000.5"})
    assert r.status_code == 200 and r.json()["monto_maximo"] == "750000.50"
    with db.transaccion(comprador) as conn:
        assert permisos.puede_aprobar(conn, comprador, "orden_compra", Decimal("750000.50"))
    assert norte.put("/retail/api/limites", json={"tipo_documento": "orden_compra", "rol": "comprador", "monto_maximo": "-1"}).status_code == 400
    assert norte.put("/retail/api/limites", json={"tipo_documento": "orden_compra", "rol": "comprador", "monto_maximo": "NaN"}).status_code == 400


def test_alta_de_usuario_con_clave_temporal(retail):
    norte = cliente("dueno@norte.demo")
    ubic = {u["nombre"]: u["id"] for u in norte.get("/retail/api/ubicaciones").json()}
    sin_sucursal = norte.post("/retail/api/usuarios", json={"email": "nuevo@norte.demo", "nombre": "Nuevo", "rol": "encargado"})
    assert sin_sucursal.status_code == 400
    r = norte.post("/retail/api/usuarios", json={"email": "Nuevo@Norte.demo", "nombre": "Nuevo", "rol": "encargado",
                                                 "ubicaciones": [ubic["San Salvador de Jujuy"]]})
    assert r.status_code == 201
    clave = r.json()["clave_temporal"]
    nuevo = cliente("nuevo@norte.demo", clave)
    assert ids_ubicaciones(nuevo) == {"San Salvador de Jujuy"}
    repetido = norte.post("/retail/api/usuarios", json={"email": "nuevo@norte.demo", "nombre": "Otro", "rol": "cajero",
                                                        "ubicaciones": [ubic["Salta Centro"]]})
    assert repetido.status_code == 400
    # Blanquear la clave cierra sus sesiones abiertas
    assert norte.post(f"/retail/api/usuarios/{r.json()['usuario']['id']}/clave").status_code == 200
    assert nuevo.get("/retail/api/yo").status_code == 401


def test_siempre_queda_un_dueno(retail):
    norte = cliente("dueno@norte.demo")
    dueno = next(u for u in norte.get("/retail/api/usuarios").json()["usuarios"] if u["rol"] == "dueno")
    r = norte.put(f"/retail/api/usuarios/{dueno['id']}", json={"nombre": dueno["nombre"], "rol": "comprador"})
    assert r.status_code == 400 and "dueño" in r.json()["detail"]


def test_segundo_factor(retail):
    c = cliente("compras@norte.demo")
    secreto = c.post("/retail/api/yo/segundo-factor").json()["secreto"]
    assert c.put("/retail/api/yo/segundo-factor", json={"secreto": secreto, "codigo": "000000"}).status_code == 400
    assert c.put("/retail/api/yo/segundo-factor", json={"secreto": secreto, "codigo": seguridad.codigo_totp(secreto)}).status_code == 200
    nuevo = TestClient(app)
    r = nuevo.post("/retail/api/sesion", json={"email": "compras@norte.demo", "clave": CLAVE_DEMO})
    assert r.json() == {"requiere_segundo_factor": True}
    assert nuevo.get("/retail/api/yo").status_code == 401
    assert nuevo.post("/retail/api/sesion/segundo-factor", json={"codigo": "123456"}).status_code == 401
    assert nuevo.post("/retail/api/sesion/segundo-factor", json={"codigo": seguridad.codigo_totp(secreto)}).status_code == 200
    assert nuevo.get("/retail/api/yo").json()["usuario"]["segundo_factor"] is True


def test_cambio_de_clave(retail):
    c = cliente("caja.centro@norte.demo")
    assert c.post("/retail/api/yo/clave", json={"actual": CLAVE_DEMO, "nueva": "corta"}).status_code == 400
    assert c.post("/retail/api/yo/clave", json={"actual": "otra", "nueva": "nueva-clave-99"}).status_code == 400
    assert c.post("/retail/api/yo/clave", json={"actual": CLAVE_DEMO, "nueva": "nueva-clave-99"}).status_code == 200
    cliente("caja.centro@norte.demo", "nueva-clave-99")


def test_empresa_configuracion_y_auditoria(retail):
    norte = cliente("dueno@norte.demo")
    empresa = norte.get("/retail/api/empresa").json()
    cambio = {**{k: empresa[k] for k in ("nombre", "cuit", "zona_horaria", "moneda")},
              "modelo_abastecimiento": "centralizado", "consentimiento_datos": True}
    r = norte.put("/retail/api/empresa", json=cambio)
    assert r.status_code == 200 and r.json()["modelo_abastecimiento"] == "centralizado" and r.json()["consentimiento_fecha"]
    assert norte.put("/retail/api/empresa", json={**cambio, "zona_horaria": "Marte/Olympus"}).status_code == 400
    ultima = norte.get("/retail/api/auditoria?objeto=empresa").json()[0]
    assert ultima["accion"] == "modificar" and ultima["usuario"] == "Marta Quispe"
    assert ultima["detalle"]["modelo_abastecimiento"] == ["mixto", "centralizado"]
    canal = next(c for c in norte.get("/retail/api/canales").json()["canales"] if c["codigo"] == "ecommerce")
    assert norte.put(f"/retail/api/canales/{canal['id']}", json={"activo": True}).status_code == 200
    assert "ecommerce" in [c["codigo"] for c in norte.get("/retail/api/yo").json()["canales"]]


def test_superadmin(retail):
    admin = cliente("admin@plataforma.demo")
    assert admin.get("/retail/api/yo").json()["usuario"]["es_superadmin"] is True
    empresas = admin.get("/retail/api/plataforma/empresas").json()
    assert {e["nombre"] for e in empresas} == {"Autoservicios del Norte", "Minimercado La Esquina"}
    r = admin.post("/retail/api/plataforma/empresas", json={"nombre": "Súper Tafí", "email_dueno": "dueno@tafi.demo",
                                                            "nombre_dueno": "Ana Tafí"})
    assert r.status_code == 201
    nueva = r.json()["empresa"]["id"]
    assert admin.get("/retail/api/ubicaciones").status_code == 200 and admin.get("/retail/api/ubicaciones").json() == []
    assert admin.post("/retail/api/plataforma/entrar", json={"org_id": nueva}).status_code == 200
    assert admin.get("/retail/api/empresa").json()["nombre"] == "Súper Tafí"
    dueno_tafi = cliente("dueno@tafi.demo", r.json()["clave_temporal_dueno"])
    assert dueno_tafi.get("/retail/api/yo").json()["empresa"]["nombre"] == "Súper Tafí"
    assert cliente("dueno@norte.demo").get("/retail/api/plataforma/empresas").status_code == 403


def test_sin_base_configurada_lo_explica(monkeypatch):
    monkeypatch.delenv("RETAIL_DB_URL", raising=False)
    r = TestClient(app).post("/retail/api/sesion", json={"email": "a@b.c", "clave": "x"})
    assert r.status_code == 503 and "RETAIL_DB_URL" in r.json()["detail"]


def test_totp_rfc6238():
    # Vector de prueba del RFC 6238 (SHA1, secreto "12345678901234567890", T=59 s → 94287082, 6 dígitos: 287082)
    import base64
    secreto = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert seguridad.codigo_totp(secreto, 59) == "287082"
    assert seguridad.verificar_totp(secreto, "287082", 59 + 25)
