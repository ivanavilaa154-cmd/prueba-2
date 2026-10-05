import { cx } from "@/components/ui";

// Tarjeta de una cifra con su nota (pantallas del modo distribuidor).
export function Cifra({ titulo, valor, nota, tono }: { titulo: string; valor: string; nota?: string; tono?: "peligro" | "alerta" | "ok" }) {
  return (
    <div className="rounded-xl border border-borde bg-panel p-4">
      <p className="text-sm text-suave">{titulo}</p>
      <p className={cx("mt-1 text-2xl font-semibold", tono === "peligro" && "text-peligro", tono === "ok" && "text-ok")}>{valor}</p>
      {nota && <p className="mt-1 text-xs text-suave">{nota}</p>}
    </div>
  );
}
