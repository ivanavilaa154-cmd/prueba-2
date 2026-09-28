"""API de la plataforma.

Levantar:  uvicorn app.main:app --reload   (desde la carpeta backend)
Preview:   http://localhost:8000
Docs:      http://localhost:8000/docs
"""
from __future__ import annotations

import os
import re
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import acceso, config
from .actividades import motor as actividades
from .analisis import catalogo_kpis
from .analisis import cobertura as cobertura_analisis
from .analisis import tablero as tablero_analisis
from .chat import motor
from .decisiones import credito
from .erp import conector, fuente, importar
from .gestion import objetivos as gestion_objetivos
from .gestion import procesos as gestion_procesos
from .gestion import servicio as gestion
from .pruebas import cuadratura as pruebas_cuadratura
from .pruebas import rutas as pruebas_rutas
from .pruebas import sesion as pruebas_sesion
from .retail import db as retail_db
from .retail import api_comprar as retail_comprar
from .retail import api_documentos as retail_documentos
from .retail import api_ingesta as retail_ingesta
from .retail import api_plata as retail_plata
from .retail import api_sucursales as retail_sucursales
from .retail import api_analisis as retail_analisis
from .retail import api_canales as retail_canales
from .retail import api_copiloto as retail_copiloto
from .retail import api_impacto as retail_impacto
from .retail import api_avisos as retail_avisos
from .retail import api_precios as retail_precios
from .retail import api_ventas as retail_ventas
from .retail import rutas as retail_rutas
from .integraciones import gestor, odoo
from .permisos import AccesoDenegado, Usuario, obtener_usuario, preparar_consulta

WEB = Path(__file__).resolve().parent / "web"


def _revisar_actividades() -> None:
    """Vuelve a correr las reglas de actividades con los datos nuevos, sin frenar a quien llamó."""
    def correr():
        try:
            actividades.ejecutar()
        except Exception:  # una regla que falla no rompe la sincronización; se reintenta al abrir la pestaña
            pass
    threading.Thread(target=correr, daemon=True).start()


def _usar_odoo(entrada: dict) -> None:
    if entrada["ok"]:
        fuente.usar("odoo")
        try:
            pruebas_cuadratura.registrar_control(entrada)   # verificación del día contra el reporte de Odoo
        except Exception:
            pass
        _revisar_actividades()

@asynccontextmanager
async def _ciclo_de_vida(_app):
    # Un .env de una versión anterior no trae las claves del Centro de pruebas: se agregan las de ejemplo.
    if "pytest" not in sys.modules:
        agregadas = pruebas_sesion.asegurar_claves_demo()
        if agregadas:
            print(f"Centro de pruebas: se agregaron las claves de ejemplo {', '.join(agregadas)} a backend/.env (cambialas antes de publicar).")
    # Retail: la base PostgreSQL se migra al arrancar y, si está vacía, se cargan las empresas demo.
    # En segundo plano: si PostgreSQL todavía se está instalando, la plataforma igual arranca y Retail se conecta después.
    if "pytest" not in sys.modules:
        def _preparar_retail():
            try:
                retail_db.asegurar_lista()
            except retail_db.BaseNoConfigurada as e:
                print(f"Retail: {e}")
                return
            from .retail import demo as retail_demo
            from .retail import motor as retail_motor
            try:
                resumen = retail_demo.preparar()
                if resumen:
                    print(f"Retail: demo del NOA lista ({resumen}).")
            except Exception as e:
                print(f"Retail: no se pudo cargar la demo ({type(e).__name__}: {str(e)[:200]}).")
            retail_motor.iniciar_programador()
        threading.Thread(target=_preparar_retail, daemon=True).start()
    # Las bases locales creadas con una versión anterior se completan con las tablas y columnas nuevas.
    from .erp import modelo
    for url in fuente.opciones().values():
        if url and url.startswith("sqlite:///"):
            modelo.actualizar_base(url.replace("sqlite:///", "", 1))
    conector.olvidar_conexiones()
    # Si Odoo ya está configurado y sincronizado, se arranca con sus datos.
    odoo_listo = not os.getenv("ERP_URL") and gestor.config_odoo()["clave_guardada"]
    if odoo_listo and fuente.RUTA_ODOO.exists():
        fuente.usar("odoo")
    elif odoo_listo:
        # En un servidor nuevo (o que se reinició) todavía no hay datos: se sincroniza al arrancar.
        gestor.sincronizar_en_segundo_plano(_usar_odoo)
    gestor.iniciar_programador(lambda entrada: _usar_odoo(entrada) if fuente.actual() in ("demo", "odoo") else None)
    try:
        gestion.sembrar_demo()
    except Exception:
        pass  # los ejemplos de la demo son opcionales
    gestion.iniciar_ciclo()
    yield


