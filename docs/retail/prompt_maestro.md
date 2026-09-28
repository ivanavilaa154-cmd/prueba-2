# PROMPT MAESTRO — Plataforma de Inteligencia Retail para Comercios

> Especificación entregada por el dueño del producto el 28/09/2026. Se construye fase por fase (sección 14); el avance está en `docs/retail/plan.md`.
> Decisiones tomadas sobre este documento: se integra en la plataforma existente como módulo Retail; stack Python + PostgreSQL + Next.js; primer conector de caja: Odoo (Punto de Venta); las OC pueden aprobarse solas bajo el límite, pero el envío al proveedor lo confirma siempre una persona.

---

## 1. ROL Y OBJETIVO

Actuá como un equipo senior de producto e ingeniería (arquitecto de software, desarrollador full-stack, científico de datos de retail y diseñador UX). Vas a construir **[NOMBRE DEL SISTEMA]**, una plataforma web SaaS multi-empresa de inteligencia retail para autoservicios, minimercados, supermercados regionales y comercios con una o varias sucursales y canales de venta (tienda física y e-commerce), inicialmente en Argentina.

El sistema **no reemplaza** el sistema de caja/facturación del comercio: se conecta a él, lee los datos, los analiza y le dice al dueño **qué hacer**: qué comprar, qué transferir, qué remarcar, qué liquidar, dónde está parada su plata, qué productos le dejan ganancia y dónde pierde dinero.

Principios del producto:
1. **Cero carga manual innecesaria.** Los datos entran por integración, importación de archivos o lectura de documentos con IA. Nunca pedir planillas.
2. **Acción, no solo reportes.** Cada pantalla termina en una recomendación concreta con un botón para ejecutarla.
3. **Todo en plata.** Cada alerta muestra su impacto en pesos (plata perdida, en riesgo o recuperable).
4. **Explicable.** Cada sugerencia muestra por qué se hizo y con qué datos.
5. **Configurable según el modelo de negocio** del comercio (centralizado, descentralizado o mixto).
6. **Simple para un dueño no técnico.** Lenguaje claro, en español rioplatense, sin jerga.

No hay app móvil ni integración con WhatsApp. La interfaz es **web responsive** (usable desde el celular) + notificaciones por email.

---

## 2. USUARIOS Y ROLES

| Rol | Alcance |
|---|---|
| Superadmin (plataforma) | Gestiona todas las empresas, planes, conectores y el catálogo maestro global. |
| Dueño | Ve y configura todo en su empresa. Aprueba OC por encima de los límites. |
| Comprador | Gestiona proveedores, OC y remarcación. Aprueba OC hasta su límite. |
| Encargado de sucursal | Ve solo sus sucursales asignadas. Aprueba transferencias y recepciones. Hace recuentos. |
| Cajero / operativo | Acceso mínimo: recepción de mercadería, recuentos y tareas asignadas. |
| Distribuidor / marca (externo, fase 3) | Solo ve el panel de datos agregados y anónimos y los pedidos que le envían sus clientes. |

Permisos granulares por rol, por sucursal y con **límites de monto** configurables para aprobaciones.

---

## 3. STACK Y ARQUITECTURA

Stack recomendado (ajustable si la herramienta usa otro por defecto):
- **Frontend:** Next.js (App Router) + TypeScript + Tailwind CSS + shadcn/ui. Gráficos con Recharts o ECharts. Tablas con TanStack Table (orden, filtros, paginación, exportación a Excel/CSV).
- **Backend:** API en Next.js (route handlers / server actions) o servicio Node separado. Servicio en Python opcional para modelos de pronóstico avanzados (fase 3).
- **Base de datos:** PostgreSQL (por ejemplo Supabase) con **Row Level Security** por empresa (`org_id`) y por sucursal.
- **Procesos en segundo plano:** cola de trabajos y tareas programadas (cron) para sincronizaciones, cálculos nocturnos y alertas.
- **Almacenamiento de archivos:** para facturas, remitos, listas de precios e importaciones.
- **IA:** modelo de lenguaje con **uso de herramientas (tool calling)** para el copiloto y modelo con visión para leer documentos.
- **Email:** servicio transaccional para avisos y resumen diario.

Arquitectura en capas:
1. **Capa de ingesta:** conectores, importadores y lector de documentos → tablas "staging".
2. **Capa de normalización:** mapeo de productos al catálogo maestro, sucursales, canales, deduplicación, validaciones.
3. **Capa de datos limpios:** modelo transaccional (sección 4).
4. **Capa analítica:** tablas agregadas diarias y métricas precalculadas (recalculadas cada noche y de forma incremental ante datos nuevos).
5. **Motor de reglas y alertas:** evalúa reglas configuradas y genera avisos, transferencias y OC sugeridas.
6. **Capa de presentación:** dashboard web + copiloto + emails.

