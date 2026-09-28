"""Retail · Fase 2, sección 9: plata parada, vencimientos, ofertas y merma."""
from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import app
from app.retail import calculos as C
from app.retail import db, demo, motor, pdf
from app.retail.semilla import CLAVE_DEMO
from conftest import DEMO_HOY


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def test_factor_merma_y_descuento_minimo():
    assert C.factor_merma(10, 90) == 0.9
    assert C.factor_merma(2, 98) == 1.0                       # 2 % está bajo el umbral
    assert C.factor_merma(80, 20) == 0.5                      # con tope
    assert C.descuento_minimo(0, 10, 5) == (0.0, 1.0)
    assert C.descuento_minimo(3, 10, 5) == (0.1, 1.3)         # 10 × 1,3 = 13 ≥ 10 + 3
    assert C.descuento_minimo(10, 10, 5) == (0.3, 2.2)        # 1,7 no alcanza (17 < 20), 2,2 sí
    assert C.descuento_minimo(40, 10, 5) is None              # ni con 50 %


def test_plata_parada_suma_y_clasifica(retail_demo):
    r = cliente().get("/retail/api/plata-parada").json()
    d = r["distribucion"]
    total = sum(Decimal(d[e]["capital"]) for e in d)
    assert abs(total - Decimal(r["tarjetas"]["capital_total"])) < Decimal("0.05")
    assert Decimal(r["tarjetas"]["plata_parada"]) == Decimal(d["sobrestock"]["capital"]) + Decimal(d["muerto"]["capital"])
    assert r["tarjetas"]["cobertura_dias"] > 0
    # Por sucursal suma lo mismo que el total.
    assert abs(sum(Decimal(x["total"]) for x in r["por_ubicacion"]) - total) < Decimal("0.05")
    # Tramos sin ventas: cada tramo contiene al siguiente.
    tramos = [x["productos"] for x in r["sin_ventas"]]
    assert tramos == sorted(tramos, reverse=True)
    # El caso de sobrestock conocido aparece con recomendación.
    sob = demo.CASOS["sobrestock"]
    item = next(i for i in r["items"] if i["codigo_interno"] == sob["producto"] and i["ubicacion"] == sob["ubicacion"])
    assert item["estado"] == "sobrestock" and "comprar" in item["recomendacion"].lower()
    assert set(item["variaciones"]) >= {"ultimos_30_vs_anteriores", "mes_vs_anio_anterior", "4_semanas_vs_3_meses"}


