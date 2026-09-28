"""Cifrado de credenciales de conexiones (Odoo, plataformas): Fernet (AES + HMAC).

La clave maestra sale de RETAIL_CLAVE_CIFRADO o, si no está, de backend/.clave_retail (se crea sola y no se sube al
repositorio). Las credenciales nunca se guardan ni se devuelven en texto plano.
"""
from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken

from .. import config

ARCHIVO = config.BACKEND / ".clave_retail"


def _fernet() -> Fernet:
    clave = os.getenv("RETAIL_CLAVE_CIFRADO", "").strip()
    if not clave:
        if not ARCHIVO.exists():
            ARCHIVO.write_text(Fernet.generate_key().decode())
            ARCHIVO.chmod(0o600)
        clave = ARCHIVO.read_text().strip()
    return Fernet(clave.encode())


def cifrar(datos: dict) -> bytes:
    return _fernet().encrypt(json.dumps(datos).encode())


def descifrar(token: bytes | memoryview | None) -> dict:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(bytes(token)))
    except InvalidToken:
        raise ValueError("No se pudieron leer las credenciales guardadas (cambió la clave de cifrado). Volvé a cargarlas.")
