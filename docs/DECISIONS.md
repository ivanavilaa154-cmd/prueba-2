# Decisiones técnicas y supuestos (especificación `docs/SPEC.md`)

Cada decisión: qué se decidió, por qué y cómo se cambia si hace falta.

## 05/10/2026 — Tecnología: se sigue con el sistema actual
La SPEC sugiere un monorepo en TypeScript. El sistema ya está en Python (FastAPI) + PostgreSQL con RLS forzada + Next.js
(TypeScript, Tailwind, Recharts) y cumple la mayor parte de las fases 1 a 3. Decisión del dueño: construir solo lo que falta sobre lo
existente. Equivalencias con la estructura sugerida en la sección 18:

| SPEC | Este repositorio |
|---|---|
| `apps/web` | `frontend/` (pantallas Next.js, exportadas a `backend/app/web/retail/`) y `backend/app/main.py` (API) |
| `apps/sync-agent` | `tools/agente/` |
| `packages/core` | `backend/app/retail/calculos.py` y módulos de cálculo puros (sin base de datos), con pruebas |
| `packages/db` | `backend/app/retail/migraciones/` (esquema, RLS) y `demo.py` / `demo_distribuidor.py` (datos de demostración) |
| `packages/connectors` | `backend/app/retail/odoo_pos.py`, `plataformas_online.py`, `importar.py`, `backend/app/integraciones/` |
| `packages/ai` | `backend/app/retail/lector.py` y `copiloto.py` |

Los nombres de tablas están en español (por ejemplo `organizaciones` = `organizations`); la correspondencia está en `docs/PROGRESS.md`.

## 05/10/2026 — Modo distribuidor dentro de Retail
Misma base PostgreSQL con RLS, mismos usuarios y menú. Los datos entran desde la conexión de Odoo de la empresa (pedidos de venta,
facturas, pagos y clientes) o por archivos. El Panel ERP queda para el chat y el Centro de Decisiones.

## 05/10/2026 — CLAUDE.md
Se actualizan producto, estructura, comandos y referencias; las reglas numeradas no se tocan sin preguntar al dueño.

## Supuestos (configurables)
- **Unidad base:** la unidad en que se vende el producto (unidad o kg). Bultos y packs se convierten con un factor exacto (`numeric`).
- **Impuestos:** IVA y percepciones de IIBB son recuperables para un responsable inscripto: el margen se calcula sin ellos. Los
  impuestos internos no son recuperables: se suman al costo neto y se descuentan del precio neto de venta.
- **Costo de reposición:** costo de la última lista vigente del proveedor principal, menos sus descuentos y bonificaciones vigentes.
  **Costo histórico:** promedio ponderado de las recepciones (cantidad × costo) de los últimos 12 meses.
- **Cliente perdido (distribuidor):** sin comprar más de 3 veces su intervalo habitual entre compras (mínimo 21 días); en riesgo,
  más de 1,5 veces. Configurable por empresa. Una «compra» es un pedido no anulado ni rechazado; el intervalo habitual es la mediana de
  sus últimos 12 intervalos (con menos de 3 compras, 30 días). La plata que se deja de facturar es lo que compraba por mes en los
  180 días anteriores a su última compra.
- **Venta del distribuidor:** lo entregado de cada pedido (o lo pedido mientras está en camino), sin IVA. Precios y costos de los
  pedidos se guardan sin impuestos. En el agregado de ventas, la demanda (unidades) suma lo que no se entregó por falta de stock,
  para que la reposición no se achique por un quiebre; la facturación es solo lo entregado.
- **Oportunidades por cliente:** categorías que compra al menos el 40 % de los clientes parecidos (misma zona y canal; si son menos de
  5, mismo canal) en 90 días y este no; se sugiere el producto más elegido y la mediana de unidades por pedido.
- **Vendedor y cobranzas:** solo acceden a las pantallas del modo distribuidor; la base (RLS) acota la cartera del vendedor.
- **Agente con lectura directa (Fase 2):** el agente nunca escribe en la base del cliente: abre SQLite en modo solo lectura, ODBC con
  `readonly=True` y valida que cada consulta sea un único SELECT sin palabras que modifiquen datos. Trae solo lo nuevo con una marca de agua
  por consulta (columna `incremental` y `:desde` en el SQL). El resultado se deja como CSV en la carpeta y sigue el mismo camino que una
  exportación. Si las columnas se llaman exactamente como los datos de la plataforma, se importa sin confirmar columnas.
- **Logística del distribuidor:** `cantidad_entregada` es lo que el cliente se quedó; lo devuelto en el momento de la entrega se guarda
  aparte (`cantidad_devuelta`, con motivo). «A tiempo» = entregado hasta la fecha prometida. Desde Odoo, la fecha de entrega es la de la
  última salida terminada del pedido (stock.picking).
- **Cobertura por zona:** clientes que compraron en 90 días sobre el universo conocido (clientes + comercios relevados que no son clientes).

