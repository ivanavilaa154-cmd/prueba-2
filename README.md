# Plataforma IA para ERP — Supermercados y distribuidores B2B

Capa de IA que se conecta en solo lectura al ERP del cliente y responde sobre **Inventario, Ventas y Finanzas**: chat interno, Centro de Decisiones y resumen diario.

## Probarla sin instalar nada (GitHub Codespaces)

Abrí https://codespaces.new/ivanavilaa154-cmd/prueba-2 → **Crear espacio de código**. En unos minutos
la plataforma se abre sola en el navegador. Las instrucciones están en `tools/codespaces/LEEME.md`.

## Publicarla en internet (link propio)

Botón de despliegue en Render (plan gratis):
https://render.com/deploy?repo=https://github.com/ivanavilaa154-cmd/prueba-2

1. Entrá con tu cuenta de GitHub y autorizá a Render a leer este repositorio.
2. Completá **PANEL_CLAVE** (la contraseña del panel, larga) y, si ya los tenés, los datos de Odoo
   (`ODOO_URL`, `ODOO_DB`, `ODOO_USUARIO`, `ODOO_API_KEY`). `ANTHROPIC_API_KEY` es opcional (para el chat).
3. Tocá **Apply**. En unos minutos Render te da el link (`https://plataforma-ia-erp-xxxx.onrender.com`).

Cómo se comporta publicada:
- Todo pide contraseña. Sin `PANEL_CLAVE` la plataforma no abre (`EXIGIR_CLAVE=1` en `render.yaml`).
- Al arrancar sincroniza Odoo sola y después cada hora.
- En el plan gratis el servidor se duerme tras 15 minutos sin uso: la primera visita tarda alrededor de
  un minuto y vuelve a sincronizar. Lo que se guarde desde el panel se pierde al reiniciar: los datos de
  Odoo conviene cargarlos en Render → tu servicio → **Environment**.

## Abrirla con doble clic

1. Instalá Python 3.11 o más nuevo desde https://www.python.org/downloads/
   (en Windows, en el instalador marcá **Add python.exe to PATH**).
2. En la carpeta del proyecto, abrí **`iniciar.bat`** (Windows) o corré `bash iniciar.sh` (Mac/Linux).
   La primera vez instala lo necesario (un par de minutos).
3. Se abre el navegador en http://localhost:8000. Para cerrarla, cerrá la ventana negra.

## Abrir en VS Code con Claude Code

1. Descomprimí la carpeta y abrila en VS Code (`Archivo → Abrir carpeta`).
2. Abrí Claude Code (extensión de VS Code o `claude` en la terminal integrada).
3. Pegá el mensaje de `docs/primer-mensaje-claude-code.md`.

Claude Code lee `CLAUDE.md` automáticamente: ahí están el producto, las reglas de seguridad y cómo trabajar.

