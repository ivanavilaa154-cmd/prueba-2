-- Retail · Partes 3 a 6: importación, lector de documentos y conexión con la caja.
ALTER TABLE lotes_importacion ADD COLUMN mapeo jsonb;
ALTER TABLE lotes_importacion ADD COLUMN resultado jsonb;
ALTER TABLE plataformas ADD COLUMN config jsonb NOT NULL DEFAULT '{}';          -- url, base, usuario (nunca la clave)
ALTER TABLE plataformas ADD COLUMN sincronizado_hasta timestamptz;              -- marca de agua de la última sincronización
ALTER TABLE plataformas ADD COLUMN ultima_sincronizacion timestamptz;
ALTER TABLE plataformas ADD COLUMN estado_sincronizacion text;                  -- ok, error, sin_probar
ALTER TABLE plataformas ADD COLUMN error_sincronizacion text;
ALTER TABLE documentos_leidos ADD COLUMN nombre_archivo text;
ALTER TABLE documentos_leidos ADD COLUMN resultado jsonb;
