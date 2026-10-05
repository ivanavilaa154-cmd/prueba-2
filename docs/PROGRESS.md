# Avance contra la especificación (`docs/SPEC.md`)

Decisiones y supuestos: `docs/DECISIONS.md`. Historia anterior por fases: `docs/retail/plan.md`.

## Estado al 05/10/2026

**Ya cumplido antes de la SPEC v2** (construido con la versión anterior, `docs/retail/prompt_maestro.md`): modo comercio completo de
las fases 1, 2 y 3 (comprar y reponer, transferencias y OC, precios, ganadores, Pareto, inflación, ticket, caja, alertas, resumen
diario, multisucursal, plata parada, vencimientos, medios de pago, GMROI, proveedores, metas, copiloto, Tiendanube y Mercado Libre,
impacto, canasta, promociones, sensibilidad, surtido, clientes, panel de marcas, otras plataformas), privacidad (13.5), planes (13.6),
predicciones con IA y Panel ERP por empresa.

## Fase 1 de la SPEC v2 — lo que faltaba

| # | Paso | Estado |
|---|---|---|
| 1 | Modos de empresa (comercio / distribuidor / ambos) y roles jefe de ventas, vendedor y cobranzas | hecho (migración 015, cartera del vendedor por RLS) |
| 2 | Unidades y conversiones exactas, venta por peso | pendiente |
| 3 | Costo de reposición e histórico, impuestos (IVA, internos, IIBB), descuentos de proveedor; margen neto | pendiente |
| 4 | Diagnóstico de calidad de datos (5.6) | pendiente |
| 5 | Agente de sincronización por carpeta (5.1) | pendiente |
| 6 | Datos del modo distribuidor (12B) desde Odoo y archivos | pendiente |
| 7 | Los 5 reportes iniciales del distribuidor (12B.7) y vista del vendedor | pendiente |
| 8 | Demo distribuidora (16) | pendiente |
| 9 | MAPE y métricas de soporte (13.7) | pendiente |
| 10 | Primer ingreso guiado de 6 pasos (15) | pendiente |
| 11 | Criterios de aceptación nuevos (17) y tiempos | pendiente |

**Fase 2 (después):** rutas y cobertura (12B.3), fill rate y logística (12B.5), marcas representadas (12B.6), lectura directa de bases
locales en el agente.
