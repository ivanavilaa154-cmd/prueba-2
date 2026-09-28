// Semáforo con ícono y texto: nunca depende solo del color (sección 15). Colores de estado de la paleta validada.
const ESTADOS: Record<string, { texto: string; icono: string; color: string }> = {
  rojo: { texto: "Se agota", icono: "●", color: "var(--estado-critico)" },
  amarillo: { texto: "Pedir", icono: "▲", color: "var(--estado-alerta)" },
  verde: { texto: "Cubierto", icono: "✓", color: "var(--estado-bien)" },
  gris: { texto: "Sobrestock", icono: "■", color: "var(--gris)" },
};

export function Semaforo({ valor, corto = false }: { valor: string | null | undefined; corto?: boolean }) {
  const e = ESTADOS[valor ?? ""] ?? { texto: "—", icono: "", color: "var(--gris)" };
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm" title={e.texto}>
      <span aria-hidden="true" style={{ color: e.color }} className="text-base leading-none">{e.icono}</span>
      {!corto && <span>{e.texto}</span>}
      {corto && <span className="sr-only">{e.texto}</span>}
    </span>
  );
}

export const TEXTO_SEMAFORO = Object.fromEntries(Object.entries(ESTADOS).map(([k, v]) => [k, v.texto]));
