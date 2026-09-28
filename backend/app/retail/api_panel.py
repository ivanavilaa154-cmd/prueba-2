"""Panel para distribuidores y marcas (sección 13.3) y portal de recepción de pedidos.

Anonimato (CLAUDE.md, regla 8: la única consulta entre empresas es este panel agregado):
- Solo entran comercios con consentimiento explícito (organizaciones.consentimiento_datos) y activos.
- Un grupo (zona, semana, subcategoría, marca, producto) se publica si lo forman al menos PANEL_MIN_COMERCIOS comercios y ninguno
  concentra más de PANEL_MAX_PARTICIPACION de su facturación. Nunca se devuelven nombres ni filas de comercios.
- Supresión complementaria: cuando se publica una partición (zonas de un total, marcas de una subcategoría, productos de una marca,
  semanas de un período), lo reservado se junta en «Otros» y ese resto también tiene que pasar el umbral; si no pasa, se reservan más
  grupos (los más chicos) hasta que pase. Así nadie puede despejar un grupo reservado restando los publicados del total.
- Las zonas que no llegan al umbral se juntan en «Otras zonas»; si ni juntas llegan, sus datos quedan afuera de todo el panel.
Portal de pedidos: el distribuidor ve las OC que los comercios le enviaron (proveedor con su CUIT) y puede confirmarlas con una fecha
de entrega. Esas OC no son anónimas porque el comercio se las mandó; no ve ninguna otra OC.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import config
from . import db, permisos, sesiones
from .rutas import respuesta

api = APIRouter(prefix="/retail/api", tags=["retail"])
OTRAS_ZONAS = "Otras zonas"
OTRAS_MARCAS = "Otras marcas"
COMERCIOS = "o.tipo = 'comercio' AND o.consentimiento_datos AND o.activa"


def pasa(por_org: dict) -> bool:
    """¿Se puede publicar un grupo? Al menos N comercios con valor y ninguno con más del máximo de participación."""
    valores = [float(v) for v in por_org.values() if v and float(v) > 0]
    if len(valores) < config.PANEL_MIN_COMERCIOS:
        return False
    return max(valores) / sum(valores) <= config.PANEL_MAX_PARTICIPACION


def _unir(grupos: list[dict]) -> dict:
    total: dict = defaultdict(float)
    for g in grupos:
        for org, v in g.items():
            total[org] += float(v)
    return total


def particion(grupos: dict) -> tuple[set, bool]:
    """Qué grupos publicar de una partición y si el resto (reservados juntos) también se puede mostrar.
    Si el resto no pasa se reservan los publicados más chicos hasta que pase; si no pasa ni con todo, no se publica nada
    (y el total de la partición tampoco)."""
    publicados = {k for k, g in grupos.items() if pasa(g)}
    while True:
        resto = _unir([g for k, g in grupos.items() if k not in publicados])
        if not any(v > 0 for v in resto.values()):
            return publicados, True
        if pasa(resto):
            return publicados, True
        if not publicados:
            return set(), False
        publicados.remove(min(publicados, key=lambda k: sum(float(v) for v in grupos[k].values())))


def _marcas(ctx: db.Contexto) -> tuple[dict, list[str]]:
    permisos.exigir(ctx, "panel_marcas")
    with db.transaccion(ctx) as conn:
        org = db.fila(conn, "SELECT id, nombre, cuit, tipo FROM organizaciones WHERE id=%s", (ctx.org_id,))
        marcas = [f["marca"] for f in db.filas(conn, "SELECT marca FROM marcas_distribuidor ORDER BY marca")]
    if not org or org["tipo"] != "distribuidor":
        raise HTTPException(status_code=403, detail="El panel es para empresas distribuidoras o marcas.")
    return org, marcas


def _hasta(conn) -> date | None:
    return db.fila(conn, f"""SELECT max(a.fecha) f FROM agg_producto_ubicacion_dia a JOIN organizaciones o ON o.id = a.org_id
                             WHERE {COMERCIOS} AND a.fecha <= current_date""")["f"]


def calcular(conn, marcas: list[str], semanas: int = 12) -> dict:
    umbral = {"min_comercios": config.PANEL_MIN_COMERCIOS, "max_participacion": config.PANEL_MAX_PARTICIPACION}
    h = _hasta(conn)
    mias = {m.lower() for m in marcas}
    base = {"umbral": umbral, "marcas": marcas, "hasta": h, "semanas": semanas}
    if not h or not mias:
        return {**base, "sin_datos": True}
    semanas = max(8, min(semanas, 26))
    d = h - timedelta(days=7 * semanas - 1)
    maestros = {f["id"]: f for f in db.filas(conn, """
        SELECT id, nombre, marca, categoria, subcategoria FROM productos_maestros
        WHERE subcategoria IN (SELECT DISTINCT subcategoria FROM productos_maestros WHERE lower(marca) = ANY(%s))""", (list(mias),))}
    subs = sorted({m["subcategoria"] for m in maestros.values()})
    filas = db.filas(conn, f"""
        SELECT a.org_id, coalesce(nullif(u.localidad, ''), 'Sin localidad') zona, (%(h)s - a.fecha) / 7 semana, p.maestro_id,
               sum(a.unidades)::float unidades, sum(a.facturacion)::float facturacion, sum(a.unidades_promo)::float promo
        FROM agg_producto_ubicacion_dia a JOIN organizaciones o ON o.id = a.org_id
        JOIN productos p ON p.id = a.producto_id JOIN ubicaciones u ON u.id = a.ubicacion_id
        WHERE {COMERCIOS} AND a.fecha BETWEEN %(d)s AND %(h)s AND p.maestro_id = ANY(%(m)s)
        GROUP BY 1, 2, 3, 4""", {"d": d, "h": h, "m": list(maestros)})
    es_mia = {mid: (m["marca"] or "").lower() in mias for mid, m in maestros.items()}

    # 1) universo: zonas publicadas (+ «Otras zonas» si juntas pasan); el resto queda afuera de todo.
    por_zona = defaultdict(lambda: defaultdict(float))
    for f in filas:
        por_zona[f["zona"]][f["org_id"]] += f["facturacion"]
    # Acá no hace falta reservar zonas publicadas: lo que no pasa ni junto se excluye de todo el panel (ningún total lo incluye).
    zonas_ok = {z for z, g in por_zona.items() if pasa(g)}
    resto_ok = pasa(_unir([g for z, g in por_zona.items() if z not in zonas_ok]))
    nombre_zona = {z: (z if z in zonas_ok else OTRAS_ZONAS) for z in por_zona if z in zonas_ok or resto_ok}
    filas = [{**f, "zona": nombre_zona[f["zona"]]} for f in filas if f["zona"] in nombre_zona]
    reservadas = len([z for z in por_zona if z not in zonas_ok])
    if not filas:
        return {**base, "sin_datos": False, "reservado": True, "zonas_reservadas": reservadas,
                "motivo": f"Todavía no hay al menos {umbral['min_comercios']} comercios con consentimiento que vendan estas categorías."}
    comercios = {f["org_id"] for f in filas}

    def grupos(clave, filtro=lambda f: True, valor="facturacion") -> dict:
        g: dict = defaultdict(lambda: defaultdict(float))
        for f in filas:
            if filtro(f):
                g[clave(f)][f["org_id"]] += f[valor]
        return g

    def suma(cond, campo: str = "facturacion") -> float:
        return sum(f[campo] for f in filas if cond(f))

    # 2) zonas: mercado (todas las marcas de las subcategorías) y tus marcas, con su participación.
    mercado_z = grupos(lambda f: f["zona"])
    mias_z = grupos(lambda f: f["zona"], lambda f: es_mia[f["maestro_id"]])
    mias_z_ok, _ = particion(mias_z)
    zonas = []
    for z, g in sorted(mercado_z.items(), key=lambda x: -sum(x[1].values())):
        mercado = sum(g.values())
        fila = {"zona": z, "comercios": len([v for v in g.values() if v > 0]), "mercado": round(mercado, 2)}
        if z in mias_z_ok:
            mias_f = sum(mias_z[z].values())
            fila.update({"facturacion": round(mias_f, 2), "participacion": mias_f / mercado if mercado else None,
                         "unidades": round(suma(lambda f: f["zona"] == z and es_mia[f["maestro_id"]], "unidades"), 1)})
        else:
            fila["reservado"] = True
        zonas.append(fila)

    # 3) serie semanal de tus marcas (semana 0 = los últimos 7 días).
    sem = grupos(lambda f: f["semana"], lambda f: es_mia[f["maestro_id"]])
    sem_ok, total_ok = particion(sem)
    serie = []
    for s in range(semanas - 1, -1, -1):
        fin = h - timedelta(days=7 * s)
        if s in sem_ok:
            serie.append({"semana": fin - timedelta(days=6), "hasta": fin, "facturacion": round(sum(sem[s].values()), 2),
                          "unidades": round(suma(lambda f, s=s: f["semana"] == s and es_mia[f["maestro_id"]], "unidades"), 1)})
        else:
            serie.append({"semana": fin - timedelta(days=6), "hasta": fin, "reservado": True})
    ultimas = [x for x in serie[-4:] if not x.get("reservado")]
    previas = [x for x in serie[-8:-4] if not x.get("reservado")]
    kpis = {"comercios": len(comercios), "zonas": len([z for z in zonas if z["zona"] != OTRAS_ZONAS]), "zonas_reservadas": reservadas}
    if len(ultimas) == 4 and len(previas) == 4:
        kpis["facturacion_4s"] = round(sum(x["facturacion"] for x in ultimas), 2)
        kpis["unidades_4s"] = round(sum(x["unidades"] for x in ultimas), 1)
        kpis["variacion_4s"] = kpis["facturacion_4s"] / sum(x["facturacion"] for x in previas) - 1
    tot_merc = sum(sum(g.values()) for g in mercado_z.values())
    if total_ok and tot_merc:
        kpis["participacion"] = sum(sum(g.values()) for g in sem.values()) / tot_merc

    # 4) participación de mercado por subcategoría: marcas publicadas y «Otras marcas» (también con umbral).
    mercado = []
    sub_g = grupos(lambda f: maestros[f["maestro_id"]]["subcategoria"])
    subs_ok, _ = particion(sub_g)
    for sub in subs:
        if sub not in subs_ok:
            mercado.append({"subcategoria": sub, "reservado": True})
            continue
        marcas_g = grupos(lambda f: maestros[f["maestro_id"]]["marca"] or "Sin marca", lambda f, sub=sub: maestros[f["maestro_id"]]["subcategoria"] == sub)
        ok, _ = particion(marcas_g)
        total = sum(sum(g.values()) for g in marcas_g.values())
        filas_m = [{"marca": m, "tuya": m.lower() in mias, "facturacion": round(sum(marcas_g[m].values()), 2),
                    "participacion": sum(marcas_g[m].values()) / total} for m in ok]
        otras = sum(sum(g.values()) for m, g in marcas_g.items() if m not in ok)
        if otras:
            filas_m.append({"marca": OTRAS_MARCAS, "tuya": False, "facturacion": round(otras, 2), "participacion": otras / total})
        filas_m.sort(key=lambda x: -x["facturacion"])
        mercado.append({"subcategoria": sub, "facturacion": round(total, 2), "marcas": filas_m,
                        "tuya": sum(x["participacion"] for x in filas_m if x["tuya"])})

    # 5) productos de tus marcas: sell-out (últimas 4 semanas vs 4 anteriores), cobertura, quiebres y oportunidades.
    productos = _productos(conn, filas, maestros, es_mia, mias, h, comercios)
    return {**base, "semanas": semanas, "desde": d, "sin_datos": False, "kpis": kpis, "zonas": zonas, "serie": serie,
            "mercado": mercado, "productos": productos["filas"], "oportunidades": productos["oportunidades"],
            "promociones": _promociones(conn, maestros, es_mia, comercios, h, semanas)}


def _productos(conn, filas, maestros, es_mia, mias, h, comercios) -> dict:
    reciente = [f for f in filas if f["semana"] < 4]
    previo = [f for f in filas if 4 <= f["semana"] < 8]

    def por(filas_p, clave, filtro):
        g: dict = defaultdict(lambda: defaultdict(float))
        for f in filas_p:
            if filtro(f):
                g[clave(f)][f["org_id"]] += f["facturacion"]
        return g

    resultado = []
    for marca in sorted({maestros[m]["marca"] for m in maestros if es_mia[m]}):
        de_marca = lambda f, marca=marca: maestros[f["maestro_id"]]["marca"] == marca
        g_rec = por(reciente, lambda f: f["maestro_id"], de_marca)
        g_prev = por(previo, lambda f: f["maestro_id"], de_marca)
        ok_rec, _ = particion(g_rec)
        ok_prev, _ = particion(g_prev)
        for mid in sorted({m for m in maestros if maestros[m]["marca"] == marca}, key=lambda m: maestros[m]["nombre"]):
            fila = {"id": mid, "producto": maestros[mid]["nombre"], "marca": marca, "subcategoria": maestros[mid]["subcategoria"]}
            if mid in ok_rec:
                fila["facturacion"] = round(sum(g_rec[mid].values()), 2)
                fila["unidades"] = round(sum(f["unidades"] for f in reciente if f["maestro_id"] == mid), 1)
                if mid in ok_prev and sum(g_prev[mid].values()):
                    fila["variacion"] = fila["facturacion"] / sum(g_prev[mid].values()) - 1
            else:
                fila["reservado"] = True
            resultado.append(fila)

    # Cobertura: de los comercios que vendieron la subcategoría en las últimas 4 semanas, cuántos vendieron el producto.
    vende_sub: dict = defaultdict(set)
    vende_prod: dict = defaultdict(set)
    zona_org: dict = defaultdict(set)
    for f in reciente:
        if f["unidades"] > 0:
            vende_sub[(f["zona"], maestros[f["maestro_id"]]["subcategoria"])].add(f["org_id"])
            vende_prod[(f["zona"], f["maestro_id"])].add(f["org_id"])
            zona_org[f["zona"]].add(f["org_id"])
    minimo = config.PANEL_MIN_COMERCIOS
    for fila in resultado:
        sub = fila["subcategoria"]
        con_sub = set().union(*[v for (z, s), v in vende_sub.items() if s == sub]) if vende_sub else set()
        con_prod = set().union(*[v for (z, m), v in vende_prod.items() if m == fila["id"]]) if vende_prod else set()
        if len(con_sub) >= minimo:
            fila["cobertura"] = len(con_prod & con_sub) / len(con_sub)
            fila["comercios_categoria"] = len(con_sub)

    # Quiebres: días sin stock ÷ días con registro, en los comercios que trabajan el producto (últimas 4 semanas).
    ids = [m for m in maestros if es_mia[m]]
    quiebres = db.filas(conn, f"""
        SELECT p.maestro_id, s.org_id, count(*)::float dias, count(*) FILTER (WHERE NOT s.con_stock)::float sin
        FROM stock_diario s JOIN organizaciones o ON o.id = s.org_id JOIN productos p ON p.id = s.producto_id
        JOIN ubicaciones u ON u.id = s.ubicacion_id
        WHERE {COMERCIOS} AND u.tipo <> 'deposito' AND s.fecha > %s AND s.fecha <= %s AND p.maestro_id = ANY(%s) AND s.org_id = ANY(%s)
        GROUP BY 1, 2""", (h - timedelta(days=28), h, ids, list(comercios)))
    q: dict = defaultdict(dict)
    for f in quiebres:
        q[f["maestro_id"]][f["org_id"]] = (f["dias"], f["sin"])
    for fila in resultado:
        datos = q.get(fila["id"], {})
        if pasa({o: dias for o, (dias, _s) in datos.items()}):
            fila["quiebres"] = sum(s for _d, s in datos.values()) / sum(dd for dd, _s in datos.values())
            fila["comercios_con_quiebre"] = len([1 for _d, s in datos.values() if s > 0])

    # Oportunidades: en cada zona, comercios que venden la subcategoría pero no el producto (solo cantidades).
    oportunidades = []
    for fila in resultado:
        for zona, orgs in zona_org.items():
            con_sub = vende_sub.get((zona, fila["subcategoria"]), set())
            if len(con_sub) < minimo:
                continue
            sin = con_sub - vende_prod.get((zona, fila["id"]), set())
            if not sin:
                continue
            op = {"zona": zona, "producto": fila["producto"], "marca": fila["marca"], "comercios_sin": len(sin), "comercios_categoria": len(con_sub)}
            vendedores = vende_prod.get((zona, fila["id"]), set())
            g = defaultdict(float)
            for f in reciente:
                if f["zona"] == zona and f["maestro_id"] == fila["id"]:
                    g[f["org_id"]] += f["facturacion"]
            if pasa(g):   # potencial solo con un promedio que no identifique a nadie
                op["potencial_4s"] = round(sum(g.values()) / len(vendedores) * len(sin), 2)
            oportunidades.append(op)
    oportunidades.sort(key=lambda o: (-(o.get("potencial_4s") or 0), -o["comercios_sin"]))
    return {"filas": resultado, "oportunidades": oportunidades[:30]}


def _promociones(conn, maestros, es_mia, comercios, h, semanas) -> list[dict]:
    """Efectividad de promociones sobre tus productos: venta diaria durante la promoción vs las 4 semanas previas, por producto."""
    ids = [m for m in maestros if es_mia[m]]
    filas = db.filas(conn, f"""
        WITH pr AS (
            SELECT pr.org_id, pr.id, p.id producto_id, p.maestro_id, pr.desde, least(pr.hasta, %(h)s) hasta
            FROM promociones pr JOIN organizaciones o ON o.id = pr.org_id
            JOIN productos p ON p.id = ANY(pr.productos) AND p.org_id = pr.org_id
            WHERE {COMERCIOS} AND pr.estado IN ('activa', 'finalizada') AND pr.desde <= %(h)s AND pr.hasta >= %(h)s - 7 * %(s)s
              AND p.maestro_id = ANY(%(ids)s) AND pr.org_id = ANY(%(orgs)s))
        SELECT pr.org_id, pr.maestro_id, pr.desde, pr.hasta,
               (SELECT coalesce(sum(a.unidades), 0)::float FROM agg_producto_ubicacion_dia a
                WHERE a.producto_id = pr.producto_id AND a.fecha BETWEEN pr.desde AND pr.hasta) / (pr.hasta - pr.desde + 1) durante,
               (SELECT coalesce(sum(a.unidades), 0)::float FROM agg_producto_ubicacion_dia a
                WHERE a.producto_id = pr.producto_id AND a.fecha BETWEEN pr.desde - 28 AND pr.desde - 1) / 28 antes
        FROM pr""", {"h": h, "s": semanas, "ids": ids, "orgs": list(comercios)})
    por: dict = defaultdict(list)
    for f in filas:
        if f["antes"] > 0:
            por[f["maestro_id"]].append(f)
    resultado = []
    for mid, lista in por.items():
        peso = defaultdict(float)
        for f in lista:
            peso[f["org_id"]] += f["antes"]
        if not pasa(peso):
            continue
        antes, durante = sum(f["antes"] for f in lista), sum(f["durante"] for f in lista)
        resultado.append({"producto": maestros[mid]["nombre"], "marca": maestros[mid]["marca"], "comercios": len(peso),
                          "desde": min(f["desde"] for f in lista), "hasta": max(f["hasta"] for f in lista),
                          "diaria_antes": round(antes, 1), "diaria_durante": round(durante, 1), "incremento": durante / antes - 1})
    resultado.sort(key=lambda x: -x["incremento"])
    return resultado


@api.get("/panel")
def panel(semanas: int = 12, ctx: db.Contexto = Depends(sesiones.contexto)):
    org, marcas = _marcas(ctx)
    with db.transaccion(ctx, superadmin=True) as conn:
        datos = calcular(conn, marcas, semanas)
    return respuesta({**datos, "distribuidor": org["nombre"]})


# --- portal de pedidos ---------------------------------------------------------------------------

def _cuit(texto: str | None) -> str:
    return "".join(c for c in (texto or "") if c.isdigit())


def _pedidos(conn, cuit: str, dias: int, orden_id: int | None = None) -> list[dict]:
    return db.filas(conn, """
        SELECT oc.id, oc.numero, oc.estado, oc.total, oc.fecha_esperada, oc.enviada_at, oc.confirmada_proveedor_at, oc.entrega_prometida,
               oc.nota_proveedor, o.nombre comercio, u.nombre sucursal, u.direccion, u.localidad,
               (SELECT json_agg(json_build_object('producto', p.nombre, 'ean', p.ean, 'codigo', pp.codigo_proveedor, 'cantidad', l.cantidad,
                                                  'bultos', l.bultos, 'costo', l.costo) ORDER BY p.nombre)
                FROM ordenes_compra_lineas l JOIN productos p ON p.id = l.producto_id
                LEFT JOIN producto_proveedores pp ON pp.producto_id = l.producto_id AND pp.proveedor_id = oc.proveedor_id
                WHERE l.orden_id = oc.id) lineas
        FROM ordenes_compra oc JOIN proveedores pr ON pr.id = oc.proveedor_id JOIN organizaciones o ON o.id = oc.org_id
        LEFT JOIN ubicaciones u ON u.id = oc.ubicacion_id
        WHERE regexp_replace(coalesce(pr.cuit, ''), '\\D', '', 'g') = %(cuit)s AND oc.enviada_at IS NOT NULL
          AND oc.estado IN ('enviada', 'recibida_parcial', 'recibida') AND oc.enviada_at > now() - make_interval(days => %(dias)s)
          AND (%(id)s::bigint IS NULL OR oc.id = %(id)s)
        ORDER BY oc.estado <> 'enviada', oc.enviada_at DESC""", {"cuit": cuit, "dias": dias, "id": orden_id})


@api.get("/panel/pedidos")
def pedidos(dias: int = 60, ctx: db.Contexto = Depends(sesiones.contexto)):
    org, _ = _marcas(ctx)
    cuit = _cuit(org["cuit"])
    if len(cuit) != 11:
        return respuesta({"pedidos": [], "motivo": "Cargá el CUIT de la distribuidora para recibir los pedidos de tus clientes."})
    with db.transaccion(ctx, superadmin=True) as conn:
        return respuesta({"pedidos": _pedidos(conn, cuit, max(1, min(dias, 365)))})


class Confirmacion(BaseModel):
    entrega_prometida: date | None = None
    nota: str | None = Field(default=None, max_length=300)


@api.post("/panel/pedidos/{orden_id}/confirmar")
def confirmar(orden_id: int, datos: Confirmacion, ctx: db.Contexto = Depends(sesiones.contexto)):
    org, _ = _marcas(ctx)
    cuit = _cuit(org["cuit"])
    with db.transaccion(ctx, superadmin=True) as conn:
        pedido = _pedidos(conn, cuit, 365, orden_id) if len(cuit) == 11 else []
        if not pedido:
            raise HTTPException(status_code=404, detail="Ese pedido no existe o no te lo enviaron a vos.")
        if pedido[0]["estado"] != "enviada":
            raise HTTPException(status_code=409, detail="El pedido ya se recibió.")
        if datos.entrega_prometida and datos.entrega_prometida < datetime.now().date():
            raise HTTPException(status_code=400, detail="La fecha de entrega no puede ser anterior a hoy.")
        with conn.cursor() as cur:
            cur.execute("UPDATE ordenes_compra SET confirmada_proveedor_at=now(), entrega_prometida=%s, nota_proveedor=%s, updated_at=now() "
                        "WHERE id=%s RETURNING org_id", (datos.entrega_prometida, (datos.nota or "").strip() or None, orden_id))
            destino = cur.fetchone()["org_id"]
        detalle = {"distribuidor": org["nombre"], "entrega_prometida": str(datos.entrega_prometida) if datos.entrega_prometida else None}
        sesiones.auditar(conn, destino, ctx.usuario_id, "confirmar_proveedor", "orden_compra", orden_id, detalle)
        sesiones.auditar(conn, ctx, ctx.usuario_id, "confirmar_pedido", "orden_compra", orden_id, detalle)
        return respuesta(_pedidos(conn, cuit, 365, orden_id)[0])


# --- alta por la administración de la plataforma --------------------------------------------------

class Distribuidor(BaseModel):
    marcas: list[str] = Field(max_length=200)


@api.put("/plataforma/empresas/{org_id}/distribuidor")
def configurar_distribuidor(org_id: int, datos: Distribuidor, ctx: db.Contexto = Depends(sesiones.contexto)):
    """La plataforma (no el distribuidor) define qué marcas representa: así nadie ve datos de marcas ajenas.
    Convierte la empresa en distribuidora; sus usuarios pasan a tener el rol «distribuidor»."""
    if not ctx.es_superadmin:
        raise HTTPException(status_code=403, detail="Solo para la administración de la plataforma.")
    marcas = sorted({m.strip() for m in datos.marcas if m.strip()})
    with db.transaccion(ctx, superadmin=True) as conn:
        org = db.fila(conn, "SELECT id, tipo FROM organizaciones WHERE id=%s", (org_id,))
        if not org:
            raise HTTPException(status_code=404, detail="No existe esa empresa.")
        if org["tipo"] != "distribuidor" and db.fila(conn, "SELECT 1 FROM productos WHERE org_id=%s LIMIT 1", (org_id,)):
            raise HTTPException(status_code=409, detail="Esa empresa ya tiene datos de comercio: creá una empresa aparte para el distribuidor.")
        with conn.cursor() as cur:
            cur.execute("UPDATE organizaciones SET tipo='distribuidor', consentimiento_datos=false, updated_at=now() WHERE id=%s", (org_id,))
            cur.execute("UPDATE usuarios SET rol='distribuidor' WHERE org_id=%s", (org_id,))
            cur.execute("DELETE FROM marcas_distribuidor WHERE org_id=%s", (org_id,))
            for m in marcas:
                cur.execute("INSERT INTO marcas_distribuidor (org_id, marca, created_by) VALUES (%s,%s,%s)", (org_id, m, ctx.usuario_id))
        sesiones.auditar(conn, org_id, ctx.usuario_id, "configurar", "distribuidor", org_id, {"marcas": marcas})
    return respuesta({"org_id": org_id, "marcas": marcas})
