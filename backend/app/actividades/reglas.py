"""Las 6 reglas de config/actividades.yml sobre el modelo de datos de la plataforma.

Cada regla es determinística (sin modelo de lenguaje): recorre el negocio,
detecta y asigna cada detección a un caso del catálogo. El caso trae las
acciones (qué hacer, quién y en qué plazo). Lo que no encaja en ningún caso no
se emite: queda como descarte para revisar la regla.

Equivalencias con el modelo canónico del catálogo: punto de venta = sucursal
(ventas.sucursal_id), lote = fila de stock con lote y fecha_vencimiento, lista
del proveedor = costos_historial, precio de venta = productos.precio / precios.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import catalogo
from .datos import Datos, _f, _fecha, cv_semanal


@dataclass
class Deteccion:
    actividad: str
    caso: str
    clave: str
    titulo: str
    impacto: float
    prioridad: str | None = None          # None = la del caso en el catálogo
    entidad: dict = field(default_factory=dict)
    evidencia: list = field(default_factory=list)   # [etiqueta, valor, formato]
    notas: list = field(default_factory=list)       # cálculos que completan las acciones (descuento sugerido, destino...)
    detalle: dict | None = None                     # tabla adjunta: {"columnas": [...], "tipos": [...], "filas": [...]}


@dataclass
class Resultado:
    detecciones: list = field(default_factory=list)
    descartes: list = field(default_factory=list)   # (clave, motivo)
    faltan: list = field(default_factory=list)      # datos que la regla necesita y la base no tiene


def _ev(etiqueta, valor, formato="numero"):
    return [etiqueta, valor, formato]


def _n(cantidad: int, palabra: str) -> str:
    return f"{cantidad} {palabra}" + ("" if cantidad == 1 else "s")


def _r(x, n=2):
    return round(x, n) if x is not None and not (isinstance(x, float) and math.isnan(x)) else None


# --- ACT-01 · Quiebre oculto --------------------------------------------------------------

def act01(d: Datos, historial) -> Resultado:
    p = catalogo.parametros("ACT-01")
    res = Resultado()
    if not d.unidades:
        res.faltan.append("ventas por día y sucursal (ventas, ventas_lineas)")
        return res
    if not d.stock:
        res.faltan.append("stock por sucursal (stock)")
        return res
    base_dias = d.dias(int(p["ventana_base_dias"]), d.hoy - timedelta(days=7))
    recientes = d.dias(7)
    ticket_medio = {}
    for suc in d.puntos():
        t = d.tickets.get(suc, {})
        for dow in range(7):
            valores = [t.get(x, 0) for x in base_dias if x.weekday() == dow and t.get(x, 0) > 0]
            ticket_medio[(suc, dow)] = statistics.mean(valores) if valores else 0
    for (pid, suc) in sorted(d.unidades, key=lambda k: (k[0], str(k[1]))):
        if suc is None or (pid, suc) not in d.puntos_stock:
            continue
        prod = d.productos.get(pid) or {}
        abiertos = d.dias_abiertos(suc, base_dias)
        if len(abiertos) < 10:
            continue
        serie = d.serie(pid, suc, abiertos)
        lam = statistics.mean(serie)
        pct = sum(1 for u in serie if u > 0) / len(serie)
        if pct < p["pct_dias_con_venta_min"] or lam < p["lambda_min"]:
            continue
        # Racha de días abiertos y con actividad normal sin venta, desde la última venta
        k = 0
        t = d.tickets.get(suc, {})
        ultima = d.ultima_venta(pid, suc)
        for dia in reversed(recientes):
            if ultima and dia <= ultima:
                break
            medio = ticket_medio.get((suc, dia.weekday()), 0)
            if medio and t.get(dia, 0) / medio >= p["actividad_local_min"]:
                k += 1
        prob = math.exp(-lam * k)
        if k == 0 or prob >= p["prob_umbral"]:
            continue
        disp, _ = d.stock_de(pid, suc)
        clave = f"ACT-01|{pid}|{suc}"
        if disp <= 0:
            res.descartes.append((clave, "Sin stock en sistema: no es quiebre oculto (lo trata el pedido sugerido)."))
            continue
        if prod.get("estado") in ("discontinuado", "estacional_fuera_temporada"):
            res.descartes.append((clave, f"Producto {prod.get('estado')}."))
            continue
        if any(pr["producto_id"] == pid and d.hoy - timedelta(days=3) <= pr["hasta"] < d.hoy for pr in d.promociones):
            res.descartes.append((clave, "Terminó una promoción del producto en los últimos 3 días."))
            continue
        subio = _suba_precio(d, pid, 7)
        if subio is not None and subio > p["variacion_precio_excluir"]:
            res.descartes.append((clave, f"El precio subió {subio:.0%} en los últimos 7 días (lo evalúa remarcación)."))
            continue
        if cv_semanal(d.serie(pid, suc, base_dias)) > 1:
            res.descartes.append((clave, "Demanda irregular (variación semanal mayor a 1)."))
            continue
        precio = d.precio_medio(pid, suc)
        perdida = lam * k * precio
        clase = d.abc.get(pid, "C")
        previo = historial(clave)
        exhibido = next((h for h in previo if h["caso"] == "C1" and h["resolucion"] == "estaba_exhibido"
                         and _fecha(h["resuelta_at"]) and _fecha(h["resuelta_at"]) >= d.hoy - timedelta(days=14)), None)
        caso = "C2" if exhibido else "C1"
        nombre, sucursal = d.nombre_producto(pid), d.nombre_sucursal(suc)
        res.detecciones.append(Deteccion(
            "ACT-01", caso, clave,
            (f"Revisar exhibición y precio: {nombre} en {sucursal}" if caso == "C2" else f"Revisar góndola: {nombre} en {sucursal}"),
            perdida, prioridad=("critica" if clase == "A" and caso == "C1" else None),
            entidad={"producto_id": pid, "producto": nombre, "sucursal_id": suc, "sucursal": sucursal, "clase_abc": clase},
            evidencia=[_ev("Venta media", _r(lam, 1), "u/día"), _ev("Días con venta (4 semanas)", _r(pct, 3), "pct"),
                       _ev("Días seguidos sin venta", k, "numero"), _ev("Probabilidad de que sea casualidad", _r(prob, 4), "pct"),
                       _ev("Stock en sistema hoy", _r(disp, 1), "u"), _ev("Venta perdida estimada", _r(perdida), "moneda"),
                       _ev("Cada día más sin resolver", _r(lam * precio), "moneda")],
            notas=([f"En la revisión anterior se marcó como exhibido y la venta no se recuperó."] if caso == "C2" else [])))
    # C3 también se detecta directo: un conteo físico reciente con menos de la mitad del stock del sistema
    for c in d.conteos:
        f = _fecha(c["fecha"])
        sistema, contado = _f(c["cantidad_sistema"]), _f(c["cantidad_contada"])
        if not f or f < d.hoy - timedelta(days=7) or sistema <= 0 or contado >= 0.5 * sistema:
            continue
        pid, suc = c["producto_id"], c["sucursal_id"]
        clave = f"ACT-01|{pid}|{suc}"
        fantasmas = sum(1 for h in historial(clave) if h["caso"] == "C3" and _fecha(h["detectada_at"]) >= d.hoy - timedelta(days=60))
        nombre, sucursal = d.nombre_producto(pid), d.nombre_sucursal(suc)
        res.detecciones.append(Deteccion(
            "ACT-01", "C3", clave, f"Stock fantasma: {nombre} en {sucursal}", (sistema - contado) * d.precio_actual(pid),
            entidad={"producto_id": pid, "producto": nombre, "sucursal_id": suc, "sucursal": sucursal},
            evidencia=[_ev("Stock en sistema", sistema, "u"), _ev("Contado", contado, "u"), _ev("Fecha del conteo", f.isoformat(), "texto"),
                       _ev("Stock fantasma en 60 días", fantasmas + 1, "numero")]))
    return res


def _suba_precio(d: Datos, pid, dias: int) -> float | None:
    """Mayor suba de precio de lista en los últimos `dias` días."""
    mayor = None
    for serie in (d.precios.get(pid) or {}).values():
        for i in range(1, len(serie)):
            if serie[i][0] >= d.hoy - timedelta(days=dias) and serie[i - 1][1]:
                v = serie[i][1] / serie[i - 1][1] - 1
                mayor = v if mayor is None else max(mayor, v)
    return mayor


# --- ACT-02 · Pedido sugerido -------------------------------------------------------------

_Z = {"A": 1.65, "B": 1.28, "C": 0.84}
_DIAS_SEMANA = ["lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"]


def _dias_hasta_pedido(texto: str | None, hoy: date) -> int | None:
    """Días hasta el próximo día de pedido ("lunes, jueves"); 0 si es hoy; None si no está cargado."""
    if not texto:
        return None
    t = catalogo._sin_tildes(texto)
    dias = [i for i, n in enumerate(_DIAS_SEMANA) if n in t or n[:3] in t.replace(",", " ").split()]
    if not dias:
        return None
    return min((i - hoy.weekday()) % 7 for i in dias)


def _siguiente_pedido(texto: str | None, hoy: date) -> int | None:
    if not texto:
        return None
    t = catalogo._sin_tildes(texto)
    dias = [i for i, n in enumerate(_DIAS_SEMANA) if n in t or n[:3] in t.replace(",", " ").split()]
    return min(((i - hoy.weekday() - 1) % 7) + 1 for i in dias) if dias else None


def act02(d: Datos, historial) -> Resultado:
    p = catalogo.parametros("ACT-02")
    res = Resultado()
    if not d.productos:
        res.faltan.append("productos")
        return res
    if not any(pr.get("proveedor_id") for pr in d.productos.values()):
        res.faltan.append("proveedor principal de cada producto (productos.proveedor_id)")
        return res
    lineas_por_prov: dict = {}
    urgentes: dict = {}
    for pid, prod in sorted(d.productos.items()):
        prov = prod.get("proveedor_id")
        if not prov:
            continue
        estado = prod.get("estado") or "activo"
        disp, trans_stock = d.stock_de(pid)
        trans = max(trans_stock, d.pendiente_compra.get(pid, 0.0))
        nombre = d.nombre_producto(pid)
        if estado in ("a_discontinuar", "discontinuado"):
            if d.pendiente_compra.get(pid):
                res.detecciones.append(Deteccion(
                    "ACT-02", "C5", f"ACT-02|C5|{pid}", f"Cancelar reposición de {nombre} ({estado.replace('_', ' ')})",
                    d.pendiente_compra[pid] * d.costo(pid),
                    entidad={"producto_id": pid, "producto": nombre, "proveedor_id": prov, "proveedor": d.nombre_proveedor(prov)},
                    evidencia=[_ev("Unidades pedidas sin recibir", d.pendiente_compra[pid], "u"), _ev("Stock", disp, "u")]))
            continue
        demanda = d.vdp(pid, None, 56)
        if demanda <= 0:
            continue
        clase = d.abc.get(pid, "C")
        cobertura = (disp + trans) / demanda
        if clase == "C" and cobertura > 60:
            continue
        lt = d.lead_time(prov)
        prox = _siguiente_pedido((d.proveedores.get(prov) or {}).get("dias_pedido"), d.hoy)
        revision = prox if prox is not None else p["dias_revision_default"]
        ss = _Z[clase] * d.sigma(pid) * math.sqrt(lt)
        necesidad = demanda * (lt + revision) + ss - (disp + trans)
        bulto = int(_f(prod.get("unidades_bulto")) or 1)
        cantidad = math.ceil(max(0.0, necesidad) / bulto) * bulto
        politica = catalogo.politica("politica_producto", prod)
        cobertura_obj = _f(politica.get("cobertura_objetivo_dias")) or 21
        tope_cob = cobertura_obj * p["tope_cobertura_factor"] * demanda - (disp + trans)
        limitado = False
        vida = _f(prod.get("vida_util_dias"))
        if prod.get("perecedero") and vida:
            tope_venc = demanda * (vida - _f(politica.get("dias_retiro_antes_vencimiento"))) * p["factor_vida_util"] - disp
            if cantidad > tope_venc:
                cantidad = max(0, math.floor(max(0.0, tope_venc) / bulto) * bulto)
                limitado = cantidad > 0   # con 0 el stock actual ya cubre la vida útil: no se pide
        if cantidad > tope_cob > 0 and not limitado:
            cantidad = max(bulto, math.floor(tope_cob / bulto) * bulto)
        costo = d.costo(pid)
        linea = [nombre, clase, _r(disp, 1), _r(trans, 1), _r(demanda, 2), _r(cobertura, 1), _r(lt, 0), cantidad,
                 cantidad // bulto if bulto else cantidad, _r(costo), _r(cantidad * costo)]
        if cobertura < lt and clase in ("A", "B"):
            urgentes.setdefault(prov, []).append((linea, demanda * max(0.0, lt - cobertura) * d.precio_medio(pid)))
        if limitado:
            res.detecciones.append(Deteccion(
                "ACT-02", "C4", f"ACT-02|C4|{pid}", f"Comprar solo {cantidad:g} u de {nombre} (vence)", cantidad * costo,
                entidad={"producto_id": pid, "producto": nombre, "proveedor_id": prov, "proveedor": d.nombre_proveedor(prov)},
                evidencia=[_ev("Venta diaria", _r(demanda, 2), "u/día"), _ev("Vida útil", vida, "días"), _ev("Cantidad tope", cantidad, "u")],
                notas=[f"Pedir cada {max(1, int(vida * 0.5))} días como máximo para que no se venza."]))
        if cantidad > 0:
            lineas_por_prov.setdefault(prov, []).append(linea)
    columnas = ["Producto", "Clase", "Stock", "En tránsito", "Venta diaria", "Cobertura (días)", "Entrega (días)",
                "Sugerido (u)", "Bultos", "Costo", "Importe"]
    tipos = ["texto", "texto", "numero", "numero", "numero", "numero", "numero", "numero", "numero", "moneda", "moneda"]
    for prov, items in urgentes.items():
        nombre = d.nombre_proveedor(prov)
        filas = [x[0] for x in items]
        res.detecciones.append(Deteccion(
            "ACT-02", "C1", f"ACT-02|C1|{prov}", f"Pedido urgente a {nombre}: {_n(len(filas), 'producto')} por quebrar",
            sum(x[1] for x in items),
            entidad={"proveedor_id": prov, "proveedor": nombre},
            evidencia=[_ev("Productos por quebrar", len(filas), "numero"), _ev("Entrega del proveedor", _r(d.lead_time(prov), 0), "días"),
                       _ev("Menor cobertura", min(f[5] for f in filas), "días")],
            detalle={"columnas": columnas, "tipos": tipos, "filas": filas}))
    for prov, filas in lineas_por_prov.items():
        info = d.proveedores.get(prov) or {}
        nombre = d.nombre_proveedor(prov)
        hoy_toca = _dias_hasta_pedido(info.get("dias_pedido"), d.hoy)
        if hoy_toca not in (None, 0):
            res.descartes.append((f"ACT-02|{prov}", f"Hoy no es día de pedido de {nombre} (faltan {hoy_toca} días)."))
            continue
        total = sum(f[10] or 0 for f in filas)
        minimo = _f(info.get("pedido_minimo"))
        caso = "C3" if minimo and total < minimo else "C2"
        ev = [_ev("Productos", len(filas), "numero"), _ev("Importe sugerido", _r(total), "moneda")]
        notas = []
        if caso == "C3":
            ev.append(_ev("Pedido mínimo del proveedor", minimo, "moneda"))
            notas.append(f"Faltan $ {minimo - total:,.0f} para el mínimo.".replace(",", "."))
        res.detecciones.append(Deteccion(
            "ACT-02", caso, f"ACT-02|{prov}", f"Pedido sugerido a {nombre}: {_n(len(filas), 'producto')}", total,
            entidad={"proveedor_id": prov, "proveedor": nombre}, evidencia=ev, notas=notas,
            detalle={"columnas": columnas, "tipos": tipos, "filas": sorted(filas, key=lambda f: f[5])}))
    return res


# --- ACT-03 · Rotación y productos que no se mueven ----------------------------------------

def act03(d: Datos, historial) -> Resultado:
    p = catalogo.parametros("ACT-03")
    res = Resultado()
    if not d.stock:
        res.faltan.append("stock por sucursal (stock)")
        return res
    fisico: dict = {}
    for s in d.stock:
        clave = (s["producto_id"], s["sucursal_id"])
        fisico[clave] = fisico.get(clave, 0.0) + _f(s["cantidad"])
    valor_suc: dict = {}
    for (pid, suc), cant in fisico.items():
        valor_suc[suc] = valor_suc.get(suc, 0.0) + max(0.0, cant) * d.costo(pid)
    dias_sin_mov = int(p["dias_sin_movimiento"])
    info: dict = {}
    for (pid, suc), cant in fisico.items():
        vdp4 = d.vdp(pid, suc, 28)
        vdp12 = sum(d.serie(pid, suc, d.dias(84, d.hoy - timedelta(days=28)))) / 84
        prod = d.productos.get(pid) or {}
        obj = _f(catalogo.politica("politica_producto", prod).get("cobertura_objetivo_dias")) or 21
        info[(pid, suc)] = {"cant": cant, "vdp4": vdp4, "vdp12": vdp12, "obj": obj,
                            "cob": cant / vdp4 if vdp4 else None}
    for (pid, suc), x in sorted(info.items(), key=lambda k: (k[0][0], str(k[0][1]))):
        if x["cant"] <= 0:
            continue
        prod = d.productos.get(pid) or {}
        alta = _fecha(prod.get("fecha_alta"))
        if alta and alta > d.hoy - timedelta(days=int(p["antiguedad_min_dias"])):
            continue
        ultima = d.ultima_venta(pid, suc)
        sin_venta = (d.hoy - ultima).days if ultima else None   # None = sin ventas en toda la historia leída
        costo = d.costo(pid)
        valor = x["cant"] * costo
        umbral = 0.01 * valor_suc.get(suc, 0.0)
        nombre, sucursal = d.nombre_producto(pid), d.nombre_sucursal(suc)
        entidad = {"producto_id": pid, "producto": nombre, "sucursal_id": suc, "sucursal": sucursal}
        clave = f"ACT-03|{pid}|{suc}"
        ev = [_ev("Stock", _r(x["cant"], 1), "u"), _ev("Valor a costo", _r(valor), "moneda"),
              _ev("Días sin venta", sin_venta if sin_venta is not None else f"más de {(d.hoy - d.desde).days}", "texto"),
              _ev("Venta diaria (4 semanas)", _r(x["vdp4"], 2), "u/día")]
        destino = None
        if sin_venta is None or sin_venta >= 30:
            for (pid2, suc2), y in info.items():
                if pid2 == pid and suc2 != suc and y["vdp4"] > 0 and (y["cob"] or 0) < y["obj"]:
                    necesidad = y["obj"] * y["vdp4"] - y["cant"]
                    if necesidad > 0 and (destino is None or necesidad > destino[1]):
                        destino = (suc2, necesidad, y)
        if destino:
            cantidad = math.floor(min(x["cant"], destino[1]))
            if cantidad > 0:
                res.detecciones.append(Deteccion(
                    "ACT-03", "C4", clave, f"Transferir {nombre} de {sucursal} a {d.nombre_sucursal(destino[0])}",
                    cantidad * d.precio_medio(pid), entidad={**entidad, "destino_id": destino[0], "destino": d.nombre_sucursal(destino[0])},
                    evidencia=ev + [_ev(f"Cobertura en {d.nombre_sucursal(destino[0])}", _r(destino[2]["cob"], 1), "días"),
                                    _ev("Cantidad a transferir", cantidad, "u")],
                    notas=[f"Transferir {cantidad} u a {d.nombre_sucursal(destino[0])}, donde sí se vende."]))
                continue
        if sin_venta is None or sin_venta >= dias_sin_mov:
            descuento = _descuento_liquidacion(d, pid)
            res.detecciones.append(Deteccion(
                "ACT-03", "C1", clave, f"Sin movimiento: {nombre} en {sucursal}", valor,
                prioridad="alta" if valor >= umbral else "media", entidad=entidad, evidencia=ev,
                notas=[f"Descuento sugerido para liquidar: {descuento:.0%} (respeta el margen mínimo)." if descuento
                       else "No hay margen para descuento sin vender por debajo del costo."]))
            continue
        if x["vdp4"] > 0 and x["cob"] > 2 * x["obj"]:
            exceso = (x["cant"] - x["obj"] * x["vdp4"]) * costo
            if exceso < umbral:
                res.descartes.append((clave, f"Sobrestock chico (${exceso:,.0f} < umbral de ${umbral:,.0f})."))
                continue
            res.detecciones.append(Deteccion(
                "ACT-03", "C2", clave, f"Sobrestock: {nombre} en {sucursal}", exceso, entidad=entidad,
                evidencia=ev + [_ev("Cobertura", _r(x["cob"], 1), "días"), _ev("Cobertura objetivo", x["obj"], "días"),
                                _ev("Capital en exceso", _r(exceso), "moneda")]))
            continue
        if x["vdp12"] > 0 and x["vdp4"] < p["caida_pct"] * x["vdp12"] and x["cant"] > 0:
            res.detecciones.append(Deteccion(
                "ACT-03", "C3", clave, f"Venta en caída: {nombre} en {sucursal}", valor, entidad=entidad,
                evidencia=ev + [_ev("Venta diaria 12 semanas previas", _r(x["vdp12"], 2), "u/día"),
                                _ev("Caída", _r(1 - x["vdp4"] / x["vdp12"], 3), "pct")]))
    return res


def _descuento_liquidacion(d: Datos, pid) -> float:
    precio, costo = d.precio_actual(pid), d.costo(pid)
    if not precio or precio <= costo:
        return 0.0
    minimo = _f(catalogo.politica("politica_precio", d.productos.get(pid) or {}).get("margen_minimo_pct")) / 100
    con_margen = 1 - costo / (1 - minimo) / precio if minimo < 1 else 0
    return max(0.0, round(con_margen if con_margen > 0.05 else 1 - costo / precio, 2))


# --- ACT-04 · Remarcación y margen --------------------------------------------------------

def _redondear(precio: float, paso: float) -> float:
    paso = paso or 1
    return math.ceil(precio / paso) * paso


def act04(d: Datos, historial) -> Resultado:
    p = catalogo.parametros("ACT-04")
    res = Resultado()
    if not d.productos:
        res.faltan.append("productos")
        return res
    if not d.costos:
        res.faltan.append("historial de costos o listas del proveedor (costos_historial)")
    tol = p["tolerancia_pct"]
    var_alerta = p["variacion_costo_alerta_pct"]
    listas_nuevas: dict = {}
    columnas = ["Producto", "Precio actual", "Costo anterior", "Costo nuevo", "Variación costo", "Margen actual",
                "Precio sugerido", "Margen resultante", "Impacto mensual"]
    tipos = ["texto", "moneda", "moneda", "moneda", "pct", "pct", "moneda", "pct", "moneda"]
    for pid, prod in sorted(d.productos.items()):
        if (prod.get("estado") or "activo") not in ("activo", ""):
            continue
        precio = d.precio_actual(pid)
        if not precio:
            continue
        nombre = d.nombre_producto(pid)
        clave = f"ACT-04|{pid}"
        if d.en_promocion(pid):
            res.descartes.append((clave, "Tiene precio promocional vigente: se evalúa al terminar la promoción."))
            continue
        hist = d.costos.get(pid) or []
        costo = d.costo(pid)
        if costo <= 0:
            res.descartes.append((clave, "Sin costo cargado: no se puede calcular el margen."))
            continue
        costo_ant = hist[-2][1] if len(hist) >= 2 and hist[-2][1] > 0 else None
        fecha_lista = hist[-1][0] if hist else None
        pol = catalogo.politica("politica_precio", prod)
        markup = pol.get("metodo") == "markup"
        margen = (precio - costo) / costo if markup else (precio - costo) / precio
        if pol.get("margen_objetivo_pct") is not None:
            objetivo = _f(pol["margen_objetivo_pct"]) / 100
        elif costo_ant:
            objetivo = (precio - costo_ant) / costo_ant if markup else (precio - costo_ant) / precio
        else:
            objetivo = margen
        objetivo = min(max(objetivo, 0.0), 0.9)   # un margen del 100 % o negativo no es un objetivo
        minimo = _f(pol.get("margen_minimo_pct")) / 100
        sugerido = _redondear(costo * (1 + objetivo) if markup else costo / (1 - objetivo), _f(pol.get("redondeo")))
        vdp = d.vdp(pid, None, 28)
        impacto = vdp * 30 * (sugerido - precio)
        var_costo = costo / costo_ant - 1 if costo_ant else None
        margen_nuevo = (sugerido - costo) / sugerido if sugerido else None
        entidad = {"producto_id": pid, "producto": nombre, "proveedor_id": prod.get("proveedor_id"),
                   "proveedor": d.nombre_proveedor(prod.get("proveedor_id"))}
        ev = [_ev("Precio actual", _r(precio), "moneda"), _ev("Costo de reposición", _r(costo), "moneda"),
              _ev("Margen actual", _r(margen, 4), "pct"), _ev("Precio sugerido", _r(sugerido), "moneda")]
        listas = {n: v[-1][1] for n, v in (d.precios.get(pid) or {}).items() if v}
        if len(listas) >= 2 and min(listas.values()) > 0:   # C7 es otro problema: tiene su propia tarea
            dif = max(listas.values()) / min(listas.values()) - 1
            if dif > _f(pol.get("diferencia_listas_pct") or 25) / 100:
                res.detecciones.append(Deteccion(
                    "ACT-04", "C7", f"ACT-04|C7|{pid}", f"Precios inconsistentes entre listas: {nombre}", 0.0, entidad=entidad,
                    evidencia=[_ev(n, v, "moneda") for n, v in listas.items()] + [_ev("Diferencia", _r(dif, 4), "pct")]))
        if precio < costo:
            res.detecciones.append(Deteccion(
                "ACT-04", "C3", clave, f"Se vende por debajo del costo: {nombre}", vdp * 30 * (costo - precio),
                entidad=entidad, evidencia=ev + [_ev("Pérdida por unidad", _r(costo - precio), "moneda")]))
            continue
        reciente = fecha_lista and fecha_lista >= d.hoy - timedelta(days=30)
        if var_costo is not None and reciente and abs(var_costo) > var_alerta:
            prov = prod.get("proveedor_id")
            grupo = listas_nuevas.setdefault((prov, fecha_lista, var_costo > 0), [])
            if var_costo < 0 or abs(sugerido - precio) / precio > tol:
                grupo.append(([nombre, _r(precio), _r(costo_ant), _r(costo), _r(var_costo, 4), _r(margen, 4), _r(sugerido),
                               _r(margen_nuevo, 4), _r(impacto)], var_costo, vdp * 30 * abs(sugerido - precio)
                              if var_costo > 0 else vdp * 30 * (costo_ant - costo)))
            continue
        if margen < minimo:
            sugerido = _redondear(costo * (1 + minimo) if markup else costo / (1 - minimo), _f(pol.get("redondeo")))
            ev[-1] = _ev("Precio sugerido (margen mínimo)", _r(sugerido), "moneda")
            res.detecciones.append(Deteccion(
                "ACT-04", "C2", clave, f"Margen por debajo del mínimo: {nombre}", max(0.0, vdp * 30 * (sugerido - precio)),
                entidad=entidad, evidencia=ev + [_ev("Margen mínimo", minimo, "pct")],
                notas=[f"Remarcar a $ {sugerido:,.0f} o dejar registrado por qué se sostiene el precio (competencia, producto gancho).".replace(",", ".")]))
            continue
        subio = _suba_precio(d, pid, 42)
        if subio is not None and subio > 0.15:
            fecha_suba = max(x[-1][0] for x in (d.precios.get(pid) or {}).values() if x)
            antes = d.vdp(pid, None, 28, fecha_suba)
            despues = sum(d.serie(pid, None, [fecha_suba + timedelta(days=i) for i in range(14)
                                             if fecha_suba + timedelta(days=i) < d.hoy])) / 14
            if (d.hoy - fecha_suba).days >= 14 and antes and despues < 0.6 * antes:
                res.detecciones.append(Deteccion(
                    "ACT-04", "C5", clave, f"La suba de precio frenó la venta: {nombre}", (antes - despues) * 30 * precio,
                    entidad=entidad, evidencia=ev + [_ev("Suba de precio", _r(subio, 4), "pct"),
                                                     _ev("Venta diaria antes", _r(antes, 2), "u/día"),
                                                     _ev("Venta diaria después", _r(despues, 2), "u/día")]))
                continue
    for (prov, fecha, sube), items in listas_nuevas.items():
        if not items:
            continue
        nombre = d.nombre_proveedor(prov)
        promedio = statistics.mean(i[1] for i in items)
        caso = "C1" if sube else "C4"
        res.detecciones.append(Deteccion(
            "ACT-04", caso, f"ACT-04|{caso}|{prov}|{fecha.isoformat()}",
            (f"Remarcar: lista de {nombre} con {promedio:+.1%} en {_n(len(items), 'producto')}" if sube
             else f"Baja de costo de {nombre}: {promedio:+.1%} en {_n(len(items), 'producto')}").replace(".", ","),
            sum(i[2] for i in items), prioridad=("critica" if sube and promedio > 0.10 else None),
            entidad={"proveedor_id": prov, "proveedor": nombre, "fecha_lista": fecha.isoformat()},
            evidencia=[_ev("Fecha de la lista", fecha.isoformat(), "texto"), _ev("Variación promedio", _r(promedio, 4), "pct"),
                       _ev("Productos", len(items), "numero")],
            detalle={"columnas": columnas, "tipos": tipos, "filas": sorted((i[0] for i in items), key=lambda f: -(f[8] or 0))}))
    # C6: listas desactualizadas por proveedor
    ultima_lista: dict = {}
    for pid, hist in d.costos.items():
        prov = (d.productos.get(pid) or {}).get("proveedor_id")
        if prov and hist:
            ultima_lista[prov] = max(ultima_lista.get(prov, hist[-1][0]), hist[-1][0])
    for prov, fecha in ultima_lista.items():
        if (d.hoy - fecha).days <= p["dias_lista_desactualizada"]:
            continue
        caros = []
        for pid, prod in d.productos.items():
            if prod.get("proveedor_id") == prov and pid in d.ultima_compra and d.costo(pid):
                f, precio_compra = d.ultima_compra[pid]
                if f > fecha and precio_compra > d.costo(pid) * (1 + var_alerta):
                    caros.append(pid)
        if caros:
            nombre = d.nombre_proveedor(prov)
            res.detecciones.append(Deteccion(
                "ACT-04", "C6", f"ACT-04|C6|{prov}", f"Pedir lista de precios actualizada a {nombre}", 0.0,
                entidad={"proveedor_id": prov, "proveedor": nombre},
                evidencia=[_ev("Última lista", fecha.isoformat(), "texto"), _ev("Días sin lista", (d.hoy - fecha).days, "numero"),
                           _ev("Productos comprados más caros que la lista", len(caros), "numero")]))
    return res


# --- ACT-05 · Promociones que no rindieron ------------------------------------------------

_MECANICAS = {"descuento": "descuento_pct", "descuento_pct": "descuento_pct", "precio_especial": "precio_especial",
              "precio": "precio_especial", "nxm": "nxm", "2x1": "nxm", "3x2": "nxm", "segunda_unidad": "segunda_unidad",
              "combo": "combo", "cupon": "cupon"}


def act05(d: Datos, historial) -> Resultado:
    p = catalogo.parametros("ACT-05")
    res = Resultado()
    if not d.promociones:
        res.faltan.append("promociones con producto, desde y hasta (promociones)")
        return res
    lifts = p["lift_minimo_esperado_por_mecanica"]
    for pr in d.promociones:
        pid = pr["producto_id"]
        if pid is None or pr["desde"] >= d.hoy:
            continue
        activa = pr["hasta"] >= d.hoy
        if not activa and pr["hasta"] < d.hoy - timedelta(days=45):
            continue
        transcurridos = [pr["desde"] + timedelta(days=i) for i in range((min(pr["hasta"], d.hoy - timedelta(days=1)) - pr["desde"]).days + 1)]
        if activa and len(transcurridos) < p["dia_control_temprano"]:
            continue
        base_dias = d.dias(int(p["semanas_base"]) * 7, pr["desde"])
        base = sum(d.serie(pid, None, base_dias)) / len(base_dias)
        promo = sum(d.serie(pid, None, transcurridos)) / len(transcurridos) if transcurridos else 0
        mecanica = _MECANICAS.get(catalogo._sin_tildes(str(pr.get("tipo") or "descuento")).replace(" ", "_"), "descuento_pct")
        esperado = lifts.get(mecanica, 0.3)
        lift = promo / base - 1 if base else None
        precio_normal = d.precio_actual(pid)
        precio_promo = _f(pr.get("precio_promocional")) or precio_normal * (1 - _f(pr.get("descuento_pct")) / (100 if _f(pr.get("descuento_pct")) > 1 else 1))
        costo = d.costo_medio_vendido(pid)
        n = len(transcurridos)
        margen_promo = (precio_promo - costo) * promo * n
        margen_base = (precio_normal - costo) * base * n
        # Canibalización: lo que dejaron de vender los otros productos de la categoría
        cat = (d.productos.get(pid) or {}).get("categoria")
        canib_u = canib_m = 0.0   # caída neta de la categoría (las subas de otros productos compensan)
        for otro, prod in d.productos.items():
            if otro == pid or not cat or prod.get("categoria") != cat:
                continue
            b = sum(d.serie(otro, None, base_dias)) / len(base_dias)
            a = sum(d.serie(otro, None, transcurridos)) / n if n else 0
            canib_u += (b - a) * n
            canib_m += (b - a) * n * (d.precio_actual(otro) - d.costo(otro))
        canib_u, canib_m = max(0.0, canib_u), max(0.0, canib_m)
        posterior_u = posterior_m = 0.0
        if not activa and (d.hoy - pr["hasta"]).days >= 14:
            despues = [pr["hasta"] + timedelta(days=i) for i in range(1, 15)]
            a = sum(d.serie(pid, None, despues)) / 14
            if a < base:
                posterior_u = (base - a) * 14
                posterior_m = posterior_u * (precio_normal - costo)
        incremental_u = (promo - base) * n
        margen_inc = margen_promo - margen_base - canib_m - posterior_m
        costo_promo = max(0.0, (precio_normal - precio_promo) * promo * n)
        roi = margen_inc / costo_promo if costo_promo else None
        disp, _ = d.stock_de(pid)
        nombre = pr.get("nombre") or f"Promoción {pr['id']}"
        clave = f"ACT-05|{pr['id']}"
        entidad = {"promocion_id": pr["id"], "promocion": nombre, "producto_id": pid, "producto": d.nombre_producto(pid),
                   "desde": pr["desde"].isoformat(), "hasta": pr["hasta"].isoformat(), "mecanica": mecanica}
        ev = [_ev("Venta diaria sin promo", _r(base, 2), "u/día"), _ev("Venta diaria en promo", _r(promo, 2), "u/día"),
              _ev("Suba de unidades (lift)", _r(lift, 4), "pct"), _ev("Lift mínimo esperado", esperado, "pct"),
              _ev("Margen incremental neto", _r(margen_inc), "moneda")]
        if activa:
            if disp <= 0:
                res.detecciones.append(Deteccion("ACT-05", "C2", clave, f"Promoción sin stock: {nombre}", base * (1 + esperado) * precio_promo * 7,
                                                 entidad=entidad, evidencia=ev + [_ev("Stock disponible", _r(disp, 1), "u")]))
            elif lift is not None and lift < 0.5 * esperado:
                dias_restantes = (pr["hasta"] - d.hoy).days + 1
                perdida = max(0.0, -margen_inc / n * (n + dias_restantes)) if n else 0.0
                res.detecciones.append(Deteccion("ACT-05", "C1", clave, f"La promoción no despega: {nombre} (día {n})", perdida,
                                                 entidad=entidad, evidencia=ev + [_ev("Días que faltan", dias_restantes, "numero")]))
            continue
        base_ev = ev + [_ev("Canibalización (u)", _r(canib_u, 1), "numero"), _ev("Efecto posterior (u)", _r(posterior_u, 1), "numero"),
                        _ev("ROI", _r(roi, 3), "pct")]
        if lift is None:
            res.descartes.append((clave, "Sin venta del producto antes de la promoción: no hay línea base."))
        elif lift < 0.10:
            res.detecciones.append(Deteccion("ACT-05", "C4", clave, f"La promoción no movió la venta: {nombre}", max(0.0, -margen_inc),
                                             entidad=entidad, evidencia=base_ev))
        elif incremental_u > 0 and margen_inc < 0:
            maximo = 1 - (costo + (precio_normal - costo) * base / promo) / precio_normal if promo and precio_normal else 0
            aporte = -margen_inc
            res.detecciones.append(Deteccion("ACT-05", "C3", clave, f"Vendió más pero perdió margen: {nombre}", -margen_inc,
                                             entidad=entidad, evidencia=base_ev,
                                             notas=[f"Descuento máximo que deja margen incremental ≥ 0 con este lift: {max(0.0, maximo):.0%}.",
                                                    f"Aporte del proveedor necesario para repetirla igual: $ {aporte:,.0f}.".replace(",", ".")]))
        elif incremental_u - canib_u - posterior_u <= 0:
            res.detecciones.append(Deteccion("ACT-05", "C5", clave, f"Solo canibalizó o adelantó compras: {nombre}", max(0.0, -margen_inc),
                                             entidad=entidad, evidencia=base_ev))
        elif margen_inc > 0 and (roi is None or roi >= p["roi_minimo"]):
            res.detecciones.append(Deteccion("ACT-05", "C6", clave, f"Promoción que rindió: {nombre}", margen_inc,
                                             entidad=entidad, evidencia=base_ev))
        else:
            res.descartes.append((clave, "Resultado intermedio: no encaja en ningún caso."))
    return res


# --- ACT-06 · Vencimientos ----------------------------------------------------------------

def act06(d: Datos, historial) -> Resultado:
    p = catalogo.parametros("ACT-06")
    res = Resultado()
    lotes = [s for s in d.stock if _f(s["cantidad"]) > 0 and s["fecha_vencimiento"]]
    sin_fecha = [s for s in d.stock if _f(s["cantidad"]) > 0 and not s["fecha_vencimiento"]
                 and (d.productos.get(s["producto_id"]) or {}).get("perecedero")]
    if not lotes and not sin_fecha:
        res.faltan.append("lotes con fecha de vencimiento (stock.lote, stock.fecha_vencimiento)")
        return res
    ventana, e, maximo = p["ventana_alerta_dias"], p["elasticidad_default"], p["descuento_maximo_pct"]
    consumo: dict = {}
    afectados: dict = {}
    for s in sorted(lotes, key=lambda s: (s["producto_id"], str(s["sucursal_id"]), str(s["fecha_vencimiento"]))):
        pid, suc = s["producto_id"], s["sucursal_id"]
        prod = d.productos.get(pid) or {}
        venc = _fecha(s["fecha_vencimiento"])
        if not venc:
            continue
        retiro = int(_f(catalogo.politica("politica_producto", prod).get("dias_retiro_antes_vencimiento") or p["dias_retiro_default"]))
        limite = venc - timedelta(days=retiro)
        dias = (limite - d.hoy).days
        cant = _f(s["cantidad"])
        vdp = d.vdp(pid, suc, 28)
        previos = consumo.get((pid, suc), 0.0)
        esperada = max(0.0, vdp * max(0, dias) - previos)
        consumo[(pid, suc)] = previos + min(cant, esperada)
        riesgo = max(0.0, cant - esperada)
        costo = d.costo(pid)
        nombre, sucursal = d.nombre_producto(pid), d.nombre_sucursal(suc)
        lote = s["lote"] or f"vence {venc.isoformat()}"
        clave = f"ACT-06|{pid}|{suc}|{lote}"
        entidad = {"producto_id": pid, "producto": nombre, "sucursal_id": suc, "sucursal": sucursal, "lote": lote,
                   "fecha_vencimiento": venc.isoformat()}
        ev = [_ev("Unidades del lote", cant, "u"), _ev("Días a vencer", (venc - d.hoy).days, "numero"),
              _ev("Venta diaria", _r(vdp, 2), "u/día"), _ev("Se venden a tiempo", _r(min(cant, esperada), 1), "u"),
              _ev("En riesgo", _r(riesgo, 1), "u"), _ev("Valor en riesgo a costo", _r(riesgo * costo), "moneda")]
        if dias <= 0:
            prov = d.proveedores.get(prod.get("proveedor_id")) or {}
            notas = ["El proveedor acepta devolución de vencidos: gestionarla." if prov.get("acepta_devolucion_vencidos")
                     else "Registrar la merma con motivo 'vencimiento'."]
            res.detecciones.append(Deteccion("ACT-06", "C1", clave, f"Retirar HOY: {nombre} lote {lote} en {sucursal}", cant * costo,
                                             entidad=entidad, evidencia=ev[:3] + [_ev("Valor a costo", _r(cant * costo), "moneda")], notas=notas))
            afectados.setdefault(pid, set()).add(lote)
            continue
        if riesgo <= 0 or dias > ventana:
            continue
        mult = (cant / dias) / vdp if vdp else math.inf
        previo_c2 = next((h for h in historial(clave) if h["caso"] == "C2" and h["estado"] in catalogo.ABIERTAS
                          and _fecha(h["detectada_at"]) <= d.hoy - timedelta(days=3)), None)
        if mult > 4 or previo_c2:
            destino = _mejor_destino(d, pid, suc, dias)
            notas = [f"Transferir {destino[1]:.0f} u a {d.nombre_sucursal(destino[0])}, donde se venden antes del vencimiento."
                     if destino else "Ninguna otra sucursal lo vende a tiempo: pedir cambio al proveedor o donar antes del vencimiento."]
            if previo_c2:
                notas.insert(0, "El descuento no alcanzó en 3 días.")
            res.detecciones.append(Deteccion("ACT-06", "C3", clave, f"No se vende a tiempo ni con descuento: {nombre} lote {lote}",
                                             riesgo * costo, entidad=entidad, evidencia=ev + [_ev("Velocidad necesaria", _r(mult, 2), "x")],
                                             notas=notas))
            afectados.setdefault(pid, set()).add(lote)
            continue
        if mult < 1.2:
            res.descartes.append((clave, f"Riesgo chico: necesita vender {mult:.1f} veces lo normal."))
            continue
        precio = d.precio_actual(pid)
        descuento = min(maximo, 1 - mult ** (1 / e))
        if precio and precio * (1 - descuento) < costo:
            descuento = max(0.0, 1 - costo / precio)
        res.detecciones.append(Deteccion("ACT-06", "C2", clave, f"Vence pronto: {nombre} lote {lote} en {sucursal}", riesgo * costo,
                                         prioridad="critica" if dias <= 7 else None, entidad=entidad,
                                         evidencia=ev + [_ev("Velocidad necesaria", _r(mult, 2), "x"), _ev("Descuento sugerido", _r(descuento, 3), "pct")],
                                         notas=[f"Aplicar {descuento:.0%} de descuento con cartel de consumo preferente y re-evaluar en 3 días."]))
        afectados.setdefault(pid, set()).add(lote)
    # C4: el mismo producto con 2 o más lotes con problemas en 90 días (sobrecompra)
    for pid, lotes_hoy in afectados.items():
        previos = set()
        for h in historial(f"ACT-06|{pid}|", prefijo=True):
            if h["caso"] in ("C1", "C2", "C3") and _fecha(h["detectada_at"]) >= d.hoy - timedelta(days=90):
                previos.add(h["entidad"].get("lote"))
        todos = previos | lotes_hoy
        if len(todos) >= 2:
            nombre = d.nombre_producto(pid)
            res.detecciones.append(Deteccion("ACT-06", "C4", f"ACT-06|C4|{pid}", f"Sobrecompra de perecederos: {nombre}", 0.0,
                                             entidad={"producto_id": pid, "producto": nombre},
                                             evidencia=[_ev("Lotes con problemas en 90 días", len(todos), "numero")],
                                             notas=["El pedido sugerido va a respetar el tope por vida útil para este producto."]))
    for s in sin_fecha:
        pid, suc = s["producto_id"], s["sucursal_id"]
        nombre, sucursal = d.nombre_producto(pid), d.nombre_sucursal(suc)
        res.detecciones.append(Deteccion("ACT-06", "C5", f"ACT-06|C5|{pid}|{suc}|{s['lote'] or ''}",
                                         f"Cargar fecha de vencimiento: {nombre} en {sucursal}", _f(s["cantidad"]) * d.costo(pid),
                                         entidad={"producto_id": pid, "producto": nombre, "sucursal_id": suc, "sucursal": sucursal},
                                         evidencia=[_ev("Unidades sin fecha", _f(s["cantidad"]), "u")]))
    return res


def _mejor_destino(d: Datos, pid, origen, dias: int):
    mejor = None
    for suc in d.puntos():
        if suc == origen:
            continue
        vdp = d.vdp(pid, suc, 28)
        disp, _ = d.stock_de(pid, suc)
        capacidad = vdp * dias - disp
        if capacidad > 0 and (mejor is None or capacidad > mejor[1]):
            mejor = (suc, capacidad)
    return mejor


REGLAS = {"ACT-01": act01, "ACT-02": act02, "ACT-03": act03, "ACT-04": act04, "ACT-05": act05, "ACT-06": act06}
