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
  más de 1,5 veces. Configurable por empresa.
