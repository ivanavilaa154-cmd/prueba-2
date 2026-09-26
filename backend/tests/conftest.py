import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import config  # noqa: E402
from app.erp import demo  # noqa: E402


@pytest.fixture(scope="session")
def base_demo(tmp_path_factory):
    ruta = demo.crear(tmp_path_factory.mktemp("erp") / "demo.db", hoy=date(2026, 9, 24))
    return f"sqlite:///{ruta}"


@pytest.fixture
def base_demo_config(base_demo, monkeypatch):
    monkeypatch.setattr(config, "ERP_URL", base_demo)
    return base_demo


@pytest.fixture(autouse=True)
def bases_propias_aisladas(tmp_path, monkeypatch):
    """Las tareas y la gestión de las pruebas nunca tocan backend/actividades.db ni backend/gestion.db."""
    from app.actividades import motor
    from app.gestion import almacen
    monkeypatch.setattr(motor, "RUTA", tmp_path / "actividades.db")
    monkeypatch.setattr(almacen, "RUTA", tmp_path / "gestion.db")
