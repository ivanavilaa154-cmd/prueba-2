# Predicciones con IA para Retail — qué ya está y qué falta

Fuente: `predicciones_ia_retail.pdf` (29/09/2026): 43 predicciones en 8 áreas, panel por rol, «rango de confianza + acción sugerida»,
caso de liquidaciones y hoja de ruta. Estado: ✔ hecho · ◐ parcial · ✕ falta.

| # | Predicción | Prioridad | Estado | Dónde está hoy / qué falta |
|---|---|---|---|---|
| 1 | Venta por producto y sucursal | Alta | ◐ | Pronóstico diario (Comprar y reponer). Falta banda de confianza y medir el error (WAPE, sesgo). |
| 2 | Venta total por sucursal y canal | Alta | ◐ | Metas con proyección de cierre. Falta pronóstico diario por sucursal × canal (calendario de calor). |
| 3 | Estacionalidad y eventos | Alta | ◐ | Factores de estacionalidad, feriados y fechas comerciales en el cálculo. Falta la curva anual visible. |
| 4 | Demanda de productos nuevos | Media | ◐ | Se mezcla con la categoría. Falta rango bajo/medio/alto para el primer pedido. |
| 5 | Canibalización y sustitución | Media | ◐ | Dentro de efectividad de promociones. Falta tabla de pares afectados por quiebres. |
| 6 | Venta del canal online | Media | ◐ | Resultado por canal. Falta pronóstico. |
| 7 | Riesgo de quiebre | Alta | ◐ | Semáforo y fecha de quiebre. Falta probabilidad (con la banda). |
| 8 | Pedido sugerido a proveedor | Alta | ✔ | Comprar y reponer, OC sugeridas. |
| 9 | Sobrestock y días de cobertura | Alta | ✔ | Plata parada. |
| 10 | Productos que van a vencer | Alta | ✔ | Vencimientos y ofertas. |
| 11 | Demora real de proveedores | Media | ✔ | Proveedores (puntualidad). |
| 12 | Stock fantasma | Media | ✔ | Avisos y recuentos sugeridos. |
| 13 | Elasticidad al precio | Alta | ✔ | Ventas → Sensibilidad al precio. |
| 14 | Venta incremental de una promo | Alta | ◐ | Medida después (Promociones). Falta el simulador antes de lanzarla. |
| 15 | Precio de liquidación | Media | ◐ | Descuento mínimo por vencimiento. Falta escalera de rebajas. |
| 16 | Precio de la competencia | Media | ✕ | Necesita cargar relevamientos de precios. |
| 17 | Inflación en el volumen | Alta | ✔ | Ventas sin inflación, efecto precio/cantidad. |
| 18 | Abandono de clientes | Alta | ✔ | Ventas → Clientes (dejaron de venir). |
| 19 | Valor de vida del cliente | Media | ✕ | |
| 20 | Próxima compra | Media | ✕ | |
| 21 | Respuesta a ofertas y cupones | Media | ✕ | Necesita historial de campañas. |
| 22 | Segmento dinámico | Media | ◐ | Segmentos RFM. |
| 23 | Afinidad de canasta | Media | ✔ | Ventas → Canasta. |
| 24 | Rendimiento por metro de góndola | Media | ✕ | Necesita metros y frentes por producto. |
| 25 | Productos a discontinuar | Media | ✔ | Ventas → Surtido. |
| 26 | Éxito de un lanzamiento | Media | ✕ | |
| 27 | Surtido ideal por sucursal | Baja | ✔ | Surtido (qué sumar por sucursal). |
| 28 | Afluencia por hora | Alta | ◐ | Mapa de calor histórico (Ticket y tráfico). Falta pronóstico. |
| 29 | Personal necesario por turno | Alta | ✕ | Necesita productividad por cajero (se deriva de tickets) y turnos. |
| 30 | Colas en caja | Media | ✕ | Necesita tickets en tiempo real. |
| 31 | Merma y robo | Media | ◐ | Merma y anomalías de caja. Falta ranking de pérdida por producto × sucursal. |
| 32 | Fallas de equipos de frío | Baja | ✕ | Necesita sensores de temperatura. |
| 33–39 | Distribución y sell-in | Alta/Media | ◐ | Panel de marcas (sell-out agregado) y pedidos. Falta pedido sugerido por cliente comercial, clientes comerciales en riesgo, carga por zona, entregas y rechazos (con datos de preventa/logística del Panel ERP). |
| 40 | Flujo de caja | Alta | ✕ | Hay plazos de acreditación por medio de pago y OC; falta la proyección. |
| 41 | Riesgo de cobro | Alta | ◐ | Fiado y morosos. Falta puntaje por cliente/factura. |
| 42 | Margen con inflación | Alta | ✔ | Precios (margen erosionado, costo de reposición). |
| 43 | Cierre contra presupuesto | Media | ✔ | Metas (proyección y semáforo). |

Además: **Salud de los modelos** (error y sesgo de cada pronóstico) ✕, **vistas por rol** ◐ (hoy por sección), **Liquidaciones activas** ◐
(ofertas, carteles y cierre; faltan ubicación puntera/isla/góndola, escalera, proyección de vaciado, reposición de puntera, control de
ejecución con foto y precio cartel vs caja).

## Plan propuesto (siguiendo la hoja de ruta del documento)

- **A. Base de confianza (Alta)**: banda de confianza en todos los pronósticos; guardar cada pronóstico y compararlo con lo real
  (WAPE y sesgo por producto, sucursal y categoría) → vista «Salud de los modelos»; probabilidad de quiebre (7); rango para productos
  nuevos (4).
- **B. Faltantes de prioridad alta**: pronóstico por sucursal × canal × día (2, 6) y curva anual con eventos (3); afluencia por hora
  pronosticada y personal necesario por turno (28, 29); simulador de promoción antes de lanzarla (14); flujo de caja a 90 días (40);
  riesgo de cobro (41).
- **C. Liquidaciones activas** (caso aplicado): escalera de rebajas, ubicación, proyección de vaciado, alerta de reponer puntera,
  control de ejecución (checklist y foto) y diferencias cartel vs caja.
- **D. Vistas por rol**: Dirección, Comercial, Sucursal (celular primero), Marketing, Finanzas y Salud de los modelos, con los bloques
  comunes (KPIs, alertas por impacto, pronóstico con banda, detalle y simulador).
- **E. Distribución (33–39)** en el Panel ERP, con los pedidos y clientes de Odoo.
- **F. Con datos nuevos**: competencia (16), clientes (19–21), góndola (24), lanzamientos (26), colas (30), frío (32).