Requisitos técnicos:
- Multi-empresa estricto: ninguna consulta puede cruzar datos entre empresas salvo el panel agregado anónimo (sección 12).
- Todas las fechas en zona horaria de la empresa (por defecto America/Argentina/Buenos_Aires).
- Montos con precisión decimal (nunca float). Moneda por empresa (ARS por defecto).
- Auditoría: registrar quién creó, modificó o aprobó cada documento y cada ajuste de stock.
- Idempotencia en las sincronizaciones (reimportar no duplica ventas).

---

## 4. MODELO DE DATOS

Todas las tablas llevan `id`, `org_id`, `created_at`, `updated_at`, y `created_by` cuando aplique.

**Organización y estructura**
- `organizations`: nombre, CUIT, plan, zona horaria, moneda, modelo de abastecimiento por defecto, consentimiento de uso de datos agregados (sí/no, fecha).
- `locations`: sucursales y depósitos. Tipo (`venta`, `deposito`, `ambos`), dirección, horarios, activa.
- `channels`: `fisico`, `ecommerce`, `delivery`, `mayorista`.
- `platforms`: Tiendanube, Mercado Libre, WooCommerce, Shopify, VTEX, PedidosYa, Rappi, caja propia, otra. Con credenciales cifradas por empresa.
- `users`, `roles`, `user_locations`, `approval_limits`.

**Catálogo**
- `master_products` (global): EAN/código de barras, nombre normalizado, marca, fabricante, categoría, subcategoría, presentación, unidad de medida, contenido neto, perecedero (sí/no).
- `products` (por empresa): referencia a `master_products` (puede ser nula para productos propios o a granel), código interno del comercio, nombre en el comercio, categoría, activo, clase ABC (calculada), rol del producto (estrella, imán, joya, peso muerto; calculado).
- `product_aliases`: nombres o códigos alternativos con que aparece el producto en cada proveedor, sistema de caja o plataforma.
- `categories`: árbol de categorías (categoría → subcategoría).

**Proveedores y compras**
- `suppliers`: razón social, CUIT, contacto, email para OC, días de visita, días de entrega (lead time), pedido mínimo (monto y/o bultos), condiciones de pago.
- `product_suppliers`: producto, proveedor, costo vigente, unidad de compra, unidades por bulto, múltiplo de compra, proveedor principal/alternativo, prioridad.
- `supplier_price_lists` y `supplier_price_list_lines`: historial de listas con fecha de vigencia.
- `purchase_orders` y `purchase_order_lines`: estado (`sugerida`, `borrador`, `aprobada`, `enviada`, `recibida_parcial`, `recibida`, `cancelada`), sucursal destino o consolidada con distribución por sucursal.
- `receipts` y `receipt_lines`: recepción de mercadería contra OC o sin OC; cantidad, costo, **lote y fecha de vencimiento**, diferencias.

**Stock**
- `stock_levels`: producto × ubicación: stock actual, stock reservado (pedidos online no despachados), stock en tránsito, última actualización.
- `stock_lots`: producto × ubicación × lote: cantidad, fecha de vencimiento, fecha de ingreso.
- `stock_movements`: todos los movimientos (venta, compra, transferencia salida/entrada, ajuste, merma, vencimiento, devolución) con referencia al documento de origen.
- `transfers` y `transfer_lines`: estado (`sugerida`, `aprobada`, `enviada`, `recibida`, `cancelada`), origen, destino, diferencias en recepción.
- `inventory_counts` y `inventory_count_lines`: recuentos cíclicos; stock sistema vs. contado, diferencia en unidades y en plata, motivo.
- `stockout_periods`: períodos en que cada producto estuvo sin stock en cada ubicación (calculado).

**Ventas**
- `sales_tickets`: ubicación, canal, plataforma, punto de venta, cajero, fecha y hora, cliente (opcional), total, estado, número de pedido externo.
- `sales_lines`: producto, cantidad, precio de lista, precio cobrado, descuento, costo al momento de la venta, promoción aplicada.
- `payments`: medio de pago (efectivo, débito, crédito, QR, transferencia, cuenta corriente/fiado, plataforma), monto, cuotas, comisión estimada, plazo de acreditación.
- `sales_voids_returns`: anulaciones y devoluciones con cajero, motivo y hora.
- `channel_fees`: comisiones, costos de envío y publicidad por pedido o por período y plataforma.

**Precios y promociones**
- `prices`: producto × ubicación × canal, con vigencia.
- `margin_targets`: margen objetivo por categoría, subcategoría o producto (y opcionalmente por canal).
- `rounding_rules`: terminaciones permitidas y umbrales de precio.
- `promotions`: tipo (descuento %, precio fijo, 2x1, combo, segunda unidad), productos, ubicaciones, canales, vigencia, origen (manual, sugerida por liquidación, sugerida por sobrestock).

**Clientes (opcional, fase 3)**
- `customers`: identificador (DNI, tarjeta o código de programa de puntos), fecha de alta, datos mínimos, consentimiento.
- `customer_accounts`: saldo de cuenta corriente/fiado, movimientos, antigüedad de la deuda.

