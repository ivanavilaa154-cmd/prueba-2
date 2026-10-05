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
| 2 | Unidades y conversiones exactas, venta por peso | hecho (migración 016, `unidades.py`; el lector de facturas convierte con el factor cargado) |
| 3 | Costo de reposición e histórico, impuestos (IVA, internos, IIBB), descuentos de proveedor; margen neto | hecho (Configuración → Unidades e impuestos; ganancia y margen sin IVA) |
| 4 | Diagnóstico de calidad de datos (5.6) | hecho (`calidad.py`, pantalla Calidad de datos, confianza por producto en Comprar; la demo siembra un caso de cada problema) |
| 5 | Agente de sincronización por carpeta (5.1) | hecho (`tools/agente/agente_sync.py` solo con la biblioteca estándar, cola local con reintentos crecientes, token propio revocable; migración 018; tarjeta en Datos → Conexiones; los formatos nuevos se retoman en Datos → Importar) |
| 6 | Datos del modo distribuidor (12B) desde Odoo y archivos | hecho (`odoo_distribuidor.py`: clientes, vendedores, pedidos con lo entregado, facturas con saldo y cobros; importación de clientes, pedidos y cuenta corriente por archivo o por el agente; los pedidos entran a la demanda por el canal mayorista) |
| 7 | Los 5 reportes iniciales del distribuidor (12B.7) y vista del vendedor | hecho (`distribuidor.py`, migración 019; pantallas Clientes, Vendedores, Pedidos y entregas, Cuenta corriente y Mi cartera (celular); vendedor y cobranzas solo ven sus pantallas y su cartera) |
| 8 | Demo distribuidora (16) | hecho (`demo_distribuidora.py`: «Distribuidora del Valle», 6 vendedores, 350 clientes en 4 zonas, 13 meses de pedidos; se carga sola en modo demo; dueno@valle.demo, jefe@valle.demo, cobranzas@valle.demo, carla@valle.demo…) |
| 9 | MAPE y métricas de soporte (13.7) | hecho (migración 020: foto diaria de WAPE/MAPE/sesgo/cobertura por empresa, tiempo de implementación, tickets de soporte; panel «Costo de servir» en Plataforma; «Pedir ayuda» en Configuración) |
| 10 | Primer ingreso guiado de 6 pasos (15) | hecho (migración 021, pantalla /bienvenida: lo que se ve en los datos se marca solo, lo demás lo confirma el dueño; una empresa nueva sin datos arranca ahí) |
| 11 | Criterios de aceptación nuevos (17) y tiempos | pendiente |

**Fase 2 (después):** rutas y cobertura completas (12B.3), logística (tiempos de entrega, repartidores; 12B.5), marcas representadas completas (12B.6), lectura directa de bases
locales en el agente.
