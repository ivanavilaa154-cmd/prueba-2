"""Retail · Fase 2, sección 13.2: copiloto con herramientas (cliente de IA falso)."""
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.retail import copiloto, db, motor
from app.retail.semilla import CLAVE_DEMO
from conftest import DEMO_HOY


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _bloque(tipo, **kw):
    return SimpleNamespace(model_dump=lambda exclude_none=True, kw=kw, tipo=tipo: {"type": tipo, **kw})


class IAFalsa:
    """Guion: cada paso es una lista de herramientas a llamar o un texto final armado con lo que devolvieron las herramientas."""
    def __init__(self, pasos):
        self.pasos, self.pedidos = list(pasos), []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.pedidos.append(kw)
        paso = self.pasos.pop(0)
        if callable(paso):
            paso = paso(kw["messages"])
        if isinstance(paso, str):
            return SimpleNamespace(stop_reason="end_turn", content=[_bloque("text", text=paso)])
        return SimpleNamespace(stop_reason="tool_use", content=[_bloque("tool_use", id=f"t{i}", name=n, input=e) for i, (n, e) in enumerate(paso)])


def _resultado(mensajes, n=0):
    return json.loads(mensajes[-1]["content"][n]["content"])


def test_responde_con_cifras_de_las_herramientas(retail_demo, monkeypatch):
    d = str(DEMO_HOY)
    ia = IAFalsa([[("ventas", {"desde": d, "hasta": d, "comparar_desde": "2026-09-19", "comparar_hasta": "2026-09-19"})],
                  lambda m: f"Hoy vendiste {_resultado(m)['periodo']['total']['facturacion']} (del {d})."])
    monkeypatch.setattr(copiloto, "_cliente", lambda: ia)
    r = cliente().post("/retail/api/copiloto", json={"mensaje": "¿Cuánto vendí hoy contra el sábado pasado?"}).json()
    total = _q("SELECT sum(facturacion) f FROM agg_producto_ubicacion_dia WHERE fecha=%s", (DEMO_HOY,))[0]["f"]
    assert str(float(total)) in r["texto"]
    assert r["herramientas"][0]["herramienta"] == "ventas"
    # Se mandan las herramientas definidas y la regla de no inventar cifras.
    p = ia.pedidos[0]
    assert {t["name"] for t in p["tools"]} >= {"ventas", "explicar_sugerencia", "proponer_accion"} and "herramienta" in p["system"]
    assert "tool_choice" not in p
    # El historial vuelve para seguir la conversación.
    assert r["historial"][-1]["role"] == "assistant"


def test_las_herramientas_respetan_sucursales_y_permisos(retail_demo):
    # Contexto del encargado: se arma igual que en la API (RLS limita a su sucursal).
    with db.transaccion(superadmin=True) as conn:
        u = db.fila(conn, "SELECT id FROM usuarios WHERE email='encargado.norte@norte.demo'")
    ctx_enc = db.Contexto(usuario_id=u["id"], org_id=1, rol="encargado", nombre="Lucía", todas_ubicaciones=False,
                          ubicaciones=[x["id"] for x in _q("SELECT id FROM ubicaciones WHERE nombre='Salta Norte'")])
    r = copiloto.ejecutar(ctx_enc, "ventas", {"desde": "2026-09-01", "hasta": str(DEMO_HOY)})
    assert [s["sucursal"] for s in r["periodo"]["por_sucursal"]] == ["Salta Norte"]
    assert copiloto.ejecutar(ctx_enc, "contexto", {})["sucursales"][0]["nombre"] == "Salta Norte"
    # El encargado sí ve costos (según su rol), el cajero no puede proponer OC.
    ctx_caja = db.Contexto(usuario_id=u["id"], org_id=1, rol="cajero", nombre="Caja", todas_ubicaciones=False, ubicaciones=ctx_enc.ubicaciones)
    r = copiloto.ejecutar(ctx_caja, "proponer_accion", {"tipo": "orden_compra", "motivo": "x", "items": [{"producto_id": 1, "ubicacion_id": ctx_enc.ubicaciones[0]}]})
    assert "error" in r
    assert "error" in copiloto.ejecutar(ctx_caja, "plata_parada", {})
    assert "error" in copiloto.ejecutar(ctx_caja, "ranking_productos", {"desde": "2026-09-01", "hasta": "2026-09-24", "criterio": "ganancia"})
    assert "error" in copiloto.ejecutar(ctx_enc, "no_existe", {})


def test_explica_una_sugerencia_y_propone_una_accion(retail_demo, monkeypatch):
    m = _q("SELECT producto_id, ubicacion_id FROM metricas_producto_actual WHERE semaforo='rojo' AND cantidad_sugerida > 0 LIMIT 1")[0]
    ia = IAFalsa([[("explicar_sugerencia", {"producto_id": m["producto_id"], "ubicacion_id": m["ubicacion_id"]})],
                  [("proponer_accion", {"tipo": "orden_compra", "motivo": "Se agota", "items": [{"producto_id": m["producto_id"], "ubicacion_id": m["ubicacion_id"], "cantidad": 12}]})],
                  lambda msgs: "Te sugiero pedir 12: confirmá abajo."])
    monkeypatch.setattr(copiloto, "_cliente", lambda: ia)
    r = cliente().post("/retail/api/copiloto", json={"mensaje": "¿Por qué me sugerís pedir esto?"}).json()
    explicacion = json.loads(ia.pedidos[1]["messages"][2]["content"][0]["content"])      # 0 pregunta, 1 llamada, 2 resultado
    assert explicacion["detalle"][0]["explicacion"] and explicacion["detalle"][0]["cantidad_sugerida"] is not None
    assert r["propuestas"][0]["tipo"] == "orden_compra" and r["propuestas"][0]["items"][0]["producto"]
    # Proponer no crea nada.
    assert not _q("SELECT 1 FROM ordenes_compra WHERE created_by IS NOT NULL AND estado='borrador' AND created_at > now() - interval '1 minute'")


def test_sin_clave_de_ia_lo_explica(retail_demo, monkeypatch):
    import anthropic
    import httpx

    def falla(**kw):
        raise anthropic.AuthenticationError("sin clave", response=httpx.Response(401, request=httpx.Request("POST", "https://x")), body=None)
    monkeypatch.setattr(copiloto, "_cliente", lambda: SimpleNamespace(messages=SimpleNamespace(create=falla)))
    r = cliente().post("/retail/api/copiloto", json={"mensaje": "hola"}).json()
    assert "ANTHROPIC_API_KEY" in r["texto"]
