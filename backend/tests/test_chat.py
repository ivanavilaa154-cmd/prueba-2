"""Prueba el bucle de herramientas del chat con un cliente de API falso (sin red)."""
import json
from types import SimpleNamespace

from app.chat import motor
from app.permisos import obtener_usuario


class ClienteFalso:
    """Primera llamada: pide consultar el ERP. Segunda: responde con texto."""

    def __init__(self, sql):
        self.sql = sql
        self.llamadas = []
        self.messages = self

    def create(self, **kwargs):
        self.llamadas.append(kwargs)
        if len(self.llamadas) == 1:
            return SimpleNamespace(stop_reason="tool_use", content=[
                {"type": "text", "text": "Consulto el ERP."},
                {"type": "tool_use", "id": "t1", "name": "consultar_erp",
                 "input": {"sql": self.sql, "motivo": "prueba"}},
            ])
        return SimpleNamespace(stop_reason="end_turn", content=[{"type": "text", "text": "Listo."}])


def _resultado_herramienta(cliente):
    for mensaje in cliente.llamadas[-1]["messages"]:
        for bloque in mensaje["content"] if isinstance(mensaje["content"], list) else []:
            if bloque.get("type") == "tool_result":
                return json.loads(bloque["content"])
    raise AssertionError("No hubo resultado de herramienta")


def test_bucle_de_herramientas(base_demo_config):
    cliente = ClienteFalso("SELECT COUNT(*) AS n FROM clientes")
    r = motor.responder("¿Cuántos clientes tengo?", obtener_usuario("u1"), cliente=cliente)
    assert r.texto == "Listo."
    assert r.herramientas_usadas[0]["herramienta"] == "consultar_erp"
    assert _resultado_herramienta(cliente)["filas"][0][0] == 12


def test_escritura_bloqueada_vuelve_como_error(base_demo_config):
    cliente = ClienteFalso("DELETE FROM ventas")
    motor.responder("Borrá las ventas", obtener_usuario("u1"), cliente=cliente)
    assert _resultado_herramienta(cliente)["tipo"] == "no_permitido"


def test_permisos_en_el_chat(base_demo_config):
    cliente = ClienteFalso("SELECT SUM(saldo) FROM cxc")
    motor.responder("¿Cuánto nos deben?", obtener_usuario("u3"), cliente=cliente)  # rol compras
    assert "no está disponible para tu perfil" in _resultado_herramienta(cliente)["error"]


def test_prompt_de_sistema_incluye_rol_y_diccionario():
    texto = motor.prompt_sistema(obtener_usuario("u2"))
    assert "Rol: vendedor" in texto and "vendedor_id = 1" in texto
    assert "TABLAS DISPONIBLES" in texto and "{EMPRESA}" not in texto
