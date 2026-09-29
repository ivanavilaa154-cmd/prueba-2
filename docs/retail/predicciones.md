# Predicciones con IA para Retail — qué ya está y qué falta

Fuente: `predicciones_ia_retail.pdf` (29/09/2026): 43 predicciones en 8 áreas, panel por rol, «rango de confianza + acción sugerida»,
caso de liquidaciones y hoja de ruta. Estado: ✔ hecho · ◐ parcial · ✕ falta. Actualizado el 29/09/2026 (partes A a F).

| # | Predicción | Prioridad | Estado | Dónde está |
|---|---|---|---|---|
| 1 | Venta por producto y sucursal | Alta | ✔ | Comprar y reponer: pronóstico con rango del 80 %, corregido por el sesgo medido (categoría × sucursal). |
| 2 | Venta total por sucursal y canal | Alta | ✔ | Pronósticos → Venta por sucursal y canal (día a día, con rango). |
| 3 | Estacionalidad y eventos | Alta | ✔ | Pronósticos → Año y eventos (curva anual, feriados y fechas comerciales). |
| 4 | Demanda de productos nuevos | Media | ✔ | Se mezcla con la categoría y su rango es más ancho (poca historia). |
| 5 | Canibalización y sustitución | Media | ◐ | Dentro de efectividad de promociones y del simulador. Falta la tabla de pares afectados por quiebres. |
| 6 | Venta del canal online | Media | ✔ | Pronósticos → por sucursal y canal (el e-commerce es un canal más). |
| 7 | Riesgo de quiebre | Alta | ✔ | Comprar y reponer y Mi tablero (Comercial, Sucursal). |
| 8 | Pedido sugerido a proveedor | Alta | ✔ | Comprar y reponer, OC sugeridas. |
| 9 | Sobrestock y días de cobertura | Alta | ✔ | Plata parada. |
| 10 | Productos que van a vencer | Alta | ✔ | Vencimientos y ofertas. |
| 11 | Demora real de proveedores | Media | ✔ | Proveedores (puntualidad). |
| 12 | Stock fantasma | Media | ✔ | Avisos y recuentos sugeridos. |
| 13 | Elasticidad al precio | Alta | ✔ | Ventas → Sensibilidad al precio. |
| 14 | Venta incremental de una promo | Alta | ✔ | Ventas → Promociones: simulador antes de lanzarla y resultado después. |
| 15 | Precio de liquidación | Media | ✔ | Liquidaciones activas: escalera de rebajas y proyección de vaciado. |
| 16 | Precio de la competencia | Media | ✔ | Ventas → Competencia. Necesita que se carguen relevamientos (a mano o CSV). |
| 17 | Inflación en el volumen | Alta | ✔ | Ventas sin inflación, efecto precio/cantidad. |
| 18 | Abandono de clientes | Alta | ✔ | Ventas → Clientes (dejaron de venir). |
| 19 | Valor de vida del cliente | Media | ✔ | Ventas → Clientes (valor a 12 meses). Necesita que la caja identifique clientes. |
| 20 | Próxima compra | Media | ✔ | Ventas → Clientes (fecha esperada y rango). Ídem. |
| 21 | Respuesta a ofertas y cupones | Media | ✕ | Necesita historial de campañas y cupones (quién recibió qué y si lo usó). |
| 22 | Segmento dinámico | Media | ◐ | Segmentos RFM que se recalculan cada día. Falta segmentación por hábitos de canasta. |
| 23 | Afinidad de canasta | Media | ✔ | Ventas → Canasta. |
| 24 | Rendimiento por metro de góndola | Media | ✔ | Ventas → Góndola. Necesita cargar frentes y metros (CSV). |
| 25 | Productos a discontinuar | Media | ✔ | Ventas → Surtido. |
| 26 | Éxito de un lanzamiento | Media | ✔ | Ventas → Lanzamientos. |
| 27 | Surtido ideal por sucursal | Baja | ✔ | Surtido (qué sumar por sucursal). |
| 28 | Afluencia por hora | Alta | ✔ | Pronósticos → Afluencia y personal. |
| 29 | Personal necesario por turno | Alta | ✔ | Pronósticos → Afluencia y personal (cajas por turno). |
| 30 | Colas en caja | Media | ✕ | Necesita tickets en tiempo real (hoy se importan por lotes). |
| 31 | Merma y robo | Media | ◐ | Merma y anomalías de caja. Falta ranking de pérdida por producto × sucursal. |
| 32 | Fallas de equipos de frío | Baja | ✕ | Necesita sensores de temperatura. |
| 33 | Pedido sugerido por cliente comercial | Alta | ✔ | Panel ERP → Distribución (con rango). |
| 34 | Clientes comerciales en riesgo | Alta | ✔ | Panel ERP → Distribución. |
| 35 | Carga por zona y día | Media | ✔ | Panel ERP → Distribución. Los kilos aparecen si el ERP trae el peso de cada producto. |
| 36 | Entregas fallidas | Media | ✔ | Panel ERP → Distribución (tarde, incompletas o rechazadas). |
| 37 | Devoluciones | Media | ✔ | Panel ERP → Distribución. |
| 38 | Puntos de venta con potencial | Media | ✔ | Panel ERP → Distribución (contra comercios del mismo tipo). |
| 39 | Stock en el canal | Media | ◐ | Panel ERP → Distribución: estimado con lo que compran. Con sell-out real (Panel de marcas) se afina. |
| 40 | Flujo de caja | Alta | ✔ | Finanzas → Flujo de caja a 90 días. |
| 41 | Riesgo de cobro | Alta | ✔ | Finanzas → Riesgo de cobro (puntaje por cliente). |
| 42 | Margen con inflación | Alta | ✔ | Precios (margen erosionado, costo de reposición). |
| 43 | Cierre contra presupuesto | Media | ✔ | Metas (proyección y semáforo). |

Además: **Salud de los modelos** ✔ (WAPE, sesgo y cobertura del rango; corrección automática del sesgo), **vistas por rol** ✔ (Mi tablero:
Dirección, Comercial, Sucursal, Marketing, Finanzas) y **Liquidaciones activas** ✔ (ubicación, escalera, vaciado, reposición de
puntera, control con foto y precio cartel vs caja).

Resumen: 36 hechas, 4 parciales (5, 22, 31, 39) y 3 que necesitan datos que hoy no existen (21 cupones, 30 colas en tiempo real,
32 sensores de frío).

## Plan (siguiendo la hoja de ruta del documento)

- **A. Base de confianza** — hecha: banda del 80 % en todos los pronósticos, registro y comparación con lo real, prueba sobre el pasado,
  probabilidad de quiebre y corrección del sesgo por categoría y sucursal.
- **B. Faltantes de prioridad alta** — hecha: 2, 3, 6, 14, 28, 29, 40, 41.
- **C. Liquidaciones activas** — hecha.
- **D. Vistas por rol** — hecha (Mi tablero).
- **E. Distribución (33–39)** — hecha en el Panel ERP con los datos de Odoo.
- **F. Con datos nuevos** — hechas 16, 19, 20, 24 y 26. Pendientes por falta de datos: 21, 30 y 32.

## Avance

- **A (29/09/2026).** Con la demo completa: WAPE 35 %, el rango del 80 % contiene lo real el 74 % de las veces y el pronóstico
  sobreestimaba un 6,5 %; ahora se corrige solo por categoría y sucursal.
- **B, C, D, E, F (29/09/2026).** Todas las pantallas nuevas cargan en menos de 3 s con la demo completa.
