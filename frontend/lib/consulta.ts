// Arma los parámetros de consulta a partir del filtro global (período, sucursales, canal).
import type { Filtro } from "@/components/Sesion";

export function parametrosFiltro(f: Filtro, extra: Record<string, string | number | null | undefined> = {}): string {
  const q = new URLSearchParams();
  q.set("periodo", f.periodo);
  if (f.periodo === "personalizado" && f.desde && f.hasta) {
    q.set("desde", f.desde);
    q.set("hasta", f.hasta);
  }
  if (f.ubicaciones.length) q.set("ubicaciones", f.ubicaciones.join(","));
  if (f.canal !== "todos") q.set("canal", f.canal);
  for (const [k, v] of Object.entries(extra)) if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  return q.toString();
}
