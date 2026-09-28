# Plataforma IA para ERP en Codespaces

La plataforma ya está arrancando. En unos segundos se abre sola en una pestaña nueva del navegador.

**Si no se abrió:** abajo, en la pestaña **PORTS**, pasá el mouse sobre el puerto **8000** y tocá el ícono
del globo ("Open in Browser").

**Para conectar Odoo:** en la plataforma, pestaña **1 · Integraciones** → recuadro **Odoo** → completá URL,
base de datos, usuario y API key → **Probar conexión** → **Guardar** → **Sincronizar ahora**.

**Retail (comercios):** agregá **/retail** al final de la dirección. Hay dos cuentas:
- Administración de la plataforma (ve todas las empresas): `admin@retail-ia.local` · clave inicial `Admin-Retail-2026`
- Dueño de Pulpo Azul (ve todo, solo de su empresa): `dueno@pulpoazul.local` · clave inicial `PulpoAzul-2026`

¿No te deja entrar? En la terminal escribí `cd backend && python -m app.retail.cuentas --reales`: deja las dos cuentas listas
y muestra con qué entrar. Entrá siempre por la dirección con **/retail** al final.

Cambiá las dos claves la primera vez que entres (arriba a la derecha → Configuración → Mi cuenta). Las empresas y cuentas de
ejemplo se borran solas al arrancar; para volver a la demo, borrá la línea `RETAIL_CUENTAS=reales` de `backend/.env`.

**Para cerrarla:** cerrá esta pestaña. El Codespace se apaga solo a los 30 minutos sin uso y no consume
horas mientras está apagado. Para volver, entrá a https://github.com/codespaces y abrilo de nuevo:
la conexión con Odoo queda guardada.

El link de la plataforma es privado: solo lo abre tu cuenta de GitHub.
