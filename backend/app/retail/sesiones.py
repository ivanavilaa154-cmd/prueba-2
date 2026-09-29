"""Ingreso con email y clave (+ segundo factor opcional), sesiones y bloqueo por intentos."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from . import db, seguridad

COOKIE = "retail_sesion"
DURACION = timedelta(hours=12)
MAX_INTENTOS = 5
BLOQUEO = timedelta(minutes=15)
ROLES_TODAS = ("dueno", "comprador")


def auditar(conn, ctx_o_org, usuario_id: int | None, accion: str, objeto: str, objeto_id=None, detalle: dict | None = None,
            ip: str | None = None) -> None:
    import json
    org_id = ctx_o_org.org_id if isinstance(ctx_o_org, db.Contexto) else ctx_o_org
    with conn.cursor() as cur:
        cur.execute("INSERT INTO auditoria (org_id, usuario_id, accion, objeto, objeto_id, detalle, ip) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (org_id, usuario_id, accion, objeto, None if objeto_id is None else str(objeto_id),
                     json.dumps(detalle or {}, ensure_ascii=False, default=str), ip))


def ip_de(request: Request) -> str | None:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else None)


def ingresar(email: str, clave: str, ip: str | None) -> tuple[str, bool]:
    """Devuelve (token, requiere_segundo_factor). Error 401/423 con un mensaje claro."""
    email = (email or "").strip().lower()
    ahora = datetime.now(timezone.utc)
    with db.transaccion(login_email=email) as conn:
        u = db.fila(conn, "SELECT * FROM usuarios WHERE lower(email)=%s", (email,))
        if not u or not u["activo"]:
            seguridad.verificar_clave(clave, seguridad.HASH_FICTICIO)
            auditar(conn, None, None, "ingreso_fallido", "sesion", detalle={"email": email}, ip=ip)
            conn.commit()
            raise HTTPException(status_code=401, detail="Email o clave incorrectos.")
        with conn.cursor() as cur:   # desde acá, la auditoría queda en la empresa del usuario
            cur.execute("SELECT set_config('app.org_id', %s, true), set_config('app.usuario_id', %s, true)",
                        ("" if u["org_id"] is None else str(u["org_id"]), str(u["id"])))
        if u["bloqueado_hasta"] and u["bloqueado_hasta"] > ahora:
            minutos = int((u["bloqueado_hasta"] - ahora).total_seconds() // 60) + 1
            raise HTTPException(status_code=423, detail=f"Demasiados intentos fallidos. Probá de nuevo en {minutos} minutos.")
        if not seguridad.verificar_clave(clave, u["hash_clave"]):
            intentos = u["intentos_fallidos"] + 1
            bloqueo = ahora + BLOQUEO if intentos >= MAX_INTENTOS else None
            with conn.cursor() as cur:
                cur.execute("UPDATE usuarios SET intentos_fallidos=%s, bloqueado_hasta=%s WHERE id=%s",
                            (0 if bloqueo else intentos, bloqueo, u["id"]))
            auditar(conn, u["org_id"], u["id"], "ingreso_fallido", "sesion", detalle={"intentos": intentos}, ip=ip)
            conn.commit()
            raise HTTPException(status_code=401, detail="Email o clave incorrectos.")
        valor = seguridad.token()
        pendiente = bool(u["totp_secreto"])
        with conn.cursor() as cur:
            cur.execute("UPDATE usuarios SET intentos_fallidos=0, bloqueado_hasta=NULL, ultimo_ingreso=now() WHERE id=%s", (u["id"],))
            cur.execute("INSERT INTO sesiones (usuario_id, token_hash, pendiente_2fa, vence, ip) VALUES (%s, %s, %s, %s, %s)",
                        (u["id"], seguridad.hash_token(valor), pendiente, ahora + DURACION, ip))
        auditar(conn, u["org_id"], u["id"], "ingreso" if not pendiente else "ingreso_clave_ok", "sesion", ip=ip)
    return valor, pendiente


def _sesion(request: Request) -> dict | None:
    valor = request.cookies.get(COOKIE)
    if not valor:
        return None
    with db.transaccion() as conn:
        return db.fila(conn, "SELECT * FROM sesiones WHERE token_hash=%s AND NOT revocada AND vence > now()",
                       (seguridad.hash_token(valor),))


def confirmar_segundo_factor(request: Request, codigo: str) -> None:
    s = _sesion(request)
    if not s or not s["pendiente_2fa"]:
        raise HTTPException(status_code=401, detail="La sesión venció. Ingresá de nuevo.")
    with db.transaccion(usuario_id=s["usuario_id"]) as conn:
        u = db.fila(conn, "SELECT id, org_id, totp_secreto FROM usuarios WHERE id=%s", (s["usuario_id"],))
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.org_id', %s, true)", ("" if u["org_id"] is None else str(u["org_id"]),))
        if not u["totp_secreto"] or not seguridad.verificar_totp(u["totp_secreto"], codigo):
            auditar(conn, u["org_id"], u["id"], "segundo_factor_fallido", "sesion", ip=ip_de(request))
            conn.commit()
            raise HTTPException(status_code=401, detail="El código no es válido.")
        with conn.cursor() as cur:
            cur.execute("UPDATE sesiones SET pendiente_2fa=false WHERE id=%s", (s["id"],))
        auditar(conn, u["org_id"], u["id"], "ingreso", "sesion", detalle={"segundo_factor": True}, ip=ip_de(request))


def salir(request: Request) -> None:
    valor = request.cookies.get(COOKIE)
    if valor:
        with db.transaccion() as conn, conn.cursor() as cur:
            cur.execute("UPDATE sesiones SET revocada=true WHERE token_hash=%s", (seguridad.hash_token(valor),))


def contexto_de_sesion(s: dict) -> db.Contexto:
    with db.transaccion(usuario_id=s["usuario_id"]) as conn:
        u = db.fila(conn, "SELECT id, org_id, rol, nombre, email, es_superadmin, activo FROM usuarios WHERE id=%s", (s["usuario_id"],))
        if not u or not u["activo"]:
            raise HTTPException(status_code=401, detail="Tu usuario está desactivado.")
        org_id = s["org_activa"] if u["es_superadmin"] else u["org_id"]
        ctx = db.Contexto(usuario_id=u["id"], org_id=org_id, rol=u["rol"], nombre=u["nombre"], email=u["email"],
                          es_superadmin=u["es_superadmin"])
        if u["es_superadmin"] or u["rol"] in ROLES_TODAS:
            ctx.todas_ubicaciones = True
        elif org_id:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))
            ctx.ubicaciones = [f["ubicacion_id"] for f in db.filas(
                conn, "SELECT ubicacion_id FROM usuario_ubicaciones WHERE usuario_id=%s ORDER BY ubicacion_id", (u["id"],))]
    return ctx


def contexto(request: Request) -> db.Contexto:
    """Dependencia de todas las rutas de Retail: sin sesión válida → 401."""
    try:
        db.asegurar_lista()
    except db.BaseNoConfigurada as e:
        raise HTTPException(status_code=503, detail=str(e))
    s = _sesion(request)
    if not s:
        raise HTTPException(status_code=401, detail="Ingresá con tu email y tu clave.")
    if s["pendiente_2fa"]:
        raise HTTPException(status_code=401, detail="Falta el código del segundo factor.")
    ctx = contexto_de_sesion(s)
    from . import suscripcion
    suscripcion.exigir_escritura(request, ctx)          # suscripción vencida → solo lectura (13.6)
    return ctx


def sesion_actual(request: Request) -> dict | None:
    return _sesion(request) if db.configurada() else None
