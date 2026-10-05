"""Importación del modo distribuidor por archivo (Excel o CSV): clientes, pedidos (con lo entregado) y cuenta corriente.
Mismo asistente que el resto de Datos → Importar (columnas, revisión, confirmación) y mismas reglas: reimportar no duplica.

- Clientes: se identifican por su código; si ya existe se actualiza. El vendedor y la lista de precios se crean si no existen.
- Pedidos: una fila por línea; las líneas con el mismo número de pedido forman un pedido. Si el pedido ya se importó, se saltea.
- Cuenta corriente: una fila por comprobante (factura, nota de crédito o débito, recibo). Reimportar actualiza el saldo.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from . import db
from .importar import _norm, _producto, fecha, numero

CAMPOS = {
    "clientes": [("codigo", "Código de cliente", True), ("razon_social", "Razón social", True), ("nombre_fantasia", "Nombre de fantasía", False),
                 ("cuit", "CUIT", False), ("direccion", "Dirección", False), ("localidad", "Localidad", False), ("zona", "Zona", False),
                 ("canal", "Canal (autoservicio, almacén, kiosco…)", False), ("vendedor", "Vendedor", False), ("lista", "Lista de precios", False),
                 ("limite_credito", "Límite de crédito", False), ("condicion_pago", "Días de pago", False)],
    "pedidos": [("pedido", "Número de pedido", True), ("fecha", "Fecha del pedido", True), ("cliente", "Cliente (código, CUIT o nombre)", True),
                ("producto", "Producto (código, EAN o nombre)", True), ("cantidad", "Cantidad pedida", True), ("precio", "Precio unitario sin IVA", True),
                ("entregada", "Cantidad entregada", False), ("faltante", "Faltante por falta de stock", False), ("precio_lista", "Precio de lista", False),
                ("costo", "Costo unitario sin IVA", False), ("vendedor", "Vendedor", False), ("estado", "Estado", False),
                ("fecha_entrega", "Fecha de entrega", False), ("motivo", "Motivo de rechazo", False), ("deposito", "Depósito", False),
                ("repartidor", "Repartidor", False), ("devuelta", "Cantidad devuelta en la entrega", False),
                ("motivo_devolucion", "Motivo de la devolución", False), ("fecha_prometida", "Fecha de entrega prometida", False)],
    "cuenta_corriente": [("cliente", "Cliente (código, CUIT o nombre)", True), ("tipo", "Tipo de comprobante", True), ("numero", "Número", True),
                         ("fecha", "Fecha", True), ("importe", "Importe", True), ("vencimiento", "Vencimiento", False), ("saldo", "Saldo pendiente", False)],
}
CAMPOS["prospectos"] = [("nombre", "Nombre del comercio", True), ("direccion", "Dirección", False), ("localidad", "Localidad", False),
                        ("zona", "Zona", False), ("canal", "Canal", False), ("fuente", "Fuente (relevamiento, cámara…)", False)]
TITULOS = {"prospectos": "Comercios de la zona que todavía no son clientes", "clientes": "Clientes (comercios)", "pedidos": "Pedidos de clientes y entregas", "cuenta_corriente": "Cuenta corriente de clientes"}
SINONIMOS = {
    "razon_social": ["razon social", "cliente", "nombre"], "nombre_fantasia": ["nombre fantasia", "fantasia", "comercio"], "cuit": ["cuit", "cuil", "documento"],
    "direccion": ["direccion", "domicilio", "calle"], "localidad": ["localidad", "ciudad"], "zona": ["zona", "region", "recorrido"],
    "vendedor": ["vendedor", "preventista", "representante"], "fuente": ["fuente", "origen"], "repartidor": ["repartidor", "chofer", "fletero"],
    "devuelta": ["devuelta", "devolucion", "cantidad devuelta"], "motivo_devolucion": ["motivo devolucion"], "fecha_prometida": ["fecha prometida", "prometida"], "lista": ["lista", "lista precios"], "limite_credito": ["limite", "limite credito", "credito"],
    "condicion_pago": ["condicion pago", "dias pago", "plazo"], "cliente": ["cliente", "codigo cliente", "razon social"],
    "entregada": ["entregada", "cantidad entregada", "entregado"], "faltante": ["faltante", "sin stock"], "fecha_entrega": ["fecha entrega", "entrega"],
    "motivo": ["motivo", "motivo rechazo", "observacion"], "deposito": ["deposito", "almacen"], "importe": ["importe", "total", "monto"],
    "saldo": ["saldo", "pendiente", "adeudado"], "tipo": ["tipo", "tipo comprobante", "comprobante"],
}
ESTADOS = {"tomado": "tomado", "pendiente": "tomado", "confirmado": "tomado", "preparado": "preparado", "despachado": "despachado",
           "en reparto": "despachado", "entregado": "entregado", "entregado parcial": "entregado_parcial", "parcial": "entregado_parcial",
           "rechazado": "rechazado", "anulado": "anulado", "cancelado": "anulado"}
TIPOS_CC = {"factura": "factura", "fc": "factura", "fa": "factura", "fb": "factura", "nota de credito": "nota_credito", "nc": "nota_credito",
            "nota de debito": "nota_debito", "nd": "nota_debito", "recibo": "recibo", "rc": "recibo", "pago": "recibo", "cobro": "recibo"}


def contexto(conn, cat: dict) -> None:
    """Agrega a la caché del importador cómo encontrar clientes y vendedores por código, CUIT o nombre."""
    if "clientes" in cat:
        return
    clientes = {}
    for c in db.filas(conn, "SELECT id, codigo_externo, razon_social, nombre_fantasia, cuit FROM clientes_b2b"):
        for clave in (c["razon_social"], c["nombre_fantasia"], c["cuit"], (c["codigo_externo"] or "").split(":")[-1]):
            if clave:
                clientes.setdefault(_norm(clave), c["id"])
    cat["clientes"] = clientes
    cat["vendedores"] = {_norm(v["nombre"]): v["id"] for v in db.filas(conn, "SELECT id, nombre FROM vendedores")}


def validar_fila(conn, tipo: str, v: dict, cat: dict, sin_producto: dict) -> str | None:
    contexto(conn, cat)
    if tipo == "prospectos":
        return None
    if tipo == "clientes":
        for campo in ("limite_credito", "condicion_pago"):
            numero(v.get(campo))
        return None
    if _norm(v["cliente"]) not in cat["clientes"]:
        return f"No existe el cliente «{v['cliente']}» (importá primero los clientes)"
    fecha(v["fecha"])
    if tipo == "pedidos":
        if numero(v["cantidad"]) is None or numero(v["precio"]) is None:
            return "Falta la cantidad o el precio"
        numero(v.get("entregada"))
        numero(v.get("faltante"))
        numero(v.get("devuelta"))
        fecha(v.get("fecha_entrega"))
        fecha(v.get("fecha_prometida"))
        if v.get("estado") and _norm(v["estado"]) not in ESTADOS:
            return f"Estado «{v['estado']}» desconocido (tomado, preparado, despachado, entregado, parcial, rechazado o anulado)"
        pid, _ = _producto(conn, cat, v["producto"])
        if not pid:
            sin_producto[str(v["producto"])] += 1
            return f"No se encontró el producto «{v['producto']}» (importá primero los productos o emparejalo en Catálogo)"
    if tipo == "cuenta_corriente":
        if _norm(v["tipo"]) not in TIPOS_CC:
            return f"Tipo de comprobante «{v['tipo']}» desconocido (factura, nota de crédito, nota de débito o recibo)"
        if numero(v["importe"]) is None:
            return "Falta el importe"
        numero(v.get("saldo"))
        fecha(v.get("vencimiento"))
    return None


def _vendedor(conn, ctx, cat: dict, nombre) -> int | None:
    if not nombre or not str(nombre).strip():
        return None
    clave = _norm(nombre)
    if clave not in cat["vendedores"]:
        cat["vendedores"][clave] = db.fila(conn, "INSERT INTO vendedores (org_id, nombre, created_by) VALUES (%s,%s,%s) RETURNING id",
                                           (ctx.org_id, str(nombre).strip(), ctx.usuario_id))["id"]
    return cat["vendedores"][clave]


def _repartidor(conn, ctx, cat: dict, nombre) -> int | None:
    if not nombre or not str(nombre).strip():
        return None
    memo = cat.setdefault("repartidores", {_norm(r["nombre"]): r["id"] for r in db.filas(conn, "SELECT id, nombre FROM repartidores")})
    clave = _norm(nombre)
    if clave not in memo:
        memo[clave] = db.fila(conn, "INSERT INTO repartidores (org_id, nombre, created_by) VALUES (%s,%s,%s) RETURNING id",
                              (ctx.org_id, str(nombre).strip(), ctx.usuario_id))["id"]
    return memo[clave]


def clientes(conn, ctx, lote, filas, cat, zona) -> dict:
    contexto(conn, cat)
    listas = {_norm(l["nombre"]): l["id"] for l in db.filas(conn, "SELECT id, nombre FROM listas_precios_clientes")}
    nuevos = actualizados = 0
    hoy = date.today()
    for _, v in filas:
        lista_id = None
        if v.get("lista"):
            if _norm(v["lista"]) not in listas:
                listas[_norm(v["lista"])] = db.fila(conn, "INSERT INTO listas_precios_clientes (org_id, nombre, created_by) VALUES (%s,%s,%s) RETURNING id",
                                                    (ctx.org_id, str(v["lista"]).strip(), ctx.usuario_id))["id"]
            lista_id = listas[_norm(v["lista"])]
        limite, dias = numero(v.get("limite_credito")), numero(v.get("condicion_pago"))
        datos = (str(v["razon_social"]).strip(), v.get("nombre_fantasia"), v.get("cuit"), v.get("direccion"), v.get("localidad"), v.get("zona"),
                 _norm(v["canal"]) if v.get("canal") else None, lista_id, limite, int(dias or 0), _vendedor(conn, ctx, cat, v.get("vendedor")))
        r = db.fila(conn, """
            INSERT INTO clientes_b2b (org_id, codigo_externo, razon_social, nombre_fantasia, cuit, direccion, localidad, zona, canal, lista_precios_id,
                                      limite_credito, condicion_pago_dias, vendedor_id, alta, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (org_id, codigo_externo) DO UPDATE SET razon_social = EXCLUDED.razon_social,
                nombre_fantasia = coalesce(EXCLUDED.nombre_fantasia, clientes_b2b.nombre_fantasia), cuit = coalesce(EXCLUDED.cuit, clientes_b2b.cuit),
                direccion = coalesce(EXCLUDED.direccion, clientes_b2b.direccion), localidad = coalesce(EXCLUDED.localidad, clientes_b2b.localidad),
                zona = coalesce(EXCLUDED.zona, clientes_b2b.zona), canal = coalesce(EXCLUDED.canal, clientes_b2b.canal),
                lista_precios_id = coalesce(EXCLUDED.lista_precios_id, clientes_b2b.lista_precios_id),
                limite_credito = coalesce(EXCLUDED.limite_credito, clientes_b2b.limite_credito), condicion_pago_dias = EXCLUDED.condicion_pago_dias,
                vendedor_id = coalesce(EXCLUDED.vendedor_id, clientes_b2b.vendedor_id), updated_at = now()
            RETURNING (xmax = 0) AS nuevo""", (ctx.org_id, f"archivo:{str(v['codigo']).strip()}", *datos, hoy, ctx.usuario_id))
        nuevos += r["nuevo"]
        actualizados += not r["nuevo"]
    return {"importadas": nuevos + actualizados, "nuevos": nuevos, "actualizados": actualizados,
            "mensaje": f"{nuevos} clientes nuevos y {actualizados} actualizados."}


def pedidos(conn, ctx, lote, filas, cat, zona) -> dict:
    contexto(conn, cat)
    depositos = {_norm(u["nombre"]): u["id"] for u in db.filas(conn, "SELECT id, nombre FROM ubicaciones")}
    grupos: dict[str, list[dict]] = defaultdict(list)
    for _, v in filas:
        grupos[str(v["pedido"]).strip()].append(v)
    importados = duplicados = lineas = 0
    fechas = []
    with conn.cursor() as cur:
        for numero_pedido, vs in grupos.items():
            v0 = vs[0]
            cliente_id = cat["clientes"][_norm(v0["cliente"])]
            vendedor_id = _vendedor(conn, ctx, cat, v0.get("vendedor")) or db.fila(conn, "SELECT vendedor_id FROM clientes_b2b WHERE id=%s",
                                                                                   (cliente_id,))["vendedor_id"]
            estado = ESTADOS.get(_norm(v0.get("estado") or ""), None)
            detalle = []
            for v in vs:
                pid, _ = _producto(conn, cat, v["producto"])
                pedida, precio = numero(v["cantidad"]), numero(v["precio"])
                entregada = numero(v.get("entregada"))
                detalle.append((pid, pedida, entregada, numero(v.get("faltante")) or 0, numero(v.get("precio_lista")) or precio, precio, numero(v.get("costo")),
                                numero(v.get("devuelta")) or 0, v.get("motivo_devolucion") or None))
            if estado is None:          # sin estado: se deduce de lo entregado
                if all(d[2] is None for d in detalle):
                    estado = "tomado"
                else:
                    entregado = sum(d[2] or 0 for d in detalle)
                    estado = "rechazado" if entregado == 0 else "entregado" if all((d[2] or 0) >= d[1] for d in detalle) else "entregado_parcial"
            f = fecha(v0["fecha"])
            total = sum(d[1] * d[5] for d in detalle)
            total_entregado = sum((d[2] if d[2] is not None else (d[1] if estado == "entregado" else 0)) * d[5] for d in detalle)
            p = db.fila(conn, """INSERT INTO pedidos_venta (org_id, numero, cliente_id, vendedor_id, ubicacion_id, fecha, fecha_entrega_prometida, estado, total,
                                                            total_entregado, descuento, origen, numero_externo, created_by)
                                 VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'archivo',%s,%s) ON CONFLICT (org_id, origen, numero_externo) DO NOTHING RETURNING id""",
                        (ctx.org_id, numero_pedido, cliente_id, vendedor_id, depositos.get(_norm(v0.get("deposito") or "")), f, fecha(v0.get("fecha_prometida")),
                         estado, total, total_entregado,
                         sum(max(0, d[4] - d[5]) * d[1] for d in detalle), numero_pedido, ctx.usuario_id))
            if not p:
                duplicados += 1
                continue
            fechas.append(f)
            for pid, pedida, entregada, faltante, lista, precio, costo, devuelta, motivo_dev in detalle:
                if entregada is None:
                    entregada = pedida if estado == "entregado" else 0
                cur.execute("""INSERT INTO pedidos_venta_lineas (org_id, pedido_id, producto_id, cantidad_pedida, cantidad_entregada, faltante_stock,
                                                                 precio_lista, precio, descuento, costo_unitario, cantidad_devuelta, motivo_devolucion)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            (ctx.org_id, p["id"], pid, pedida, entregada, faltante, lista, precio, max(0, lista - precio) * pedida, costo, devuelta,
                             motivo_dev if devuelta else None))
                lineas += 1
            if estado in ("entregado", "entregado_parcial", "rechazado"):
                cur.execute("INSERT INTO entregas (org_id, pedido_id, fecha, resultado, motivo, repartidor_id, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            (ctx.org_id, p["id"], fecha(v0.get("fecha_entrega")) or f,
                             {"entregado": "entregado", "entregado_parcial": "parcial", "rechazado": "rechazado"}[estado], v0.get("motivo"),
                             _repartidor(conn, ctx, cat, v0.get("repartidor")), ctx.usuario_id))
            importados += 1
    return {"importadas": importados, "duplicadas": duplicados, "lineas": lineas, "desde": min(fechas) if fechas else None,
            "mensaje": f"{importados} pedidos ({lineas} líneas)" + (f"; {duplicados} ya estaban cargados" if duplicados else "") + "."}


