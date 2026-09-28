// Tarjeta de indicador: valor, variación contra el período anterior (con signo y flecha, no solo color) y nota.
import { numero } from "@/lib/formato";

export function Indicador({ titulo, valor, actual, anterior, nota, invertido = false }: {
  titulo: string; valor: string; actual?: string | number | null; anterior?: string | number | null; nota?: string; invertido?: boolean;
}) {
  const a = Number(actual ?? 0), b = Number(anterior ?? 0);
  const variacion = anterior !== undefined && anterior !== null && b !== 0 ? (a / b - 1) * 100 : null;
  const bueno = variacion !== null && (invertido ? variacion < 0 : variacion > 0);
  return (
    <div className="rounded-xl border border-borde bg-panel p-4">
      <p className="text-sm text-suave">{titulo}</p>
      <p className="mt-1 text-2xl font-semibold">{valor}</p>
      {variacion !== null && (
        <p className={`mt-1 text-xs ${Math.abs(variacion) < 0.5 ? "text-suave" : bueno ? "text-ok" : "text-peligro"}`}>
          {variacion > 0 ? "▲" : variacion < 0 ? "▼" : "="} {variacion > 0 ? "+" : ""}{numero(variacion, 1)} % vs. período anterior
        </p>
      )}
      {nota && <p className="mt-1 text-xs text-suave">{nota}</p>}
    </div>
  );
}