**Configuración, reglas y alertas**
- `replenishment_settings`: modelo de abastecimiento (centralizado, descentralizado, mixto) por empresa, sucursal, categoría o proveedor.
- `replenishment_rules`: por producto/categoría/ubicación/canal: stock mínimo (unidades o días), stock máximo, punto de pedido, stock de seguridad, origenes permitidos para transferencias, stock mínimo a conservar en origen, cantidad mínima de traslado, días y demora de traslado.
- `automation_settings`: nivel por tipo de documento (`solo_aviso`, `borrador`, `automatico_con_limite`) y monto límite.
- `alerts`: tipo, prioridad (`urgente`, `normal`, `preventiva`), ubicación, producto, impacto en pesos, estado (`nueva`, `vista`, `resuelta`, `descartada`, `escalada`), acción sugerida, vencimiento, destinatarios.
- `notification_preferences`: por usuario y tipo de alerta.
- `goals`: metas de venta o ganancia por período, ubicación y canal.

**Referencias externas**
- `cpi_index`: índice de precios al consumidor mensual (INDEC), para deflactar. Carga manual o por importación.
- `calendar_events`: feriados, fechas de cobro (inicio de mes, aguinaldo), fechas comerciales, eventos locales.
- `weather_daily` (opcional): temperatura y lluvia por ubicación.

**Tablas analíticas (precalculadas)**
- `agg_product_location_daily`: producto × ubicación × canal × día: unidades, facturación, costo, ganancia, tickets, stock al cierre, día con stock (sí/no), unidades en promoción.
- `agg_location_hourly`: ubicación × canal × día × hora: tickets, facturación, unidades.
- `product_metrics_current`: por producto × ubicación: venta promedio diaria, pronóstico, días de stock, fecha estimada de quiebre, cantidad sugerida, semáforo, clase ABC, tendencia, días sin venta, capital inmovilizado, GMROI, rotación, riesgo de vencimiento.

---

## 5. CAPA DE INGESTA E INTEGRACIONES

### 5.1 Conector con sistemas de caja/facturación
- Arquitectura de **conectores pluggables**: una interfaz común (`fetchSales`, `fetchStock`, `fetchProducts`, `fetchPurchases`, `pushPrices` opcional) y un adaptador por sistema.
- Priorizar los sistemas de caja y facturación más usados por los comercios objetivo de la región (a relevar con los primeros clientes).
- Frecuencia: ventas cada 15 minutos a 1 hora (o en tiempo real si el sistema lo permite); stock y catálogo, diario.
- Detección automática de **sucursales y puntos de venta** a partir de los datos: proponer el mapeo y pedir confirmación del dueño.

### 5.2 Importación de archivos (respaldo universal)
- Carga de Excel/CSV de ventas, stock, productos, compras y listas de precios.
- **Asistente de mapeo de columnas** que recuerda la configuración por empresa y archivo.
- Importación programada desde una carpeta o email (fase 2).
- Validaciones con reporte de errores fila por fila.

### 5.3 Lectura de documentos con IA
- Subir PDF o foto de **factura, remito o lista de precios** del proveedor.
- Extraer: proveedor, fecha, número, líneas (código, descripción, cantidad, unidad, costo unitario, descuentos, impuestos), lote y **fecha de vencimiento** si figura.
- Emparejar cada línea con un producto (por código, alias o similitud de texto) mostrando nivel de confianza. Las de baja confianza se confirman manualmente y se guardan como alias para la próxima vez.
- Al confirmar: genera la recepción, actualiza stock, lotes, costos y detecta cambios de precio (dispara remarcación).

### 5.4 Plataformas de e-commerce y delivery
- Fase 2: **Tiendanube** y **Mercado Libre**. Fase 3: WooCommerce, Shopify, VTEX, PedidosYa, Rappi.
- Traer: pedidos, líneas, estado, comisiones, costos de envío, cancelaciones, devoluciones, publicaciones y stock publicado.
- Cada venta queda etiquetada con **canal, plataforma y ubicación que despacha**.
- Si las ventas online se registran en la caja, permitir configurar la detección del canal por punto de venta, usuario, medio de pago o un campo del ticket.

### 5.5 Normalización del catálogo
- Todo producto se vincula a `master_products` por EAN cuando exista.
- Algoritmo de emparejamiento: código exacto → alias conocido → similitud de texto (marca + presentación + contenido) → confirmación manual.
- Cola de "productos sin mapear" con sugerencias y acción masiva.
- Productos a granel o de elaboración propia se manejan sin EAN.

---

## 6. MÓDULO: QUÉ ME FALTA Y QUÉ COMPRAR

