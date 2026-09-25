"""Integración con Odoo: diagnóstico, mapeo a las tablas del diccionario y panel.

Usa un Odoo falso en memoria que entiende los dominios que usa el conector.
Contra un Odoo 17 real se probó con tools/odoo_local/seed_distribuidora.py.
"""
import pytest
from fastapi.testclient import TestClient

from app import config
from app.erp import conector, fuente
from app.integraciones import gestor, odoo
from app.permisos import obtener_usuario

M2O = lambda i, n="": [i, n] if i else False  # noqa: E731

DATOS = {
    "stock.warehouse": [{"id": 1, "name": "Central", "lot_stock_id": M2O(10)}, {"id": 2, "name": "Norte", "lot_stock_id": M2O(20)}],
    "res.users": [{"id": 7, "name": "Valentina"}, {"id": 8, "name": "Federico"}],
    "res.partner": [
        {"id": 100, "name": "Almacén Sol SA", "is_company": True, "customer_rank": 3, "supplier_rank": 0, "user_id": M2O(7),
         "property_payment_term_id": M2O(30), "credit_limit": 500000.0, "city": "Montevideo", "state_id": False,
         "category_id": [5], "create_date": "2024-02-01 10:00:00", "parent_id": False, "commercial_partner_id": M2O(100)},
        {"id": 101, "name": "Compras de Almacén Sol", "is_company": False, "customer_rank": 0, "supplier_rank": 0, "user_id": False,
         "property_payment_term_id": False, "credit_limit": 0, "city": False, "state_id": False, "category_id": [],
         "create_date": "2024-02-01 10:00:00", "parent_id": M2O(100), "commercial_partner_id": M2O(100)},
        {"id": 102, "name": "Kiosco Luna", "is_company": True, "customer_rank": 1, "supplier_rank": 0, "user_id": M2O(8),
         "property_payment_term_id": False, "credit_limit": 0, "city": False, "state_id": M2O(3, "Canelones"),
         "category_id": [], "create_date": "2025-05-03 09:00:00", "parent_id": False, "commercial_partner_id": M2O(102)},
        {"id": 200, "name": "Lácteos del Este", "is_company": True, "customer_rank": 0, "supplier_rank": 2, "user_id": False,
         "property_supplier_payment_term_id": M2O(30), "parent_id": False, "commercial_partner_id": M2O(200)},
    ],
    "res.partner.category": [{"id": 5, "name": "Autoservicio"}],
    "account.payment.term": [{"id": 30, "line_ids": [301]}],
    "account.payment.term.line": [{"id": 301, "nb_days": 30}],
    "product.product": [
        {"id": 50, "display_name": "[LEC-1] Leche entera 1 L", "name": "Leche entera 1 L", "categ_id": M2O(1, "Lácteos"),
         "standard_price": 38.0, "lst_price": 47.0, "seller_ids": [900], "use_expiration_date": True, "sale_ok": True},
        {"id": 51, "display_name": "Yerba 1 kg", "name": "Yerba 1 kg", "categ_id": M2O(2, "Almacén"),
         "standard_price": 185.0, "lst_price": 230.0, "seller_ids": [], "use_expiration_date": False, "sale_ok": True},
        {"id": 52, "display_name": "Producto discontinuado", "name": "Producto discontinuado", "categ_id": M2O(2, "Almacén"),
         "standard_price": 10.0, "lst_price": 20.0, "seller_ids": [], "use_expiration_date": False, "sale_ok": False},
    ],
    "product.supplierinfo": [{"id": 900, "partner_id": M2O(200), "delay": 2}],
    "stock.quant": [
        {"id": 1, "product_id": M2O(50), "quantity": 30.0, "location_id": 10},
        {"id": 2, "product_id": M2O(50), "quantity": 5.0, "location_id": 10},
        {"id": 3, "product_id": M2O(51), "quantity": 12.0, "location_id": 20},
    ],
    "sale.order": [
        {"id": 1, "date_order": "2026-09-01 14:00:00", "partner_id": M2O(101), "user_id": M2O(7), "warehouse_id": M2O(1), "state": "sale"},
        {"id": 2, "date_order": "2026-09-10 11:00:00", "partner_id": M2O(102), "user_id": M2O(8), "warehouse_id": M2O(2), "state": "cancel"},
        {"id": 3, "date_order": "2020-01-01 11:00:00", "partner_id": M2O(102), "user_id": M2O(8), "warehouse_id": M2O(2), "state": "sale"},
    ],
    "sale.order.line": [
        {"id": 11, "order_id": M2O(1), "product_id": M2O(50), "product_uom_qty": 10.0, "price_subtotal": 450.0, "purchase_price": 37.0, "display_type": False},
        {"id": 12, "order_id": M2O(1), "product_id": False, "product_uom_qty": 0, "price_subtotal": 0, "purchase_price": 0, "display_type": "line_note"},
        {"id": 13, "order_id": M2O(2), "product_id": M2O(52), "product_uom_qty": 2.0, "price_subtotal": 40.0, "purchase_price": 10.0, "display_type": False},
    ],
    "pos.order": [{"id": 5, "date_order": "2026-09-20 12:00:00", "partner_id": False, "user_id": M2O(7), "config_id": M2O(60), "state": "paid"}],
    "pos.order.line": [{"id": 70, "order_id": M2O(5), "product_id": M2O(51), "qty": 2.0, "price_subtotal": 460.0, "total_cost": 370.0}],
    "pos.config": [{"id": 60, "picking_type_id": M2O(61)}],
    "stock.picking.type": [{"id": 61, "warehouse_id": M2O(2)}],
    "account.move": [
        {"id": 400, "move_type": "out_invoice", "state": "posted", "partner_id": M2O(101), "commercial_partner_id": M2O(100),
         "invoice_date": "2026-08-01", "invoice_date_due": "2026-08-31", "amount_total_signed": 450.0,
         "amount_residual_signed": 0.0, "amount_residual": 0.0, "payment_state": "paid"},
        {"id": 401, "move_type": "out_invoice", "state": "posted", "partner_id": M2O(102), "commercial_partner_id": M2O(102),
         "invoice_date": "2026-09-10", "invoice_date_due": "2026-09-20", "amount_total_signed": 900.0,
         "amount_residual_signed": 900.0, "amount_residual": 900.0, "payment_state": "not_paid"},
    ],
    "account.move.line": [{"id": 4001, "move_id": M2O(400), "account_type": "asset_receivable", "matched_credit_ids": [77]}],
    "account.partial.reconcile": [{"id": 77, "max_date": "2026-09-05"}],
}
CAMPOS_EXTRA = {"sale.order.line": {"purchase_price"}, "account.move.line": {"account_type"}, "account.payment.term.line": {"nb_days"}}


