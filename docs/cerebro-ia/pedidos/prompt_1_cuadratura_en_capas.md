# Prompt 1 — Integrar la cuadratura y la prevención de diferencias en las capas

Leé docs/16_cuadratura_con_origen.md completo (secciones 1 a 8) y el CLAUDE.md actualizado. La cuadratura y la prevención de diferencias no son un módulo aparte: tienen que quedar integradas en cada capa. Implementá lo siguiente, capa por capa, sin factores ni constantes para acercar números, sin exclusiones por ID y sin filtros en el tablero ni en la capa semántica.

## Capa 1 — Ingesta

1. Agregá al formato de source.yml la sección `streams_control`, obligatoria para los roles ventas, facturacion, tesoreria, inventario y cuentas_corrientes. Son consultas agregadas al propio sistema de origen que devuelven sus totales oficiales por día. Guardalos en ops.totales_origen, sin pasar por el mapping.
2. Implementá la reconciliación diaria de claves: una consulta liviana de IDs y fecha de modificación de los últimos 90 días, comparada contra raw. Tiene que detectar faltantes, borrados en origen y duplicados.
3. Hacé que el incremental relea siempre una ventana hacia atrás (lookback) y que una vez por semana relea completos el mes en curso y el anterior.
4. Exigí que cada campo de fecha del source.yml declare su zona horaria. Si falta, la validación del archivo tiene que fallar.
5. Agregá tests de idempotencia por arquetipo: releer no debe duplicar nada.

## Capa 2 — Almacén

6. Creá las tablas ops.totales_origen, ops.control_totales, ops.cuadratura_definicion, ops.incidencia_cuadratura y ops.calidad_cuadratura.
7. Usá tipos numeric en todo el pipeline y nunca float. Redondeá solo al mostrar.

## Capa 3 — Mapeo y modelo canónico

8. En staging, guardá junto a cada valor canónico el valor tal como vino del origen, en columnas *_origen.
9. Hacé que el compilador de mappings use los importes que el origen ya calculó (neto, impuesto, total, tipo de cambio del documento) y marque como "calculado" todo lo que tuvo que recalcular.
10. Hacé que el compilador rechace la publicación si pasa algo de esto:
    - una columna monetaria no declara si viene con o sin impuestos;
    - un campo de fecha no declara zona horaria;
    - un value map de estados deja valores sin clasificar;
    - falta el stream de control para una métrica clave;
    - la prueba en seco sobre 3 meses no cuadra con los totales de control al 0,01 %.
11. Implementá los totales de control por carga (raw contra staging contra core, por fuente, stream y día) y los controles DQ-25, DQ-26 y DQ-27.

## Capa 4 — Semántica, IA y tablero

12. Implementá `cerebro cuadratura descubrir <tenant> <metrica>`. Tiene que probar todas las combinaciones del checklist (impuestos, fecha, zona horaria, estados, notas de crédito, envío y líneas no producto, alcance) sobre los últimos 3 meses. Se queda con la que coincide al 0,01 % en al menos el 98 % de los días y la guarda como definición espejo, con su evidencia.
13. Hacé que los números principales del tablero usen la definición espejo. Los números con la definición estándar tienen que llevar la etiqueta de su definición.
14. Implementá el puente de conciliación calculado sobre raw, paso a paso y con la cantidad de registros de cada paso, y la herramienta `conciliar` del agente.
15. Agregá el sello en cada número clave: "✔ Cuadrado con tu sistema (hace X)", "⚠ En revisión" o "— Sin referencia".
16. Agregá la verificación continua: cada hora para ventas y cada día para el resto, sobre los últimos 7 días y el mes en curso.
17. Implementá la marcha blanca: un cliente o fuente nueva corre al menos 14 días en paralelo sin mostrarse, y pasa a producción solo con 7 días seguidos sin diferencias no explicadas.
18. Hacé que cada diferencia encontrada se guarde como caso de prueba permanente en tests/cuadratura/casos/ y en el perfil del tipo de sistema.

## Criterios de aceptación

- Con las fuentes simuladas configuradas con definiciones distintas, el descubrimiento encuentra la correcta de cada una sin intervención humana.
- Un registro borrado a propósito se detecta en la siguiente verificación, con su ID.
- Ninguna métrica muestra "✔" sin haber pasado el descubrimiento y la verificación del día.

Antes de empezar, mostrame el plan de archivos que vas a crear o modificar. Al terminar cada capa, mostrame los tests que la cubren y su resultado.