### Cálculos (por producto × ubicación, y consolidado)
1. **Venta promedio diaria (VPD):** unidades vendidas en los últimos 28 días ÷ **días con stock** en ese período (excluir días en `stockout_periods`). Mínimo de datos configurable; si hay pocos días, usar el promedio de la categoría o la empresa como referencia y marcar "baja confianza".
2. **Pronóstico diario:** VPD ponderada (más peso a las últimas semanas) × factor de día de la semana × factor de inicio/fin de mes × factor de feriado/evento × factor estacional (cuando haya más de un año de historial) × factor de tendencia. Todos los factores se calculan con el historial propio del producto, o de la categoría si el producto tiene poco historial. Sumar demanda de **todos los canales** que usan ese stock.
3. **Días de stock:** (stock disponible − stock reservado) ÷ pronóstico diario.
4. **Fecha estimada de quiebre:** hoy + días de stock, recorriendo el pronóstico día por día.
5. **Horizonte de cobertura:** días hasta la próxima visita del proveedor + demora de entrega (o días hasta la próxima transferencia posible).
6. **Stock de seguridad:** según clase ABC y variabilidad de la demanda (A más alto, C más bajo), editable.
7. **Cantidad sugerida:** pronóstico acumulado del horizonte + stock de seguridad − stock disponible − stock en tránsito − pedidos ya aprobados. Si es ≤ 0, no comprar. Redondear hacia arriba al múltiplo de bulto del proveedor. Respetar stock máximo.
8. **Semáforo:**
   - Rojo: se agota antes de que llegue la próxima reposición posible.
   - Amarillo: alcanza, pero debe incluirse en el próximo pedido.
   - Verde: cubierto.
   - Gris: sobrestock (cobertura mayor al umbral configurable, por defecto 30 días).

### Detección de faltante en góndola y stock fantasma
- Para productos con venta frecuente: si pasaron X horas de apertura sin ventas y la probabilidad de que eso ocurra con su ritmo normal de venta es muy baja (por ejemplo, menor al 5% según una distribución de Poisson), generar alerta de **"posible faltante en góndola"**.
- Si el sistema indica stock pero la venta cayó a cero por varios días: alerta de **"posible stock fantasma"** y agregar el producto a la lista de recuento.

### Recuento guiado
- Lista diaria corta (10–15 productos por ubicación, configurable) priorizada por: sospecha de stock fantasma, clase A, alto valor, diferencias previas.
- Carga del recuento desde el celular (web responsive); calcula diferencia en unidades y en plata y ajusta con motivo.

### Pantalla
- Tarjetas superiores: productos en rojo, plata que falta comprar, ventas en riesgo por faltantes.
- Tabla: producto, categoría, stock, venta/día, días de stock, se agota (fecha y día), cantidad sugerida, proveedor, semáforo, clase ABC.
- Filtros: ubicación, categoría, proveedor, canal, semáforo, clase ABC.
- Vista resumen por categoría: productos en rojo, monto a comprar, cobertura promedio.
- Acciones: generar OC por proveedor, generar transferencia, marcar para recuento.
- Detalle de producto: gráfico de ventas y stock en el tiempo, pronóstico, explicación del cálculo ("Te sugiero 48 porque vendés 6 por día, el proveedor vuelve en 7 días y tarda 2 en entregar...").

---

## 7. MÓDULO: REGLAS DE REPOSICIÓN, TRANSFERENCIAS Y ÓRDENES DE COMPRA

### Configuración (manual, por el dueño)
- **Modelo de abastecimiento** por empresa, y sobrescribible por ubicación, categoría o proveedor:
  - Centralizado: todo entra al depósito central; las sucursales solo reciben transferencias.
  - Descentralizado: cada sucursal genera sus OC.
  - Mixto: primero transferencia desde ubicaciones con excedente; si no alcanza, OC.
- Parámetros de `replenishment_rules` (sección 4).
- Nivel de automatización y límites de monto por tipo de documento y rol.

### Lógica de decisión (ejecutar tras cada cálculo de métricas)
1. Para cada producto × ubicación que alcanza el punto de pedido:
2. Si el modelo permite transferencias: buscar ubicaciones origen permitidas con **excedente** (stock por encima de su máximo o cobertura superior al umbral), respetando el stock mínimo a conservar en origen y la cantidad mínima de traslado. Priorizar el origen con más excedente, más cercano o con lotes de vencimiento más próximo (rescate de vencimientos).
3. Excedente suficiente → transferencia sugerida.
4. Excedente parcial → transferencia por lo disponible + OC por la diferencia.
5. Sin excedente o modelo sin transferencias → OC sugerida.
6. Agrupar necesidades por proveedor (y por ubicación o consolidado según el modelo). Si la OC no alcanza el pedido mínimo, sugerir adelantar productos en amarillo del mismo proveedor hasta completarlo, mostrando el impacto.
7. Validar contra el presupuesto de compra configurado.
8. Según el nivel de automatización: generar solo aviso, borrador o documento aprobado automáticamente (si está bajo el límite).

### Rescate de vencimientos
- Si un lote no se venderá a tiempo en una ubicación pero sí en otra (según su ritmo de venta), sugerir transferencia preventiva.

### Flujos y estados
- Transferencia: sugerida → aprobada → enviada (descuenta de origen, suma "en tránsito") → recibida (suma en destino, registra diferencias).
- OC: sugerida → borrador → aprobada → enviada al proveedor (PDF por email o portal del distribuidor) → recibida parcial/total.
- Recepción contra OC: compara cantidades y precios; marca faltantes, sobrantes y diferencias de costo; actualiza el nivel de servicio del proveedor.
- Escalamiento: si una OC sugerida no se aprueba antes del día de visita del proveedor, escalar al dueño.

