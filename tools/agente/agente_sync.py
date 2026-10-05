"""Agente de sincronización de Retail IA para la PC del local (Windows, también corre en Linux o Mac).

Qué hace: cada N minutos mira una carpeta donde el sistema de caja deja sus exportaciones (CSV o Excel) y sube cada archivo nuevo a
la plataforma por HTTPS, con el token del agente. Si no hay internet, el archivo queda en la cola local y se reintenta después,
esperando cada vez un poco más. Lo enviado se mueve a la subcarpeta «enviados»; lo rechazado, a «rechazados» con el motivo.
Cada vuelta informa a la plataforma su estado (versión, PC, carpeta, archivos en cola, último error): se ve en Datos → Conexiones.

El nombre del archivo dice qué trae: ventas_….csv, stock_….xlsx, productos_…, compras_…, precios_… (configurable en agente.ini).
Solo usa la biblioteca estándar de Python: se empaqueta como un .exe con PyInstaller (ver LEEME.md).

Uso:  python agente_sync.py            (corre para siempre)
      python agente_sync.py --una-vez  (una vuelta y termina; útil para el Programador de tareas)
"""
from __future__ import annotations

import configparser
import hashlib
import json
import logging
import mimetypes
import os
import platform
import shutil
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

VERSION = "1.0.0"
EXTENSIONES = {".csv", ".txt", ".xlsx", ".xlsm"}
ESPERA_ESTABLE = 30          # segundos sin cambios antes de subir (el sistema puede estar escribiendo el archivo)
REINTENTO_MAXIMO = 3600      # espera máxima entre reintentos de un archivo (segundos)

log = logging.getLogger("agente")


class Config:
    def __init__(self, ruta: Path):
        c = configparser.ConfigParser()
        if not c.read(ruta, encoding="utf-8"):
            raise SystemExit(f"No encuentro {ruta}. Copiá agente.ini.ejemplo como agente.ini y completalo.")
        s = c["agente"]
        self.url = s.get("url", "").rstrip("/")
        self.token = s.get("token", "").strip()
        self.carpeta = Path(s.get("carpeta", "")).expanduser()
        self.cada_minutos = max(1, s.getint("cada_minutos", 15))
        self.tipos = dict(c["tipos"]) if c.has_section("tipos") else {}      # prefijo de archivo → tipo, si el sistema usa otros nombres
        if not self.url.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise SystemExit("La url tiene que empezar con https:// (los datos viajan cifrados).")
        if not self.token.startswith("ag_"):
            raise SystemExit("Falta el token del agente (Datos → Conexiones → Agente de sincronización → Crear).")
        if not self.carpeta.is_dir():
            raise SystemExit(f"La carpeta {self.carpeta} no existe.")


