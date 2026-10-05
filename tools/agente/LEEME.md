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


## Lectura directa de la base del sistema (sin exportar a mano)

Además de mirar la carpeta, el agente puede leer la base del sistema de caja **en solo lectura** y traer solo lo nuevo:

- **SQLite** y **DBF** (dBase, FoxPro, Clipper): no hace falta instalar nada.
- **SQL Server** (por ejemplo Tango), **Access**, **Firebird** y **MySQL**: por ODBC, con el controlador de esa base instalado en Windows
  (pyodbc va incluido en el .exe: `pyinstaller --onefile --hidden-import pyodbc agente_sync.py`).

Se configura agregando a `agente.ini` una sección `[base]` y una `[consulta:nombre]` por cada dato: ver la carpeta `plantillas`.
Cada consulta deja un CSV en la carpeta y de ahí sigue el camino de siempre (cola, reintentos e importador). El estado de cada consulta
(filas nuevas, último error) se ve en Datos → Conexiones.

Para probarlo sin un sistema real: `python ejemplo/crear_base_ejemplo.py C:\Ejemplo` crea una base SQLite de ejemplo y un `agente.ini` que la lee.
