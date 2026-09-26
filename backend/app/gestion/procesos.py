"""Procesos estándar medidos paso a paso con los datos de la plataforma.

Cada proceso del catálogo (config/gestion/procesos.yml) se reconstruye con las
tablas de la plataforma según config/gestion/empresa.yaml: cada caso (un pedido,
una factura a cobrar, una orden de compra) y el estado de cada paso:
completado, completado_fuera_de_sla, pendiente_en_plazo, pendiente_vencido,
omitido, fuera_de_orden, no_aplica o sin_dato (la integración no trae ese dato).
Los pasos sin dato nunca cuentan como omitidos.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..erp import conector
from . import almacen, catalogo

HISTORIA_DIAS = 120
SIN_LIMITE = 2_000_000
ESTADOS = ["completado", "completado_fuera_de_sla", "pendiente_en_plazo", "pendiente_vencido", "omitido",
           "fuera_de_orden", "no_aplica", "sin_dato"]


def _fecha(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _q(sql: str) -> list[list]:
    return conector.consultar(sql, max_filas=SIN_LIMITE)["filas"]


def _p(valores: list[float], q: float) -> float | None:
    if not valores:
        return None
    v = sorted(valores)
    i = (len(v) - 1) * q
    a, b = int(i), min(int(i) + 1, len(v) - 1)
    return round(v[a] + (v[b] - v[a]) * (i - a), 2)


@dataclass
class Caso:
    key: str
    etiqueta: str
    inicio: date
    datos: dict
    pasos: dict = field(default_factory=dict)      # codigo → {estado, fecha, vence, ...}
    cerrado: bool = False
    fin: date | None = None
    detenido: dict | None = None
    escalon: dict | None = None

    @property
    def vencidos(self) -> list[str]:
        """Pasos obligatorios vencidos (los opcionales vencidos cuentan en el cumplimiento de plazos, pero no traban el caso)."""
        return [c for c, p in self.pasos.items() if p["estado"] == "pendiente_vencido" and p["obligatorio"]]

    @property
    def trabado(self) -> bool:
        return not self.cerrado and bool(self.vencidos or self.detenido)


def _aplica(paso: dict, cfg_paso: dict, caso: dict, variante: str | None, hoy: date) -> bool:
    cond = cfg_paso.get("aplica_si")
    if isinstance(cond, dict):
        ok = True
        if "saldo_mayor_a" in cond:
            ok &= (caso.get("_saldo") or 0) > cond["saldo_mayor_a"]
        if "vencido" in cond:
            v = _fecha(caso.get(cond["vencido"]))
            ok &= bool(v and hoy > v)
        return ok
    texto = paso.get("aplica_si") or ""
    m = re.match(r"variante\s*=\s*'(\w+)'", texto)
    if m:
        return variante is None or variante == m.group(1)
    return True


class Proceso:
    def __init__(self, proceso_id: str, hoy: date, eventos: dict | None = None):
        self.id = proceso_id
        self.hoy = hoy
        self.def_ = catalogo.procesos()[proceso_id]
        self.cfg = catalogo.config_proceso(proceso_id)
        self.activo = bool(self.cfg.get("activo"))
        self.motivo = self.cfg.get("motivo")
        self.casos: list[Caso] = []
        self.error: str | None = None
        self._eventos = eventos
        if self.activo:
            try:
                self._cargar()
            except Exception as e:  # la tabla del caso no existe en esta fuente
                self.activo, self.error = False, f"No se pudo leer: {type(e).__name__}: {str(e).splitlines()[0][:160]}"

    # --- lectura ------------------------------------------------------------------------
    def _cargar(self) -> None:
        caso = self.cfg["caso"]
        pasos_cfg = self.cfg.get("pasos") or {}
        columnas = {caso["clave"], caso["inicio"]}
        for extra in ("etiqueta", "importe", "saldo", "cliente", "vendedor", "sucursal", "proveedor"):
            if caso.get(extra):
                columnas.add(caso[extra])
        for pc in pasos_cfg.values():
            for k in ("columna", "limite", "desde_columna"):
                if pc.get(k):
                    columnas.add(pc[k])
            v = (pc.get("aplica_si") or {}) if isinstance(pc.get("aplica_si"), dict) else {}
            if v.get("vencido"):
                columnas.add(v["vencido"])
        columnas = sorted(columnas)
        desde = (self.hoy - timedelta(days=HISTORIA_DIAS * 3)).isoformat()
        filtro = f" AND ({caso['filtro']})" if caso.get("filtro") else ""
        filas = _q(f"SELECT {', '.join(columnas)} FROM {caso['tabla']} WHERE {caso['inicio']} >= '{desde}' "
                   f"AND {caso['inicio']} <= '{self.hoy.isoformat()}'{filtro}")
        relaciones = {}
        for codigo, pc in pasos_cfg.items():
            r = pc.get("relacion")
            if r:
                agg = "MIN" if r.get("agregacion", "min") == "min" else "MAX"
                relaciones[codigo] = {str(k): _fecha(v) for k, v in _q(
                    f"SELECT {r['clave']}, {agg}({r['columna']}) FROM {r['tabla']} WHERE {r['clave']} IS NOT NULL GROUP BY {r['clave']}")}
        variantes = {}
        var = self.cfg.get("variante")
        if var and caso.get("cliente"):
            umbral = var.get("cuenta_corriente_si_mayor_a", 0)
            variantes = {i: ("cuenta_corriente" if (v or 0) > umbral else "prepago")
                         for i, v in _q(f"SELECT id, {var['columna']} FROM {var['de_tabla']}")}
        eventos = self._eventos if self._eventos is not None else eventos_manuales(self.id)
        for fila in filas:
            d = dict(zip(columnas, fila))
            inicio = _fecha(d[caso["inicio"]])
            if not inicio:
                continue
            key = str(d[caso["clave"]])
            d["_saldo"] = d.get(caso["saldo"]) if caso.get("saldo") else None
            c = Caso(key, str(d.get(caso.get("etiqueta")) or key), inicio, d)
            self._pasos(c, relaciones, variantes.get(d.get(caso.get("cliente"))), eventos)
            if c.cerrado and c.fin and c.fin < self.hoy - timedelta(days=HISTORIA_DIAS):
                continue
            self.casos.append(c)
        self._detenidos()

    def _pasos(self, c: Caso, relaciones: dict, variante: str | None, eventos: dict) -> None:
        cfg = self.cfg.get("pasos") or {}
        caso = self.cfg["caso"]
        pasos = self.def_["pasos"]
        # 1) fecha de cada paso
        for s in pasos:
            pc = cfg.get(s["codigo"])
            info = {"codigo": s["codigo"], "nombre": s["nombre"], "obligatorio": bool(s.get("obligatorio")), "fecha": None,
                    "vence": None, "manual": bool(pc and pc.get("evento_proceso")), "evento": (pc or {}).get("evento_proceso")}
            if not pc:
                info["estado"] = "sin_dato"
            elif not _aplica(s, pc, c.datos, variante, self.hoy):
                info["estado"] = "no_aplica"
            else:
                if pc.get("columna"):
                    info["fecha"] = _fecha(c.datos.get(pc["columna"]))
                elif pc.get("relacion"):
                    info["fecha"] = relaciones.get(s["codigo"], {}).get(c.key)
                elif pc.get("evento_proceso"):
                    info["fecha"] = eventos.get((c.key, pc["evento_proceso"]))
                info["estado"] = None
            c.pasos[s["codigo"]] = info
        # Documento cancelado sin fecha de cobro (saldo 0): el paso final está hecho, sin fecha conocida
        if caso.get("saldo") and c.datos.get("_saldo") is not None and float(c.datos["_saldo"] or 0) <= 0:
            final = self._final(c)
            if final and not c.pasos[final]["fecha"]:
                c.pasos[final]["fecha"] = c.pasos[final]["fecha"] or c.inicio
                c.pasos[final]["sin_fecha"] = True
        # 2) plazo y estado
        codigos = [s["codigo"] for s in pasos]
        for i, s in enumerate(pasos):
            p = c.pasos[s["codigo"]]
            if p["estado"] in ("sin_dato", "no_aplica"):
                continue
            p["vence"] = self._vence(s, cfg[s["codigo"]], c)
            posteriores = [c.pasos[x] for x in codigos[i + 1:] if c.pasos[x]["fecha"] and c.pasos[x]["estado"] != "no_aplica"]
            if p["fecha"]:
                previos = [c.pasos[x]["fecha"] for x in codigos[:i] if c.pasos[x]["fecha"] and c.pasos[x]["obligatorio"]]
                if previos and p["fecha"] < max(previos) and not p.get("sin_fecha"):
                    p["estado"] = "fuera_de_orden"
                elif p["vence"] and p["fecha"] > p["vence"]:
                    p["estado"] = "completado_fuera_de_sla"
                else:
                    p["estado"] = "completado"
            elif posteriores:
                p["estado"] = "omitido" if p["obligatorio"] else "no_aplica"
            elif p["vence"] and self.hoy > p["vence"]:
                p["estado"] = "pendiente_vencido"
            else:
                p["estado"] = "pendiente_en_plazo"
        final = self._final(c)
        if final and c.pasos[final]["fecha"]:
            c.cerrado, c.fin = True, c.pasos[final]["fecha"]
            for p in c.pasos.values():   # lo opcional que quedó pendiente en un caso cerrado ya no aplica
                if p["estado"] in ("pendiente_en_plazo", "pendiente_vencido") and not p["obligatorio"]:
                    p["estado"] = "no_aplica"
        # Escalamiento del paso vencido (ej. cobranza a 15/30/60 días)
        for s in pasos:
            p = c.pasos[s["codigo"]]
            if p["estado"] == "pendiente_vencido" and s.get("escalamiento") and p["vence"]:
                atraso = (self.hoy - p["vence"]).days
                alcanzados = [e for e in s["escalamiento"] if atraso >= e["dias_vencido"]]
                if alcanzados:
                    c.escalon = {**alcanzados[-1], "paso": s["codigo"], "dias": atraso}

    def _final(self, c: Caso) -> str | None:
        """Último paso obligatorio que se puede medir y aplica: cuando ocurre, el caso está cerrado."""
        for s in reversed(self.def_["pasos"]):
            p = c.pasos.get(s["codigo"])
            if p and s.get("obligatorio") and p["estado"] not in ("sin_dato", "no_aplica") and not p["manual"]:
                return s["codigo"]
        return None

    def _vence(self, s: dict, pc: dict, c: Caso) -> date | None:
        sla = dict(s.get("sla") or {})
        sla.update(pc.get("sla") or {})
        if not sla:
            return None
        if "limite" in sla:
            lim = _fecha(c.datos.get(pc.get("limite"))) if pc.get("limite") else None
            if lim:
                return lim
            sla = sla.get("alternativa") or {}
            if not sla:
                return None
        if "desde_columna" in sla:
            base = _fecha(c.datos.get(pc.get("desde_columna"))) if pc.get("desde_columna") else None
            return catalogo.plazo(sla, base) if base else None
        if "desde" in sla:
            for origen in (sla["desde"], sla.get("alternativa_desde")):
                if origen and c.pasos.get(origen, {}).get("fecha"):
                    return catalogo.plazo(sla, c.pasos[origen]["fecha"])
        return None

    def _detenidos(self, factor: float = 2.0) -> None:
        """Caso abierto que no avanza hace más de 2 × P90 histórico del paso actual (aunque el paso no tenga plazo)."""
        codigos = [s["codigo"] for s in self.def_["pasos"]]
        historico: dict[str, list[int]] = {}
        for c in self.casos:
            ultima = c.inicio
            for cod in codigos:
                p = c.pasos[cod]
                if p["fecha"] and p["estado"] in ("completado", "completado_fuera_de_sla") and not p.get("sin_fecha"):
                    historico.setdefault(cod, []).append((p["fecha"] - ultima).days)
                    ultima = p["fecha"]
        for c in self.casos:
            if c.cerrado or c.vencidos:
                continue
            fechas = [p["fecha"] for p in c.pasos.values() if p["fecha"]]
            ultima = max(fechas) if fechas else c.inicio
            actual = next((cod for cod in codigos if c.pasos[cod]["estado"] == "pendiente_en_plazo"
                           and not c.pasos[cod]["manual"]), None)
            if not actual:
                continue
            muestra = historico.get(actual, [])
            p90 = _p(muestra, 0.9) if len(muestra) >= 10 else None
            if p90 and (self.hoy - ultima).days > factor * max(p90, 1):
                c.detenido = {"paso": actual, "dias": (self.hoy - ultima).days, "p90": p90}

    # --- métricas -----------------------------------------------------------------------
    def metricas(self, desde: date, hasta: date, filtro=None) -> dict:
        casos = [c for c in self.casos if not filtro or filtro(c)]
        en = lambda d: d is not None and desde <= d <= hasta  # noqa: E731
        completados = [c for c in casos if c.cerrado and en(c.fin)]
        ciclos = [(c.fin - c.inicio).days for c in completados if not c.pasos[self._final(c)].get("sin_fecha")]
        res = {
            "casos_iniciados": sum(1 for c in casos if en(c.inicio)),
            "casos_completados": len(completados),
            "casos_en_curso": sum(1 for c in casos if not c.cerrado),
            "casos_trabados": sum(1 for c in casos if c.trabado),
            "casos_vencidos_abiertos": sum(1 for c in casos if not c.cerrado and c.vencidos),
            "tiempo_ciclo_p50": _p(ciclos, 0.5), "tiempo_ciclo_p90": _p(ciclos, 0.9),
            "conformidad_pct": (round(sum(1 for c in completados if not any(p["estado"] in ("omitido", "fuera_de_orden")
                                                                          for p in c.pasos.values())) / len(completados), 4)
                                if completados else None),
            "muestra": len(completados),
        }
        a_tiempo = total = 0
        pasos = {}
        for s in self.def_["pasos"]:
            cod = s["codigo"]
            estados = {e: 0 for e in ESTADOS}
            ok = tot = 0
            tiempos = []
            for c in casos:
                p = c.pasos[cod]
                if not (en(c.inicio) or not c.cerrado or en(c.fin)):
                    continue
                estados[p["estado"]] += 1
                if p["vence"] and p["estado"] in ("completado", "completado_fuera_de_sla", "fuera_de_orden") and en(p["fecha"]):
                    tot += 1
                    ok += p["estado"] != "completado_fuera_de_sla"
                elif p["estado"] == "pendiente_vencido" and en(p["vence"]):
                    tot += 1
                if p["fecha"] and en(p["fecha"]) and not p.get("sin_fecha"):
                    previas = [c.pasos[x["codigo"]]["fecha"] for x in self.def_["pasos"][:self.def_["pasos"].index(s)]
                               if c.pasos[x["codigo"]]["fecha"]]
                    if previas:
                        tiempos.append((p["fecha"] - max(previas)).days)
            a_tiempo += ok
            total += tot
            pasos[cod] = {"codigo": cod, "nombre": s["nombre"], "obligatorio": bool(s.get("obligatorio")),
                          "medible": estados["sin_dato"] == 0 and any(v for k, v in estados.items() if k != "sin_dato"),
                          "manual": bool((self.cfg.get("pasos") or {}).get(cod, {}).get("evento_proceso")),
                          "estados": estados, "cumplimiento_sla_pct": round(ok / tot, 4) if tot else None, "muestra_sla": tot,
                          "tiempo_paso_p50": _p(tiempos, 0.5), "sla": s.get("sla"), "si_vence": s.get("si_vence")}
        res["cumplimiento_sla_pct"] = round(a_tiempo / total, 4) if total else None
        res["muestra_sla"] = total
        res["pasos"] = pasos
        return res

    def valor(self, metrica: str, desde: date, hasta: date, filtro=None) -> tuple[float | None, int]:
        """'P3.cumplimiento_sla_pct' o 'tiempo_ciclo_p90' → (valor, muestra)."""
        m = self.metricas(desde, hasta, filtro)
        partes = metrica.split(".")
        if len(partes) == 2:
            p = m["pasos"].get(partes[0]) or {}
            if not p.get("medible") and not p.get("manual"):
                return None, 0
            return p.get(partes[1]), p.get("muestra_sla", 0)
        muestra = m["muestra_sla"] if metrica == "cumplimiento_sla_pct" else m["muestra"]
        return m.get(metrica), muestra


def eventos_manuales(proceso_id: str) -> dict:
    with almacen.conectar() as con:
        filas = con.execute("SELECT caso_key, codigo, MIN(fecha) FROM evento_proceso WHERE fuente=? AND proceso=? GROUP BY caso_key, codigo",
                            (almacen.fuente_actual(), proceso_id)).fetchall()
    return {(k, cod): _fecha(f) for k, cod, f in filas}


def registrar_evento(proceso_id: str, caso_key: str, codigo: str, usuario: str, fecha: date | None = None,
                     resultado: str | None = None, detalle: str | None = None, origen: str = "tablero") -> dict:
    """Registra un paso que ningún sistema marca (ej. gestión de cobranza). Solo en la base de gestión, nunca en el ERP."""
    if proceso_id not in catalogo.procesos():
        raise KeyError("Proceso desconocido.")
    pasos = catalogo.config_proceso(proceso_id).get("pasos") or {}
    validos = {pc["evento_proceso"] for pc in pasos.values() if pc.get("evento_proceso")}
    if codigo not in validos:
        raise ValueError(f"Ese paso no se registra a mano en {proceso_id}. Válidos: {', '.join(sorted(validos)) or 'ninguno'}.")
    fecha = fecha or date.today()
    with almacen.conectar() as con:
        cur = con.execute("INSERT INTO evento_proceso (fuente, proceso, caso_key, codigo, fecha, resultado, detalle, usuario, origen, registrado_at) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (almacen.fuente_actual(), proceso_id, str(caso_key), codigo, fecha.isoformat(), resultado,
                           (detalle or "")[:1000], usuario, origen, datetime.now().isoformat(timespec="seconds")))
        return {"id": cur.lastrowid, "proceso": proceso_id, "caso_key": str(caso_key), "codigo": codigo, "fecha": fecha.isoformat()}


def todos(hoy: date) -> dict[str, Proceso]:
    return {pid: Proceso(pid, hoy) for pid in catalogo.procesos()}
