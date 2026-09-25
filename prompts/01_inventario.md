OBJETIVO
Analizá de forma exhaustiva el inventario de {EMPRESA} para que siempre haya stock de lo que se vende, no se inmovilice dinero en lo que no se vende y no se pierda mercadería por vencimiento, rotura o faltantes. Trabajá por SKU, sucursal, depósito, categoría y proveedor.

==================================================
PARTE 1. DATOS QUE NECESITÁS DEL ERP
==================================================
Extraé y validá estas fuentes. Si alguna no existe, informalo y seguí.

1. Maestro de productos: código interno, código de barras (EAN/DUN), descripción, marca, categoría, subcategoría, familia, proveedor principal y alternativos, unidad de medida, unidades por bulto, múltiplo de compra, peso y volumen, si es pesable o fraccionado, si es perecedero, vida útil en días, si es kit o combo (y sus componentes), si es insumo de producción propia (panadería, rotisería, fiambrería), tasa de IVA e impuestos internos, estado (activo, discontinuado, bloqueado), fecha de alta.
2. Stock actual: por producto, sucursal, depósito, ubicación, lote y fecha de vencimiento; stock comprometido (pedidos de clientes no despachados), stock en tránsito (órdenes de compra y transferencias no recibidas), stock disponible.
3. Movimientos de stock del {PERIODO}: ventas, devoluciones de clientes, compras, devoluciones a proveedores, transferencias entre sucursales, ajustes de inventario (positivos y negativos con motivo), bajas por vencimiento, rotura, robo, consumo interno, degustación, producción (consumo de insumos y alta de producto terminado). Cada movimiento con fecha, hora, usuario, comprobante y costo.
4. Ventas diarias por SKU y sucursal (unidades, kilos, importe, costo), con marca de si estaba en promoción.
5. Órdenes de compra: fecha de emisión, fecha prometida, fecha de recepción real, cantidades pedidas y recibidas, precio pactado y facturado, proveedor, estado.
6. Proveedores: condiciones de pago, plazo de entrega prometido, días de visita o pedido, pedido mínimo en unidades o importe, descuentos por volumen, bonificaciones, acuerdos de devolución por vencimiento, bonificación por pronto pago.
7. Costos: costo promedio, último costo, costo de reposición y su historial de cambios.
8. Conteos físicos e inventarios cíclicos: fecha, producto, cantidad contada, cantidad en sistema, diferencia, usuario.
9. Promociones y calendario comercial: productos, fechas, tipo de promoción, precio promocional.
10. Si existen: planograma o espacio en góndola, capacidad de depósito, ubicaciones de picking.

==================================================
PARTE 2. ANÁLISIS (hacé todos los bloques)
==================================================

BLOQUE 1. CALIDAD DEL MAESTRO Y DEL STOCK
- Productos sin categoría, sin proveedor, sin código de barras, sin costo o con costo mayor al precio.
- Códigos duplicados o el mismo producto dado de alta dos veces.
- Stock negativo por producto y sucursal, con su posible causa (venta sin recepción cargada, error de unidad de medida, fraccionados).
- Unidades de medida inconsistentes entre compra y venta (bulto vs unidad, kilo vs unidad).
- Perecederos sin vida útil cargada o sin control de lote.
- Productos activos sin movimiento en 12 meses y productos discontinuados con stock.
- Impacto: cuánto valor de inventario está afectado por estos problemas.

BLOQUE 2. FOTO DEL INVENTARIO
- Valor total a costo y a precio de venta; unidades totales.
- Distribución por sucursal, depósito, categoría, proveedor y marca.
- Participación del inventario en el capital de trabajo (dato para Finanzas).
- Evolución mensual del valor del inventario en el {PERIODO}, separando efecto cantidad y efecto precio (inflación de costos).

