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
    """Las pruebas nunca tocan backend/actividades.db, backend/gestion.db ni backend/ops.db."""
    from app.actividades import motor
    from app.gestion import almacen
    from app.pruebas import almacen as ops
    monkeypatch.setattr(motor, "RUTA", tmp_path / "actividades.db")
    monkeypatch.setattr(almacen, "RUTA", tmp_path / "gestion.db")
    monkeypatch.setattr(ops, "RUTA", tmp_path / "ops.db")
    monkeypatch.setattr(ops, "EVIDENCIAS", tmp_path / "evidencias")
    monkeypatch.delenv("RETAIL_DB_URL", raising=False)   # Retail solo usa la base temporal del fixture `retail`


# --- Retail: PostgreSQL temporal ------------------------------------------------------------------

def _binarios_pg() -> Path | None:
    import shutil
    import subprocess
    if shutil.which("pg_config"):
        try:
            ruta = Path(subprocess.run(["pg_config", "--bindir"], capture_output=True, text=True, check=True).stdout.strip())
            if (ruta / "initdb").exists():
                return ruta
        except Exception:
            pass
    candidatos = sorted(Path("/usr/lib/postgresql").glob("*/bin"), reverse=True)
    return candidatos[0] if candidatos else None


@pytest.fixture(scope="session")
def retail_pg(tmp_path_factory):
    """Levanta un PostgreSQL de prueba (initdb en una carpeta temporal) con el usuario retail_app, que no es
    superusuario: así las políticas RLS se aplican igual que en producción. Carga una plantilla migrada y con la demo."""
    import os
    import subprocess
    import socket
    import time
    externo = os.getenv("RETAIL_TEST_ADMIN_URL")   # opcional: un servidor ya levantado (superusuario)
    bin_ = _binarios_pg()
    if not externo and not bin_:
        pytest.skip("No hay PostgreSQL instalado para las pruebas de Retail.")
    proceso = None
    if externo:
        admin = externo
    else:
        import tempfile
        carpeta = Path(tempfile.mkdtemp(prefix="retail-pg-"))
        como = []
        if os.geteuid() == 0:   # initdb no corre como root: se usa el usuario postgres del sistema
            import shutil
            shutil.chown(carpeta, "postgres")
            como = ["runuser", "-u", "postgres", "--"]
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            puerto = s.getsockname()[1]
        datos = carpeta / "datos"
        subprocess.run(como + [str(bin_ / "initdb"), "-D", str(datos), "-A", "trust", "-U", "postgres", "-E", "UTF8", "--no-sync"],
                       check=True, capture_output=True)
        subprocess.run(como + [str(bin_ / "pg_ctl"), "-D", str(datos), "-o", f"-p {puerto} -k {carpeta} -c fsync=off -c listen_addresses=''",
                               "-l", str(carpeta / "log.txt"), "-w", "start"], check=True, capture_output=True)
        proceso = (como, bin_, datos)
        admin = f"postgresql://postgres@/postgres?host={carpeta}&port={puerto}"
    import psycopg
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute("DROP DATABASE IF EXISTS retail_plantilla")
        c.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='retail_app') THEN "
                  "CREATE ROLE retail_app LOGIN PASSWORD 'retail_app' NOSUPERUSER NOBYPASSRLS; END IF; END $$")
        c.execute("CREATE DATABASE retail_plantilla OWNER retail_app")
    base_app = admin.replace("postgres@", "retail_app:retail_app@", 1)
    from app.retail import db, semilla
    anterior = os.environ.get("RETAIL_DB_URL")
    os.environ["RETAIL_DB_URL"] = base_app.replace("/postgres?", "/retail_plantilla?", 1)
    try:
        semilla.cargar()
    finally:
        if anterior is None:
            os.environ.pop("RETAIL_DB_URL", None)
        else:
            os.environ["RETAIL_DB_URL"] = anterior
    yield {"admin": admin, "app": base_app, "contador": [0]}
    if proceso:
        como, bin_, datos = proceso
        subprocess.run(como + [str(bin_ / "pg_ctl"), "-D", str(datos), "-m", "immediate", "stop"], capture_output=True)
        import shutil
        shutil.rmtree(datos.parent, ignore_errors=True)