app = FastAPI(title="Plataforma IA para ERP", version="0.1.0", lifespan=_ciclo_de_vida)


@app.middleware("http")
async def _solo_lectura_en_ver_como(request, call_next):
    """En modo «ver como usuario» (Centro de pruebas) no se puede cambiar nada, salvo salir del modo."""
    permitidas = ("/pruebas/api/ver-como/salir", "/pruebas/salir", "/login", "/salir")
    if request.method not in ("GET", "HEAD", "OPTIONS") and not request.url.path.startswith(permitidas) \
            and pruebas_sesion.ver_como_activo(request):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Estás en modo «ver como usuario»: es solo lectura. Salí del modo para hacer cambios."},
                            status_code=403)
    return await call_next(request)


acceso.registrar(app)
app.include_router(pruebas_rutas.router)
app.include_router(pruebas_rutas.api)
app.include_router(retail_rutas.api)
app.include_router(retail_comprar.api)
app.include_router(retail_documentos.api)
app.include_router(retail_ventas.api)
app.include_router(retail_precios.api)
app.include_router(retail_avisos.api)
app.include_router(retail_ingesta.api)
app.include_router(retail_plata.api)
app.include_router(retail_sucursales.api)
app.include_router(retail_analisis.api)
app.include_router(retail_canales.api)
app.include_router(retail_copiloto.api)
app.include_router(retail_impacto.api)
app.include_router(retail_rutas.sitio)   # último: sirve las pantallas en /retail/…


class PreguntaChat(BaseModel):
    usuario_id: str
    mensaje: str
    historial: list[dict] = []


class SimulacionCredito(BaseModel):
    compra_mensual_cliente: float
    margen_bruto: float
    dias_cobro_reales: float
    dias_inventario: float
    dias_pago_proveedores: float
    costo_servir: float
    incobrabilidad: float
    punto_mas_bajo_caja: float
    costo_dinero_mensual: float | None = None
    caja_minima: float | None = None
    descubierto_disponible: float | None = None
    clientes_solicitados: int | None = None


class ConsultaDirecta(BaseModel):
    usuario_id: str
    sql: str


class CambioFuente(BaseModel):
    fuente: str


class CambioActividad(BaseModel):
    usuario_id: str
    estado: str                      # en_curso | resuelta | descartada
    resolucion: str | None = None
    comentario: str | None = None


class PropuestaObjetivo(BaseModel):
    usuario_id: str
    plantilla_id: str
    alcance_tipo: str | None = None
    alcance_valor: str | None = None
    periodicidad: str | None = None
    meta: float | None = None
    responsable_rol: str | None = None
    cascada_tiempo: list[str] = []
    cascada_alcance: str | None = None
    justificacion: str | None = None

    def argumentos(self) -> dict:
        return self.model_dump(exclude={"usuario_id", "justificacion"})


class Comentario(BaseModel):
    usuario_id: str
    texto: str


class EventoProceso(BaseModel):
    usuario_id: str
    caso_key: str
    codigo: str
    fecha: str | None = None
    resultado: str | None = None
    detalle: str | None = None


class ConfigOdoo(BaseModel):
    url: str
    db: str
    usuario: str
    api_key: str = ""  # vacía = usar la guardada
    meses: int = 12
    cada_min: int = 0




def _chat_habilitado() -> bool:
    clave = os.getenv("ANTHROPIC_API_KEY", "")
    return bool(clave) and clave != "sk-ant-..."