def _valor(fila, campo):
    v = fila.get(campo)
    return v[0] if isinstance(v, list) and len(v) == 2 and isinstance(v[0], int) and isinstance(v[1], str) else v


def _cumple(fila, hoja):
    campo, op, valor = hoja
    if "." in campo:
        return True  # los filtros por campos relacionados no se simulan
    v = _valor(fila, campo)
    if op == "=":
        return v == valor or (valor is False and not v)
    if op == "!=":
        return (bool(v) if valor is False else v != valor)
    if op == ">":
        return (v or 0) > valor
    if op == ">=":
        return str(v or "") >= valor
    if op == "in":
        return v in valor
    if op == "child_of":
        return v == valor
    raise AssertionError(f"operador no simulado: {op}")


def _filtrar(filas, dominio):
    def evaluar(pila):
        elemento = pila.pop(0)
        if elemento == "|":
            a, b = evaluar(pila), evaluar(pila)
            return lambda f: a(f) or b(f)
        return lambda f, h=elemento: _cumple(f, h)
    condiciones = []
    pila = list(dominio)
    while pila:
        condiciones.append(evaluar(pila))
    return [f for f in filas if all(c(f) for c in condiciones)]


class OdooFalso:
    def __init__(self, clave="secreta", sin_permiso=(), reporte_ventas=(), falla_en=None):
        self.clave, self.sin_permiso, self.metodos = clave, set(sin_permiso), []
        self.reporte_ventas, self.falla_en = list(reporte_ventas), falla_en

    def __call__(self, url, payload):
        p = payload["params"]
        if p["service"] == "common":
            if p["method"] == "version":
                return {"result": {"server_version": "17.0"}}
            return {"result": 6 if p["args"][2] == self.clave else False}
        db, uid, clave, modelo, metodo, args, kwargs = p["args"]
        self.metodos.append(metodo)
        if self.falla_en == (modelo, metodo):
            raise ConnectionResetError("se cortó la conexión")
        if metodo == "check_access_rights":
            return {"result": modelo not in self.sin_permiso}
        if modelo in self.sin_permiso:
            return {"error": {"message": "Access Denied", "data": {"message": f"Sin acceso a {modelo}"}}}
        filas = DATOS.get(modelo, [])
        if metodo == "fields_get":
            campos = {c for f in filas for c in f} | CAMPOS_EXTRA.get(modelo, set())
            return {"result": {c: {"type": "char"} for c in campos}}
        if metodo == "search_count":
            return {"result": len(_filtrar(filas, args[0]))}
        if metodo == "read":
            return {"result": [f for f in filas if f["id"] in args[0]]}
        if metodo == "read_group":
            return {"result": self.reporte_ventas}
        if metodo == "search_read":
            encontrados = _filtrar(filas, args[0])
            ini = kwargs.get("offset", 0)
            return {"result": encontrados[ini:ini + kwargs.get("limit", 10**6)]}
        raise AssertionError(f"método no simulado: {metodo}")


