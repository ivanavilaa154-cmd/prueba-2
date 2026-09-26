"""Revisión independiente: compara lo que dice la especificación con lo que hace el sistema.

Dos partes:
1. Chequeos fijos (siempre): requisitos de la especificación que se pueden comprobar mirando
   el estado real del sistema, cada uno con su evidencia.
2. Un agente separado (si hay ANTHROPIC_API_KEY): otra llamada al modelo, sin el contexto del
   desarrollo, que recibe los documentos y el estado del cliente y devuelve discrepancias.
Todo lo que encuentra entra como incidencia "para revisar".
"""
from __future__ import annotations

import json
import os
import re
import threading

from .. import config
from ..erp import fuente, modelo
from ..gestion import catalogo as gcat
from . import almacen, cuadratura, estado, incidencias, suites

DOCS = [config.RAIZ / "docs" / "cerebro-ia" / "pedidos" / "prompt_1_cuadratura_en_capas.md",
        config.RAIZ / "docs" / "cerebro-ia" / "pedidos" / "prompt_2_centro_de_pruebas.md",
        config.RAIZ / "docs" / "evaluacion-cerebro-ia.md"]
_estado = {"corriendo": False, "ultima": None}


def _d(titulo, especificacion, sistema, evidencia) -> dict:
    return {"titulo": titulo, "especificacion": especificacion, "sistema": sistema, "evidencia": evidencia}


def chequeos_fijos() -> list[dict]:
    res = []
    ficha = cuadratura.ficha("ventas")
    if ficha["descubrimiento"] == "pendiente":
        res.append(_d("Descubrimiento automático de la definición espejo",
                      "Pedido 1, punto 12: probar todas las combinaciones del checklist sobre 3 meses y guardar la que coincide ≥ 98 % de los días.",
                      "La definición usada es fija (la del filtro «Órdenes de venta» de Odoo); no hay descubrimiento automático.",
                      "Centro de pruebas → Cuadratura: descubrimiento «pendiente»; falta docs/16_cuadratura_con_origen.md."))
    sin_ref = [m["nombre"] for m in cuadratura.METRICAS if not m["referencia"]]
    if sin_ref:
        res.append(_d("Métricas clave sin control del origen", "Pedido 1, punto 1: streams_control obligatorios para ventas, facturación, "
                      "tesorería, inventario y cuentas corrientes.", "Solo ventas tiene total oficial del origen.",
                      "Sin referencia: " + ", ".join(sin_ref)))
    reales = re.findall(r"\b(\w+) REAL\b", modelo.ESQUEMA)
    if reales:
        res.append(_d("Importes con coma flotante en el modelo", "Pedido 1, punto 7: tipos numeric en todo el pipeline, nunca float.",
                      f"{len(reales)} columnas del modelo son REAL (coma flotante); solo la base de pruebas usa centésimos enteros.",
                      "backend/app/erp/modelo.py: " + ", ".join(sorted(set(reales))[:12]) + ("…" if len(set(reales)) > 12 else "")))
    mb = cuadratura.marcha_blanca()
    if not mb["en_produccion"] and fuente.actual() == "odoo":
        res.append(_d("Marcha blanca: los números se muestran antes de pasar a producción",
                      "Pedido 1, punto 17: una fuente nueva corre 14 días en paralelo sin mostrarse.",
                      "El tablero muestra los datos de Odoo desde la primera sincronización.",
                      f"Días en paralelo {mb['dias_en_paralelo']}, racha {mb['racha_sin_diferencias']}."))
    for pid, cfg in (gcat.empresa().get("procesos") or {}).items():
        if not cfg.get("activo"):
            res.append(_d(f"Proceso {pid} sin medir", "docs/15 §1: 6 procesos estándar medidos paso a paso.", cfg.get("motivo", "Inactivo."),
                          "config/gestion/empresa.yaml"))
    for s in suites.resumen()["suites"]:
        u = s["ultima"]
        if not u:
            res.append(_d(f"Suite «{s['nombre']}» sin ejecutar", "Pedido 2, pantalla 5: resultados de la última corrida de cada suite.",
                          "Nunca se corrió desde el Centro de pruebas.", "Centro de pruebas → Pruebas automáticas"))
        elif u["estado"] != "aprobado":
            res.append(_d(f"Suite «{s['nombre']}» en rojo", "Las suites tienen que estar en verde para salir a producción.",
                          f"{u['fallidas']} de {u['total']} pruebas fallan.", json.dumps(u["fallas"][:2], ensure_ascii=False)[:600]))
    rec = cuadratura.ultima_reconciliacion()
    if fuente.actual() == "odoo" and not rec:
        res.append(_d("Reconciliación de IDs sin ejecutar", "Pedido 1, punto 2: reconciliación diaria de claves de los últimos 90 días.",
                      "Nunca se ejecutó.", "Centro de pruebas → Integridad de datos"))
    elif rec and (rec["faltantes"] or rec["borrados"] or rec["duplicados"]):
        res.append(_d("Diferencias de IDs con el origen", "Todo registro del origen tiene que estar en la plataforma y nada de más.",
                      f"{len(rec['faltantes'])} faltan, {len(rec['borrados'])} borrados en origen, {len(rec['duplicados'])} duplicados.",
                      f"Reconciliación del {rec['ejecutado_at']}: faltan {rec['faltantes'][:10]}, borrados {rec['borrados'][:10]}"))
    return res


