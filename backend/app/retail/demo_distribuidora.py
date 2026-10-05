"""Demo del modo distribuidor (SPEC v2, sección 17): «Distribuidora del Valle».

- 1 depósito, 6 vendedores con rutas (lunes a sábado), ~350 comercios clientes en 4 zonas, 3 listas de precios por cliente.
- 13 meses de pedidos: cada cliente compra en su día de ruta con su frecuencia (semanal, quincenal o mensual); entregas completas,
  parciales (faltantes de stock) y rechazos con motivo.
- Cuenta corriente: una factura por entrega y su cobro; pagadores buenos, lentos y morosos (deuda en todos los tramos),
  compromisos de pago cumplidos, pendientes e incumplidos.
- Clientes que dejaron de comprar y clientes en riesgo; objetivos de 3 marcas representadas (uno cumplido, uno en camino, uno en riesgo).
- Usuarios (clave de demostración): dueno@valle.demo, jefe@valle.demo (jefe de ventas), cobranzas@valle.demo y un usuario por
  vendedor (diego@valle.demo, carla@valle.demo, …) que solo ve su cartera.

Casos fijos para las pruebas: CASOS (abajo).
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import catalogo_demo, db, seguridad

EMPRESA = "Distribuidora del Valle"
CUIT = "30-71555444-2"
ZONA_HORARIA = "America/Argentina/Salta"
DUENO = ("dueno@valle.demo", "Graciela Ríos")
USUARIOS = [("jefe@valle.demo", "Martín Copa", "jefe_ventas"), ("cobranzas@valle.demo", "Silvia Arias", "cobranzas")]
# nombre, zona, email, descuento típico que otorga (Diego descuenta de más: se ve en su margen)
VENDEDORES = [("Diego Ruiz", "Salta Centro", "diego@valle.demo", 0.06), ("Carla Mendoza", "Salta Centro", "carla@valle.demo", 0.015),
              ("Javier Soria", "Salta Norte", "javier@valle.demo", 0.02), ("Paula Vargas", "Salta Norte", "paula@valle.demo", 0.015),
              ("Hernán Ibarra", "Valle de Lerma", "hernan@valle.demo", 0.025), ("Natalia Cáceres", "San Salvador de Jujuy", "natalia@valle.demo", 0.02)]
ZONAS = {"Salta Centro": (["Salta"], 0.32), "Salta Norte": (["Salta"], 0.28),
         "Valle de Lerma": (["Cerrillos", "Rosario de Lerma", "La Merced", "El Carril"], 0.2),
         "San Salvador de Jujuy": (["San Salvador de Jujuy", "Palpalá"], 0.2)}
CANALES = {"almacen": (0.5, 1.0, 35), "autoservicio": (0.25, 2.6, 70), "kiosco": (0.2, 0.45, 18), "mayorista": (0.05, 4.0, 90)}  # peso, tamaño, surtido
CATEGORIAS = ("Almacén", "Bebidas", "Limpieza", "Golosinas", "Perfumería")
INCLUYE = {"kiosco": {"Almacén": 0.3, "Bebidas": 0.95, "Limpieza": 0.1, "Golosinas": 1.0, "Perfumería": 0.2},
           "almacen": {"Almacén": 1.0, "Bebidas": 0.9, "Limpieza": 0.85, "Golosinas": 0.7, "Perfumería": 0.6}}
LISTAS = [("General", 0.0), ("Autoservicios", 0.04), ("Mayoristas chicos", 0.07)]
MOTIVOS_RECHAZO = ["Comercio cerrado", "Sin dinero para pagar", "Pedido duplicado", "Mercadería dañada"]
INFLACION_MENSUAL = 0.025

# Casos fijos (los primeros clientes), para las pruebas y para mostrar en la demo.
CASOS = {
    "perdido": {"cliente": "Autoservicio San Bernardo", "vendedor": "Diego Ruiz", "zona": "Salta Centro", "canal": "autoservicio", "frecuencia": 7,
                "tamano": 3.0, "sin_comprar": 35},
    "riesgo": {"cliente": "Almacén Doña Rosa", "vendedor": "Carla Mendoza", "zona": "Salta Centro", "canal": "almacen", "frecuencia": 7,
               "tamano": 1.2, "sin_comprar": 13, "sin_categoria": "Limpieza"},
    "moroso": {"cliente": "Kiosco El Pibe", "vendedor": "Javier Soria", "zona": "Salta Norte", "canal": "kiosco", "frecuencia": 7,
               "tamano": 1.0, "pagador": "moroso"},
    "limite": {"cliente": "Minimercado Los Andes", "vendedor": "Paula Vargas", "zona": "Salta Norte", "canal": "autoservicio", "frecuencia": 7,
               "tamano": 2.0, "pagador": "lento", "limite": 250000},
}
QUIEBRES = 3              # productos populares sin stock en los últimos días (pedidos con faltantes)


@dataclass
class Escala:
    dias: int = 395
    clientes: int = 350
    productos: int = 160


@dataclass(eq=False)
class _Cliente:
    id: int
    nombre: str
    zona: str
    canal: str
    vendedor: int
    frecuencia: int
    tamano: float
    dia: int
    alta: date
    fin: date | None
    canasta: list
    pagador: str
    condicion: int
    lista: int
    descuento_lista: float
    fijo: bool = False


def ya_cargada(conn) -> bool:
    return bool(db.fila(conn, "SELECT 1 FROM organizaciones o JOIN pedidos_venta p ON p.org_id = o.id WHERE o.nombre = %s LIMIT 1", (EMPRESA,)))


def _crear_empresa(conn) -> int:
    from .rutas import EmpresaNueva, crear_empresa
    from .semilla import CLAVE_DEMO
    org, _ = crear_empresa(conn, EmpresaNueva(nombre=EMPRESA, cuit=CUIT, zona_horaria=ZONA_HORARIA, modelo_abastecimiento="centralizado",
                                              modos=["distribuidor"], email_dueno=DUENO[0], nombre_dueno=DUENO[1]), None)
    oid = org["id"]
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.org_id', %s, true)", (str(oid),))
        cur.execute("UPDATE organizaciones SET plan='cadena', pagado_hasta='2099-12-31', costos_con_iva=false WHERE id=%s", (oid,))
        cur.execute("UPDATE usuarios SET hash_clave=%s WHERE org_id=%s", (seguridad.hash_clave(CLAVE_DEMO), oid))
        for email, nombre, rol in USUARIOS:
            cur.execute("INSERT INTO usuarios (org_id, email, nombre, rol, hash_clave) VALUES (%s,%s,%s,%s,%s)",
                        (oid, email, nombre, rol, seguridad.hash_clave(CLAVE_DEMO)))
    return oid


def cargar(hoy: date | None = None, escala: Escala | None = None, semilla: int = 20261005, calcular: bool = True) -> dict:
    """Crea la empresa (si no existe) y carga la demo. Devuelve un resumen."""
    escala = escala or Escala()
    rng = random.Random(semilla)
    hoy = hoy or datetime.now(ZoneInfo(ZONA_HORARIA)).date()
    inicio = hoy - timedelta(days=escala.dias - 1)
    from .semilla import CLAVE_DEMO
    with db.transaccion(superadmin=True) as conn:
        org = db.fila(conn, "SELECT id FROM organizaciones WHERE nombre=%s", (EMPRESA,))
        oid = org["id"] if org else _crear_empresa(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.org_id', %s, true)", (str(oid),))
        if db.fila(conn, "SELECT 1 FROM pedidos_venta WHERE org_id=%s LIMIT 1", (oid,)):
            return {"cargada": False, "motivo": "La distribuidora ya tiene pedidos."}
        deposito = db.fila(conn, "INSERT INTO ubicaciones (org_id, nombre, tipo, direccion, localidad) VALUES (%s,'Depósito central','ambos',"
                                 "'Parque Industrial, lote 22','Salta') RETURNING id", (oid,))["id"]

        # ---------------------------------------------------------------- catálogo, proveedores, precios
        catalogo = [p for p in catalogo_demo.productos() if p["categoria"] in CATEGORIAS and p.get("unidad", "unidad") != "kg"]
        n = min(escala.productos, len(catalogo))           # repartidos en todo el catálogo (todas las categorías)
        catalogo = [catalogo[int(i * len(catalogo) / n)] for i in range(n)]
        categorias: dict = {}
        for p in catalogo:
            if p["categoria"] not in categorias:
                categorias[p["categoria"]] = db.fila(conn, "INSERT INTO categorias (org_id, nombre) VALUES (%s,%s) RETURNING id", (oid, p["categoria"]))["id"]
            clave = (p["categoria"], p["subcategoria"])
            if clave not in categorias:
                categorias[clave] = db.fila(conn, "INSERT INTO categorias (org_id, nombre, padre_id) VALUES (%s,%s,%s) RETURNING id",
                                            (oid, p["subcategoria"], categorias[p["categoria"]]))["id"]
        proveedores = {}
        for nombre, dias, demora, minimo, bultos, pago in catalogo_demo.PROVEEDORES:
            if any(p["proveedor"] == nombre for p in catalogo):
                proveedores[nombre] = db.fila(conn, "INSERT INTO proveedores (org_id, razon_social, cuit, dias_visita, demora_entrega_dias, "
                                                    "pedido_minimo_monto, pedido_minimo_bultos, condiciones_pago) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                                              (oid, nombre, f"30-{rng.randint(50000000, 79999999)}-{rng.randint(0, 9)}", dias, demora or 2,
                                               minimo * 3, bultos, pago))["id"]
        orden = list(range(len(catalogo)))
        rng.shuffle(orden)
        prods = []
        for rango, i in enumerate(orden):
            p = catalogo[i]
            pid = db.fila(conn, "INSERT INTO productos (org_id, codigo_interno, nombre, ean, marca, categoria_id, unidad, perecedero, estado_mapeo) "
                                "VALUES (%s,%s,%s,%s,%s,%s,'unidad',false,'propio') RETURNING id",
                          (oid, p["codigo"], p["nombre"], p["ean"], p["marca"], categorias[(p["categoria"], p["subcategoria"])]))["id"]
            costo = p["precio"] * (1 - p["margen"]) / 1.21 * 0.82          # lo que le cuesta a la distribuidora, sin IVA
            prods.append({"id": pid, "nombre": p["nombre"], "categoria": p["categoria"], "marca": p["marca"], "proveedor": p["proveedor"],
                          "bulto": p["bulto"], "costo": costo, "lista": costo * rng.uniform(1.16, 1.26), "popularidad": 1 / (rango + 1) ** 0.8,
                          "estacion": p["estacion"]})
        prods.sort(key=lambda x: -x["popularidad"])
        db.copiar(conn, "producto_proveedores", ["org_id", "producto_id", "proveedor_id", "costo", "unidades_por_bulto", "principal"],
                  [(oid, p["id"], proveedores[p["proveedor"]], round(p["costo"], 4), p["bulto"], True) for p in prods])
        db.copiar(conn, "precios", ["org_id", "producto_id", "precio", "desde", "origen"],
                  [(oid, p["id"], round(p["lista"] * 1.21, 2), hoy - timedelta(days=20), "importado") for p in prods])
        sin_stock = {p["id"]: hoy - timedelta(days=rng.randint(6, 12)) for p in prods[:QUIEBRES]}

        # ---------------------------------------------------------------- vendedores, usuarios, listas
        vendedores = {}
        for nombre, zona, email, desc in VENDEDORES:
            vid = db.fila(conn, "INSERT INTO vendedores (org_id, nombre, zona) VALUES (%s,%s,%s) RETURNING id", (oid, nombre, zona))["id"]
            vendedores[nombre] = {"id": vid, "zona": zona, "descuento": desc}
            with conn.cursor() as cur:
                cur.execute("INSERT INTO usuarios (org_id, email, nombre, rol, hash_clave, vendedor_id) VALUES (%s,%s,%s,'vendedor',%s,%s)",
                            (oid, email, nombre, seguridad.hash_clave(CLAVE_DEMO), vid))
        listas = [db.fila(conn, "INSERT INTO listas_precios_clientes (org_id, nombre, descuento_pct) VALUES (%s,%s,%s) RETURNING id",
                          (oid, n, d))["id"] for n, d in LISTAS]

        # ---------------------------------------------------------------- clientes
        clientes = _clientes(conn, rng, oid, escala.clientes, inicio, hoy, prods, vendedores, listas)

        # ---------------------------------------------------------------- pedidos, entregas, cuenta corriente
        resumen = _pedidos(conn, rng, oid, deposito, clientes, prods, vendedores, inicio, hoy, sin_stock)
        _rutas_y_visitas(conn, rng, oid, clientes, vendedores, hoy, resumen["fechas_pedido"])
        _metas_y_marcas(conn, oid, vendedores, hoy, resumen)

        # ---------------------------------------------------------------- stock del depósito
        diaria = resumen["diaria"]
        stock = []
        for k, p in enumerate(prods):
            if p["id"] in sin_stock:
                cantidad = 0
            elif k % 23 == 5:
                cantidad = math.ceil(diaria.get(p["id"], 0.2) * rng.uniform(70, 120))          # sobrestock: plata parada
            elif k % 11 == 3:
                cantidad = math.ceil(diaria.get(p["id"], 0.2) * rng.uniform(1, 4))            # se agota en días
            else:
                cantidad = math.ceil(diaria.get(p["id"], 0.2) * rng.uniform(12, 35))
            stock.append((oid, p["id"], deposito, cantidad))
        db.copiar(conn, "stock_actual", ["org_id", "producto_id", "ubicacion_id", "cantidad"], stock)
        db.copiar(conn, "stock_diario", ["org_id", "producto_id", "ubicacion_id", "fecha", "stock_cierre", "con_stock"],
                  [(oid, pid, deposito, desde + timedelta(days=d), 0, False) for pid, desde in sin_stock.items()
                   for d in range((hoy - desde).days + 1)])
        resumen = {k: v for k, v in resumen.items() if k not in ("diaria", "fechas_pedido", "marcas", "venta_mes")}
        resumen.update({"org_id": oid, "clientes": len(clientes), "productos": len(prods)})
    if calcular:
        from . import motor
        resumen["calculo"] = {k: v for k, v in motor.recalcular(oid, hoy, "nocturno").items() if k in ("segundos", "productos")}
    return resumen


def _clientes(conn, rng, oid, cantidad, inicio, hoy, prods, vendedores, listas) -> list[_Cliente]:
    por_zona = defaultdict(list)
    for nombre, v in vendedores.items():
        por_zona[v["zona"]].append(nombre)
    nombres_base = ["Almacén", "Despensa", "Autoservicio", "Kiosco", "Minimercado", "Maxikiosco", "Mayorista"]
    apellidos = ["San Martín", "La Esperanza", "El Sol", "Don Luis", "Los Lapachos", "Santa Ana", "El Molino", "La Unión", "Las Rosas", "El Cardón",
                 "Doña Clara", "Los Ceibos", "El Trébol", "San Cayetano", "La Estrella", "El Progreso", "Los Nogales", "Tres Cerritos", "La Loma",
                 "El Portal", "Don Tito", "La Familia", "El Algarrobo", "Santa Rita", "Las Moras", "Los Pinos"]
    salida = []
    filas = []
    casos = list(CASOS.values())
    zonas, pesos_z = zip(*[(z, w) for z, (_, w) in ZONAS.items()])
    canales, pesos_c = zip(*[(c, w[0]) for c, w in CANALES.items()])
    usados = set()
    for i in range(cantidad):
        caso = casos[i] if i < len(casos) else None
        if caso:
            zona, canal, vendedor, frecuencia, tamano = caso["zona"], caso["canal"], caso["vendedor"], caso["frecuencia"], caso["tamano"]
            nombre = caso["cliente"]
        else:
            zona = rng.choices(zonas, pesos_z)[0]
            canal = rng.choices(canales, pesos_c)[0]
            vendedor = rng.choice(por_zona[zona])
            frecuencia = rng.choices([7, 14, 28], [0.6, 0.3, 0.1] if canal in ("autoservicio", "mayorista") else [0.4, 0.37, 0.23])[0]
            tamano = CANALES[canal][1] * rng.lognormvariate(0, 0.45)
            base = {"almacen": ["Almacén", "Despensa"], "autoservicio": ["Autoservicio", "Minimercado"], "kiosco": ["Kiosco", "Maxikiosco"],
                    "mayorista": ["Mayorista"]}[canal]
            while True:
                nombre = f"{rng.choice(base)} {rng.choice(apellidos)}"
                if nombre not in usados:
                    break
                nombre = f"{nombre} {rng.randint(2, 99)}"
                if nombre not in usados:
                    break
        usados.add(nombre)
        localidad = rng.choice(ZONAS[zona][0])
        alta = inicio if (caso or rng.random() < 0.85) else inicio + timedelta(days=rng.randint(30, max(31, (hoy - inicio).days - 60)))
        fin = None
        if caso and "sin_comprar" in caso:
            fin = hoy - timedelta(days=caso["sin_comprar"])
        elif not caso:
            r = rng.random()
            if r < 0.08:                                         # dejó de comprar
                fin = hoy - timedelta(days=rng.randint(max(30, frecuencia * 4), 220))
            elif r < 0.13:                                       # se está alejando: lleva entre 1,6 y 2,6 veces su intervalo
                fin = hoy - timedelta(days=int(frecuencia * rng.uniform(1.6, 2.6)))
        # Surtido: categorías según el tipo de comercio, productos según su popularidad.
        incluye = INCLUYE.get(canal, {})
        categorias = {c for c in CATEGORIAS if rng.random() < incluye.get(c, 0.95)}
        if caso and caso.get("sin_categoria"):
            categorias.discard(caso["sin_categoria"])
        posibles = [p for p in prods if p["categoria"] in categorias]
        n = min(len(posibles), max(5, int(CANALES[canal][2] * rng.uniform(0.7, 1.3) * len(prods) / 160)))
        canasta = []
        pesos = [p["popularidad"] for p in posibles]
        while len(canasta) < n and posibles:
            k = rng.choices(range(len(posibles)), pesos)[0]
            canasta.append(posibles.pop(k))
            pesos.pop(k)
        pagador = caso.get("pagador", "bueno") if caso else rng.choices(["bueno", "lento", "moroso"], [0.8, 0.14, 0.06])[0]
        condicion = 0 if canal == "kiosco" and not caso else rng.choice([7, 15, 30]) if not caso else 15
        lista = 1 if canal == "autoservicio" else 2 if canal == "mayorista" else 0
        cid = len(salida)
        salida.append(_Cliente(id=cid, nombre=nombre, zona=zona, canal=canal, vendedor=vendedores[vendedor]["id"], frecuencia=frecuencia,
                               tamano=tamano, dia=min(hoy.weekday(), 5) if caso is CASOS["riesgo"] else rng.randint(0, 5), fijo=bool(caso),
                               alta=alta, fin=fin, canasta=canasta, pagador=pagador, condicion=condicion, lista=listas[lista],
                               descuento_lista=LISTAS[lista][1]))
        compra_mes = tamano * 120000
        filas.append((oid, f"demo:{i + 1:04d}", nombre, nombre if rng.random() < 0.5 else None, f"20-{rng.randint(10000000, 45000000)}-{rng.randint(0, 9)}",
                      f"{rng.choice(['Belgrano', 'San Martín', 'Mitre', 'Güemes', 'Alvarado', 'Caseros', 'España'])} {rng.randint(100, 3900)}",
                      localidad, zona, canal, listas[lista], (caso or {}).get("limite") or round(compra_mes * rng.uniform(2.0, 3.5), -3),
                      condicion, vendedores[vendedor]["id"], alta))
    db.copiar(conn, "clientes_b2b", ["org_id", "codigo_externo", "razon_social", "nombre_fantasia", "cuit", "direccion", "localidad", "zona", "canal",
                                     "lista_precios_id", "limite_credito", "condicion_pago_dias", "vendedor_id", "alta"], filas)
    ids = {f["codigo_externo"]: f["id"] for f in db.filas(conn, "SELECT id, codigo_externo FROM clientes_b2b WHERE org_id=%s", (oid,))}
    for k, c in enumerate(salida):
        c.id = ids[f"demo:{k + 1:04d}"]
    return salida


def _factor_precio(d: date, hoy: date) -> float:
    return (1 + INFLACION_MENSUAL) ** (-(hoy - d).days / 30)


def _estacion(estacion: str | None, d: date) -> float:
    if estacion == "verano":
        return 1 + 0.35 * math.cos((d.timetuple().tm_yday - 15) / 365 * 2 * math.pi)
    if estacion == "invierno":
        return 1 - 0.25 * math.cos((d.timetuple().tm_yday - 15) / 365 * 2 * math.pi)
    return 1.0


def _ids(conn, secuencia: str, n: int) -> list[int]:
    return [f["id"] for f in db.filas(conn, f"SELECT nextval('{secuencia}') id FROM generate_series(1, %s)", (n,))]


def _pedidos(conn, rng, oid, deposito, clientes, prods, vendedores, inicio, hoy, sin_stock) -> dict:
    descuento_vendedor = {v["id"]: v["descuento"] for v in vendedores.values()}
    pedidos, lineas, entregas, docs = [], [], [], []
    diaria = defaultdict(float)
    fechas_pedido = defaultdict(set)
    venta_mes = defaultdict(float)           # (vendedor, mes) → venta neta
    marcas = defaultdict(lambda: defaultdict(float))   # marca → {'unidades', clientes...}
    marcas_clientes = defaultdict(set)
    numero = 0
    for c in clientes:
        # Primera compra: el primer día de ruta desde su alta, con un desfase según su frecuencia.
        d = c.alta + timedelta(days=(c.dia - c.alta.weekday()) % 7 + 7 * rng.randint(0, c.frecuencia // 7 - 1))
        while d <= hoy and (c.fin is None or d <= c.fin):
            if rng.random() < 0.06 and not c.fijo:          # a veces no pide esa vuelta
                d += timedelta(days=c.frecuencia)
                continue
            numero += 1
            if d == hoy:
                estado = "tomado"
            elif d == hoy - timedelta(days=1):
                estado = "preparado"
            else:
                estado = "rechazado" if rng.random() < 0.02 else "entregado"
            factor = _factor_precio(d, hoy)
            detalle = []
            for p in c.canasta:
                if rng.random() > 0.5:
                    continue
                media = c.tamano * p["popularidad"] ** 0.35 * 9 * c.frecuencia / 7 * _estacion(p["estacion"], d)
                pedida = max(1, round(media * rng.uniform(0.6, 1.4)))
                if c.canal in ("autoservicio", "mayorista") and p["bulto"] > 1:
                    pedida = max(1, round(pedida / p["bulto"])) * p["bulto"]
                lista = p["lista"] * factor * (1 - c.descuento_lista)
                desc = min(0.15, max(0.0, rng.gauss(descuento_vendedor[c.vendedor], 0.01)))
                precio = lista * (1 - desc)
                faltante = 0
                if p["id"] in sin_stock and d >= sin_stock[p["id"]]:
                    faltante = pedida
                elif rng.random() < 0.012:
                    faltante = max(1, round(pedida * rng.uniform(0.3, 1)))
                detalle.append([p, pedida, faltante, round(lista, 4), round(precio, 4), round(p["costo"] * factor, 4)])
            if not detalle:
                d += timedelta(days=c.frecuencia)
                continue
            if estado == "entregado" and any(x[2] for x in detalle):
                estado = "entregado_parcial"
            pedidos.append([None, oid, f"PV-{numero:06d}", c.id, c.vendedor, deposito, d, d + timedelta(days=1), estado, 0, 0, 0, "demo", f"demo:{numero}"])
            total = entregado = descuento = 0.0
            for p, pedida, faltante, lista, precio, costo in detalle:
                entregada = 0 if estado == "rechazado" else (pedida - faltante if estado in ("entregado", "entregado_parcial") else 0)
                facturable = entregada if estado in ("entregado", "entregado_parcial") else (pedida if estado in ("tomado", "preparado") else 0)
                total += pedida * precio
                entregado += entregada * precio
                descuento += (lista - precio) * pedida
                lineas.append([len(pedidos) - 1, p["id"], pedida, entregada, faltante if estado != "rechazado" else 0, lista, precio,
                               round((lista - precio) * pedida, 2), costo])
                if facturable + faltante and d > hoy - timedelta(days=90):
                    diaria[p["id"]] += (facturable + faltante) / 90
                marcas[p["marca"]][d] += facturable
                if facturable:
                    marcas_clientes[(p["marca"], d)].add(c.id)
            pedidos[-1][9:12] = [round(total, 2), round(entregado, 2), round(descuento, 2)]
            fechas_pedido[c.id].add(d)
            venta_mes[(c.vendedor, d.replace(day=1))] += entregado if estado != "tomado" and estado != "preparado" else total
            if estado in ("entregado", "entregado_parcial", "rechazado"):
                entregas.append([len(pedidos) - 1, d + timedelta(days=1), {"entregado": "entregado", "entregado_parcial": "parcial",
                                                                          "rechazado": "rechazado"}[estado],
                                 rng.choice(MOTIVOS_RECHAZO) if estado == "rechazado" else ("Faltante de stock" if estado == "entregado_parcial" else None)])
                if entregado > 0:
                    docs.append((c, len(pedidos) - 1, d + timedelta(days=1), round(entregado * 1.21, 2)))
            d += timedelta(days=c.frecuencia)
    ids = _ids(conn, "pedidos_venta_id_seq", len(pedidos))
    for p, i in zip(pedidos, ids):
        p[0] = i
    db.copiar(conn, "pedidos_venta", ["id", "org_id", "numero", "cliente_id", "vendedor_id", "ubicacion_id", "fecha", "fecha_entrega_prometida", "estado",
                                      "total", "total_entregado", "descuento", "origen", "numero_externo"], [tuple(p) for p in pedidos])
    db.copiar(conn, "pedidos_venta_lineas", ["org_id", "pedido_id", "producto_id", "cantidad_pedida", "cantidad_entregada", "faltante_stock",
                                             "precio_lista", "precio", "descuento", "costo_unitario"],
              [(oid, ids[k], *rest) for k, *rest in lineas])
    db.copiar(conn, "entregas", ["org_id", "pedido_id", "fecha", "resultado", "motivo"], [(oid, ids[k], *rest) for k, *rest in entregas])
    _cuenta_corriente(conn, rng, oid, docs, ids, hoy)
    return {"pedidos": len(pedidos), "lineas": len(lineas), "diaria": diaria, "fechas_pedido": fechas_pedido, "venta_mes": venta_mes,
            "marcas": (marcas, marcas_clientes)}


def _cuenta_corriente(conn, rng, oid, docs, ids, hoy) -> None:
    filas, compromisos = [], []
    numero = 0
    deudores = defaultdict(float)
    for c, k, fecha, importe in docs:
        numero += 1
        vence = fecha + timedelta(days=c.condicion)
        if c.condicion == 0:
            pago = fecha
        elif c.pagador == "bueno":
            pago = vence + timedelta(days=rng.randint(-3, 4))
        elif c.pagador == "lento":
            pago = vence + timedelta(days=rng.randint(10, 45))
        else:
            pago = None if (hoy - fecha).days < 160 and rng.random() < 0.7 else vence + timedelta(days=rng.randint(40, 120))
        pagada = pago is not None and pago <= hoy
        filas.append((oid, c.id, "factura", f"FA-{numero:07d}", fecha, vence, importe, 0 if pagada else importe, ids[k], "demo", f"fa:{numero}"))
        if pagada:
            filas.append((oid, c.id, "recibo", f"RC-{numero:07d}", pago, None, -importe, 0, None, "demo", f"rc:{numero}"))
        else:
            deudores[c.id] += importe
    # Límite de crédito según lo que factura cada uno: un buen pagador queda holgado; los lentos y morosos lo pasan.
    mensual = defaultdict(float)
    for c, k, fecha, importe in docs:
        if fecha > hoy - timedelta(days=90):
            mensual[c] += importe / 3
    with conn.cursor() as cur:
        cur.executemany("UPDATE clientes_b2b SET limite_credito = %s WHERE id = %s",
                        [(round(max(50000, m * (c.condicion / 30 * 2 + 0.4)) * rng.uniform(1.0, 1.4), -3), c.id)
                         for c, m in mensual.items() if not c.fijo or c.pagador != "lento"])
    db.copiar(conn, "documentos_cc", ["org_id", "cliente_id", "tipo", "numero", "fecha", "vencimiento", "importe", "saldo", "pedido_id", "origen",
                                      "numero_externo"], filas)
    for i, (cid, deuda) in enumerate(sorted(deudores.items(), key=lambda x: -x[1])[:14]):
        estado, cuando = [("pendiente", 5), ("pendiente", -6), ("cumplido", -20), ("incumplido", -15)][i % 4]
        compromisos.append((oid, cid, hoy + timedelta(days=cuando), round(deuda * rng.uniform(0.2, 0.5), -2), estado,
                            "Promete pagar con la próxima entrega" if i % 2 else "Paga la mitad a fin de mes"))
    db.copiar(conn, "compromisos_pago", ["org_id", "cliente_id", "fecha", "monto", "estado", "nota"], compromisos)


def _rutas_y_visitas(conn, rng, oid, clientes, vendedores, hoy, fechas_pedido) -> None:
    rutas = {}
    for v in vendedores.values():
        for dia in range(6):
            rutas[(v["id"], dia)] = db.fila(conn, "INSERT INTO rutas (org_id, vendedor_id, dia_semana, nombre) VALUES (%s,%s,%s,%s) RETURNING id",
                                            (oid, v["id"], dia, ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"][dia]))["id"]
    orden = defaultdict(int)
    filas, visitas = [], []
    for c in clientes:
        r = rutas[(c.vendedor, c.dia)]
        orden[r] += 1
        filas.append((oid, r, c.id, orden[r]))
        d = hoy - timedelta(days=(hoy.weekday() - c.dia) % 7)
        for semana in range(8):
            f = d - timedelta(days=7 * semana)
            if f < c.alta:
                break
            if f == hoy:
                visitas.append((oid, c.vendedor, c.id, f, True, f in fechas_pedido[c.id], "pedido" if f in fechas_pedido[c.id] else None))
                continue
            realizada = rng.random() < 0.92 or f in fechas_pedido[c.id]
            resultado = ("pedido" if f in fechas_pedido[c.id] else rng.choices(["sin_pedido", "cerrado", "no_atendio"], [0.8, 0.1, 0.1])[0]) if realizada else None
            visitas.append((oid, c.vendedor, c.id, f, True, realizada, resultado))
    db.copiar(conn, "rutas_clientes", ["org_id", "ruta_id", "cliente_id", "orden"], filas)
    db.copiar(conn, "visitas", ["org_id", "vendedor_id", "cliente_id", "fecha", "planificada", "realizada", "resultado"], visitas)


def _metas_y_marcas(conn, oid, vendedores, hoy, resumen) -> None:
    venta_mes = resumen["venta_mes"]
    mes = hoy.replace(day=1)
    filas = []
    for v in vendedores.values():
        meses = sorted(m for (vid, m) in venta_mes if vid == v["id"])
        for m in meses:
            previos = [venta_mes[(v["id"], x)] for x in meses if x < m][-3:]
            base = sum(previos) / len(previos) if previos else venta_mes[(v["id"], m)]
            filas.append((oid, v["id"], m, round(base * 1.08, -3)))
    db.copiar(conn, "metas_vendedor", ["org_id", "vendedor_id", "mes", "venta"], filas)
    # Objetivos de las 3 marcas con más volumen: período de 2 meses que termina a fin de este mes.
    marcas, marcas_clientes = resumen["marcas"]
    desde = (mes - timedelta(days=1)).replace(day=1)
    hasta = (mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    transcurrido = ((hoy - desde).days + 1) / ((hasta - desde).days + 1)
    volumen = {m: sum(u for d, u in dias.items() if desde <= d <= hoy) for m, dias in marcas.items()}
    top = sorted(volumen, key=lambda m: -volumen[m])[:3]
    objetivos = []
    for i, marca in enumerate(top):
        if i == 0:      # en riesgo: al ritmo actual no llega
            objetivos.append((oid, marca, desde, hasta, "volumen", round(volumen[marca] / transcurrido * 1.18), 450000))
        elif i == 1:    # en camino
            objetivos.append((oid, marca, desde, hasta, "volumen", round(volumen[marca] / transcurrido * 0.96), 300000))
        else:           # cobertura ya cumplida
            clientes = set().union(*(cs for (m, d), cs in marcas_clientes.items() if m == marca and desde <= d <= hoy))
            objetivos.append((oid, marca, desde, hasta, "cobertura", max(1, round(len(clientes) * 0.9)), 200000))
    db.copiar(conn, "objetivos_marca", ["org_id", "marca", "desde", "hasta", "tipo", "objetivo", "bonificacion"], objetivos)


def preparar() -> dict | None:
    """Al arrancar (solo en modo demo): crea la distribuidora si no existe y la regenera hasta hoy si quedó vieja."""
    if db.modo_cuentas() != "demo":
        return None
    with db.transaccion(superadmin=True) as conn:
        org = db.fila(conn, "SELECT id FROM organizaciones WHERE nombre=%s", (EMPRESA,))
        hoy = datetime.now(ZoneInfo(ZONA_HORARIA)).date()
        if org:
            ultimo = db.fila(conn, "SELECT max(fecha) m, bool_and(origen = 'demo') solo_demo FROM pedidos_venta WHERE org_id=%s", (org["id"],))
            if ultimo["m"] and (ultimo["m"] >= hoy or not ultimo["solo_demo"]):
                return None
            if ultimo["m"]:
                from .cuentas import borrar_empresas
                borrar_empresas(conn, [org["id"]])
    return cargar(hoy)
