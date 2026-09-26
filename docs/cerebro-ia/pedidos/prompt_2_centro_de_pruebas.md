# Prompt 2 — Crear dentro del mismo panel el "Centro de pruebas"

Agregá al tablero de gestión (docs/15 §5) una sección nueva llamada "Centro de pruebas". Es visible solo para los roles operador y tester (agregalos al dominio rol_responsable) y cada acción queda registrada en ops.auditoria. Su objetivo es que una persona sin conocimientos técnicos pueda verificar que la plataforma funciona bien para un cliente antes y después de salir a producción.

## Pantallas

### 1. Estado general del cliente
Un semáforo "Listo para producción" con los criterios de marcha blanca: días en paralelo, días seguidos sin diferencias, métricas cuadradas, controles DQ críticos abiertos, suites de tests en verde y pruebas manuales aprobadas. Para cada criterio, mostrá qué falta.

### 2. Cuadratura
Para cada métrica clave:
- el sello, la definición espejo descubierta y su evidencia día por día;
- el puente de conciliación;
- el historial de días cuadrados;
- la lista de diferencias a nivel registro (faltan, sobran, importe distinto) con su causa probable;
- botones para reejecutar el descubrimiento y la verificación.

### 3. Integridad de datos
Por fuente y stream: frescura, totales de control (raw contra staging contra core), resultado de la reconciliación de IDs, controles DQ abiertos y valores sin mapear.

### 4. Verificación por muestra
El tester elige una métrica y un período, y el sistema toma 20 registros al azar. Para cada uno muestra lado a lado el valor en el origen (payload crudo) y en la plataforma (canónico y espejo). El tester marca cada registro como "coincide" o "no coincide". Un "no coincide" crea una incidencia con el registro adjunto.

### 5. Pruebas automáticas
Resultados de la última corrida de cada suite: unitarios, compilador de mappings, e2e de KPIs, escenarios de actividades (los 39 casos y sus exclusiones), procesos, objetivos y cascada, permisos y casos de cuadratura. Mostrá fecha, duración, fallas con detalle, y un botón para ejecutarlas de nuevo en un entorno de prueba, nunca sobre producción.

### 6. Pruebas guiadas manuales
Un catálogo de casos de prueba escritos en lenguaje simple, con pasos, resultado esperado y rol con el que se ejecuta. Incluí al menos:
- que cada pantalla del tablero cargue en computadora y en celular;
- que un usuario de sucursal no vea otra sucursal;
- que una tarea de cada actividad tenga sentido con datos reales;
- que un objetivo cambie de estado y genere su tarea;
- que el botón "¿Por qué difiere?" explique la diferencia;
- que el agente responda con números y cite período y fuente.

El tester marca cada caso como aprobado o fallido, adjunta una captura como evidencia y deja un comentario. Un fallido crea una incidencia.

### 7. Ver como usuario
Un modo de solo lectura para ver el tablero exactamente como lo ve un usuario o rol elegido, y así probar permisos. Tiene que mostrar un banner visible mientras está activo y quedar auditado.

### 8. Incidencias
Lista con origen (automático, muestra o prueba manual), métrica o pantalla, causa del checklist, estado, responsable, test de regresión vinculado y fecha de resolución. Una incidencia de datos no se puede cerrar sin un test de regresión vinculado o una definición registrada en la ficha de cuadratura.

### 9. Revisión independiente
Un botón que lanza una revisión por un agente separado que no participó del desarrollo. Recibe la especificación (docs) y el estado del cliente, y devuelve una lista de discrepancias entre lo que dice la especificación y lo que hace el sistema, cada una con evidencia. Los resultados entran como incidencias para revisar.

## Modelo de datos

Creá ops.prueba_caso, ops.prueba_ejecucion, ops.verificacion_muestra y ops.incidencia (unificada con ops.incidencia_cuadratura), con estado, evidencia (archivo), usuario y fechas.

## Criterios de aceptación

- Un tester sin acceso al código puede decidir si un cliente está listo para producción usando solo esta sección.
- Toda incidencia queda trazada hasta su causa y su test.
- Un usuario con rol que no sea operador o tester no ve la sección, ni por URL ni por API.

Antes de programar, mostrame los wireframes en texto de cada pantalla y el modelo de datos para que los apruebe.
