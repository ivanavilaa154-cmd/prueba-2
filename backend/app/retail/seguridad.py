"""Claves, tokens de sesión y segundo factor (TOTP, RFC 6238), sin dependencias externas."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

CLAVE_MINIMA = 10
_N, _R, _P = 2 ** 14, 8, 1


def hash_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(clave.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(sal).decode()}${base64.b64encode(h).decode()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calculado = hashlib.scrypt(clave.encode(), salt=base64.b64decode(sal), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calculado, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


# Para que un email inexistente tarde lo mismo que uno existente.
HASH_FICTICIO = hash_clave(secrets.token_hex(8))


def validar_clave_nueva(clave: str) -> str | None:
    if len(clave) < CLAVE_MINIMA:
        return f"La clave tiene que tener al menos {CLAVE_MINIMA} caracteres."
    if clave.isdigit() or clave.isalpha():
        return "La clave tiene que combinar letras con números o símbolos."
    return None


def clave_temporal() -> str:
    return secrets.token_urlsafe(9) + "7"


def token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


# --- segundo factor --------------------------------------------------------------------------

def secreto_totp() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def codigo_totp(secreto: str, instante: float | None = None, paso: int = 30) -> str:
    clave = base64.b32decode(secreto + "=" * (-len(secreto) % 8))
    contador = int((instante if instante is not None else time.time()) // paso)
    digest = hmac.new(clave, struct.pack(">Q", contador), hashlib.sha1).digest()
    desplazamiento = digest[-1] & 0x0F
    numero = struct.unpack(">I", digest[desplazamiento:desplazamiento + 4])[0] & 0x7FFFFFFF
    return f"{numero % 1_000_000:06d}"


def verificar_totp(secreto: str, codigo: str, instante: float | None = None) -> bool:
    ahora = instante if instante is not None else time.time()
    codigo = (codigo or "").strip().replace(" ", "")
    return any(hmac.compare_digest(codigo_totp(secreto, ahora + d * 30), codigo) for d in (-1, 0, 1))


def uri_totp(secreto: str, email: str, emisor: str = "Retail IA") -> str:
    return f"otpauth://totp/{quote(emisor)}:{quote(email)}?secret={secreto}&issuer={quote(emisor)}"
