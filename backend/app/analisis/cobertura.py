"""Cobertura de datos: qué trajo la integración activa y qué falta, tabla por tabla.

Sirve para detectar errores al integrar cualquier sistema: tablas vacías,
campos que no vienen, referencias que no cruzan (ventas de clientes que no
existen, etc.). Es de uso interno (no aplica rol): lo ve quien administra.
"""
from __future__ import annotations

from ..erp import conector, modelo
from ..erp.importar import PRINCIPALES, _REFERENCIAS


def _esquema() -> dict[str, list[str]]:
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.executescript(modelo.ESQUEMA)
    tablas = {t: [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
              for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    con.close()
    return tablas


def _tabla(tabla: str, columnas: list[str]) -> dict:
    conteos = ", ".join(f"COUNT({c})" for c in columnas)
    try:
        fila = conector.consultar(f"SELECT COUNT(*), {conteos} FROM {tabla}", max_filas=1)["filas"][0]
    except Exception as e:  # la tabla no existe en esta fuente (por ejemplo, la base de un ERP sin adaptar)
        return {"tabla": tabla, "existe": False, "filas": 0, "estado": "vacia", "error": str(e).splitlines()[0][:160],
                "campos_completos": 0, "campos_total": len(columnas), "campos_vacios": columnas, "campos_parciales": []}
    filas = fila[0] or 0
    llenos = dict(zip(columnas, fila[1:]))
    vacios = [c for c in columnas if not llenos[c]]
    parciales = [{"campo": c, "pct": round(llenos[c] / filas, 3)} for c in columnas if filas and 0 < llenos[c] < filas]
    minimos = modelo.MINIMOS.get(tabla, [])
    if not filas:
        estado = "vacia"
    elif any(c in vacios for c in minimos) or len(vacios) > len(columnas) / 2:
        estado = "parcial"
    else:
        estado = "completa" if not vacios else "buena"
    return {"tabla": tabla, "existe": True, "filas": filas, "estado": estado, "campos_total": len(columnas),
            "campos_completos": len(columnas) - len(vacios), "campos_vacios": vacios, "campos_parciales": parciales}


def _controles(tablas: dict[str, dict]) -> list[dict]:
    avisos = []
    for tabla, columna, destino, texto in _REFERENCIAS:
        if not tablas[tabla]["filas"] or not tablas[destino]["filas"]:
            continue
        try:
            n = conector.consultar(f"SELECT COUNT(*) FROM {tabla} WHERE {columna} IS NOT NULL AND {columna} NOT IN "
                                   f"(SELECT id FROM {destino})", max_filas=1)["filas"][0][0]
        except Exception:
            continue
        if n:
            avisos.append({"nivel": "alerta", "texto": f"{n} {texto}."})
    if tablas["clientes"]["filas"]:
        n = conector.consultar("SELECT COUNT(*) FROM clientes WHERE vendedor_id IS NULL", max_filas=1)["filas"][0][0]
        if n:
            avisos.append({"nivel": "alerta", "texto": f"{n} clientes sin vendedor asignado: ningún vendedor los ve en su cartera."})
    if tablas["ventas_lineas"]["filas"]:
        n = conector.consultar("SELECT COUNT(*) FROM ventas_lineas WHERE costo_unitario IS NULL OR costo_unitario = 0",
                               max_filas=1)["filas"][0][0]
        if n:
            avisos.append({"nivel": "alerta", "texto": f"{n} líneas de venta sin costo: el margen de esas ventas sale inflado."})
        n = conector.consultar("SELECT COUNT(*) FROM ventas_lineas WHERE cantidad < 0 OR precio_unitario < 0", max_filas=1)["filas"][0][0]
        if n:
            avisos.append({"nivel": "alerta", "texto": f"{n} líneas de venta con cantidad o precio negativo (¿devoluciones dentro de ventas?)."})
    for tabla in PRINCIPALES:
        if not tablas[tabla]["filas"]:
            avisos.append({"nivel": "error", "texto": f"Sin datos de {tabla}: los indicadores que la usan no se pueden calcular."})
    return avisos


def cobertura() -> dict:
    esquema = _esquema()
    tablas = {t: _tabla(t, columnas) for t, columnas in esquema.items()}
    pilares = []
    for pilar, nombres in modelo.PILARES.items():
        filas = [tablas[t] for t in nombres]
        con_datos = sum(1 for f in filas if f["filas"])
        pilares.append({"pilar": pilar, "tablas": filas, "con_datos": con_datos, "total": len(filas),
                        "campos_completos": sum(f["campos_completos"] for f in filas if f["filas"]),
                        "campos_total": sum(f["campos_total"] for f in filas)})
    return {"pilares": pilares, "controles": _controles(tablas)}