def _usuario(usuario_id: str) -> Usuario:
    """Usuario de roles.yaml o, en el preview, "vendedor:<id>" para ver como cualquier vendedor.

    Todavía no hay login (Fase 3): quien usa la API elige el usuario. Por eso el
    servidor solo debe escuchar en 127.0.0.1 hasta que haya autenticación.
    """
    try:
        if usuario_id.startswith("vendedor:"):
            vendedor_id = int(usuario_id.split(":", 1)[1])
            return Usuario(id=usuario_id, nombre=f"Vendedor {vendedor_id}", rol="vendedor", vendedor_id=vendedor_id)
        return obtener_usuario(usuario_id)
    except (AccesoDenegado, ValueError) as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.get("/", include_in_schema=False)
def preview():
    return FileResponse(WEB / "index.html")


def _version() -> str | None:
    """Versión del código que está corriendo (commit y fecha), para saber si el Codespace se actualizó."""
    import subprocess
    try:
        return subprocess.run(["git", "log", "-1", "--format=%h del %ad", "--date=format:%d/%m %H:%M"], cwd=config.RAIZ,
                              capture_output=True, text=True, timeout=3).stdout.strip() or None
    except Exception:
        return None


VERSION = _version()


@app.get("/salud")
def salud():
    return {"estado": "ok", "empresa": config.empresa()["EMPRESA"], "modelo": config.ANTHROPIC_MODEL, "version": VERSION,
            "chat_habilitado": _chat_habilitado(), "fuente": fuente.actual(), "con_clave": bool(os.getenv("PANEL_CLAVE"))}


@app.post("/chat")
def chat(pregunta: PreguntaChat):
    usuario = _usuario(pregunta.usuario_id)
    if not _chat_habilitado():
        raise HTTPException(status_code=503, detail="Falta ANTHROPIC_API_KEY en backend/.env para usar el chat.")
    r = motor.responder(pregunta.mensaje, usuario, pregunta.historial)
    return {"respuesta": r.texto, "herramientas_usadas": r.herramientas_usadas, "historial": r.historial}


@app.get("/tablero")
def tablero(usuario_id: str, mes: str | None = None):
    """Indicadores de Ventas, Inventario y Finanzas de un mes (AAAA-MM), con los permisos del usuario.

    Sin mes, el más reciente con ventas. La respuesta trae la lista de meses para elegir.
    """
    if mes is not None and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
        raise HTTPException(status_code=400, detail="El mes tiene que tener el formato AAAA-MM, por ejemplo 2026-09.")
    return tablero_analisis.tablero(_usuario(usuario_id), mes)


@app.get("/cobertura")
def cobertura():
    """Qué datos trajo la fuente activa, tabla por tabla, y controles de calidad."""
    return cobertura_analisis.cobertura()


@app.get("/kpis/catalogo")
def kpis_catalogo():
    """Los 111 KPIs estándar y cuáles tienen sus datos base en la fuente activa."""
    return catalogo_kpis.estado()


@app.get("/usuarios")
def usuarios():
    """Usuarios de demo y, si la fuente tiene vendedores, uno por vendedor para probar carteras."""
    lista = [{"id": uid, "nombre": d["nombre"], "rol": d["rol"]} for uid, d in config.roles()["usuarios"].items()
             if d["rol"] not in ("operador", "tester")]   # esos entran con su clave al Centro de pruebas
    try:
        vendedores = conector.consultar("SELECT id, nombre FROM vendedores ORDER BY nombre", max_filas=500)
        lista += [{"id": f"vendedor:{int(v[0])}", "nombre": v[1] or f"Vendedor {v[0]}", "rol": "vendedor"}
                  for v in vendedores["filas"] if v[0] is not None]
    except Exception:
        pass  # la fuente no tiene tabla de vendedores
    return lista


@app.post("/consulta")
def consulta(datos: ConsultaDirecta):
    """Ejecuta un SELECT como el usuario elegido: mismas barreras que usa el chat."""
    usuario = _usuario(datos.usuario_id)
    try:
        ejecutado = preparar_consulta(usuario, conector.validar_sql(datos.sql), conector.dialecto(config.ERP_URL))
        resultado = conector.consultar(datos.sql, usuario=usuario)
    except (conector.ConsultaNoPermitida, AccesoDenegado) as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {str(e).splitlines()[0]}")
    return {**resultado, "sql_ejecutado": ejecutado}


