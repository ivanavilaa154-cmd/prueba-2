#!/usr/bin/env bash
# Se ejecuta una sola vez al crear el Codespace: instala y arma la base demo.
set -e
cd "$(dirname "$0")/../../backend"
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
[ -f .env ] || cp .env.example .env
[ -f demo_erp.db ] || python -m app.erp.demo
