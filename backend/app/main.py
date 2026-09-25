"""API de la plataforma.

Levantar:  uvicorn app.main:app --reload   (desde la carpeta backend)
Preview:   http://localhost:8000
Docs:      http://localhost:8000/docs
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import acceso, config
from .chat import motor
from .decisiones import credito
from .erp import conector, fuente, importar
from .integraciones import gestor, odoo
from .permisos import AccesoDenegado, Usuario, obtener_usuario, preparar_consulta

WEB = Path(__file__).resolve().parent / "web"

@asynccontextmanager
async def _ciclo_de_vida(_app):
    # Si Odoo ya está configurado y sincronizado, se arranca con sus datos.
    odoo_listo = not os.getenv("ERP_URL") and gestor.config_odoo()["clave_guardada"]
    if odoo_listo and fuente.RUTA_ODOO.exists():
        fuente.usar("odoo")
    elif odoo_listo:
        # En un servidor nuevo (o que se reinició) todavía no hay datos: se sincroniza al arrancar.
        gestor.sincronizar_en_segundo_plano(lambda entrada: entrada["ok"] and fuente.usar("odoo"))
    gestor.iniciar_programador(lambda entrada: entrada["ok"] and fuente.actual() == "demo" and fuente.usar("odoo"))
    yield


app = FastAPI(title="Plataforma IA para ERP", version="0.1.0", lifespan=_ciclo_de_vida)
acceso.registrar(app)


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


@app.get("/salud")
def salud():
    return {"estado": "ok", "empresa": config.empresa()["EMPRESA"], "modelo": config.ANTHROPIC_MODEL,
            "chat_habilitado": _chat_habilitado(), "fuente": fuente.actual(), "con_clave": bool(os.getenv("PANEL_CLAVE"))}


@app.post("/chat")
def chat(pregunta: PreguntaChat):
    usuario = _usuario(pregunta.usuario_id)
    if not _chat_habilitado():
        raise HTTPException(status_code=503, detail="Falta ANTHROPIC_API_KEY en backend/.env para usar el chat.")
    r = motor.responder(pregunta.mensaje, usuario, pregunta.historial)
    return {"respuesta": r.texto, "herramientas_usadas": r.herramientas_usadas, "historial": r.historial}


@app.get("/usuarios")
def usuarios():
    """Usuarios de demo y, si la fuente tiene vendedores, uno por vendedor para probar carteras."""
    lista = [{"id": uid, "nombre": d["nombre"], "rol": d["rol"]} for uid, d in config.roles()["usuarios"].items()]
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

    def al_terminar(entrada):
        if entrada["ok"]:
            fuente.usar("odoo")

    if not gestor.sincronizar_en_segundo_plano(al_terminar):
        raise HTTPException(status_code=409, detail="Ya hay una sincronización en curso.")
    return gestor.estado_odoo()


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
