"""Emails de Retail: bandeja de salida en la base; se envían por SMTP si está configurado (SMTP_HOST, SMTP_USUARIO,
SMTP_CLAVE, SMTP_REMITENTE en backend/.env). Sin SMTP, cada email se guarda como archivo en backend/emails/ para revisarlo
(estado «guardado»): nada se pierde y nada sale sin configurarlo."""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

from . import db

CARPETA = Path(__file__).resolve().parents[2] / "emails"


def encolar(conn, org_id: int | None, para: str, asunto: str, html: str, tipo: str, usuario_id: int | None = None,
            adjunto: str | None = None) -> int:
    return db.fila(conn, "INSERT INTO emails (org_id, usuario_id, para, asunto, html, tipo, adjunto) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                   (org_id, usuario_id, para, asunto, html, tipo, adjunto))["id"]


def enviar_pendientes(conn) -> dict:
    enviados, guardados, errores = 0, 0, 0
    for e in db.filas(conn, "SELECT * FROM emails WHERE estado='pendiente' ORDER BY id LIMIT 200"):
        try:
            if os.getenv("SMTP_HOST"):
                _smtp(e)
                estado = "enviado"
                enviados += 1
            else:
                CARPETA.mkdir(exist_ok=True)
                (CARPETA / f"{e['id']:06d}-{e['tipo']}.html").write_text(
                    f"<!-- Para: {e['para']} -->\n<!-- Asunto: {e['asunto']} -->\n{e['html']}", encoding="utf-8")
                estado = "guardado"
                guardados += 1
            with conn.cursor() as cur:
                cur.execute("UPDATE emails SET estado=%s, enviado_at=now() WHERE id=%s", (estado, e["id"]))
        except Exception as ex:
            errores += 1
            with conn.cursor() as cur:
                cur.execute("UPDATE emails SET estado='error', error=%s WHERE id=%s", (str(ex)[:300], e["id"]))
    return {"enviados": enviados, "guardados": guardados, "errores": errores}


def _smtp(e: dict) -> None:
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_REMITENTE", os.getenv("SMTP_USUARIO", "retail@localhost"))
    msg["To"] = e["para"]
    msg["Subject"] = e["asunto"]
    msg.set_content("Este email necesita un lector con HTML.")
    msg.add_alternative(e["html"], subtype="html")
    if e.get("adjunto") and Path(e["adjunto"]).exists():
        msg.add_attachment(Path(e["adjunto"]).read_bytes(), maintype="application", subtype="pdf", filename=Path(e["adjunto"]).name)
    puerto = int(os.getenv("SMTP_PUERTO", "587"))
    with smtplib.SMTP(os.environ["SMTP_HOST"], puerto, timeout=20) as s:
        s.starttls()
        if os.getenv("SMTP_USUARIO"):
            s.login(os.environ["SMTP_USUARIO"], os.getenv("SMTP_CLAVE", ""))
        s.send_message(msg)
