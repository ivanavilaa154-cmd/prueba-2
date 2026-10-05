# Plantillas de lectura directa

Copiá las secciones `[base]` y `[consulta:…]` de la plantilla de tu sistema al final de `agente.ini` y ajustá rutas y nombres.

- Cada consulta trae **solo lo nuevo**: la columna `incremental` (una fecha o un número que crece) se usa como marca de agua y
  en la consulta se escribe `:desde` donde va el último valor leído. La primera vez se usa `desde_inicial` (si no, 400 días atrás).
- Si las columnas se llaman como los datos de la plataforma (`fecha`, `sucursal`, `ticket`, `producto`, `cantidad`, `precio`…),
  se importan solas; si no, la primera vez se confirman en Datos → Importar.
- El agente **solo lee**: abre la base en modo lectura y rechaza cualquier consulta que no sea un único `SELECT`.
- Las claves de la base pueden ir en una variable de entorno de Windows y escribirse en la cadena como `%TANGO_CLAVE%`
  (o `${TANGO_CLAVE}`), así no quedan en el archivo.

| Sistema | Plantilla | Necesita |
|---|---|---|
| Base SQLite (muchos sistemas chicos) | `sqlite.ini` | nada |
| dBase, FoxPro, Clipper (archivos .dbf) | `dbf.ini` | nada |
| Tango Gestión (SQL Server) | `tango_sqlserver.ini` | controlador ODBC de SQL Server (viene con Windows) |
| Access (.mdb / .accdb) | `access.ini` | Microsoft Access Database Engine |
| Firebird (.fdb) | `firebird.ini` | controlador ODBC de Firebird |
| MySQL / MariaDB | `mysql.ini` | MySQL Connector/ODBC |

Los nombres de tablas y columnas de cada sistema cambian según la versión: revisalos con quien administra el sistema antes de
activar la consulta (el agente avisa en Datos → Conexiones si una consulta falla).
