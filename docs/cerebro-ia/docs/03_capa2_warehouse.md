# 03 — Capa 2: Almacén (warehouse), multi-cliente y seguridad

## 1. Esquemas

| Esquema | Contenido | Escribe | Notas |
|---|---|---|---|
| `raw_<tenant_slug>` | Una tabla por `<source_id>__<stream>` (docs/02 §4) | Motor de ingesta | Append-only. Un esquema por cliente: facilita borrado, backup y cuotas |
| `staging` | Vista "versión vigente" de cada stream, tipada según el mapeo | Compilador de mapeos → dbt | Generado, nunca escrito a mano |
| `intermediate` | Unión de fuentes por entidad, resolución de identidad, fuente de verdad | dbt (genérico) | Genérico por entidad, no por fuente |
| `core` | **Modelo canónico** (docs/04) | dbt | Contrato único |
| `marts` | Agregados y snapshots para KPIs (docs/04 §8) | dbt | |
| `ref` | Tipo de cambio, índice de precios, calendario, catálogos canónicos, plan de cuentas estándar | seeds + fuentes de referencia | Sin `tenant_id` (salvo configuración por tenant) |
| `ops` | Tenants, fuentes, estado, mapeos publicados, calidad, auditoría, alertas, reportes | App | |

## 2. Registro de tenants y fuentes

```sql
create table ops.tenant (
  tenant_id uuid primary key,
  slug text unique not null,
  nombre text not null,
  pais char(2),                              -- ISO 3166-1; define calendario e impuestos por defecto
  moneda_base char(3) not null,              -- ISO 4217
  zona_horaria text not null,                -- IANA
  tipo_cambio_referencia text,               -- qué serie de ref.tipo_cambio usar por defecto
  indice_precios_referencia text,            -- qué serie de ref.indice_precios usar para 'real'
  inicio_ejercicio_mes int not null default 1,
  tasa_impuesto_indirecto_default numeric(6,3),   -- ej. 21.000; se usa si una fuente trae precios con impuesto incluido sin desglose
  horario_operativo jsonb,                   -- {"lun-vie": ["09:00","18:00"], "sab": null}
  preferencias jsonb,                        -- idioma, tono de reportes, canales de notificación
  activo boolean not null default true,
  creado_at timestamptz not null default now()
);

create table ops.tenant_fuente (
  tenant_id uuid references ops.tenant,
  source_id text not null,                   -- nombre elegido por el operador (docs/02 §3)
  arquetipo text not null,
  roles text[] not null,
  spec_version int not null,                 -- versión publicada de source.yml
  mapping_version int,                       -- versión publicada de mapping.yml
  prioridad int default 100,                 -- para desempates de fuente de verdad
  activo boolean default true,
  primary key (tenant_id, source_id)
);

create table ops.fuente_de_verdad (          -- quién manda por entidad cuando hay superposición (docs/05 §6)
  tenant_id uuid, entidad text, source_id text, alcance jsonb,   -- alcance opcional: {"canal_id": ["marketplace"]}
  primary key (tenant_id, entidad, source_id)
);

create table ops.artefacto_config (           -- source.yml / mapping.yml versionados (auditables)
  tenant_id uuid, source_id text, tipo text,  -- 'source' | 'mapping'
  version int, contenido jsonb, estado text,  -- 'borrador' | 'validado' | 'publicado' | 'archivado'
  autor text, aprobado_por text, creado_at timestamptz, publicado_at timestamptz,
  primary key (tenant_id, source_id, tipo, version)
);

create table ops.tenant_config_kpi (tenant_id uuid, kpi_id text, parametro text, valor jsonb, primary key (tenant_id, kpi_id, parametro));
```

## 3. Aislamiento y seguridad

1. **RLS** en `staging`, `intermediate`, `core`, `marts`: `using (tenant_id = current_setting('app.tenant_id')::uuid)`. El rol de lectura de la capa semántica no tiene `BYPASSRLS`.
2. `raw_<tenant>` accesible solo por el rol de ingesta y por dbt.
3. Capa semántica con contexto de seguridad obligatorio (docs/06 §2.4); servidor IA con token por tenant (docs/06 §3).
4. **Credenciales** solo en el gestor de secretos; en YAML y DB únicamente referencias.
5. **Datos personales:** emails, teléfonos y documentos de personas se guardan hasheados (`sha256(normalizado ‖ sal_del_tenant)`) en `core`; el crudo queda en `raw` con retención limitada. La IA nunca recibe datos personales.
6. **Auditoría:** `ops.auditoria` registra cada consulta de la IA (tenant, usuario, KPI, parámetros, timestamp) y cada publicación de configuración.
7. **Borrado de cliente:** `drop schema raw_<slug>` + `delete where tenant_id = …` en todas las capas + revocar secretos; comando `cerebro tenant eliminar`.

## 4. Materialización y rendimiento

- `core.*` incremental con `unique_key = [tenant_id, <pk>]`; `on_schema_change = append_new_columns`.
- Índices `(tenant_id, <fecha principal>)` y `(tenant_id, <fk>)` en facts.
- Particionado por mes en facts de alto volumen cuando superen ~50 M filas.
- Retención `raw`: configurable (default 24 meses de versiones históricas; la versión vigente se conserva siempre).
- Motor migrable: todo SQL generado usa macros cross-database de dbt (sin funciones exclusivas del motor salvo en macros aisladas).

## 5. Orquestación

- Un asset por `(tenant, source_id, stream)` generado desde `ops.tenant_fuente` + `source.yml`.
- Al terminar una ingesta: `dbt build` del subárbol afectado para ese tenant (`--vars tenant_id`).
- Job diario (hora local del tenant, configurable): snapshots (`fct_stock_diario`, saldos), marts, tests de calidad, alertas y reportes programados.
- Sensor de frescura por fuente según SLA configurado (docs/07 §4).
