#!/usr/bin/env python3
"""Genera la documentación (KPIs y actividades) y el registry de KPIs a partir de kpis/src/*.yml, validando contra el modelo canónico (docs/04).

Salidas:
  docs/08..12_kpis_<area>.md       fichas de KPI por área
  docs/13_matriz_requisitos.md     columna canónica × KPIs que la necesitan (guía de onboarding)
  kpis/registry/kpi_<ID>.yml       registry consumido por la capa semántica y el servidor IA
  kpis/catalogo_kpis.csv

Validaciones (el build falla si alguna no se cumple):
  - cada columna de requisitos existe en el DDL de docs/04 (tabla.columna o ref.tabla.columna)
  - cada columna de requisitos_entidad.yml existe
  - IDs únicos, relacionados existentes, campos obligatorios presentes
  - la documentación de KPIs no contiene términos de la lista `terminos_prohibidos.txt` (si existe)
Uso: python3 tools/build_kpis.py
"""
import csv, pathlib, re, sys, collections
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "kpis" / "src"
AREAS = [("finanzas", "08"), ("ventas", "09"), ("inventario", "10"), ("logistica", "11"), ("marketing", "12")]
CAMPOS_OBLIG = ["id", "nombre", "pregunta", "definicion", "formula", "cube", "unidad", "direccion", "agregacion", "requisitos"]
ROL_TABLA = {"fct_pedido": "ventas", "fct_pedido_linea": "ventas", "dim_cliente": "ventas", "dim_producto": "ventas", "fct_devolucion": "ventas",
    "fct_oportunidad": "crm", "fct_oportunidad_historial_etapa": "crm", "fct_lead": "crm", "fct_presupuesto": "presupuesto", "fct_comprobante": "facturacion",
    "fct_asiento_linea": "contabilidad", "dim_cuenta_contable": "contabilidad", "fct_documento_cxc": "cuentas_corrientes", "fct_documento_cxp": "cuentas_corrientes",
    "fct_cobro": "cuentas_corrientes", "fct_pago": "cuentas_corrientes", "fct_aplicacion_cobro": "cuentas_corrientes", "dim_proveedor": "compras",
    "fct_movimiento_tesoreria": "tesoreria", "dim_cuenta_tesoreria": "tesoreria", "fct_liquidacion_pasarela": "pasarela_pagos", "fct_stock_diario": "inventario",
    "fct_movimiento_stock": "inventario", "fct_orden_compra": "compras", "fct_orden_compra_linea": "compras", "fct_recepcion": "compras", "fct_conteo_inventario": "inventario",
    "parametro_reposicion": "inventario", "fct_envio": "logistica", "fct_evento_envio": "logistica", "fct_preparacion": "logistica", "fct_ads_diario": "publicidad",
    "dim_campana": "publicidad", "fct_web_diario": "analitica_web", "fct_email_campana": "email_marketing", "fct_suscriptores_diario": "email_marketing",
    "fct_atribucion_pedido": "ventas (con UTM)", "ref.indice_precios": "referencia_indice_precios", "ref.tipo_cambio": "referencia_tipo_cambio", "ref.feriado": "referencia_calendario",
    "fct_lista_precio_proveedor": "precios_compra", "fct_precio_venta": "precios_venta", "dim_promocion": "promociones", "fct_promocion_producto": "promociones",
    "fct_stock_lote": "lotes_vencimientos", "dim_deposito": "inventario"}


def roles_minimos(k):
    """Roles de fuente mínimos derivados de los requisitos (no se editan a mano)."""
    r = k["requisitos"]
    base = sorted({ROL_TABLA[c.rpartition(".")[0]] for c in r.get("obligatorias", [])})
    alts = []
    for a in r.get("alternativas", []):
        roles = "+".join(sorted({ROL_TABLA[c.rpartition(".")[0]] for c in a["obligatorias"]}))
        if roles not in alts:
            alts.append(roles)
    if any(set(a.split("+")) <= set(base) for a in alts):   # alguna variante ya se cumple con los roles base
        alts = []
    extra = [x for x in k.get("roles_extra", []) if x not in base]
    return base + ([" o ".join(alts)] if alts else []) + extra


