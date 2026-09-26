"""Casos de cuadratura permanentes: cada diferencia encontrada con un sistema de origen queda acá (INC-*.yml).

Cada caso tiene que decir qué métrica, qué causa del checklist y qué comprobar; el perfil del
tipo de sistema (config/perfiles/<sistema>.yml) tiene que conocerlo.
"""
from pathlib import Path

import pytest
import yaml

CASOS = sorted((Path(__file__).parent / "casos").glob("*.yml"))
PERFILES = Path(__file__).resolve().parents[3] / "config" / "perfiles"


def test_carpeta_de_casos():
    assert (Path(__file__).parent / "casos").is_dir()


@pytest.mark.parametrize("ruta", CASOS, ids=[c.stem for c in CASOS])
def test_caso_completo_y_en_el_perfil(ruta):
    from app.pruebas.incidencias import CAUSAS
    caso = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    assert caso["id"] == ruta.stem and caso["metrica"] and caso["causa"] in CAUSAS and caso["comprobacion"]
    perfil = yaml.safe_load((PERFILES / f"{caso['fuente']}.yml").read_text(encoding="utf-8"))
    assert caso["id"] in [c["id"] for c in perfil["casos_conocidos"]]