def cuenta_corriente(conn, ctx, lote, filas, cat, zona) -> dict:
    contexto(conn, cat)
    nuevos = actualizados = 0
    for _, v in filas:
        tipo = TIPOS_CC[_norm(v["tipo"])]
        importe = abs(numero(v["importe"]))
        if tipo in ("nota_credito", "recibo"):
            importe = -importe
        saldo = numero(v.get("saldo"))
        saldo = importe if saldo is None else (abs(saldo) if importe > 0 else -abs(saldo))
        r = db.fila(conn, """
            INSERT INTO documentos_cc (org_id, cliente_id, tipo, numero, fecha, vencimiento, importe, saldo, origen, numero_externo, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'archivo',%s,%s)
            ON CONFLICT (org_id, origen, numero_externo) DO UPDATE SET saldo = EXCLUDED.saldo, vencimiento = EXCLUDED.vencimiento, updated_at = now()
            RETURNING (xmax = 0) AS nuevo""",
                    (ctx.org_id, cat["clientes"][_norm(v["cliente"])], tipo, str(v["numero"]).strip(), fecha(v["fecha"]), fecha(v.get("vencimiento")),
                     importe, saldo, f"{tipo}:{str(v['numero']).strip()}", ctx.usuario_id))
        nuevos += r["nuevo"]
        actualizados += not r["nuevo"]
    return {"importadas": nuevos + actualizados, "nuevos": nuevos, "actualizados": actualizados,
            "mensaje": f"{nuevos} comprobantes nuevos y {actualizados} con el saldo actualizado."}


