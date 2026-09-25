#!/usr/bin/env bash
# Abre la plataforma en http://localhost:8000 (Mac y Linux): bash iniciar.sh
set -e
cd "$(dirname "$0")/backend"
PY=$(command -v python3 || command -v python || true)
if [ -z "$PY" ]; then
  echo "No encontré Python. Instalalo desde https://www.python.org/downloads/ y volvé a correr este archivo."
  exit 1
fi
if [ ! -d .venv ]; then
  echo "Preparando la plataforma por primera vez, tarda un par de minutos..."
  "$PY" -m venv .venv
fi
. .venv/bin/activate
python -m pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
[ -f demo_erp.db ] || python -m app.erp.demo
echo
echo "Plataforma lista en http://localhost:8000  (para cerrarla: Ctrl+C)"
( sleep 4; (command -v open >/dev/null && open http://localhost:8000) || (command -v xdg-open >/dev/null && xdg-open http://localhost:8000) || true ) >/dev/null 2>&1 &
python -m uvicorn app.main:app
