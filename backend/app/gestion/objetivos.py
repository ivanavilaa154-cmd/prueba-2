"""Objetivos: definición desde plantillas, meta sugerida, validación V1-V9, cascada y evaluación en tiempo real.

Todo determinístico (sin modelo de lenguaje). La meta la pone una persona (con una
sugerencia de la plataforma); el valor actual siempre lo mide la plataforma.
Ver docs/cerebro-ia/docs/15_gestion_procesos_objetivos.md §2.
"""
from __future__ import annotations

import json
import math
import statistics
from datetime import date, datetime, timedelta

from .. import config
from ..actividades import catalogo as act_catalogo
from ..permisos import Usuario
from . import almacen, catalogo, metricas

PERIODOS = ("diario", "semanal", "mensual", "trimestral", "anual")
CONFLICTOS = [("OBJ-17", "OBJ-16", "Bajar días de inventario y bajar el quiebre tiran en sentidos opuestos: menos stock sube el riesgo de quiebre."),
              ("OBJ-04", "OBJ-01", "Subir el margen y subir la venta a la vez: más precio suele bajar volumen."),
              ("OBJ-12", "OBJ-01", "Bajar la cartera vencida y crecer en venta: vender más a crédito suele subir la deuda."),
              ("OBJ-14", "OBJ-07", "Recortar gastos y mejorar el despacho en plazo pueden chocar (personal y logística).")]
PRIORIDAD_ESTADO = {"fuera_de_camino": 0, "en_riesgo": 1, "no_evaluable": 2, "en_camino": 3, "cumplido": 4, "sin_meta": 5}


# --- períodos y curva esperada --------------------------------------------------------------

