"""Rutas del Centro de pruebas. Todo lo que está bajo /pruebas exige sesión de operador o tester (403 si no)."""
from __future__ import annotations

import html
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from .. import config
from ..erp import fuente
from ..permisos import Usuario, obtener_usuario
from . import almacen, cuadratura, estado, incidencias, manuales, muestra, revision, sesion, suites

WEB = Path(__file__).resolve().parents[1] / "web"
router = APIRouter()
api = APIRouter(prefix="/pruebas/api", dependencies=[Depends(sesion.probador)])


def _errores(funcion):
    try:
        return funcion()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e.args[0]))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- ingreso y página ---------------------------------------------------------------------

def _pagina_ingreso(error: str = "", status: int = 200) -> HTMLResponse:
    usuarios = [(uid, d) for uid, d in config.roles()["usuarios"].items() if d["rol"] in sesion.ROLES]
    opciones = "".join(f'<option value="{html.escape(u)}">{html.escape(d["nombre"])} · {html.escape(d["rol"])}</option>' for u, d in usuarios)
    aviso = f'<p class="error">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(status_code=status, content=f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Centro de pruebas · Ingresar</title>
<style>
:root {{ --fondo:#f6f7f9; --panel:#fff; --texto:#1c2430; --suave:#5b6675; --borde:#dde2e8; --acento:#1f6feb; --error:#c62828; }}
@media (prefers-color-scheme: dark) {{ :root {{ --fondo:#0f141a; --panel:#171d25; --texto:#e4e9ef; --suave:#98a4b3; --borde:#2a333e; --acento:#4c8dff; --error:#ff7b72; }} }}
body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:16px; background:var(--fondo); color:var(--texto);
  font:15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; box-sizing:border-box; }}
form {{ background:var(--panel); border:1px solid var(--borde); border-radius:12px; padding:24px; width:100%; max-width:360px; display:grid; gap:12px; }}
h1 {{ font-size:18px; margin:0; }} p {{ margin:0; color:var(--suave); }}
select, input {{ font:inherit; color:inherit; background:var(--panel); border:1px solid var(--borde); border-radius:8px; padding:9px 10px; }}
button {{ font:inherit; border:0; border-radius:8px; padding:9px; background:var(--acento); color:#fff; cursor:pointer; }}
.error {{ color:var(--error); }} a {{ color:var(--acento); }}
</style></head><body>
<form method="post" action="/pruebas/ingresar">
  <h1>Centro de pruebas</h1>
  <p>Solo para los roles operador y tester.</p>{aviso}
  <select name="usuario_id" aria-label="Usuario">{opciones}</select>
  <input type="password" name="clave" autocomplete="current-password" aria-label="Clave" placeholder="Clave" required>
  <button>Ingresar</button>
  <p><a href="/">Volver a la plataforma</a></p>
</form></body></html>""")


@router.get("/pruebas", include_in_schema=False)
def pagina(request: Request):
    usuario_id = sesion.leer(request.cookies.get(sesion.COOKIE))
    if not usuario_id:
        return RedirectResponse("/pruebas/ingresar", status_code=303)
    try:
        sesion.probador(request)
    except HTTPException:
        return HTMLResponse("<p>El Centro de pruebas es solo para los roles operador y tester.</p>", status_code=403)
    return FileResponse(WEB / "pruebas.html")


@router.get("/pruebas/ingresar", include_in_schema=False)
def ver_ingreso():
    return _pagina_ingreso()


@router.post("/pruebas/ingresar", include_in_schema=False)
async def ingresar(request: Request):
    datos = parse_qs((await request.body()).decode("utf-8", "replace"))
    usuario_id, clave = (datos.get("usuario_id") or [""])[0], (datos.get("clave") or [""])[0]
    u = sesion.verificar_clave(usuario_id, clave)
    if not u:
        import time
        time.sleep(1)
        almacen.auditar(usuario_id or "?", "ingreso_fallido", "centro_de_pruebas")
        return _pagina_ingreso("Usuario o clave incorrectos, o el usuario no es operador ni tester.", 401)
    almacen.auditar(u, "ingreso", "centro_de_pruebas")
    r = RedirectResponse("/pruebas", status_code=303)
    r.set_cookie(sesion.COOKIE, sesion.crear(u.id), max_age=sesion.DURACION, httponly=True, samesite="lax",
                 secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
    return r


@router.get("/pruebas/salir", include_in_schema=False)
def salir(request: Request):
    usuario_id = sesion.leer(request.cookies.get(sesion.COOKIE))
    if usuario_id:
        almacen.auditar(usuario_id, "salida", "centro_de_pruebas")
    r = RedirectResponse("/", status_code=303)
    r.delete_cookie(sesion.COOKIE)
    r.delete_cookie(sesion.COOKIE_VER_COMO)
    return r


@router.get("/ver-como/estado")
def estado_ver_como(request: Request):
    """Para el banner del panel principal: si este navegador está en modo «ver como» (solo lectura)."""
    simulado = sesion.ver_como_activo(request)
    return {"activo": bool(simulado), "usuario_id": simulado, "nombre": _nombre_usuario(simulado) if simulado else None,
            "probador": bool(sesion.leer(request.cookies.get(sesion.COOKIE)))}


def _nombre_usuario(usuario_id: str) -> str:
    if usuario_id.startswith("vendedor:"):
        return f"Vendedor {usuario_id.split(':', 1)[1]}"
    try:
        u = obtener_usuario(usuario_id)
        return f"{u.nombre} ({u.rol})"
    except Exception:
        return usuario_id


# --- API --------------------------------------------------------------------------------

class Texto(BaseModel):
    texto: str = ""


class PedidoMuestra(BaseModel):
    metrica: str
    desde: str
    hasta: str


class Marca(BaseModel):
    resultado: str
    comentario: str | None = None


class EjecucionManual(BaseModel):
    estado: str
    comentario: str | None = None
    evidencia_id: int | None = None


class CambioIncidencia(BaseModel):
    estado: str | None = None
    responsable: str | None = None
    test_regresion: str | None = None
    definicion: str | None = None
    causa: str | None = None
    comentario: str | None = None


class NuevaIncidencia(BaseModel):
    titulo: str
    tipo: str = "datos"
    descripcion: str = ""
    metrica: str | None = None
    pantalla: str | None = None
    registro_clave: str | None = None
    fecha_dato: str | None = None
    causa: str | None = None
    evidencia: dict | None = None
    origen: str = "muestra"


class Suites(BaseModel):
    suites: list[str] = []


class VerComo(BaseModel):
    usuario_id: str


@api.get("/sesion")
def ver_sesion(u: Usuario = Depends(sesion.probador)):
    return {"usuario_id": u.id, "nombre": u.nombre, "rol": u.rol, "fuente": fuente.actual()}


@api.get("/estado")
def ver_estado():
    return estado.general()


@api.get("/cuadratura")
def ver_cuadratura(metrica: str = "ventas"):
    return _errores(lambda: {**cuadratura.ficha(metrica), "metricas": cuadratura.METRICAS, "marcha_blanca": cuadratura.marcha_blanca()})


@api.post("/cuadratura/verificar")
def reverificar(u: Usuario = Depends(sesion.probador)):
    """Vuelve a verificar: sincroniza Odoo (que compara contra su reporte) y registra el día."""
    from ..integraciones import gestor
    if fuente.actual() != "odoo":
        raise HTTPException(status_code=400, detail="La fuente activa no es Odoo: no hay sistema de origen para verificar.")
    almacen.auditar(u, "reverificar_cuadratura", "ventas")
    from ..main import _usar_odoo
    if not gestor.sincronizar_en_segundo_plano(_usar_odoo):
        raise HTTPException(status_code=409, detail="Ya hay una sincronización en curso.")
    return {"ok": True, "mensaje": "Verificación en curso: tarda lo mismo que una sincronización."}


@api.post("/cuadratura/descubrir")
def descubrir(u: Usuario = Depends(sesion.probador), metrica: str = "ventas"):
    almacen.auditar(u, "descubrir_definicion", metrica)
    return {"ok": False, "pendiente": True, "mensaje": "El descubrimiento automático de la definición espejo se implementa con "
            "docs/16_cuadratura_con_origen.md (checklist completo). Mientras tanto se usa la definición fija indicada en la ficha."}


@api.get("/cuadratura/diferencias")
def ver_diferencias(mes: str, u: Usuario = Depends(sesion.probador)):
    almacen.auditar(u, "por_que_difiere", "ventas", {"mes": mes})
    return _errores(lambda: cuadratura.diferencias(mes))


@api.get("/integridad")
def integridad():
    from ..analisis import cobertura as cob
    from ..integraciones import gestor
    est = gestor.estado_odoo() if fuente.actual() == "odoo" else None
    ultima = (est or {}).get("ultima_ok") or {}
    try:
        c = cob.cobertura()
    except Exception as e:
        c = {"pilares": [], "controles": [{"nivel": "error", "texto": f"No se pudo calcular: {e}"}]}
    return {"fuente": fuente.actual(), "resumen": fuente.resumen(), "sincronizacion": {"fecha": ultima.get("fecha"), "segundos": ultima.get("segundos"),
            "conteos": ultima.get("conteos"), "avisos": ultima.get("avisos", [])} if est else None,
            "cobertura": c, "reconciliacion": cuadratura.ultima_reconciliacion(),
            "pendiente": "Totales de control por capa (crudo, intermedio, final) y DQ-25 a DQ-27: llegan con la capa de ingesta de docs/16."}


@api.post("/integridad/reconciliar")
def reconciliar(u: Usuario = Depends(sesion.probador)):
    almacen.auditar(u, "reconciliar_ids", "ventas")
    return _errores(lambda: cuadratura.reconciliar_claves())


@api.post("/muestra")
def nueva_muestra(datos: PedidoMuestra, u: Usuario = Depends(sesion.probador)):
    almacen.auditar(u, "tomar_muestra", datos.metrica, datos.model_dump())
    return _errores(lambda: muestra.tomar(datos.metrica, datos.desde, datos.hasta, u.nombre))


@api.get("/muestra")
def lotes_muestra():
    return {"lotes": muestra.lotes(), "metricas": muestra.METRICAS}


@api.get("/muestra/{lote}")
def ver_muestra(lote: str):
    return _errores(lambda: muestra.ver(lote))


@api.post("/muestra/registro/{id_}")
def marcar_muestra(id_: int, datos: Marca, u: Usuario = Depends(sesion.probador)):
    almacen.auditar(u, "marcar_muestra", str(id_), datos.model_dump())
    return _errores(lambda: muestra.marcar(id_, datos.resultado, datos.comentario, u.nombre))


@api.get("/suites")
def ver_suites():
    return suites.resumen()


@api.post("/suites/correr")
def correr_suites(datos: Suites, u: Usuario = Depends(sesion.probador)):
    elegidas = datos.suites or [s["id"] for s in suites.SUITES]
    almacen.auditar(u, "correr_suites", ",".join(elegidas))
    if not suites.correr_en_segundo_plano(elegidas, u.nombre):
        raise HTTPException(status_code=409, detail="Ya hay pruebas corriendo.")
    return suites.resumen()


@api.get("/manuales")
def ver_manuales():
    return {"casos": manuales.listar()}


@api.post("/manuales/{caso_id}")
def ejecutar_manual(caso_id: int, datos: EjecucionManual, u: Usuario = Depends(sesion.probador)):
    almacen.auditar(u, "prueba_manual", str(caso_id), datos.model_dump())
    return _errores(lambda: manuales.ejecutar(caso_id, datos.estado, u.nombre, datos.comentario, datos.evidencia_id))


@api.post("/evidencias")
async def subir_evidencia(archivo: UploadFile = File(...), u: Usuario = Depends(sesion.probador)):
    contenido = await archivo.read()
    r = _errores(lambda: manuales.guardar_evidencia(archivo.filename or "evidencia", archivo.content_type or "", contenido, u.nombre))
    almacen.auditar(u, "subir_evidencia", r["nombre"])
    return r


@api.get("/evidencias/{id_}")
def ver_evidencia(id_: int):
    e = manuales.obtener_evidencia(id_)
    if not e:
        raise HTTPException(status_code=404, detail="No existe esa evidencia.")
    return FileResponse(almacen.EVIDENCIAS / e["ruta"], media_type=e["tipo"], filename=e["nombre"])


@api.get("/incidencias")
def ver_incidencias(filtro: str | None = Query(None, alias="estado"), origen: str | None = None):
    return {"incidencias": incidencias.listar(filtro, origen), "causas": incidencias.CAUSAS, "estados": incidencias.ESTADOS,
            "tipos": incidencias.TIPOS}


@api.post("/incidencias")
def nueva_incidencia(datos: NuevaIncidencia, u: Usuario = Depends(sesion.probador)):
    almacen.auditar(u, "crear_incidencia", datos.titulo)
    return _errores(lambda: incidencias.obtener(incidencias.crear(
        datos.origen, datos.titulo, u.nombre, tipo=datos.tipo, descripcion=datos.descripcion, metrica=datos.metrica, pantalla=datos.pantalla,
        fuente=fuente.actual(), fecha_dato=datos.fecha_dato, registro_clave=datos.registro_clave, causa=datos.causa, evidencia=datos.evidencia)))


@api.get("/incidencias/{id_}")
def ver_incidencia(id_: int):
    return _errores(lambda: incidencias.obtener(id_))


@api.post("/incidencias/{id_}")
def cambiar_incidencia(id_: int, datos: CambioIncidencia, u: Usuario = Depends(sesion.probador)):
    almacen.auditar(u, "actualizar_incidencia", str(id_), datos.model_dump(exclude_none=True))
    return _errores(lambda: incidencias.actualizar(id_, u.nombre, **datos.model_dump()))


@api.post("/incidencias/{id_}/caso-regresion")
def caso_regresion(id_: int, u: Usuario = Depends(sesion.probador)):
    almacen.auditar(u, "crear_caso_regresion", str(id_))
    return _errores(lambda: incidencias.crear_caso_regresion(id_, u.nombre))


@api.post("/revision")
def lanzar_revision(u: Usuario = Depends(sesion.probador)):
    almacen.auditar(u, "revision_independiente", "")
    if not revision.en_segundo_plano(u.nombre):
        raise HTTPException(status_code=409, detail="Ya hay una revisión en curso.")
    return revision.ultima()


@api.get("/revision")
def ver_revision():
    return revision.ultima()


@api.get("/usuarios")
def usuarios_para_ver_como():
    from ..erp import conector
    lista = [{"id": uid, "nombre": d["nombre"], "rol": d["rol"]} for uid, d in config.roles()["usuarios"].items()
             if d["rol"] not in sesion.ROLES]
    try:
        lista += [{"id": f"vendedor:{int(v[0])}", "nombre": v[1] or f"Vendedor {v[0]}", "rol": "vendedor"}
                  for v in conector.consultar("SELECT id, nombre FROM vendedores ORDER BY nombre", max_filas=500)["filas"] if v[0] is not None]
    except Exception:
        pass
    return lista


@api.post("/ver-como")
def activar_ver_como(datos: VerComo, request: Request, u: Usuario = Depends(sesion.probador)):
    almacen.auditar(u, "ver_como_inicio", datos.usuario_id, ver_como=datos.usuario_id)
    r = JSONResponse({"ok": True, "usuario_id": datos.usuario_id, "nombre": _nombre_usuario(datos.usuario_id)})
    r.set_cookie(sesion.COOKIE_VER_COMO, sesion.crear(datos.usuario_id), max_age=4 * 3600, httponly=True, samesite="lax",
                 secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
    return r


@api.post("/ver-como/salir")
def salir_ver_como(request: Request, u: Usuario = Depends(sesion.probador)):
    almacen.auditar(u, "ver_como_fin", sesion.ver_como_activo(request) or "", ver_como=sesion.ver_como_activo(request))
    r = JSONResponse({"ok": True})
    r.delete_cookie(sesion.COOKIE_VER_COMO)
    return r


@api.get("/auditoria")
def ver_auditoria():
    return {"eventos": almacen.filas("SELECT * FROM auditoria ORDER BY id DESC LIMIT 200")}
