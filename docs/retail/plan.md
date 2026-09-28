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
