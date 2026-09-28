"""Tiempos de carga de cada pantalla (criterio de aceptación: menos de 3 segundos con los datos de demostración).

Cada pantalla se mide como la suma de las consultas que hace al abrirse. Se usa en las pruebas (con la demo reducida) y a
mano contra un servidor corriendo con la demo completa:

    python -m app.retail.tiempos --url http://localhost:8000 --email dueno@norte.demo --clave demo-retail-2026
"""
from __future__ import annotations

import argparse
import time
from typing import Callable

LIMITE_SEGUNDOS = 3.0
FILTRO = "periodo=mes"

PANTALLAS: dict[str, list[str]] = {
    "Inicio": ["/yo", "/inicio"],
    "Comprar y reponer": ["/comprar"],
    "Detalle de producto": ["/productos/{producto}"],
    "Transferencias y OC": ["/documentos"],
    "Ventas · ganadores": [f"/ventas/ganadores?{FILTRO}"],
    "Ventas · Pareto": ["/ventas/pareto?periodo=90d"],
    "Ventas · inflación": [f"/ventas/inflacion?{FILTRO}"],
    "Ventas · ticket y tráfico": [f"/ventas/ticket?{FILTRO}"],
    "Precios": ["/precios/remarcacion?filtro=todos"],
    "Caja y control": [f"/caja?{FILTRO}"],
    "Plata parada": ["/plata-parada", "/merma"],
    "Vencimientos y ofertas": ["/vencimientos", "/ofertas"],
    "Ventas · rentabilidad": ["/ventas/rentabilidad?nivel=categoria"],
    "Ventas · medios y fiado": [f"/ventas/medios?{FILTRO}", "/cuentas-corrientes"],
    "Ventas · metas": ["/metas"],
    "Proveedores": ["/proveedores/analisis"],
    "Ventas · impacto": ["/impacto"],
    "Canales · ganancia": [f"/canales/resultado?{FILTRO}"],
    "Canales · stock y online": ["/canales/stock", "/canales/ecommerce"],
    "Sucursales · comparar": [f"/sucursales/comparativo?{FILTRO}"],
    "Sucursales · matriz": ["/sucursales/matriz"],
    "Sucursales · precios y ajustes": ["/sucursales/precios-distintos", "/sucursales/ajustes"],
    "Avisos": ["/avisos?estado=abiertas"],
    "Datos · importar": ["/importar/tipos", "/importar/lotes"],
    "Datos · catálogo": ["/catalogo/pendientes"],
    "Datos · documentos": ["/lector", "/proveedores"],
    "Datos · conexiones": ["/conexiones"],
    "Configuración": ["/ubicaciones", "/canales", "/usuarios", "/limites", "/config/precios"],
}


def medir(get: Callable[[str], object], base: str = "/retail/api") -> list[dict]:
    """get(ruta) hace el pedido y devuelve la respuesta (con .status_code y .json()). Devuelve una fila por pantalla."""
    comprar = get(f"{base}/comprar")
    items = comprar.json().get("filas", []) if comprar.status_code == 200 else []
    producto = items[0]["producto_id"] if items else 1
    salida = []
    for pantalla, rutas in PANTALLAS.items():
        t0 = time.perf_counter()
        estados = []
        for ruta in rutas:
            estados.append(get(base + ruta.format(producto=producto)).status_code)
        segundos = time.perf_counter() - t0
        salida.append({"pantalla": pantalla, "segundos": round(segundos, 2), "ok": all(e == 200 for e in estados) and segundos < LIMITE_SEGUNDOS,
                       "estados": estados})
    return salida


def main() -> None:
    import httpx
    p = argparse.ArgumentParser(description="Mide cuánto tarda en cargar cada pantalla de Retail.")
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--email", default="dueno@norte.demo")
    p.add_argument("--clave", required=True)
    a = p.parse_args()
    with httpx.Client(base_url=a.url, timeout=60) as c:
        r = c.post("/retail/api/sesion", json={"email": a.email, "clave": a.clave})
        r.raise_for_status()
        filas = medir(c.get)
    for f in filas:
        print(f"{'✓' if f['ok'] else '✕'} {f['pantalla']:<28} {f['segundos']:>5.2f} s  {f['estados']}")
    lentas = [f for f in filas if not f["ok"]]
    print(f"\n{len(filas) - len(lentas)} de {len(filas)} pantallas cargan en menos de {LIMITE_SEGUNDOS:g} s.")
    raise SystemExit(1 if lentas else 0)


if __name__ == "__main__":
    main()
