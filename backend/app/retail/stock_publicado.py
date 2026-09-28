"""Stock publicado en las tiendas online (sección 12, fase 3), con aprobación humana.

La «sincronización automática» del documento choca con la regla 4 de CLAUDE.md (ninguna comunicación externa sale sin que la
confirme una persona). Por eso el sistema propone y la persona aprueba:
1. proponer(): después de cada sincronización (y cada hora) compara lo publicado con lo disponible en la sucursal que despacha
   (stock − reservado por pedidos online − stock de seguridad online) y deja una propuesta por publicación:
   - «sobreventa»: publicás más de lo que tenés → bajar al disponible;
   - «falta_publicar»: publicás 0 y tenés stock → subir al disponible.
   Si ya había una propuesta pendiente para esa publicación, se reemplaza por la nueva.
2. aplicar(): solo con las propuestas que una persona eligió. Recalcula el disponible en ese momento, escribe en la plataforma
   (el único pedido de escritura de los conectores) y guarda quién lo aprobó y qué respondió la plataforma. Cada propuesta va en
   su propia transacción: si una plataforma falla, las demás siguen.
En la demo (plataformas sin claves marcadas «demo») no sale nada: se actualiza el valor local y queda dicho en la respuesta.
"""
from __future__ import annotations

import math
from decimal import Decimal

from . import cifrado, db, plataformas_online
from .api_plata import parametro


def _disponible(stock, reservado, seguridad) -> int:
    return max(0, math.floor(Decimal(stock or 0) - Decimal(reservado or 0) - seguridad))


def _candidatas(conn, plataforma_id: int | None = None, publicaciones: list[int] | None = None) -> list[dict]:
    return db.filas(conn, """
        SELECT pb.id, pb.org_id, pb.plataforma_id, pb.producto_id, pb.id_externo, pb.id_padre, pb.stock_publicado, pl.ubicacion_despacho_id,
               pl.tipo, pl.config, pl.credenciales_cifradas IS NOT NULL tiene_clave,
               coalesce(s.cantidad, 0) stock, coalesce(s.reservado, 0) reservado
        FROM publicaciones pb JOIN plataformas pl ON pl.id = pb.plataforma_id
        LEFT JOIN stock_actual s ON s.producto_id = pb.producto_id AND s.ubicacion_id = pl.ubicacion_despacho_id
        WHERE pb.org_id = app_org() AND pb.activa AND pl.activa AND pb.producto_id IS NOT NULL AND pl.ubicacion_despacho_id IS NOT NULL AND pl.tipo = ANY(%(tipos)s)
          AND (%(pl)s::bigint IS NULL OR pb.plataforma_id = %(pl)s) AND (%(pubs)s::bigint[] IS NULL OR pb.id = ANY(%(pubs)s))""",
                    {"tipos": list(plataformas_online.TIENDAS), "pl": plataforma_id, "pubs": publicaciones})