BLOQUE 3. CLASIFICACIONES
- ABC por venta: A = 80% de la venta, B = siguiente 15%, C = último 5%.
- ABC por margen bruto en dinero (puede diferir del ABC por venta).
- XYZ por variabilidad de la demanda (coeficiente de variación semanal): X estable, Y variable, Z errática o intermitente.
- Matriz ABC-XYZ con la política recomendada para cada cuadrante (nivel de servicio, frecuencia de revisión, método de pronóstico).
- Clasificación por rotación: rápida, media, lenta, sin movimiento.
- Productos "ancla" o de tráfico: los que traen al cliente aunque tengan margen bajo (leche, pan, aceite, azúcar, yerba, bebidas, artículos de limpieza básicos). Nunca deben faltar.

BLOQUE 4. ROTACIÓN Y COBERTURA
- Rotación anual = costo de ventas / inventario promedio a costo.
- Días de inventario = inventario a costo / costo de venta diario promedio.
- Cobertura en días por SKU y sucursal = stock disponible / venta diaria pronosticada.
- GMROI = margen bruto anual / inventario promedio a costo.
- Sell-through de lo recibido en los últimos 30, 60 y 90 días.
- Comparación por categoría, sucursal y proveedor; destacar los extremos.

BLOQUE 5. QUIEBRES DE STOCK
- Quiebres actuales: SKU en cero o por debajo del stock de seguridad, por sucursal.
- Quiebres inminentes: cobertura menor al plazo de entrega del proveedor más los días hasta el próximo pedido.
- Historial: cantidad de días en quiebre por SKU en el {PERIODO}, frecuencia y duración.
- Venta perdida estimada = días en quiebre x venta diaria esperada x precio; sumar por categoría y proveedor.
- Nivel de servicio o fill rate: porcentaje de la demanda atendida con stock.
- Stock fantasma: productos con stock en sistema pero sin ventas durante varios días cuando normalmente venden todos los días (posible faltante físico, mala ubicación o error de carga). Recomendar conteo.
- Quiebres resolubles por transferencia: el producto falta en una sucursal pero sobra en otra.
- Causa raíz de cada quiebre relevante: pedido tardío, proveedor que no entregó, pronóstico bajo, promoción no planificada, error de stock.

BLOQUE 6. SOBRESTOCK Y STOCK INMOVILIZADO
- Productos con cobertura mayor a 60, 90 y 180 días (umbral ajustable por categoría).
- Productos sin venta en 30, 60, 90 y 180 días, con valor inmovilizado.
- Capital inmovilizado total y costo financiero de mantenerlo (tasa de interés de referencia de {PAIS} o costo de capital informado).
- Riesgo de obsolescencia: productos de temporada pasada, cambios de envase, discontinuados por el proveedor.
- Acción recomendada por producto: devolución o cambio con el proveedor, transferencia a otra sucursal, promoción, combo con producto de alta rotación, oferta a clientes B2B que lo compraron antes, liquidación, donación.

BLOQUE 7. PRONÓSTICO DE DEMANDA
- Pronóstico por SKU, sucursal y semana para las próximas 4 a 12 semanas.
- Método según el tipo de demanda: promedio móvil o suavizado exponencial para demanda estable; Holt-Winters o descomposición estacional para demanda con estacionalidad; Croston o SBA para demanda intermitente; analogía con productos similares para lanzamientos.
- Corregir la demanda censurada: los días en quiebre no son demanda cero.
- Separar venta base de venta promocional y medir el efecto de las promociones.
- Considerar: estacionalidad anual y semanal (día de la semana), feriados, fechas de cobro, eventos comerciales, clima si hay dato, canibalización entre productos sustitutos, crecimiento o caída de la categoría, inflación que cambia el comportamiento de compra.
- Medir la precisión: WMAPE y sesgo por categoría. Informar dónde el pronóstico es poco confiable.

