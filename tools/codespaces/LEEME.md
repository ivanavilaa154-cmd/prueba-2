# Plataforma IA para ERP en Codespaces

La plataforma ya está arrancando. En unos segundos se abre sola en una pestaña nueva del navegador.

**Si no se abrió:** abajo, en la pestaña **PORTS**, pasá el mouse sobre el puerto **8000** y tocá el ícono
del globo ("Open in Browser").

**Para conectar Odoo (una sola vez por empresa, sirve para las dos secciones):** entrá como el dueño de la empresa. Al abrir
el Panel ERP aparece «Conectá el Odoo de …» → **Conectar Odoo** → completá URL, base de datos, usuario y API key → **Guardar**.
(Lo mismo se puede hacer desde Retail → Datos → Conectar caja y tiendas → **Conectar y sincronizar**.) Con eso se completan
solas las dos secciones: el Panel ERP (ventas, clientes, stock, deuda, distribución) y Retail (caja, reposición, precios).
La primera vez tarda unos minutos; después se actualiza sola (Retail cada hora, el Panel ERP cada 3 horas).
Cada empresa ve solo sus datos. La administración entra a una empresa desde Retail → Plataforma → Entrar.

**Ingreso (uno solo para todo):** al abrir la plataforma aparece la pantalla de ingreso. Con la misma cuenta entrás al
**Panel ERP** (tablero, chat y decisiones) y a **Retail** (comercios); arriba de cada uno hay un enlace al otro.
- Administración de la plataforma (ve todas las empresas): `admin@retail-ia.local` · clave inicial `Admin-Retail-2026`
- Dueño de Pulpo Azul (ve todo, solo de su empresa): `dueno@pulpoazul.local` · clave inicial `PulpoAzul-2026`

Cambiá las dos claves la primera vez que entres (en Retail: Configuración → Mi cuenta).

**¿No aparece la página?** La plataforma tiene que estar corriendo: en la terminal de abajo escribí
`bash tools/codespaces/iniciar.sh` y esperá el mensaje «Abriendo la plataforma…»; después, en la pestaña **PORTS**, abrí el
puerto **8000** (ícono del globo). No cierres esa terminal ni aprietes Ctrl+C mientras la usás.
¿No te deja entrar? En otra terminal: `cd backend && python -m app.retail.cuentas --reales` (deja las dos cuentas listas).

**Para cerrarla:** cerrá esta pestaña. El Codespace se apaga solo a los 30 minutos sin uso y no consume
horas mientras está apagado. Para volver, entrá a https://github.com/codespaces y abrilo de nuevo:
la conexión con Odoo queda guardada.

El link de la plataforma es privado: solo lo abre tu cuenta de GitHub.