def proponer(conn, plataforma_id: int | None = None) -> dict:
    seguridad = Decimal(str(parametro(conn, "stock_seguridad_online") or 0))
    nuevas = 0
    vigentes = set()
    with conn.cursor() as cur:
        for f in _candidatas(conn, plataforma_id):
            objetivo = _disponible(f["stock"], f["reservado"], seguridad)
            publicado = Decimal(f["stock_publicado"] or 0)
            motivo = "sobreventa" if publicado > objetivo else "falta_publicar" if publicado == 0 and objetivo >= 1 else None
            if not motivo:
                continue
            vigentes.add(f["id"])
            actual = db.fila(conn, "SELECT id, stock_propuesto, stock_publicado FROM propuestas_stock WHERE publicacion_id=%s AND estado='pendiente'", (f["id"],))
            if actual and actual["stock_propuesto"] == objetivo and actual["stock_publicado"] == publicado:
                continue
            if actual:
                cur.execute("UPDATE propuestas_stock SET estado='reemplazada', resuelta_at=now() WHERE id=%s", (actual["id"],))
            cur.execute("""INSERT INTO propuestas_stock (org_id, publicacion_id, plataforma_id, ubicacion_id, producto_id, stock_publicado, disponible,
                                                         stock_propuesto, motivo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (f["org_id"], f["id"], f["plataforma_id"], f["ubicacion_despacho_id"], f["producto_id"], publicado,
                         Decimal(f["stock"] or 0) - Decimal(f["reservado"] or 0), objetivo, motivo))
            nuevas += 1
        # Las que ya no hacen falta (se vendió, se repuso o alguien lo corrigió en la plataforma) dejan de estar pendientes.
        cur.execute("""UPDATE propuestas_stock SET estado='reemplazada', resuelta_at=now(), respuesta='Ya no hacía falta'
                       WHERE org_id = app_org() AND estado='pendiente' AND (%(pl)s::bigint IS NULL OR plataforma_id=%(pl)s) AND NOT (publicacion_id = ANY(%(v)s))""",
                    {"pl": plataforma_id, "v": list(vigentes)})
    return {"nuevas": nuevas, "pendientes": len(vigentes)}


def listar(conn) -> list[dict]:
    return db.filas(conn, """
        SELECT ps.id, ps.motivo, ps.stock_publicado, ps.disponible, ps.stock_propuesto, ps.created_at, pl.nombre plataforma, pl.tipo,
               p.nombre, p.codigo_interno, u.nombre ubicacion, pb.precio, pb.titulo,
               (pl.credenciales_cifradas IS NOT NULL OR coalesce((pl.config->>'demo')::boolean, false)) se_puede_enviar
        FROM propuestas_stock ps JOIN plataformas pl ON pl.id = ps.plataforma_id JOIN productos p ON p.id = ps.producto_id
        JOIN ubicaciones u ON u.id = ps.ubicacion_id JOIN publicaciones pb ON pb.id = ps.publicacion_id
        WHERE ps.estado = 'pendiente'
        ORDER BY ps.motivo = 'sobreventa' DESC, (ps.stock_publicado - ps.stock_propuesto) * coalesce(pb.precio, 0) DESC""")


def historial(conn, limite: int = 30) -> list[dict]:
    return db.filas(conn, """
        SELECT ps.id, ps.estado, ps.stock_publicado, ps.stock_propuesto, ps.resuelta_at, ps.respuesta, pl.nombre plataforma, p.nombre,
               us.nombre resuelta_por
        FROM propuestas_stock ps JOIN plataformas pl ON pl.id = ps.plataforma_id JOIN productos p ON p.id = ps.producto_id
        LEFT JOIN usuarios us ON us.id = ps.resuelta_por
        WHERE ps.estado IN ('aplicada', 'error', 'descartada') ORDER BY ps.resuelta_at DESC LIMIT %s""", (limite,))


def descartar(conn, ctx, ids: list[int]) -> int:
    with conn.cursor() as cur:
        cur.execute("UPDATE propuestas_stock SET estado='descartada', resuelta_por=%s, resuelta_at=now() WHERE estado='pendiente' AND id = ANY(%s)",
                    (ctx.usuario_id, ids))
        return cur.rowcount


def aplicar(ctx, ids: list[int], transporte=None, enviador=None) -> list[dict]:
    """La persona aprobó estas propuestas: se escriben en cada plataforma, una por una."""
    from . import sesiones
    resultados = []
    clientes: dict = {}
    for pid in ids:
        with db.transaccion(ctx) as conn:
            prop = db.fila(conn, "SELECT * FROM propuestas_stock WHERE id=%s AND estado='pendiente' FOR UPDATE", (pid,))
            if not prop:
                resultados.append({"id": pid, "estado": "omitida", "mensaje": "Ya no está pendiente."})
                continue
            f = _candidatas(conn, publicaciones=[prop["publicacion_id"]])
            seguridad = Decimal(str(parametro(conn, "stock_seguridad_online") or 0))
            estado, mensaje, cantidad = "error", "", None
            if not f:
                mensaje = "La publicación o la conexión ya no está activa."
            else:
                f = f[0]
                cantidad = _disponible(f["stock"], f["reservado"], seguridad)     # el disponible de ahora, no el de la propuesta
                demo = bool((f["config"] or {}).get("demo")) and not f["tiene_clave"]
                try:
                    if demo:
                        mensaje = "Demo: no se envió a ninguna plataforma; se actualizó el valor local."
                    elif not f["tiene_clave"]:
                        raise plataformas_online.ErrorPlataforma("La plataforma no está conectada (sin claves).")
                    else:
                        if f["plataforma_id"] not in clientes:
                            p = db.fila(conn, "SELECT config, credenciales_cifradas FROM plataformas WHERE id=%s", (f["plataforma_id"],))
                            clientes[f["plataforma_id"]] = plataformas_online.cliente_de(
                                f["tipo"], p["config"] or {}, cifrado.descifrar(p["credenciales_cifradas"]), transporte, enviador)
                        clientes[f["plataforma_id"]].actualizar_stock({"id_externo": f["id_externo"], "id_padre": f["id_padre"]}, cantidad)
                        mensaje = f"La plataforma aceptó el stock {cantidad}."
                    estado = "aplicada"
                except plataformas_online.ErrorPlataforma as e:
                    mensaje = str(e)
                except OSError as e:
                    mensaje = f"No se pudo conectar con la plataforma ({e})."
            with conn.cursor() as cur:
                cur.execute("UPDATE propuestas_stock SET estado=%s, resuelta_por=%s, resuelta_at=now(), respuesta=%s WHERE id=%s",
                            (estado, ctx.usuario_id, mensaje[:500], pid))
                if estado == "aplicada":
                    cur.execute("UPDATE publicaciones SET stock_publicado=%s, actualizado_at=now() WHERE id=%s", (cantidad, prop["publicacion_id"]))
            sesiones.auditar(conn, ctx, ctx.usuario_id, "actualizar_stock_publicado", "publicacion", prop["publicacion_id"],
                             {"propuesta": pid, "de": str(prop["stock_publicado"]), "a": cantidad, "estado": estado, "respuesta": mensaje[:200]})
            resultados.append({"id": pid, "estado": estado, "mensaje": mensaje, "cantidad": cantidad})
    return resultados
