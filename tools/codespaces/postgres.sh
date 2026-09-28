#!/usr/bin/env bash
# Prepara la base PostgreSQL de Retail dentro del Codespace (una sola vez) y la levanta en cada inicio.
# - Instala PostgreSQL si falta (apt).
# - Crea un servidor propio en backend/.pgdata (puerto 5433), solo accesible desde el Codespace.
# - Crea el usuario retail_app (sin permisos de superusuario, así las políticas RLS se aplican) y la base retail.
# - Escribe RETAIL_DB_URL en backend/.env.
# Todo va dentro de una función: bash la lee entera antes de ejecutarla.
principal() {
set -e
cd "$(dirname "$0")/../../backend"
PUERTO=5433
DATOS="$PWD/.pgdata"
SOCKET="$DATOS/socket"
bin_pg() { ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1; }

if [ -z "$(bin_pg)" ]; then
  echo "Instalando PostgreSQL (una sola vez)…"
  sudo apt-get update -qq >/dev/null && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql >/dev/null
  sudo systemctl disable --now postgresql >/dev/null 2>&1 || sudo service postgresql stop >/dev/null 2>&1 || true
fi
BIN="$(bin_pg)"
if [ ! -f "$DATOS/PG_VERSION" ]; then
  echo "Creando la base de Retail…"
  mkdir -p "$DATOS"
  "$BIN/initdb" -D "$DATOS" -A scram-sha-256 -U postgres --pwfile=<(echo "admin-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')") -E UTF8 >/dev/null
  mkdir -p "$SOCKET"
  echo "unix_socket_directories = '$SOCKET'" >> "$DATOS/postgresql.conf"
  echo "listen_addresses = 'localhost'" >> "$DATOS/postgresql.conf"
  echo "port = $PUERTO" >> "$DATOS/postgresql.conf"
  # Solo para crear el usuario de la aplicación: el socket local confía en el dueño del sistema durante la preparación.
  sed -i "1i local all postgres peer map=propio" "$DATOS/pg_hba.conf"
  echo "propio $(whoami) postgres" >> "$DATOS/pg_ident.conf"
fi
mkdir -p "$SOCKET"
if ! "$BIN/pg_ctl" -D "$DATOS" status >/dev/null 2>&1; then
  "$BIN/pg_ctl" -D "$DATOS" -l "$DATOS/registro.log" -w start >/dev/null
fi
if ! grep -q "^RETAIL_DB_URL=" .env 2>/dev/null; then
  CLAVE="$(head -c 18 /dev/urandom | od -An -tx1 | tr -d ' \n')"
  "$BIN/psql" -h "$SOCKET" -p $PUERTO -U postgres -d postgres -q -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'retail_app') THEN
    CREATE ROLE retail_app LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE;
  END IF;
END \$\$;
ALTER ROLE retail_app PASSWORD '$CLAVE';
SQL
  "$BIN/psql" -h "$SOCKET" -p $PUERTO -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='retail'" | grep -q 1 \
    || "$BIN/createdb" -h "$SOCKET" -p $PUERTO -U postgres -O retail_app retail
  printf "\n# Base de Retail (PostgreSQL local del Codespace)\nRETAIL_DB_URL=postgresql://retail_app:%s@localhost:%s/retail\n" "$CLAVE" "$PUERTO" >> .env
  echo "Base de Retail lista."
fi
}
principal "$@"
exit
