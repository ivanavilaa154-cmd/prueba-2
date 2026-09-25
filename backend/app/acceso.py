"""Acceso con contraseña para cuando la plataforma se publica en internet.

- Si PANEL_CLAVE está definida, todas las páginas y la API piden iniciar sesión.
- Si EXIGIR_CLAVE=1 (así se publica en un servidor) y falta PANEL_CLAVE, la
  plataforma no muestra nada: nunca queda abierta por olvido.
- En la computadora propia (sin esas variables) funciona sin contraseña.

La sesión es una cookie firmada con la contraseña: cambiarla cierra todas las
sesiones. Todavía es una sola contraseña para todo el panel; los usuarios con
rol propio llegan en la Fase 3.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import os
import time

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

COOKIE = "plataforma_sesion"
DURACION = 12 * 3600  # segundos
LIBRES = {"/login", "/salud"}


def _clave() -> str:
    return os.getenv("PANEL_CLAVE", "")


def _exigida() -> bool:
    return os.getenv("EXIGIR_CLAVE", "").strip().lower() in {"1", "true", "si", "sí"}


def _firma(vence: int) -> str:
    return hmac.new(_clave().encode(), f"sesion:{vence}".encode(), hashlib.sha256).hexdigest()


def crear_sesion() -> str:
    vence = int(time.time()) + DURACION
    return f"{vence}.{_firma(vence)}"


def sesion_valida(valor: str | None) -> bool:
    if not valor or "." not in valor or not _clave():
        return False
    vence, firma = valor.split(".", 1)
    return vence.isdigit() and int(vence) > time.time() and hmac.compare_digest(firma, _firma(int(vence)))


def _pagina_login(error: str = "", status: int = 200) -> HTMLResponse:
    aviso = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(status_code=status, content=f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Plataforma IA · Ingresar</title>
<style>
:root {{ --fondo:#f6f7f9; --panel:#fff; --texto:#1c2430; --suave:#5b6675; --borde:#dde2e8; --acento:#1f6feb; --error:#c62828; }}
@media (prefers-color-scheme: dark) {{ :root {{ --fondo:#0f141a; --panel:#171d25; --texto:#e4e9ef; --suave:#98a4b3; --borde:#2a333e; --acento:#4c8dff; --error:#ff7b72; }} }}
body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:16px; background:var(--fondo); color:var(--texto);
  font:15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; box-sizing:border-box; }}
form {{ background:var(--panel); border:1px solid var(--borde); border-radius:12px; padding:24px; width:100%; max-width:360px; display:grid; gap:12px; }}
h1 {{ font-size:18px; margin:0; }} p {{ margin:0; color:var(--suave); }}
input {{ font:inherit; color:inherit; background:var(--panel); border:1px solid var(--borde); border-radius:8px; padding:9px 10px; }}
button {{ font:inherit; border:0; border-radius:8px; padding:9px; background:var(--acento); color:#fff; cursor:pointer; }}
.error {{ color:var(--error); }}
</style></head><body>
<form method="post" action="/login">
  <h1>Plataforma IA para ERP</h1>
  <p>Ingresá la contraseña del panel.</p>{aviso}
  <input type="password" name="clave" autocomplete="current-password" aria-label="Contraseña" autofocus required>
  <button>Ingresar</button>
</form></body></html>""")


async def middleware(request: Request, call_next):
    ruta = request.url.path
    if _exigida() and not _clave():
        mensaje = "Falta configurar PANEL_CLAVE en el servidor: la plataforma no se abre sin contraseña."
        return JSONResponse({"detail": mensaje}, status_code=503) if ruta != "/" else _pagina_login(mensaje, 503)
    if not _clave() or ruta in LIBRES or sesion_valida(request.cookies.get(COOKIE)):
        return await call_next(request)
    if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
        return RedirectResponse("/login", status_code=303)
    return JSONResponse({"detail": "Tenés que iniciar sesión."}, status_code=401)


def registrar(app) -> None:
    app.middleware("http")(middleware)

    @app.get("/login", include_in_schema=False)
    def ver_login():
        return _pagina_login()

    @app.post("/login", include_in_schema=False)
    async def ingresar(request: Request):
        formulario = (await request.body()).decode("utf-8", "replace")
        from urllib.parse import parse_qs
        clave = (parse_qs(formulario).get("clave") or [""])[0]
        if not _clave() or not hmac.compare_digest(clave.encode(), _clave().encode()):
            time.sleep(1)  # frena intentos por fuerza bruta
            return _pagina_login("Contraseña incorrecta.", 401)
        respuesta = RedirectResponse("/", status_code=303)
        respuesta.set_cookie(COOKIE, crear_sesion(), max_age=DURACION, httponly=True, samesite="lax",
                             secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
        return respuesta

    @app.get("/salir", include_in_schema=False)
    def salir():
        respuesta = RedirectResponse("/login", status_code=303)
        respuesta.delete_cookie(COOKIE)
        return respuesta
