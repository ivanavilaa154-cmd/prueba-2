-- Al borrar una empresa (por ejemplo, las de demostración), su auditoría se conserva: queda sin empresa en lugar de impedir el
-- borrado. La auditoría sigue siendo de solo agregar (no tiene política de borrado).
ALTER TABLE auditoria DROP CONSTRAINT auditoria_org_id_fkey;
ALTER TABLE auditoria ADD CONSTRAINT auditoria_org_id_fkey FOREIGN KEY (org_id) REFERENCES organizaciones(id) ON DELETE SET NULL;