BLOQUE 8. PARÁMETROS DE REPOSICIÓN
Calculá para cada SKU y sucursal:
- Plazo de entrega real del proveedor (promedio y desvío, no el prometido).
- Stock de seguridad = Z x raíz(LT x desvío de demanda^2 + demanda media^2 x desvío de LT^2). Z según nivel de servicio objetivo: 98% para A y productos ancla, 95% para B, 90% para C (ajustable).
- Punto de pedido = demanda durante el plazo de entrega + stock de seguridad.
- Stock máximo = punto de pedido + demanda del período de revisión.
- Lote económico (EOQ) cuando aplique, comparado con el pedido mínimo del proveedor y el múltiplo de bulto.
- Frecuencia de pedido recomendada por proveedor.
- Comparar estos parámetros con los cargados en el ERP (si existen) y marcar diferencias.

BLOQUE 9. PEDIDO SUGERIDO
- Pedido sugerido por proveedor = stock máximo - stock disponible - stock en tránsito + pedidos comprometidos de clientes.
- Redondear a bulto y múltiplo de compra; verificar pedido mínimo del proveedor.
- Si no llega al mínimo: proponer adelantar productos de la misma marca con cobertura baja, en vez de sobrecomprar uno solo.
- Evaluar descuentos por volumen: comparar ahorro contra el costo de mantener el stock extra y el riesgo de vencimiento.
- Si hay aumentos de costo anunciados o esperados: evaluar compra anticipada y cuánto conviene adelantar.
- Importe total del pedido, fecha límite para emitirlo, fecha estimada de llegada y efecto en la caja (dato para Finanzas).
- Priorización cuando la caja no alcanza: primero productos ancla y A, después B, después C.

BLOQUE 10. PERECEDEROS Y VENCIMIENTOS
- Lotes que vencen en 7, 15 y 30 días, con cantidad, valor a costo y a precio.
- Probabilidad de venderlos a tiempo = stock del lote / venta diaria esperada vs días hasta el vencimiento.
- Verificar FEFO: que se venda primero lo que vence primero; detectar lotes nuevos vendiéndose antes que los viejos.
- Acción escalonada: rebaja de precio progresiva (por ejemplo 20% a 7 días, 40% a 3 días), traslado a sucursal con más venta, oferta a clientes B2B, uso en producción propia, devolución al proveedor si hay acuerdo, donación con beneficio fiscal si aplica en {PAIS}.
- Secciones de frescos por separado: frutas y verduras, carnes, fiambrería, lácteos, panadería, congelados, rotisería. Merma por sección y por día de la semana.
- Pedido de perecederos ajustado a vida útil: nunca pedir más de lo que se vende antes del vencimiento, dejando margen de seguridad.

BLOQUE 11. MERMA Y PÉRDIDAS
- Merma conocida: vencimiento, rotura, deterioro, consumo interno, degustación.
- Merma desconocida: diferencias de inventario no explicadas (robo interno o externo, errores de recepción, errores de facturación, errores de pesaje).
- Tasa de merma = merma a costo / venta a costo, por sucursal, categoría y sección. Comparar con referencias del rubro.
- Productos con mayor merma en valor y en porcentaje.
- Patrones sospechosos: ajustes negativos repetidos del mismo usuario, ajustes concentrados a fin de mes, anulaciones de ventas frecuentes, devoluciones sin comprobante, productos de alto valor y fácil ocultamiento (bebidas alcohólicas, perfumería, cuchillas, pilas, chocolates) con diferencias recurrentes.
- Diferencias entre lo recibido y lo facturado por proveedores.
- Pesables: diferencia entre kilos comprados y kilos vendidos (merma de corte, deshidratación, errores de balanza).

BLOQUE 12. EXACTITUD DEL INVENTARIO
- Exactitud = SKU con diferencia dentro de la tolerancia / SKU contados.
- Diferencias por conteo en unidades y en dinero, por sucursal y categoría.
- Plan de conteo cíclico: qué contar cada semana, priorizando productos A, de alto valor, de alto riesgo de robo, con stock negativo o con stock fantasma.

