"""Semáforo «Listo para producción»: los criterios de marcha blanca y, para cada uno, qué falta."""
from __future__ import annotations

from datetime import date

from ..analisis import cobertura
from ..erp import fuente
from . import cuadratura, incidencias, manuales, suites


def _criterio(nombre: str, ok: bool, valor: str, falta: str | None, pantalla: str) -> dict:
    return {"criterio": nombre, "ok": ok, "valor": valor, "falta": None if ok else falta, "pantalla": pantalla}


def general(hoy: date | None = None) -> dict:
    fte = fuente.actual()
    criterios = []
    mb = cuadratura.marcha_blanca("odoo")
    es_odoo = fte == "odoo"
    criterios.append(_criterio("Días en paralelo (mínimo 14)", es_odoo and mb["dias_en_paralelo"] >= 14, f"{mb['dias_en_paralelo']} de 14",
                               "La fuente activa no es Odoo: la marcha blanca corre con el sistema real del cliente." if not es_odoo else
                               f"Faltan {14 - mb['dias_en_paralelo']} días de verificación diaria (cada sincronización cuenta el día).",
                               "cuadratura"))
    criterios.append(_criterio("Días seguidos sin diferencias (mínimo 7)", es_odoo and mb["racha_sin_diferencias"] >= 7,
                               f"{mb['racha_sin_diferencias']} de 7",
                               "Sin verificaciones con Odoo todavía." if not es_odoo else
                               f"Faltan {7 - mb['racha_sin_diferencias']} días seguidos cuadrados; revisá los días con diferencia.", "cuadratura"))
    sellos = [(m, cuadratura.sello(m["id"], fte, hoy)) for m in cuadratura.METRICAS]
    cuadradas = [m["nombre"] for m, s in sellos if s["sello"] == "cuadrado"]
    en_revision = [m["nombre"] for m, s in sellos if s["sello"] == "en_revision"]
    sin_ref = [m["nombre"] for m, s in sellos if s["sello"] == "sin_referencia"]
    falta = []
    if en_revision:
        falta.append("En revisión: " + ", ".join(en_revision))
    if sin_ref:
        falta.append("Sin referencia del origen: " + ", ".join(sin_ref))
    criterios.append(_criterio("Métricas clave cuadradas con el sistema", len(cuadradas) == len(sellos),
                               f"{len(cuadradas)} de {len(sellos)}", " · ".join(falta), "cuadratura"))
    try:
        cob = cobertura.cobertura()
        errores = [a["texto"] for a in cob.get("controles", []) if a.get("nivel") == "error"]
    except Exception as e:
        errores = [f"No se pudo revisar la calidad de datos: {e}"]
    abiertas_datos = [i for i in incidencias.listar("abiertas") if i["tipo"] == "datos"]
    criterios.append(_criterio("Controles de datos críticos abiertos (tienen que ser 0)", not errores and not abiertas_datos,
                               str(len(errores) + len(abiertas_datos)),
                               "; ".join(errores[:3] + [f"Incidencia #{i['id']}: {i['titulo']}" for i in abiertas_datos[:3]]), "integridad"))
    r = suites.resumen()
    sin_correr = [s["nombre"] for s in r["suites"] if not s["ultima"]]
    rojas = [s["nombre"] for s in r["suites"] if s["ultima"] and s["ultima"]["estado"] != "aprobado"]
    verdes = len(r["suites"]) - len(sin_correr) - len(rojas)
    criterios.append(_criterio("Suites de pruebas automáticas en verde", verdes == len(r["suites"]), f"{verdes} de {len(r['suites'])}",
                               " · ".join(x for x in (("Fallan: " + ", ".join(rojas)) if rojas else "",
                                                      ("Sin correr: " + ", ".join(sin_correr)) if sin_correr else "") if x),
                               "automaticas"))
    casos = manuales.listar()
    aprobados = [c for c in casos if c["ultima"] and c["ultima"]["estado"] == "aprobado"]
    fallidos = [c["codigo"] for c in casos if c["ultima"] and c["ultima"]["estado"] == "fallido"]
    pendientes = [c["codigo"] for c in casos if not c["ultima"]]
    criterios.append(_criterio("Pruebas manuales aprobadas", len(aprobados) == len(casos), f"{len(aprobados)} de {len(casos)}",
                               " · ".join(x for x in (("Fallidas: " + ", ".join(fallidos)) if fallidos else "",
                                                      ("Sin ejecutar: " + ", ".join(pendientes)) if pendientes else "") if x),
                               "manuales"))
    listos = sum(1 for c in criterios if c["ok"])
    color = "verde" if listos == len(criterios) else ("amarillo" if listos >= len(criterios) - 2 else "rojo")
    return {"fuente": fte, "listo": listos == len(criterios), "color": color, "criterios": criterios, "marcha_blanca": mb,
            "incidencias_abiertas": len(incidencias.listar("abiertas"))}