### Control posterior
- % de sugerencias aprobadas sin cambios, modificadas o ignoradas.
- Aprendizaje: si el usuario corrige sistemáticamente una cantidad, ajustar el stock de seguridad o los factores de ese producto (con registro del cambio).
- Resultado: faltantes evitados y plata ahorrada por transferir en vez de comprar.

---

## 8. MÓDULO: MULTISUCURSAL

- Detección y configuración de ubicaciones (sección 5.1).
- **Matriz producto × ubicación** con días de stock y semáforo por celda, stock del depósito y en tránsito.
- Stock por lote y vencimiento en cada ubicación.
- **Comparativos entre sucursales:** ventas, ganancia, margen, ticket promedio, plata parada, merma, faltantes, diferencias de inventario.
- **Rendimiento del mismo producto en distintas sucursales** (ventas por día y ranking) para ajustar el surtido de cada local.
- **Precios distintos** del mismo producto entre sucursales (alerta configurable).
- **Diferencias de inventario** por sucursal y **alerta de faltantes sospechosos** (diferencias o mermas significativamente superiores al promedio de las demás sucursales).
- Ajustes de stock auditados (quién, cuándo, cuánto, motivo).
- Compra consolidada (una OC por proveedor con distribución por sucursal) o por sucursal, según configuración.
- Permisos: el encargado ve solo sus sucursales.

---

## 9. MÓDULO: DÓNDE ESTÁ PARADA LA PLATA

### Plata inmovilizada
- Capital en stock = stock × costo, por producto, categoría, proveedor, ubicación.
- Cobertura en días del capital total.
- Distribución: stock sano (≤ 30 días), sobrestock (30–90 días), stock muerto (sin ventas en ≥ 90 días). Umbrales configurables.

### Qué ya no se vende (con comparativos)
- Productos sin ventas en 15, 30, 60 y 90 días, con capital atrapado por tramo.
- Variación de ventas: últimos 30 días vs. 30 anteriores; mes actual vs. mismo mes del año anterior; últimas 4 semanas vs. promedio de 3 meses.
- Etiqueta de tendencia: creciendo, estable, cayendo, muerto.
- Posible causa: aumento de precio reciente, sustituto de la misma subcategoría que creció, fin de temporada, faltante prolongado.
- Recomendación: dejar de comprar, liquidar, devolver/cambiar al proveedor, sacar del surtido.

### Próximos a vencer
- Lista por lote: producto, ubicación, cantidad, fecha de vencimiento, días restantes.
- **Unidades que no llegarán a venderse** = cantidad del lote − (pronóstico acumulado hasta el vencimiento), considerando lotes que vencen antes (se venden primero).
- Tramos: < 7 días, 7–15, 15–30.
- Plata en riesgo = unidades que no llegan × costo.

### Qué ofertar
- Por vencer: descuento mínimo necesario para vender lo que sobra a tiempo (usar sensibilidad al precio si existe; si no, escala por defecto configurable).
- Sobrestock: combo con un producto de alta rotación de la misma canasta (usar análisis de canasta si existe) o segunda unidad con descuento.
- Stock muerto: liquidación al costo o pedido de cambio al proveedor.
- Mostrar comparación: resultado de no hacer nada vs. resultado con la oferta.
- Generar la promoción, cartelería imprimible (PDF en tamaños de góndola) y seguimiento del resultado (plata recuperada).

### Merma
- Registro de vencidos y roturas con costo.
- Ranking por producto, categoría, proveedor y ubicación. Evolución mensual.
- La merma histórica ajusta el pedido sugerido de productos perecederos.

### Tarjetas resumen
Plata parada, plata en riesgo de vencimiento este mes, productos que dejaron de venderse, ofertas sugeridas hoy con plata recuperable.

---

## 10. MÓDULO: VENTAS, RENDIMIENTO Y ANÁLISIS RETAIL

### 10.1 Productos ganadores
- Períodos: hoy, ayer, semana, mes, rango personalizado; siempre comparado con el período anterior.
- Criterios: unidades, facturación, ganancia, margen %, ganancia por peso invertido en stock, frecuencia en tickets.
- Top 10 y peores 10 por criterio; indicadores de subida, bajada y nuevo en el ranking.
- Rol del producto (matriz volumen × margen): estrella, imán, joya, peso muerto.
- Filtros por ubicación, canal, categoría, proveedor, día de la semana y franja horaria.

### 10.2 Análisis de Pareto (ABC)
- Ordenar productos por ganancia (por defecto) y acumular porcentaje: A hasta 80%, B hasta 95%, C el resto (umbrales configurables).
- También por unidades, facturación, categoría y proveedor. Mostrar Pareto cruzado (ej.: A en volumen y C en ganancia = imán).
- Gráfico de Pareto (barras + curva acumulada) y tabla.
- Historial mensual de la clase de cada producto.
- La clase ABC alimenta stock de seguridad, prioridad de alertas, recuentos y candidatos a liquidar.