## Arranque manual

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # completar ANTHROPIC_API_KEY
python -m app.erp.demo          # crea la base de demostración
pytest -q                       # 89 pruebas
uvicorn app.main:app --reload   # preview: http://localhost:8000 · API: /docs
```

## Tablero

La primera pestaña muestra los indicadores clave de los tres pilares, con los datos de la fuente activa
(Odoo, archivos o demo) y los permisos del usuario elegido en "Ver como":

- **Ventas:** venta neta, margen, pedidos, pedido promedio, clientes activos y nuevos, venta en riesgo por
  clientes que dejaron de comprar, venta por mes, por vendedor y por sucursal.
- **Inventario:** valor a costo, días de inventario, rotación, quiebres y venta perdida, productos por
  quebrar y capital inmovilizado.
- **Finanzas:** deuda de clientes, vencida y en riesgo, antigüedad, DSO, días reales de cobro y atraso.

Las cuentas están en `backend/app/analisis/tablero.py` (con pruebas contra SQL directo). Lo que falta en los
datos (caja, cuentas por pagar, lotes, merma) se muestra como "todavía no se puede calcular".

## Integraciones: de dónde toma los datos

En la pestaña **Integraciones** del preview local (`uvicorn app.main:app`, http://localhost:8000) se elige
la plataforma. Cada integración traduce sus datos a las tablas de `config/diccionario_datos.yaml`, así el
chat, los permisos por rol y los análisis funcionan igual con cualquiera.

| Plataforma | Estado |
|---|---|
| Odoo 12 o superior (nube o servidor propio) | Disponible, por API y en solo lectura |
| Archivos CSV o Excel | Disponible |
| Base de datos del ERP (SQL Server, PostgreSQL, MySQL, Oracle) | Disponible con `ERP_URL` en `.env` |
| Tango, SAP Business One, Memory, Zeta, Bejerman | Próximamente |

**Modelo de datos completo.** Todas las integraciones se traducen a las mismas 35 tablas
(`backend/app/erp/modelo.py`, descriptas en `config/diccionario_datos.yaml`), agrupadas en Ventas, Inventario y
Finanzas. Todo campo es opcional salvo los mínimos: lo que un sistema no tiene queda vacío y el indicador que lo
necesita lo avisa. La sección **Cobertura de datos** muestra, tabla por tabla, qué llegó y qué controles fallan.

**Odoo** (`backend/app/integraciones/`):
1. Creá en Odoo un usuario para la integración con permisos de Ventas, Facturación e Inventario y generale
   una API key (Preferencias → Seguridad de la cuenta → Nueva clave API).
2. En el panel completá URL, base, usuario y API key y tocá **Probar conexión**: revisa servidor, acceso,
   permisos y datos, y te dice qué falta.
3. **Guardar** escribe la configuración en `backend/.env` (la API key nunca vuelve al navegador).
4. **Sincronizar ahora** trae clientes, vendedores, proveedores, productos, stock por almacén, pedidos,
   ventas de caja y facturas con su fecha real de cobro a `backend/odoo.db`, y la plataforma pasa a usarla.
   Opcional: sincronización automática (cada 15 min a una vez por día) mientras el servidor esté encendido.

Cada sincronización se compara con el reporte **Análisis de ventas** de Odoo (mismos filtros que
"Órdenes de venta"), por mes y equipo, con y sin impuestos, y el panel muestra si coincide.

La integración solo usa métodos de lectura de la API de Odoo (bloqueado también en el código). El "Vendedor"
de la ficha de cada cliente en Odoo define la cartera que ve cada vendedor en la plataforma.

Para probar sin un Odoo propio: `bash tools/odoo_local/start.sh` del repositorio prueba-1- (necesita Docker)
y después `python tools/odoo_local/seed_distribuidora.py`, que agrega vendedores, plazos y facturas.

## Preview para probar con datos reales

Con el servidor levantado, abrí **http://localhost:8000**. Tiene cuatro pestañas:

1. **Datos**: elegís con qué datos trabajar.
   - *Demo*: la distribuidora ficticia.
   - *Mis archivos*: arrastrás exportaciones reales del ERP en CSV o Excel, un archivo por tabla y
     con el nombre de la tabla (`clientes.xlsx`, `ventas.csv`, `cxc.csv`...). Las columnas son las de
     `config/diccionario_datos.yaml`; hay plantillas para descargar. Acepta `1.234,56`, fechas
     `dd/mm/aaaa`, separador `;` y archivos en Latin-1. El mínimo es `clientes`; lo que falte queda
     vacío y el informe lo avisa. Se guarda en `backend/datos_reales.db` (no se sube al repo).
   - *ERP*: la base de `ERP_URL` en `backend/.env`, con un usuario de solo lectura. Para un ERP real
     hay que adaptar `config/diccionario_datos.yaml` y `config/roles.yaml` a sus tablas.
2. **Consultas y permisos**: ejecutás un SELECT "como" cualquier usuario, incluido un usuario por cada
   vendedor de tus datos, y ves el SQL que se ejecutó con el filtro de su cartera. No necesita clave de API.
3. **Chat**: necesita `ANTHROPIC_API_KEY` en `backend/.env`. Muestra qué consultas hizo para responder.
4. **Centro de Decisiones**: el simulador de crédito con formulario.

Para que el chat use el nombre de tu empresa y tus políticas, editá `config/empresa.yaml`.

### Versión que corre en el navegador (sin servidor)

`python tools/build_preview.py` genera `preview.html`, una sola página que se abre en claude.ai y
funciona sin instalar nada: base demo, importación de CSV/Excel, permisos por rol, Centro de Decisiones
y chat. Los archivos se procesan en el navegador y no se suben a ningún servidor. El chat usa la cuenta
de Claude de quien la abre y llama a las mismas herramientas (`consultar_erp`, `ver_diccionario`,
`simular_credito`), que se ejecutan en la página. El generador toma prompts, roles, diccionario y datos
demo del proyecto; si cambian, se vuelve a generar. El importador, el validador de SQL y el simulador
están portados a JavaScript con los mismos resultados que Python (verificado con los mismos casos).

> ⚠️ El preview **no tiene login** (llega en la Fase 3): cualquiera que lo abra elige el usuario.
> Dejalo escuchando solo en tu máquina (`127.0.0.1`, lo que hace uvicorn por defecto) y no lo publiques.

## Probar

**Centro de Decisiones (no necesita clave de API):**

```bash
curl -X POST localhost:8000/decisiones/credito -H "content-type: application/json" -d '{
  "compra_mensual_cliente": 400000, "margen_bruto": 0.22, "dias_cobro_reales": 42,
  "dias_inventario": 20, "dias_pago_proveedores": 21, "costo_servir": 0.04,
  "incobrabilidad": 0.02, "punto_mas_bajo_caja": 2600000, "clientes_solicitados": 5}'
```

Respuesta: `SÍ CON CONDICIONES`, límite 3 clientes (2 sin descubierto), 1 en el escenario pesimista.

**Chat interno (necesita `ANTHROPIC_API_KEY`):**

```bash
curl -X POST localhost:8000/chat -H "content-type: application/json" \
  -d '{"usuario_id": "u1", "mensaje": "¿Qué clientes tienen deuda vencida y cuánto?"}'
```

Usuarios de demo: `u1` dueño, `u2` vendedora (cartera del vendedor 1), `u3` compras.

## Contenido

| Carpeta | Qué hay |
|---|---|
| `CLAUDE.md` | Contexto y reglas para Claude Code |
| `prompts/` | Los 7 prompts maestros: base, inventario, ventas, finanzas, integrador, centro de decisiones, chat interno |
| `config/` | Datos de la empresa, roles y diccionario de datos |
| `backend/app/erp/` | Conector de solo lectura y base demo |
| `backend/app/chat/` | Motor del chat con herramientas |
| `backend/app/decisiones/` | Simulador de crédito (tres pruebas) |
| `docs/` | Arquitectura, plan por fases, preguntas de prueba, primer mensaje |
