"""Privacidad y cumplimiento (sección 13.5; Ley 25.326 de Protección de Datos Personales de Argentina).

- Política de privacidad versionada: cada usuario la acepta al entrar (y otra vez si cambia la versión).
- Derecho de acceso: el dueño descarga todos los datos de su empresa (un ZIP con un CSV por tabla).
- Derecho de supresión de la empresa: el dueño pide la baja; queda un plazo para arrepentirse (DIAS_BAJA) y después se borra
  todo (la auditoría se conserva sin empresa). Mientras tanto la empresa sigue funcionando y se muestra el aviso.
- Supresión de un cliente final: se anonimiza (se borran nombre e identificador; las ventas quedan sin dato personal).
- Copias de seguridad diarias de la base (pg_dump), se guardan las últimas COPIAS_A_GUARDAR.
"""
from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import db

VERSION_POLITICA = "2026-09"
DIAS_BAJA = 30
COPIAS_A_GUARDAR = 7
CARPETA_COPIAS = Path(__file__).resolve().parents[2] / "respaldos"
# Tablas que no se exportan: técnicas o con secretos (hash de claves, credenciales cifradas, tokens de sesión).
NO_EXPORTAR = {"staging_filas"}
COLUMNAS_OCULTAS = {"hash_clave", "totp_secreto", "credenciales_cifradas", "token_hash"}


def _tablas_empresa(conn) -> list[str]:
    return [f["table_name"] for f in db.filas(conn, """
        SELECT c.table_name FROM information_schema.columns c JOIN information_schema.tables t USING (table_schema, table_name)
        WHERE c.table_schema = 'public' AND c.column_name = 'org_id' AND t.table_type = 'BASE TABLE' ORDER BY 1""")
        if f["table_name"] not in NO_EXPORTAR]


def exportar(conn, org_id: int) -> bytes:
    """ZIP con un CSV por tabla con los datos de la empresa (el acceso a los propios datos de la ley)."""
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
        org = db.fila(conn, "SELECT * FROM organizaciones WHERE id=%s", (org_id,))
        tablas = {"organizaciones": [org]}
        for tabla in _tablas_empresa(conn):
            with conn.cursor() as cur:
                cur.execute(f'SELECT * FROM "{tabla}" WHERE org_id = %s', (org_id,))
                columnas = [d.name for d in cur.description]
                tablas[tabla] = (columnas, cur.fetchall())
        for tabla, contenido in tablas.items():
            if tabla == "organizaciones":
                columnas, filas = list(org.keys()), [org]
            else:
                columnas, filas = contenido
            visibles = [c for c in columnas if c not in COLUMNAS_OCULTAS]
            texto = io.StringIO()
            w = csv.writer(texto)
            w.writerow(visibles)
            for f in filas:
                w.writerow(["" if f[c] is None else f[c] for c in visibles])
            z.writestr(f"{tabla}.csv", texto.getvalue())
        from .. import empresas                  # y lo del Panel ERP de la empresa (su base, tareas y objetivos)
        base = empresas.CARPETA / str(int(org_id))
        if base.exists():
            for archivo in sorted(base.iterdir()):
                if archivo.is_file() and archivo.suffix in (".db", ".json"):
                    z.write(archivo, f"panel_erp/{archivo.name}")
        z.writestr("LEEME.txt", "Datos de tu empresa exportados de Retail IA el "
                   f"{datetime.now().strftime('%d/%m/%Y %H:%M')}. Un archivo por tabla, en CSV (UTF-8, separado por comas).\n"
                   "No se incluyen claves ni credenciales (solo sus nombres de columna quedan fuera).\n")
    return salida.getvalue()


def estado_baja(conn, org_id: int) -> dict | None:
    f = db.fila(conn, "SELECT baja_solicitada_at FROM organizaciones WHERE id=%s", (org_id,))
    if not f or not f["baja_solicitada_at"]:
        return None
    return {"solicitada": f["baja_solicitada_at"], "se_borra": f["baja_solicitada_at"] + timedelta(days=DIAS_BAJA)}


def procesar_bajas() -> list[int]:
    """Borra las empresas cuyo plazo de arrepentimiento terminó (lo llama el programador)."""
    from . import cuentas, sesiones
    with db.transaccion(superadmin=True) as conn:
        vencidas = db.filas(conn, "SELECT id, nombre FROM organizaciones WHERE baja_solicitada_at IS NOT NULL "
                                  "AND baja_solicitada_at < now() - make_interval(days => %s)", (DIAS_BAJA,))
        for o in vencidas:
            sesiones.auditar(conn, None, None, "borrar", "empresa", o["id"], {"nombre": o["nombre"], "motivo": "baja solicitada"})
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sesiones WHERE usuario_id IN (SELECT id FROM usuarios WHERE org_id=%s)", (o["id"],))
            cuentas.borrar_empresas(conn, [o["id"]])
    import shutil
    from .. import empresas
    for o in vencidas:                           # ya confirmado el borrado: también el Panel ERP de la empresa
        shutil.rmtree(empresas.CARPETA / str(int(o["id"])), ignore_errors=True)
    return [o["id"] for o in vencidas]


# --- copias de seguridad ------------------------------------------------------------------------

def _pg_dump() -> str | None:
    encontrado = shutil.which("pg_dump")
    if encontrado:
        return encontrado
    candidatos = sorted(Path("/usr/lib/postgresql").glob("*/bin/pg_dump"), reverse=True)
    return str(candidatos[0]) if candidatos else None


def respaldar(carpeta: Path | None = None) -> Path:
    """Copia completa de la base (formato comprimido de pg_dump). Se guardan las últimas COPIAS_A_GUARDAR."""
    carpeta = carpeta or CARPETA_COPIAS
    carpeta.mkdir(parents=True, exist_ok=True)
    binario = _pg_dump()
    if not binario:
        raise RuntimeError("No está instalado pg_dump: no se puede hacer la copia de seguridad.")
    destino = carpeta / f"retail-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}.dump"
    # Las tablas tienen RLS forzada: la copia se hace con las políticas activas y como administración de la plataforma
    # (app.superadmin=1), que ve todas las empresas. Sin esto pg_dump se niega a leerlas.
    entorno = {**os.environ, "PGOPTIONS": "-c app.superadmin=1"}
    r = subprocess.run([binario, "--format=custom", "--no-owner", "--enable-row-security", f"--file={destino}", "--dbname", db.url()],
                       capture_output=True, text=True, timeout=3600, env=entorno)
    if r.returncode != 0:
        destino.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump falló: {r.stderr.strip()[:300]}")
    try:
        os.chmod(destino, 0o600)
    except OSError:
        pass
    for viejo in sorted(carpeta.glob("retail-*.dump"))[:-COPIAS_A_GUARDAR]:
        viejo.unlink(missing_ok=True)
    return destino


def copias(carpeta: Path | None = None) -> list[dict]:
    carpeta = carpeta or CARPETA_COPIAS
    return [{"archivo": p.name, "bytes": p.stat().st_size, "fecha": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)}
            for p in sorted(carpeta.glob("retail-*.dump"), reverse=True)] if carpeta.exists() else []
