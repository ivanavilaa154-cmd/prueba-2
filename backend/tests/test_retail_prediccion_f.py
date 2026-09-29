"""Predicciones · parte F: valor de vida y próxima compra (19, 20), lanzamientos (26), competencia (16) y góndola (24)."""
from fastapi.testclient import TestClient

from app.main import app
from app.retail import db, demo, motor
from app.retail.semilla import CLAVE_DEMO


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def test_valor_de_vida_y_proxima_compra(retail_demo):
    r = cliente().get("/retail/api/clientes").json()
    assert r["activo"] and r["valor_de_vida"] and 0.3 <= r["retencion_mensual"] <= 0.99
    valores = [c["valor_12m"] for c in r["valor_de_vida"]]
    assert valores == sorted(valores, reverse=True) and all(v >= 0 for v in valores)
    for p in r["proximas_compras"]:
        assert p["entre"] <= p["proxima"] <= p["y"] or p["entre"] <= p["y"]
        assert p["cada_dias"] >= 1


def test_lanzamientos_distingue_el_que_despega_del_que_no(retail_demo):
    r = cliente().get("/retail/api/lanzamientos").json()["lanzamientos"]
    por_codigo = {x["codigo"]: x for x in r}
    fuerte, debil = (por_codigo.get(c) for c in ("P0304", "P0314"))
    assert fuerte and debil
    assert fuerte["dias"] >= 60 and 40 <= debil["dias"] <= 50
    assert fuerte["prob_exito"] > debil["prob_exito"]
    assert debil["veredicto"] in ("no_despega", "en_duda")
    for x in r:
        assert x["unidades_90_min"] <= x["unidades_90"] <= x["unidades_90_max"] and x["vendidas"] <= x["unidades_90"]


def test_competencia_estima_el_precio_de_hoy_y_carga_archivos(retail_demo):
    c = cliente()
    r = c.get("/retail/api/competencia").json()
    assert r["relevados"] >= 10 and set(r["competidores"]) == set(demo.COMPETIDORES)
    for p in r["productos"]:
        for comp in p["competidores"]:
            assert comp["estimado_hoy"] >= comp["precio"]                 # con inflación positiva el precio de hoy no baja
    caro = r["productos"][0]
    assert caro["diferencia"] > 0.1 and caro["mas_barato"] == demo.COMPETIDORES[1]
    if caro["elasticidad"] is not None:
        assert caro["unidades_30d_si_igualas"] >= 0
    # Archivo: una fila buena y una con un código que no existe.
    codigo = _q("SELECT codigo_interno FROM productos ORDER BY id LIMIT 1")[0]["codigo_interno"]
    csv = f"codigo;competidor;precio;fecha\n{codigo};Almacén Nuevo;1.234,50;25/09/2026\nNOEXISTE;Almacén Nuevo;100;2026-09-25\n"
    res = c.post("/retail/api/competencia/archivo", files={"archivo": ("rel.csv", csv.encode(), "text/csv")}).json()
    assert res["cargados"] == 1 and res["errores"][0]["fila"] == 3
    assert _q("SELECT precio FROM precios_competencia WHERE competidor='Almacén Nuevo'")[0]["precio"] == 1234.5
    # El encargado no remarca: no puede cargar.
    assert cliente("encargado.norte@norte.demo").post("/retail/api/competencia", json=[]).status_code == 403


def test_gondola_rendimiento_por_metro_y_permisos(retail_demo):
    c = cliente()
    r = c.get("/retail/api/gondola").json()
    assert r["ubicacion"]["nombre"] == "Salta Centro" and r["productos"]
    for f in r["productos"]:
        assert abs(f["por_metro"] - f["ganancia_semana"] / f["metros"]) < 0.01
    assert r["movimientos"] and all(m["efecto_semana"] > 0 for m in r["movimientos"])
    estado = {f["nombre"]: f["estado"] for f in r["productos"]}
    assert all(estado[m["sacar_de"]] == "rinde_poco" and estado[m["dar_a"]] == "le_falta_espacio" for m in r["movimientos"])
    centro = r["ubicacion"]["id"]
    pid = r["productos"][0]["producto_id"]
    # El encargado de Salta Norte no puede tocar la góndola de Salta Centro, pero sí la suya.
    enc = cliente("encargado.norte@norte.demo")
    assert enc.put("/retail/api/gondola", json=[{"producto_id": pid, "ubicacion_id": centro, "frentes": 2, "metros": 0.5}]).status_code == 403
    norte = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Norte'")[0]["id"]
    assert enc.put("/retail/api/gondola", json=[{"producto_id": pid, "ubicacion_id": norte, "frentes": 2, "metros": 0.5}]).status_code == 200
    assert enc.get("/retail/api/gondola").json()["ubicacion"]["nombre"] == "Salta Norte"
