"""Empresas de demostración de Retail (parte 1: estructura y usuarios; la parte 2 agrega catálogo y ventas).

Uso: python -m app.retail.semilla   (migra la base y carga la demo solo si no hay empresas)

Claves de ejemplo: todas las cuentas demo usan CLAVE_DEMO. Cambialas antes de usar la plataforma con datos reales.
"""
from __future__ import annotations

import json

from . import db, seguridad
from .rutas import EmpresaNueva, crear_empresa

CLAVE_DEMO = "demo-retail-2026"
SUPERADMIN = ("admin@plataforma.demo", "Administración de la plataforma")

NORTE = {
    "empresa": EmpresaNueva(nombre="Autoservicios del Norte", cuit="30-71234567-8", modelo_abastecimiento="mixto",
                            email_dueno="dueno@norte.demo", nombre_dueno="Marta Quispe"),
    "ubicaciones": [
        ("Salta Centro", "venta", "Av. Belgrano 850", "Salta"),
        ("Salta Norte", "venta", "Av. Bolivia 4200", "Salta"),
        ("San Salvador de Jujuy", "venta", "Belgrano 1100", "San Salvador de Jujuy"),
        ("Depósito Salta", "deposito", "Parque Industrial, lote 14", "Salta"),
    ],
    "usuarios": [
        ("compras@norte.demo", "Diego Mamaní", "comprador", []),
        ("encargado.norte@norte.demo", "Lucía Cruz", "encargado", ["Salta Norte"]),
        ("encargado.jujuy@norte.demo", "Ramón Tolaba", "encargado", ["San Salvador de Jujuy"]),
        ("caja.centro@norte.demo", "Sofía Guitián", "cajero", ["Salta Centro"]),
    ],
    "limites": [("orden_compra", "comprador", "500000.00"), ("transferencia", "encargado", "300000.00")],
}
ESQUINA = {
    "empresa": EmpresaNueva(nombre="Minimercado La Esquina", cuit="20-28765432-1", modelo_abastecimiento="descentralizado",
                            email_dueno="dueno@esquina.demo", nombre_dueno="Jorge Paz"),
    "ubicaciones": [("La Esquina — Yerba Buena", "ambos", "Av. Aconquija 1500", "Yerba Buena")],
    "usuarios": [],
    "limites": [],
}
HORARIO = {"lunes_a_sabado": "08:00-21:30", "domingo": "09:00-13:00"}


def _cargar_empresa(conn, datos: dict) -> int:
    org, _ = crear_empresa(conn, datos["empresa"], None)
    org_id = org["id"]
    with conn.cursor() as cur:        # demostración: plan completo, sin vencimiento
        cur.execute("UPDATE organizaciones SET plan='cadena', pagado_hasta='2099-12-31' WHERE id=%s", (org_id,))
    ids = {}
    with conn.cursor() as cur:
        cur.execute("UPDATE usuarios SET hash_clave=%s WHERE org_id=%s", (seguridad.hash_clave(CLAVE_DEMO), org_id))
        for nombre, tipo, direccion, localidad in datos["ubicaciones"]:
            cur.execute("INSERT INTO ubicaciones (org_id, nombre, tipo, direccion, localidad, horarios) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                        (org_id, nombre, tipo, direccion, localidad, json.dumps(HORARIO)))
            ids[nombre] = cur.fetchone()["id"]
        for email, nombre, rol, sucursales in datos["usuarios"]:
            cur.execute("INSERT INTO usuarios (org_id, email, nombre, rol, hash_clave) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                        (org_id, email, nombre, rol, seguridad.hash_clave(CLAVE_DEMO)))
            uid = cur.fetchone()["id"]
            for s in sucursales:
                cur.execute("INSERT INTO usuario_ubicaciones (org_id, usuario_id, ubicacion_id) VALUES (%s,%s,%s)", (org_id, uid, ids[s]))
        for tipo, rol, monto in datos["limites"]:
            cur.execute("INSERT INTO limites_aprobacion (org_id, tipo_documento, rol, monto_maximo) VALUES (%s,%s,%s,%s)",
                        (org_id, tipo, rol, monto))
    return org_id


def cargar(forzar: bool = False) -> bool:
    """Carga la demo si la base no tiene empresas. Devuelve True si cargó."""
    db.migrar()
    with db.transaccion(superadmin=True) as conn:
        if not forzar and db.fila(conn, "SELECT 1 FROM organizaciones LIMIT 1"):
            return False
        with conn.cursor() as cur:
            cur.execute("INSERT INTO usuarios (email, nombre, es_superadmin, hash_clave) VALUES (%s,%s,true,%s) ON CONFLICT DO NOTHING",
                        (SUPERADMIN[0], SUPERADMIN[1], seguridad.hash_clave(CLAVE_DEMO)))
        _cargar_empresa(conn, NORTE)
        _cargar_empresa(conn, ESQUINA)
    return True


if __name__ == "__main__":
    from .. import config  # noqa: F401  (carga backend/.env)
    if cargar():
        print(f"Retail: empresas de demostración cargadas. Clave de todas las cuentas demo: {CLAVE_DEMO}")
    else:
        print("Retail: la base ya tiene empresas; no se cargó la demo.")