@app.get("/fuente")
def ver_fuente():
    return fuente.resumen()


@app.post("/fuente")
def cambiar_fuente(datos: CambioFuente):
    try:
        fuente.usar(datos.fuente)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return fuente.resumen()


@app.post("/importar")
async def importar_archivos(archivos: list[UploadFile] = File(...)):
    """Carga exportaciones del ERP (CSV/Excel) en una base local y pasa a usarla."""
    recibidos = [(a.filename or "sin_nombre", await a.read()) for a in archivos]
    conector.olvidar_conexiones()
    try:
        informe = importar.importar(recibidos)
    except importar.ErrorImportacion as e:
        raise HTTPException(status_code=400, detail=str(e))
    fuente.usar("importada")
    return {**informe, "fuente": fuente.resumen()}


@app.get("/integraciones")
def integraciones():
    """Plataformas disponibles, configuración de Odoo (sin la API key) y estado de sincronización."""
    return {"plataformas": gestor.PLATAFORMAS, "intervalos": gestor.INTERVALOS,
            "odoo": {"config": gestor.config_odoo(), **gestor.estado_odoo()}, "fuente": fuente.resumen()}


@app.post("/integraciones/odoo/probar")
def probar_odoo(datos: ConfigOdoo):
    """Diagnóstico paso a paso con los datos del formulario (no guarda nada)."""
    try:
        cliente = gestor.cliente_odoo(datos.url, datos.db, datos.usuario, datos.api_key or None)
    except odoo.OdooError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not cliente.api_key:
        raise HTTPException(status_code=400, detail="Falta la API key.")
    return odoo.diagnosticar(cliente)


@app.post("/integraciones/odoo")
def guardar_odoo(datos: ConfigOdoo):
    try:
        return gestor.guardar_odoo(datos.url, datos.db, datos.usuario, datos.api_key or None, datos.meses, datos.cada_min)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/integraciones/odoo/sincronizar")
def sincronizar_odoo():
    """Arranca la sincronización en segundo plano; el avance se consulta en GET /integraciones."""
    if not gestor.config_odoo()["clave_guardada"]:
        raise HTTPException(status_code=400, detail="Primero guardá la conexión con Odoo.")

    if not gestor.sincronizar_en_segundo_plano(_usar_odoo):
        raise HTTPException(status_code=409, detail="Ya hay una sincronización en curso.")
    return gestor.estado_odoo()


@app.get("/actividades")
def ver_actividades(usuario_id: str):
    """Tareas del usuario (según su rol), ordenadas por puntaje, con el catálogo y la precisión de cada actividad."""
    return actividades.resumen(_usuario(usuario_id))


@app.post("/actividades/revisar")
def revisar_actividades(usuario_id: str):
    """Corre ahora las 6 reglas sobre los datos actuales."""
    _usuario(usuario_id)
    actividades.ejecutar()
    return actividades.resumen(_usuario(usuario_id))


@app.post("/actividades/{tarea_id}")
def cambiar_actividad(tarea_id: int, datos: CambioActividad):
    try:
        return actividades.cambiar_estado(tarea_id, _usuario(datos.usuario_id), datos.estado, datos.resolucion, datos.comentario)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e.args[0]))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/actividades/{tarea_id}/archivo.csv", response_class=PlainTextResponse)
def archivo_actividad(tarea_id: int, usuario_id: str):
    """Adjunto de la tarea (pedido sugerido, lista de remarcación) para revisar y cargar a mano en el sistema."""
    try:
        nombre, contenido = actividades.archivo_csv(tarea_id, _usuario(usuario_id))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e.args[0]))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return PlainTextResponse("\ufeff" + contenido, media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


def _errores_gestion(funcion):
    try:
        return funcion()
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e.args[0]))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/gestion/objetivos")
def ver_objetivos(usuario_id: str, periodicidad: str | None = None):
    """Mis objetivos: semáforo, valor, meta, avance, ritmo, proyección y cuándo se actualizaron los datos."""
    return gestion_objetivos.tablero(_usuario(usuario_id), periodicidad)