def periodo(periodicidad: str, d: date) -> tuple[date, date]:
    if periodicidad == "diario":
        return d, d
    if periodicidad == "semanal":
        inicio = d - timedelta(days=d.weekday())
        return inicio, inicio + timedelta(days=6)
    if periodicidad == "mensual":
        inicio = d.replace(day=1)
    elif periodicidad == "trimestral":
        inicio = d.replace(month=(d.month - 1) // 3 * 3 + 1, day=1)
    else:
        inicio = d.replace(month=1, day=1)
    meses = {"mensual": 1, "trimestral": 3, "anual": 12}[periodicidad]
    fin = inicio
    for _ in range(meses):
        fin = (fin + timedelta(days=32)).replace(day=1)
    return inicio, fin - timedelta(days=1)


def anterior(periodicidad: str, inicio: date, n: int = 1) -> tuple[date, date]:
    d = inicio
    for _ in range(n):
        d = periodo(periodicidad, d - timedelta(days=1))[0]
    return periodo(periodicidad, d)


def _dias(inicio: date, fin: date) -> list[date]:
    return [inicio + timedelta(days=i) for i in range((fin - inicio).days + 1)]


def _pesos_semana(hoy: date) -> list[float] | None:
    """Participación de cada día de la semana en la venta de las últimas 12 semanas (None si hay menos de 8)."""
    desde = hoy - timedelta(days=84)
    filas = metricas._q(f"SELECT v.fecha, SUM(l.cantidad * l.precio_unitario) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id "
                        f"WHERE COALESCE(v.anulada, 0) = 0 AND v.fecha >= '{desde}' AND v.fecha < '{hoy}' GROUP BY v.fecha")
    fechas = [date.fromisoformat(str(f)[:10]) for f, _ in filas if f]
    if not fechas or (max(fechas) - min(fechas)).days < 56:
        return None
    suma = [0.0] * 7
    for f, v in filas:
        suma[date.fromisoformat(str(f)[:10]).weekday()] += float(v or 0)
    return suma if sum(suma) else None


def pesos(curva: str, inicio: date, fin: date, hoy: date) -> dict[date, float]:
    """Peso de cada día del período en la curva esperada."""
    dias = _dias(inicio, fin)
    if curva == "estacionalidad_historica":
        semana = _pesos_semana(hoy)
        if semana:
            return {d: semana[d.weekday()] for d in dias}
        curva = "dias_habiles"
    if curva == "dias_habiles":
        return {d: 1.0 if catalogo.es_habil(d) else 0.0 for d in dias}
    return {d: 1.0 for d in dias}


def fraccion_hoy(ahora: datetime) -> float:
    desde, hasta = catalogo.horario()
    h = ahora.hour + ahora.minute / 60
    return min(1.0, max(0.0, (h - desde) / max(1, hasta - desde)))


def fraccion_intradia(hoy: date, ahora: datetime) -> float | None:
    """Parte de la venta del día que suele estar hecha a esta hora (mismo día de la semana, últimas 8 semanas).

    Usa ventas.hora; si la integración no trae la hora, devuelve None y se usa el horario operativo parejo.
    """
    dias = ", ".join(f"'{hoy - timedelta(days=7 * k)}'" for k in range(1, 9))
    try:
        filas = metricas._q(f"SELECT v.hora, SUM(l.cantidad * l.precio_unitario) FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id "
                            f"WHERE COALESCE(v.anulada, 0) = 0 AND v.hora IS NOT NULL AND v.fecha IN ({dias}) GROUP BY v.hora")
    except Exception:
        return None
    total = sum(float(v or 0) for _h, v in filas)
    if not filas or not total:
        return None
    ahora_txt = ahora.strftime("%H:%M")
    hecho = sum(float(v or 0) for h, v in filas if str(h)[:5] <= ahora_txt)
    return hecho / total


def avance_curva(w: dict[date, float], hasta_dato: date, hoy: date, parcial: float) -> float:
    """c(t): parte de la meta que debería estar lograda con los datos hasta `hasta_dato`."""
    total = sum(w.values())
    if not total:
        return 1.0
    hecho = sum(p for d, p in w.items() if d < hoy and d <= hasta_dato)
    if hoy in w and hasta_dato >= hoy:
        hecho += w[hoy] * parcial
    return min(1.0, hecho / total)


# --- datos y frescura -----------------------------------------------------------------------

def datos_hasta() -> date | None:
    try:
        f = metricas._uno("SELECT MAX(fecha) FROM ventas")
        return date.fromisoformat(str(f)[:10]) if f else None
    except Exception:
        return None


def datos_actualizados_at() -> datetime | None:
    """Cuándo se actualizaron los datos por última vez (sincronización de Odoo, importación o base demo)."""
    from ..erp import fuente
    from ..integraciones import gestor
    tipo = fuente.actual()
    if tipo == "odoo":
        hist = [h for h in gestor._leer_estado().get("historial", []) if h.get("ok")]
        if hist:
            return datetime.fromtimestamp(hist[0]["ts"])
    url = fuente.opciones().get(tipo) or ""
    if url.startswith("sqlite:///"):
        from pathlib import Path
        ruta = Path(url.replace("sqlite:///", "", 1))
        if ruta.exists():
            return datetime.fromtimestamp(ruta.stat().st_mtime)
    return None


# --- objetivos guardados ----------------------------------------------------------------

def _fila(r) -> dict:
    return dict(r) if r else None


def listar_objetivos(estado: str = "activo") -> list[dict]:
    with almacen.conectar() as con:
        return [dict(r) for r in con.execute("SELECT * FROM objetivo WHERE fuente=? AND estado=? ORDER BY id",
                                            (almacen.fuente_actual(), estado))]


def obtener(objetivo_id: int) -> dict:
    with almacen.conectar() as con:
        r = con.execute("SELECT * FROM objetivo WHERE id=? AND fuente=?", (objetivo_id, almacen.fuente_actual())).fetchone()
    if not r:
        raise KeyError("No existe ese objetivo.")
    return dict(r)


def visible(o: dict, usuario: Usuario) -> bool:
    if usuario.rol == "dueno":
        return True
    if usuario.vendedor_id is not None:
        return o["alcance_tipo"] == "vendedor" and str(o["alcance_valor"]) == str(usuario.vendedor_id)
    return o["area"] in (catalogo.areas_de(usuario.rol) or [])


def puede_configurar(usuario: Usuario, area: str) -> bool:
    return usuario.rol == "dueno" or (usuario.vendedor_id is None and area in (catalogo.areas_de(usuario.rol) or []))


def meta_de(o: dict, inicio: date, fin: date, hoy: date, cache: dict | None = None) -> float | None:
    """Meta del objetivo para un período: la cargada, la de la cascada (padre) o la meta base."""
    cache = cache if cache is not None else {}
    with almacen.conectar() as con:
        r = con.execute("SELECT meta FROM objetivo_meta WHERE objetivo_id=? AND periodo_inicio=?", (o["id"], inicio.isoformat())).fetchone()
    if r and r[0] is not None:
        return float(r[0])
    if o.get("objetivo_padre_id"):
        padre = cache.get(o["objetivo_padre_id"]) or obtener(o["objetivo_padre_id"])
        m = metricas.metrica(o["metrica"])
        if padre["periodicidad"] != o["periodicidad"]:            # cascada en el tiempo
            p_ini, p_fin = periodo(padre["periodicidad"], inicio)
            mp = meta_de(padre, p_ini, p_fin, hoy, cache)
            if mp is None or not m or not m.acumulable:
                return mp
            w = pesos(padre["curva_esperada"] if padre["curva_esperada"] != "no_aplica" else "dias_habiles", p_ini, p_fin, hoy)
            sub = sum(v for d, v in w.items() if inicio <= d <= fin)
            if o.get("modo_reparto") == "fijo" or inicio <= p_ini:
                total = sum(w.values())
                return round(mp * sub / total, 2) if total else None
            hecho, _n = metricas.valor(padre["metrica"], padre["alcance_tipo"], padre["alcance_valor"], p_ini, inicio - timedelta(days=1), hoy)
            resto = sum(v for d, v in w.items() if d >= inicio)
            falta = (mp - (hecho or 0)) if padre["tipo_meta"] != "maximo" else (mp - (hecho or 0))
            return round(max(0.0, falta) * sub / resto, 2) if resto else None
        mp = meta_de(padre, inicio, fin, hoy, cache)                # cascada por alcance
        if mp is None:
            return None
        return round(mp * (o.get("participacion") or 1.0), 2) if m and m.acumulable else mp
    return o.get("meta_base")


# --- evaluación ----------------------------------------------------------------------------

def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def evaluar(o: dict, hoy: date, ahora: datetime, guardar: bool = True, cache: dict | None = None) -> dict:
    inicio, fin = periodo(o["periodicidad"], hoy)
    m = metricas.metrica(o["metrica"])
    res = {"objetivo_id": o["id"], "periodo_inicio": inicio.isoformat(), "periodo_fin": fin.isoformat(), "evaluado_at": ahora.isoformat(timespec="seconds"),
           "valor_actual": None, "valor_esperado": None, "meta": None, "avance_pct": None, "ritmo": None, "proyeccion_cierre": None,
           "prob_cumplimiento": None, "estado": None, "muestra": 0, "advertencias": [], "ritmo_necesario": None, "fraccion_periodo": None}
    hasta_dato = datos_hasta()
    res["datos_hasta"] = hasta_dato.isoformat() if hasta_dato else None
    meta = meta_de(o, inicio, fin, hoy, cache)
    res["meta"] = meta
    actualizado = datos_actualizados_at()
    res["datos_actualizados_at"] = actualizado.isoformat(timespec="seconds") if actualizado else None
    frescura = float(catalogo.empresa().get("frescura_max_horas", 30))
    if meta is None:
        res["estado"] = "sin_meta"
    elif not m:
        res["estado"] = "no_evaluable"
        res["advertencias"].append("La plataforma no puede calcular esta métrica con los datos actuales.")
    elif not hasta_dato or (actualizado and (ahora - actualizado).total_seconds() / 3600 > frescura and
                            hasta_dato < hoy - timedelta(days=1)):
        res["estado"] = "no_evaluable"
        res["advertencias"].append("Los datos están desactualizados: no se muestran números viejos como si fueran de hoy.")
    else:
        corte = min(fin, hasta_dato) if m.historica else hoy   # las fotos (caja, stock) son siempre las de ahora
        valor, muestra = (metricas.valor(o["metrica"], o["alcance_tipo"], o["alcance_valor"], inicio, corte, hoy)
                          if corte >= inicio else (0.0 if m.acumulable else None, 0))
        res["valor_actual"], res["muestra"] = valor, muestra
        if m.acumulable:
            _acumulable(o, res, inicio, fin, hoy, ahora, hasta_dato, valor or 0.0, meta)
        else:
            _no_acumulable(o, m, res, valor, muestra, meta)
        if o["curva_esperada"] == "intradia_historica" and not res.get("curva_intradia") and m.acumulable:
            res["advertencias"].append("Sin hora de cada venta: la curva del día se toma pareja en el horario operativo.")
    if guardar:
        with almacen.conectar() as con:
            con.execute("INSERT OR REPLACE INTO objetivo_evaluacion (objetivo_id, periodo_inicio, evaluado_at, valor_actual, valor_esperado, meta, "
                        "avance_pct, ritmo, proyeccion_cierre, prob_cumplimiento, estado, datos_hasta, muestra, advertencias) VALUES "
                        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (o["id"], res["periodo_inicio"], res["evaluado_at"], res["valor_actual"], res["valor_esperado"], res["meta"],
                         res["avance_pct"], res["ritmo"], res["proyeccion_cierre"], res["prob_cumplimiento"], res["estado"],
                         res["datos_hasta"], res["muestra"], json.dumps(res["advertencias"], ensure_ascii=False)))
    return res


def _estado_por_ritmo(o: dict, ritmo: float | None) -> str:
    if ritmo is None:
        return "no_evaluable"
    if ritmo >= o["umbral_en_riesgo"]:
        return "en_camino"
    return "en_riesgo" if ritmo >= o["umbral_fuera_de_camino"] else "fuera_de_camino"


def _acumulable(o, res, inicio, fin, hoy, ahora, hasta_dato, a, meta) -> None:
    curva = o["curva_esperada"] if o["curva_esperada"] not in ("no_aplica", "intradia_historica") else "lineal"
    w = pesos(curva, inicio, fin, hoy)
    parcial = fraccion_hoy(ahora)
    if o["curva_esperada"] == "intradia_historica" or o["periodicidad"] == "diario":
        intradia = fraccion_intradia(hoy, ahora)
        if intradia is not None:
            parcial = intradia
            res["curva_intradia"] = True
    c = avance_curva(w, hasta_dato, hoy, parcial) if fin >= hoy else 1.0
    res["fraccion_periodo"] = round(c, 4)
    esperado = meta * c
    res["valor_esperado"] = round(esperado, 2)
    res["avance_pct"] = round(a / meta, 4) if meta else None
    maximo = o["tipo_meta"] == "maximo"
    if maximo:
        ritmo = (esperado / a) if a else (1.5 if c > 0 else None)
    else:
        ritmo = (a / esperado) if esperado else None
    res["ritmo"] = round(ritmo, 4) if ritmo is not None else None
    r_acotado = min(1.5, max(0.5, (a / esperado) if esperado else 1.0))
    proy = a / c if c >= 0.15 else a + meta * (1 - c) * r_acotado
    res["proyeccion_cierre"] = round(proy, 2)
    sd = max(1e-9, 0.10 * max(proy, 1e-9) * math.sqrt(max(0.05, 1 - c)))
    prob = 1 - _normal_cdf((meta - proy) / sd) if not maximo else _normal_cdf((meta - proy) / sd)
    res["prob_cumplimiento"] = round(prob, 3)
    restantes = sum(1 for d, p in w.items() if p and (d > hoy or (d == hoy and hasta_dato < hoy)))
    if not maximo and a < meta and restantes:
        res["ritmo_necesario"] = round((meta - a) / restantes, 2)
    cerrado = fin < hoy
    if not maximo and a >= meta:
        res["estado"] = "cumplido"
    elif maximo and a > meta:
        res["estado"] = "fuera_de_camino"
    elif cerrado:
        res["estado"] = "cumplido" if (maximo and a <= meta) else "fuera_de_camino"
    elif ritmo is None:
        res["estado"] = "no_evaluable"
        res["advertencias"].append("Todavía no hay datos de este período (llegan con la próxima sincronización).")
    else:
        res["estado"] = _estado_por_ritmo(o, ritmo)
        # Primer 10 % del período: poca información, no pasa a rojo (salvo diarios después de la mitad del horario)
        if res["estado"] == "fuera_de_camino" and c < 0.10 and not (o["periodicidad"] == "diario" and fraccion_hoy(ahora) > 0.5):
            res["estado"] = "en_riesgo"
            res["advertencias"].append("Recién empieza el período: se muestra en amarillo hasta tener más datos.")


def _no_acumulable(o, m, res, valor, muestra, meta) -> None:
    minimo_muestra = int(catalogo.empresa().get("muestra_minima", 30))
    res["proyeccion_cierre"] = valor
    if valor is None:
        res["estado"] = "no_evaluable"
        res["advertencias"].append("No hay datos de esta métrica en el período.")
        return
    if m.con_muestra and muestra < minimo_muestra:
        res["estado"] = "no_evaluable"
        res["advertencias"].append(f"Muestra chica ({muestra} casos, mínimo {minimo_muestra}): conviene un período más largo.")
        return
    if o["tipo_meta"] == "maximo":
        ritmo = (meta / valor) if valor else 1.5
    else:
        ritmo = (valor / meta) if meta else None
    res["ritmo"] = round(ritmo, 4) if ritmo is not None else None
    res["avance_pct"] = res["ritmo"]
    res["estado"] = _estado_por_ritmo(o, ritmo)


def evaluar_todos(hoy: date | None = None, ahora: datetime | None = None) -> list[dict]:
    ahora = ahora or datetime.now()
    hoy = hoy or ahora.date()
    objetivos = listar_objetivos()
    cache = {o["id"]: o for o in objetivos}
    res = []
    for o in objetivos:
        try:
            res.append({"objetivo": o, "evaluacion": evaluar(o, hoy, ahora, cache=cache)})
        except Exception as e:  # un objetivo con un dato raro no frena a los demás
            res.append({"objetivo": o, "evaluacion": {"estado": "no_evaluable", "advertencias": [f"{type(e).__name__}: {e}"],
                                                      "periodo_inicio": periodo(o["periodicidad"], hoy)[0].isoformat()}})
    return res


def ultimas_evaluaciones(objetivo_id: int, n: int = 3) -> list[dict]:
    with almacen.conectar() as con:
        return [dict(r) for r in con.execute("SELECT * FROM objetivo_evaluacion WHERE objetivo_id=? ORDER BY evaluado_at DESC LIMIT ?",
                                            (objetivo_id, n))]


# --- meta sugerida e historia --------------------------------------------------------------

def _inflacion_mensual() -> float:
    return float((config.empresa().get("finanzas") or {}).get("inflacion_mensual", 0))


def historia(metrica: str, alcance_tipo, alcance_valor, periodicidad: str, hoy: date, n: int | None = None) -> list[dict]:
    """Valores de períodos cerrados anteriores (llevados a pesos de hoy si son de plata)."""
    m = metricas.metrica(metrica)
    if not m or not m.historica:
        return []
    n = n or {"diario": 8, "semanal": 26, "mensual": 13, "trimestral": 8, "anual": 3}[periodicidad]
    inicio, _fin = periodo(periodicidad, hoy)
    primera = metricas.primera_fecha(metrica)
    res = []
    for k in range(1, n + 1):
        if periodicidad == "diario":
            ini = fin = hoy - timedelta(days=7 * k)   # mismo día de la semana
        else:
            ini, fin = anterior(periodicidad, inicio, k)
        if primera and ini < primera:   # período que los datos no cubren entero: no sirve para comparar
            break
        v, muestra = metricas.valor(metrica, alcance_tipo, alcance_valor, ini, fin, hoy)
        if v is None:
            continue
        meses = (hoy - fin).days / 30.4
        real = v * (1 + _inflacion_mensual()) ** meses if m.unidad == "moneda" else v
        res.append({"inicio": ini.isoformat(), "fin": fin.isoformat(), "valor": v, "valor_real": real, "muestra": muestra})
    datos = [h for h in res if h["valor"]] if m.acumulable else res
    return datos


def sugerir(plantilla_id: str, alcance_tipo, alcance_valor, periodicidad: str, hoy: date) -> dict:
    """Meta sugerida con el método de la plantilla (o una aproximación honesta si faltan datos)."""
    pl = catalogo.plantillas()[plantilla_id]
    codigo = pl["metrica"]
    m = metricas.metrica(codigo)
    if not m:
        return {"meta": None, "explicacion": "La métrica no está disponible."}
    crec = float(catalogo.empresa().get("crecimiento_real_objetivo", 0.05))
    infl = _inflacion_mensual()
    ini, fin = periodo(periodicidad, hoy)
    fijas = {"kpi:VEN-07": (1.0, "Cumplir el 100 % de la cuota cargada."),
             "actividad:todas.tareas_resueltas_en_plazo_pct": (0.9, "90 % de las tareas resueltas dentro de su plazo.")}
    if codigo in fijas:
        return {"meta": fijas[codigo][0], "explicacion": fijas[codigo][1]}
    if codigo == "kpi:FIN-07":
        caja = float((config.empresa().get("finanzas") or {}).get("caja_minima", 0))
        return {"meta": caja, "explicacion": "Caja mínima de seguridad de la política de la empresa (config/empresa.yaml)."}
    if m.acumulable:
        hist = historia(codigo, alcance_tipo, alcance_valor, periodicidad, hoy)
        mismo = None
        if periodicidad == "mensual":
            hace_un_anio = [h for h in hist if h["inicio"] == ini.replace(year=ini.year - 1).isoformat()]
            mismo = hace_un_anio[0] if hace_un_anio else None
        if codigo == "kpi:VEN-01" and periodicidad == "mensual" and (alcance_tipo in (None, "empresa")):
            pres = metricas._uno(f"SELECT SUM(importe) FROM presupuesto WHERE mes = '{ini.isoformat()[:7]}' AND concepto = 'venta'")
            if pres and not mismo:
                return {"meta": round(float(pres), -2), "explicacion": "Presupuesto de venta cargado para el mes."}
        if mismo:
            meta = mismo["valor_real"] * (1 + crec)
            ajuste = f" en pesos de hoy (inflación {infl:.1%} mensual)" if m.unidad == "moneda" else ""
            return {"meta": _redondo(meta, m), "explicacion": f"Mismo período del año pasado{ajuste} × (1 + {crec:.0%} de crecimiento real)."}
        ultimos = hist[:3]
        if not ultimos:
            return {"meta": None, "explicacion": "No hay historia suficiente para sugerir una meta."}
        base = statistics.mean(h["valor_real"] for h in ultimos)
        factor = (1 - 0.05) if m.direccion == "menor_mejor" else (1 + crec)
        return {"meta": _redondo(base * factor, m),
                "explicacion": f"Promedio de los últimos {len(ultimos)} períodos" + (" en pesos de hoy" if m.unidad == "moneda" else "") +
                               f" × {factor:.2f}."}
    hist = historia(codigo, alcance_tipo, alcance_valor, periodicidad, hoy, 3) if m.historica else []
    if hist:
        actual = statistics.mean(h["valor"] for h in hist)
    else:
        actual, _n = metricas.valor(codigo, alcance_tipo, alcance_valor, hoy - timedelta(days=90), hoy - timedelta(days=1), hoy)
    if actual is None:
        return {"meta": None, "explicacion": "No hay datos para sugerir una meta."}
    if codigo.endswith("cumplimiento_sla_pct") or codigo.endswith("conformidad_pct"):
        return {"meta": round(min(0.98, max(0.9, actual + 0.03)), 3),
                "explicacion": "Estándar de 90 % de pasos en plazo (o el nivel actual + 3 puntos si ya está por encima)."}
    if m.unidad == "dias":
        return {"meta": max(1.0, round(actual * 0.9, 1)), "explicacion": "Valor actual con una mejora del 10 % (mínimo 1 día: los datos vienen por día)."}
    if m.unidad == "porcentaje":
        meta = min(0.98, actual + 0.03) if m.direccion == "mayor_mejor" else max(0.0, actual * 0.8)
        return {"meta": round(meta, 3), "explicacion": "Valor de los últimos 3 meses " + ("+ 3 puntos." if m.direccion == "mayor_mejor"
                                                                                         else "con una mejora del 20 %.")}
    meta = actual * (1.03 if m.direccion == "mayor_mejor" else 0.9)
    return {"meta": _redondo(meta, m), "explicacion": "Valor actual " + ("+ 3 %." if m.direccion == "mayor_mejor" else "con una mejora del 10 %.")}


def _redondo(v: float, m) -> float:
    if m.unidad == "moneda":
        return round(v, -3) if v >= 100_000 else round(v, -1)
    return round(v, 2 if m.unidad == "dias" else 0 if m.unidad == "cantidad" else 3)


# --- cascada y validación ------------------------------------------------------------------

def cascada(plantilla_id: str, alcance_tipo, alcance_valor, periodicidad: str, meta: float, hoy: date,
            tiempo: list[str] | None = None, por: str | None = None) -> dict:
    """Vista previa de la cascada: metas por semana/día del período y por sucursal/vendedor (participación de 3 meses)."""
    pl = catalogo.plantillas()[plantilla_id]
    m = metricas.metrica(pl["metrica"])
    ini, fin = periodo(periodicidad, hoy)
    curva = pl["curva_esperada"].get(periodicidad, "dias_habiles")
    res = {"tiempo": [], "alcance": []}
    for sub in tiempo or []:
        if PERIODOS.index(sub) >= PERIODOS.index(periodicidad):
            continue
        w = pesos(curva if curva not in ("no_aplica", "intradia_historica") else "dias_habiles", ini, fin, hoy)
        total = sum(w.values()) or 1
        filas, d = [], ini
        while d <= fin:
            s_ini, s_fin = periodo(sub, d)
            s_ini, s_fin = max(s_ini, ini), min(s_fin, fin)
            parte = sum(v for x, v in w.items() if s_ini <= x <= s_fin)
            filas.append({"inicio": s_ini.isoformat(), "fin": s_fin.isoformat(),
                          "meta": round(meta * parte / total, 2) if m and m.acumulable else meta})
            d = s_fin + timedelta(days=1)
        res["tiempo"].append({"periodicidad": sub, "periodos": filas})
    if por and m and por in m.alcances and alcance_tipo in (None, "empresa"):
        partes = metricas.desglose("kpi:VEN-01" if m.unidad == "moneda" else pl["metrica"], por, hoy - timedelta(days=90), hoy - timedelta(days=1))
        total = sum(partes.values())
        nombres = {x["valor"]: x["nombre"] for x in metricas.opciones_alcance().get(por, [])}
        for k, v in sorted(partes.items(), key=lambda x: -x[1]):
            part = v / total if total else 0
            res["alcance"].append({"tipo": por, "valor": str(k), "nombre": nombres.get(str(k), str(k)), "participacion": round(part, 4),
                                   "meta": round(meta * part, 2) if m.acumulable else meta})
        if res["alcance"] and m.acumulable:   # redondeo: el último absorbe la diferencia para que sumen exacto (V4)
            dif = round(meta - sum(x["meta"] for x in res["alcance"]), 2)
            res["alcance"][-1]["meta"] = round(res["alcance"][-1]["meta"] + dif, 2)
    return res


def validar(plantilla_id: str, alcance_tipo, alcance_valor, periodicidad: str, meta, responsable_rol: str | None, hoy: date,
            prevista: dict | None = None) -> list[dict]:
    """Reglas V1-V9. severidad: bloquea | advierte | ok."""
    pl = catalogo.plantillas()[plantilla_id]
    codigo = pl["metrica"]
    m = metricas.metrica(codigo)
    res = []

    def r(regla, severidad, mensaje):
        res.append({"regla": regla, "severidad": severidad, "mensaje": mensaje})

    ok, motivo = metricas.disponible(codigo, hoy)
    r("V1 Métrica disponible", "ok" if ok else "bloquea", "La plataforma mide esta métrica con tus datos." if ok else motivo)
    if not ok:
        return res
    sentido = {"minimo": "mayor_mejor", "maximo": "menor_mejor"}.get(pl["tipo_meta"])
    r("V2 Coherencia de sentido", "ok" if sentido in (None, m.direccion) else "bloquea",
      "El tipo de meta coincide con la dirección de la métrica." if sentido in (None, m.direccion)
      else f"La meta es '{pl['tipo_meta']}' pero la métrica mejora cuando {'sube' if m.direccion == 'mayor_mejor' else 'baja'}.")
    faltan = []
    if periodicidad not in pl["periodicidades"]:
        faltan.append(f"período ({', '.join(pl['periodicidades'])})")
    tipo = alcance_tipo or "empresa"
    if tipo not in pl.get("alcances", ["empresa"]) or tipo not in m.alcances:
        faltan.append(f"alcance válido ({', '.join(a for a in pl.get('alcances', []) if a in m.alcances)})")
    if tipo != "empresa" and alcance_valor in (None, ""):
        faltan.append(f"a qué {tipo} se aplica")
    if meta is None or (isinstance(meta, (int, float)) and meta < 0):
        faltan.append("meta")
    if not responsable_rol:
        faltan.append("responsable")
    r("V3 Datos completos", "bloquea" if faltan else "ok", "Falta: " + ", ".join(faltan) + "." if faltan else "Período, alcance, meta y responsable completos.")
    if faltan:
        return res
    if prevista:
        errores = []
        for t in prevista.get("tiempo", []):
            suma = sum(p["meta"] for p in t["periodos"])
            if m.acumulable and abs(suma - meta) > 0.005 * max(abs(meta), 1):
                errores.append(f"las metas {t['periodicidad']}es suman {suma:,.0f}")
        if prevista.get("alcance") and m.acumulable:
            suma = sum(p["meta"] for p in prevista["alcance"])
            if abs(suma - meta) > 0.005 * max(abs(meta), 1):
                errores.append(f"las metas por {prevista['alcance'][0]['tipo']} suman {suma:,.0f}")
        r("V4 Suma de la cascada", "bloquea" if errores else "ok",
          ("No cierra: " + "; ".join(errores) + ".") if errores else "Las metas de la cascada suman la meta total.")
    hist = historia(codigo, alcance_tipo, alcance_valor, periodicidad, hoy)
    if len(hist) >= 3 and meta:
        valores = sorted(h["valor_real"] for h in hist)
        p95 = valores[min(len(valores) - 1, int(0.95 * (len(valores) - 1) + 0.5))]
        p25 = valores[int(0.25 * (len(valores) - 1))]
        p75 = valores[int(0.75 * (len(valores) - 1) + 0.5)]
        p05 = valores[int(0.05 * (len(valores) - 1))]
        ini, _fin = periodo(periodicidad, hoy)
        anio = [h for h in hist if h["inicio"] == ini.replace(year=ini.year - 1).isoformat()] if periodicidad == "mensual" else []
        crec = (meta / anio[0]["valor_real"] - 1) if anio and anio[0]["valor_real"] else None
        if m.direccion == "mayor_mejor":
            exigente = meta > p95 or (crec is not None and crec > 0.30)
            flojo = meta < p25
        else:
            exigente, flojo = meta < p05, meta > p75
        detalle = f"historia de {len(hist)} períodos" + (" en pesos de hoy" if m.unidad == "moneda" else "")
        if exigente:
            r("V5 Realismo", "advierte", f"Muy exigente frente a la {detalle}" + (f" (crecimiento real {crec:.0%})" if crec is not None else "") +
              ". Para activarla hace falta una justificación.")
        elif flojo:
            r("V5 Realismo", "advierte", f"Poco exigente frente a la {detalle}. Para activarla hace falta una justificación.")
        else:
            r("V5 Realismo", "ok", f"Dentro de lo razonable frente a la {detalle}.")
    else:
        r("V5 Realismo", "ok", "Sin historia suficiente para comparar (se evalúa igual).")
    if codigo == "kpi:VEN-01" and periodicidad == "mensual" and tipo == "empresa":
        ini, _ = periodo("mensual", hoy)
        pres = metricas._uno(f"SELECT SUM(importe) FROM presupuesto WHERE mes = '{ini.isoformat()[:7]}' AND concepto = 'venta'")
        if pres:
            dif = meta / float(pres) - 1
            r("V6 Contra presupuesto", "advierte" if abs(dif) > 0.05 else "ok",
              f"La meta difiere {dif:+.0%} del presupuesto del mes ($ {float(pres):,.0f}).".replace(",", "."))
    activos = {(o["plantilla_id"], o["alcance_tipo"], str(o["alcance_valor"])) for o in listar_objetivos()}
    for a, b, texto in CONFLICTOS:
        otro = b if plantilla_id == a else a if plantilla_id == b else None
        if otro and (otro, tipo, str(alcance_valor)) in activos:
            r("V7 Conflictos", "advierte", texto)
    rol = act_catalogo.rol_plataforma(pl["responsable"]) if not responsable_rol else responsable_rol
    if rol == "vendedor" and tipo != "vendedor":
        r("V8 Controlabilidad", "advierte", "Un vendedor no controla un objetivo de toda la empresa o sucursal.")
    if m.con_muestra and hist:
        volumen = statistics.mean(h["muestra"] for h in hist[:4])
        minimo = int(catalogo.empresa().get("muestra_minima", 30))
        if volumen < minimo:
            r("V9 Muestra suficiente", "advierte", f"Por período hay ~{volumen:.0f} casos (mínimo {minimo}): conviene un período más largo.")
    return res


def proponer(plantilla_id: str, alcance_tipo=None, alcance_valor=None, periodicidad: str | None = None, meta=None,
             responsable_rol: str | None = None, cascada_tiempo=None, cascada_alcance=None, hoy: date | None = None) -> dict:
    """Todo lo que el asistente muestra antes de guardar: meta sugerida, validación y cascada. No guarda nada."""
    hoy = hoy or date.today()
    pl = catalogo.plantillas()[plantilla_id]
    periodicidad = periodicidad or pl["periodicidades"][-1]
    alcance_tipo = alcance_tipo or "empresa"
    sugerida = sugerir(plantilla_id, alcance_tipo, alcance_valor, periodicidad, hoy) if metricas.metrica(pl["metrica"]) else \
        {"meta": None, "explicacion": "Métrica no disponible."}
    meta = sugerida["meta"] if meta in (None, "") else float(meta)
    responsable_rol = responsable_rol or act_catalogo.rol_plataforma(pl["responsable"])
    prevista = cascada(plantilla_id, alcance_tipo, alcance_valor, periodicidad, meta, hoy, cascada_tiempo, cascada_alcance) \
        if meta is not None and metricas.metrica(pl["metrica"]) else {"tiempo": [], "alcance": []}
    validacion = validar(plantilla_id, alcance_tipo, alcance_valor, periodicidad, meta, responsable_rol, hoy, prevista)
    m = metricas.metrica(pl["metrica"])
    ini, fin = periodo(periodicidad, hoy)
    return {"plantilla": {k: pl.get(k) for k in ("id", "nombre", "area", "metrica", "periodicidades", "alcances", "tipo_meta", "meta_sugerida",
                                                 "responsable", "palancas")},
            "metrica": m.__dict__ if m else None, "periodicidad": periodicidad, "periodo": {"inicio": ini.isoformat(), "fin": fin.isoformat()},
            "alcance_tipo": alcance_tipo, "alcance_valor": alcance_valor, "meta": meta, "sugerida": sugerida,
            "responsable_rol": responsable_rol, "cascada": prevista, "validacion": validacion,
            "bloquea": any(v["severidad"] == "bloquea" for v in validacion),
            "requiere_justificacion": any(v["severidad"] == "advierte" and v["regla"].startswith("V5") for v in validacion)}


def guardar(propuesta_args: dict, usuario: Usuario, justificacion: str | None = None, hoy: date | None = None) -> dict:
    """Valida de nuevo y guarda el objetivo (y su cascada) como activo. Requiere aprobación humana: la da quien guarda."""
    hoy = hoy or date.today()
    p = proponer(**propuesta_args, hoy=hoy)
    pl = catalogo.plantillas()[p["plantilla"]["id"]]
    if not puede_configurar(usuario, pl["area"]):
        raise PermissionError("Tu rol no configura objetivos de esta área.")
    if p["bloquea"]:
        raise ValueError("No se puede guardar: " + " ".join(v["mensaje"] for v in p["validacion"] if v["severidad"] == "bloquea"))
    if p["requiere_justificacion"] and not (justificacion or "").strip():
        raise ValueError("La meta quedó fuera de lo habitual (V5): escribí una justificación para activarla.")
    nombres = {t: {x["valor"]: x["nombre"] for x in v} for t, v in metricas.opciones_alcance().items()}
    ahora = datetime.now().isoformat(timespec="seconds")
    ini, fin = periodo(p["periodicidad"], hoy)

    def insertar(con, periodicidad, alcance_tipo, alcance_valor, meta_base, padre=None, participacion=None, curva=None):
        nombre_alc = "Empresa" if alcance_tipo == "empresa" else nombres.get(alcance_tipo, {}).get(str(alcance_valor), str(alcance_valor))
        cur = con.execute(
            "INSERT INTO objetivo (fuente, plantilla_id, nombre, metrica, alcance_tipo, alcance_valor, alcance_nombre, periodicidad, tipo_meta, "
            "curva_esperada, responsable_rol, objetivo_padre_id, metodo_reparto, area, estado, justificacion, creado_por, aprobado_por, creado_at, "
            "meta_base, participacion) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (almacen.fuente_actual(), pl["id"], pl["nombre"], pl["metrica"], alcance_tipo, None if alcance_valor in (None, "") else str(alcance_valor),
             nombre_alc, periodicidad, pl["tipo_meta"], curva or pl["curva_esperada"].get(periodicidad, "dias_habiles"), p["responsable_rol"], padre,
             "estacionalidad_historica" if padre else None, pl["area"], "activo", justificacion, usuario.nombre, usuario.nombre, ahora,
             meta_base, participacion))
        return cur.lastrowid

    with almacen.conectar() as con:
        raiz = insertar(con, p["periodicidad"], p["alcance_tipo"], p["alcance_valor"], p["meta"])
        con.execute("INSERT INTO objetivo_meta VALUES (?,?,?,?,?)", (raiz, ini.isoformat(), fin.isoformat(), p["meta"],
                                                                    "sugerida_aceptada" if p["meta"] == p["sugerida"]["meta"] else "manual"))
        for v in p["validacion"]:
            con.execute("INSERT INTO objetivo_validacion VALUES (?,?,?,?,?)", (raiz, v["regla"], v["severidad"], v["mensaje"], ahora))
        hijos = []
        for t in p["cascada"]["tiempo"]:
            if t["periodicidad"] in pl["periodicidades"] or t["periodicidad"] in ("semanal", "diario"):
                hijos.append(insertar(con, t["periodicidad"], p["alcance_tipo"], p["alcance_valor"], None, padre=raiz))
        for a in p["cascada"]["alcance"]:
            hijos.append(insertar(con, p["periodicidad"], a["tipo"], a["valor"], None, padre=raiz, participacion=a["participacion"]))
    return {"id": raiz, "hijos": hijos, "propuesta": p}