### 10.3 Ventas reales ajustadas por inflación
- Ventas nominales, ventas en unidades y ventas deflactadas con `cpi_index` (llevadas a pesos del último mes).
- Comparativos interanuales y mensuales en términos reales.
- Descomposición de la variación de facturación en efecto precio y efecto cantidad.

### 10.4 Ticket y tráfico
- Cantidad de tickets, ticket promedio en pesos y en unidades, por ubicación, canal, día y hora.
- Descomposición: variación de ventas explicada por más clientes vs. mayor gasto por cliente.
- Mapa de calor día × hora (tickets y facturación) para planificar turnos.

### 10.5 Análisis de canasta
- Pares y grupos de productos que se compran juntos: soporte, confianza y lift. Mostrar en lenguaje simple ("El 60% de los que compran X también llevan Y").
- Identificar productos arrastre (presentes en muchos tickets y asociados a tickets altos).
- Sugerencias de combos, ubicación en góndola y ofertas cruzadas.
- Requiere volumen mínimo de tickets; mostrar aviso si no hay suficiente historial.

### 10.6 Rentabilidad del inventario
- GMROI = ganancia bruta del período ÷ inversión promedio en stock a costo.
- Rotación anualizada = costo de lo vendido ÷ inventario promedio a costo. Días de inventario.
- Por producto, categoría, proveedor y ubicación.

### 10.7 Control de caja y anomalías
- Anulaciones, devoluciones y descuentos manuales por cajero, turno, ubicación y hora.
- Ventas a precio distinto del precio de lista vigente.
- Detección estadística de valores atípicos respecto del promedio de otros cajeros o turnos; alertas con detalle de tickets.
- Diferencias de inventario recurrentes asociadas a una ubicación o turno.

### 10.8 Medios de pago
- Participación de cada medio en ventas por ubicación y canal.
- Costo real por medio (comisiones configurables y plazo de acreditación) y su impacto en el margen.
- Cuenta corriente / fiado: saldos por cliente, antigüedad de la deuda, alertas de deuda vencida.

### 10.9 Efectividad de promociones
- Línea base: ventas esperadas sin promoción (pronóstico).
- Incremento real = ventas en promoción − línea base, en unidades y ganancia.
- Canibalización: caída de productos sustitutos de la misma subcategoría durante la promoción.
- Efecto rebote: caída de ventas posterior a la promoción.
- Resultado neto en ganancia y recomendación de repetir o no.

### 10.10 Sensibilidad al precio
- Estimar para cada producto (o subcategoría si hay pocos datos) cómo cambian las unidades ante cambios de precio, controlando por estacionalidad y promociones.
- Clasificar: poco sensible (margen para subir precio), sensible (no tocar), sin datos suficientes.
- Alimenta remarcación y descuentos de liquidación.

### 10.11 Proveedores
- Nivel de servicio: % de unidades y líneas entregadas vs. pedidas, puntualidad.
- Evolución de costos del proveedor vs. inflación.
- Rentabilidad por proveedor: ganancia generada, merma, plata parada, GMROI.

### 10.12 Surtido óptimo
- Por subcategoría: cantidad de marcas y presentaciones, participación de cada una, duplicados de bajo rendimiento.
- Sugerencia de productos a discontinuar (clase C, baja ganancia, con sustituto en el surtido) y productos con buen desempeño en otras sucursales que no están en esta.

### 10.13 Metas y proyección
- Metas por período, ubicación y canal (ventas, ganancia, margen).
- Proyección de cierre al ritmo actual, ajustada por el patrón de días restantes (fines de semana, inicio de mes).
- Semáforo de cumplimiento.

### 10.14 Clientes (solo si hay identificación en caja)
- Frecuencia, recencia y gasto (segmentación RFM).
- Clientes que dejaron de venir; clientes de mayor valor.
- Si no hay datos de clientes, ocultar el módulo y mostrar cómo activarlo.

---

## 11. MÓDULO: PRECIOS Y REMARCACIÓN

- Ingesta de listas de proveedores (sección 5.3) y detección de aumentos por producto.
- Margen objetivo por categoría/subcategoría/producto/canal.
- Precio sugerido = costo ÷ (1 − margen objetivo) (o markup, según configuración), más costos del canal en e-commerce, aplicando reglas de redondeo y umbrales.
- Prioridad: productos más vendidos con mayor aumento primero (mayor pérdida de margen diaria).
- Alerta de margen erosionado: productos vendiéndose por debajo del margen objetivo.
- Considerar sensibilidad al precio cuando exista (sugerir no trasladar todo el aumento en productos muy sensibles o imanes).
- Salida: actualización de precios en el sistema de caja si el conector lo permite; si no, exportación; **etiquetas de góndola imprimibles** solo de los productos que cambiaron.
- Historial de precios por producto y canal.

---

## 12. MÓDULO: CANALES DE VENTA Y E-COMMERCE