@pytest.fixture
def retail(retail_pg, monkeypatch):
    """Una base Retail nueva por prueba (copia de la plantilla con la demo), conectada como retail_app."""
    import psycopg
    retail_pg["contador"][0] += 1
    nombre = f"retail_t{retail_pg['contador'][0]}"
    with psycopg.connect(retail_pg["admin"], autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nombre} TEMPLATE retail_plantilla OWNER retail_app")
    monkeypatch.setenv("RETAIL_DB_URL", retail_pg["app"].replace("/postgres?", f"/{nombre}?", 1))
    yield nombre
    with psycopg.connect(retail_pg["admin"], autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {nombre} WITH (FORCE)")


DEMO_HOY = date(2026, 9, 24)


@pytest.fixture(scope="session")
def retail_demo_plantilla(retail_pg):
    """Plantilla con la demo a escala reducida (120 días, ~120 productos) y las métricas calculadas."""
    import os
    import psycopg
    from app.retail import demo
    with psycopg.connect(retail_pg["admin"], autocommit=True) as c:
        c.execute("DROP DATABASE IF EXISTS retail_plantilla_demo")
        c.execute("CREATE DATABASE retail_plantilla_demo TEMPLATE retail_plantilla OWNER retail_app")
    anterior = os.environ.get("RETAIL_DB_URL")
    os.environ["RETAIL_DB_URL"] = retail_pg["app"].replace("/postgres?", "/retail_plantilla_demo?", 1)
    try:
        resumen = demo.cargar(hoy=DEMO_HOY, escala=demo.Escala(dias=120, tickets=0.3, online_dias=60, productos=120))
    finally:
        if anterior is None:
            os.environ.pop("RETAIL_DB_URL", None)
        else:
            os.environ["RETAIL_DB_URL"] = anterior
    return resumen


@pytest.fixture
def retail_demo(retail_pg, retail_demo_plantilla, monkeypatch):
    """Base nueva por prueba, copia de la plantilla con la demo."""
    import psycopg
    retail_pg["contador"][0] += 1
    nombre = f"retail_d{retail_pg['contador'][0]}"
    with psycopg.connect(retail_pg["admin"], autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nombre} TEMPLATE retail_plantilla_demo OWNER retail_app")
    monkeypatch.setenv("RETAIL_DB_URL", retail_pg["app"].replace("/postgres?", f"/{nombre}?", 1))
    yield retail_demo_plantilla
    with psycopg.connect(retail_pg["admin"], autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {nombre} WITH (FORCE)")


@pytest.fixture(scope="session")
def retail_distribuidora_plantilla(retail_pg):
    """Plantilla con la demo del modo distribuidor a escala reducida (120 días, 60 clientes, 40 productos)."""
    import os
    import psycopg
    from app.retail import demo_distribuidora
    with psycopg.connect(retail_pg["admin"], autocommit=True) as c:
        c.execute("DROP DATABASE IF EXISTS retail_plantilla_valle")
        c.execute("CREATE DATABASE retail_plantilla_valle TEMPLATE retail_plantilla OWNER retail_app")
    anterior = os.environ.get("RETAIL_DB_URL")
    os.environ["RETAIL_DB_URL"] = retail_pg["app"].replace("/postgres?", "/retail_plantilla_valle?", 1)
    try:
        resumen = demo_distribuidora.cargar(hoy=DEMO_HOY, escala=demo_distribuidora.Escala(dias=120, clientes=60, productos=40))
    finally:
        if anterior is None:
            os.environ.pop("RETAIL_DB_URL", None)
        else:
            os.environ["RETAIL_DB_URL"] = anterior
    return resumen


@pytest.fixture
def retail_distribuidora(retail_pg, retail_distribuidora_plantilla, monkeypatch):
    """Base nueva por prueba, copia de la plantilla con la demo de la distribuidora."""
    import psycopg
    retail_pg["contador"][0] += 1
    nombre = f"retail_v{retail_pg['contador'][0]}"
    with psycopg.connect(retail_pg["admin"], autocommit=True) as c:
        c.execute(f"CREATE DATABASE {nombre} TEMPLATE retail_plantilla_valle OWNER retail_app")
    monkeypatch.setenv("RETAIL_DB_URL", retail_pg["app"].replace("/postgres?", f"/{nombre}?", 1))
    yield retail_distribuidora_plantilla
    with psycopg.connect(retail_pg["admin"], autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {nombre} WITH (FORCE)")
