-- SPEC v2 · Fase 2: el agente lee la base del sistema de caja (en solo lectura) e informa el estado de cada consulta.
ALTER TABLE agentes_sincronizacion
    ADD COLUMN base text,                                   -- sqlite, dbf, odbc (o nulo: solo carpeta)
    ADD COLUMN consultas jsonb NOT NULL DEFAULT '[]';       -- [{nombre, tipo, ultima, filas, error, marca}]
