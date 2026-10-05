"""API de Retail (/retail/api) y sitio de pantallas (/retail).

Todas las rutas, salvo el ingreso, exigen sesión (sesiones.contexto) y trabajan dentro de una
transacción aislada por empresa y sucursal (db.transaccion). Cada cambio queda en auditoría.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import db, permisos, seguridad, sesiones

WEB = Path(__file__).resolve().parents[1] / "web" / "retail"
api = APIRouter(prefix="/retail/api", tags=["retail"])
sitio = APIRouter(include_in_schema=False)

MONEDAS = ("ARS", "USD", "UYU")
ETIQUETA_CANAL = {"fisico": "Tienda física", "ecommerce": "E-commerce", "delivery": "Delivery", "mayorista": "Mayorista"}


def _json(valor):
    """Importes como texto (nunca float) y fechas en ISO."""
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {k: _json(v) for k, v in valor.items() if k not in ("hash_clave", "totp_secreto", "credenciales_cifradas")}
    if isinstance(valor, (list, tuple)):
        return [_json(v) for v in valor]
    return valor


def respuesta(valor, status: int = 200) -> JSONResponse:
    return JSONResponse(_json(valor), status_code=status)


def _monto(texto) -> Decimal:
    try:
        valor = Decimal(str(texto).replace(" ", ""))
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="El monto no es un número válido.")
    if not valor.is_finite():
        raise HTTPException(status_code=400, detail="El monto no es un número válido.")
    if valor < 0:
        raise HTTPException(status_code=400, detail="El monto no puede ser negativo.")
    return valor.quantize(Decimal("0.01"))


# --- sesión -----------------------------------------------------------------------------------

class Ingreso(BaseModel):
    email: str = Field(max_length=200)
    clave: str = Field(max_length=200)


class Codigo(BaseModel):
    codigo: str = Field(max_length=12)


def _cookie(respuesta_: JSONResponse, request: Request, valor: str) -> None:
    segura = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    respuesta_.set_cookie(sesiones.COOKIE, valor, max_age=int(sesiones.DURACION.total_seconds()), httponly=True,
                          samesite="lax", secure=segura, path="/")


@api.get("/estado")
def estado_base():
    """Público: si la base de Retail está lista (la pantalla de ingreso lo muestra mientras se prepara)."""
    return respuesta(db.estado())


@api.post("/sesion")
def ingresar(datos: Ingreso, request: Request):
    try:
        db.asegurar_lista()
    except db.BaseNoConfigurada as e:
        raise HTTPException(status_code=503, detail=str(e))
    valor, pendiente = sesiones.ingresar(datos.email, datos.clave, sesiones.ip_de(request))
    r = respuesta({"requiere_segundo_factor": pendiente})
    _cookie(r, request, valor)
    return r


@api.post("/sesion/segundo-factor")
def segundo_factor(datos: Codigo, request: Request):
    sesiones.confirmar_segundo_factor(request, datos.codigo)
    return respuesta({"ok": True})


@api.delete("/sesion")
def salir(request: Request):
    sesiones.salir(request)
    r = respuesta({"ok": True})
    r.delete_cookie(sesiones.COOKIE, path="/")
    return r


def suscripcion_de(ctx: db.Contexto) -> dict | None:
    if not ctx.org_id:
        return None
    from . import suscripcion
    with db.transaccion(ctx) as conn:
        return suscripcion.estado(conn, ctx.org_id)


@api.get("/yo")
def yo(ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        org = db.fila(conn, "SELECT * FROM organizaciones WHERE id=%s", (ctx.org_id,)) if ctx.org_id else None
        ubicaciones = db.filas(conn, "SELECT id, nombre, tipo FROM ubicaciones WHERE activa ORDER BY tipo='deposito', nombre")
        canales = db.filas(conn, "SELECT id, codigo, nombre FROM canales WHERE activo ORDER BY id")
        plataformas = db.filas(conn, "SELECT id, tipo, nombre, canal_id FROM plataformas WHERE activa ORDER BY nombre")
        segundo = db.fila(conn, "SELECT totp_secreto IS NOT NULL AS activo FROM usuarios WHERE id=%s", (ctx.usuario_id,))
        datos = None
        if ctx.org_id:
            datos = db.fila(conn, """SELECT (SELECT count(*) FROM productos) AS productos, (SELECT count(*) FROM proveedores) AS proveedores,
                                            (SELECT count(*) FROM productos WHERE estado_mapeo='sin_mapear') AS sin_mapear,
                                            (SELECT origen FROM tickets ORDER BY id DESC LIMIT 1) AS origen,
                                            (SELECT max(calculado_at) FROM metricas_producto_actual) AS calculado_at""")
    return respuesta({
        "usuario": {"id": ctx.usuario_id, "nombre": ctx.nombre, "email": ctx.email, "rol": ctx.rol,
                    "es_superadmin": ctx.es_superadmin, "segundo_factor": bool(segundo and segundo["activo"]),
                    "todas_ubicaciones": ctx.todas_ubicaciones},
        "empresa": org, "permisos": sorted(permisos.permisos_de(ctx)), "suscripcion": suscripcion_de(ctx),
        "ubicaciones": ubicaciones, "canales": canales, "plataformas": plataformas, "datos": datos,
    })


class CambioClave(BaseModel):
    actual: str = Field(max_length=200)
    nueva: str = Field(max_length=200)


@api.post("/yo/clave")
def cambiar_clave(datos: CambioClave, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    error = seguridad.validar_clave_nueva(datos.nueva)
    if error:
        raise HTTPException(status_code=400, detail=error)
    with db.transaccion(ctx) as conn:
        u = db.fila(conn, "SELECT hash_clave FROM usuarios WHERE id=%s", (ctx.usuario_id,))
        if not seguridad.verificar_clave(datos.actual, u["hash_clave"]):
            raise HTTPException(status_code=400, detail="La clave actual no es correcta.")
        with conn.cursor() as cur:
            cur.execute("UPDATE usuarios SET hash_clave=%s, updated_at=now() WHERE id=%s", (seguridad.hash_clave(datos.nueva), ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "cambio_clave", "usuario", ctx.usuario_id, ip=sesiones.ip_de(request))
    return respuesta({"ok": True})


@api.post("/yo/segundo-factor")
def iniciar_segundo_factor(ctx: db.Contexto = Depends(sesiones.contexto)):
    """Genera un secreto nuevo; queda activo recién cuando se confirma con un código válido."""
    secreto = seguridad.secreto_totp()
    return respuesta({"secreto": secreto, "uri": seguridad.uri_totp(secreto, ctx.email)})


class ActivarFactor(BaseModel):
    secreto: str = Field(max_length=64)
    codigo: str = Field(max_length=12)


@api.put("/yo/segundo-factor")
def activar_segundo_factor(datos: ActivarFactor, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    if not seguridad.verificar_totp(datos.secreto, datos.codigo):
        raise HTTPException(status_code=400, detail="El código no coincide. Revisá la hora del celular y probá con el código nuevo.")
    with db.transaccion(ctx) as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE usuarios SET totp_secreto=%s, updated_at=now() WHERE id=%s", (datos.secreto, ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "segundo_factor_activado", "usuario", ctx.usuario_id, ip=sesiones.ip_de(request))
    return respuesta({"ok": True})


@api.delete("/yo/segundo-factor")
def desactivar_segundo_factor(datos: Codigo, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        u = db.fila(conn, "SELECT totp_secreto FROM usuarios WHERE id=%s", (ctx.usuario_id,))
        if not u["totp_secreto"] or not seguridad.verificar_totp(u["totp_secreto"], datos.codigo):
            raise HTTPException(status_code=400, detail="El código no es válido.")
        with conn.cursor() as cur:
            cur.execute("UPDATE usuarios SET totp_secreto=NULL, updated_at=now() WHERE id=%s", (ctx.usuario_id,))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "segundo_factor_desactivado", "usuario", ctx.usuario_id, ip=sesiones.ip_de(request))
    return respuesta({"ok": True})


# --- empresa ----------------------------------------------------------------------------------

class Empresa(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    cuit: str | None = Field(default=None, max_length=20)
    zona_horaria: str = "America/Argentina/Buenos_Aires"
    moneda: str = "ARS"
    modelo_abastecimiento: str = "mixto"
    consentimiento_datos: bool = False
    modos: list[str] = Field(default_factory=lambda: ["comercio"])   # comercio, distribuidor o ambos (SPEC v2, sección 1)


def _validar_empresa(e: Empresa) -> None:
    try:
        ZoneInfo(e.zona_horaria)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status_code=400, detail="La zona horaria no es válida.")
    if e.moneda not in MONEDAS:
        raise HTTPException(status_code=400, detail=f"Moneda no admitida. Opciones: {', '.join(MONEDAS)}.")
    if e.modelo_abastecimiento not in ("centralizado", "descentralizado", "mixto"):
        raise HTTPException(status_code=400, detail="El modelo de abastecimiento tiene que ser centralizado, descentralizado o mixto.")
    if not e.modos or set(e.modos) - {"comercio", "distribuidor"}:
        raise HTTPException(status_code=400, detail="Elegí el modo de la empresa: comercio, distribuidor o ambos.")
    e.modos = sorted(set(e.modos))
    if e.cuit and not e.cuit.replace("-", "").isdigit():
        raise HTTPException(status_code=400, detail="El CUIT tiene que tener solo números (con o sin guiones).")


@api.get("/empresa")
def ver_empresa(ctx: db.Contexto = Depends(sesiones.contexto)):
    if not ctx.org_id:
        raise HTTPException(status_code=409, detail="Elegí una empresa para trabajar.")
    with db.transaccion(ctx) as conn:
        return respuesta(db.fila(conn, "SELECT * FROM organizaciones WHERE id=%s", (ctx.org_id,)))


@api.put("/empresa")
def guardar_empresa(datos: Empresa, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    _validar_empresa(datos)
    with db.transaccion(ctx) as conn:
        antes = db.fila(conn, "SELECT * FROM organizaciones WHERE id=%s", (ctx.org_id,))
        fecha = antes["consentimiento_fecha"]
        if datos.consentimiento_datos != antes["consentimiento_datos"]:
            fecha = datetime.now().astimezone() if datos.consentimiento_datos else None
        with conn.cursor() as cur:
            cur.execute("UPDATE organizaciones SET nombre=%s, cuit=%s, zona_horaria=%s, moneda=%s, modelo_abastecimiento=%s, "
                        "consentimiento_datos=%s, consentimiento_fecha=%s, modos=%s, updated_at=now() WHERE id=%s",
                        (datos.nombre.strip(), datos.cuit, datos.zona_horaria, datos.moneda, datos.modelo_abastecimiento,
                         datos.consentimiento_datos, fecha, datos.modos, ctx.org_id))
            if "distribuidor" in datos.modos:          # el distribuidor vende por el canal mayorista
                cur.execute("UPDATE canales SET activo = true WHERE codigo = 'mayorista' AND org_id = %s", (ctx.org_id,))
        cambios = {k: [antes[k], v] for k, v in datos.model_dump().items() if antes[k] != v}
        sesiones.auditar(conn, ctx, ctx.usuario_id, "modificar", "empresa", ctx.org_id, cambios, sesiones.ip_de(request))
        return respuesta(db.fila(conn, "SELECT * FROM organizaciones WHERE id=%s", (ctx.org_id,)))


# --- ubicaciones ------------------------------------------------------------------------------

class Ubicacion(BaseModel):
    nombre: str = Field(min_length=2, max_length=80)
    tipo: str = "venta"
    direccion: str | None = Field(default=None, max_length=200)
    localidad: str | None = Field(default=None, max_length=80)
    horarios: dict = Field(default_factory=dict)
    codigo_externo: str | None = Field(default=None, max_length=60)
    activa: bool = True


def _validar_ubicacion(u: Ubicacion) -> None:
    if u.tipo not in ("venta", "deposito", "ambos"):
        raise HTTPException(status_code=400, detail="El tipo tiene que ser venta, depósito o ambos.")


@api.get("/ubicaciones")
def listar_ubicaciones(ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        return respuesta(db.filas(conn, "SELECT * FROM ubicaciones ORDER BY activa DESC, tipo='deposito', nombre"))


@api.post("/ubicaciones")
def crear_ubicacion(datos: Ubicacion, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_ubicaciones")
    _validar_ubicacion(datos)
    import json
    with db.transaccion(ctx) as conn:
        if db.fila(conn, "SELECT 1 FROM ubicaciones WHERE lower(nombre)=lower(%s)", (datos.nombre.strip(),)):
            raise HTTPException(status_code=400, detail="Ya hay una sucursal o depósito con ese nombre.")
        if not ctx.es_superadmin:
            from . import suscripcion
            suscripcion.exigir_sucursal_nueva(conn, ctx.org_id, datos.tipo)
        nueva = db.fila(conn, "INSERT INTO ubicaciones (org_id, nombre, tipo, direccion, localidad, horarios, codigo_externo, activa, created_by) "
                              "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                        (ctx.org_id, datos.nombre.strip(), datos.tipo, datos.direccion, datos.localidad, json.dumps(datos.horarios),
                         datos.codigo_externo, datos.activa, ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "crear", "ubicacion", nueva["id"], datos.model_dump(), sesiones.ip_de(request))
        return respuesta(nueva, 201)


@api.put("/ubicaciones/{ubicacion_id}")
def modificar_ubicacion(ubicacion_id: int, datos: Ubicacion, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_ubicaciones")
    _validar_ubicacion(datos)
    import json
    with db.transaccion(ctx) as conn:
        antes = db.fila(conn, "SELECT * FROM ubicaciones WHERE id=%s", (ubicacion_id,))
        if not antes:
            raise HTTPException(status_code=404, detail="No existe esa sucursal.")
        if db.fila(conn, "SELECT 1 FROM ubicaciones WHERE lower(nombre)=lower(%s) AND id<>%s", (datos.nombre.strip(), ubicacion_id)):
            raise HTTPException(status_code=400, detail="Ya hay una sucursal o depósito con ese nombre.")
        nueva = db.fila(conn, "UPDATE ubicaciones SET nombre=%s, tipo=%s, direccion=%s, localidad=%s, horarios=%s, codigo_externo=%s, "
                              "activa=%s, updated_at=now() WHERE id=%s RETURNING *",
                        (datos.nombre.strip(), datos.tipo, datos.direccion, datos.localidad, json.dumps(datos.horarios),
                         datos.codigo_externo, datos.activa, ubicacion_id))
        cambios = {k: [antes[k], v] for k, v in datos.model_dump().items() if antes.get(k) != v}
        sesiones.auditar(conn, ctx, ctx.usuario_id, "modificar", "ubicacion", ubicacion_id, cambios, sesiones.ip_de(request))
        return respuesta(nueva)


# --- canales y plataformas --------------------------------------------------------------------

@api.get("/canales")
def listar_canales(ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        return respuesta({"canales": db.filas(conn, "SELECT * FROM canales ORDER BY id"),
                          "plataformas": db.filas(conn, "SELECT * FROM plataformas ORDER BY nombre")})


class CanalActivo(BaseModel):
    activo: bool


@api.put("/canales/{canal_id}")
def activar_canal(canal_id: int, datos: CanalActivo, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    with db.transaccion(ctx) as conn:
        canal = db.fila(conn, "UPDATE canales SET activo=%s, updated_at=now() WHERE id=%s RETURNING *", (datos.activo, canal_id))
        if not canal:
            raise HTTPException(status_code=404, detail="No existe ese canal.")
        sesiones.auditar(conn, ctx, ctx.usuario_id, "activar" if datos.activo else "desactivar", "canal", canal_id,
                         {"canal": canal["codigo"]}, sesiones.ip_de(request))
        return respuesta(canal)


class Plataforma(BaseModel):
    tipo: str
    nombre: str = Field(min_length=2, max_length=80)
    canal_id: int
    ubicacion_despacho_id: int | None = None


@api.post("/plataformas")
def crear_plataforma(datos: Plataforma, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "configurar_empresa")
    tipos = ('tiendanube', 'mercadolibre', 'woocommerce', 'shopify', 'vtex', 'pedidosya', 'rappi', 'caja_propia', 'odoo', 'otra')
    if datos.tipo not in tipos:
        raise HTTPException(status_code=400, detail="Tipo de plataforma no admitido.")
    with db.transaccion(ctx) as conn:
        if not db.fila(conn, "SELECT 1 FROM canales WHERE id=%s", (datos.canal_id,)):
            raise HTTPException(status_code=400, detail="No existe ese canal.")
        if datos.ubicacion_despacho_id and not db.fila(conn, "SELECT 1 FROM ubicaciones WHERE id=%s", (datos.ubicacion_despacho_id,)):
            raise HTTPException(status_code=400, detail="No existe esa sucursal.")
        nueva = db.fila(conn, "INSERT INTO plataformas (org_id, tipo, nombre, canal_id, ubicacion_despacho_id, created_by) "
                              "VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                        (ctx.org_id, datos.tipo, datos.nombre.strip(), datos.canal_id, datos.ubicacion_despacho_id, ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "crear", "plataforma", nueva["id"], datos.model_dump(), sesiones.ip_de(request))
        return respuesta(nueva, 201)


# --- usuarios ---------------------------------------------------------------------------------

ROLES_CON_SUCURSAL = ("encargado", "cajero")


class UsuarioNuevo(BaseModel):
    email: str = Field(min_length=5, max_length=200)
    nombre: str = Field(min_length=2, max_length=120)
    rol: str
    ubicaciones: list[int] = Field(default_factory=list)
    vendedor_id: int | None = None          # rol vendedor: su ficha de vendedor (modo distribuidor)


class UsuarioCambio(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    rol: str
    activo: bool = True
    ubicaciones: list[int] = Field(default_factory=list)
    vendedor_id: int | None = None


def _validar_rol(conn, rol: str, ubicaciones: list[int], vendedor_id: int | None = None) -> None:
    if rol not in permisos.PERMISOS:
        raise HTTPException(status_code=400, detail="Rol no válido.")
    if rol in ("jefe_ventas", "vendedor", "cobranzas"):
        modos = db.fila(conn, "SELECT modos FROM organizaciones WHERE id = app_org()")["modos"]
        if "distribuidor" not in modos:
            raise HTTPException(status_code=400, detail="Ese rol es del modo distribuidor: activalo primero en Configuración → Empresa.")
    if rol == "vendedor" and (not vendedor_id or not db.fila(conn, "SELECT 1 FROM vendedores WHERE id=%s", (vendedor_id,))):
        raise HTTPException(status_code=400, detail="Elegí la ficha del vendedor: así ve solo su cartera.")
    if rol in ROLES_CON_SUCURSAL and not ubicaciones:
        raise HTTPException(status_code=400, detail="Asigná al menos una sucursal a un encargado o cajero.")
    if ubicaciones:
        existentes = {f["id"] for f in db.filas(conn, "SELECT id FROM ubicaciones WHERE id = ANY(%s)", (ubicaciones,))}
        if set(ubicaciones) - existentes:
            raise HTTPException(status_code=400, detail="Alguna de las sucursales elegidas no existe.")


def _usuarios(conn, usuario_id: int | None = None) -> list[dict]:
    return db.filas(conn, "SELECT u.id, u.email, u.nombre, u.rol, u.activo, u.vendedor_id, u.ultimo_ingreso, u.totp_secreto IS NOT NULL AS segundo_factor, "
                          "u.bloqueado_hasta > now() AS bloqueado, "
                          "coalesce(array_agg(uu.ubicacion_id ORDER BY uu.ubicacion_id) FILTER (WHERE uu.ubicacion_id IS NOT NULL), '{}') AS ubicaciones "
                          "FROM usuarios u LEFT JOIN usuario_ubicaciones uu ON uu.usuario_id=u.id "
                          "WHERE u.org_id = app_org() AND (%s::bigint IS NULL OR u.id=%s) "
                          "GROUP BY u.id ORDER BY u.activo DESC, u.nombre", (usuario_id, usuario_id))


def _guardar_ubicaciones(conn, ctx, usuario_id: int, rol: str, ubicaciones: list[int]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM usuario_ubicaciones WHERE usuario_id=%s", (usuario_id,))
        if rol in ROLES_CON_SUCURSAL:
            for u in sorted(set(ubicaciones)):
                cur.execute("INSERT INTO usuario_ubicaciones (org_id, usuario_id, ubicacion_id, created_by) VALUES (%s,%s,%s,%s)",
                            (ctx.org_id, usuario_id, u, ctx.usuario_id))


@api.get("/usuarios")
def listar_usuarios(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_usuarios")
    with db.transaccion(ctx) as conn:
        return respuesta({"usuarios": _usuarios(conn),
                          "roles": db.filas(conn, "SELECT * FROM roles ORDER BY array_position(ARRAY['dueno','comprador','encargado','cajero','jefe_ventas','vendedor','cobranzas','distribuidor'], codigo)"),
                          "vendedores": db.filas(conn, "SELECT id, nombre, zona FROM vendedores WHERE activo ORDER BY nombre")})


@api.post("/usuarios")
def crear_usuario(datos: UsuarioNuevo, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_usuarios")
    email = datos.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="El email no es válido.")
    clave = seguridad.clave_temporal()
    with db.transaccion(ctx, login_email=email) as conn:
        _validar_rol(conn, datos.rol, datos.ubicaciones, datos.vendedor_id)
        if db.fila(conn, "SELECT 1 FROM usuarios WHERE lower(email)=%s", (email,)):
            raise HTTPException(status_code=400, detail="Ya existe un usuario con ese email.")
        nuevo = db.fila(conn, "INSERT INTO usuarios (org_id, email, nombre, rol, hash_clave, vendedor_id, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (ctx.org_id, email, datos.nombre.strip(), datos.rol, seguridad.hash_clave(clave),
                         datos.vendedor_id if datos.rol == "vendedor" else None, ctx.usuario_id))
        _guardar_ubicaciones(conn, ctx, nuevo["id"], datos.rol, datos.ubicaciones)
        sesiones.auditar(conn, ctx, ctx.usuario_id, "crear", "usuario", nuevo["id"],
                         {"email": email, "rol": datos.rol, "ubicaciones": datos.ubicaciones}, sesiones.ip_de(request))
        return respuesta({"usuario": _usuarios(conn, nuevo["id"])[0], "clave_temporal": clave}, 201)


@api.put("/usuarios/{usuario_id}")
def modificar_usuario(usuario_id: int, datos: UsuarioCambio, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_usuarios")
    with db.transaccion(ctx) as conn:
        antes = db.fila(conn, "SELECT id, rol, activo, nombre FROM usuarios WHERE id=%s AND org_id=app_org()", (usuario_id,))
        if not antes:
            raise HTTPException(status_code=404, detail="No existe ese usuario.")
        _validar_rol(conn, datos.rol, datos.ubicaciones, datos.vendedor_id)
        deja_de_ser_dueno = antes["rol"] == "dueno" and (datos.rol != "dueno" or not datos.activo)
        if deja_de_ser_dueno and not db.fila(conn, "SELECT 1 FROM usuarios WHERE org_id=app_org() AND rol='dueno' AND activo AND id<>%s", (usuario_id,)):
            raise HTTPException(status_code=400, detail="La empresa tiene que tener al menos un dueño activo.")
        with conn.cursor() as cur:
            cur.execute("UPDATE usuarios SET nombre=%s, rol=%s, activo=%s, vendedor_id=%s, updated_at=now() WHERE id=%s",
                        (datos.nombre.strip(), datos.rol, datos.activo, datos.vendedor_id if datos.rol == "vendedor" else None, usuario_id))
            if not datos.activo:
                cur.execute("UPDATE sesiones SET revocada=true WHERE usuario_id=%s", (usuario_id,))
        _guardar_ubicaciones(conn, ctx, usuario_id, datos.rol, datos.ubicaciones)
        sesiones.auditar(conn, ctx, ctx.usuario_id, "modificar", "usuario", usuario_id,
                         {"antes": {"rol": antes["rol"], "activo": antes["activo"]}, "despues": datos.model_dump()}, sesiones.ip_de(request))
        return respuesta(_usuarios(conn, usuario_id)[0])


@api.post("/usuarios/{usuario_id}/clave")
def blanquear_clave(usuario_id: int, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Genera una clave temporal nueva (se muestra una sola vez) y cierra las sesiones abiertas del usuario."""
    permisos.exigir(ctx, "gestionar_usuarios")
    clave = seguridad.clave_temporal()
    with db.transaccion(ctx) as conn:
        if not db.fila(conn, "SELECT 1 FROM usuarios WHERE id=%s AND org_id=app_org()", (usuario_id,)):
            raise HTTPException(status_code=404, detail="No existe ese usuario.")
        with conn.cursor() as cur:
            cur.execute("UPDATE usuarios SET hash_clave=%s, intentos_fallidos=0, bloqueado_hasta=NULL, updated_at=now() WHERE id=%s",
                        (seguridad.hash_clave(clave), usuario_id))
            cur.execute("UPDATE sesiones SET revocada=true WHERE usuario_id=%s", (usuario_id,))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "blanquear_clave", "usuario", usuario_id, ip=sesiones.ip_de(request))
    return respuesta({"clave_temporal": clave})


