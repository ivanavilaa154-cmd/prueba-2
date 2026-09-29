# Retail — plan de la Fase 1

Especificación: `docs/retail/prompt_maestro.md`. Marcar con [x] lo terminado. Cada parte termina con sus pruebas y con cómo probarla.

Decisiones (28/09/2026): módulo dentro de la plataforma existente · Python + PostgreSQL (RLS) + Next.js · primer conector de caja: Odoo Punto de Venta · OC y transferencias pueden aprobarse solas bajo el límite, el envío externo lo confirma una persona.

Valores por defecto (configurables): ARS, America/Argentina/Buenos_Aires, semana lunes–domingo, VPD sobre 28 días con stock, sobrestock > 30 días, ABC 80 % / 95 %, alerta de góndola con probabilidad < 5 %, emails a una carpeta local hasta configurar el servicio de envío.

- [x] **Parte 1 — Base multi-empresa:** empresas, sucursales/depósitos, canales, plataformas, usuarios, roles, sucursales por usuario, límites de aprobación, ingreso con email y clave (+ segundo factor opcional), sesiones, auditoría, RLS por empresa y sucursal, pantallas de ingreso, estructura de navegación y Configuración.
- [x] Parte 2 — Modelo de datos completo y demo NOA (3 sucursales + depósito, ~400 productos, 12 proveedores, 13 meses de tickets, lotes, online, IPC).
- [x] Parte 3 — Importación de archivos con asistente de mapeo e idempotencia.
- [x] Parte 4 — Conector Odoo Punto de Venta (detección de sucursales y puntos de venta).
- [x] Parte 5 — Lector de facturas, remitos y listas con IA.
- [x] Parte 6 — Catálogo y normalización (código → alias → similitud → confirmación).
- [x] Parte 7 — Tablas analíticas y cálculo nocturno/incremental.
- [x] Parte 8 — Qué me falta y qué comprar (sección 6), con recuento guiado.
- [x] Parte 9 — Reposición, transferencias y OC con aprobaciones (sección 7).
- [x] Parte 10 — Remarcación (sección 11).
- [x] Parte 11 — Ganadores, Pareto, inflación, ticket y tráfico, control de caja.
- [x] Parte 12 — Alertas, bandeja, emails y resumen diario; Inicio con datos reales.
- [x] Parte 13 — Verificación de los criterios de aceptación y tiempos de carga (`docs/retail/aceptacion.md`). Quedan para la Fase 2 la ganancia por canal completa y el copiloto de Retail.

## Orden de trabajo acordado (28/09/2026)

El dueño pidió ver datos cuanto antes: se construyeron primero las partes 2, 7, 8 y 9 sobre la demo; siguen 11, 10, 12, luego la ingesta (3 a 6) y la verificación (13). Después, fases 2 y 3.

## Demo

`python -m app.retail.demo` (o sola al arrancar si la empresa demo no tiene datos). Se regenera cada día que cambia la fecha para que «hoy» siempre tenga datos; lo que se haga sobre la demo se pierde al regenerarla. Casos conocidos para las pruebas: `demo.CASOS`.

## Fase 2 (28/09/2026)

- [x] Plata parada, vencimientos y ofertas (cartel PDF y seguimiento), merma que ajusta el pedido de perecederos (sección 9).
- [x] Sucursales: comparativos, matriz producto × sucursal, precios distintos, faltantes sospechosos, ajustes auditados (sección 8).
- [x] Rentabilidad del inventario (10.6), medios de pago y fiado (10.8), proveedores (10.11), metas y proyección (10.13).
- [x] Canales: ganancia real por canal, stock unificado con reservas, sobreventa, métricas de e-commerce (sección 12).
- [x] Conectores de Tiendanube y Mercado Libre, solo lectura (5.4).
- [x] Copiloto con herramientas (13.2) y medición de impacto (13.4).
- [x] Avisos nuevos: sobreventa online, meta en riesgo, deuda vencida de fiado.

## Fase 3 (28/09/2026)

