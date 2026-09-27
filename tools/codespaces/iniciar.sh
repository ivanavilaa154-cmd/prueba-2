#!/usr/bin/env bash
# Se ejecuta cada vez que abrís el Codespace: levanta la plataforma en el puerto 8000.
# Codespaces la abre en una pestaña nueva; el link es privado (solo tu cuenta de GitHub).
# Todo va dentro de una función: bash la lee entera antes de ejecutarla, así la actualización
# de este mismo archivo (git reset) no lo corta a la mitad.
principal() {
cd "$(dirname "$0")/../../backend" || exit 1
# Trae la última versión de la plataforma antes de arrancar (no toca .env ni los datos, que no se versionan).
echo "Buscando actualizaciones…"
if git fetch -q origin main; then
  git checkout -q main 2>/dev/null || true
  # Si quedó algún archivo del programa tocado a mano, se guarda aparte (git stash) para que no frene la actualización.
  if ! git diff --quiet || ! git diff --cached --quiet; then
    git stash push -q -m "cambios locales $(date +%F_%H%M)" && echo "Había cambios locales en el código: quedaron guardados (git stash)."
  fi
  git reset -q --hard origin/main
  echo "Plataforma actualizada: versión $(git log -1 --format='%h del %ad' --date=format:'%d/%m %H:%M')."
else
  echo "No se pudo conectar con GitHub; se abre la versión que ya está ($(git log -1 --format=%h))."
fi
# Si quedó abierta una versión anterior de la plataforma, se cierra para que arranque la nueva.
pkill -f "uvicorn app.main:app" 2>/dev/null && sleep 1 || true
python -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
[ -f .env ] || cp .env.example .env
# Claves del Centro de pruebas: si el .env es de una versión anterior, se agregan las de ejemplo.
grep -q "^CLAVE_U5=" .env || printf "\n# Claves del Centro de pruebas (cambialas antes de publicar)\nCLAVE_U4=operador-demo\nCLAVE_U5=tester-demo\n" >> .env
# La demo es de ejemplo: se regenera siempre, así tiene todas las tablas de la versión actual.
python -m app.erp.demo >/dev/null
echo "Abriendo la plataforma… si no se abre sola, andá a la pestaña PORTS y abrí el puerto 8000."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
}
principal "$@"
exit