def _agente(estado_cliente: dict) -> list[dict]:
    """Otra llamada al modelo, sin el contexto del desarrollo: solo documentos y estado."""
    if not os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY") == "sk-ant-...":
        return []
    import anthropic
    documentos = "\n\n".join(f"### {d.name}\n{d.read_text(encoding='utf-8')[:20000]}" for d in DOCS if d.exists())
    sistema = ("Sos un revisor independiente de software. No participaste del desarrollo. Recibís la especificación y el estado real "
               "de un cliente de la plataforma. Tu trabajo: listar discrepancias entre lo que la especificación exige y lo que el sistema "
               "hace, cada una con evidencia tomada del estado. No inventes: si el estado no muestra algo, no lo afirmes. Respondé solo "
               'con un arreglo JSON: [{"titulo": "...", "especificacion": "...", "sistema": "...", "evidencia": "..."}].')
    respuesta = anthropic.Anthropic().messages.create(
        model=config.ANTHROPIC_MODEL, max_tokens=4000, system=sistema,
        messages=[{"role": "user", "content": f"ESPECIFICACIÓN\n{documentos}\n\nESTADO DEL CLIENTE (JSON)\n"
                                              f"{json.dumps(estado_cliente, ensure_ascii=False, default=str)[:30000]}"}])
    texto = "".join(getattr(b, "text", "") for b in respuesta.content)
    m = re.search(r"\[.*\]", texto, re.S)
    try:
        return [x for x in json.loads(m.group(0)) if isinstance(x, dict) and x.get("titulo")] if m else []
    except json.JSONDecodeError:
        return []


def ejecutar(usuario: str) -> dict:
    fijos = chequeos_fijos()
    estado_cliente = {"estado_general": estado.general(), "fuente": fuente.actual(),
                      "cuadratura_ventas": {k: v for k, v in cuadratura.ficha("ventas").items() if k != "historial"},
                      "suites": suites.resumen(), "chequeos_fijos": fijos}
    try:
        del_agente = _agente(estado_cliente)
        error = None
    except Exception as e:   # sin conexión o sin crédito: quedan los chequeos fijos
        del_agente, error = [], f"{type(e).__name__}: {str(e)[:200]}"
    nuevas = []
    for origen_, lista in (("fijo", fijos), ("agente", del_agente)):
        for d in lista:
            titulo = f"Revisión: {d['titulo']}"[:300]
            ya = almacen.filas("SELECT id FROM incidencia WHERE titulo=? AND estado NOT IN ('resuelta', 'descartada')", (titulo,))
            if not ya:
                nuevas.append(incidencias.crear("revision", titulo, usuario, tipo="otro", estado="para_revisar",
                                                descripcion=f"Especificación: {d.get('especificacion', '')}\nSistema: {d.get('sistema', '')}",
                                                evidencia={"evidencia": d.get("evidencia"), "revisor": origen_}))
    resultado = {"ejecutada_at": almacen.ahora(), "fijos": fijos, "agente": del_agente, "agente_error": error,
                 "agente_disponible": bool(os.getenv("ANTHROPIC_API_KEY")) and os.getenv("ANTHROPIC_API_KEY") != "sk-ant-...",
                 "incidencias_nuevas": nuevas}
    _estado["ultima"] = resultado
    return resultado


def en_segundo_plano(usuario: str) -> bool:
    if _estado["corriendo"]:
        return False
    _estado["corriendo"] = True

    def correr():
        try:
            ejecutar(usuario)
        finally:
            _estado["corriendo"] = False
    threading.Thread(target=correr, daemon=True).start()
    return True


def ultima() -> dict:
    return {"corriendo": _estado["corriendo"], "ultima": _estado["ultima"]}