def archivar(objetivo_id: int, usuario: Usuario) -> None:
    o = obtener(objetivo_id)
    if not puede_configurar(usuario, o["area"]):
        raise PermissionError("Tu rol no configura objetivos de esta área.")
    with almacen.conectar() as con:
        con.execute("UPDATE objetivo SET estado='archivado' WHERE id=? OR objetivo_padre_id=?", (objetivo_id, objetivo_id))


def comentar(objetivo_id: int, usuario: Usuario, texto: str, hoy: date | None = None) -> None:
    o = obtener(objetivo_id)
    if not visible(o, usuario):
        raise PermissionError("Ese objetivo no es de tu área.")
    ini, _ = periodo(o["periodicidad"], hoy or date.today())
    with almacen.conectar() as con:
        con.execute("INSERT INTO objetivo_comentario VALUES (?,?,?,?,?)", (objetivo_id, ini.isoformat(), usuario.nombre, texto.strip()[:1000],
                                                                           datetime.now().isoformat(timespec="seconds")))


# --- explicación y detalle -------------------------------------------------------------

def explicar(o: dict, ev: dict, hoy: date) -> list[str]:
    """Qué explica la brecha: las dimensiones que más cayeron contra los mismos días del período anterior."""
    textos = []
    ini = date.fromisoformat(ev["periodo_inicio"])
    corte = min(date.fromisoformat(ev["periodo_fin"]), hoy - timedelta(days=1))
    if o["metrica"] in ("kpi:VEN-01", "kpi:VEN-02") and o["alcance_tipo"] in (None, "empresa") and corte >= ini:
        dias = (corte - ini).days
        a_ini, _a_fin = anterior(o["periodicidad"], ini)
        a_corte = a_ini + timedelta(days=dias)
        nombres = {t: {x["valor"]: x["nombre"] for x in v} for t, v in metricas.opciones_alcance().items()}
        caidas = []
        for dim in ("sucursal", "canal", "categoria"):
            ahora_, antes = metricas.desglose(o["metrica"], dim, ini, corte), metricas.desglose(o["metrica"], dim, a_ini, a_corte)
            for k in set(ahora_) | set(antes):
                dif = ahora_.get(k, 0) - antes.get(k, 0)
                if dif < 0:
                    caidas.append((dif, dim, nombres.get(dim, {}).get(str(k), str(k))))
        for dif, dim, nombre in sorted(caidas)[:3]:
            valor = f"$ {abs(dif):,.0f}".replace(",", ".") if o["metrica"] == "kpi:VEN-01" else f"{abs(dif):.0f} pedidos"
            textos.append(f"{dim.capitalize()} {nombre}: −{valor} contra los mismos días del período anterior.")
    if ev.get("ritmo_necesario"):
        valor = f"$ {ev['ritmo_necesario']:,.0f}".replace(",", ".") if (metricas.metrica(o["metrica"]) or metricas.Metrica("", "", "", "", True, ())).unidad == "moneda" \
            else f"{ev['ritmo_necesario']:.1f}"
        textos.append(f"Para cumplir hace falta {valor} por día hábil de acá al cierre.")
    return textos


