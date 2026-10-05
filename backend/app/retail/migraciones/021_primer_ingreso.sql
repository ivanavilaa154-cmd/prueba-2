-- SPEC v2 · sección 15: primer ingreso guiado de 6 pasos. Se guarda qué pasos confirmó el dueño y cuándo terminó (o si lo salteó).
ALTER TABLE organizaciones
    ADD COLUMN primer_ingreso jsonb NOT NULL DEFAULT '{}',          -- {paso: fecha en que se confirmó}
    ADD COLUMN primer_ingreso_completo_at timestamptz,
    ADD COLUMN primer_ingreso_omitido boolean NOT NULL DEFAULT false;