def _contiene(real: dict, esperado: dict) -> bool:
    """El mapeo trae más campos que los que se comprueban: se comparan solo los esperados."""
    return {k: real.get(k) for k in esperado} == esperado


def _cliente(transporte=None, clave="secreta"):
    return odoo.ClienteOdoo("https://odoo.test", "empresa", "integracion@empresa.com", clave, transporte=transporte or OdooFalso(), pagina=2)


def test_diagnostico_ok():
    r = odoo.diagnosticar(_cliente())
    assert r["ok"] and [p["paso"] for p in r["pasos"]] == ["Servidor", "Acceso", "Permisos", "Datos"]
    assert r["conteos"] == {"clientes": 2, "productos": 2, "pedidos": 2, "facturas": 2}


def test_diagnostico_clave_mala():
    r = odoo.diagnosticar(_cliente(clave="otra"))
    assert not r["ok"] and r["pasos"][-1]["paso"] == "Acceso" and "rechazó" in r["pasos"][-1]["detalle"]


def test_diagnostico_sin_facturas_avisa_pero_sigue():
    r = odoo.diagnosticar(_cliente(OdooFalso(sin_permiso={"account.move"})))
    permisos = next(p for p in r["pasos"] if p["paso"] == "Permisos")
    assert r["ok"] and permisos["aviso"] and "facturas" in permisos["detalle"]


def test_diagnostico_sin_clientes_se_frena():
    r = odoo.diagnosticar(_cliente(OdooFalso(sin_permiso={"res.partner"})))
    assert not r["ok"] and r["pasos"][-1]["paso"] == "Permisos"


def test_servidor_caido():
    def caido(url, payload):
        raise OSError("Connection refused")
    r = odoo.diagnosticar(_cliente(caido))
    assert not r["ok"] and "Revisá la URL" in r["pasos"][0]["detalle"]


def test_solo_lectura():
    with pytest.raises(odoo.OdooError, match="solo lectura"):
        _cliente().ejecutar("res.partner", "write", [[1], {"name": "x"}])
    falso = OdooFalso()
    odoo.Extraccion(_cliente(falso), meses=12, hoy=__import__("datetime").date(2026, 9, 25)).ejecutar()
    assert set(falso.metodos) <= odoo._METODOS_LECTURA


def test_url_invalida():
    with pytest.raises(odoo.OdooError, match="https://"):
        odoo.ClienteOdoo("odoo.miempresa.com", "db", "u", "k")


@pytest.fixture
def extraccion():
    from datetime import date
    e = odoo.Extraccion(_cliente(), meses=12, hoy=date(2026, 9, 25))
    return e, e.ejecutar()