- [x] Canasta: pares con soporte, confianza y lift, productos arrastre, combos y ubicación en góndola (10.5).
- [x] Efectividad de promociones: línea base, incremento, canibalización, rebote y neto (10.9).
- [x] Sensibilidad al precio: semanas sin promoción, precio real y estacionalidad; combinada con su categoría; alimenta remarcación y
      el descuento de liquidación (10.10).
- [x] Surtido: marcas, presentaciones, duplicados flojos, qué discontinuar y qué sumar por sucursal (10.12).
- [x] Clientes (RFM) cuando la caja identifica clientes; si no, explica cómo activarlo (10.14).
- [x] Panel para distribuidores y marcas, agregado y anónimo (13.3): solo comercios con consentimiento; un dato se muestra si lo
      forman al menos 5 comercios y ninguno pesa más del 60 % (PANEL_MIN_COMERCIOS / PANEL_MAX_PARTICIPACION, los fija la plataforma);
      supresión complementaria para que nadie despeje un dato reservado restando. Sell-out por zona y semana, participación por marca,
      cobertura, quiebres, oportunidades y efectividad de promociones. Portal de pedidos: el distribuidor ve y confirma las OC que le
      enviaron (por CUIT). Las marcas de cada distribuidor las carga la administración de la plataforma.
- [x] Otras plataformas: WooCommerce, Shopify y VTEX por API, en lectura (pedidos, publicaciones y stock publicado), con las claves cifradas.
- [x] Delivery: PedidosYa y Rappi solo abren su API a integradores aprobados; entran importando el reporte de pedidos de su panel
      (tipo «Pedidos de delivery»: comisión y envío por pedido, cancelados, sin duplicar al reimportar), en el canal delivery.
- [x] Stock publicado: en lugar de sincronizarlo solo (regla 4 de CLAUDE.md), el sistema propone después de cada sincronización y cada
      hora (sobreventa o publicado en 0 con stock) y el dueño elige y aprueba en Canales → Stock; recién ahí se escribe en la plataforma,
      con el disponible de ese momento, y queda auditado quién lo aprobó y qué respondió la plataforma.

## Transversales (29/09/2026)

- [x] Privacidad y cumplimiento (13.5): política de privacidad versionada que cada usuario acepta al entrar; descarga de todos los
      datos de la empresa (ZIP, sin claves); baja de la empresa con 30 días para arrepentirse (después se borra todo, la auditoría
      queda sin empresa); supresión de los datos de un cliente final; copia de seguridad diaria de la base (se guardan 7, probada
      restaurando en una base nueva). Ya estaban: cifrado de credenciales, segundo factor, RLS con pruebas y auditoría.
- [x] Un solo ingreso para el Panel ERP y Retail (cuentas de administración y dueño) y uso del Odoo del Panel ERP en una empresa.
- [x] Planes y facturación (13.6): planes Inicial (1 sucursal, operación diaria), Crecimiento (5, + gestión avanzada) y Cadena (sin
      límite, todo), editables por la plataforma; prueba de 30 días con todo; al vencer, solo lectura sin perder datos; pagos
      registrados por la plataforma. Pendiente de decisión: precios y cobro automático con Mercado Pago (necesita la cuenta).

## Predicciones con IA (29/09/2026) — detalle en `predicciones.md`

- [x] A. Rango del 80 % en todos los pronósticos, registro contra lo real, Salud de los pronósticos y corrección automática del sesgo.
- [x] B. Pronósticos por sucursal × canal, curva anual, afluencia y cajas por turno, simulador de promociones, flujo de caja y riesgo de cobro.
- [x] C. Liquidaciones activas: ubicación, escalera, vaciado, reposición de puntera y control con foto.
- [x] D. Mi tablero: vistas por rol (Dirección, Comercial, Sucursal, Marketing, Finanzas).
- [x] E. Panel ERP → Distribución (33 a 39) con los datos de Odoo.
- [x] F. Valor de vida y próxima compra, lanzamientos, competencia y góndola (estas dos, con datos cargados por CSV).
- [ ] Sin datos todavía: cupones y campañas (21), colas en tiempo real (30), sensores de frío (32).
