"""Crea una base SQLite de ejemplo («caja_ejemplo.sqlite») con ventas, existencias y artículos, para probar la lectura directa del agente.

Uso:  python crear_base_ejemplo.py C:\\Ejemplo   (crea la base y un agente.ini de ejemplo que la lee; completá url y token)
"""
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path


def crear(carpeta: Path, dias: int = 60, semilla: int = 7) -> Path:
    rng = random.Random(semilla)
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / "caja_ejemplo.sqlite"
    ruta.unlink(missing_ok=True)
    articulos = [("A001", "Yerba 1 kg", "7790000000011", "Almacén", 2900, 4200), ("A002", "Azúcar 1 kg", "7790000000028", "Almacén", 900, 1350),
                 ("A003", "Gaseosa 2,25 L", "7790000000035", "Bebidas", 1500, 2300), ("A004", "Galletitas 300 g", "7790000000042", "Almacén", 800, 1250)]
    with sqlite3.connect(ruta) as c:
        c.execute("CREATE TABLE articulos (codigo TEXT PRIMARY KEY, descripcion TEXT, barras TEXT, rubro TEXT, costo REAL, precio REAL)")
        c.execute("CREATE TABLE existencias (codigo TEXT, local TEXT, cantidad REAL)")
        c.execute("CREATE TABLE ventas (fecha TEXT, hora TEXT, local TEXT, numero INTEGER, codigo TEXT, cantidad REAL, precio REAL)")
        c.executemany("INSERT INTO articulos VALUES (?,?,?,?,?,?)", articulos)
        c.executemany("INSERT INTO existencias VALUES (?,?,?)", [(a[0], "Local 1", rng.randint(5, 60)) for a in articulos])
        numero, hoy = 0, date.today()
        for d in range(dias, 0, -1):
            dia = hoy - timedelta(days=d)
            for _ in range(rng.randint(15, 30)):
                numero += 1
                for a in rng.sample(articulos, rng.randint(1, 3)):
                    c.execute("INSERT INTO ventas VALUES (?,?,?,?,?,?,?)", (dia.isoformat(), f"{rng.randint(8, 20):02d}:{rng.randint(0, 59):02d}",
                                                                           "Local 1", numero, a[0], rng.randint(1, 3), a[5]))
    return ruta


if __name__ == "__main__":
    destino = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    base = crear(destino)
    (destino / "exportaciones").mkdir(exist_ok=True)
    plantilla = (Path(__file__).resolve().parent.parent / "plantillas" / "sqlite.ini").read_text(encoding="utf-8")
    (destino / "agente.ini").write_text(
        f"[agente]\nurl = https://tu-plataforma.ejemplo.com\ntoken = ag_pegá-acá-el-token\ncarpeta = {destino / 'exportaciones'}\ncada_minutos = 15\n\n"
        + plantilla.replace(r"C:\SistemaCaja\datos\caja.sqlite", str(base)), encoding="utf-8")
    print(f"Base de ejemplo: {base}\nConfiguración: {destino / 'agente.ini'} (completá url y token)")
