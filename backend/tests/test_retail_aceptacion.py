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
