"""Cuentas reales de Retail: la administración de la plataforma y el dueño de cada empresa.

Uso (en la terminal, dentro de backend/):  python -m app.retail.cuentas

Modo «solo cuentas reales» (RETAIL_CUENTAS=reales en backend/.env, lo pone el Codespace): al arrancar se crean, si no existen,
la cuenta de administración y la empresa Pulpo Azul con su dueño (claves iniciales abajo: cambialas en Mi cuenta), y se
borran las empresas y cuentas de ejemplo. Las empresas que crees vos no se tocan nunca.

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


ADMIN = ("admin@retail-ia.local", "Administración", "Admin-Retail-2026")
PULPO = {"empresa": "Pulpo Azul", "email": "dueno@pulpoazul.local", "nombre": "Dueño Pulpo Azul", "clave": "PulpoAzul-2026"}


def _empresas_demo() -> list[str]:
    from . import demo, demo_panel
    return [demo.EMPRESA, "Minimercado La Esquina", demo_panel.DISTRIBUIDOR] + [c[0] for c in demo_panel.COMERCIOS]


def borrar_empresas(conn, org_ids: list[int]) -> None:
    """Borra todo lo de esas empresas: cada tabla de empresa tiene org_id. Varias pasadas porque unas tablas dependen de otras."""
    if not org_ids:
        return
    tablas = [f["table_name"] for f in db.filas(conn, """
        SELECT c.table_name FROM information_schema.columns c JOIN information_schema.tables t USING (table_schema, table_name)
        WHERE c.table_schema = 'public' AND c.column_name = 'org_id' AND t.table_type = 'BASE TABLE' ORDER BY 1""")]
    pendientes = list(tablas)
    for _ in range(len(tablas) + 1):
        trabadas = []
        for tabla in pendientes:
            with conn.cursor() as cur:
                cur.execute("SAVEPOINT borrar")
                try:
                    cur.execute(f'DELETE FROM "{tabla}" WHERE org_id = ANY(%s)', (org_ids,))
                    cur.execute("RELEASE SAVEPOINT borrar")
                except Exception:
                    cur.execute("ROLLBACK TO SAVEPOINT borrar")
                    trabadas.append(tabla)
        if not trabadas:
            break
        pendientes = trabadas
    else:
        raise RuntimeError(f"No se pudieron borrar: {', '.join(pendientes)}")
    with conn.cursor() as cur:
        cur.execute("DELETE FROM organizaciones WHERE id = ANY(%s)", (org_ids,))


def dejar_solo_reales() -> dict:
    """Idempotente: crea lo que falte (sin tocar claves ya cambiadas) y borra lo de ejemplo."""
    resultado = {"creadas": [], "borradas": []}
    with db.transaccion(superadmin=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(4243)")
        if not db.fila(conn, "SELECT 1 FROM usuarios WHERE lower(email)=lower(%s)", (ADMIN[0],)):
            administrador(conn, *ADMIN)
            resultado["creadas"].append(ADMIN[0])
        if not db.fila(conn, "SELECT 1 FROM organizaciones WHERE lower(nombre)=lower(%s)", (PULPO["empresa"],)):
            empresa_con_dueno(conn, PULPO["empresa"], None, PULPO["email"], PULPO["nombre"], PULPO["clave"])
            resultado["creadas"].append(PULPO["email"])
        demo = db.filas(conn, "SELECT id, nombre FROM organizaciones WHERE nombre = ANY(%s)", (_empresas_demo(),))
        if demo:
            sesiones.auditar(conn, None, None, "borrar", "empresas_demo", None, {"empresas": [o["nombre"] for o in demo]})
        borrar_empresas(conn, [o["id"] for o in demo])
        resultado["borradas"] = [o["nombre"] for o in demo]
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usuarios WHERE email LIKE '%%.demo'")          # la administración de ejemplo no tiene empresa
    return resultado


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
