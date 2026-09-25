"""Completa el Odoo de prueba (tools/odoo_local/start.sh del repositorio prueba-1-) con lo
que necesita una distribuidora: vendedores con cartera, plazos de pago, límite
de crédito, proveedores y facturas (algunas cobradas, otras vencidas).

    python tools/odoo_local/seed_distribuidora.py --url http://127.0.0.1:8069 --db tienda

Solo escribe en el Odoo LOCAL de prueba, con el usuario admin. La integración de la
plataforma nunca escribe en Odoo. Se puede correr más de una vez.
"""
from __future__ import annotations

import argparse
import itertools
import json
import urllib.request
from datetime import date, timedelta

_ids = itertools.count(1)


def rpc(url, servicio, metodo, *args):
    datos = json.dumps({"jsonrpc": "2.0", "method": "call", "id": next(_ids),
                        "params": {"service": servicio, "method": metodo, "args": list(args)}}).encode()
    pedido = urllib.request.Request(url + "/jsonrpc", data=datos, headers={"Content-Type": "application/json"})
    r = json.loads(urllib.request.urlopen(pedido, timeout=120).read())
    if r.get("error"):
        raise RuntimeError(r["error"].get("data", {}).get("message") or r["error"])
    return r["result"]


# Cartera: cliente -> vendedor
CARTERA = {"Ana Pérez": "Valentina Ríos", "Bruno Soto": "Valentina Ríos", "Carla Ruiz": "Valentina Ríos",
           "Diego Muñoz": "Federico Silva", "Elena Rojas": "Federico Silva", "Felipe Vargas": "Federico Silva",
           "Gabriela Díaz": "Valentina Ríos"}  # Hugo Torres queda sin vendedor a propósito