- Canal y plataforma como dimensión en **todos** los reportes y cálculos; filtro global en el dashboard (consolidado, por canal, por plataforma).
- **Stock unificado:** la demanda de todos los canales consume el mismo stock; stock reservado por pedidos online no despachados.
- **Alerta de sobreventa:** stock publicado mayor al disponible. Fase 3: sincronización automática del stock publicado.
- **Ganancia real por canal:** precio − costo − comisión de plataforma − envío a cargo del vendedor − costo del medio de pago − publicidad prorrateada.
- Ganadores, Pareto, ticket y precio por canal. Participación de cada canal y su evolución.
- Precio online sugerido que cubra costos del canal.
- Stock de seguridad exclusivo para el canal online (opcional).
- Métricas de e-commerce: cancelaciones, devoluciones y reclamos por producto; tiempo de despacho por ubicación; productos que se venden bien en el local y no están publicados.

---

## 13. MÓDULOS TRANSVERSALES

### 13.1 Motor de alertas y avisos
- Tipos: quiebre, posible faltante en góndola, stock fantasma, transferencia sugerida, OC sugerida, OC por escalar, sobrestock, stock muerto, vencimiento, margen erosionado, aumento de proveedor, anomalía de caja, diferencia de inventario, sobreventa online, meta en riesgo, caída de producto A.
- Cada alerta: prioridad, impacto en pesos, explicación, acción sugerida con botón, estado y vencimiento.
- Deduplicación (no repetir la misma alerta mientras siga abierta) y agrupación.
- Bandeja de avisos en el dashboard, emails según preferencias, y **resumen diario por email** a la hora configurada.

### 13.2 Copiloto con IA (dentro del dashboard)
- Chat en español que responde preguntas sobre los datos de la empresa: "¿cuánto vendí hoy contra el sábado pasado?", "¿qué me conviene comprar esta semana?", "¿por qué me sugerís pedir 12 de esto?".
- **Implementación obligatoria con herramientas:** el modelo no escribe SQL libre; llama a funciones predefinidas y seguras (ventas por período, ranking, métricas de producto, alertas abiertas, explicación de una sugerencia, etc.) que respetan permisos y sucursales del usuario.
- Responde solo con datos obtenidos por las herramientas; si no hay datos, lo dice. Muestra las cifras y el período usado.
- Puede proponer acciones (crear borrador de OC, transferencia u oferta) que el usuario confirma.
- **Resumen diario** generado automáticamente: ventas vs. comparativo, ganancia, 3 alertas principales, 3 acciones recomendadas.

### 13.3 Panel para distribuidores y marcas (fase 3)
- Solo con consentimiento explícito de cada comercio.
- Datos **agregados y anónimos**: sell-out por producto, categoría, zona y semana; cobertura (% de comercios con el producto), quiebres, participación de mercado vs. competencia, efectividad de promociones, oportunidades (comercios que venden la categoría pero no el producto).
- **Umbral mínimo de agregación:** no mostrar datos de una zona o segmento con menos de N comercios (configurable, por defecto 5) ni donde un solo comercio represente más de un % alto del total.
- Portal de recepción de pedidos para distribuidores.

### 13.4 Medición de impacto
- Línea base de cada comercio al conectarse (primeras semanas): faltantes, merma, plata parada, margen.
- Reporte mensual de mejora: plata recuperada por faltantes evitados, merma reducida, margen recuperado por remarcación, plata liberada de sobrestock.

### 13.5 Privacidad, seguridad y cumplimiento
- Cumplimiento de la Ley 25.326 de Protección de Datos Personales: política de privacidad, consentimiento, derecho de acceso y supresión.
- Cifrado de credenciales de integraciones. HTTPS. Autenticación con email + contraseña y opción de segundo factor.
- Aislamiento por empresa con RLS y pruebas automatizadas que verifiquen que un usuario no accede a datos de otra empresa ni de sucursales no asignadas.
- Registro de auditoría consultable.
- Copias de seguridad diarias.

### 13.6 Planes y facturación
- Planes por cantidad de sucursales y módulos. Período de prueba.
- Gestión de suscripción y medios de pago locales.

---

## 14. FASES DE CONSTRUCCIÓN

**Fase 1 — MVP (construir primero, completo y funcionando)**
1. Autenticación, empresas, ubicaciones, canales (dimensión presente desde el inicio aunque solo haya tienda física), usuarios y roles.
2. Importación de archivos con asistente de mapeo + un primer conector de caja + lector de facturas/remitos/listas con IA.
3. Catálogo y normalización de productos.
4. Tablas analíticas y cálculo nocturno de métricas.
5. Qué me falta y qué comprar (sección 6).
6. Reglas de reposición, transferencias y OC con aprobaciones (sección 7).
7. Remarcación inteligente (sección 11).
8. Productos ganadores y Pareto (10.1, 10.2).
9. Ventas ajustadas por inflación (10.3), ticket y tráfico (10.4), control de caja (10.7).
10. Motor de alertas, bandeja de avisos, emails y resumen diario (13.1, parte de 13.2).
11. Datos de demostración (sección 16).

