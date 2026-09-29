"""Conexión a la base PostgreSQL de Retail, migraciones y aislamiento por transacción.

Cada transacción fija, con set_config(..., true) (vale solo para esa transacción):
- app.org_id: la empresa del usuario. Las políticas RLS filtran toda tabla por org_id.
- app.todas_ubicaciones / app.ubicaciones: qué sucursales puede ver (encargado y cajero, solo las asignadas).
- app.usuario_id: el propio usuario (puede leer su fila aunque todavía no se conozca su empresa).
- app.superadmin: solo en las rutas de plataforma.
Las tablas tienen RLS forzada, así que ni el dueño de las tablas se saltea el filtro. El usuario
de base de datos de la aplicación no es superusuario ni tiene BYPASSRLS.
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

MIGRACIONES = Path(__file__).parent / "migraciones"


class BaseNoConfigurada(RuntimeError):
    pass


def url() -> str:
    valor = os.getenv("RETAIL_DB_URL", "").strip()
    if not valor:
        raise BaseNoConfigurada("Falta configurar la base de Retail (RETAIL_DB_URL en backend/.env).")
    return valor


def configurada() -> bool:
    return bool(os.getenv("RETAIL_DB_URL", "").strip())


_preparada: set[str] = set()
_ultimo_error: dict = {"texto": None}
_candado = threading.Lock()


def _releer_env() -> None:
    """En el Codespace, postgres.sh escribe RETAIL_DB_URL en backend/.env mientras la plataforma ya corre."""
    import sys
    if configurada() or "pytest" in sys.modules:
        return
    archivo = Path(__file__).resolve().parents[2] / ".env"
    if archivo.exists():
        for linea in archivo.read_text(encoding="utf-8").splitlines():
            if linea.strip().startswith("RETAIL_DB_URL="):
                os.environ["RETAIL_DB_URL"] = linea.split("=", 1)[1].strip().strip('"').strip("'")


def modo_cuentas() -> str:
    """«reales»: solo la administración y Pulpo Azul (ver cuentas.py). En un Codespace es lo predeterminado (GitHub define
    CODESPACES=true); en otro lado, la demo. RETAIL_CUENTAS=demo o =reales en backend/.env lo fija a mano."""
    valor = os.getenv("RETAIL_CUENTAS", "").strip().lower()
    if valor in ("demo", "reales"):
        return valor
    return "reales" if os.getenv("CODESPACES", "").lower() == "true" else "demo"


def asegurar_lista() -> None:
    """Deja la base lista (migraciones + demo si está vacía) la primera vez que se usa. Si todavía no se puede,
    levanta BaseNoConfigurada con un mensaje claro; se reintenta en el pedido siguiente."""
    _releer_env()
    if not configurada():
        raise BaseNoConfigurada("La base de Retail todavía se está preparando (PostgreSQL). Esperá un minuto y recargá la página.")
    actual = url()
    if actual in _preparada:
        return
    with _candado:
        if actual in _preparada:
            return
        try:
            import sys
            if modo_cuentas() == "reales" and "pytest" not in sys.modules:
                from . import cuentas
                migrar()
                r = cuentas.dejar_solo_reales()
                if r["creadas"] or r["borradas"]:
                    print(f"Retail: solo cuentas reales (creadas: {', '.join(r['creadas']) or '—'}; borradas: {', '.join(r['borradas']) or '—'}).")
            else:
                from . import semilla
                if semilla.cargar():
                    print(f"Retail: empresas de demostración cargadas (clave de las cuentas demo: {semilla.CLAVE_DEMO}).")
        except Exception as e:
            _ultimo_error["texto"] = f"{type(e).__name__}: {str(e)[:200]}"
            raise BaseNoConfigurada("La base de Retail todavía no responde (se está preparando o se detuvo). "
                                    "Esperá un minuto y recargá; si sigue igual, reiniciá con bash tools/codespaces/iniciar.sh. "
                                    f"Detalle: {_ultimo_error['texto']}") from e
        _ultimo_error["texto"] = None
        _preparada.add(actual)


def estado() -> dict:
    try:
        asegurar_lista()
        return {"lista": True, "mensaje": "La base de Retail está lista."}
    except BaseNoConfigurada as e:
        return {"lista": False, "mensaje": str(e)}


@dataclass
class Contexto:
    """Quién hace el pedido y qué puede ver. Lo arma sesiones.contexto() en cada pedido."""
    usuario_id: int
    org_id: int | None
    rol: str | None
    nombre: str = ""
    email: str = ""
    es_superadmin: bool = False
    todas_ubicaciones: bool = False
    ubicaciones: list[int] = field(default_factory=list)


def conectar():
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(url(), row_factory=dict_row, autocommit=False)


@contextmanager
def transaccion(ctx: Contexto | None = None, *, usuario_id: int | None = None, login_email: str | None = None,
                superadmin: bool = False, org_id: int | None = None) -> Iterator:
    """Abre una transacción con el aislamiento del contexto. Confirma al salir o deshace ante un error."""
    ajustes = {
        "app.org_id": org_id if org_id is not None else (ctx.org_id if ctx else None),
        "app.usuario_id": usuario_id if usuario_id is not None else (ctx.usuario_id if ctx else None),
        "app.todas_ubicaciones": "1" if ctx and ctx.todas_ubicaciones else "0",
        "app.ubicaciones": "{" + ",".join(str(int(u)) for u in (ctx.ubicaciones if ctx else [])) + "}",
        "app.superadmin": "1" if superadmin else "0",
        "app.login_email": login_email or "",
    }
    with conectar() as conn:
        with conn.cursor() as cur:
            for clave, valor in ajustes.items():
                cur.execute("SELECT set_config(%s, %s, true)", (clave, "" if valor is None else str(valor)))
        yield conn


def migrar() -> list[str]:
    """Aplica en orden las migraciones que falten. Devuelve las aplicadas."""
    aplicadas = []
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(4242)")
        # Las migraciones que corrigen datos existentes necesitan ver todas las empresas (las tablas tienen RLS forzada).
        cur.execute("SELECT set_config('app.superadmin', '1', true)")
        cur.execute("CREATE TABLE IF NOT EXISTS esquema_migraciones (version text PRIMARY KEY, aplicada timestamptz NOT NULL DEFAULT now())")
        cur.execute("SELECT version FROM esquema_migraciones")
        hechas = {f["version"] for f in cur.fetchall()}
        for archivo in sorted(MIGRACIONES.glob("*.sql")):
            if archivo.stem in hechas:
                continue
            cur.execute(archivo.read_text(encoding="utf-8"))
            cur.execute("INSERT INTO esquema_migraciones (version) VALUES (%s)", (archivo.stem,))
            aplicadas.append(archivo.stem)
    return aplicadas


def filas(conn, sql: str, params: tuple | dict = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall() if cur.description else []


def fila(conn, sql: str, params: tuple | dict = ()) -> dict | None:
    r = filas(conn, sql, params)
    return r[0] if r else None


def copiar(conn, tabla: str, columnas: list[str], filas) -> int:
    """Carga masiva respetando la RLS: COPY a una tabla temporal (sin RLS) y de ahí INSERT … SELECT, que sí pasa por las
    políticas de la tabla destino (PostgreSQL no permite COPY directo sobre tablas con RLS)."""
    filas = list(filas)
    if not filas:
        return 0
    cols = ", ".join(columnas)
    temporal = f"_carga_{tabla}"
    with conn.cursor() as cur:
        cur.execute(f"CREATE TEMP TABLE IF NOT EXISTS {temporal} (LIKE {tabla} INCLUDING DEFAULTS) ON COMMIT DROP")
        cur.execute(f"TRUNCATE {temporal}")
        with cur.copy(f"COPY {temporal} ({cols}) FROM STDIN") as cp:
            for f in filas:
                cp.write_row(f)
        cur.execute(f"INSERT INTO {tabla} ({cols}) SELECT {cols} FROM {temporal}")
        cur.execute(f"TRUNCATE {temporal}")
    return len(filas)