def test_mapeo_de_maestros(extraccion):
    _, t = extraccion
    assert [(s["id"], s["nombre"]) for s in t["sucursales"]] == [(1, "Central"), (2, "Norte")]
    clientes = {c["id"]: c for c in t["clientes"]}
    assert set(clientes) == {100, 102}  # el contacto 101 se agrupa en su empresa
    assert _contiene(clientes[100], {"id": 100, "razon_social": "Almacén Sol SA", "tipo": "Autoservicio", "zona": "Montevideo",
                             "vendedor_id": 7, "condicion_pago_dias": 30, "limite_credito": 500000.0, "fecha_alta": "2024-02-01"})
    assert clientes[102]["zona"] == "Canelones" and clientes[102]["condicion_pago_dias"] == 0
    assert {v["id"]: v["nombre"] for v in t["vendedores"]} == {7: "Valentina", 8: "Federico"}
    assert len(t["proveedores"]) == 1 and _contiene(t["proveedores"][0], {"id": 200, "nombre": "Lácteos del Este", "plazo_pago_dias": 30,
                                                                          "plazo_entrega_dias": 2})
    productos = {p["id"]: p for p in t["productos"]}
    assert productos[50]["descripcion"] == "Leche entera 1 L" and productos[50]["proveedor_id"] == 200 and productos[50]["perecedero"] == 1
    assert 52 in productos  # no es vendible hoy, pero aparece en una venta
    assert sorted((s["producto_id"], s["sucursal_id"], s["cantidad"]) for s in t["stock"]) == [(50, 1, 35.0), (51, 2, 12.0)]


def test_mapeo_de_ventas_y_cobranzas(extraccion):
    _, t = extraccion
    ventas = {v["id"]: v for v in t["ventas"]}
    assert set(ventas) == {1, 2, odoo.OFFSET_POS + 5}  # el pedido de 2020 queda fuera de los 12 meses
    # 14:00 UTC son las 11:00 en Montevideo
    assert _contiene(ventas[1], {"id": 1, "fecha": "2026-09-01", "hora": "11:00", "cliente_id": 100, "vendedor_id": 7, "sucursal_id": 1, "anulada": 0})
    assert ventas[2]["anulada"] == 1
    assert ventas[odoo.OFFSET_POS + 5]["sucursal_id"] == 2 and ventas[odoo.OFFSET_POS + 5]["cliente_id"] is None
    lineas = {l["venta_id"]: l for l in t["ventas_lineas"]}
    assert len(t["ventas_lineas"]) == 3  # la nota del pedido no es una línea de venta
    assert _contiene(lineas[1], {"venta_id": 1, "producto_id": 50, "cantidad": 10.0, "precio_unitario": 45.0, "costo_unitario": 37.0})
    assert lineas[odoo.OFFSET_POS + 5]["costo_unitario"] == 185.0 and lineas[odoo.OFFSET_POS + 5]["precio_unitario"] == 230.0
    cxc = {x["id"]: x for x in t["cxc"]}
    assert _contiene(cxc[400], {"id": 400, "cliente_id": 100, "fecha_emision": "2026-08-01", "fecha_vencimiento": "2026-08-31",
                                "fecha_cobro": "2026-09-05", "importe": 450.0, "saldo": 0.0, "tipo": "factura"})
    assert cxc[401]["fecha_cobro"] is None and cxc[401]["saldo"] == 900.0


def test_avisos_de_datos():
    from datetime import date
    DATOS["res.partner"][2]["user_id"] = False
    try:
        e = odoo.Extraccion(_cliente(OdooFalso(sin_permiso={"account.move"})), hoy=date(2026, 9, 25))
        t = e.ejecutar()
    finally:
        DATOS["res.partner"][2]["user_id"] = M2O(8)
    assert t["cxc"] == []
    assert any("facturas" in a for a in e.avisos) and any("no tienen «Vendedor»" in a for a in e.avisos)


