"""Cuentas reales de Retail: la administración de la plataforma y el dueño de cada empresa.

Uso (en la terminal, dentro de backend/):  python -m app.retail.cuentas

Pregunta todo en pantalla; las claves se escriben sin mostrarse y nunca quedan en el código ni en el repositorio.
1. Tu cuenta de administración de la plataforma (ve y administra todas las empresas). Si el email ya existe, le cambia la clave.
2. Una empresa con su dueño (ve todo, pero solo de su empresa). Por ejemplo «Pulpo Azul», que después conecta su Odoo.
3. Opcional: desactiva las cuentas de ejemplo (@*.demo) para que nadie entre con la clave de demostración.
"""
from __future__ import annotations

import getpass
import sys

from . import db, seguridad, sesiones
from .rutas import EmpresaNueva, crear_empresa


def _pedir(texto: str, defecto: str | None = None, obligatorio: bool = True) -> str:
    while True:
        valor = input(f"{texto}{f' [{defecto}]' if defecto else ''}: ").strip() or (defecto or "")
        if valor or not obligatorio:
            return valor
        print("  Este dato es obligatorio.")


def _email(texto: str) -> str:
    while True:
        valor = _pedir(texto).lower()
        if "@" in valor and "." in valor.split("@")[-1]:
            return valor
        print("  No parece un email válido.")


def _clave(texto: str) -> str:
    while True:
        clave = getpass.getpass(f"{texto} (no se ve mientras escribís): ")
        error = seguridad.validar_clave_nueva(clave)
        if error:
            print(f"  {error}")
            continue
        if getpass.getpass("Repetila: ") != clave:
            print("  No coinciden.")
            continue
        return clave


def _si(texto: str) -> bool:
    return _pedir(f"{texto} (s/n)", "n").lower().startswith("s")


def administrador(conn, email: str, nombre: str, clave: str) -> str:
    existe = db.fila(conn, "SELECT id, es_superadmin FROM usuarios WHERE lower(email)=lower(%s)", (email,))
    with conn.cursor() as cur:
        if existe and not existe["es_superadmin"]:
            raise ValueError("Ese email ya es de un usuario de una empresa: usá otro para la administración.")
        if existe:
            cur.execute("UPDATE usuarios SET hash_clave=%s, nombre=%s, activo=true, intentos_fallidos=0, bloqueado_hasta=NULL, updated_at=now() "
                        "WHERE id=%s", (seguridad.hash_clave(clave), nombre, existe["id"]))
            return "actualizada"
        cur.execute("INSERT INTO usuarios (email, nombre, es_superadmin, hash_clave) VALUES (%s,%s,true,%s)",
                    (email, nombre, seguridad.hash_clave(clave)))
        return "creada"


def empresa_con_dueno(conn, nombre: str, cuit: str | None, email: str, nombre_dueno: str, clave: str) -> int:
    if db.fila(conn, "SELECT 1 FROM organizaciones WHERE lower(nombre)=lower(%s)", (nombre,)):
        raise ValueError(f"Ya existe una empresa «{nombre}».")
    if db.fila(conn, "SELECT 1 FROM usuarios WHERE lower(email)=lower(%s)", (email,)):
        raise ValueError("Ya existe un usuario con ese email.")
    org, _temporal = crear_empresa(conn, EmpresaNueva(nombre=nombre, cuit=cuit or None, email_dueno=email, nombre_dueno=nombre_dueno), None)
    with conn.cursor() as cur:
        cur.execute("UPDATE usuarios SET hash_clave=%s WHERE org_id=%s AND lower(email)=lower(%s)", (seguridad.hash_clave(clave), org["id"], email))
    return org["id"]


def desactivar_demo(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("UPDATE usuarios SET activo=false, updated_at=now() WHERE email LIKE '%%.demo' AND activo")
        n = cur.rowcount
        cur.execute("UPDATE sesiones SET revocada=true WHERE usuario_id IN (SELECT id FROM usuarios WHERE email LIKE '%%.demo')")
    return n


def main() -> None:
    from .. import config  # noqa: F401  (carga backend/.env)
    db.migrar()
    print("\n=== 1. Tu cuenta de administración de la plataforma (ve todas las empresas) ===")
    email = _email("Tu email")
    nombre = _pedir("Tu nombre")
    clave = _clave("Tu clave (mínimo 10 caracteres, letras y números)")
    with db.transaccion(superadmin=True) as conn:
        estado = administrador(conn, email, nombre, clave)
    print(f"  ✓ Cuenta de administración {estado}: {email}")

    while _si("\n¿Crear una empresa con su dueño (por ejemplo Pulpo Azul)?"):
        print("=== 2. Empresa y dueño (ve todo, pero solo de su empresa) ===")
        nombre_emp = _pedir("Nombre de la empresa", "Pulpo Azul")
        cuit = _pedir("CUIT (opcional)", obligatorio=False)
        email_d = _email("Email del dueño")
        nombre_d = _pedir("Nombre del dueño")
        clave_d = _clave("Clave del dueño")
        try:
            with db.transaccion(superadmin=True) as conn:
                org = empresa_con_dueno(conn, nombre_emp, cuit, email_d, nombre_d, clave_d)
                sesiones.auditar(conn, org, None, "crear", "empresa", org, {"desde": "terminal"})
            print(f"  ✓ Empresa «{nombre_emp}» creada con su dueño {email_d}.")
            print("    Siguiente: entrá como dueño → Configuración → Sucursales (cargá sus locales y depósitos) → Datos → Conectar Odoo.")
        except ValueError as e:
            print(f"  ✕ {e}")

    if _si("\n¿Desactivar las cuentas de ejemplo (@*.demo)? Los datos de demostración quedan, pero nadie entra con esas cuentas"):
        with db.transaccion(superadmin=True) as conn:
            n = desactivar_demo(conn)
        print(f"  ✓ {n} cuentas de ejemplo desactivadas.")
    print("\nListo. Entrá en la dirección de la plataforma con /retail al final.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.")
        sys.exit(1)