def curva_real(o: dict, ev: dict, hoy: date) -> list[dict]:
    """Acumulado real vs esperado por día del período (para el gráfico del detalle)."""
    m = metricas.metrica(o["metrica"])
    if not m or not m.acumulable or ev.get("meta") is None:
        return []
    ini, fin = date.fromisoformat(ev["periodo_inicio"]), date.fromisoformat(ev["periodo_fin"])
    if o["metrica"] not in ("kpi:VEN-01", "kpi:VEN-02", "kpi:FIN-04") or o["periodicidad"] == "diario":
        return []
    w = pesos(o["curva_esperada"] if o["curva_esperada"] not in ("no_aplica", "intradia_historica") else "lineal", ini, fin, hoy)
    total = sum(w.values()) or 1
    if o["metrica"] == "kpi:FIN-04":
        cond = f" AND sucursal_id = {int(o['alcance_valor'])}" if o["alcance_tipo"] == "sucursal" and o["alcance_valor"] else ""
        diario = {str(f)[:10]: float(v or 0) for f, v in metricas._q(f"SELECT fecha, SUM(importe) FROM gastos WHERE fecha >= '{ini}' AND fecha <= '{fin}'{cond} GROUP BY fecha")}
    else:
        join, cond = metricas._filtro_ventas(o["alcance_tipo"], o["alcance_valor"])
        medida = "SUM(l.cantidad * l.precio_unitario)" if o["metrica"] == "kpi:VEN-01" else "COUNT(DISTINCT v.id)"
        diario = {str(f)[:10]: float(v or 0) for f, v in metricas._q(
            f"SELECT v.fecha, {medida} FROM ventas v JOIN ventas_lineas l ON l.venta_id = v.id{join} WHERE COALESCE(v.anulada, 0) = 0 "
            f"AND v.fecha >= '{ini}' AND v.fecha <= '{fin}'{cond} GROUP BY v.fecha")}
    acum_r = acum_e = 0.0
    puntos = []
    limite = date.fromisoformat(ev["datos_hasta"]) if ev.get("datos_hasta") else hoy
    for d in _dias(ini, fin):
        acum_e += ev["meta"] * w[d] / total
        real = None
        if d <= limite and d < hoy + timedelta(days=1):
            acum_r += diario.get(d.isoformat(), 0.0)
            real = round(acum_r, 2)
        puntos.append({"fecha": d.isoformat(), "esperado": round(acum_e, 2), "real": real})
    return puntos


