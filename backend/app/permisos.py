"""Usuarios, roles y control de acceso a datos.

Dos niveles, los dos se aplican en el conector antes de ejecutar:
- Tablas: cada rol solo puede consultar las tablas de su lista.
- Filas: los roles con `filtros_fila` (vendedor → su cartera) ven cada tabla
  filtrada. La consulta se reescribe reemplazando cada tabla por una subconsulta
  ya filtrada, así el modelo nunca toca la tabla original.
"""
from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from . import config


class AccesoDenegado(Exception):
    pass


@dataclass
class Usuario:
    id: str
    nombre: str
    rol: str
    vendedor_id: int | None = None

    @property
    def _rol(self) -> dict:
        return config.roles()["roles"][self.rol]

    @property
    def tablas_permitidas(self) -> set[str] | str:
        tablas = self._rol["tablas"]
        return "*" if tablas == "*" else {t.lower() for t in tablas}

    @property
    def filtros_fila(self) -> dict[str, str]:
        """Condición SQL por tabla, con {vendedor_id} ya reemplazado."""
        filtros = self._rol.get("filtros_fila") or {}
        if not filtros:
            return {}
        if self.vendedor_id is None:
            raise AccesoDenegado(f"El usuario {self.nombre} no tiene cartera asignada (falta vendedor_id).")
        vendedor_id = int(self.vendedor_id)  # entero: nunca se interpola texto libre
        return {t.lower(): c.format(vendedor_id=vendedor_id) for t, c in filtros.items()}

    def describir(self) -> str:
        texto = f"Usuario: {self.nombre}. Rol: {self.rol} ({self._rol['descripcion']})"
        if self.vendedor_id is not None:
            texto += f" Cartera: solo clientes con vendedor_id = {self.vendedor_id}."
        tablas = self.tablas_permitidas
        texto += " Tablas permitidas: " + ("todas" if tablas == "*" else ", ".join(sorted(tablas)))
        return texto


def obtener_usuario(usuario_id: str) -> Usuario:
    datos = config.roles()["usuarios"].get(usuario_id)
    if not datos:
        raise AccesoDenegado(f"Usuario desconocido: {usuario_id}")
    return Usuario(id=usuario_id, **datos)


def _analizar(sql: str, dialecto: str | None) -> exp.Expression:
    try:
        arbol = sqlglot.parse_one(sql, read=dialecto)
    except SqlglotError as e:
        raise AccesoDenegado(f"No pude interpretar la consulta para verificar permisos: {e}") from e
    if not isinstance(arbol, exp.Query):
        raise AccesoDenegado("Solo se permiten consultas SELECT.")
    return arbol


def _tablas_reales(arbol: exp.Expression) -> list[exp.Table]:
    """Referencias a tablas del ERP (no a CTE definidos en la misma consulta).

    Un CTE no puede llamarse igual que una tabla del diccionario: si no, no se
    podría distinguir la tabla real del CTE y un filtro podría esquivarse.
    """
    ctes = {c.alias_or_name.lower() for c in arbol.find_all(exp.CTE)}
    conocidas = {t.lower() for t in config.diccionario().get("tablas", {})}
    choque = ctes & conocidas
    if choque:
        raise AccesoDenegado(
            "Usá otro nombre para el CTE: " + ", ".join(sorted(choque)) + " es una tabla del ERP."
        )
    return [t for t in arbol.find_all(exp.Table) if t.name and t.name.lower() not in ctes]


def tablas_de_sql(sql: str, dialecto: str | None = None) -> set[str]:
    """Tablas del ERP que usa la consulta (FROM, JOIN, comas, subconsultas y CTE)."""
    return {t.name.lower() for t in _tablas_reales(_analizar(sql, dialecto))}


def preparar_consulta(usuario: Usuario, sql: str, dialecto: str | None = None) -> str:
    """Verifica las tablas del rol y aplica el filtro por fila. Devuelve el SQL a ejecutar."""
    permitidas = usuario.tablas_permitidas
    filtros = usuario.filtros_fila
    if permitidas == "*" and not filtros:
        return sql  # sin restricciones: se ejecuta tal cual

    arbol = _analizar(sql, dialecto)
    tablas = _tablas_reales(arbol)
    if permitidas != "*":
        prohibidas = {t.name.lower() for t in tablas} - permitidas
        if prohibidas:
            raise AccesoDenegado(
                "Ese dato no está disponible para tu perfil (tablas: " + ", ".join(sorted(prohibidas)) + ")."
            )

    for tabla in tablas:
        condicion = filtros.get(tabla.name.lower())
        if not condicion:
            continue
        alias = tabla.alias or tabla.name
        original = tabla.copy()
        original.set("alias", None)
        filtrada = (
            exp.select("*")
            .from_(original)
            .where(sqlglot.parse_one(condicion, read=dialecto))
            .subquery(alias)
        )
        tabla.replace(filtrada)
    return arbol.sql(dialect=dialecto)


def verificar_acceso(usuario: Usuario, sql: str, dialecto: str | None = None) -> None:
    """Solo verifica tablas y cartera (sin devolver el SQL reescrito)."""
    preparar_consulta(usuario, sql, dialecto)
