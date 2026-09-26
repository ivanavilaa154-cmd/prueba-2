# 12 — KPIs de Marketing

> Generado por `tools/build_kpis.py` desde `kpis/src/marketing.yml`. No editar a mano.
> Los KPIs se calculan **solo** sobre el modelo canónico (docs/04). Cada ficha declara qué columnas canónicas necesita; qué sistema las aporta lo define el `mapping.yml` de cada fuente (docs/05).

Cubre inversión y eficiencia de medios pagos, tráfico y conversión web, adquisición de clientes, leads y email.

**§0.1 Dos verdades distintas (el agente SIEMPRE aclara cuál usa):**
- **Métricas de plataforma** (`*_plataforma` de `fct_ads_diario`): lo que cada plataforma publicitaria se auto-atribuye. Se solapan entre plataformas → **nunca se suman entre plataformas** para "ventas por publicidad".
- **Métricas de negocio** (`fct_pedido` + `fct_atribucion_pedido`): venta real, sin duplicar. MER, CAC y ROAS real se calculan con estas.

**§0.2 Gasto publicitario:** `gasto` sin impuesto indirecto, en moneda base. Si en el país del tenant la publicidad contratada en el exterior tiene impuestos o recargos no recuperables, el tenant configura `ops.tenant_config_kpi(MKT, factor_costo_ads)` y los KPIs de costo ofrecen `costo='plataforma|total'`.

**§0.3 Atribución de pedidos (`fct_atribucion_pedido`):**
1. `ultimo_clic_utm` (default): UTMs del pedido → reglas UTM del tenant (`ops.tenant_config_kpi(MKT, reglas_utm)`, con un set por defecto de la plataforma) → `canal_marketing`; `campana_id` por `utm_campaign` normalizado. Pedidos de canal `marketplace` → `marketplace`. Sin UTM y sin referrer → `directo`. Canal `tienda_fisica` → `offline`.
2. `primer_contacto`: canal del primer pedido/lead del cliente (para CAC por canal de adquisición).
3. `plataforma_declarada`: solo para comparar con métricas de plataforma.

**§0.4 Las plataformas recalculan hacia atrás** (ventana de atribución): los últimos días de conversiones de plataforma son provisorios (ventana configurable por fuente, `relectura_dias` del source.yml); el agente lo advierte.

## Índice