def tablero(usuario: Usuario, periodicidad: str | None = None, hoy: date | None = None, ahora: datetime | None = None) -> dict:
    """Pantalla 'Mis objetivos': la última evaluación de cada objetivo visible (se reevalúa si la última tiene más de un ciclo)."""
    ahora = ahora or datetime.now()
    hoy = hoy or ahora.date()
    ciclo = float(catalogo.empresa().get("ciclo_minutos", 15))
    objetivos = [o for o in listar_objetivos() if visible(o, usuario)]
    cache = {o["id"]: o for o in listar_objetivos()}
    tarjetas = []
    for o in objetivos:
        if periodicidad and o["periodicidad"] != periodicidad:
            continue
        ult = ultimas_evaluaciones(o["id"], 1)
        ini, _ = periodo(o["periodicidad"], hoy)
        if ult and ult[0]["periodo_inicio"] == ini.isoformat() and \
                (ahora - datetime.fromisoformat(ult[0]["evaluado_at"])).total_seconds() < ciclo * 60:
            ev = dict(ult[0])
            ev["advertencias"] = json.loads(ev["advertencias"] or "[]")
            ev["periodo_fin"] = periodo(o["periodicidad"], hoy)[1].isoformat()
        else:
            ev = evaluar(o, hoy, ahora, cache=cache)
        m = metricas.metrica(o["metrica"])
        tarjetas.append({"objetivo": o, "evaluacion": ev, "unidad": m.unidad if m else None})
    puntaje_num = sum(t["objetivo"]["peso"] * {"cumplido": 1, "en_camino": 1, "en_riesgo": 0.5, "fuera_de_camino": 0}.get(t["evaluacion"]["estado"], 0)
                      for t in tarjetas)
    puntaje_den = sum(t["objetivo"]["peso"] for t in tarjetas if t["evaluacion"]["estado"] not in ("no_evaluable", "sin_meta"))
    tarjetas.sort(key=lambda t: (PRIORIDAD_ESTADO.get(t["evaluacion"]["estado"], 9), t["objetivo"]["area"] or "", t["objetivo"]["id"]))
    return {"objetivos": tarjetas, "puntaje": round(puntaje_num / puntaje_den, 3) if puntaje_den else None,
            "datos_actualizados_at": (datos_actualizados_at() or ahora).isoformat(timespec="seconds"), "evaluado_at": ahora.isoformat(timespec="seconds"),
            "puede_configurar": usuario.rol == "dueno" or bool(catalogo.areas_de(usuario.rol)) and usuario.vendedor_id is None}


