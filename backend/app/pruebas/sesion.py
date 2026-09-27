"""Ingreso al Centro de pruebas (solo roles operador y tester) y modo "ver como usuario".

Cada persona entra con su usuario y su clave (CLAVE_<ID> en backend/.env). La sesión
es una cookie firmada; el servidor valida el rol en cada pedido a /pruebas, así que
la sección no se ve ni escribiendo la dirección ni llamando a la API.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from fastapi import HTTPException, Request

from .. import config
from ..permisos import Usuario, obtener_usuario

COOKIE = "pruebas_sesion"
COOKIE_VER_COMO = "ver_como"
DURACION = 12 * 3600
ROLES = ("operador", "tester")
_ARCHIVO_SECRETO = config.BACKEND / ".secreto_sesiones"


def _secreto() -> bytes:
    valor = os.getenv("SESION_SECRETO")
    if valor:
        return valor.encode()
    if not _ARCHIVO_SECRETO.exists():
        _ARCHIVO_SECRETO.write_text(secrets.token_hex(32))
    return _ARCHIVO_SECRETO.read_text().strip().encode()


def _firmar(texto: str) -> str:
    return hmac.new(_secreto(), texto.encode(), hashlib.sha256).hexdigest()


def crear(usuario_id: str) -> str:
    vence = int(time.time()) + DURACION
    cuerpo = f"{usuario_id}|{vence}"
    return f"{cuerpo}|{_firmar(cuerpo)}"


def leer(valor: str | None) -> str | None:
    """Usuario de una cookie firmada y vigente, o None."""
    if not valor or valor.count("|") != 2:
        return None
    usuario_id, vence, firma = valor.split("|")
    if not vence.isdigit() or int(vence) < time.time() or not hmac.compare_digest(firma, _firmar(f"{usuario_id}|{vence}")):
        return None
    return usuario_id


CLAVES_DEMO = {"CLAVE_U4": "operador-demo", "CLAVE_U5": "tester-demo"}


def asegurar_claves_demo() -> list[str]:
    """Si backend/.env no trae las claves del Centro de pruebas (un .env de una versión anterior),
    agrega las de ejemplo y las activa. No pisa claves que ya existan."""
    agregadas = [k for k in CLAVES_DEMO if not os.getenv(k)]
    if not agregadas:
        return []
    archivo = config.BACKEND / ".env"
    previo = archivo.read_text(encoding="utf-8") if archivo.exists() else ""
    lineas = "".join(f"{k}={CLAVES_DEMO[k]}\n" for k in agregadas)
    separador = "" if not previo or previo.endswith("\n") else "\n"
    archivo.write_text(previo + separador + "# Claves del Centro de pruebas (cambialas antes de publicar)\n" + lineas, encoding="utf-8")
    for k in agregadas:
        os.environ[k] = CLAVES_DEMO[k]
    return agregadas


def clave_configurada(usuario_id: str) -> bool:
    return bool(os.getenv(f"CLAVE_{usuario_id.upper()}", "").strip())


def verificar_clave(usuario_id: str, clave: str) -> Usuario | None:
    datos = config.roles()["usuarios"].get(usuario_id)
    esperada = os.getenv(f"CLAVE_{usuario_id.upper()}", "").strip()
    if not datos or datos.get("rol") not in ROLES or not esperada:
        return None
    if not hmac.compare_digest(clave.strip().encode(), esperada.encode()):
        return None
    return obtener_usuario(usuario_id)


def probador(request: Request) -> Usuario:
    """Dependencia de todas las rutas /pruebas: sin sesión de operador o tester → 403."""
    usuario_id = leer(request.cookies.get(COOKIE))
    if usuario_id:
        try:
            u = obtener_usuario(usuario_id)
            if u.rol in ROLES:
                return u
        except Exception:
            pass
    raise HTTPException(status_code=403, detail="El Centro de pruebas es solo para los roles operador y tester.")


def ver_como_activo(request: Request) -> str | None:
    """Usuario que se está simulando (modo solo lectura), si lo hay y lo activó un operador o tester válido."""
    valor = leer(request.cookies.get(COOKIE_VER_COMO))
    if not valor or not leer(request.cookies.get(COOKIE)):
        return None
    return valor
