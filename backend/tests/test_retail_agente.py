"""SPEC v2 · agente de sincronización por carpeta (5.1): sube exportaciones con token, cola local y reintentos."""
import os
import sys
import time
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.retail import api_ingesta, db, motor
from app.retail.semilla import CLAVE_DEMO
from test_retail_importar import _q, _ventas_archivo

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "agente"))
import agente_sync  # noqa: E402


@pytest.fixture(autouse=True)
def sin_recalculo(monkeypatch):
    monkeypatch.setattr(api_ingesta, "recalcular_en_segundo_plano", lambda org, desde=None: None)


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


class PorTestClient(agente_sync.Transporte):
    """El agente real, pero hablando con la aplicación en memoria en lugar de por internet."""

    def __init__(self, cfg, sin_internet=False):
        super().__init__(cfg)
        self.http = TestClient(app)
        self.sin_internet = sin_internet

    def _pedido(self, ruta, cuerpo, tipo):
        if self.sin_internet:
            raise urllib.error.URLError("sin conexión")
        r = self.http.post(ruta, content=cuerpo, headers={"Authorization": f"Agente {self.cfg.token}", "Content-Type": tipo})
        return r.status_code, r.json()


def _config(tmp_path, token):
    carpeta = tmp_path / "exportaciones"
    carpeta.mkdir()
    ini = tmp_path / "agente.ini"
    ini.write_text(f"[agente]\nurl = http://localhost\ntoken = {token}\ncarpeta = {carpeta}\ncada_minutos = 5\n", encoding="utf-8")
    return agente_sync.Config(ini), carpeta


def _dejar(carpeta: Path, nombre: str, contenido: bytes) -> Path:
    f = carpeta / nombre
    f.write_bytes(contenido)
    viejo = time.time() - 120
    os.utime(f, (viejo, viejo))                 # ya terminó de escribirse
    return f


def test_agente_sube_espera_columnas_y_despues_importa_solo(retail_demo, tmp_path):
    c = cliente()
    r = c.post("/retail/api/agentes", json={"nombre": "PC caja Salta Centro"})
    assert r.status_code == 201 and r.json()["token"].startswith("ag_")
    cfg, carpeta = _config(tmp_path, r.json()["token"])
    agente = agente_sync.Agente(cfg, PorTestClient(cfg))

    # Primera vez con este formato: queda esperando que el dueño confirme las columnas.
    _dejar(carpeta, "ventas_2026-09-20.csv", _ventas_archivo(3, 1))
    res = agente.vuelta()
    assert res["subidos"] == 1 and (carpeta / "enviados" / "ventas_2026-09-20.csv").exists()
    lista = c.get("/retail/api/agentes").json()
    assert lista["agentes"][0]["archivos_subidos"] == 1 and lista["agentes"][0]["version"] == agente_sync.VERSION
    pendiente = lista["esperando_columnas"][0]
    a = c.get("/retail/api/importar/lotes").json()
    lote = next(x for x in (a if isinstance(a, list) else a["lotes"]) if x["id"] == pendiente["id"])
    retomado = c.get(f"/retail/api/importar/{lote['id']}/analisis").json()      # Datos → Importar retoma el archivo en el paso de columnas
    assert retomado["tipo"] == "ventas" and not retomado["mapeo_recordado"] and len(retomado["muestra"]) > 0
    filas = retomado["encabezados"]
    mapeo = {"fecha": "Fecha", "hora": "Hora", "sucursal": "Local", "ticket": "Nro Ticket", "producto": "Codigo", "cantidad": "Cant",
             "precio": "Precio Unitario", "medio_pago": "Medio de pago"}
    assert set(mapeo.values()) <= set(filas)
    assert c.post(f"/retail/api/importar/{lote['id']}/validar", json={"mapeo": mapeo}).status_code == 200
    assert c.post(f"/retail/api/importar/{lote['id']}/confirmar").status_code == 200
    assert c.get(f"/retail/api/importar/{lote['id']}/analisis").status_code == 400       # ya no espera

    # El siguiente archivo con las mismas columnas entra solo; reenviar el mismo contenido no duplica.
    _dejar(carpeta, "ventas_2026-09-21.csv", _ventas_archivo(2, 100))
    assert agente.vuelta()["subidos"] == 1
    hecho = agente.estado["enviados"]
    assert any(v["archivo"] == "ventas_2026-09-21.csv" and v["estado"] == "importado" for v in hecho.values())
    _dejar(carpeta, "ventas_copia.csv", _ventas_archivo(2, 100))
    assert agente.vuelta()["subidos"] == 0                   # mismo contenido: ya enviado, no se vuelve a subir
    tickets = _q("SELECT count(*) n FROM tickets WHERE numero_externo LIKE '%%-A-0010%%' AND origen = 'archivo'")[0]["n"]
    assert tickets == 2


def test_sin_internet_queda_en_cola_y_un_archivo_raro_se_rechaza(retail_demo, tmp_path):
    c = cliente()
    token = c.post("/retail/api/agentes", json={"nombre": "PC"}).json()["token"]
    cfg, carpeta = _config(tmp_path, token)
    reloj = [time.time()]
    agente = agente_sync.Agente(cfg, PorTestClient(cfg, sin_internet=True), reloj=lambda: reloj[0])
    _dejar(carpeta, "ventas_x.csv", _ventas_archivo(1, 500))
    res = agente.vuelta()
    assert res["en_cola"] == 1 and (carpeta / "ventas_x.csv").exists()
    assert agente.vuelta()["en_cola"] == 1                   # todavía no toca reintentar: espera
    agente.t = PorTestClient(cfg)                            # vuelve internet y pasó el tiempo de espera
    reloj[0] += 120
    assert agente.vuelta()["subidos"] == 1
    _dejar(carpeta, "cualquiercosa.csv", b"a;b\n1;2\n")
    res = agente.vuelta()
    assert res["rechazados"] == 1 and (carpeta / "rechazados" / "cualquiercosa.csv").exists()


def test_token_revocado_o_de_otra_empresa(retail_demo, tmp_path):
    c = cliente()
    r = c.post("/retail/api/agentes", json={"nombre": "PC"}).json()
    assert TestClient(app).post("/retail/api/agente/latido", json={}).status_code == 401
    ok = TestClient(app).post("/retail/api/agente/latido", json={"pendientes": 2}, headers={"Authorization": f"Agente {r['token']}"})
    assert ok.status_code == 200
    assert c.delete(f"/retail/api/agentes/{r['id']}").status_code == 200
    assert TestClient(app).post("/retail/api/agente/latido", json={}, headers={"Authorization": f"Agente {r['token']}"}).status_code == 401
    assert cliente("encargado.norte@norte.demo").post("/retail/api/agentes", json={"nombre": "xx"}).status_code == 403
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        assert "ag_" not in str(db.filas(conn, "SELECT * FROM agentes_sincronizacion"))   # el token no se guarda
