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
