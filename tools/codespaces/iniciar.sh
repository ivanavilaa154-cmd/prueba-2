#!/usr/bin/env bash
# Se ejecuta cada vez que abrís el Codespace: levanta la plataforma en el puerto 8000.
# Codespaces la abre en una pestaña nueva; el link es privado (solo tu cuenta de GitHub).
cd "$(dirname "$0")/../../backend"
# Trae la última versión de la plataforma antes de arrancar (no toca .env ni los datos, que no se versionan).
echo "Buscando actualizaciones…"
git pull --ff-only -q && echo "Plataforma actualizada." || echo "No se pudo actualizar; se abre la versión que ya está."
python -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
[ -f .env ] || cp .env.example .env
# La demo es de ejemplo: se regenera siempre, así tiene todas las tablas de la versión actual.
python -m app.erp.demo >/dev/null
echo "Abriendo la plataforma… si no se abre sola, andá a la pestaña PORTS y abrí el puerto 8000."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
