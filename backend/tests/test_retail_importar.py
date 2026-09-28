"""Retail · partes 3 y 5: importación de archivos y normalización del catálogo."""
import io
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.retail import api_ingesta, catalogo, db, importar, motor
from app.retail.semilla import CLAVE_DEMO


@pytest.fixture(autouse=True)
def sin_recalculo(monkeypatch):
    llamadas = []
    monkeypatch.setattr(api_ingesta, "recalcular_en_segundo_plano", lambda org, desde=None: llamadas.append((org, desde)))
    return llamadas


def _q(sql, params=()):
    with db.transaccion(motor.contexto_sistema(1)) as conn:
        return db.filas(conn, sql, params)


def cliente(email="dueno@norte.demo"):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": CLAVE_DEMO}).status_code == 200
    return c


def _csv(filas: list[list]) -> bytes:
    return "\n".join(";".join(str(c) for c in f) for f in filas).encode("utf-8")


def _importar(c, tipo, nombre, contenido, mapeo=None):
    a = c.post("/retail/api/importar/analizar", data={"tipo": tipo}, files={"archivo": (nombre, contenido)})
    assert a.status_code == 200, a.text
    a = a.json()
    v = c.post(f"/retail/api/importar/{a['lote_id']}/validar", json={"mapeo": mapeo or a["mapeo"]})
    assert v.status_code == 200, v.text
    v = v.json()
    r = c.post(f"/retail/api/importar/{a['lote_id']}/confirmar")
    return a, v, r


def _ventas_archivo(n_tickets=3, desde=1):
    suc = _q("SELECT nombre FROM ubicaciones WHERE tipo <> 'deposito' ORDER BY id LIMIT 1")[0]["nombre"]
    prods = _q("SELECT codigo_interno, ean FROM productos WHERE ean IS NOT NULL ORDER BY id LIMIT 2")
    filas = [["Fecha", "Hora", "Local", "Nro Ticket", "Codigo", "Cant", "Precio Unitario", "Medio de pago"]]
    for t in range(desde, desde + n_tickets):
        filas.append(["20/09/2026", "10:15", suc, f"A-{t:05d}", prods[0]["codigo_interno"], "2", "1.250,50", "Efectivo"])
        filas.append(["20/09/2026", "10:15", suc, f"A-{t:05d}", prods[1]["ean"], "1", "899", "Efectivo"])
    return _csv(filas)


def test_reimportar_el_mismo_archivo_no_duplica_ventas(retail_demo, sin_recalculo):
    """Criterio de aceptación: reimportar el mismo archivo no duplica ventas."""
    c = cliente()
    antes = _q("SELECT count(*) n FROM tickets")[0]["n"]
    archivo = _ventas_archivo(3)
    a, v, r = _importar(c, "ventas", "ventas.csv", archivo)
    assert a["mapeo"]["sucursal"] == "Local" and a["mapeo"]["ticket"] == "Nro Ticket" and a["mapeo"]["precio"] == "Precio Unitario"
    assert v["validas"] == 6 and v["con_error"] == 0
    assert r.status_code == 200 and r.json()["importadas"] == 3 and r.json()["lineas"] == 6
    assert sin_recalculo and str(sin_recalculo[0][1]) == "2026-09-20"
    assert _q("SELECT count(*) n FROM tickets")[0]["n"] == antes + 3
    t = _q("SELECT t.total, t.origen, (SELECT sum(monto) FROM pagos p WHERE p.ticket_id=t.id) pagado FROM tickets t WHERE origen='archivo' LIMIT 1")[0]
    assert t["total"] == Decimal("3400.00") and t["pagado"] == Decimal("3400.00")

    # El mismo archivo otra vez: se avisa y no se duplica nada.
    a2, v2, r2 = _importar(c, "ventas", "ventas.csv", archivo)
    assert a2["ya_importado"] and a2["mapeo_recordado"]
    assert r2.json()["importadas"] == 0 and r2.json()["duplicadas"] == 3
    assert _q("SELECT count(*) n FROM tickets")[0]["n"] == antes + 3

    # Un archivo que se superpone (tickets 2 a 5): solo entran los 2 nuevos.
    _, _, r3 = _importar(c, "ventas", "ventas-2.csv", _ventas_archivo(4, desde=2))
    assert r3.json()["importadas"] == 2 and r3.json()["duplicadas"] == 2
    assert _q("SELECT count(*) n FROM tickets WHERE origen='archivo'")[0]["n"] == 5