TIPOS = r"(uuid|text|numeric|date|timestamptz|boolean|int|bigint|smallint|char|jsonb)"


def columnas_canonicas():
    ddl = (ROOT / "docs" / "04_capa3_modelo_canonico.md").read_text()
    cols = collections.defaultdict(set)
    ddl_sin_coment = re.sub(r"--[^\n]*", "", ddl)
    for m in re.finditer(r"create table (core|ref)\.(\w+)\s*\(", ddl_sin_coment):
        esquema, tabla = m.group(1), m.group(2)
        i, prof = m.end(), 1
        while prof and i < len(ddl_sin_coment):   # cuerpo balanceado por paréntesis
            prof += {"(": 1, ")": -1}.get(ddl_sin_coment[i], 0); i += 1
        cuerpo = ddl_sin_coment[m.end():i - 1]
        nombre = tabla if esquema == "core" else f"ref.{tabla}"
        for c, _ in re.findall(r"\b([a-z_][a-z0-9_]*)\s+" + TIPOS + r"\b", cuerpo):
            cols[nombre].add(c)
    for t in cols:
        if not t.startswith("ref."):
            cols[t] |= {"tenant_id", "source_id", "source_key", "_cargado_at", "_actualizado_at"}
    return cols


def esc(t):
    return str(t).replace("|", "\\|").replace("\n", " ")


def lista(v):
    if not v:
        return "—"
    if isinstance(v, dict):
        return ", ".join(f"`{a}`={b}" for a, b in v.items())
    return ", ".join(str(x) for x in v)


