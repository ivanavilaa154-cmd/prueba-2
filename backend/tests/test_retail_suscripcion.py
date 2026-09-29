"""Retail · 13.6 Planes y facturación: prueba, módulos por plan, límite de sucursales, solo lectura al vencer y pagos."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.retail import cuentas, db
from app.retail.semilla import CLAVE_DEMO

CLAVE = "Pulpo-Azul-2026"


def _login(email, clave=CLAVE):
    c = TestClient(app)
    assert c.post("/retail/api/sesion", json={"email": email, "clave": clave}).status_code == 200
    return c


def _q(sql, params=()):
    with db.transaccion(superadmin=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall() if cur.description else None


def _empresa():
    with db.transaccion(superadmin=True) as conn:
        cuentas.administrador(conn, "yo@ejemplo.com", "Yo", CLAVE)
        return cuentas.empresa_con_dueno(conn, "Pulpo Azul", None, "dueno@pulpo.test", "Dueño", CLAVE)


def test_prueba_modulos_y_limite_de_sucursales(retail_demo):
    org = _empresa()
    d = _login("dueno@pulpo.test")
    s = d.get("/retail/api/suscripcion").json()["estado"]
    assert s["en_prueba"] and s["al_dia"] and 29 <= s["dias_restantes"] <= 30 and set(s["modulos"]) == {"base", "avanzado", "completo"}
    assert d.get("/retail/api/ventas/canasta").status_code == 200
    admin = _login("yo@ejemplo.com")
    assert admin.put(f"/retail/api/plataforma/empresas/{org}/plan", json={"plan": "inicial"}).status_code == 200
    r = d.get("/retail/api/ventas/canasta")
    assert r.status_code == 403 and "no incluye" in r.json()["detail"]                   # módulo completo fuera del plan
    assert d.get("/retail/api/plata-parada").status_code == 403                           # avanzado también
    assert d.get("/retail/api/comprar").status_code == 200                                # base sí
    assert d.post("/retail/api/ubicaciones", json={"nombre": "Local 1", "tipo": "venta"}).status_code == 201
    r = d.post("/retail/api/ubicaciones", json={"nombre": "Local 2", "tipo": "venta"})
    assert r.status_code == 403 and "hasta 1" in r.json()["detail"]                       # el plan inicial permite 1 sucursal
    assert d.post("/retail/api/ubicaciones", json={"nombre": "Depósito", "tipo": "deposito"}).status_code == 201
    assert d.get("/retail/api/yo").json()["suscripcion"]["plan"] == "inicial"


def test_vencida_queda_en_solo_lectura_y_el_pago_la_reactiva(retail_demo):
    org = _empresa()
    _q("UPDATE organizaciones SET prueba_hasta=%s WHERE id=%s", (date.today() - timedelta(days=1), org))
    d = _login("dueno@pulpo.test")
    assert d.get("/retail/api/suscripcion").json()["estado"]["al_dia"] is False
    assert d.get("/retail/api/ubicaciones").status_code == 200                           # se ve todo
    r = d.post("/retail/api/ubicaciones", json={"nombre": "Local 1", "tipo": "venta"})
    assert r.status_code == 402 and "solo lectura" in r.json()["detail"]
    assert d.post("/retail/api/privacidad/aceptar").status_code == 200                   # la privacidad y la exportación siguen
    assert d.get("/retail/api/empresa/exportar").status_code == 200
    # Solo la plataforma registra pagos.
    assert d.post(f"/retail/api/plataforma/empresas/{org}/pagos", json={"monto": 1, "medio": "efectivo", "cubre_hasta": "2027-01-01"}).status_code == 403
    admin = _login("yo@ejemplo.com")
    assert admin.post(f"/retail/api/plataforma/empresas/{org}/pagos",
                      json={"monto": 50000, "medio": "transferencia", "cubre_hasta": "2026-12-31"}).status_code == 400   # falta el plan
    r = admin.post(f"/retail/api/plataforma/empresas/{org}/pagos",
                   json={"monto": 50000, "medio": "transferencia", "cubre_hasta": str(date.today() + timedelta(days=30)), "plan": "crecimiento"})
    assert r.status_code == 200 and r.json()["al_dia"] and r.json()["plan"] == "crecimiento"
    assert d.post("/retail/api/ubicaciones", json={"nombre": "Local 1", "tipo": "venta"}).status_code == 201
    pagos = d.get("/retail/api/suscripcion").json()["pagos"]
    assert len(pagos) == 1 and pagos[0]["medio"] == "transferencia"
    lista = admin.get("/retail/api/plataforma/suscripciones").json()
    assert any(e["nombre"] == "Pulpo Azul" and e["plan"] == "crecimiento" for e in lista["empresas"])


def test_planes_los_edita_solo_la_plataforma(retail_demo):
    _empresa()
    admin = _login("yo@ejemplo.com")
    r = admin.put("/retail/api/plataforma/planes/crecimiento",
                  json={"nombre": "Crecimiento", "max_sucursales": 8, "modulos": ["base", "avanzado"], "precio_mensual": "45000"})
    assert r.status_code == 200 and next(p for p in r.json() if p["codigo"] == "crecimiento")["max_sucursales"] == 8
    assert admin.put("/retail/api/plataforma/planes/crecimiento", json={"nombre": "Xy", "modulos": ["avanzado"]}).status_code == 400
    assert _login("dueno@norte.demo", CLAVE_DEMO).put("/retail/api/plataforma/planes/crecimiento",
                                                      json={"nombre": "Xy", "modulos": ["base"]}).status_code == 403
    # La demo tiene el plan completo y no vence.
    assert _login("dueno@norte.demo", CLAVE_DEMO).get("/retail/api/suscripcion").json()["estado"]["plan"] == "cadena"