def test_validacion_fila_por_fila(retail_demo):
    c = cliente()
    suc = _q("SELECT nombre FROM ubicaciones ORDER BY id LIMIT 1")[0]["nombre"]
    cod = _q("SELECT codigo_interno FROM productos ORDER BY id LIMIT 1")[0]["codigo_interno"]
    archivo = _csv([["Fecha", "Sucursal", "Ticket", "Producto", "Cantidad", "Precio"],
                    ["20/09/2026", suc, "1", cod, "1", "100"],
                    ["20/09/2026", "Sucursal Marte", "2", cod, "1", "100"],
                    ["20/09/2026", suc, "3", "NO-EXISTE-999", "1", "100"],
                    ["20/09/2026", suc, "4", cod, "uno", "100"],
                    ["32/13/2026", suc, "5", cod, "1", "100"],
                    ["20/09/2026", suc, "", cod, "1", "100"]])
    a, v, r = _importar(c, "ventas", "errores.csv", archivo)
    assert v["validas"] == 1 and v["con_error"] == 5
    por_fila = {e["fila"]: e["error"] for e in v["errores"]}
    assert "Sucursal Marte" in por_fila[3]
    assert "NO-EXISTE-999" in por_fila[4] and ["NO-EXISTE-999", 1] in [list(x) for x in v["productos_no_encontrados"]]
    assert "no es un número" in por_fila[5]
    assert "fecha" in por_fila[6]
    assert "Falta" in por_fila[7]
    assert r.json()["importadas"] == 1
    errores = c.get(f"/retail/api/importar/{a['lote_id']}/errores.csv")
    assert errores.status_code == 200 and "Sucursal Marte" in errores.content.decode("utf-8-sig")
    lotes = c.get("/retail/api/importar/lotes").json()
    assert lotes[0]["id"] == a["lote_id"] and lotes[0]["estado"] == "importado"


def test_falta_mapear_un_campo_obligatorio(retail_demo):
    c = cliente()
    a = c.post("/retail/api/importar/analizar", data={"tipo": "stock"},
               files={"archivo": ("s.csv", _csv([["Articulo", "Local", "Cosa"], ["1", "x", "3"]]))}).json()
    v = c.post(f"/retail/api/importar/{a['lote_id']}/validar", json={"mapeo": {"producto": "Articulo", "sucursal": "Local", "cantidad": None}})
    assert v.status_code == 400 and "Stock" in v.json()["detail"]
    assert c.post(f"/retail/api/importar/{a['lote_id']}/confirmar").status_code == 400


def test_productos_stock_y_excel(retail_demo):
    from openpyxl import Workbook
    c = cliente()
    libro = Workbook()
    hoja = libro.active
    hoja.append(["Código", "Descripción", "Código de barras", "Marca", "Rubro", "Proveedor", "Costo", "Precio venta", "Unidades por bulto"])
    hoja.append(["IMP-001", "Yerba Importada 1 kg", "7790000000017", "Importada", "Almacén", "Distribuidora Nueva SRL", 2100.5, 3500, 10])
    hoja.append(["IMP-002", "Pan casero x kg", None, None, "Panadería", None, None, 2800, None])
    buffer = io.BytesIO()
    libro.save(buffer)
    _, v, r = _importar(c, "productos", "productos.xlsx", buffer.getvalue())
    assert v["validas"] == 2, v
    assert r.json()["nuevos"] == 2
    p = _q("SELECT p.*, pp.costo, pp.unidades_por_bulto FROM productos p LEFT JOIN producto_proveedores pp ON pp.producto_id=p.id WHERE codigo_interno LIKE 'IMP-%%' ORDER BY codigo_interno")
    assert p[0]["estado_mapeo"] == "sin_mapear" and p[0]["costo"] == Decimal("2100.5") and p[0]["unidades_por_bulto"] == 10
    assert p[1]["estado_mapeo"] == "propio"
    assert _q("SELECT precio FROM precios WHERE producto_id=%s AND hasta IS NULL", (p[1]["id"],))[0]["precio"] == Decimal("2800")
    pend = c.get("/retail/api/catalogo/pendientes").json()
    assert any(x["codigo_interno"] == "IMP-001" for x in pend["productos_sin_mapear"])
    assert c.post(f"/retail/api/catalogo/productos/{p[0]['id']}/maestro", json={"maestro_id": None}).status_code == 200
    assert _q("SELECT estado_mapeo FROM productos WHERE id=%s", (p[0]["id"],))[0]["estado_mapeo"] == "propio"

    suc = _q("SELECT nombre FROM ubicaciones ORDER BY id LIMIT 1")[0]["nombre"]
    _, v, r = _importar(c, "stock", "stock.csv", _csv([["Producto", "Sucursal", "Existencia", "Vencimiento"],
                                                       ["IMP-001", suc, "24", "31/12/2026"]]))
    assert r.json()["importadas"] == 1
    s = _q("SELECT cantidad FROM stock_actual WHERE producto_id=%s", (p[0]["id"],))
    assert s[0]["cantidad"] == Decimal("24")
    assert _q("SELECT vencimiento FROM stock_lotes WHERE producto_id=%s", (p[0]["id"],))[0]["vencimiento"].isoformat() == "2026-12-31"