# (cliente, hace N días, importe, días de plazo, pagada hace N días o None)
FACTURAS = [
    ("Ana Pérez", 70, 250000, 30, 32), ("Ana Pérez", 40, 180000, 30, None), ("Bruno Soto", 55, 320000, 30, 10),
    ("Bruno Soto", 20, 140000, 30, None), ("Carla Ruiz", 95, 90000, 30, None), ("Diego Muñoz", 60, 410000, 30, 22),
    ("Diego Muñoz", 35, 275000, 30, None), ("Elena Rojas", 15, 130000, 30, None), ("Felipe Vargas", 50, 98000, 15, 30),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8069")
    ap.add_argument("--db", default="tienda")
    a = ap.parse_args()
    uid = rpc(a.url, "common", "authenticate", a.db, "admin", "admin", {})

    def x(modelo, metodo, args, kwargs=None):
        return rpc(a.url, "object", "execute_kw", a.db, uid, "admin", modelo, metodo, args, kwargs or {})

    def xmlid(modulo, nombre):
        return x("ir.model.data", "search_read", [[("module", "=", modulo), ("name", "=", nombre)]], {"fields": ["res_id"]})[0]["res_id"]

    # Vendedores (usuarios internos con permiso de ventas)
    vendedores = {}
    for nombre in sorted(set(CARTERA.values())):
        login = nombre.lower().split()[0] + "@tienda.cl"
        ids = x("res.users", "search", [[("login", "=", login)]])
        vendedores[nombre] = ids[0] if ids else x("res.users", "create", [{
            "name": nombre, "login": login, "groups_id": [(4, xmlid("sales_team", "group_sale_salesman"))]}])

    plazo_30 = xmlid("account", "account_payment_term_30days")
    plazo_15 = xmlid("account", "account_payment_term_15days")
    clientes = {p["name"]: p["id"] for p in x("res.partner", "search_read", [[("customer_rank", ">", 0)]], {"fields": ["name"]})}
    for nombre, pid in clientes.items():
        valores = {"property_payment_term_id": plazo_15 if nombre == "Felipe Vargas" else plazo_30, "city": "Montevideo"}
        if nombre in CARTERA:
            valores["user_id"] = vendedores[CARTERA[nombre]]
        x("res.partner", "write", [[pid], valores])

    # Proveedor con plazo de entrega para cada producto
    prov = x("res.partner", "search", [[("name", "=", "Textiles del Plata")]])
    prov = prov[0] if prov else x("res.partner", "create", [{"name": "Textiles del Plata", "is_company": True, "supplier_rank": 1}])
    x("res.partner", "write", [[prov], {"property_supplier_payment_term_id": plazo_30}])
    for t in x("product.template", "search", [[("sale_ok", "=", True), ("type", "!=", "service")]]):
        if not x("product.supplierinfo", "search", [[("product_tmpl_id", "=", t), ("partner_id", "=", prov)]]):
            x("product.supplierinfo", "create", [{"product_tmpl_id": t, "partner_id": prov, "delay": 5, "price": 1}])

    # Facturas de cliente, algunas cobradas
    producto = x("product.product", "search", [[("default_code", "=", "POL-ALG-M")]])[0]
    hoy = date.today()
    for i, (cliente, hace, importe, plazo, pagada) in enumerate(FACTURAS):
        ref = f"seed-fac-{i}"
        if x("account.move", "search", [[("ref", "=", ref)]]):
            continue
        emision = hoy - timedelta(days=hace)
        factura = x("account.move", "create", [{
            "move_type": "out_invoice", "partner_id": clientes[cliente], "ref": ref,
            "invoice_date": emision.isoformat(), "invoice_date_due": (emision + timedelta(days=plazo)).isoformat(),
            "invoice_line_ids": [(0, 0, {"product_id": producto, "quantity": 1, "price_unit": importe, "tax_ids": [(6, 0, [])]})],
        }])
        x("account.move", "action_post", [[factura]])
        if pagada is not None:
            asistente = x("account.payment.register", "create", [{"payment_date": (hoy - timedelta(days=pagada)).isoformat()}],
                          {"context": {"active_model": "account.move", "active_ids": [factura]}})
            x("account.payment.register", "action_create_payments", [[asistente]])
    # --- Compras, facturas de proveedor, pagos, lotes y merma (si están los módulos) ---
    integracion = x("res.users", "search", [[("login", "=", "integracion@tienda.cl")]])
    grupos = [xmlid("account", "group_account_invoice")]
    if x("ir.module.module", "search", [[("name", "=", "purchase"), ("state", "=", "installed")]]):
        grupos.append(xmlid("purchase", "group_purchase_user"))
    x("res.users", "write", [integracion, {"groups_id": [(4, g) for g in grupos]}])

    compras = 0
    if x("ir.module.module", "search", [[("name", "=", "purchase"), ("state", "=", "installed")]]):
        botella = x("product.product", "search", [[("default_code", "=", "BOT-TER-750")]])[0]
        for i, (hace, cantidad, recibir) in enumerate([(40, 50, 50), (20, 80, 60), (5, 40, 0)]):
            ref = f"seed-oc-{i}"
            if x("purchase.order", "search", [[("partner_ref", "=", ref)]]):
                continue
            oc = x("purchase.order", "create", [{"partner_id": prov, "partner_ref": ref, "order_line": [(0, 0, {
                "product_id": botella, "product_qty": cantidad, "price_unit": 5200,
                "date_planned": (hoy - timedelta(days=hace - 3)).isoformat() + " 12:00:00"})]}])
            x("purchase.order", "button_confirm", [[oc]])
            compras += 1
            if recibir:
                for picking in x("stock.picking", "search", [[("purchase_id", "=", oc), ("state", "not in", ["done", "cancel"])]]):
                    for mov in x("stock.move", "search", [[("picking_id", "=", picking)]]):
                        x("stock.move", "write", [[mov], {"quantity": recibir, "picked": True}])
                    x("stock.picking", "button_validate", [[picking]], {"context": {"skip_backorder": True, "skip_sms": True}})
                factura = x("account.move", "create", [{
                    "move_type": "in_invoice", "partner_id": prov, "ref": f"FP-{i}",
                    "invoice_date": (hoy - timedelta(days=hace)).isoformat(),
                    "invoice_date_due": (hoy - timedelta(days=hace - 30)).isoformat(),
                    "invoice_line_ids": [(0, 0, {"product_id": botella, "quantity": recibir, "price_unit": 5200, "tax_ids": [(6, 0, [])]})]}])
                x("account.move", "action_post", [[factura]])
                if i == 0:
                    asistente = x("account.payment.register", "create", [{"payment_date": (hoy - timedelta(days=8)).isoformat()}],
                                  {"context": {"active_model": "account.move", "active_ids": [factura]}})
                    x("account.payment.register", "action_create_payments", [[asistente]])

    # Merma: rotura de 2 botellas en Sucursal Centro
    if not x("stock.scrap", "search", [[("origin", "=", "seed-merma")]]):
        centro = x("stock.warehouse", "search_read", [[("code", "=", "CEN")]], {"fields": ["lot_stock_id"]})[0]
        botella = x("product.product", "search", [[("default_code", "=", "BOT-TER-750")]])[0]
        merma = x("stock.scrap", "create", [{"product_id": botella, "scrap_qty": 2, "origin": "seed-merma",
                                             "location_id": centro["lot_stock_id"][0]}])
        x("stock.scrap", "action_validate", [[merma]])
    print(f"Listo: {len(vendedores)} vendedores, {len(FACTURAS)} facturas, {compras} compras, proveedor Textiles del Plata")


if __name__ == "__main__":
    main()
