# Evaluación: especificación "Cerebro IA" contra la plataforma

La especificación completa está en `docs/cerebro-ia/` (docs 01 a 15, KPIs, actividades, procesos, objetivos y
el PDF de gestión). Este documento dice qué se integró a la plataforma que ya funciona (FastAPI + SQLite + el
modelo de 35 tablas), cómo se adaptó y qué falta, con lo que haría falta para completarlo.

## 1. Integrado y funcionando

| Parte de la especificación | Dónde está | Cómo se adaptó |
|---|---|---|
| **Actividades ACT-01 a ACT-08** (39 casos, 86 acciones), "ninguna alerta sin acción" | `backend/app/actividades/`, pestaña Actividades | Las 8 reglas corren sobre el modelo de la plataforma. Tareas con evidencia, acciones, plazo, impacto, puntaje (impacto × urgencia), una abierta por clave, vencida → sube al dueño, cierre automático, seguimientos (ACT-01 C3/C4), precisión por actividad y tope de avisos diarios. |
| **Procesos estándar** (docs/15 §1) | `backend/app/gestion/procesos.py`, Gestión → Procesos | Cobranza (6 pasos, con escalamiento 15/30/60 días), compra y venta. Estados de paso completos (completado, fuera de plazo, pendiente, vencido, omitido, fuera de orden, no aplica) más "sin dato" cuando la integración no trae ese paso (nunca se cuenta como omitido). Métricas estándar: iniciados, completados, en curso, trabados, tiempo de ciclo P50/P90, tiempo por paso, % en plazo, conformidad. Pasos manuales registrables con un botón o desde el chat. |
| **Objetivos** (docs/15 §2): 24 plantillas, meta sugerida, validación V1-V9, cascada, evaluación | `backend/app/gestion/objetivos.py`, Gestión → Objetivos / Configurar | Curvas lineal, días hábiles, estacionalidad por día de semana e intradía por hora (con `ventas.hora`, que Odoo trae). Ritmo, proyección, probabilidad (normal con CV 10 %), primer 10 % sin rojo, modo "recuperar" en la cascada diaria/semanal, reparto por sucursal/vendedor con participación de 3 meses, historia en pesos de hoy con la inflación de `config/empresa.yaml`. |
| **Ciclo de tiempo real** (§4) | `backend/app/gestion/servicio.py` | Cada 15 min en horario operativo (30 fuera de horario) se reevalúan objetivos y casos trabados; al sincronizar Odoo corren las 8 actividades. El tablero muestra "actualizado hace X" y deja de mostrar números viejos como actuales (no evaluable). |
| **Tablero de gestión** (§5) | pestañas Gestión y Actividades | Pantallas 1 (mis objetivos), 2 (detalle con curva real vs esperada, brecha, cascada, palancas, plan de recuperación), 3 (procesos), 4 (mis tareas), 5 (configurar objetivos) y 8 (chat). Usable en celular. |
| **Herramientas del agente** (§6) | `backend/app/chat/herramientas.py` | consultar_objetivos, detalle_objetivo, proponer_objetivo (no guarda), estado_proceso, casos_trabados, registrar_evento_proceso, más ver_actividades. |
| **Catálogo de 111 KPIs** | Integraciones → Catálogo de KPIs | Muestra qué KPIs tienen sus datos base con la fuente activa y qué falta para cada uno (control por tabla). |
| **Permisos** | `_visible` / `visible` | El dueño ve todo; cada rol ve las áreas de `config/gestion/empresa.yaml`; un vendedor ve solo objetivos, casos y tareas de su cartera. |

Pruebas: 171 en `backend/tests/` (actividades, procesos y objetivos comparados contra SQL directo, cascada que suma,
V5, escalones, permisos, API y chat).

## 2. Con los datos de hoy no se puede (falta el dato, no el código)

| Qué | Por qué | Qué haría falta |
|---|---|---|
| Proceso de **logística** (PRC-LOG) y objetivos OBJ-07 a OBJ-10 | La plataforma no tiene envíos | Tabla `envios` (pedido, listo para despachar, despacho, promesa, entrega, transportista) y su lectura desde Odoo (`stock.picking` de salida) |
| **CRM** (PRC-CRM) y parte de clientes nuevos | No hay leads ni oportunidades | Tablas `leads` y `oportunidades` (Odoo `crm.lead`) |
| **Devoluciones** como proceso (PRC-DEV) | Se registran ya resueltas | Fechas de solicitud, recepción y reintegro |
| Venta: pasos P2-P5 y P7 (pago, facturado, preparado, despachado, cobrado) y OBJ-22 | Falta el vínculo pedido → factura → cobro | Columna `pedidos.venta_id` y `cxc.venta_id` (Odoo `sale.order.invoice_ids`) |
| Compra: P5-P7 (recepción completa, factura y pago del proveedor) | Falta el vínculo orden → factura del proveedor | `cxp.compra_id` (Odoo `purchase.order.invoice_ids`) |
| **Marketing** (OBJ-20, OBJ-21, 22 KPIs MKT) | No hay publicidad, analítica web ni email | Conectores de esas plataformas |
| Contabilidad (FIN-06, asientos) | No se leen asientos | Tabla de asientos (Odoo `account.move.line`) |
| ACT-05: aporte del proveedor y costo de comunicación | No están en el modelo | Dos columnas en `promociones` |

Cada uno de estos puntos es un cambio acotado: agregar la tabla o columna al modelo (`modelo.py` + diccionario),
leerla en la integración y declarar el paso en `config/gestion/empresa.yaml`. El motor ya los mide solos.

## 3. Aproximaciones que conviene conocer

- Los datos llegan **por día** (salvo la hora de la venta): los plazos en horas se pasan a días hábiles (24 h hábiles = 3 días de 8 h).
- ACT-01 usa el stock de hoy (no hay foto diaria de stock) y no tiene la versión intradía por hora.
- ACT-02 calcula el pedido a nivel red (todas las sucursales juntas), no por depósito.
- La estacionalidad usa el día de la semana (no el día del mes ni fechas especiales).
- La probabilidad de cumplir usa la aproximación normal con CV 10 % (la especificación prevé una tabla empírica por empresa).
- V7 (conflictos) revisa una lista fija de pares de objetivos.
- El tablero se refresca cada 60 s (no por Server-Sent Events).

## 4. Lo que es de otra escala (decisión tuya)

La especificación describe un **SaaS multi-cliente**: PostgreSQL con RLS, dbt, Dagster, Cube, servidor MCP,
motor de conectores por arquetipo con mapeos declarativos (`source.yml` / `mapping.yml`), resolución de identidad
entre fuentes, datos personales hasheados, conversión de moneda por fecha, autenticación por usuario y
notificaciones (resumen diario, WhatsApp/email). Nada de eso se hizo: la plataforma actual es para una empresa, con
una fuente activa por vez.

Hay además una diferencia de principio: la especificación pide **agnosticismo total** (ningún nombre de sistema en
el código; todo en configuración). Hoy la integración con Odoo es código propio (`backend/app/integraciones/odoo.py`),
que es lo que ya está probado contra tu Odoo. Pasar a mapeos declarativos es el primer paso si el objetivo es
vender la plataforma a muchas empresas con sistemas distintos.

**Sugerencia de orden:** (1) validar actividades, procesos y objetivos con tu Odoo real; (2) sumar envíos y los
vínculos pedido→factura y orden→factura de proveedor (destraban logística, venta completa y compra completa);
(3) pantallas que faltan del tablero: configurar procesos (hoy se hace en YAML) y ranking por sucursal/responsable;
(4) recién después, la migración a la arquitectura multi-cliente.
