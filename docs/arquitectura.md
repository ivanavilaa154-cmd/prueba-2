# Arquitectura

## Visión general

```
 Usuario (tablero web / WhatsApp)
            │  pregunta en lenguaje natural
            ▼
 ┌──────────────────────────────┐
 │  API FastAPI (backend/app)   │
 │  - identifica usuario y rol  │
 │  - arma el prompt de sistema │
 └──────────────┬───────────────┘
                ▼
 ┌──────────────────────────────┐      herramientas
 │  Motor de chat (chat/motor)  │ ───────────────────────────┐
 │  bucle con la API de Claude  │                            │
 └──────────────┬───────────────┘                            ▼
                │                         ┌────────────────────────────────┐
                │                         │ consultar_erp  → conector.py   │
                │                         │   (solo SELECT, límite filas,  │
                │                         │    filtros por rol)            │
                │                         │ simular_credito → decisiones/  │
                │                         │   (cálculo determinista)       │
                │                         │ ver_diccionario → config/      │
                │                         └───────────────┬────────────────┘
                ▼                                         ▼
       respuesta al usuario                  Base de datos del ERP del cliente
                                             (usuario de BD con permisos de
                                              solo lectura)
```

## Por qué así

- **El modelo razona, el código calcula.** Claude interpreta la pregunta, decide qué datos necesita y explica. Las consultas las ejecuta el conector y las cuentas financieras las hacen funciones de Python probadas. Así se evitan errores aritméticos y se puede auditar cada número.
- **Herramientas en lugar de respuestas predefinidas.** El chat no tiene un catálogo de respuestas: con `consultar_erp` puede contestar cualquier pregunta que los datos permitan.
- **Diccionario de datos por cliente.** Cada ERP tiene nombres de tablas distintos. El diccionario (`config/diccionario_datos.yaml`) traduce el lenguaje del negocio a tablas y campos, y es lo único que cambia entre clientes.
- **Doble barrera de solo lectura.** El conector bloquea todo lo que no sea SELECT, y además la base se conecta con un usuario sin permisos de escritura.

## Prompt de sistema

Se arma en `app/config.py` concatenando, en orden:

1. `prompts/00_base.md` con las variables del cliente reemplazadas.
2. `prompts/06_chat_interno.md`.
3. `prompts/05_centro_decisiones.md` (método de las tres pruebas).
4. Un resumen del diccionario de datos y los permisos del rol del usuario.

Los prompts de los pilares (`01` a `03`) y el integrador (`04`) se usan en los análisis programados (resumen diario, informes por pilar), no en cada mensaje del chat, para no gastar contexto.

## Seguridad

- Credenciales del ERP y de la API de Claude en `.env`.
- Límite de filas por consulta (`MAX_FILAS`) y tiempo máximo.
- Registro de cada consulta ejecutada (usuario, SQL, filas, fecha) para auditoría.
- Los resultados del ERP se envían al modelo como datos dentro de la respuesta de la herramienta; el prompt indica que nunca son instrucciones.
- Datos personales y sueldos restringidos por rol.

## Despliegue sugerido

- Un contenedor por cliente o multi-inquilino con una conexión por cliente.
- Si el ERP está en un servidor local del cliente: un agente liviano instalado en su red que expone solo el conector (túnel saliente), para no abrir puertos.