def test_vencimientos_con_calculo_manual_y_oferta(retail_demo, tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "CARPETA", tmp_path)
    c = cliente()
    r = c.get("/retail/api/vencimientos").json()
    codigo = retail_demo["vence_pronto"]
    lote = next(l for l in r["lotes"] if l["codigo_interno"] == codigo and Decimal(l["no_llegan"]) > 0)
    assert lote["tramo"] == "menos de 7 días"
    assert Decimal(lote["plata_en_riesgo"]) == (Decimal(lote["no_llegan"]) * Decimal(lote["costo"])).quantize(Decimal("0.01"))
    # Cálculo manual: cantidad − pronóstico acumulado hasta el vencimiento (lotes anteriores primero).
    m = _q("SELECT explicacion FROM metricas_producto_actual m JOIN productos p ON p.id=m.producto_id WHERE p.codigo_interno=%s AND m.ubicacion_id=%s",
           (codigo, lote["ubicacion_id"]))[0]["explicacion"]
    lotes = [{"lote": x["lote"], "cantidad": x["cantidad"], "vencimiento": __import__("datetime").date.fromisoformat(str(x["vencimiento"])[:10])}
             for x in m["lotes"]]
    manual = C.unidades_que_no_llegan(lotes, m["pronostico_120d"], DEMO_HOY)
    esperado = next(x for x in manual if x["lote"] == lote["lote"])["no_llegan"]
    assert abs(float(lote["no_llegan"]) - esperado) < 0.01
    # El caso conocido tiene tanto de más que ni con 50 % se vende: se recomienda transferir o devolver.
    assert lote["oferta"]["descuento"] is None and "transferilo" in lote["oferta"]["texto"]
    # Otro lote en el que alcanza con descuento: con oferta se recupera más que sin hacer nada.
    lote = next(l for l in r["lotes"] if l["oferta"] and l["oferta"]["descuento"])
    of = lote["oferta"]
    assert Decimal(of["con_oferta"]) - Decimal(of["sin_oferta"]) == Decimal(of["recuperable"]) and Decimal(of["recuperable"]) > 0
    o = c.post("/retail/api/ofertas", json={"producto_id": lote["producto_id"], "ubicacion_id": lote["ubicacion_id"], "descuento": of["descuento"],
                                            "hasta": lote["vencimiento"], "unidades_objetivo": float(lote["no_llegan"])})
    assert o.status_code == 200, o.text
    cartel = c.get(f"/retail/api/ofertas/{o.json()['id']}/cartel?tamano=a6")
    assert cartel.status_code == 200 and cartel.content[:4] == b"%PDF"
    lista = c.get("/retail/api/ofertas").json()
    assert lista[0]["id"] == o.json()["id"] and lista[0]["vigente"] and "plata_recuperada" in lista[0]
    assert next(l for l in c.get("/retail/api/vencimientos").json()["lotes"] 
                if (l["lote"], l["producto_id"], l["ubicacion_id"]) == (lote["lote"], lote["producto_id"], lote["ubicacion_id"]))["en_oferta"]
    # Un encargado no puede crear ofertas.
    assert cliente("encargado.norte@norte.demo").post("/retail/api/ofertas", json={"producto_id": 1, "descuento": 0.1,
                                                                                   "hasta": str(DEMO_HOY + timedelta(days=3))}).status_code == 403


def test_merma_registra_descuenta_stock_y_ajusta_el_pedido(retail_demo):
    c = cliente("encargado.norte@norte.demo")
    norte = _q("SELECT id FROM ubicaciones WHERE nombre='Salta Norte'")[0]["id"]
    p = _q("SELECT s.producto_id, s.cantidad FROM stock_actual s JOIN productos p ON p.id=s.producto_id WHERE s.ubicacion_id=%s AND p.perecedero "
           "AND s.cantidad > 10 ORDER BY s.producto_id LIMIT 1", (norte,))[0]
    r = c.post("/retail/api/merma", json={"producto_id": p["producto_id"], "ubicacion_id": norte, "cantidad": 3, "motivo": "rotura"})
    assert r.status_code == 200, r.text
    assert _q("SELECT cantidad FROM stock_actual WHERE producto_id=%s AND ubicacion_id=%s", (p["producto_id"], norte))[0]["cantidad"] == p["cantidad"] - 3
    assert _q("SELECT count(*) n FROM auditoria WHERE accion='merma'")[0]["n"] == 1
    # El encargado de Norte no registra merma en otra sucursal.
    jujuy = _q("SELECT id FROM ubicaciones WHERE nombre='San Salvador de Jujuy'")[0]["id"]
    assert c.post("/retail/api/merma", json={"producto_id": p["producto_id"], "ubicacion_id": jujuy, "cantidad": 1, "motivo": "rotura"}).status_code == 404
    rk = cliente().get("/retail/api/merma").json()
    assert Decimal(rk["total"]) > 0 and rk["mensual"] and rk["por_producto"][0]["costo"]
    # Tras recalcular, el factor de merma queda en la explicación de los perecederos.
    motor.recalcular(1, DEMO_HOY, tipo="incremental")
    e = _q("SELECT explicacion FROM metricas_producto_actual WHERE producto_id=%s AND ubicacion_id=%s", (p["producto_id"], norte))[0]["explicacion"]
    assert e["merma_90d"] >= 3 and 0.5 <= e["factor_merma"] <= 1
