"""SPEC v2 · pasos 6-8: modo distribuidor (datos, 5 reportes, vista del vendedor, demo «Distribuidora del Valle»)."""
import copy
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.integraciones import odoo
from app.main import app
from app.retail import db, demo_distribuidora as demo, distribuidor, odoo_distribuidor, odoo_pos
from app.retail.semilla import CLAVE_DEMO

HOY = date(2026, 9, 24)
CASOS = demo.CASOS


def cliente(email="dueno@valle.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _q(sql, params=()):
    with db.transaccion(superadmin=True) as conn:
        return db.filas(conn, sql, params)


def _org():
    return _q("SELECT id FROM organizaciones WHERE nombre=%s", (demo.EMPRESA,))[0]["id"]


def _fila(filas, nombre, campo="cliente"):
    return next(f for f in filas if f[campo] == nombre)


# ------------------------------------------------------------------------------------------- 1. clientes que dejaron de comprar
def test_clasificacion_segun_el_ritmo_propio():
    u = {"riesgo": 1.5, "perdido": 3.0, "min_dias": 21}
    semanal = [HOY - timedelta(days=7 * k) for k in range(10, 0, -1)]          # última compra hace 7 días
    assert distribuidor.clasificar(semanal, HOY, u)["estado"] == "activo"
    assert distribuidor.clasificar(semanal, HOY + timedelta(days=5), u)["estado"] == "en_riesgo"      # 12 días > 1,5 × 7
    assert distribuidor.clasificar(semanal, HOY + timedelta(days=15), u)["estado"] == "perdido"       # 22 días > max(21, 3 × 7)
    mensual = [HOY - timedelta(days=28 * k) for k in range(6, 0, -1)]
    assert distribuidor.clasificar(mensual, HOY + timedelta(days=30), u)["estado"] == "en_riesgo"     # 58 días: más de 1,5×, menos de 3×
    pocas = [HOY - timedelta(days=10)]
    r = distribuidor.clasificar(pocas, HOY, u)
    assert r["intervalo"] == 30 and r["estado"] == "activo"
    assert distribuidor.clasificar([], HOY, u)["estado"] == "sin_compras"


def test_clientes_que_dejaron_de_comprar(retail_distribuidora):
    r = cliente().get("/retail/api/distribuidor/clientes").json()
    perdido = _fila(r["filas"], CASOS["perdido"]["cliente"])
    assert perdido["estado"] == "perdido" and perdido["intervalo"] == 7 and perdido["dias_sin_comprar"] >= 35
    assert perdido["deja_de_facturar_mes"] > 0 and "7 días" in perdido["explicacion"]
    riesgo = _fila(r["filas"], CASOS["riesgo"]["cliente"])
    assert riesgo["estado"] == "en_riesgo" and 10 < riesgo["dias_sin_comprar"] <= 21
    assert r["resumen"]["perdido"] >= 1 and r["resumen"]["en_riesgo"] >= 1
    assert abs(r["resumen"]["deja_de_facturar_mes"] - sum(f["deja_de_facturar_mes"] for f in r["filas"])) < 1
    # Primero los perdidos, de mayor a menor plata.
    assert r["filas"][0]["estado"] == "perdido"
    solo = cliente().get("/retail/api/distribuidor/clientes?estado=en_riesgo").json()["filas"]
    assert solo and all(f["estado"] == "en_riesgo" for f in solo)


def test_umbrales_configurables(retail_distribuidora):
    c = cliente()
    assert c.put("/retail/api/distribuidor/umbrales", json={"riesgo": 3, "perdido": 2, "min_dias": 21}).status_code == 400
    assert c.put("/retail/api/distribuidor/umbrales", json={"riesgo": 2.5, "perdido": 4, "min_dias": 30}).status_code == 200
    r = c.get("/retail/api/distribuidor/clientes").json()
    assert r["umbrales"] == {"riesgo": 2.5, "perdido": 4.0, "min_dias": 30}
    assert _fila(r["filas"], CASOS["riesgo"]["cliente"])["estado"] == "activo"          # 14 días < 2,5 × 7


def test_ficha_con_oportunidades(retail_distribuidora):
    c = cliente()
    cid = _q("SELECT id FROM clientes_b2b WHERE razon_social=%s", (CASOS["riesgo"]["cliente"],))[0]["id"]
    f = c.get(f"/retail/api/distribuidor/clientes/{cid}").json()
    assert f["estado"]["estado"] == "en_riesgo" and f["meses"] and f["pedidos"]
    assert f["oportunidades"], "a un almacén sin limpieza se le sugiere lo que compran los almacenes parecidos"
    o = f["oportunidades"][0]
    assert o["compran_parecidos"] >= 0.4 and o["cantidad_sugerida"] >= 1
    compradas = {x["categoria_id"] for x in _q("""SELECT DISTINCT pr.categoria_id FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id
                                                 JOIN productos pr ON pr.id = l.producto_id WHERE p.cliente_id = %s AND p.fecha > %s""",
                                              (cid, HOY - timedelta(days=90)))}
    assert not {x["categoria_id"] for x in f["oportunidades"]} & compradas


# ------------------------------------------------------------------------------------------- 2. rendimiento por vendedor
def test_rendimiento_por_vendedor(retail_distribuidora):
    r = cliente().get("/retail/api/distribuidor/vendedores?periodo=90d").json()
    vs = {v["vendedor"]: v for v in r["vendedores"]}
    assert len(vs) == 6
    diego = vs["Diego Ruiz"]
    otros = [v for n, v in vs.items() if n != "Diego Ruiz" and v["venta"]]
    assert diego["descuento_pct"] > max(v["descuento_pct"] for v in otros)       # descuenta de más…
    assert diego["margen"] < min(v["margen"] for v in otros)                     # …y se le nota en el margen
    assert diego["clientes_perdidos"] >= 1 and diego["plata_en_riesgo_mes"] > 0
    assert [v["ranking"] for v in r["vendedores"]] == list(range(1, 7))
    # La venta del equipo es la suma de lo facturable de los pedidos del período.
    total = _q(f"""SELECT sum(l.precio * {distribuidor.FACTURABLE}) t FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id
                   WHERE {distribuidor.COMPRA} AND p.fecha BETWEEN %s AND %s""", (HOY - timedelta(days=89), HOY))[0]["t"]
    assert abs(r["equipo"]["venta"] - float(total)) < 1
    assert all(v["meta_mes"] for v in r["vendedores"]) and all(v["proyeccion_mes"] >= v["venta_mes"] for v in r["vendedores"])
    marcas = r["marcas"]
    assert len(marcas) == 3 and any(m["en_riesgo"] for m in marcas) and any(m["falta"] == 0 for m in marcas)
    riesgo = next(m for m in marcas if m["en_riesgo"])
    assert riesgo["mensaje"].startswith("Faltan") and "bonificación" in riesgo["mensaje"]


# ------------------------------------------------------------------------------------------- 4. cuenta corriente vencida
def test_cuenta_corriente(retail_distribuidora):
    r = cliente().get("/retail/api/distribuidor/cuenta-corriente").json()
    moroso = _fila(r["clientes"], CASOS["moroso"]["cliente"])
    assert moroso["sigue_comprando"] and moroso["vencido"] > 0 and moroso["dias_mayor_atraso"] > 30
    limite = _fila(r["clientes"], CASOS["limite"]["cliente"])
    assert limite["supera_limite"] and limite["bloqueo_sugerido"] and limite["saldo"] > CASOS["limite"]["limite"]
    for c in r["clientes"]:
        assert abs(sum(c[t] for t in distribuidor.TRAMOS) + c["a_favor"] - c["saldo"]) < 0.05
    assert abs(r["totales"]["vencido"] - sum(c["vencido"] for c in r["clientes"])) < 1
    saldo = _q("SELECT sum(saldo) s FROM documentos_cc WHERE saldo > 0")[0]["s"]
    assert abs(float(saldo) - r["totales"]["saldo"]) < 1
    assert r["por_vendedor"] and any(v["cobrado_30_dias"] > 0 for v in r["por_vendedor"])
    # Cobranzas registra un compromiso de pago; un vendedor no puede.
    cid = moroso["cliente_id"]
    assert cliente("cobranzas@valle.demo").post("/retail/api/distribuidor/compromisos",
                                                json={"cliente_id": cid, "fecha": "2026-10-01", "monto": 50000}).status_code == 201
    assert cliente("javier@valle.demo").post("/retail/api/distribuidor/compromisos",
                                             json={"cliente_id": cid, "fecha": "2026-10-01", "monto": 50000}).status_code == 403


def test_tramos_de_antiguedad():
    assert [distribuidor.tramo(d) for d in (-3, 0, 1, 30, 31, 60, 61, 90, 91)] == \
        ["a_vencer", "a_vencer", "d0_30", "d0_30", "d31_60", "d31_60", "d61_90", "d61_90", "d90_mas"]


# ------------------------------------------------------------------------------------------- 5. Pareto y 3. qué comprar hoy
def test_pareto_de_clientes_y_productos(retail_distribuidora):
    r = cliente().get("/retail/api/distribuidor/pareto?periodo=90d").json()
    for clave in ("clientes", "productos"):
        filas = r[clave]["filas"]
        assert filas and abs(sum(f["participacion"] for f in filas) - 1) < 1e-3
        assert filas[0]["clase"] == "A" and filas == sorted(filas, key=lambda f: -f["ganancia"])
        assert r[clave]["clase_a"] < len(filas)


def test_pedidos_alimentan_la_reposicion(retail_distribuidora):
    """La demanda de los pedidos (con lo que no se entregó por falta de stock) entra a «Comprar y reponer» por el canal mayorista."""
    org = _org()
    sin_stock = _q("""SELECT s.producto_id FROM stock_actual s WHERE s.org_id = %s AND s.cantidad = 0
                      AND EXISTS (SELECT 1 FROM pedidos_venta_lineas l WHERE l.producto_id = s.producto_id AND l.faltante_stock > 0)""", (org,))
    assert sin_stock
    pid = sin_stock[0]["producto_id"]
    agg = _q("""SELECT sum(a.unidades) u, sum(a.facturacion_neta) n FROM agg_producto_ubicacion_dia a JOIN canales c ON c.id = a.canal_id
                WHERE a.producto_id = %s AND c.codigo = 'mayorista' AND a.fecha > %s""", (pid, HOY - timedelta(days=30)))[0]
    pedido = _q(f"""SELECT sum(CASE WHEN p.estado IN ('entregado','entregado_parcial') THEN l.cantidad_entregada ELSE l.cantidad_pedida END + l.faltante_stock) u,
                           sum(l.precio * {distribuidor.FACTURABLE}) n
                    FROM pedidos_venta p JOIN pedidos_venta_lineas l ON l.pedido_id = p.id
                    WHERE l.producto_id = %s AND {distribuidor.COMPRA} AND p.fecha > %s""", (pid, HOY - timedelta(days=30)))[0]
    assert agg["u"] == pedido["u"] and abs(agg["n"] - pedido["n"]) < Decimal("0.05")
    filas = cliente().get("/retail/api/comprar").json()["filas"]
    fila = next(f for f in filas if f["producto_id"] == pid)
    assert fila["semaforo"] == "rojo" and Decimal(fila["cantidad_sugerida"]) > 0
    r = cliente().get("/retail/api/distribuidor/pedidos?periodo=mes").json()
    assert 0.8 < r["fill_rate_unidades"] < 1 and r["no_facturado_faltantes"] > 0
    assert any(f["producto_id"] == pid for f in r["faltantes"])


# ------------------------------------------------------------------------------------------- vista del vendedor y aislamiento
def test_el_vendedor_solo_ve_su_cartera(retail_distribuidora):
    carla = cliente("carla@valle.demo")
    vid = _q("SELECT id FROM vendedores WHERE nombre = 'Carla Mendoza'")[0]["id"]
    suyos = {f["id"] for f in _q("SELECT id FROM clientes_b2b WHERE vendedor_id = %s", (vid,))}
    filas = carla.get("/retail/api/distribuidor/clientes").json()["filas"]
    assert {f["cliente_id"] for f in filas} == suyos
    ajeno = _q("SELECT id FROM clientes_b2b WHERE vendedor_id <> %s LIMIT 1", (vid,))[0]["id"]
    assert carla.get(f"/retail/api/distribuidor/clientes/{ajeno}").status_code == 404
    cc = carla.get("/retail/api/distribuidor/cuenta-corriente").json()["clientes"]
    assert {c["cliente_id"] for c in cc} <= suyos
    # La base acota también pedidos y comprobantes (RLS), no solo la pantalla.
    from app.retail.sesiones import contexto_de_sesion  # noqa: F401
    ctx = db.Contexto(usuario_id=0, org_id=_org(), rol="vendedor", vendedor_id=vid, todas_ubicaciones=True)
    with db.transaccion(ctx) as conn:
        assert {f["cliente_id"] for f in db.filas(conn, "SELECT DISTINCT cliente_id FROM pedidos_venta")} <= suyos
        assert {f["cliente_id"] for f in db.filas(conn, "SELECT DISTINCT cliente_id FROM documentos_cc")} <= suyos
    for ruta in ("/distribuidor/vendedores", "/distribuidor/pareto", "/comprar", "/inicio", "/productos/1"):
        assert carla.get(f"/retail/api{ruta}").status_code == 403, ruta
    assert carla.get("/retail/api/yo").status_code == 200


def test_mi_cartera_y_visitas(retail_distribuidora):
    carla = cliente("carla@valle.demo")
    r = carla.get("/retail/api/distribuidor/mi-cartera").json()
    assert r["vendedor"]["nombre"] == "Carla Mendoza" and r["hoy"] == HOY.isoformat()   # el «hoy» es el de la empresa, no el de su cartera
    parada = _fila(r["ruta"], CASOS["riesgo"]["cliente"])          # el cliente en riesgo está en la ruta de hoy, con qué ofrecerle
    assert parada["estado"] == "en_riesgo" and parada["oportunidades"]
    assert r["meta"] and r["meta"]["meta_mes"] and r["resumen"]["en_riesgo"] >= 1
    assert carla.post("/retail/api/distribuidor/visitas", json={"cliente_id": parada["cliente_id"], "resultado": "pedido"}).status_code == 200
    r = carla.get("/retail/api/distribuidor/mi-cartera").json()
    assert _fila(r["ruta"], CASOS["riesgo"]["cliente"])["visita"] == {"cliente_id": parada["cliente_id"], "realizada": True, "resultado": "pedido"}
    ajeno = _q("SELECT id FROM clientes_b2b WHERE vendedor_id <> %s LIMIT 1", (r["vendedor"]["id"],))[0]["id"]
    assert carla.post("/retail/api/distribuidor/visitas", json={"cliente_id": ajeno, "resultado": "pedido"}).status_code == 404
    # El jefe de ventas ve la cartera de cualquiera; el vendedor no puede pedir la de otro.
    jefe = cliente("jefe@valle.demo")
    otro = _q("SELECT id FROM vendedores WHERE nombre = 'Diego Ruiz'")[0]["id"]
    assert jefe.get(f"/retail/api/distribuidor/mi-cartera?vendedor={otro}").json()["vendedor"]["nombre"] == "Diego Ruiz"
    assert carla.get(f"/retail/api/distribuidor/mi-cartera?vendedor={otro}").json()["vendedor"]["nombre"] == "Carla Mendoza"


def test_sin_modo_distribuidor_no_hay_pantallas(retail_demo):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": "dueno@norte.demo", "clave": CLAVE_DEMO}).status_code == 200
    r = c.get("/retail/api/distribuidor/clientes")
    assert r.status_code == 403 and "modo distribuidor" in r.json()["detail"]
    assert "pedidos" not in {t["tipo"] for t in c.get("/retail/api/importar/tipos").json()}


# ------------------------------------------------------------------------------------------- ingesta: archivos y Odoo
def _importar(c, tipo, nombre, texto, mapeo):
    a = c.post("/retail/api/importar/analizar", data={"tipo": tipo}, files={"archivo": (nombre, texto.encode(), "text/csv")})
    assert a.status_code == 200, a.text
    lote = a.json()["lote_id"]
    v = c.post(f"/retail/api/importar/{lote}/validar", json={"mapeo": mapeo})
    assert v.status_code == 200, v.text
    assert v.json()["con_error"] == 0, v.json()["errores"]
    r = c.post(f"/retail/api/importar/{lote}/confirmar")
    assert r.status_code == 200, r.text
    return r.json()


def test_importar_clientes_pedidos_y_cuenta_corriente(retail_distribuidora, monkeypatch):
    from app.retail import api_ingesta
    monkeypatch.setattr(api_ingesta, "recalcular_en_segundo_plano", lambda org, desde=None: None)
    c = cliente()
    assert {"clientes", "pedidos", "cuenta_corriente"} <= {t["tipo"] for t in c.get("/retail/api/importar/tipos").json()}
    clientes = "Codigo;Razon social;Zona;Canal;Vendedor;Lista;Limite\nC1;Almacén Nuevo SRL;Salta Centro;almacen;Vendedora Nueva;Especial;100000\n" \
               "C2;Kiosco Nuevo;Salta Norte;kiosco;Diego Ruiz;;\n"
    m = {"codigo": "Codigo", "razon_social": "Razon social", "zona": "Zona", "canal": "Canal", "vendedor": "Vendedor", "lista": "Lista",
         "limite_credito": "Limite"}
    assert _importar(c, "clientes", "clientes.csv", clientes, m)["nuevos"] == 2
    assert _importar(c, "clientes", "clientes2.csv", clientes.replace("100000", "150000"), m)["actualizados"] == 2
    nuevo = _q("SELECT c.limite_credito, v.nombre FROM clientes_b2b c JOIN vendedores v ON v.id = c.vendedor_id WHERE c.razon_social = 'Almacén Nuevo SRL'")[0]
    assert nuevo["limite_credito"] == 150000 and nuevo["nombre"] == "Vendedora Nueva"
    producto = _q("SELECT codigo_interno FROM productos WHERE org_id = %s ORDER BY id LIMIT 2", (_org(),))
    p1, p2 = producto[0]["codigo_interno"], producto[1]["codigo_interno"]
    pedidos = (f"Pedido;Fecha;Cliente;Producto;Cant;Entregada;Precio;Estado;Motivo\nX-1;20/09/2026;C1;{p1};10;10;100;;\nX-1;20/09/2026;C1;{p2};5;2;200;;\n"
               f"X-2;21/09/2026;C2;{p1};3;0;100;rechazado;Comercio cerrado\nX-3;24/09/2026;C2;{p1};4;;100;;\n")
    mp = {"pedido": "Pedido", "fecha": "Fecha", "cliente": "Cliente", "producto": "Producto", "cantidad": "Cant", "entregada": "Entregada",
          "precio": "Precio", "estado": "Estado", "motivo": "Motivo"}
    r = _importar(c, "pedidos", "pedidos.csv", pedidos, mp)
    assert r["importadas"] == 3 and r["lineas"] == 4 and r["desde"] == "2026-09-20"
    estados = {f["numero"]: (f["estado"], f["total"], f["total_entregado"]) for f in _q("SELECT numero, estado, total, total_entregado FROM pedidos_venta WHERE origen='archivo'")}
    assert estados == {"X-1": ("entregado_parcial", 2000, 1400), "X-2": ("rechazado", 300, 0), "X-3": ("tomado", 400, 0)}
    assert _q("SELECT motivo FROM entregas e JOIN pedidos_venta p ON p.id = e.pedido_id WHERE p.numero = 'X-2'")[0]["motivo"] == "Comercio cerrado"
    assert _importar(c, "pedidos", "pedidos-otra-vez.csv", pedidos + "\n", mp)["duplicadas"] == 3
    cc = "Cliente;Tipo;Numero;Fecha;Vence;Importe;Saldo\nC1;FA;0001-1;20/09/2026;30/09/2026;2420;2420\nC1;Recibo;R-1;22/09/2026;;1000;0\n"
    mc = {"cliente": "Cliente", "tipo": "Tipo", "numero": "Numero", "fecha": "Fecha", "vencimiento": "Vence", "importe": "Importe", "saldo": "Saldo"}
    assert _importar(c, "cuenta_corriente", "cc.csv", cc, mc)["nuevos"] == 2
    assert _importar(c, "cuenta_corriente", "cc2.csv", cc.replace(";2420\n", ";1420\n"), mc)["actualizados"] == 2
    docs = {f["numero"]: (f["importe"], f["saldo"]) for f in _q("SELECT numero, importe, saldo FROM documentos_cc WHERE origen='archivo'")}
    assert docs == {"0001-1": (2420, 1420), "R-1": (-1000, 0)}
    # Un archivo con un cliente que no existe se rechaza fila por fila.
    a = c.post("/retail/api/importar/analizar", data={"tipo": "pedidos"},
               files={"archivo": ("malo.csv", f"Pedido;Fecha;Cliente;Producto;Cant;Precio\nZ;20/09/2026;NO-EXISTE;{p1};1;1\n".encode(), "text/csv")}).json()
    v = c.post(f"/retail/api/importar/{a['lote_id']}/validar", json={"mapeo": {k: mp[k] for k in ("pedido", "fecha", "cliente", "producto", "cantidad", "precio")}}).json()
    assert v["con_error"] == 1 and "No existe el cliente" in v["errores"][0]["error"]


M2O = lambda i, n="": [i, n] if i else False  # noqa: E731


def test_odoo_trae_clientes_pedidos_y_cuenta_corriente(retail_distribuidora, monkeypatch):
    from test_retail_odoo import CLAVE, CRED, OdooPos
    datos = {
        "res.partner": [
            {"id": 1, "name": "Almacén Odoo", "vat": "20-1", "city": "Salta", "state_id": M2O(9, "Salta"), "user_id": M2O(7, "Vera Odoo"),
             "credit_limit": 500000.0, "category_id": [[3, "Almacén"]], "customer_rank": 2, "parent_id": False, "commercial_partner_id": M2O(1)},
            {"id": 2, "name": "Contacto de compras", "parent_id": M2O(1), "commercial_partner_id": M2O(1), "customer_rank": 1},
        ],
        "sale.order": [
            {"id": 10, "name": "S0010", "partner_id": M2O(2), "user_id": M2O(7, "Vera Odoo"), "date_order": "2026-09-20 10:00:00", "state": "sale",
             "warehouse_id": M2O(1), "write_date": "2026-09-21 10:00:00"},
            {"id": 11, "name": "S0011", "partner_id": M2O(1), "user_id": M2O(7, "Vera Odoo"), "date_order": "2026-09-22 10:00:00", "state": "cancel",
             "warehouse_id": M2O(1), "write_date": "2026-09-22 10:00:00"},
        ],
        "sale.order.line": [
            {"id": 100, "order_id": M2O(10), "product_id": M2O(500), "product_uom_qty": 10.0, "qty_delivered": 8.0, "price_unit": 100.0, "discount": 10.0,
             "price_subtotal": 900.0, "display_type": False},
            {"id": 101, "order_id": M2O(10), "product_id": False, "display_type": "line_section", "name": "Sección"},
        ],
        "account.move": [
            {"id": 50, "name": "FA-A 0001-00000050", "partner_id": M2O(1), "move_type": "out_invoice", "invoice_date": "2026-09-21",
             "invoice_date_due": "2026-10-21", "amount_total": 871.2, "amount_residual": 871.2, "state": "posted", "write_date": "2026-09-21 10:00:00"},
            {"id": 51, "name": "NC-A 0001-00000003", "partner_id": M2O(1), "move_type": "out_refund", "invoice_date": "2026-09-22",
             "invoice_date_due": "2026-09-22", "amount_total": 100.0, "amount_residual": 0.0, "state": "posted", "write_date": "2026-09-22 10:00:00"},
        ],
        "account.payment": [{"id": 70, "name": "PAGO/1", "partner_id": M2O(1), "date": "2026-09-23", "amount": 300.0, "partner_type": "customer",
                             "state": "posted", "payment_type": "inbound"}],
    }
    falso = OdooPos(copy.deepcopy(datos))
    monkeypatch.setattr(odoo, "_http", falso)
    c = odoo_pos.cliente_de({**CRED, "api_key": CLAVE})
    org = _org()
    pid = _q("SELECT id FROM productos WHERE org_id=%s ORDER BY id LIMIT 1", (org,))[0]["id"]
    dep = _q("SELECT id FROM ubicaciones WHERE org_id=%s", (org,))[0]["id"]
    ctx = db.Contexto(usuario_id=0, org_id=org, rol="dueno", todas_ubicaciones=True)

    def sincronizar():
        with db.transaccion(ctx) as conn:
            return odoo_distribuidor.sincronizar(conn, ctx, c, 99, {1: dep}, {"mapa": {500: pid}}, datetime(2026, 1, 1))
    r = sincronizar()
    assert r["clientes_nuevos"] == 1 and r["pedidos_nuevos"] == 2 and r["comprobantes"] == 2 and r["cobros"] == 1
    cli = _q("SELECT c.id, c.zona, c.canal, c.limite_credito, v.nombre FROM clientes_b2b c JOIN vendedores v ON v.id = c.vendedor_id "
             "WHERE c.codigo_externo = 'odoo:partner:1'")[0]
    assert (cli["zona"], cli["canal"], cli["limite_credito"], cli["nombre"]) == ("Salta", "almacén", 500000, "Vera Odoo")
    pedidos = {f["numero"]: f for f in _q("SELECT numero, cliente_id, estado, total, total_entregado, ubicacion_id FROM pedidos_venta WHERE origen='odoo'")}
    assert pedidos["S0010"]["cliente_id"] == cli["id"]           # el pedido del contacto hijo es de su empresa
    assert (pedidos["S0010"]["estado"], pedidos["S0010"]["total"], pedidos["S0010"]["total_entregado"]) == ("entregado_parcial", 900, 720)
    assert pedidos["S0011"]["estado"] == "anulado" and pedidos["S0010"]["ubicacion_id"] == dep
    linea = _q("SELECT precio_lista, precio, cantidad_entregada FROM pedidos_venta_lineas l JOIN pedidos_venta p ON p.id = l.pedido_id WHERE p.numero='S0010'")
    assert len(linea) == 1 and (linea[0]["precio_lista"], linea[0]["precio"], linea[0]["cantidad_entregada"]) == (100, 90, 8)
    docs = {f["tipo"]: (f["importe"], f["saldo"]) for f in _q("SELECT tipo, importe, saldo FROM documentos_cc WHERE origen='odoo'")}
    assert docs == {"factura": (Decimal("871.20"), Decimal("871.20")), "nota_credito": (-100, 0), "recibo": (-300, 0)}
    # Se entrega el resto y se paga la factura: la próxima sincronización actualiza, sin duplicar.
    falso.datos["sale.order.line"][0]["qty_delivered"] = 10.0
    falso.datos["account.move"][0]["amount_residual"] = 0.0
    r = sincronizar()
    assert r["pedidos_nuevos"] == 0 and r["pedidos_actualizados"] == 2
    assert _q("SELECT estado FROM pedidos_venta WHERE numero='S0010'")[0]["estado"] == "entregado"
    assert _q("SELECT count(*) n FROM pedidos_venta_lineas l JOIN pedidos_venta p ON p.id = l.pedido_id WHERE p.numero='S0010'")[0]["n"] == 1
    assert _q("SELECT saldo FROM documentos_cc WHERE tipo='factura' AND origen='odoo'")[0]["saldo"] == 0


def test_demo_completa_de_la_distribuidora(retail_distribuidora):
    org = _org()
    n = _q("""SELECT (SELECT count(*) FROM vendedores WHERE org_id=%(o)s) v, (SELECT count(DISTINCT zona) FROM clientes_b2b WHERE org_id=%(o)s) z,
                     (SELECT count(*) FROM listas_precios_clientes WHERE org_id=%(o)s) l, (SELECT count(*) FROM objetivos_marca WHERE org_id=%(o)s) m,
                     (SELECT count(*) FROM pedidos_venta WHERE org_id=%(o)s AND estado='entregado_parcial') parciales,
                     (SELECT count(*) FROM pedidos_venta WHERE org_id=%(o)s AND estado='rechazado') rechazos,
                     (SELECT count(*) FROM rutas WHERE org_id=%(o)s) rutas,
                     (SELECT count(*) FROM usuarios WHERE org_id=%(o)s AND rol='vendedor' AND vendedor_id IS NOT NULL) usuarios_vendedor,
                     (SELECT modos FROM organizaciones WHERE id=%(o)s) modos""", {"o": org})[0]
    assert (n["v"], n["z"], n["l"], n["m"], n["rutas"], n["usuarios_vendedor"]) == (6, 4, 3, 3, 36, 6)
    assert n["parciales"] > 0 and n["rechazos"] > 0 and n["modos"] == ["distribuidor"]
    tramos = cliente().get("/retail/api/distribuidor/cuenta-corriente").json()["totales"]
    assert all(tramos[t] > 0 for t in ("d0_30", "d31_60", "d61_90"))


def test_pantallas_del_distribuidor_cargan_en_menos_de_3_segundos(retail_distribuidora):
    from app.retail import tiempos
    vid = _q("SELECT id FROM vendedores WHERE nombre = 'Carla Mendoza'")[0]["id"]
    pantallas = {**tiempos.PANTALLAS_MODO_DISTRIBUIDOR, "Mi cartera (vendedor)": [f"/distribuidor/mi-cartera?vendedor={vid}"]}
    filas = tiempos.medir(cliente().get, pantallas=pantallas)
    assert all(f["ok"] for f in filas), [f for f in filas if not f["ok"]]


# ------------------------------------------------------------------------------------------- Fase 2 · rutas y cobertura (12B.3)
def test_cumplimiento_y_efectividad_de_visitas(retail_distribuidora):
    r = cliente("jefe@valle.demo").get("/retail/api/distribuidor/rutas?periodo=90d").json()
    vs = {v["vendedor"]: v for v in r["cumplimiento"]["vendedores"]}
    assert len(vs) == 6
    # Hernán no hace la ruta del sábado: es su peor día y está muy por debajo de lo que cumple el resto del equipo.
    hernan = vs["Hernán Ibarra"]["dias"]
    assert hernan["Sábado"]["cumplimiento"] == min(d["cumplimiento"] for d in hernan.values()) and hernan["Sábado"]["cumplimiento"] < 0.6
    assert r["cumplimiento"]["vendedores"] == sorted(r["cumplimiento"]["vendedores"], key=lambda v: v["cumplimiento"])
    total = _q("""SELECT count(*) FILTER (WHERE planificada) p, count(*) FILTER (WHERE planificada AND realizada) r,
                         count(*) FILTER (WHERE realizada AND resultado = 'pedido') c, count(*) FILTER (WHERE realizada) rt
                  FROM visitas WHERE fecha BETWEEN %s AND %s""", (HOY - timedelta(days=89), HOY))[0]
    t = r["cumplimiento"]["total"]
    assert (t["planificadas"], t["realizadas"]) == (total["p"], total["r"])
    assert abs(t["efectividad"] - total["c"] / total["rt"]) < 1e-3 and 0 < t["efectividad"] < 1
    assert all(set(v["dias"]) <= set(r["cumplimiento"]["dias"]) for v in vs.values())
    assert cliente("carla@valle.demo").get("/retail/api/distribuidor/rutas").status_code == 403


def test_clientes_sin_visita(retail_distribuidora):
    c = cliente("jefe@valle.demo")
    r = c.get("/retail/api/distribuidor/rutas").json()["sin_visita"]
    assert r["dias"] == 14 and r["filas"]
    assert all(f["dias_sin_visita"] is None or f["dias_sin_visita"] > 14 for f in r["filas"])
    assert CASOS["perdido"]["cliente"] in {f["cliente"] for f in r["filas"]}           # al que dejó de comprar se lo dejó de visitar
    assert c.put("/retail/api/distribuidor/rutas/dias-sin-visita", json={"dias": 60}).status_code == 200
    menos = c.get("/retail/api/distribuidor/rutas").json()["sin_visita"]
    assert menos["dias"] == 60 and len(menos["filas"]) < len(r["filas"])


def test_cobertura_por_zona_y_prospectos(retail_distribuidora):
    c = cliente("jefe@valle.demo")
    zonas = {z["zona"]: z for z in c.get("/retail/api/distribuidor/rutas").json()["cobertura"]["zonas"]}
    assert set(zonas) == set(demo.ZONAS)
    assert min(zonas.values(), key=lambda z: z["cobertura"])["zona"] == "Valle de Lerma"
    for z in zonas.values():
        assert abs(z["cobertura"] - z["activos"] / (z["clientes"] + z["prospectos"])) < 1e-3
    lista = c.get("/retail/api/distribuidor/prospectos?zona=Valle de Lerma").json()
    assert len(lista) == zonas["Valle de Lerma"]["prospectos"]
    hernan = _q("SELECT id FROM vendedores WHERE nombre = 'Hernán Ibarra'")[0]["id"]
    nuevo = c.post(f"/retail/api/distribuidor/prospectos/{lista[0]['id']}/convertir", json={"vendedor_id": hernan})
    assert nuevo.status_code == 201
    assert _q("SELECT vendedor_id, zona FROM clientes_b2b WHERE id = %s", (nuevo.json()["cliente_id"],))[0] == {"vendedor_id": hernan, "zona": "Valle de Lerma"}
    despues = {z["zona"]: z for z in c.get("/retail/api/distribuidor/rutas").json()["cobertura"]["zonas"]}["Valle de Lerma"]
    assert (despues["prospectos"], despues["clientes"]) == (zonas["Valle de Lerma"]["prospectos"] - 1, zonas["Valle de Lerma"]["clientes"] + 1)
    assert c.post(f"/retail/api/distribuidor/prospectos/{lista[0]['id']}/convertir", json={"vendedor_id": hernan}).status_code == 404


def test_armar_rutas(retail_distribuidora):
    c = cliente("jefe@valle.demo")
    carla = _q("SELECT id FROM vendedores WHERE nombre = 'Carla Mendoza'")[0]["id"]
    rutas = c.get(f"/retail/api/distribuidor/rutas?vendedor={carla}").json()["rutas"]
    assert [d["nombre"] for d in rutas] == distribuidor.DIAS + ["Sin ruta"]
    jueves = [x["cliente_id"] for x in rutas[3]["clientes"]]
    otro = next(x["cliente_id"] for d in rutas[:6] if d["dia"] != 3 for x in d["clientes"])
    nuevo_orden = list(reversed(jueves + [otro]))                     # se suma un cliente de otro día y se invierte el recorrido
    r = c.put(f"/retail/api/distribuidor/rutas/{carla}/3", json={"clientes": nuevo_orden})
    assert r.status_code == 200 and [x["cliente_id"] for x in r.json()["rutas"][3]["clientes"]] == nuevo_orden
    ajeno = _q("SELECT id FROM clientes_b2b WHERE vendedor_id <> %s LIMIT 1", (carla,))[0]["id"]
    assert c.put(f"/retail/api/distribuidor/rutas/{carla}/3", json={"clientes": [ajeno]}).status_code == 400
    assert c.put(f"/retail/api/distribuidor/rutas/{carla}/6", json={"clientes": []}).status_code == 400
    # La ruta nueva es la que ve Carla hoy (jueves).
    ruta = cliente("carla@valle.demo").get("/retail/api/distribuidor/mi-cartera").json()["ruta"]
    assert [p["cliente_id"] for p in ruta] == [x for x in nuevo_orden if x in {p["cliente_id"] for p in ruta}]
    assert cliente("cobranzas@valle.demo").put(f"/retail/api/distribuidor/rutas/{carla}/3", json={"clientes": []}).status_code == 403


def test_importar_comercios_de_la_zona(retail_distribuidora, monkeypatch):
    from app.retail import api_ingesta
    monkeypatch.setattr(api_ingesta, "recalcular_en_segundo_plano", lambda org, desde=None: None)
    c = cliente()
    texto = f"Nombre;Direccion;Zona;Canal\nAlmacén Nuevo del Cerro;Belgrano 100;Salta Centro;almacen\n{CASOS['perdido']['cliente']};Mitre 1;Salta Centro;autoservicio\n"
    m = {"nombre": "Nombre", "direccion": "Direccion", "zona": "Zona", "canal": "Canal"}
    r = _importar(c, "prospectos", "comercios.csv", texto, m)
    assert r["importadas"] == 1 and r["ya_clientes"] == 1
    assert _importar(c, "prospectos", "comercios2.csv", texto + "\n", m)["importadas"] == 0
