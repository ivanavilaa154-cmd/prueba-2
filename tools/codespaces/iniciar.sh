#!/usr/bin/env bash
# Se ejecuta cada vez que abrís el Codespace: levanta la plataforma en el puerto 8000.
# Codespaces la abre en una pestaña nueva; el link es privado (solo tu cuenta de GitHub).
cd "$(dirname "$0")/../../backend"
[ -f demo_erp.db ] || bash ../tools/codespaces/preparar.sh
echo "Abriendo la plataforma… si no se abre sola, andá a la pestaña PORTS y abrí el puerto 8000."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
