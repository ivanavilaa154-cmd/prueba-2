# Retail — plan de la Fase 1

Especificación: `docs/retail/prompt_maestro.md`. Marcar con [x] lo terminado. Cada parte termina con sus pruebas y con cómo probarla.

Decisiones (28/09/2026): módulo dentro de la plataforma existente · Python + PostgreSQL (RLS) + Next.js · primer conector de caja: Odoo Punto de Venta · OC y transferencias pueden aprobarse solas bajo el límite, el envío externo lo confirma una persona.

Valores por defecto (configurables): ARS, America/Argentina/Buenos_Aires, semana lunes–domingo, VPD sobre 28 días con stock, sobrestock > 30 días, ABC 80 % / 95 %, alerta de góndola con probabilidad < 5 %, emails a una carpeta local hasta configurar el servicio de envío.

- [x] **Parte 1 — Base multi-empresa:** empresas, sucursales/depósitos, canales, plataformas, usuarios, roles, sucursales por usuario, límites de aprobación, ingreso con email y clave (+ segundo factor opcional), sesiones, auditoría, RLS por empresa y sucursal, pantallas de ingreso, estructura de navegación y Configuración.
- [ ] Parte 2 — Modelo de datos completo y demo NOA (3 sucursales + depósito, ~400 productos, 12 proveedores, 13 meses de tickets, lotes, online, IPC).
- [ ] Parte 3 — Importación de archivos con asistente de mapeo e idempotencia.
- [ ] Parte 4 — Conector Odoo Punto de Venta (detección de sucursales y puntos de venta).
- [ ] Parte 5 — Lector de facturas, remitos y listas con IA.
- [ ] Parte 6 — Catálogo y normalización (código → alias → similitud → confirmación).
- [ ] Parte 7 — Tablas analíticas y cálculo nocturno/incremental.
- [ ] Parte 8 — Qué me falta y qué comprar (sección 6).
- [ ] Parte 9 — Reposición, transferencias y OC con aprobaciones (sección 7).
- [ ] Parte 10 — Remarcación (sección 11).
- [ ] Parte 11 — Ganadores, Pareto, inflación, ticket y tráfico, control de caja.
- [ ] Parte 12 — Alertas, bandeja, emails y resumen diario.
- [ ] Parte 13 — Verificación de los criterios de aceptación y tiempos de carga.