def detalle(objetivo_id: int, usuario: Usuario, hoy: date | None = None, ahora: datetime | None = None) -> dict:
    ahora = ahora or datetime.now()
    hoy = hoy or ahora.date()
    o = obtener(objetivo_id)
    if not visible(o, usuario):
        raise PermissionError("Ese objetivo no es de tu área.")
    ev = evaluar(o, hoy, ahora)
    pl = catalogo.plantillas().get(o["plantilla_id"]) or {}
    from ..actividades import motor
    palancas = [p for p in pl.get("palancas", []) if p.startswith("ACT-")]
    tareas = [{"id": t["id"], "tipo": t["tipo"], "titulo": t["titulo"], "impacto": t["impacto_estimado"]}
              for t in motor.listar(usuario) if t["tipo"] in palancas][:8]
    with almacen.conectar() as con:
        hijos = [dict(r) for r in con.execute("SELECT * FROM objetivo WHERE objetivo_padre_id=? AND estado='activo'", (objetivo_id,))]
        comentarios = [dict(r) for r in con.execute("SELECT * FROM objetivo_comentario WHERE objetivo_id=? ORDER BY creado_at DESC LIMIT 20",
                                                    (objetivo_id,))]
        validacion = [dict(r) for r in con.execute("SELECT regla, severidad, mensaje FROM objetivo_validacion WHERE objetivo_id=?", (objetivo_id,))]
    cache = {o["id"]: o}
    hijos_ev = [{"objetivo": h, "evaluacion": evaluar(h, hoy, ahora, guardar=False, cache=cache)} for h in hijos]
    hist = historia(o["metrica"], o["alcance_tipo"], o["alcance_valor"], o["periodicidad"], hoy, 6)
    return {"objetivo": o, "evaluacion": ev, "curva": curva_real(o, ev, hoy), "explicacion": explicar(o, ev, hoy),
            "palancas": pl.get("palancas", []), "tareas_palanca": tareas, "hijos": hijos_ev, "historia": hist,
            "comentarios": comentarios, "validacion": validacion,
            "acciones": {"en_riesgo": pl.get("si_en_riesgo", []), "fuera_de_camino": pl.get("si_fuera_de_camino", [])},
            "unidad": (metricas.metrica(o["metrica"]).unidad if metricas.metrica(o["metrica"]) else None)}


def plantillas_disponibles(hoy: date | None = None) -> list[dict]:
    hoy = hoy or date.today()
    res = []
    for pl in catalogo.plantillas().values():
        ok, motivo = metricas.disponible(pl["metrica"], hoy)
        res.append({k: pl.get(k) for k in ("id", "nombre", "area", "metrica", "periodicidades", "alcances", "tipo_meta", "responsable", "meta_sugerida")}
                   | {"disponible": ok, "motivo": motivo,
                      "alcances_validos": [a for a in pl.get("alcances", []) if metricas.metrica(pl["metrica"]) and a in metricas.metrica(pl["metrica"]).alcances]})
    return res