def prospectos(conn, ctx, lote, filas, cat, zona) -> dict:
    """Comercios relevados de cada zona. Reimportar no duplica (mismo nombre y dirección); los que ya son clientes se saltean."""
    contexto(conn, cat)
    nuevos = ya_clientes = 0
    for _, v in filas:
        nombre = str(v["nombre"]).strip()
        if _norm(nombre) in cat["clientes"]:
            ya_clientes += 1
            continue
        clave = f"archivo:{_norm(nombre)}|{_norm(v.get('direccion') or '')}"
        r = db.fila(conn, """INSERT INTO prospectos (org_id, razon_social, direccion, localidad, zona, canal, fuente, codigo_externo, created_by)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (org_id, codigo_externo) DO NOTHING RETURNING id""",
                    (ctx.org_id, nombre, v.get("direccion"), v.get("localidad"), v.get("zona"), _norm(v["canal"]) if v.get("canal") else None,
                     v.get("fuente"), clave, ctx.usuario_id))
        nuevos += bool(r)
    return {"importadas": nuevos, "duplicadas": len(filas) - nuevos - ya_clientes, "ya_clientes": ya_clientes,
            "mensaje": f"{nuevos} comercios nuevos" + (f"; {ya_clientes} ya eran clientes" if ya_clientes else "") + "."}


MANEJADORES = {"prospectos": prospectos, "clientes": clientes, "pedidos": pedidos, "cuenta_corriente": cuenta_corriente}
