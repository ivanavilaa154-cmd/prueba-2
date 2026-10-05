"""SPEC v2 · modos de empresa, roles del modo distribuidor y cartera del vendedor (secciones 1, 2 y 12B)."""
from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from app.retail import db
from app.retail.semilla import CLAVE_DEMO


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _empresa(c, **cambios):
    e = c.get("/retail/api/yo").json()["empresa"]
    datos = {k: e[k] for k in ("nombre", "cuit", "zona_horaria", "moneda", "modelo_abastecimiento", "consentimiento_datos")}
    datos["modos"] = e.get("modos", ["comercio"])
    return c.put("/retail/api/empresa", json={**datos, **cambios})


def _cartera(org_id):
    """Dos vendedores con un cliente, un pedido y una factura cada uno."""
    ids = {}
    with db.transaccion(superadmin=True, org_id=org_id) as conn:
        prod = db.fila(conn, "SELECT id FROM productos WHERE org_id=%s ORDER BY id LIMIT 1", (org_id,))["id"]
        for nombre in ("Ana", "Beto"):
            v = db.fila(conn, "INSERT INTO vendedores (org_id, nombre, zona) VALUES (%s,%s,'Centro') RETURNING id", (org_id, nombre))["id"]
            cli = db.fila(conn, "INSERT INTO clientes_b2b (org_id, razon_social, vendedor_id) VALUES (%s,%s,%s) RETURNING id",
                          (org_id, f"Almacén de {nombre}", v))["id"]
            p = db.fila(conn, "INSERT INTO pedidos_venta (org_id, numero, cliente_id, vendedor_id, fecha, total) VALUES (%s,%s,%s,%s,%s,100) RETURNING id",
                        (org_id, f"P-{nombre}", cli, v, date(2026, 9, 1)))["id"]
            with conn.cursor() as cur:
                cur.execute("INSERT INTO pedidos_venta_lineas (org_id, pedido_id, producto_id, cantidad_pedida, precio_lista, precio) "
                            "VALUES (%s,%s,%s,1,100,100)", (org_id, p, prod))
                cur.execute("INSERT INTO documentos_cc (org_id, cliente_id, tipo, numero, fecha, importe, saldo) VALUES (%s,%s,'factura',%s,%s,121,121)",
                            (org_id, cli, f"F-{nombre}", date(2026, 9, 1)))
            ids[nombre] = v
    return ids


def test_modos_de_empresa(retail_demo):
    c = cliente()
    assert _empresa(c, modos=["comercio", "fantasia"]).status_code == 400
    assert _empresa(c, modos=[]).status_code == 400
    r = _empresa(c, modos=["distribuidor", "comercio"])
    assert r.status_code == 200 and r.json()["modos"] == ["comercio", "distribuidor"]
    with db.transaccion(superadmin=True) as conn:
        assert db.fila(conn, "SELECT activo FROM canales WHERE org_id=1 AND codigo='mayorista'")["activo"]


def test_roles_del_distribuidor_necesitan_el_modo_y_la_ficha(retail_demo):
    c = cliente()
    nuevo = {"email": "ana@norte.demo", "nombre": "Ana Vendedora", "rol": "vendedor"}
    assert "modo distribuidor" in c.post("/retail/api/usuarios", json=nuevo).json()["detail"]
    _empresa(c, modos=["comercio", "distribuidor"])
    ids = _cartera(1)
    assert "ficha del vendedor" in c.post("/retail/api/usuarios", json=nuevo).json()["detail"]
    r = c.post("/retail/api/usuarios", json={**nuevo, "vendedor_id": ids["Ana"]})
    assert r.status_code == 201 and r.json()["usuario"]["vendedor_id"] == ids["Ana"]
    assert c.post("/retail/api/usuarios", json={"email": "jefe@norte.demo", "nombre": "Jefe", "rol": "jefe_ventas"}).status_code == 201


def test_el_vendedor_solo_ve_su_cartera(retail_demo):
    _empresa(cliente(), modos=["comercio", "distribuidor"])
    ids = _cartera(1)

    def ver(ctx):
        with db.transaccion(ctx) as conn:
            return {t: [f["n"] for f in db.filas(conn, q)] for t, q in {
                "clientes": "SELECT razon_social n FROM clientes_b2b ORDER BY 1",
                "pedidos": "SELECT numero n FROM pedidos_venta ORDER BY 1",
                "lineas": "SELECT p.numero n FROM pedidos_venta_lineas l JOIN pedidos_venta p ON p.id = l.pedido_id ORDER BY 1",
                "cc": "SELECT numero n FROM documentos_cc ORDER BY 1"}.items()}
    base = dict(usuario_id=1, org_id=1, todas_ubicaciones=True)
    ana = ver(db.Contexto(rol="vendedor", vendedor_id=ids["Ana"], **base))
    assert ana == {"clientes": ["Almacén de Ana"], "pedidos": ["P-Ana"], "lineas": ["P-Ana"], "cc": ["F-Ana"]}
    sin_ficha = ver(db.Contexto(rol="vendedor", vendedor_id=None, **base))
    assert all(v == [] for v in sin_ficha.values())
    jefe = ver(db.Contexto(rol="jefe_ventas", **base))
    assert jefe["clientes"] == ["Almacén de Ana", "Almacén de Beto"] and len(jefe["cc"]) == 2
    # Otra empresa no ve nada, ni siquiera sin restricción de cartera.
    otra = ver(db.Contexto(rol="dueno", usuario_id=1, org_id=999, todas_ubicaciones=True))
    assert all(v == [] for v in otra.values())
