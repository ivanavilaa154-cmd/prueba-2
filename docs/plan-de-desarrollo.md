# Plan de desarrollo por fases

Marcar con [x] lo terminado. Trabajar una fase por vez.

## Fase 0 — Base del proyecto (incluida en este esqueleto)

- [x] Estructura del repositorio, CLAUDE.md y documentación
- [x] Los 7 prompts maestros como archivos
- [x] Conector de solo lectura con validación de SQL
- [x] Base de demostración SQLite con clientes, productos, ventas, deuda y proveedores
- [x] Motor de chat con herramientas (consultar_erp, simular_credito, ver_diccionario)
- [x] Simulador de crédito del Centro de Decisiones con pruebas
- [x] API FastAPI con /chat, /decisiones/credito y /salud

## Fase 1 — Chat interno funcionando sobre la base demo

- [ ] Probar el chat con las 12 preguntas de `docs/preguntas-de-prueba.md`
- [x] Filtro por rol dentro de las consultas (vendedor → solo su cartera) aplicado en el conector, no solo en el prompt
- [ ] Registro de auditoría de consultas en una tabla propia
- [ ] Memoria de conversación por usuario (historial de mensajes)
- [ ] Manejo de errores de SQL: devolver el error al modelo para que corrija una vez

## Fase 2 — Módulos de análisis

- [ ] Inventario: cobertura, quiebres, sobrestock, pedido sugerido (funciones en `app/analisis/inventario.py`)
- [ ] Ventas: RFM, clientes en riesgo, venta cruzada, márgenes bajo mínimo
- [ ] Finanzas: antigüedad de deuda, DSO/DPO, flujo de caja de 13 semanas
- [ ] Cada análisis expuesto como herramienta del chat
- [ ] Más simuladores del Centro de Decisiones: precios, compra anticipada, descuento por pronto pago, préstamo

## Fase 3 — Tablero web

- [x] Tablero con indicadores de Ventas, Inventario y Finanzas por rol (`app/analisis/tablero.py`, pestaña Tablero)

- [ ] Frontend Next.js: chat, pestaña Decisiones con controles de supuestos, indicadores por pilar
- [ ] Autenticación de usuarios y asignación de rol
- [ ] Registro de decisiones con seguimiento real vs simulado

## Fase 4 — WhatsApp y resumen diario

- [ ] Integración con WhatsApp Business Cloud API (webhook de entrada y envío)
- [ ] Resumen diario programado con el prompt integrador
- [ ] Alertas de seguimiento de decisiones

## Fase 5 — Conectores de ERP reales

- [ ] Diccionario de datos para Tango
- [ ] Diccionario para SAP Business One
- [ ] Diccionario para Odoo (conexión directa a su base PostgreSQL)
- [x] Integración con Odoo por API, con panel de integraciones (probar, guardar, sincronizar, automático)
- [ ] Agente local para ERPs en servidores del cliente
- [ ] Proceso de implementación: mapeo, validación de datos y 12 preguntas de prueba