# --- límites de aprobación --------------------------------------------------------------------

class Limite(BaseModel):
    tipo_documento: str
    rol: str | None = None
    usuario_id: int | None = None
    monto_maximo: str


@api.get("/limites")
def listar_limites(ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_usuarios")
    with db.transaccion(ctx) as conn:
        return respuesta({"limites": db.filas(conn, "SELECT l.*, u.nombre AS usuario FROM limites_aprobacion l "
                                                    "LEFT JOIN usuarios u ON u.id=l.usuario_id ORDER BY tipo_documento, rol NULLS LAST, usuario"),
                          "tipos": permisos.TIPOS_DOCUMENTO})


@api.put("/limites")
def guardar_limite(datos: Limite, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_usuarios")
    if datos.tipo_documento not in permisos.TIPOS_DOCUMENTO:
        raise HTTPException(status_code=400, detail="Tipo de documento no válido.")
    if (datos.rol is None) == (datos.usuario_id is None):
        raise HTTPException(status_code=400, detail="El límite es para un rol o para un usuario, no ambos.")
    if datos.rol and datos.rol not in permisos.PERMISOS:
        raise HTTPException(status_code=400, detail="Rol no válido.")
    monto = _monto(datos.monto_maximo)
    with db.transaccion(ctx) as conn:
        if datos.usuario_id and not db.fila(conn, "SELECT 1 FROM usuarios WHERE id=%s AND org_id=app_org()", (datos.usuario_id,)):
            raise HTTPException(status_code=404, detail="No existe ese usuario.")
        columna = "rol" if datos.rol else "usuario_id"
        valor = datos.rol or datos.usuario_id
        existente = db.fila(conn, f"SELECT id FROM limites_aprobacion WHERE tipo_documento=%s AND {columna}=%s", (datos.tipo_documento, valor))
        if existente:
            fila = db.fila(conn, "UPDATE limites_aprobacion SET monto_maximo=%s, updated_at=now() WHERE id=%s RETURNING *", (monto, existente["id"]))
        else:
            fila = db.fila(conn, f"INSERT INTO limites_aprobacion (org_id, tipo_documento, {columna}, monto_maximo, created_by) "
                                 "VALUES (%s,%s,%s,%s,%s) RETURNING *", (ctx.org_id, datos.tipo_documento, valor, monto, ctx.usuario_id))
        sesiones.auditar(conn, ctx, ctx.usuario_id, "guardar", "limite_aprobacion", fila["id"],
                         {"tipo": datos.tipo_documento, columna: valor, "monto": monto}, sesiones.ip_de(request))
        return respuesta(fila)


@api.delete("/limites/{limite_id}")
def borrar_limite(limite_id: int, request: Request, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "gestionar_usuarios")
    with db.transaccion(ctx) as conn:
        fila = db.fila(conn, "DELETE FROM limites_aprobacion WHERE id=%s RETURNING *", (limite_id,))
        if not fila:
            raise HTTPException(status_code=404, detail="No existe ese límite.")
        sesiones.auditar(conn, ctx, ctx.usuario_id, "borrar", "limite_aprobacion", limite_id, fila, sesiones.ip_de(request))
    return respuesta({"ok": True})


@api.get("/limites/mio")
def mis_limites(ctx: db.Contexto = Depends(sesiones.contexto)):
    with db.transaccion(ctx) as conn:
        return respuesta({t: permisos.limite_aprobacion(conn, ctx, t) for t in permisos.TIPOS_DOCUMENTO})


# --- auditoría --------------------------------------------------------------------------------

@api.get("/auditoria")
def ver_auditoria(objeto: str | None = None, limite: int = 200, ctx: db.Contexto = Depends(sesiones.contexto)):
    permisos.exigir(ctx, "ver_auditoria")
    with db.transaccion(ctx) as conn:
        return respuesta(db.filas(conn, "SELECT a.*, u.nombre AS usuario FROM auditoria a LEFT JOIN usuarios u ON u.id=a.usuario_id "
                                        "WHERE a.org_id=app_org() AND (%s::text IS NULL OR a.objeto=%s) ORDER BY a.id DESC LIMIT %s",
                                  (objeto, objeto, max(1, min(limite, 1000)))))


# --- exportación a Excel ------------------------------------------------------------------------

class Exportacion(BaseModel):
    nombre: str = Field(max_length=80)
    columnas: list[str]
    filas: list[list]


@api.post("/exportar")
def exportar_excel(datos: Exportacion, ctx: db.Contexto = Depends(sesiones.contexto)):
    """Convierte lo que se ve en una tabla (ya filtrado por permisos en el servidor) en un .xlsx."""
    import io
    import re

    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook
    if len(datos.filas) > 50000:
        raise HTTPException(status_code=400, detail="Demasiadas filas para exportar de una vez (máximo 50.000).")
    libro = Workbook()
    hoja = libro.active
    hoja.title = re.sub(r"[^\w -]", "", datos.nombre)[:30] or "Datos"
    hoja.append(datos.columnas)
    for f in datos.filas:
        hoja.append([_celda(v) for v in f])
    buf = io.BytesIO()
    libro.save(buf)
    buf.seek(0)
    nombre = re.sub(r"[^\w-]", "_", datos.nombre)[:60] or "datos"
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{nombre}.xlsx"'})


def _celda(v):
    """Números como números (Excel los suma); texto que empieza con = + - @ se neutraliza (inyección de fórmulas)."""
    if isinstance(v, (int, float)):
        return v
    texto = "" if v is None else str(v)
    try:
        return float(texto) if texto.replace(".", "", 1).lstrip("-").isdigit() else (("'" + texto) if texto[:1] in "=+-@" else texto)
    except ValueError:
        return texto


# --- plataforma (superadmin) ------------------------------------------------------------------

def _superadmin(ctx: db.Contexto = Depends(sesiones.contexto)) -> db.Contexto:
    if not ctx.es_superadmin:
        raise HTTPException(status_code=403, detail="Solo para la administración de la plataforma.")
    return ctx


class EmpresaNueva(Empresa):
    email_dueno: str = Field(min_length=5, max_length=200)
    nombre_dueno: str = Field(min_length=2, max_length=120)


def crear_empresa(conn, datos: EmpresaNueva, creada_por: int | None) -> tuple[dict, str]:
    """Empresa con sus 4 canales (solo tienda física activa) y su primer dueño. Devuelve (empresa, clave temporal)."""
    org = db.fila(conn, "INSERT INTO organizaciones (nombre, cuit, zona_horaria, moneda, modelo_abastecimiento, consentimiento_datos, "
                        "consentimiento_fecha, modos, created_by) VALUES (%s,%s,%s,%s,%s,%s, CASE WHEN %s THEN now() END, %s, %s) RETURNING *",
                  (datos.nombre.strip(), datos.cuit, datos.zona_horaria, datos.moneda, datos.modelo_abastecimiento,
                   datos.consentimiento_datos, datos.consentimiento_datos, sorted(set(datos.modos or ["comercio"])), creada_por))
    with conn.cursor() as cur:
        for codigo, nombre in ETIQUETA_CANAL.items():
            cur.execute("INSERT INTO canales (org_id, codigo, nombre, activo, created_by) VALUES (%s,%s,%s,%s,%s)",
                        (org["id"], codigo, nombre, codigo == "fisico" or (codigo == "mayorista" and "distribuidor" in org["modos"]), creada_por))
    clave = seguridad.clave_temporal()
    dueno = db.fila(conn, "INSERT INTO usuarios (org_id, email, nombre, rol, hash_clave, created_by) VALUES (%s,%s,%s,'dueno',%s,%s) RETURNING id",
                    (org["id"], datos.email_dueno.strip().lower(), datos.nombre_dueno.strip(), seguridad.hash_clave(clave), creada_por))
    sesiones.auditar(conn, org["id"], creada_por, "crear", "empresa", org["id"], {"dueno": dueno["id"]})
    return org, clave


@api.get("/plataforma/empresas")
def listar_empresas(ctx: db.Contexto = Depends(_superadmin)):
    with db.transaccion(ctx, superadmin=True) as conn:
        return respuesta(db.filas(conn, "SELECT o.id, o.nombre, o.cuit, o.plan, o.activa, o.created_at, "
                                        "(SELECT count(*) FROM ubicaciones u WHERE u.org_id=o.id) AS ubicaciones, "
                                        "(SELECT count(*) FROM usuarios u WHERE u.org_id=o.id) AS usuarios "
                                        "FROM organizaciones o ORDER BY o.nombre"))


@api.post("/plataforma/empresas")
def alta_empresa(datos: EmpresaNueva, ctx: db.Contexto = Depends(_superadmin)):
    _validar_empresa(datos)
    with db.transaccion(ctx, superadmin=True) as conn:
        if db.fila(conn, "SELECT 1 FROM usuarios WHERE lower(email)=lower(%s)", (datos.email_dueno.strip(),)):
            raise HTTPException(status_code=400, detail="Ya existe un usuario con ese email.")
        org, clave = crear_empresa(conn, datos, ctx.usuario_id)
        return respuesta({"empresa": org, "clave_temporal_dueno": clave}, 201)


class Entrar(BaseModel):
    org_id: int | None


@api.post("/plataforma/entrar")
def entrar_a_empresa(datos: Entrar, request: Request, ctx: db.Contexto = Depends(_superadmin)):
    with db.transaccion(ctx, superadmin=True) as conn:
        if datos.org_id and not db.fila(conn, "SELECT 1 FROM organizaciones WHERE id=%s", (datos.org_id,)):
            raise HTTPException(status_code=404, detail="No existe esa empresa.")
        with conn.cursor() as cur:
            cur.execute("UPDATE sesiones SET org_activa=%s WHERE token_hash=%s",
                        (datos.org_id, seguridad.hash_token(request.cookies.get(sesiones.COOKIE, ""))))
        if datos.org_id:
            sesiones.auditar(conn, datos.org_id, ctx.usuario_id, "entrar_como_plataforma", "empresa", datos.org_id, ip=sesiones.ip_de(request))
    return respuesta({"ok": True})


# --- sitio ------------------------------------------------------------------------------------

@sitio.api_route("/retail", methods=["GET", "HEAD"])
def inicio_retail():
    return RedirectResponse("/retail/", status_code=307)


@sitio.api_route("/retail/{ruta:path}", methods=["GET", "HEAD"])
def pagina_retail(ruta: str):
    """Sirve la exportación estática de Next.js (frontend/ → backend/app/web/retail)."""
    if ruta.startswith("api/"):
        raise HTTPException(status_code=404)
    base = WEB.resolve()
    for candidato in (base / ruta, base / ruta / "index.html", base / f"{ruta}.html"):
        candidato = candidato.resolve()
        if candidato.is_file() and base in candidato.parents:
            return FileResponse(candidato)
    pagina_404 = base / "404.html"
    if pagina_404.exists():
        return FileResponse(pagina_404, status_code=404)
    raise HTTPException(status_code=404, detail="Todavía no se generaron las pantallas de Retail (cd frontend && npm run build).")
