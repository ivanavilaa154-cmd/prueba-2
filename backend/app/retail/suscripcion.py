"""Planes y suscripción (sección 13.6).

- Cada empresa tiene un plan (organizaciones.plan) que limita las sucursales de venta y los módulos:
  base (Fase 1: comprar y reponer, transferencias y OC, precios, ventas, caja, avisos, datos),
  avanzado (Fase 2: plata parada, vencimientos, sucursales, proveedores, canales, copiloto, impacto),
  completo (Fase 3: canasta, promociones, sensibilidad, surtido y clientes).
- Período de prueba de 30 días con todo incluido. La cuenta está al día si la prueba o lo pagado no venció.
- Vencida: queda en solo lectura (se ve todo, se puede exportar y pagar, pero no se modifica nada). Nunca se borran datos.
- Los pagos los registra la administración de la plataforma (transferencia, Mercado Pago, etc.). El cobro automático con
  Mercado Pago necesita la cuenta de la plataforma y la decisión de precios: queda para cuando estén.
"""
from __future__ import annotations

from datetime import date

from fastapi import Depends, HTTPException, Request

from . import db

MODULOS = {"base": "Operación diaria", "avanzado": "Gestión avanzada", "completo": "Análisis avanzado"}
AVISO_DIAS = 7
# Rutas que se pueden usar con la suscripción vencida (además de todas las de lectura).
LIBRES_VENCIDA = ("/retail/api/sesion", "/retail/api/yo", "/retail/api/privacidad", "/retail/api/empresa/baja", "/retail/api/plataforma")


def estado(conn, org_id: int, hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    o = db.fila(conn, """SELECT o.plan, o.prueba_hasta, o.pagado_hasta, p.nombre, p.max_sucursales, p.modulos, p.precio_mensual
                         FROM organizaciones o LEFT JOIN planes p ON p.codigo = o.plan WHERE o.id=%s""", (org_id,))
    if not o:
        return {"al_dia": True, "modulos": list(MODULOS)}
    # Al día si no venció lo pagado o, mientras dure, el período de prueba (aunque ya se haya elegido un plan pago).
    pagado = o["pagado_hasta"] is not None and o["pagado_hasta"] >= hoy
    en_prueba = not pagado and o["prueba_hasta"] is not None and o["prueba_hasta"] >= hoy
    hasta = max([d for d in (o["prueba_hasta"], o["pagado_hasta"]) if d], default=None)
    al_dia = bool(hasta and hasta >= hoy)
    sucursales = db.fila(conn, "SELECT count(*) n FROM ubicaciones WHERE org_id=%s AND activa AND tipo <> 'deposito'", (org_id,))["n"]
    return {"plan": o["plan"], "plan_nombre": o["nombre"] or o["plan"], "en_prueba": en_prueba, "hasta": hasta, "al_dia": al_dia,
            "dias_restantes": (hasta - hoy).days if hasta else None, "por_vencer": al_dia and hasta is not None and (hasta - hoy).days <= AVISO_DIAS,
            "max_sucursales": o["max_sucursales"], "sucursales": sucursales, "modulos": list(o["modulos"] or MODULOS),
            "precio_mensual": o["precio_mensual"]}


def exigir_escritura(request: Request, ctx) -> None:
    """Llamado desde sesiones.contexto: con la suscripción vencida no se modifica nada (salvo ingresar, privacidad y pagar)."""
    if request.method in ("GET", "HEAD", "OPTIONS") or ctx.es_superadmin or not ctx.org_id:
        return
    if request.url.path.startswith(LIBRES_VENCIDA):
        return
    with db.transaccion(ctx) as conn:
        e = estado(conn, ctx.org_id)
    if not e["al_dia"]:
        raise HTTPException(status_code=402, detail="La suscripción venció: la cuenta quedó en solo lectura (tus datos están intactos). "
                                                    "Regularizá el pago para volver a operar.")


def modulo(nombre: str):
    """Dependencia de los routers de cada módulo: si el plan no lo incluye, 403 con un mensaje claro."""
    from . import sesiones

    def verificar(ctx=Depends(sesiones.contexto)):
        if ctx.es_superadmin or not ctx.org_id:
            return
        with db.transaccion(ctx) as conn:
            e = estado(conn, ctx.org_id)
        if nombre not in e["modulos"]:
            raise HTTPException(status_code=403, detail=f"Tu plan ({e['plan_nombre']}) no incluye «{MODULOS[nombre]}». Cambiá de plan para usarlo.")
    return verificar


def exigir_sucursal_nueva(conn, org_id: int, tipo: str) -> None:
    if tipo == "deposito":
        return
    e = estado(conn, org_id)
    if e.get("max_sucursales") is not None and e["sucursales"] >= e["max_sucursales"]:
        raise HTTPException(status_code=403, detail=f"Tu plan ({e['plan_nombre']}) permite hasta {e['max_sucursales']} sucursal(es). Cambiá de plan para sumar más.")
