-- Retail · 13.5 Privacidad y cumplimiento (Ley 25.326 de Protección de Datos Personales).
ALTER TABLE usuarios ADD COLUMN privacidad_version text;              -- versión de la política que aceptó
ALTER TABLE usuarios ADD COLUMN privacidad_aceptada_at timestamptz;
ALTER TABLE organizaciones ADD COLUMN baja_solicitada_at timestamptz;  -- supresión: se borra todo al cumplirse el plazo
ALTER TABLE organizaciones ADD COLUMN baja_solicitada_por bigint REFERENCES usuarios(id) ON DELETE SET NULL;
ALTER TABLE clientes ADD COLUMN anonimizado_at timestamptz;            -- supresión de los datos de un cliente final
ALTER TABLE clientes ALTER COLUMN identificador DROP NOT NULL;

-- Copias de seguridad: pg_dump corre con search_path vacío; la función que usan las políticas por sucursal nombra a la otra
-- con su esquema para funcionar igual (sin SET search_path, así la función se sigue expandiendo dentro de las consultas).
CREATE OR REPLACE FUNCTION app_ve_ubicacion(u bigint) RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT public.app_superadmin()
       OR coalesce(current_setting('app.todas_ubicaciones', true), '') = '1'
       OR u = ANY (coalesce(NULLIF(current_setting('app.ubicaciones', true), ''), '{}')::bigint[]) $$;