| ID | KPI | Unidad | Dirección | Roles mínimos |
|---|---|---|---|---|
| [MKT-01](#mkt-01) | Inversión publicitaria | moneda | neutral | publicidad |
| [MKT-02](#mkt-02) | Impresiones y CPM | cantidad \| moneda | menor_mejor (CPM) | publicidad |
| [MKT-03](#mkt-03) | CTR | porcentaje | mayor_mejor | publicidad |
| [MKT-04](#mkt-04) | CPC | moneda | menor_mejor | publicidad |
| [MKT-05](#mkt-05) | Conversiones y CPA de plataforma | cantidad \| moneda | menor_mejor (CPA) | publicidad |
| [MKT-06](#mkt-06) | ROAS de plataforma | ratio | mayor_mejor | publicidad |
| [MKT-07](#mkt-07) | MER / ROAS real | ratio | mayor_mejor | publicidad, ventas |
| [MKT-08](#mkt-08) | CAC (costo de adquisición de cliente) | moneda | menor_mejor | publicidad, ventas |
| [MKT-09](#mkt-09) | LTV/CAC y payback | ratio \| meses | mayor_mejor (ltv_cac) / menor_mejor (payback) | publicidad, ventas |
| [MKT-10](#mkt-10) | Sesiones web y mix de tráfico | cantidad | mayor_mejor | analitica_web |
| [MKT-11](#mkt-11) | Tasa de conversión web | porcentaje | mayor_mejor | analitica_web |
| [MKT-12](#mkt-12) | Funnel e-commerce | porcentaje | mayor_mejor | analitica_web |
| [MKT-13](#mkt-13) | Abandono de carrito | porcentaje | menor_mejor | analitica_web |
| [MKT-14](#mkt-14) | Venta atribuida por canal de marketing | moneda \| cantidad | neutral | ventas, ventas (con UTM) |
| [MKT-15](#mkt-15) | Leads y costo por lead (CPL) | cantidad \| moneda | menor_mejor (CPL) | crm o analitica_web o publicidad |
| [MKT-16](#mkt-16) | Conversión de leads (lead → calificado → cliente) y velocidad de contacto | porcentaje \| minutos | mayor_mejor (conversión) / menor_mejor (tiempo) | crm |
| [MKT-17](#mkt-17) | Rendimiento de email marketing | porcentaje \| moneda | mayor_mejor (salvo bajas) | email_marketing |
| [MKT-18](#mkt-18) | Crecimiento de la base de suscriptores | cantidad \| porcentaje | mayor_mejor | email_marketing |
| [MKT-19](#mkt-19) | Distribución de inversión y eficiencia por plataforma | varias | neutral | publicidad |
| [MKT-20](#mkt-20) | Frecuencia y fatiga creativa | ratio \| cantidad | menor_mejor | publicidad |
| [MKT-21](#mkt-21) | Peso del tráfico orgánico | porcentaje | mayor_mejor | analitica_web o ventas (con UTM) |
| [MKT-22](#mkt-22) | Inversión en marketing sobre ventas | porcentaje | neutral (objetivo tenant) | publicidad, ventas |

---

## MKT-01
### Inversión publicitaria

**Pregunta que responde:** ¿Cuánto invertimos en publicidad?  
**Definición:** Σ gasto de fct_ads_diario en el período.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ads.inversion` |
| Unidad | moneda |
| Dirección | neutral |
| Agregación | aditivo |
| Grano mínimo | dia |
| Dimensiones | plataforma, cuenta_ads, campana, objetivo, tipo_campana, canal_marketing |
| Filtros base | — |
| Parámetros | `costo`=plataforma\|total, `moneda`=base\|<ISO>\|original, `ajuste`=nominal\|real |
| Roles de fuente mínimos | publicidad |
| Historia mínima | — |
| Relacionados | MKT-07, MKT-22 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(gasto) from core.fct_ads_diario where fecha between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_ads_diario.fecha` | obligatoria |
| `fct_ads_diario.gasto` | obligatoria |
| `dim_campana.objetivo` | opcional (habilita desgloses o mayor precisión) |
| `dim_campana.canal_marketing` | opcional (habilita desgloses o mayor precisión) |
| `ref.tipo_cambio.valor` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Cuentas facturadas en moneda extranjera → TC del día del gasto; mostrar también en una moneda de referencia para comparar sin efecto de devaluación.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| gasto diario > 1.5× presupuesto diario configurado | alta |
| gasto del mes proyectado > presupuesto de marketing | alta |

---

## MKT-02
### Impresiones y CPM

**Pregunta que responde:** ¿Cuánta gente vio nuestros anuncios y a qué costo?  
**Definición:** Σ impresiones; CPM = gasto / impresiones × 1000.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ads.impresiones, ads.cpm` |
| Unidad | cantidad \| moneda |
| Dirección | menor_mejor (CPM) |
| Agregación | aditivo / ratio |
| Grano mínimo | dia |
| Dimensiones | plataforma, campana, conjunto, anuncio, objetivo |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | publicidad |
| Historia mínima | — |
| Relacionados | MKT-20 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(impresiones), sum(gasto)/nullif(sum(impresiones),0)*1000 from core.fct_ads_diario where fecha between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_ads_diario.gasto` | obligatoria |
| `fct_ads_diario.impresiones` | obligatoria |

**Casos borde y reglas:**

- Alcance no es aditivo entre días/campañas: solo se informa a nivel plataforma y período tal como lo devuelve la API.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| cpm real sube > 30% vs promedio 4 semanas | media |

---

## MKT-03
### CTR

**Pregunta que responde:** ¿Qué porcentaje de quienes ven el anuncio hace clic?  
**Definición:** Clics al sitio (link clicks) / impresiones.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ads.ctr` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | plataforma, campana, conjunto, anuncio, tipo_campana |
| Filtros base | — |
| Parámetros | `tipo_clic`=enlace\|todos |
| Roles de fuente mínimos | publicidad |
| Historia mínima | — |
| Relacionados | MKT-20 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(clics_enlace)::numeric/nullif(sum(impresiones),0) from core.fct_ads_diario where fecha between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_ads_diario.impresiones` | obligatoria |
| `fct_ads_diario.clics_enlace` | obligatoria |

**Casos borde y reglas:**

- Comparar CTR solo dentro de la misma plataforma y tipo de campaña (search vs social difieren por naturaleza).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| anuncio con ctr cae > 30% vs su primera semana y frecuencia > 3 (fatiga) | media |

---

## MKT-04
### CPC

**Pregunta que responde:** ¿Cuánto nos cuesta cada clic?  
**Definición:** Gasto / clics al sitio.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ads.cpc` |
| Unidad | moneda |
| Dirección | menor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | plataforma, campana, conjunto, anuncio |
| Filtros base | — |
| Parámetros | `ajuste`=real por defecto en comparaciones |
| Roles de fuente mínimos | publicidad |
| Historia mínima | — |
| Relacionados | MKT-03 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(gasto)/nullif(sum(clics_enlace),0) from core.fct_ads_diario where fecha between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_ads_diario.gasto` | obligatoria |
| `fct_ads_diario.clics_enlace` | obligatoria |

**Casos borde y reglas:**

- 

---

## MKT-05
### Conversiones y CPA de plataforma

**Pregunta que responde:** ¿Cuántas compras/leads reporta cada plataforma y a qué costo?  
**Definición:** Σ conversiones_plataforma; CPA = gasto / conversiones (por plataforma, nunca sumado entre plataformas).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ads.conversiones_plataforma, ads.cpa_plataforma` |
| Unidad | cantidad \| moneda |
| Dirección | menor_mejor (CPA) |
| Agregación | aditivo dentro de plataforma / ratio |
| Grano mínimo | dia |
| Dimensiones | plataforma (obligatoria), campana, conjunto, anuncio, objetivo |
| Filtros base | objetivo in (ventas) para compras; (leads) para leads |
| Parámetros | `conversion`=compra\|lead |
| Roles de fuente mínimos | publicidad |
| Historia mínima | — |
| Relacionados | MKT-06, MKT-08 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select plataforma, sum(conversiones_plataforma), sum(gasto)/nullif(sum(conversiones_plataforma),0) from core.fct_ads_diario where fecha between :desde and :hasta group by 1;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_ads_diario.gasto` | obligatoria |
| `fct_ads_diario.conversiones_plataforma` | obligatoria si se usa la variante **compras** |
| `fct_ads_diario.leads_plataforma` | obligatoria si se usa la variante **leads** |
| `dim_campana.objetivo` | opcional (habilita desgloses o mayor precisión) |

Basta con que se cumpla **una** de las variantes: compras, leads (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- Si se pide sin dimensión plataforma, el MCP fuerza el desglose y advierte que no son sumables.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| cpa_plataforma de campaña de ventas > 1.5× CPA objetivo 3 días seguidos | media |

---

## MKT-06
### ROAS de plataforma

**Pregunta que responde:** ¿Cuánto dice cada plataforma que vendió por cada unidad de moneda invertida?  
**Definición:** Valor de conversiones de plataforma / gasto, por plataforma.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ads.roas_plataforma` |
| Unidad | ratio |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | plataforma (obligatoria), campana, conjunto, anuncio |
| Filtros base | objetivo = ventas |
| Parámetros | — |
| Roles de fuente mínimos | publicidad |
| Historia mínima | — |
| Relacionados | MKT-07 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select plataforma, sum(valor_conversiones_plataforma)/nullif(sum(gasto),0) from core.fct_ads_diario where fecha between :desde and :hasta group by 1;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_ads_diario.gasto` | obligatoria |
| `fct_ads_diario.valor_conversiones_plataforma` | obligatoria |

**Casos borde y reglas:**

- valor_conversiones incluye impuesto indirecto y a veces envío (lo que envía la etiqueta de conversión); para comparar con venta neta dividir por (1+impuesto indirecto) si el tenant lo configura.
- Útil para optimizar DENTRO de una plataforma; para decidir presupuesto total usar MKT-07.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| roas_plataforma < roas_minimo tenant (default 3) en campaña con gasto > 10% del total | media |

---

## MKT-07
### MER / ROAS real

**Pregunta que responde:** ¿Cuánto vendemos en total por cada unidad de moneda invertida en marketing?  
**Definición:** MER = venta neta total (VEN-01) / inversión total en marketing (ads + otros gastos de marketing opcionales). ROAS real por canal = venta atribuida last-click al canal / gasto del canal.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `marketing.mer, marketing.roas_real` |
| Unidad | ratio |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia (semana recomendado) |
| Dimensiones | canal_marketing, plataforma (solo roas_real), campana (solo si utm consistente) |
| Filtros base | pedido_valido |
| Parámetros | `incluir_canales`=online\|todos, `modelo`=ultimo_clic_utm, `incluir_otros_gastos_mkt`=False |
| Roles de fuente mínimos | publicidad, ventas |
| Historia mínima | — |
| Relacionados | MKT-06, MKT-08, MKT-22 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
mer = VEN-01.venta_neta / nullif(MKT-01.inversion, 0)
roas_real_canal = Σ fct_pedido.importe_neto join fct_atribucion_pedido(modelo='ultimo_clic_utm') por canal_marketing
                  / Σ fct_ads_diario.gasto por canal_marketing
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.importe_neto` | obligatoria |
| `fct_ads_diario.gasto` | obligatoria |
| `fct_atribucion_pedido.canal_marketing` | opcional (habilita desgloses o mayor precisión) |
| `fct_atribucion_pedido.campana_id` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.utm_source` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.utm_medium` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.utm_campaign` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- MER con incluir_canales='online' excluye mostrador/mayorista para no inflar.
- Last-click subestima plataformas de awareness (awareness); el agente lo menciona al comparar canales.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| mer semanal cae > 20% vs promedio 4 semanas | alta |

---

## MKT-08
### CAC (costo de adquisición de cliente)

**Pregunta que responde:** ¿Cuánto nos cuesta conseguir un cliente nuevo?  
**Definición:** Inversión en marketing de adquisición / clientes nuevos (VEN-11) del período; CAC por canal usando atribución de primer pedido.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `marketing.cac_blended, marketing.cac_pago` |
| Unidad | moneda |
| Dirección | menor_mejor |
| Agregación | ratio |
| Grano mínimo | mes |
| Dimensiones | canal_marketing, plataforma (cac_pago) |
| Filtros base | canales online por defecto |
| Parámetros | `costo`=plataforma\|total, `excluir_retargeting`=True |
| Roles de fuente mínimos | publicidad, ventas |
| Historia mínima | — |
| Relacionados | MKT-09, VEN-11 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
cac_blended = MKT-01.inversion / nullif(VEN-11.nuevos, 0)
cac_pago = gasto canales pagos / nuevos cuyo primer pedido se atribuye a canal pago
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_ads_diario.gasto` | obligatoria |
| `fct_pedido.cliente_id` | obligatoria |
| `fct_pedido.fecha_pedido` | obligatoria |
| `dim_campana.objetivo` | opcional (habilita desgloses o mayor precisión) |
| `fct_atribucion_pedido.canal_marketing` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Campañas objetivo 'retargeting' se excluyen del numerador si excluir_retargeting (no adquieren).

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| cac real sube > 25% vs trimestre anterior | alta |

---

## MKT-09
### LTV/CAC y payback

**Pregunta que responde:** ¿Recuperamos lo que invertimos para conseguir clientes? ¿En cuánto tiempo?  
**Definición:** LTV 12m (VEN-14, en margen) / CAC; payback = meses hasta que el margen acumulado de la cohorte iguala su CAC.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `marketing.ltv_cac, marketing.payback_meses` |
| Unidad | ratio \| meses |
| Dirección | mayor_mejor (ltv_cac) / menor_mejor (payback) |
| Agregación | calculado por cohorte |
| Grano mínimo | mes |
| Dimensiones | cohorte, canal_marketing adquisición |
| Filtros base | — |
| Parámetros | `ajuste`=real |
| Roles de fuente mínimos | publicidad, ventas |
| Historia mínima | ≥ 12 meses de ventas + ads |
| Relacionados | VEN-14, MKT-08 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
ltv_cac = VEN-14.ltv_12m / nullif(MKT-08.cac_blended, 0)   -- misma cohorte/período de adquisición
payback_meses = min(m) tal que margen_acumulado_cohorte(m)/clientes >= cac_cohorte
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_ads_diario.gasto` | obligatoria |
| `fct_pedido.cliente_id` | obligatoria |
| `fct_pedido.fecha_pedido` | obligatoria |
| `fct_pedido_linea.costo_total` | obligatoria |

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| ltv_cac < 3 | media |
| ltv_cac < 1 | alta |

---

## MKT-10
### Sesiones web y mix de tráfico

**Pregunta que responde:** ¿Cuántas visitas tuvo el sitio y de dónde vienen?  
**Definición:** Σ sesiones de la analítica web; participación por canal de marketing.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `web.sesiones` |
| Unidad | cantidad |
| Dirección | mayor_mejor |
| Agregación | aditivo (sesiones) — usuarios NO aditivo |
| Grano mínimo | dia |
| Dimensiones | canal_marketing, fuente, medio, campana, dispositivo |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | analitica_web |
| Historia mínima | — |
| Relacionados | MKT-11, MKT-21 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select canal_marketing, sum(sesiones) from core.fct_web_diario where fecha between :desde and :hasta group by 1;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_web_diario.sesiones` | obligatoria |
| `fct_web_diario.canal_marketing` | opcional (habilita desgloses o mayor precisión) |
| `fct_web_diario.usuarios` | opcional (habilita desgloses o mayor precisión) |
| `fct_web_diario.dispositivo` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Usuarios de un período = consulta directa a la analítica web del rango (no suma de días); se guarda solo por día.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| sesiones diarias < 50% del promedio del mismo día de semana (posible caída de tracking o sitio) | critica |

---

## MKT-11
### Tasa de conversión web

**Pregunta que responde:** ¿Qué porcentaje de visitas termina en compra?  
**Definición:** Pedidos e-commerce válidos (fuente de verdad, canal ecommerce_propio) / sesiones la analítica web. Alternativa la analítica web pura = transacciones / sesiones.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `web.tasa_conversion` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | canal_marketing, dispositivo, campana (solo cr_analitica) |
| Filtros base | — |
| Parámetros | `base`=negocio\|analitica |
| Roles de fuente mínimos | analitica_web |
| Historia mínima | — |
| Relacionados | MKT-12 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
cr = count(pedidos validos canal='ecommerce_propio') / nullif(sum(fct_web_diario.sesiones), 0)
cr_analitica = sum(transacciones) / nullif(sum(sesiones), 0)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_web_diario.sesiones` | obligatoria |
| `fct_pedido.canal_id` | obligatoria si se usa la variante **base_negocio** |
| `fct_pedido.fecha_pedido` | obligatoria si se usa la variante **base_negocio** |
| `fct_web_diario.transacciones` | obligatoria si se usa la variante **base_analitica** |
| `fct_web_diario.transacciones` | opcional (habilita desgloses o mayor precisión) |
| `fct_web_diario.canal_marketing` | opcional (habilita desgloses o mayor precisión) |

Basta con que se cumpla **una** de las variantes: base_negocio, base_analitica (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- Diferencia grande entre cr y cr_analitica (> 20%) indica tracking roto o bloqueo de cookies → DQ-16.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| cr cae > 20% vs promedio 4 semanas con sesiones estables | alta |

---

## MKT-12
### Funnel e-commerce

**Pregunta que responde:** ¿En qué paso del recorrido perdemos compradores?  
**Definición:** Tasas de paso sesiones → vista de producto → carrito → checkout → compra.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `web.funnel_*` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | dispositivo, canal_marketing |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | analitica_web |
| Historia mínima | — |
| Relacionados | MKT-11, MKT-13 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(vistas_producto)/nullif(sum(sesiones),0) s_a_producto,
       sum(agregados_carrito)/nullif(sum(vistas_producto),0) producto_a_carrito,
       sum(checkouts_iniciados)/nullif(sum(agregados_carrito),0) carrito_a_checkout,
       sum(transacciones)/nullif(sum(checkouts_iniciados),0) checkout_a_compra
from core.fct_web_diario where fecha between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_web_diario.sesiones` | obligatoria |
| `fct_web_diario.vistas_producto` | obligatoria |
| `fct_web_diario.agregados_carrito` | obligatoria |
| `fct_web_diario.checkouts_iniciados` | obligatoria |
| `fct_web_diario.transacciones` | obligatoria |

**Casos borde y reglas:**

- Eventos de e-commerce mal implementados (vistas_producto = 0) → KPI no disponible.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| checkout_a_compra cae > 15% vs 4 semanas (posible problema de pago) | critica |

---

## MKT-13
### Abandono de carrito

**Pregunta que responde:** ¿Cuántos carritos no terminan en compra?  
**Definición:** 1 − transacciones / carritos iniciados (la analítica web); alternativa e-commerce = checkouts abandonados de la plataforma de e-commerce / checkouts creados.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `web.abandono_carrito` |
| Unidad | porcentaje |
| Dirección | menor_mejor |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | dispositivo, canal_marketing |
| Filtros base | — |
| Parámetros | `base`=analitica\|plataforma |
| Roles de fuente mínimos | analitica_web |
| Historia mínima | — |
| Relacionados | MKT-12 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
abandono = 1 - sum(transacciones) / nullif(sum(agregados_carrito), 0)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_web_diario.agregados_carrito` | obligatoria |
| `fct_web_diario.transacciones` | obligatoria |

**Casos borde y reglas:**

- La base 'plataforma' requiere que la fuente de e-commerce exponga checkouts/carritos abandonados (mapearlos a fct_web_diario.checkouts_iniciados por día).

---

## MKT-14
### Venta atribuida por canal de marketing

**Pregunta que responde:** ¿Qué canales de marketing traen las ventas?  
**Definición:** Venta neta y pedidos por canal_marketing según modelo de atribución.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ventas.venta_neta (dimensión canal_marketing, modelo)` |
| Unidad | moneda \| cantidad |
| Dirección | neutral |
| Agregación | aditivo |
| Grano mínimo | dia |
| Dimensiones | canal_marketing, campana, fuente, medio |
| Filtros base | pedido_valido |
| Parámetros | `modelo`=ultimo_clic_utm\|primer_contacto |
| Roles de fuente mínimos | ventas, ventas (con UTM) |
| Historia mínima | — |
| Relacionados | MKT-07 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select a.canal_marketing, sum(p.importe_neto * a.peso), count(distinct p.pedido_id)
from core.fct_pedido p join core.fct_atribucion_pedido a using (tenant_id, pedido_id)
where pedido_valido and a.modelo = :modelo and p.fecha_pedido between :desde and :hasta group by 1;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_pedido.importe_neto` | obligatoria |
| `fct_atribucion_pedido.canal_marketing` | obligatoria |
| `fct_atribucion_pedido.campana_id` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.utm_source` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.utm_medium` | opcional (habilita desgloses o mayor precisión) |
| `fct_pedido.utm_campaign` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- % de venta 'sin_asignar' > 20% → UTMs mal configuradas; el agente recomienda revisar.

---

## MKT-15
### Leads y costo por lead (CPL)

**Pregunta que responde:** ¿Cuántos leads generamos y cuánto nos cuesta cada uno?  
**Definición:** Leads creados en CRM en el período (fuente de verdad); CPL = gasto de campañas objetivo leads / leads atribuidos a esas campañas (o total).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `leads.cantidad, leads.cpl, ads.cpl_plataforma` |
| Unidad | cantidad \| moneda |
| Dirección | menor_mejor (CPL) |
| Agregación | aditivo / ratio |
| Grano mínimo | dia |
| Dimensiones | canal_marketing, campana, formulario, vendedor |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | crm o analitica_web o publicidad |
| Historia mínima | — |
| Relacionados | MKT-16 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
leads = count(fct_lead where fecha_creacion in periodo)
cpl = Σ gasto (objetivo='leads') / nullif(count(leads con canal pago), 0)
cpl_plataforma = Σ gasto / Σ leads_plataforma   (por plataforma)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_lead.fecha_creacion` | obligatoria si se usa la variante **crm** |
| `fct_web_diario.leads_web` | obligatoria si se usa la variante **analitica_web** |
| `fct_ads_diario.leads_plataforma` | obligatoria si se usa la variante **plataforma** |
| `fct_ads_diario.gasto` | opcional (habilita desgloses o mayor precisión) |
| `dim_campana.objetivo` | opcional (habilita desgloses o mayor precisión) |
| `fct_lead.canal_marketing` | opcional (habilita desgloses o mayor precisión) |
| `fct_lead.utm_campaign` | opcional (habilita desgloses o mayor precisión) |

Basta con que se cumpla **una** de las variantes: crm, analitica_web, plataforma (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- Leads duplicados (mismo email/teléfono en 30 días) se cuentan una vez.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| cpl sube > 30% vs 4 semanas | media |

---

## MKT-16
### Conversión de leads (lead → calificado → cliente) y velocidad de contacto

**Pregunta que responde:** ¿Cuántos leads se convierten en clientes y qué tan rápido los atendemos?  
**Definición:** % calificados, % convertidos (cohorte por fecha de creación); mediana de minutos hasta el primer contacto.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `leads.pct_calificado, leads.pct_convertido, leads.minutos_primer_contacto` |
| Unidad | porcentaje \| minutos |
| Dirección | mayor_mejor (conversión) / menor_mejor (tiempo) |
| Agregación | ratio / mediana |
| Grano mínimo | semana |
| Dimensiones | canal_marketing, campana, vendedor, formulario |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | crm |
| Historia mínima | — |
| Relacionados | MKT-15, VEN-20 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
pct_calificado = count(estado in (calificado, convertido)) / count(*)
pct_convertido = count(estado = convertido) / count(*)        -- cohorte, madurez ≥ ciclo de venta
tiempo_primer_contacto = median(primer_contacto_at - creado_at)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_lead.fecha_creacion` | obligatoria |
| `fct_lead.estado` | obligatoria |
| `fct_lead.primer_contacto_at` | opcional (habilita desgloses o mayor precisión) |
| `fct_lead.fecha_conversion` | opcional (habilita desgloses o mayor precisión) |
| `fct_lead.canal_marketing` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Cohortes recientes no maduraron: marcar.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| leads sin contactar > 24 h | alta |

---

## MKT-17
### Rendimiento de email marketing

**Pregunta que responde:** ¿Funcionan nuestros emails?  
**Definición:** Tasa de apertura = aperturas únicas / entregados; CTR = clics únicos / entregados; CTOR = clics / aperturas; bajas = bajas / entregados; ingresos por email = ingresos atribuidos / entregados × 1000.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `email.open_rate, email.ctr, email.unsub_rate, email.ingresos_por_mil` |
| Unidad | porcentaje \| moneda |
| Dirección | mayor_mejor (salvo bajas) |
| Agregación | ratio |
| Grano mínimo | dia |
| Dimensiones | plataforma, tipo (campana\|flow), nombre |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | email_marketing |
| Historia mínima | — |
| Relacionados | MKT-18 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select sum(aperturas_unicas)::numeric/nullif(sum(entregados),0) open_rate,
       sum(clics_unicos)::numeric/nullif(sum(entregados),0) ctr,
       sum(bajas)::numeric/nullif(sum(entregados),0) unsub_rate,
       sum(ingresos_atribuidos)/nullif(sum(entregados),0)*1000 ingresos_por_mil
from core.fct_email_campana where fecha_envio between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_email_campana.entregados` | obligatoria |
| `fct_email_campana.clics_unicos` | obligatoria |
| `fct_email_campana.aperturas_unicas` | opcional (habilita desgloses o mayor precisión) |
| `fct_email_campana.bajas` | opcional (habilita desgloses o mayor precisión) |
| `fct_email_campana.ingresos_atribuidos` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Open rate inflado por protecciones de privacidad de clientes de correo: priorizar CTR y clics.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| unsub_rate > 0.5% o spam > 0.1% en un envío | alta |

---

## MKT-18
### Crecimiento de la base de suscriptores

**Pregunta que responde:** ¿Crece nuestra base de contactos?  
**Definición:** Suscriptores activos al cierre; altas netas = altas − bajas del período; tasa de crecimiento neta.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `email.suscriptores, email.altas_netas` |
| Unidad | cantidad \| porcentaje |
| Dirección | mayor_mejor |
| Agregación | snapshot / aditivo |
| Grano mínimo | dia |
| Dimensiones | plataforma, lista |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | email_marketing |
| Historia mínima | — |
| Relacionados | MKT-17 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
select (array_agg(suscriptores_activos order by fecha desc))[1] activos_cierre, sum(altas) - sum(bajas) altas_netas from core.fct_suscriptores_diario where fecha between :desde and :hasta;
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_suscriptores_diario.suscriptores_activos` | obligatoria |
| `fct_suscriptores_diario.altas` | obligatoria |
| `fct_suscriptores_diario.bajas` | obligatoria |

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| altas_netas < 0 en el mes | media |

---

## MKT-19
### Distribución de inversión y eficiencia por plataforma

**Pregunta que responde:** ¿Cómo repartimos el presupuesto y dónde rinde más?  
**Definición:** % del gasto por plataforma/campaña junto a su ROAS real (MKT-07), CAC pago (MKT-08) y ROAS plataforma (MKT-06).

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `view marketing_scorecard` |
| Unidad | varias |
| Dirección | neutral |
| Agregación | vista |
| Grano mínimo | semana |
| Dimensiones | plataforma, campana, objetivo |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | publicidad |
| Historia mínima | — |
| Relacionados | MKT-07, MKT-08 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
vista compuesta MKT-01 (share), MKT-06, MKT-07 (roas_real por plataforma), MKT-08 (cac_pago)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_ads_diario.gasto` | obligatoria |
| `fct_ads_diario.valor_conversiones_plataforma` | opcional (habilita desgloses o mayor precisión) |
| `fct_ads_diario.conversiones_plataforma` | opcional (habilita desgloses o mayor precisión) |
| `fct_atribucion_pedido.canal_marketing` | opcional (habilita desgloses o mayor precisión) |
| `fct_atribucion_pedido.campana_id` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- 

---

## MKT-20
### Frecuencia y fatiga creativa

**Pregunta que responde:** ¿Estamos saturando a la audiencia con los mismos anuncios?  
**Definición:** Frecuencia (impresiones / alcance) por anuncio en 7 días y tendencia de CTR/CPA del anuncio vs su primera semana.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `ads.frecuencia, ads.anuncios_fatigados` |
| Unidad | ratio \| cantidad |
| Dirección | menor_mejor |
| Agregación | calculado |
| Grano mínimo | semana |
| Dimensiones | plataforma, campana, anuncio |
| Filtros base | plataformas sociales |
| Parámetros | `umbral_frecuencia`=3 |
| Roles de fuente mínimos | publicidad |
| Historia mínima | — |
| Relacionados | MKT-03 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
frecuencia_7d = impresiones_7d / alcance_7d (dato de la API a nivel anuncio)
fatiga = frecuencia_7d > 3 and ctr_7d < 0.7 × ctr_primera_semana
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_ads_diario.impresiones` | obligatoria |
| `fct_ads_diario.alcance` | obligatoria |
| `fct_ads_diario.frecuencia` | obligatoria |
| `fct_ads_diario.clics_enlace` | obligatoria |

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| anuncio fatigado con gasto > 10% de su campaña | media |

---

## MKT-21
### Peso del tráfico orgánico

**Pregunta que responde:** ¿Cuánto del tráfico y la venta no depende de pagar publicidad?  
**Definición:** Sesiones y venta atribuida de canales no pagos (busqueda_organica, social_organico, directo, referral, email) / total.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `web.pct_organico, ventas.pct_venta_no_paga` |
| Unidad | porcentaje |
| Dirección | mayor_mejor |
| Agregación | ratio |
| Grano mínimo | semana |
| Dimensiones | canal_marketing |
| Filtros base | — |
| Parámetros | — |
| Roles de fuente mínimos | analitica_web o ventas (con UTM) |
| Historia mínima | — |
| Relacionados | MKT-10, MKT-14 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
pct_sesiones_organicas = Σ sesiones where not es_pago / Σ sesiones
pct_venta_no_paga = Σ venta atribuida canal no pago / Σ venta atribuida
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_web_diario.sesiones` | obligatoria si se usa la variante **web** |
| `fct_web_diario.canal_marketing` | obligatoria si se usa la variante **web** |
| `fct_atribucion_pedido.canal_marketing` | obligatoria si se usa la variante **pedidos** |

Basta con que se cumpla **una** de las variantes: web, pedidos (se usa la primera disponible en ese orden y se informa en `metadata.modo`).

**Casos borde y reglas:**

- 

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| pct_venta_no_paga cae > 10 pp en el trimestre | media |

---

## MKT-22
### Inversión en marketing sobre ventas

**Pregunta que responde:** ¿Qué porcentaje de la venta reinvertimos en marketing?  
**Definición:** Inversión en marketing (ads + otros gastos de marketing de cuentas cuenta estándar 6.1.03 si incluir_otros) / venta neta.

| Atributo | Valor |
|---|---|
| Medida en capa semántica | `marketing.inversion_pct_venta` |
| Unidad | porcentaje |
| Dirección | neutral (objetivo tenant) |
| Agregación | ratio |
| Grano mínimo | mes |
| Dimensiones | canal (online vs total) |
| Filtros base | — |
| Parámetros | `incluir_otros_gastos_mkt`=True |
| Roles de fuente mínimos | publicidad, ventas |
| Historia mínima | — |
| Relacionados | MKT-07, FIN-04 |

**Fórmula de referencia (SQL sobre `core`; la implementación productiva vive en la capa semántica):**

```sql
mkt_pct_venta = (MKT-01.inversion + otros_gastos_mkt) / nullif(VEN-01.venta_neta, 0)
```

**Requisitos de datos canónicos:**

| Columna canónica | Tipo de requisito |
|---|---|
| `fct_ads_diario.gasto` | obligatoria |
| `fct_pedido.importe_neto` | obligatoria |
| `fct_asiento_linea.saldo` | opcional (habilita desgloses o mayor precisión) |
| `dim_cuenta_contable.codigo_estandar` | opcional (habilita desgloses o mayor precisión) |

**Casos borde y reglas:**

- Evitar doble conteo: si las facturas de las plataformas publicitarias están contabilizadas en cuenta estándar 6.1.03, no sumar fct_ads_diario además.

**Alertas por defecto** (sobreescribibles en `ops.tenant_config_kpi`):

| Condición | Severidad |
|---|---|
| mkt_pct_venta > objetivo tenant + 3 pp | media |

