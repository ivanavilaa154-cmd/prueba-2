-- Retail · Parte 9: adjuntos de email (PDF de la OC) y datos de la recepción.
ALTER TABLE emails ADD COLUMN adjunto text;
ALTER TABLE recepciones_lineas ADD COLUMN diferencia text;           -- faltante, sobrante, costo_distinto
ALTER TABLE transferencias_lineas ADD COLUMN diferencia text;
ALTER TABLE ordenes_compra ADD COLUMN cancelada_motivo text;
