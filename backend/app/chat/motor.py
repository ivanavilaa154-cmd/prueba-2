"""Motor del chat interno: bucle de herramientas con la API de Claude.

El modelo recibe la pregunta, decide qué herramientas usar (consultar el ERP,
ver el diccionario, simular una decisión), recibe los resultados y responde.
No hay respuestas predefinidas.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import config
from ..permisos import Usuario
from . import herramientas


def prompt_sistema(usuario: Usuario) -> str:
    partes = [
        config.prompt("00_base.md", {"USUARIO": usuario.nombre}),
        config.prompt("06_chat_interno.md"),
        config.prompt("05_centro_decisiones.md"),
        "USUARIO ACTUAL\n" + usuario.describir(),
        config.resumen_diccionario(),
    ]
    return "\n\n".join(partes)


@dataclass
class RespuestaChat:
    texto: str
    herramientas_usadas: list[dict] = field(default_factory=list)
    historial: list[dict] = field(default_factory=list)


def _cliente_por_defecto():
    import anthropic  # importación diferida: las pruebas usan un cliente falso

    return anthropic.Anthropic()


def responder(mensaje: str, usuario: Usuario, historial: list[dict] | None = None, cliente=None) -> RespuestaChat:
    cliente = cliente or _cliente_por_defecto()
    mensajes = list(historial or []) + [{"role": "user", "content": mensaje}]
    usadas: list[dict] = []
    sistema = prompt_sistema(usuario)

    for _ in range(config.MAX_VUELTAS_HERRAMIENTAS):
        respuesta = cliente.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=4096,
            system=sistema,
            tools=herramientas.DEFINICIONES,
            messages=mensajes,
        )
        contenido = [bloque.model_dump() if hasattr(bloque, "model_dump") else bloque
                     for bloque in respuesta.content]
        mensajes.append({"role": "assistant", "content": contenido})

        if respuesta.stop_reason != "tool_use":
            texto = "\n".join(b["text"] for b in contenido if b.get("type") == "text").strip()
            return RespuestaChat(texto=texto, herramientas_usadas=usadas, historial=mensajes)

        resultados = []
        for bloque in contenido:
            if bloque.get("type") != "tool_use":
                continue
            salida = herramientas.ejecutar(bloque["name"], bloque.get("input", {}), usuario)
            usadas.append({"herramienta": bloque["name"], "entrada": bloque.get("input", {})})
            resultados.append({"type": "tool_result", "tool_use_id": bloque["id"], "content": salida})
        mensajes.append({"role": "user", "content": resultados})

    return RespuestaChat(
        texto="No pude completar la respuesta en el límite de pasos. Probá con una pregunta más concreta.",
        herramientas_usadas=usadas,
        historial=mensajes,
    )