@app.get("/gestion/objetivos/{objetivo_id}")
def ver_objetivo(objetivo_id: int, usuario_id: str):
    return _errores_gestion(lambda: gestion_objetivos.detalle(objetivo_id, _usuario(usuario_id)))


@app.get("/gestion/plantillas")
def ver_plantillas(usuario_id: str):
    u = _usuario(usuario_id)
    from .gestion import metricas as gestion_metricas
    return {"plantillas": [p | {"puede_configurar": gestion_objetivos.puede_configurar(u, p["area"])}
                           for p in gestion_objetivos.plantillas_disponibles()],
            "opciones": gestion_metricas.opciones_alcance(), "roles": list(config.roles()["roles"])}


@app.post("/gestion/objetivos/proponer")
def proponer_objetivo(datos: PropuestaObjetivo):
    """Meta sugerida, validación V1-V9 y cascada. No guarda nada."""
    _usuario(datos.usuario_id)
    return _errores_gestion(lambda: gestion_objetivos.proponer(**datos.argumentos()))


@app.post("/gestion/objetivos")
def crear_objetivo(datos: PropuestaObjetivo):
    """Guarda y activa el objetivo con su cascada (quien guarda lo aprueba)."""
    resultado = _errores_gestion(lambda: gestion_objetivos.guardar(datos.argumentos(), _usuario(datos.usuario_id), datos.justificacion))
    _revisar_actividades()
    return resultado


@app.post("/gestion/objetivos/{objetivo_id}/archivar")
def archivar_objetivo(objetivo_id: int, datos: Comentario):
    _errores_gestion(lambda: gestion_objetivos.archivar(objetivo_id, _usuario(datos.usuario_id)))
    return {"ok": True}


@app.post("/gestion/objetivos/{objetivo_id}/comentario")
def comentar_objetivo(objetivo_id: int, datos: Comentario):
    _errores_gestion(lambda: gestion_objetivos.comentar(objetivo_id, _usuario(datos.usuario_id), datos.texto))
    return {"ok": True}


@app.get("/gestion/procesos")
def ver_procesos(usuario_id: str, dias: int = 30):
    """Por proceso: embudo de pasos, tiempos, % en plazo y casos trabados."""
    return {"procesos": gestion.vista_procesos(_usuario(usuario_id), max(7, min(dias, 365)))}


@app.post("/gestion/procesos/{proceso_id}/eventos")
def registrar_paso(proceso_id: str, datos: EventoProceso):
    """Registra un paso que ningún sistema marca (ej. gestión de cobranza). Se guarda en la plataforma, nunca en el ERP."""
    u = _usuario(datos.usuario_id)
    if not gestion.puede_registrar(u, proceso_id):
        raise HTTPException(status_code=403, detail="Tu rol no registra pasos de este proceso.")
    from datetime import date as _date
    fecha = None
    if datos.fecha:
        try:
            fecha = _date.fromisoformat(datos.fecha)
        except ValueError:
            raise HTTPException(status_code=400, detail="Fecha inválida (AAAA-MM-DD).")
    r = _errores_gestion(lambda: gestion_procesos.registrar_evento(proceso_id, datos.caso_key, datos.codigo, u.nombre, fecha,
                                                                   datos.resultado, datos.detalle))
    _revisar_actividades()
    return r


@app.get("/plantillas/{tabla}.csv", response_class=PlainTextResponse)
def plantilla(tabla: str):
    try:
        return PlainTextResponse(importar.plantilla(tabla), media_type="text/csv",
                                 headers={"Content-Disposition": f'attachment; filename="{tabla}.csv"'})
    except importar.ErrorImportacion as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/decisiones/credito")
def decision_credito(datos: SimulacionCredito):
    fin = config.empresa().get("finanzas", {})
    valores = datos.model_dump()
    for clave in ("costo_dinero_mensual", "caja_minima", "descubierto_disponible"):
        if valores[clave] is None:
            valores[clave] = fin.get(clave, 0)
    return credito.simular(credito.ParametrosCredito(**valores)).a_dict()
