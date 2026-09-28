"""Retail · parte 12: alertas con impacto en pesos, explicación y acción; dedupe; resumen diario; emails."""
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.retail import alertas, api_avisos, db, demo, emails, motor
from app.retail.semilla import CLAVE_DEMO

HOY = date(2026, 9, 24)


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def test_cada_alerta_tiene_impacto_explicacion_y_accion(retail_demo):
    """Criterio: cada alerta muestra impacto en pesos, explicación y acción."""
    todas = _q("SELECT * FROM alertas")
    assert len(todas) > 5
    tipos = {a["tipo"] for a in todas}
    assert {"quiebre", "stock_fantasma", "transferencia", "aumento_proveedor", "caja"} <= tipos
    for a in todas:
        assert a["impacto"] is not None and a["impacto"] >= 0 and a["tipo_impacto"] in ("perdida", "en_riesgo", "recuperable")
        assert len(a["explicacion"]) > 20 and a["accion"].get("etiqueta") and a["accion"].get("tipo")


def test_dedupe_y_resolucion_automatica(retail_demo):
    antes = _q("SELECT count(*) c FROM alertas WHERE estado IN ('nueva','vista','escalada')")[0]["c"]
    r = alertas.generar(1, HOY)
    assert r["nuevas"] == 0 and r["actualizadas"] > 0
    assert _q("SELECT count(*) c FROM alertas WHERE estado IN ('nueva','vista','escalada')")[0]["c"] == antes
    # Si la condición desaparece (se aprueban las transferencias), su aviso se resuelve solo
    with db.transaccion(motor.contexto_sistema(1)) as conn, conn.cursor() as cur:
        cur.execute("UPDATE transferencias SET estado='aprobada' WHERE estado='sugerida'")
    alertas.generar(1, HOY)
    # El aviso «aprobar» se cerró solo y apareció el siguiente paso: «preparar y enviar».
    assert _q("SELECT count(*) c FROM alertas WHERE clave_dedupe LIKE 'transferencia:%%' AND estado IN ('nueva','vista')")[0]["c"] == 0
    assert _q("SELECT count(*) c FROM alertas WHERE clave_dedupe LIKE 'transferencia:%%' AND estado='resuelta' AND datos->>'automatica'='true'")[0]["c"] > 0
    assert _q("SELECT count(*) c FROM alertas WHERE clave_dedupe LIKE 'transferencia_enviar:%%' AND estado='nueva'")[0]["c"] > 0


def test_stock_fantasma_del_caso_conocido(retail_demo):
    caso = demo.CASOS["stock_fantasma"]
    pid = _q("SELECT id FROM productos WHERE codigo_interno=%s", (caso["producto"],))[0]["id"]
    a = _q("""SELECT a.* FROM alertas a JOIN ubicaciones u ON u.id=a.ubicacion_id WHERE a.tipo='stock_fantasma' AND u.nombre=%s""", (caso["ubicacion"],))
    assert a and pid in a[0]["datos"]["productos"] and a[0]["accion"]["destino"].endswith("#recuento")


def test_bandeja_por_rol_y_sucursal(retail_demo):
    dueno = cliente().get("/retail/api/avisos").json()
    enc = cliente("encargado.norte@norte.demo").get("/retail/api/avisos").json()
    comp = cliente("compras@norte.demo").get("/retail/api/avisos").json()
    assert len(dueno["avisos"]) > len(enc["avisos"])
    salta_norte = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Norte'")[0]["id"]
    assert all(a["ubicacion_id"] == salta_norte for a in enc["avisos"])
    assert all("encargado" in a["destinatarios"] for a in enc["avisos"])
    assert not any(a["tipo"] == "caja" for a in comp["avisos"])


def test_descartar_pide_motivo_y_queda_auditado(retail_demo):
    c = cliente()
    aviso = c.get("/retail/api/avisos").json()["avisos"][0]
    assert c.put(f"/retail/api/avisos/{aviso['id']}", json={"estado": "descartada"}).status_code == 400
    assert c.put(f"/retail/api/avisos/{aviso['id']}", json={"estado": "descartada", "motivo": "Ya lo resolví por teléfono"}).status_code == 200
    assert _q("SELECT estado FROM alertas WHERE id=%s", (aviso["id"],))[0]["estado"] == "descartada"


def test_inicio_y_resumen_diario(retail_demo, tmp_path, monkeypatch):
    monkeypatch.setattr(emails, "CARPETA", tmp_path)
    r = cliente().get("/retail/api/inicio").json()
    assert Decimal(r["ventas_ayer"]) > 0 and len(r["avisos"]) == 3 and r["acciones"]
    cajero = cliente("caja.centro@norte.demo").get("/retail/api/inicio").json()
    assert cajero["ganancia_ayer"] is None and cajero["plata_parada"] is None
    dueno_id = _q("SELECT id, hora_resumen FROM usuarios WHERE email='dueno@norte.demo'")[0]
    n = api_avisos.enviar_resumenes(1, dueno_id["hora_resumen"], HOY)
    assert n >= 1 and list(tmp_path.glob("*resumen_diario.html"))
    assert api_avisos.enviar_resumenes(1, dueno_id["hora_resumen"], HOY) == 0      # una vez por día


def test_urgentes_por_email(retail_demo, tmp_path, monkeypatch):
    monkeypatch.setattr(emails, "CARPETA", tmp_path)
    n = api_avisos.enviar_urgentes(1)
    assert n > 0 and api_avisos.enviar_urgentes(1) == 0
