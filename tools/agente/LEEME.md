# Agente de sincronización de Retail IA

Para comercios cuyo sistema de caja está instalado en una PC del local, sin API ni nube: el sistema exporta sus datos a una carpeta
(CSV o Excel) y el agente los sube solos a la plataforma, por HTTPS y con un token propio.

## Instalar en la PC del local (Windows)
1. En Retail → Datos → Conectar caja y tiendas → **Agente de sincronización** → **Crear**. Copiá el token (se muestra una sola vez).
2. Copiá a una carpeta de la PC (por ejemplo `C:\RetailIA`) el archivo `agente_sync.exe` y `agente.ini.ejemplo`.
3. Renombrá `agente.ini.ejemplo` como `agente.ini` y completá la dirección de la plataforma, el token y la carpeta de exportaciones.
4. Doble clic en `instalar_windows.bat`: queda como tarea programada que arranca con la PC.
5. Configurá tu sistema de caja para exportar ventas (y, si puede, stock, productos y compras) a esa carpeta, por ejemplo cada hora.
   Los nombres de archivo tienen que empezar con `ventas_`, `stock_`, `productos_`, `compras_` o `precios_` (o configurá otros en agente.ini).

La primera vez que llega un formato de archivo nuevo, la plataforma te pide confirmar las columnas en Datos → Importar; a partir de
ahí, los archivos con las mismas columnas entran solos. El estado del agente (última conexión, archivos en cola, errores) se ve en
Datos → Conectar caja y tiendas.

## Cómo funciona
- Sube solo archivos que no cambiaron en los últimos 30 segundos (para no tomar uno a medio escribir).
- Lo subido se mueve a `enviados\`; lo que la plataforma rechaza (formato que no corresponde) va a `rechazados\` con un `.motivo.txt`.
- Sin internet, los archivos quedan en la cola y se reintentan cada vez más espaciado (1, 2, 4… minutos, hasta 1 hora).
- Reenviar el mismo archivo no duplica ventas: la plataforma reconoce el contenido.
- Registro: `agente.log` junto al programa.

## Armar el .exe (una vez, en cualquier PC con Python 3.11)
```
pip install pyinstaller
pyinstaller --onefile --name agente_sync agente_sync.py
```
El ejecutable queda en `dist\agente_sync.exe`. El agente usa solo la biblioteca estándar de Python.

## Fase 2
Lectura directa de las bases de datos de los sistemas de caja más comunes (sin exportar a carpeta).
