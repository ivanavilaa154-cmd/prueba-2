# Primer mensaje para Claude Code

Abrí la carpeta del proyecto en VS Code, abrí Claude Code y pegá este mensaje:

---

Leé CLAUDE.md, docs/arquitectura.md y docs/plan-de-desarrollo.md para entender el proyecto.

Después:

1. Instalá las dependencias del backend, creá la base de demostración y corré las pruebas. Decime si algo falla.
2. Levantá la API y probá el endpoint /decisiones/credito con los parámetros de ejemplo de docs.
3. Empezá la Fase 1 del plan: implementá el filtro por rol dentro del conector (un vendedor solo puede consultar datos de su cartera), con pruebas.

Trabajá de a un paso, mostrame el plan antes de cambios grandes y no modifiques las reglas de CLAUDE.md sin preguntarme.

---

## Mensajes útiles para después

- "Implementá la herramienta de análisis de inventario de la Fase 2: cobertura por SKU, quiebres inminentes y pedido sugerido, con pruebas sobre la base demo."
- "Agregá un simulador de precios al Centro de Decisiones siguiendo el patrón de credito.py."
- "Armá el diccionario de datos para Tango a partir de este esquema: [pegar tablas]."
- "Probá el chat con las 12 preguntas de docs/preguntas-de-prueba.md y contame cuáles fallan."
