"""Qué puede hacer cada rol de Retail y cuánto puede aprobar.

- El alcance por sucursal lo aplica la base (RLS). Acá se decide qué acciones habilita cada rol.
- Límites de monto: primero el límite propio del usuario, si no el de su rol. Sin límite cargado,
  un comprador, encargado o cajero no puede aprobar (0): la aprobación sube al dueño.
  El dueño aprueba cualquier monto (sección 2: "aprueba OC por encima de los límites").
"""
from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException

from . import db

PERMISOS: dict[str, set[str]] = {
    "dueno": {"ver_todas_ubicaciones", "configurar_empresa", "gestionar_ubicaciones", "gestionar_usuarios",
              "ver_auditoria", "gestionar_proveedores", "crear_oc", "aprobar_oc", "aprobar_transferencias",
              "recepciones", "recuentos", "remarcar", "ver_costos", "ver_ventas", "importar_datos", "gestionar_conexiones"},
    "comprador": {"ver_todas_ubicaciones", "gestionar_proveedores", "crear_oc", "aprobar_oc", "remarcar",
                  "ver_costos", "ver_ventas", "importar_datos"},
    "encargado": {"aprobar_transferencias", "recepciones", "recuentos", "ver_costos", "ver_ventas"},
    "cajero": {"recepciones", "recuentos"},
    "distribuidor": {"panel_marcas"},   # solo el panel agregado y anónimo y los pedidos que le envían (13.3)
}

TIPOS_DOCUMENTO = ("orden_compra", "transferencia", "ajuste_stock", "precio")
PERMISO_APROBAR = {"orden_compra": "aprobar_oc", "transferencia": "aprobar_transferencias",
                   "ajuste_stock": "recuentos", "precio": "remarcar"}


def permisos_de(ctx: db.Contexto) -> set[str]:
    if ctx.es_superadmin and ctx.org_id:
        return PERMISOS["dueno"] | {"panel_marcas"}   # el superadmin dentro de una empresa actúa con todo el alcance
    return PERMISOS.get(ctx.rol or "", set())


def puede(ctx: db.Contexto, permiso: str) -> bool:
    return permiso in permisos_de(ctx)


def exigir(ctx: db.Contexto, permiso: str) -> None:
    if not ctx.org_id:
        raise HTTPException(status_code=409, detail="Elegí una empresa para trabajar.")
    if not puede(ctx, permiso):
        raise HTTPException(status_code=403, detail="Tu rol no tiene permiso para esta acción.")


def limite_aprobacion(conn, ctx: db.Contexto, tipo_documento: str) -> Decimal | None:
    """Monto máximo que este usuario puede aprobar. None = sin límite."""
    if ctx.es_superadmin or ctx.rol == "dueno":
        return None
    if not puede(ctx, PERMISO_APROBAR[tipo_documento]):
        return Decimal("0")
    propio = db.fila(conn, "SELECT monto_maximo FROM limites_aprobacion WHERE tipo_documento=%s AND usuario_id=%s",
                     (tipo_documento, ctx.usuario_id))
    if propio:
        return propio["monto_maximo"]
    del_rol = db.fila(conn, "SELECT monto_maximo FROM limites_aprobacion WHERE tipo_documento=%s AND rol=%s",
                      (tipo_documento, ctx.rol))
    return del_rol["monto_maximo"] if del_rol else Decimal("0")


def puede_aprobar(conn, ctx: db.Contexto, tipo_documento: str, monto: Decimal) -> bool:
    limite = limite_aprobacion(conn, ctx, tipo_documento)
    return limite is None or Decimal(monto) <= limite
