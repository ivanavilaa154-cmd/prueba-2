"""Acceso con contraseña para la versión publicada en internet."""
import time

import pytest
from fastapi.testclient import TestClient

from app import acceso, main


@pytest.fixture
def api(monkeypatch):
    monkeypatch.delenv("PANEL_CLAVE", raising=False)
    monkeypatch.delenv("EXIGIR_CLAVE", raising=False)
    return TestClient(main.app)


def test_en_la_compu_propia_no_pide_clave(api):
    assert api.get("/fuente").status_code == 200
    assert api.get("/salud").json()["con_clave"] is False


def test_con_clave_todo_pide_sesion(api, monkeypatch):
    monkeypatch.setenv("PANEL_CLAVE", "correcta-y-larga")
    assert api.get("/salud").status_code == 200  # para el chequeo del servidor
    pagina = api.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert pagina.status_code == 303 and pagina.headers["location"] == "/login"
    for ruta in ("/fuente", "/integraciones", "/usuarios", "/docs", "/openapi.json"):
        assert api.get(ruta).status_code == 401, ruta
    assert api.post("/consulta", json={"usuario_id": "u1", "sql": "SELECT 1"}).status_code == 401


def test_login(api, monkeypatch):
    monkeypatch.setenv("PANEL_CLAVE", "correcta-y-larga")
    mala = api.post("/login", data={"clave": "otra"}, follow_redirects=False)
    assert mala.status_code == 401 and acceso.COOKIE not in mala.cookies
    buena = api.post("/login", data={"clave": "correcta-y-larga"}, follow_redirects=False)
    assert buena.status_code == 303 and acceso.COOKIE in buena.cookies
    assert api.get("/fuente").status_code == 200  # el cliente guarda la cookie
    api.get("/salir")
    assert api.get("/fuente").status_code == 401


def test_cambiar_la_clave_cierra_sesiones(api, monkeypatch):
    monkeypatch.setenv("PANEL_CLAVE", "primera-clave")
    api.post("/login", data={"clave": "primera-clave"})
    assert api.get("/fuente").status_code == 200
    monkeypatch.setenv("PANEL_CLAVE", "segunda-clave")
    assert api.get("/fuente").status_code == 401


def test_sesion_vencida_o_falsa(monkeypatch):
    monkeypatch.setenv("PANEL_CLAVE", "x")
    vencida = int(time.time()) - 10
    assert not acceso.sesion_valida(f"{vencida}.{acceso._firma(vencida)}")
    futura = int(time.time()) + 999
    assert not acceso.sesion_valida(f"{futura}.firma-inventada")
    assert not acceso.sesion_valida(None)


def test_en_servidor_sin_clave_no_abre(api, monkeypatch):
    monkeypatch.setenv("EXIGIR_CLAVE", "1")
    assert api.get("/fuente").status_code == 503
    assert "PANEL_CLAVE" in api.get("/").text