@pytest.fixture
def entorno(tmp_path, monkeypatch, base_demo):
    env = tmp_path / ".env"
    env.write_text("# mi configuración\nANTHROPIC_API_KEY=sk-ant-x\nMAX_FILAS=200\n", encoding="utf-8")
    monkeypatch.setattr(gestor, "ENV", env)
    monkeypatch.setattr(gestor, "RUTA_ESTADO", tmp_path / "estado.json")
    monkeypatch.setattr(gestor, "RUTA_ODOO", tmp_path / "odoo.db")
    monkeypatch.setattr(fuente, "RUTA_ODOO", tmp_path / "odoo.db")
    monkeypatch.setattr(fuente, "URL_ODOO", f"sqlite:///{tmp_path / 'odoo.db'}")
    monkeypatch.setattr(fuente, "URL_DEMO", base_demo)
    monkeypatch.setattr(config, "ERP_URL", base_demo)
    for clave in gestor.CLAVES.values():
        monkeypatch.delenv(clave, raising=False)
    monkeypatch.delenv("ERP_URL", raising=False)
    falso = OdooFalso()
    monkeypatch.setattr(odoo, "_http", falso)
    yield env
    conector.olvidar_conexiones()


def test_guardar_en_env_sin_exponer_la_clave(entorno):
    gestor.guardar_odoo("https://odoo.test/", "empresa", "integracion@empresa.com", "secreta", 12, 60)
    texto = entorno.read_text()
    assert "ANTHROPIC_API_KEY=sk-ant-x" in texto and "# mi configuración" in texto
    assert "ODOO_URL=https://odoo.test\n" in texto and "ODOO_API_KEY=secreta" in texto
    assert "api_key" not in gestor.config_odoo() and gestor.config_odoo()["clave_guardada"]
    gestor.guardar_odoo("https://odoo.test", "otra", "integracion@empresa.com", None, 6, 0)  # sin clave: conserva
    texto = entorno.read_text()
    assert texto.count("ODOO_API_KEY=") == 1 and "ODOO_API_KEY=secreta" in texto and "ODOO_DB=otra" in texto
    with pytest.raises(ValueError):
        gestor.guardar_odoo("https://odoo.test", "x", "u", None, 12, 7)  # intervalo no válido


def test_panel_completo(entorno):
    from app import main

    api = TestClient(main.app)
    datos = {"url": "https://odoo.test", "db": "empresa", "usuario": "integracion@empresa.com", "api_key": "secreta", "meses": 12, "cada_min": 0}
    inicial = api.get("/integraciones").json()
    assert inicial["odoo"]["config"]["clave_guardada"] is False
    assert {p["id"] for p in inicial["plataformas"] if p["estado"] == "disponible"} == {"odoo", "archivos", "sql"}
    assert api.post("/integraciones/odoo/sincronizar").status_code == 400  # sin configurar

    assert api.post("/integraciones/odoo/probar", json={**datos, "api_key": "mala"}).json()["ok"] is False
    assert api.post("/integraciones/odoo/probar", json=datos).json()["ok"] is True
    assert api.post("/integraciones/odoo", json=datos).status_code == 200
    assert "secreta" not in api.get("/integraciones").text

    entrada = gestor.sincronizar_odoo()  # bloqueante, igual que la del botón
    assert entrada["ok"], entrada
    fuente.usar("odoo")
    estado = api.get("/integraciones").json()
    assert estado["fuente"]["fuente"] == "odoo" and estado["fuente"]["tablas"]["clientes"] == 2
    assert estado["odoo"]["ultima_ok"]["conteos"]["ventas"] == 3

    # La cartera del vendedor funciona igual con los datos de Odoo
    usuarios = {u["id"] for u in api.get("/usuarios").json()}
    assert {"vendedor:7", "vendedor:8"} <= usuarios
    como_valentina = api.post("/consulta", json={"usuario_id": "vendedor:7", "sql": "SELECT razon_social FROM clientes"}).json()
    assert como_valentina["filas"] == [["Almacén Sol SA"]]
    deuda = api.post("/consulta", json={"usuario_id": "vendedor:8", "sql": "SELECT SUM(saldo) FROM cxc"}).json()
    assert deuda["filas"] == [[900.0]]


