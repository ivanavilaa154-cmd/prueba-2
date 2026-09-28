# Plataforma IA para ERP en Codespaces

La plataforma ya está arrancando. En unos segundos se abre sola en una pestaña nueva del navegador.

**Si no se abrió:** abajo, en la pestaña **PORTS**, pasá el mouse sobre el puerto **8000** y tocá el ícono
del globo ("Open in Browser").

**Para conectar Odoo:** en la plataforma, pestaña **1 · Integraciones** → recuadro **Odoo** → completá URL,
base de datos, usuario y API key → **Probar conexión** → **Guardar** → **Sincronizar ahora**.

**Retail (comercios):** agregá **/retail** al final de la dirección. Cuentas de ejemplo (clave `demo-retail-2026`):
`dueno@norte.demo` (dueño), `compras@norte.demo` (comprador), `encargado.norte@norte.demo` (encargado de Salta Norte),
`caja.centro@norte.demo` (cajero), `dueno@esquina.demo` (otra empresa) y `admin@plataforma.demo` (plataforma).

**Tus cuentas reales (administración + dueño de tu empresa):** en la terminal de abajo escribí
`cd backend && python -m app.retail.cuentas` y respondé lo que pregunta. Crea tu cuenta de administración (ve todas las
empresas) y la empresa con su dueño (por ejemplo **Pulpo Azul**, que ve todo pero solo de su empresa). Las claves las escribís
vos y no se muestran. Al final te ofrece desactivar las cuentas de ejemplo `@*.demo`.

**Para cerrarla:** cerrá esta pestaña. El Codespace se apaga solo a los 30 minutos sin uso y no consume
horas mientras está apagado. Para volver, entrá a https://github.com/codespaces y abrilo de nuevo:
la conexión con Odoo queda guardada.

El link de la plataforma es privado: solo lo abre tu cuenta de GitHub.