def test_lista_de_precios_empareja_y_aprende(retail_demo):
    c = cliente()
    prov = _q("SELECT id, razon_social FROM proveedores ORDER BY id LIMIT 1")[0]
    prod = _q("SELECT p.id, p.codigo_interno, p.nombre, pp.costo FROM productos p JOIN producto_proveedores pp ON pp.producto_id=p.id "
              "WHERE pp.proveedor_id=%s ORDER BY p.id LIMIT 1", (prov["id"],))[0]
    otro = _q("SELECT id, nombre FROM productos WHERE id <> %s ORDER BY id DESC LIMIT 1", (prod["id"],))[0]
    nuevo_costo = (prod["costo"] * Decimal("1.12")).quantize(Decimal("0.01"))
    archivo = _csv([["Proveedor", "Codigo", "Descripcion", "Costo"],
                    [prov["razon_social"], prod["codigo_interno"], prod["nombre"], str(nuevo_costo).replace(".", ",")],
                    [prov["razon_social"], "ZZ-77", "Articulo rarisimo que nadie conoce", "100"]])
    _, v, r = _importar(c, "precios", "lista.csv", archivo)
    assert r.json()["importadas"] == 1 and r.json()["sin_emparejar"] == 1
    assert _q("SELECT costo FROM producto_proveedores WHERE producto_id=%s AND proveedor_id=%s", (prod["id"], prov["id"]))[0]["costo"] == nuevo_costo
    linea = _q("SELECT costo_anterior FROM listas_precios_proveedor_lineas WHERE producto_id=%s ORDER BY id DESC LIMIT 1", (prod["id"],))[0]
    assert linea["costo_anterior"] == prod["costo"]

    # Emparejar a mano la línea desconocida: queda como alias y la próxima lista la reconoce sola.
    pend = c.get("/retail/api/catalogo/pendientes").json()["lineas_sin_producto"]
    rara = next(x for x in pend if x["codigo"] == "ZZ-77")
    assert c.post(f"/retail/api/catalogo/lineas/{rara['id']}", json={"producto_id": otro["id"]}).status_code == 200
    _, _, r2 = _importar(c, "precios", "lista-2.csv", _csv([["Proveedor", "Codigo", "Descripcion", "Costo"],
                                                            [prov["razon_social"], "ZZ-77", "Articulo rarisimo que nadie conoce", "110"]]))
    assert r2.json()["importadas"] == 1 and r2.json()["sin_emparejar"] == 0
    assert c.get("/retail/api/catalogo/buscar", params={"q": otro["nombre"][:6]}).json()


def test_permisos_importar(retail_demo):
    c = cliente("caja.centro@norte.demo")
    r = c.post("/retail/api/importar/analizar", data={"tipo": "ventas"}, files={"archivo": ("v.csv", b"a;b\n1;2")})
    assert r.status_code == 403


def test_numeros_fechas_y_mapeo():
    assert importar.numero("1.234,56") == Decimal("1234.56")
    assert importar.numero("1,234.56") == Decimal("1234.56")
    assert importar.numero("$ 1.234") == Decimal("1234")
    assert importar.numero("0,5") == Decimal("0.5")
    assert importar.numero("") is None
    with pytest.raises(ValueError):
        importar.numero("dos")
    assert importar.fecha("05/03/2026").isoformat() == "2026-03-05"
    assert importar.fecha("2026-03-05").isoformat() == "2026-03-05"
    assert importar.fecha(46086).isoformat() == "2026-03-05"            # número de serie de Excel
    assert importar.hora("9:05").isoformat() == "09:05:00"
    m = importar.sugerir_mapeo("ventas", ["Día", "Sucursal", "Comprobante", "SKU", "Unidades", "Precio"])
    assert m["fecha"] == "Día" and m["ticket"] == "Comprobante" and m["producto"] == "SKU" and m["cantidad"] == "Unidades"
    assert importar.firma(["B", "a"]) == importar.firma(["A", "b"])


def test_similitud_de_textos():
    assert catalogo.similitud("Coca Cola 1,5 L", "Gaseosa Coca-Cola 1500 ml") > 0.6
    assert catalogo.similitud("Coca Cola 1,5 L", "Coca Cola 2,25 L") < catalogo.similitud("Coca Cola 1,5 L", "COCA-COLA 1.5LT")
    assert catalogo.similitud("Yerba Playadito 1 kg", "Fideos Lucchetti 500 g") < catalogo.UMBRAL_SUGERENCIA