**Fase 2**
Multisucursal completo (8), plata parada, vencimientos y ofertas (9), medios de pago (10.8), GMROI y rotación (10.6), proveedores (10.11), metas (10.13), copiloto completo (13.2), Tiendanube y Mercado Libre con stock unificado y ganancia por canal (12), medición de impacto (13.4).

**Fase 3**
Canasta (10.5), promociones (10.9), sensibilidad al precio (10.10), surtido (10.12), clientes (10.14), panel de distribuidores y marcas (13.3), otras plataformas y delivery, sincronización automática de stock publicado.

---

## 15. DISEÑO DE INTERFAZ

- Navegación lateral: Inicio · Comprar y reponer · Transferencias y OC · Plata parada · Vencimientos y ofertas · Ventas y ganadores · Precios · Sucursales · Canales · Caja y control · Proveedores · Avisos · Copiloto · Configuración.
- **Filtro global** persistente arriba: período, ubicación(es), canal/plataforma.
- **Inicio:** resumen diario, tarjetas clave (ventas vs. comparativo, ganancia, productos en rojo, plata parada, plata en riesgo, anomalías), acciones del día con botones.
- Cada número clave es clicable y lleva al detalle.
- Tablas con orden, filtros, búsqueda, exportación a Excel y selección masiva de acciones.
- Colores de semáforo consistentes en todo el sistema, siempre acompañados de texto o ícono (no depender solo del color).
- Formatos argentinos: $ con punto de miles y coma decimal, fechas DD/MM/AAAA, semanas de lunes a domingo.
- Responsive: todas las pantallas usables en celular, con prioridad en Inicio, Avisos, recuentos y recepción de mercadería.
- Modo claro y oscuro.
- Estados vacíos que explican qué dato falta y cómo cargarlo.
- Onboarding guiado: conectar datos → confirmar sucursales → mapear productos → configurar proveedores → configurar modelo de abastecimiento y márgenes → ver primeras recomendaciones.

---

## 16. DATOS DE DEMOSTRACIÓN

Generar una empresa de ejemplo realista para probar y hacer demos:
- 3 sucursales + 1 depósito, en el NOA.
- ~400 productos en categorías típicas (bebidas, almacén, lácteos, fiambrería, limpieza, perfumería, golosinas, cigarrillos, congelados), con EAN, costos y precios.
- 12 proveedores con días de visita, demoras y pedidos mínimos.
- 13 meses de ventas por ticket con: estacionalidad (bebidas en verano), patrón semanal, picos de inicio de mes, feriados, inflación mensual en precios y costos, promociones, faltantes y algunas anomalías de caja.
- Lotes con vencimientos, algunos en riesgo.
- Ventas online de Tiendanube y Mercado Libre en una sucursal, con comisiones.
- Índice de inflación mensual cargado.

---

## 17. CRITERIOS DE ACEPTACIÓN (verificar antes de dar por terminada cada fase)

- La venta promedio diaria excluye los días sin stock (probar con un producto con faltante conocido).
- La cantidad sugerida respeta horizonte, stock de seguridad, tránsito, pedidos abiertos y múltiplo de bulto (probar casos con cálculo manual).
- En modelo mixto, el sistema propone transferencia antes que OC y no deja al origen por debajo de su mínimo.
- En modelo centralizado, ninguna sucursal genera OC.
- Las OC por proveedor respetan el pedido mínimo o proponen completarlo.
- Los flujos de aprobación respetan límites de monto por rol.
- La clase ABC suma exactamente 100% y coincide con un cálculo manual en la muestra.
- Las ventas deflactadas coinciden con el cálculo manual usando el índice cargado.
- La ganancia por canal descuenta comisiones y envíos.
- Un encargado no ve sucursales no asignadas; un usuario no ve datos de otra empresa (pruebas automatizadas).
- Reimportar el mismo archivo no duplica ventas.
- Cada alerta muestra impacto en pesos, explicación y acción.
- El copiloto no responde cifras que no provengan de sus herramientas.
- Todas las pantallas cargan en menos de 3 segundos con los datos de demostración.

---

## 18. INSTRUCCIONES DE TRABAJO PARA QUIEN CONSTRUYE

1. Antes de programar, presentá: el esquema de base de datos, la lista de pantallas de la fase y las decisiones técnicas. Esperá confirmación.
2. Construí la fase en partes pequeñas y verificables; al terminar cada parte, mostrá cómo probarla.
3. Escribí pruebas automatizadas para todos los cálculos (secciones 6, 7, 9, 10) con casos de borde: producto nuevo sin historial, stock negativo, ventas con devoluciones, producto sin costo, proveedor sin días configurados.
4. Si falta información para decidir, elegí el valor por defecto más razonable, dejalo **configurable** y documentalo.
5. Documentá cada fórmula en el código y en una sección de ayuda visible para el usuario ("¿Cómo se calcula esto?").
6. No avances de fase hasta cumplir los criterios de aceptación de la fase actual.