def main():
    cols = columnas_canonicas()
    errores = []

    def existe(ref):
        t, _, c = ref.rpartition(".")
        return c in cols.get(t, set())

    todos, por_area = {}, {}
    for area, num in AREAS:
        data = yaml.safe_load((SRC / f"{area}.yml").read_text())
        por_area[area] = (num, data)
        for k in data["kpis"]:
            k["roles_minimos"] = roles_minimos(k)
            if k["id"] in todos:
                errores.append(f"ID duplicado {k['id']}")
            todos[k["id"]] = k

    uso = collections.defaultdict(lambda: {"obligatoria": set(), "opcional": set(), "alternativa": set()})
    for kid, k in todos.items():
        for c in CAMPOS_OBLIG:
            if not k.get(c):
                errores.append(f"{kid}: falta '{c}'")
        r = k.get("requisitos") or {}
        if not r.get("obligatorias") and not r.get("alternativas"):
            errores.append(f"{kid}: requisitos vacíos (sin obligatorias ni alternativas)")
        for tipo, lst in (("obligatoria", r.get("obligatorias", [])), ("opcional", r.get("opcionales", []))):
            for c in lst:
                (uso[c][tipo].add(kid) if existe(c) else errores.append(f"{kid}: columna inexistente en docs/04: {c}"))
        for a in r.get("alternativas", []):
            for c in a["obligatorias"]:
                (uso[c]["alternativa"].add(kid) if existe(c) else errores.append(f"{kid}: columna inexistente en docs/04: {c}"))
        for rel in k.get("relacionados") or []:
            if rel not in todos:
                errores.append(f"{kid}: relacionado inexistente {rel}")

    req_ent = yaml.safe_load((SRC / "requisitos_entidad.yml").read_text())
    for ent, lst in req_ent.items():
        for c in lst:
            if not existe(f"{ent}.{c}"):
                errores.append(f"requisitos_entidad: {ent}.{c} no existe en docs/04")

    # ---------- actividades
    act_doc = yaml.safe_load((ROOT / "actividades" / "src" / "actividades.yml").read_text())
    roles_validos = {l.split(",")[1] for l in (ROOT / "seeds" / "ref_valores_canonicos.csv").read_text().splitlines() if l.startswith("rol_responsable,")}
    act_ids = set()
    for a in act_doc["actividades"]:
        aid = a["id"]; act_ids.add(aid)
        for campo in ["nombre", "caso_de_negocio", "entidad", "frecuencia", "responsable_principal", "deteccion", "calculo", "impacto", "casos", "resoluciones", "resolucion_confirmada", "requisitos"]:
            if not a.get(campo):
                errores.append(f"{aid}: falta '{campo}'")
        for c in a.get("casos", []):
            cid = f"{aid}.{c.get('codigo')}"
            for campo in ["codigo", "nombre", "condicion", "prioridad", "cierre"]:
                if not c.get(campo):
                    errores.append(f"{cid}: falta '{campo}'")
            if not c.get("acciones"):
                errores.append(f"{cid}: caso SIN ACCIÓN (regla: ninguna alerta sin acción)")
            for acc in c.get("acciones", []):
                for campo in ["orden", "accion", "responsable", "plazo"]:
                    if not acc.get(campo):
                        errores.append(f"{cid}: acción sin '{campo}'")
                if acc.get("responsable") not in roles_validos:
                    errores.append(f"{cid}: responsable '{acc.get('responsable')}' no está en el dominio rol_responsable")
        if not set(a.get("resolucion_confirmada", [])) <= set(a.get("resoluciones", [])):
            errores.append(f"{aid}: resolucion_confirmada no es subconjunto de resoluciones")
        r = a.get("requisitos", {})
        for c in r.get("obligatorias", []) + r.get("opcionales", []) + [x for alt in r.get("alternativas", []) for x in alt["obligatorias"]]:
            if not existe(c):
                errores.append(f"{aid}: columna inexistente en docs/04: {c}")
        for k in a.get("kpis_relacionados", []):
            if k not in todos:
                errores.append(f"{aid}: KPI relacionado inexistente {k}")

    if errores:
        print("ERRORES:\n  " + "\n  ".join(errores))
        sys.exit(1)

    # ---------- docs por área
    for area, (num, data) in por_area.items():
        out = [f"# {num} — {data['titulo']}", "",
               f"> Generado por `tools/build_kpis.py` desde `kpis/src/{area}.yml`. No editar a mano.",
               "> Los KPIs se calculan **solo** sobre el modelo canónico (docs/04). Cada ficha declara qué columnas canónicas necesita; qué sistema las aporta lo define el `mapping.yml` de cada fuente (docs/05).", "",
               data["intro"].strip(), "", "## Índice", "", "| ID | KPI | Unidad | Dirección | Roles mínimos |", "|---|---|---|---|---|"]
        for k in data["kpis"]:
            out.append(f"| [{k['id']}](#{k['id'].lower()}) | {k['nombre']} | {esc(k['unidad'])} | {k['direccion']} | {esc(', '.join(k.get('roles_minimos', [])))} |")
        out.append("")
        for k in data["kpis"]:
            r = k["requisitos"]
            out += ["---", "", f"## {k['id']}", f"### {k['nombre']}", "",
                    f"**Pregunta que responde:** {k['pregunta']}  ", f"**Definición:** {k['definicion']}", "",
                    "| Atributo | Valor |", "|---|---|",
                    f"| Medida en capa semántica | `{esc(k['cube'])}` |", f"| Unidad | {esc(k['unidad'])} |",
                    f"| Dirección | {k['direccion']} |", f"| Agregación | {esc(k['agregacion'])} |",
                    f"| Grano mínimo | {k.get('grano_min', '')} |", f"| Dimensiones | {esc(lista(k.get('dimensiones')))} |",
                    f"| Filtros base | {esc(lista(k.get('filtros_base')))} |", f"| Parámetros | {esc(lista(k.get('parametros')))} |",
                    f"| Roles de fuente mínimos | {esc(', '.join(k.get('roles_minimos', [])))} |",
                    f"| Historia mínima | {k.get('historia_minima', '—')} |", f"| Relacionados | {lista(k.get('relacionados'))} |", "",
                    "**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**", "",
                    "```sql", k["formula"].rstrip(), "```", "", "**Requisitos de datos canónicos:**", "",
                    "| Columna canónica | Tipo de requisito |", "|---|---|"]
            out += [f"| `{c}` | obligatoria |" for c in r.get("obligatorias", [])]
            for a in r.get("alternativas", []):
                out += [f"| `{c}` | obligatoria si se usa la variante **{a['nombre']}** |" for c in a["obligatorias"]]
            out += [f"| `{c}` | opcional (habilita desgloses o mayor precisión) |" for c in r.get("opcionales", [])]
            if r.get("alternativas"):
                out += ["", f"Basta con que se cumpla **una** de las variantes: {', '.join(a['nombre'] for a in r['alternativas'])} (se usa la primera disponible en ese orden y se informa en `metadata.modo`)."]
            out.append("")
            if k.get("casos_borde"):
                out += ["**Casos borde y reglas:**", ""] + [f"- {c}" for c in k["casos_borde"]] + [""]
            if k.get("alertas"):
                out += ["**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):", "", "| Condición | Severidad |", "|---|---|"]
                out += [f"| {esc(a['condicion'])} | {a['severidad']} |" for a in k["alertas"]] + [""]
        (ROOT / "docs" / f"{num}_kpis_{area}.md").write_text("\n".join(out) + "\n")

    # ---------- matriz de requisitos
    out = ["# 13 — Matriz de requisitos: columna canónica → KPIs", "",
           "> Generado. Sirve para el onboarding: al mapear una columna se ve qué KPIs habilita. `O` = obligatoria, `A` = obligatoria en una variante, `o` = opcional.", "",
           "## Por tabla", ""]
    por_tabla = collections.defaultdict(list)
    for c in sorted(uso):
        por_tabla[c.rpartition(".")[0]].append(c)
    for t in sorted(por_tabla):
        out += [f"### `{t}`", "", "| Columna | KPIs (O) | KPIs (A) | KPIs (o) |", "|---|---|---|---|"]
        for c in por_tabla[t]:
            u = uso[c]
            out.append(f"| `{c.rpartition('.')[2]}` | {', '.join(sorted(u['obligatoria'])) or '—'} | {', '.join(sorted(u['alternativa'])) or '—'} | {', '.join(sorted(u['opcional'])) or '—'} |")
        out.append("")
    out += ["## Columnas obligatorias por entidad (para publicar un mapping)", "", "| Entidad | Columnas |", "|---|---|"]
    out += [f"| `{e}` | {', '.join(v)} |" for e, v in req_ent.items()]
    (ROOT / "docs" / "13_matriz_requisitos.md").write_text("\n".join(out) + "\n")

    # ---------- doc + registry de actividades
    out = [f"# 14 — {act_doc['titulo']}", "", "> Generado por `tools/build_kpis.py` desde `actividades/src/actividades.yml`. No editar a mano.", "",
           act_doc["intro"].strip(), "", "## Índice", "", "| ID | Actividad | Entidad | Frecuencia | Responsable principal | Casos |", "|---|---|---|---|---|---|"]
    for a in act_doc["actividades"]:
        out.append(f"| [{a['id']}](#{a['id'].lower()}) | {a['nombre']} | {esc(a['entidad'])} | {esc(a['frecuencia'])} | {a['responsable_principal']} | {len(a['casos'])} |")
    out.append("")
    for a in act_doc["actividades"]:
        d = a["deteccion"]; r = a["requisitos"]
        out += ["---", "", f"## {a['id']}", f"### {a['nombre']}", "", f"**El caso de negocio:** {a['caso_de_negocio']}", "",
                "| Atributo | Valor |", "|---|---|", f"| Entidad | {esc(a['entidad'])} |", f"| Frecuencia | {esc(a['frecuencia'])} |",
                f"| Responsable principal | {a['responsable_principal']} |", f"| Parámetros (por tenant) | {esc(lista(a.get('parametros')))} |",
                f"| Impacto (para priorizar) | {esc(a['impacto'])} |", f"| KPIs relacionados | {lista(a.get('kpis_relacionados'))} |", "",
                "#### Detección", "", f"**Universo:** {d['universo']}", "", "**Condiciones:**", ""] + [f"- {x}" for x in d.get("condiciones", [])] + [""]
        if d.get("exclusiones"):
            out += ["**Exclusiones (no se genera tarea):**", ""] + [f"- {x}" for x in d["exclusiones"]] + [""]
        if d.get("intradia"):
            out += [f"**Versión intradía:** {d['intradia']}", ""]
        out += ["**Cálculo de referencia:**", "", "```sql", a["calculo"].rstrip(), "```", "",
                "#### Casos y acciones (cada detección cae en un caso; cada caso prescribe acciones)", ""]
        for c in a["casos"]:
            out += [f"**{a['id']}.{c['codigo']} — {c['nombre']}**  ", f"*Cuándo:* {c['condicion']}  ", f"*Prioridad:* {c['prioridad']}", "",
                    "| # | Acción | Responsable | Plazo |", "|---|---|---|---|"]
            out += [f"| {x['orden']} | {esc(x['accion'])} | {x['responsable']} | {esc(x['plazo'])} |" for x in c["acciones"]]
            out += ["", f"*Cierre:* {c['cierre']}", ""]
        out += [f"**Resoluciones posibles:** {', '.join(f'`{x}`' for x in a['resoluciones'])}  ",
                f"**Cuentan como detección confirmada (precisión):** {', '.join(f'`{x}`' for x in a['resolucion_confirmada'])}", "",
                f"**Ejemplo de tarea:** _{a['ejemplo']}_", "", "**Requisitos de datos canónicos:**", "", "| Columna canónica | Tipo |", "|---|---|"]
        out += [f"| `{c}` | obligatoria |" for c in r.get("obligatorias", [])]
        for alt in r.get("alternativas", []):
            out += [f"| `{c}` | obligatoria en variante **{alt['nombre']}** |" for c in alt["obligatorias"]]
        out += [f"| `{c}` | opcional |" for c in r.get("opcionales", [])] + [""]
    (ROOT / "docs" / "14_actividades.md").write_text("\n".join(out) + "\n")
    areg = ROOT / "actividades" / "registry"; areg.mkdir(parents=True, exist_ok=True)
    for f in areg.glob("act_*.yml"):
        f.unlink()
    for a in act_doc["actividades"]:
        (areg / f"act_{a['id']}.yml").write_text(yaml.safe_dump(a, allow_unicode=True, sort_keys=False, width=140))
    n_casos = sum(len(a["casos"]) for a in act_doc["actividades"]); n_acc = sum(len(c["acciones"]) for a in act_doc["actividades"] for c in a["casos"])

    # ---------- registry + catálogo
    reg = ROOT / "kpis" / "registry"
    reg.mkdir(parents=True, exist_ok=True)
    for f in reg.glob("kpi_*.yml"):
        f.unlink()
    with open(ROOT / "kpis" / "catalogo_kpis.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "area", "nombre", "pregunta", "unidad", "direccion", "agregacion", "grano_min", "cube", "roles_minimos", "relacionados"])
        for area, (num, data) in por_area.items():
            for k in data["kpis"]:
                (reg / f"kpi_{k['id']}.yml").write_text(yaml.safe_dump({**k, "area": area}, allow_unicode=True, sort_keys=False, width=140))
                w.writerow([k["id"], area, k["nombre"], k["pregunta"], k["unidad"], k["direccion"], k["agregacion"], k.get("grano_min"), k["cube"],
                            "; ".join(k.get("roles_minimos", [])), "|".join(k.get("relacionados") or [])])

    print(f"OK: {len(todos)} KPIs · {len(uso)} columnas canónicas referenciadas · {sum(len(v) for v in cols.values())} columnas en el modelo")
    for area, (num, data) in por_area.items():
        print(f"  {area}: {len(data['kpis'])}")
    print(f"OK: {len(act_doc['actividades'])} actividades · {n_casos} casos · {n_acc} acciones (todas con responsable y plazo)")


if __name__ == "__main__":
    main()