def test_sincronizacion_fallida_conserva_la_base(entorno, monkeypatch):
    gestor.guardar_odoo("https://odoo.test", "empresa", "integracion@empresa.com", "secreta", 12, 0)
    assert gestor.sincronizar_odoo()["ok"]
    antes = gestor.RUTA_ODOO.read_bytes()
    monkeypatch.setattr(odoo, "_http", OdooFalso(clave="cambiada"))
    fallida = gestor.sincronizar_odoo()
    assert not fallida["ok"] and "rechazó" in fallida["error"]
    assert gestor.RUTA_ODOO.read_bytes() == antes
    assert [h["ok"] for h in gestor.estado_odoo()["historial"]] == [False, True]


def test_cuenta_regresiva(entorno, monkeypatch):
    gestor.guardar_odoo("https://odoo.test", "empresa", "integracion@empresa.com", "secreta", 12, 0)
    assert gestor.estado_odoo()["segundos_para_proxima"] is None  # automática apagada
    gestor.guardar_odoo("https://odoo.test", "empresa", "integracion@empresa.com", None, 12, 60)
    assert gestor.estado_odoo()["segundos_para_proxima"] == 0  # nunca sincronizó: arranca ya
    entrada = gestor.sincronizar_odoo()
    monkeypatch.setattr(gestor.time, "time", lambda: entrada["ts"] + 10 * 60)
    estado = gestor.estado_odoo()
    assert estado["segundos_para_proxima"] == 50 * 60 and estado["cada_min"] == 60
    monkeypatch.setattr(gestor.time, "time", lambda: entrada["ts"] + 2 * 3600)
    assert gestor.estado_odoo()["segundos_para_proxima"] == 0


def test_modulo_que_falla_no_frena_el_resto():
    from datetime import date

    class SinCompras(OdooFalso):
        def __call__(self, url, payload):
            p = payload["params"]
            if p["service"] == "object" and p["args"][3] == "sale.order.line" and p["args"][4] == "search_read":
                return {"error": {"message": "boom", "data": {"message": "campo inexistente"}}}
            return super().__call__(url, payload)

    e = odoo.Extraccion(_cliente(SinCompras()), hoy=date(2026, 9, 25))
    t = e.ejecutar()
    assert any("ventas" in a and "campo inexistente" in a for a in e.avisos)
    assert not t.get("ventas") and not t.get("ventas_lineas")  # se deshace el paso entero, no queda a medias
    assert t["clientes"] and t["cxc"]  # el resto se sincroniza igual


def test_corte_de_conexion_cancela_y_conserva_la_base(entorno, monkeypatch):
    gestor.guardar_odoo("https://odoo.test", "empresa", "integracion@empresa.com", "secreta", 12, 0)
    assert gestor.sincronizar_odoo()["ok"]
    antes = gestor.RUTA_ODOO.read_bytes()
    monkeypatch.setattr(odoo, "_http", OdooFalso(falla_en=("account.move", "search_read")))
    fallida = gestor.sincronizar_odoo()
    assert not fallida["ok"] and "conexión" in fallida["error"]
    assert gestor.RUTA_ODOO.read_bytes() == antes


def test_control_contra_reporte_de_ventas():
    from datetime import date

    e = odoo.Extraccion(_cliente(), hoy=date(2026, 9, 25))
    t = e.ejecutar()
    # Lo que devolvería Odoo en "Análisis de ventas": pedido 1 (450 + IVA) y el ticket de caja (460), en setiembre.
    reporte = [{"__range": {"date:month": {"from": "2026-09-01", "to": "2026-10-01"}}, "team_id": False,
                "price_subtotal": 910.0, "price_total": 910.0, "product_uom_qty": 12.0, "nbr": 2}]
    bien = odoo.control_ventas(_cliente(OdooFalso(reporte_ventas=reporte)), t, 12, zona="America/Montevideo", hoy=date(2026, 9, 25))
    assert bien["coinciden"] and bien["filas"][0]["plataforma_sin_impuestos"] == 910.0
    reporte[0]["price_subtotal"] = 1500.0
    mal = odoo.control_ventas(_cliente(OdooFalso(reporte_ventas=reporte)), t, 12, zona="America/Montevideo", hoy=date(2026, 9, 25))
    assert not mal["coinciden"] and mal["filas"][0]["diferencia"] == -590.0
