"""Centro de pruebas: acceso solo operador/tester, auditoría, incidencias, muestra, pruebas manuales, cuadratura y ver como."""
import json
import sqlite3
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.pruebas import almacen, cuadratura, estado, incidencias, manuales, muestra, revision, sesion, suites

CLAVES = {"CLAVE_U4": "op-secreta", "CLAVE_U5": "test-secreta"}


@pytest.fixture
def claves(monkeypatch):
    for k, v in CLAVES.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SESION_SECRETO", "secreto-de-prueba")


@pytest.fixture
def cliente(base_demo_config, claves):
    from app.main import app
    return TestClient(app)


def _ingresar(c, usuario="u5", clave="test-secreta"):
    return c.post("/pruebas/ingresar", data={"usuario_id": usuario, "clave": clave}, follow_redirects=False)


# --- acceso y auditoría ------------------------------------------------------------------

def test_acceso_solo_operador_y_tester(cliente):
    assert cliente.get("/pruebas/api/estado").status_code == 403                 # sin sesión, ni por API
    r = cliente.get("/pruebas", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/pruebas/ingresar"  # ni por URL
    assert _ingresar(cliente, "u1", "cualquiera").status_code == 401             # el dueño no es operador ni tester
    assert _ingresar(cliente, "u5", "mala").status_code == 401
    falsa = sesion.crear("u1")                                                    # cookie bien firmada pero de otro rol
    cliente.cookies.set(sesion.COOKIE, falsa)
    assert cliente.get("/pruebas/api/estado").status_code == 403
    cliente.cookies.set(sesion.COOKIE, "u5|9999999999|firma-inventada")
    assert cliente.get("/pruebas/api/estado").status_code == 403
    cliente.cookies.clear()
    assert _ingresar(cliente).status_code == 303
    assert cliente.get("/pruebas/api/estado").status_code == 200
    assert cliente.get("/pruebas").status_code == 200
    acciones = [e["accion"] for e in almacen.filas("SELECT accion FROM auditoria ORDER BY id")]
    assert acciones.count("ingreso_fallido") == 2 and "ingreso" in acciones


def test_usuarios_de_pruebas_no_aparecen_en_ver_como_general(cliente):
    roles = {u["rol"] for u in cliente.get("/usuarios").json()}
    assert not roles & {"operador", "tester"}


def test_ver_como_es_solo_lectura_y_auditado(cliente):
    _ingresar(cliente)
    assert cliente.post("/pruebas/api/ver-como", json={"usuario_id": "u2"}).status_code == 200
    e = cliente.get("/ver-como/estado").json()
    assert e["activo"] and e["usuario_id"] == "u2" and "Laura" in e["nombre"]
    r = cliente.post("/actividades/revisar", params={"usuario_id": "u1"})
    assert r.status_code == 403 and "solo lectura" in r.json()["detail"]
    assert cliente.get("/actividades", params={"usuario_id": "u2"}).status_code == 200   # leer sí
    assert cliente.post("/pruebas/api/ver-como/salir").status_code == 200
    assert not cliente.get("/ver-como/estado").json()["activo"]
    auditoria = almacen.filas("SELECT accion, ver_como FROM auditoria WHERE accion LIKE 'ver_como%'")
    assert [a["accion"] for a in auditoria] == ["ver_como_inicio", "ver_como_fin"] and auditoria[0]["ver_como"] == "u2"


# --- incidencias ---------------------------------------------------------------------------

def test_incidencia_de_datos_no_se_cierra_sin_test_ni_definicion(base_demo_config):
    i = incidencias.crear("muestra", "Venta distinta", "Tomás", tipo="datos", metrica="ventas", registro_clave="10")
    with pytest.raises(ValueError, match="test de regresión"):
        incidencias.actualizar(i, "Tomás", estado="resuelta")
    with pytest.raises(ValueError, match="No encuentro"):
        incidencias.actualizar(i, "Tomás", test_regresion="tests/no_existe.py::test_x")
    ok = incidencias.actualizar(i, "Tomás", estado="resuelta", test_regresion="tests/test_tablero.py::test_ventas_contra_sql_directo")
    assert ok["estado"] == "resuelta" and ok["resuelta_por"] == "Tomás"
    j = incidencias.crear("automatico", "Otra", "Tomás", tipo="datos", metrica="ventas")
    r = incidencias.actualizar(j, "Tomás", estado="resuelta", definicion="Odoo resta las notas de crédito del mes en que se emiten.")
    assert r["definicion_id"] and almacen.filas("SELECT * FROM cuadratura_definicion")[0]["descripcion"].startswith("Odoo resta")
    pantalla = incidencias.crear("prueba_manual", "No carga en el celular", "Tomás", tipo="pantalla")
    assert incidencias.actualizar(pantalla, "Tomás", estado="resuelta")["estado"] == "resuelta"   # la regla es para datos


def test_caso_de_regresion_permanente(base_demo_config, tmp_path, monkeypatch):
    monkeypatch.setattr(incidencias, "CASOS_DIR", tmp_path / "casos")
    monkeypatch.setattr(incidencias, "PERFILES_DIR", tmp_path / "perfiles")
    monkeypatch.setattr(incidencias, "test_existe", lambda ruta: bool(ruta))
    i = incidencias.crear("muestra", "Nota de crédito restada dos veces", "Tomás", tipo="datos", metrica="ventas", fuente="odoo")
    with pytest.raises(ValueError, match="causa"):
        incidencias.crear_caso_regresion(i, "Tomás")
    incidencias.actualizar(i, "Tomás", causa="notas_de_credito")
    r = incidencias.crear_caso_regresion(i, "Tomás")
    assert (tmp_path / "casos" / f"INC-{i:05d}.yml").exists() and r["test_regresion"].endswith(f"INC-{i:05d}.yml")
    assert f"INC-{i:05d}" in (tmp_path / "perfiles" / "odoo.yml").read_text()


# --- muestra y pruebas manuales --------------------------------------------------------------

def test_muestra_de_20_y_no_coincide_crea_incidencia(base_demo_config):
    m = muestra.tomar("ventas", "2026-08-01", "2026-08-31", "Tomás", semilla=1)
    assert len(m["registros"]) == 20 and m["aviso"]                     # la demo no tiene sistema de origen
    assert len({r["registro_clave"] for r in m["registros"]}) == 20
    r0 = m["registros"][0]
    assert r0["plataforma"]["total"] == pytest.approx(r0["plataforma"]["sin_impuestos"] + r0["plataforma"]["impuestos"], abs=0.01)
    v = muestra.marcar(r0["id"], "no_coincide", "El total no es el de la factura", "Tomás")
    inc = incidencias.obtener(v["registros"][0]["incidencia_id"])
    assert inc["origen"] == "muestra" and inc["registro_clave"] == r0["registro_clave"] and inc["evidencia"]["plataforma"]
    assert muestra.marcar(m["registros"][1]["id"], "coincide", None, "Tomás")["marcados"] == 2


def test_prueba_manual_fallida_crea_incidencia_con_evidencia(base_demo_config):
    casos = manuales.listar()
    assert len(casos) >= 12 and {"MAN-03", "MAN-08", "MAN-09", "MAN-10"} <= {c["codigo"] for c in casos}
    with pytest.raises(ValueError, match="imagen"):
        manuales.guardar_evidencia("x.exe", "application/octet-stream", b"MZ", "Tomás")
    ev = manuales.guardar_evidencia("captura.png", "image/png", b"\x89PNG....", "Tomás")
    with pytest.raises(ValueError, match="comentario"):
        manuales.ejecutar(casos[0]["id"], "fallido", "Tomás")
    r = manuales.ejecutar(casos[0]["id"], "fallido", "Tomás", "No carga Finanzas", ev["id"])
    inc = incidencias.obtener(r["incidencia_id"])
    assert inc["origen"] == "prueba_manual" and inc["evidencia"]["archivo"]["id"] == ev["id"]
    assert manuales.listar()[0]["ultima"]["estado"] == "fallido"


# --- cuadratura: sello, marcha blanca, diferencias y reconciliación con un Odoo simulado --------------

def _entrada(dia: str, coincide=True):
    fila = {"mes": "2026-08", "equipo": "Ventas", "odoo_sin_impuestos": 1000.0, "plataforma_sin_impuestos": 1000.0 if coincide else 990.0,
            "odoo_con_impuestos": 1220.0, "plataforma_con_impuestos": 1220.0 if coincide else 1207.8, "odoo_lineas": 5, "plataforma_lineas": 5}
    return {"ok": True, "fecha": f"{dia}T09:00:00", "control_ventas": {"disponible": True, "zona": "America/Montevideo", "filas": [fila]}}


def test_sello_y_marcha_blanca(base_demo_config):
    hoy = date(2026, 9, 24)
    assert cuadratura.sello("ventas", "odoo", hoy)["sello"] == "sin_referencia"
    for k in range(15, 0, -1):
        cuadratura.registrar_control(_entrada((hoy - timedelta(days=k)).isoformat(), coincide=(k != 9)))
    assert cuadratura.sello("ventas", "odoo", hoy)["sello"] == "en_revision"          # sin verificación de hoy no hay ✔
    cuadratura.registrar_control(_entrada(hoy.isoformat()))
    assert cuadratura.sello("ventas", "odoo", hoy)["sello"] == "cuadrado"
    assert cuadratura.sello("facturacion", "odoo", hoy)["sello"] == "sin_referencia"
    mb = cuadratura.marcha_blanca()
    assert mb["dias_en_paralelo"] == 16 and mb["racha_sin_diferencias"] == 9 and mb["en_produccion"]
    cuadratura.registrar_control(_entrada(hoy.isoformat(), coincide=False))              # la última del día manda
    assert cuadratura.sello("ventas", "odoo", hoy)["sello"] == "en_revision" and cuadratura.marcha_blanca()["racha_sin_diferencias"] == 0
    ficha = cuadratura.ficha("ventas", "odoo")
    assert ficha["evidencia"][0]["diferencia"] == -10.0 and ficha["descubrimiento"] == "pendiente"


class OdooSimulado:
    """Odoo mínimo: pedidos del mes, uno borrado (no existe) y uno con otro importe."""
    def __init__(self, pedidos):
        self.pedidos = pedidos

    def __call__(self, url, payload):
        p = payload["params"]
        if p["service"] == "common":
            return {"result": 6}
        _db, _uid, _clave, modelo, metodo, args, kwargs = p["args"]
        if metodo == "check_access_rights":
            return {"result": modelo == "sale.order"}
        if metodo == "fields_get":
            return {"result": {c: {"type": "char"} for c in ("name", "date_order", "state", "amount_untaxed", "amount_tax", "currency_rate",
                                                             "write_date", "tz", "id")}}
        if modelo == "res.users":
            return {"result": [{"id": 6, "tz": "America/Montevideo"}]}
        filas = list(self.pedidos.values())
        if metodo == "read":
            return {"result": [f for f in filas if f["id"] in args[0]]}
        for campo, op, valor in [d for d in args[0] if isinstance(d, (list, tuple))]:
            if op == ">=":
                filas = [f for f in filas if str(f.get(campo)) >= valor]
            elif op == "<":
                filas = [f for f in filas if str(f.get(campo)) < valor]
            elif op == "in":
                filas = [f for f in filas if f.get(campo) in valor]
        ini = kwargs.get("offset", 0)
        return {"result": filas[ini:ini + kwargs.get("limit", 10**6)]}


@pytest.fixture
def odoo_simulado(tmp_path, monkeypatch):
    from app import config
    from app.erp import conector, fuente
    from app.integraciones import gestor, odoo
    base = tmp_path / "odoo.db"
    con = sqlite3.connect(base)
    from app.erp import modelo
    con.executescript(modelo.ESQUEMA)
    for i, fecha, neto in ((101, "2026-08-05", 1000.0), (102, "2026-08-06", 500.0), (103, "2026-08-07", 300.0), (104, "2026-08-08", 80.0)):
        con.execute("INSERT INTO ventas (id, tipo, numero, fecha, anulada) VALUES (?,?,?,?,0)", (i, "orden_venta", f"S{i}", fecha))
        con.execute("INSERT INTO ventas_lineas (venta_id, producto_id, cantidad, precio_unitario, impuestos) VALUES (?,?,?,?,?)",
                    (i, 1, 1, neto, neto * 0.22))
    con.commit()
    con.close()
    monkeypatch.setattr(config, "ERP_URL", f"sqlite:///{base}")
    conector.olvidar_conexiones()
    pedidos = {101: {"id": 101, "name": "S101", "date_order": "2026-08-05 15:00:00", "state": "sale", "amount_untaxed": 1000.0, "currency_rate": 1.0,
                     "write_date": "2026-08-05 15:00:00"},
               102: {"id": 102, "name": "S102", "date_order": "2026-08-06 15:00:00", "state": "sale", "amount_untaxed": 520.0, "currency_rate": 1.0,
                     "write_date": "2026-08-06 15:00:00"},
               104: {"id": 104, "name": "S104", "date_order": "2026-08-08 15:00:00", "state": "cancel", "amount_untaxed": 80.0, "currency_rate": 1.0,
                     "write_date": "2026-09-01 10:00:00"},
               105: {"id": 105, "name": "S105", "date_order": "2026-08-09 15:00:00", "state": "sale", "amount_untaxed": 250.0, "currency_rate": 1.0,
                     "write_date": "2026-08-09 15:00:00"}}   # 103 se borró en Odoo
    monkeypatch.setattr(fuente, "actual", lambda: "odoo")
    monkeypatch.setattr(gestor, "config_odoo", lambda con_clave=False: {"clave_guardada": True})
    monkeypatch.setattr(gestor, "cliente_odoo", lambda: odoo.ClienteOdoo("https://odoo.test", "db", "u", "k", transporte=OdooSimulado(pedidos)))
    monkeypatch.setattr(gestor, "_leer_estado", lambda: {"historial": [{"ok": True, "fecha": "2026-09-20T10:00:00"}]})
    return pedidos


def test_por_que_difiere_registro_por_registro(odoo_simulado):
    r = cuadratura.diferencias("2026-08")
    por_id = {d["id"]: d for d in r["diferencias"]}
    assert por_id[102]["tipo"] == "importe_distinto" and por_id[102]["origen"] == 520.0
    assert por_id[103]["tipo"] == "sobra" and "borró" in por_id[103]["causa"]
    assert por_id[104]["tipo"] == "sobra" and "cancel" in por_id[104]["causa"]
    assert por_id[105]["tipo"] == "falta"
    assert r["puente"][0]["importe"] == 1770.0 and r["puente"][-1]["importe"] == 1880.0
    assert r["sin_explicar"] == pytest.approx(0, abs=0.01)      # el puente explica toda la diferencia


def test_registro_borrado_se_detecta_con_su_id(odoo_simulado):
    r = cuadratura.reconciliar_claves(dias=90, hoy=date(2026, 9, 24))
    assert r["borrados"] == [103] and r["faltantes"] == [105]
    assert cuadratura.ultima_reconciliacion()["borrados"] == [103]


# --- suites, revisión y estado general ---------------------------------------------------

def test_suites_leen_junit_y_ruta():
    assert suites._ruta_test("tests.test_tablero::test_x[1]") == "tests/test_tablero.py::test_x"
    assert {s["id"] for s in suites.SUITES} >= {"unitarios", "mapeo", "kpis", "actividades", "gestion", "permisos", "cuadratura"}


def test_suite_corre_en_entorno_de_prueba(base_demo_config, monkeypatch):
    monkeypatch.setattr(suites, "SUITES", [{"id": "cuadratura", "nombre": "Casos de cuadratura", "descripcion": "", "args": ["tests/cuadratura"]}])
    r = suites.correr("cuadratura", "Tomás")
    assert r["estado"] == "aprobado" and r["total"] >= 1
    assert suites.resumen()["suites"][0]["ultima"]["estado"] == "aprobado"


def test_revision_independiente_sin_clave_hace_chequeos_fijos(base_demo_config, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = revision.ejecutar("Tomás")
    titulos = [d["titulo"] for d in r["fijos"]]
    assert "Descubrimiento automático de la definición espejo" in titulos and "Importes con coma flotante en el modelo" in titulos
    assert not r["agente_disponible"] and r["incidencias_nuevas"]
    assert all(i["estado"] == "para_revisar" for i in incidencias.listar(origen="revision"))
    assert not revision.ejecutar("Tomás")["incidencias_nuevas"]      # no se duplican


def test_estado_general_dice_que_falta(base_demo_config):
    e = estado.general(date(2026, 9, 24))
    assert not e["listo"] and len(e["criterios"]) == 6
    assert all(c["falta"] for c in e["criterios"] if not c["ok"])
    assert {c["pantalla"] for c in e["criterios"]} == {"cuadratura", "integridad", "automaticas", "manuales"}


def test_claves_demo_se_agregan_a_un_env_anterior(tmp_path, monkeypatch):
    from app import config
    from app.pruebas import sesion
    (tmp_path / ".env").write_text("ERP_URL=sqlite:///x.db")   # sin salto de línea final, como un .env viejo
    monkeypatch.setattr(config, "BACKEND", tmp_path)
    for k in sesion.CLAVES_DEMO:
        monkeypatch.delenv(k, raising=False)
    assert sesion.asegurar_claves_demo() == ["CLAVE_U4", "CLAVE_U5"]
    texto = (tmp_path / ".env").read_text()
    assert "ERP_URL=sqlite:///x.db\n" in texto and "CLAVE_U5=tester-demo\n" in texto
    assert sesion.verificar_clave("u5", " tester-demo ").rol == "tester"
    assert sesion.asegurar_claves_demo() == []                   # no duplica ni pisa


def test_ingreso_sin_clave_configurada_lo_explica(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.delenv("CLAVE_U5", raising=False)
    r = TestClient(app).post("/pruebas/ingresar", data={"usuario_id": "u5", "clave": "tester-demo"}, follow_redirects=False)
    assert r.status_code == 401 and "CLAVE_U5" in r.text