def _multipart(campos: dict[str, str], archivo: Path) -> tuple[bytes, str]:
    limite = uuid.uuid4().hex
    partes = []
    for k, v in campos.items():
        partes.append(f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    tipo = mimetypes.guess_type(archivo.name)[0] or "application/octet-stream"
    partes.append(f"--{limite}\r\nContent-Disposition: form-data; name=\"archivo\"; filename=\"{archivo.name}\"\r\n"
                  f"Content-Type: {tipo}\r\n\r\n".encode() + archivo.read_bytes() + b"\r\n")
    partes.append(f"--{limite}--\r\n".encode())
    return b"".join(partes), f"multipart/form-data; boundary={limite}"


class Transporte:
    """Habla con la plataforma. Se puede reemplazar en las pruebas."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _pedido(self, ruta: str, cuerpo: bytes, tipo: str) -> tuple[int, dict]:
        req = urllib.request.Request(self.cfg.url + ruta, data=cuerpo, method="POST",
                                     headers={"Authorization": f"Agente {self.cfg.token}", "Content-Type": tipo,
                                              "User-Agent": f"RetailIA-Agente/{VERSION}"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {}

    def subir(self, archivo: Path, tipo: str | None) -> tuple[int, dict]:
        cuerpo, ctype = _multipart({"tipo": tipo} if tipo else {}, archivo)
        return self._pedido("/retail/api/agente/archivo", cuerpo, ctype)

    def latido(self, estado: dict) -> tuple[int, dict]:
        return self._pedido("/retail/api/agente/latido", json.dumps(estado).encode(), "application/json")


class Agente:
    def __init__(self, cfg: Config, transporte=None, reloj=time.time):
        self.cfg = cfg
        self.t = transporte or Transporte(cfg)
        self.reloj = reloj
        self.estado_ruta = cfg.carpeta / ".agente_estado.json"
        self.estado = self._leer_estado()
        for sub in ("enviados", "rechazados"):
            (cfg.carpeta / sub).mkdir(exist_ok=True)

    def _leer_estado(self) -> dict:
        try:
            return json.loads(self.estado_ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"enviados": {}, "cola": {}, "ultimo_error": None}

    def _guardar_estado(self) -> None:
        temporal = self.estado_ruta.with_suffix(".tmp")
        temporal.write_text(json.dumps(self.estado, ensure_ascii=False, indent=1), encoding="utf-8")
        temporal.replace(self.estado_ruta)

    def _tipo(self, nombre: str) -> str | None:
        n = nombre.lower()
        return next((t for prefijo, t in self.cfg.tipos.items() if n.startswith(prefijo.lower())), None)

    def archivos_nuevos(self) -> list[Path]:
        ahora = self.reloj()
        nuevos = []
        for f in sorted(self.cfg.carpeta.iterdir()):
            if not f.is_file() or f.suffix.lower() not in EXTENSIONES or f.name.startswith((".", "~$")):
                continue
            if ahora - f.stat().st_mtime < ESPERA_ESTABLE:
                continue                                       # todavía se está escribiendo
            huella = hashlib.sha256(f.read_bytes()).hexdigest()
            if huella in self.estado["enviados"]:
                self._mover(f, "enviados")                     # ya subido (por ejemplo, el sistema lo volvió a dejar)
                continue
            nuevos.append(f)
        return nuevos

    def _mover(self, f: Path, sub: str, motivo: str | None = None) -> None:
        destino = self.cfg.carpeta / sub / f.name
        if destino.exists():
            destino = destino.with_name(f"{destino.stem}_{int(self.reloj())}{destino.suffix}")
        shutil.move(str(f), destino)
        if motivo:
            destino.with_suffix(destino.suffix + ".motivo.txt").write_text(motivo, encoding="utf-8")

    def vuelta(self) -> dict:
        """Sube lo pendiente (respetando los reintentos) e informa el estado. Devuelve un resumen de la vuelta."""
        resumen = {"subidos": 0, "rechazados": 0, "en_cola": 0, "errores": []}
        ahora = self.reloj()
        for f in self.archivos_nuevos():
            huella = hashlib.sha256(f.read_bytes()).hexdigest()
            cola = self.estado["cola"].get(huella, {"intentos": 0, "proximo": 0})
            if cola["proximo"] > ahora:
                resumen["en_cola"] += 1
                continue
            try:
                codigo, r = self.t.subir(f, self._tipo(f.name))
            except (urllib.error.URLError, OSError, TimeoutError) as e:     # sin internet o servidor caído: a la cola
                codigo, r = None, {"detail": f"Sin conexión: {e}"}
            if codigo == 200:
                self.estado["enviados"][huella] = {"archivo": f.name, "estado": r.get("estado"), "lote": r.get("lote_id"), "cuando": ahora}
                self.estado["cola"].pop(huella, None)
                self._mover(f, "enviados")
                resumen["subidos"] += 1
                log.info("Subido %s: %s", f.name, r.get("mensaje") or r.get("estado"))
            elif codigo in (400, 413):                                      # el archivo no sirve: no se reintenta
                self.estado["cola"].pop(huella, None)
                self._mover(f, "rechazados", r.get("detail") or "Rechazado")
                resumen["rechazados"] += 1
                resumen["errores"].append(f"{f.name}: {r.get('detail')}")
                log.warning("Rechazado %s: %s", f.name, r.get("detail"))
            else:                                                           # 401, 5xx o sin conexión: se reintenta más tarde
                cola["intentos"] += 1
                cola["proximo"] = ahora + min(REINTENTO_MAXIMO, 60 * 2 ** (cola["intentos"] - 1))
                self.estado["cola"][huella] = cola
                resumen["en_cola"] += 1
                resumen["errores"].append(f"{f.name}: {r.get('detail') or codigo}")
                log.warning("No se pudo subir %s (intento %s): %s", f.name, cola["intentos"], r.get("detail") or codigo)
        self.estado["ultimo_error"] = resumen["errores"][-1] if resumen["errores"] else None
        self._guardar_estado()
        try:
            self.t.latido({"version": VERSION, "equipo": platform.node()[:120], "carpeta": str(self.cfg.carpeta)[:400],
                           "pendientes": resumen["en_cola"], "error": self.estado["ultimo_error"]})
        except (urllib.error.URLError, OSError, TimeoutError):
            pass                                                            # sin internet: se informa en la próxima vuelta
        return resumen


def main() -> None:
    base = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
    logging.basicConfig(filename=base / "agente.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger().addHandler(logging.StreamHandler())
    cfg = Config(Path(os.environ.get("AGENTE_INI", base / "agente.ini")))
    agente = Agente(cfg)
    log.info("Agente %s vigilando %s cada %s minutos", VERSION, cfg.carpeta, cfg.cada_minutos)
    while True:
        try:
            agente.vuelta()
        except Exception:                                                    # nunca se cae: lo deja en el log y sigue
            log.exception("Error en la vuelta")
        if "--una-vez" in sys.argv:
            break
        time.sleep(cfg.cada_minutos * 60)


if __name__ == "__main__":
    main()