BLOQUE 13. PROVEEDORES
- Plazo de entrega real vs prometido, y su variabilidad.
- Nivel de cumplimiento: pedidos completos y a tiempo; unidades recibidas / pedidas.
- Diferencias de precio entre orden de compra y factura.
- Evolución de costos por proveedor vs inflación de {PAIS} y vs otros proveedores del mismo producto.
- Dependencia: porcentaje de la compra y de la venta concentrado en cada proveedor.
- Condiciones: plazo de pago, descuentos, bonificaciones, acuerdos de devolución. Qué condición convendría renegociar y con qué argumento (volumen, cumplimiento, pago puntual).
- Proveedores alternativos disponibles por producto crítico.
- Puntaje de proveedor combinando cumplimiento, precio, plazo y condiciones.

BLOQUE 14. COSTOS Y VALORIZACIÓN
- Diferencia entre costo promedio, último costo y costo de reposición por producto.
- Productos donde el costo de reposición subió y el precio de venta no se actualizó (alerta cruzada con Ventas).
- Inflación de costos por categoría y proveedor en el {PERIODO}.
- Efecto de la valorización elegida en el margen informado.

BLOQUE 15. SURTIDO
- Candidatos a discontinuar: baja venta, bajo margen, alta merma y con sustituto dentro del surtido.
- Productos duplicados o casi iguales que dividen la venta sin sumar.
- Huecos de surtido: categorías con pocas opciones de precio o marca; productos que los clientes B2B compran en otra parte (cruzar con Ventas).
- Seguimiento de productos nuevos: venta de las primeras 4, 8 y 12 semanas vs lo esperado.
- Marcas propias (si existen): participación, margen y rotación vs marcas líderes.
- Si hay datos de espacio en góndola: venta y margen por metro lineal; productos con demasiado o muy poco espacio.

BLOQUE 16. RED DE SUCURSALES Y DEPÓSITOS
- Desbalances: el mismo producto con sobrestock en una sucursal y quiebre en otra.
- Transferencias sugeridas con cantidades, origen, destino y costo de traslado.
- Si hay centro de distribución: qué conviene centralizar y qué comprar directo en cada sucursal.
- Rendimiento del inventario por sucursal comparado entre sí.

BLOQUE 17. PRODUCCIÓN PROPIA Y KITS
- Consumo de insumos según recetas vs consumo real registrado.
- Rendimiento real de producción (panadería, rotisería, carnicería, fiambrería).
- Kits y combos: stock disponible según el componente más escaso.

BLOQUE 18. DEVOLUCIONES
- Devoluciones de clientes: productos, motivos, frecuencia y costo.
- Devoluciones a proveedores: pendientes de retiro, notas de crédito pendientes de recibir y su importe (dato para Finanzas).

BLOQUE 19. DEPÓSITO
- Si hay ubicaciones: productos de alta rotación en ubicaciones lejanas, ubicaciones saturadas.
- Uso de capacidad del depósito y previsión para eventos de alta demanda.

BLOQUE 20. PREPARACIÓN PARA EVENTOS
- Para cada evento de los próximos 90 días: productos que se venden más, cuánto más, stock necesario, fecha límite para pedir.

==================================================
PARTE 3. INDICADORES CLAVE (con valor actual, referencia y variación)
==================================================
Valor del inventario a costo | Días de inventario | Rotación anual | GMROI | Nivel de servicio | Quiebres actuales y venta perdida estimada | Capital inmovilizado (sin venta más de 90 días) | Mercadería por vencer en 30 días | Tasa de merma | Exactitud de inventario | Cumplimiento de proveedores | Precisión del pronóstico (WMAPE).

==================================================
PARTE 4. FORMATO DE SALIDA
==================================================
1. Resumen de inventario en 5 líneas.
2. Alertas CRÍTICO / IMPORTANTE / OPORTUNIDAD con impacto en dinero.
3. Pedido sugerido por proveedor listo para cargar en el ERP: proveedor, código, descripción, cantidad en bultos, costo, total, fecha límite.
4. Lista de acciones sobre vencimientos, sobrestock y transferencias.
5. Tablero de indicadores.
6. Datos faltantes y preguntas para el usuario.
