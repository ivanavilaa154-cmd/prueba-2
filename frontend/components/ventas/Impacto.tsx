"use client";
// Medición de impacto (13.4): cómo estaba el comercio al conectarse y cuánto mejoró cada mes.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, ComoSeCalcula, Tabla, Tarjeta } from "@/components/ui";

type Ind = { desde: string; hasta: string; ventas: string; ventas_perdidas: string; tasa_faltantes: number; merma: string; merma_pct: number; plata_parada: string; margen: number };
type Mes = Ind & { mes: string; mejora: { faltantes_evitados: string; merma_reducida: string; margen_recuperado: string; plata_liberada: string; total: string } };
type R = { linea_base: Ind; meses: Mes[] };
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const signo = (v: string) => (Number(v) > 0 ? <span className="text-ok">▲ {plata(v)}</span> : Number(v) < 0 ? <span className="text-peligro">▼ {plata(Math.abs(Number(v)))}</span> : "—");

export function Impacto() {
  const { puede } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (puede("ver_costos")) api<R>("/impacto").then(setR).catch((e) => setError(e.message)); }, [puede]);
  if (!puede("ver_costos")) return <Aviso>El reporte de impacto lo ven el dueño y el comprador.</Aviso>;
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const b = r.linea_base;
  return (
    <div className="grid grid-cols-1 gap-4">
      <Tarjeta titulo={`Cómo estabas al empezar · del ${fechaCorta(b.desde)} al ${fechaCorta(b.hasta)}`}>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[["Ventas perdidas por faltantes", `${numero(b.tasa_faltantes * 100, 1)} %`, `${plataCorta(b.ventas_perdidas)} en 4 semanas`],
            ["Merma", `${numero(b.merma_pct * 100, 2)} %`, `${plataCorta(b.merma)} de lo vendido`], ["Plata parada", plataCorta(b.plata_parada), "productos con más de 30 días de stock"],
            ["Margen bruto", `${numero(b.margen * 100, 1)} %`, ""]].map(([t, v, n]) => (
            <div key={t} className="rounded-lg border border-borde p-3"><p className="text-xs text-suave">{t}</p><p className="text-xl font-semibold">{v}</p>{n && <p className="text-xs text-suave">{n}</p>}</div>
          ))}
        </div>
      </Tarjeta>
      <Tarjeta titulo="Mejora mes a mes">
        <Tabla columnas={["Mes", "Faltantes evitados", "Merma reducida", "Margen recuperado", "Total en el mes", "Plata liberada de sobrestock"]}>
          {r.meses.map((m) => (
            <tr key={m.mes}>
              <td className="whitespace-nowrap">{MESES[Number(m.mes.slice(5, 7)) - 1]} {m.mes.slice(0, 4)}</td>
              <td className="text-right">{signo(m.mejora.faltantes_evitados)}<span className="block text-xs text-suave">{numero(m.tasa_faltantes * 100, 1)} % perdido</span></td>
              <td className="text-right">{signo(m.mejora.merma_reducida)}<span className="block text-xs text-suave">{numero(m.merma_pct * 100, 2)} %</span></td>
              <td className="text-right">{signo(m.mejora.margen_recuperado)}<span className="block text-xs text-suave">{numero(m.margen * 100, 1)} %</span></td>
              <td className="text-right font-semibold">{signo(m.mejora.total)}</td>
              <td className="text-right">{signo(m.mejora.plata_liberada)}</td>
            </tr>
          ))}
        </Tabla>
        <div className="mt-3">
          <ComoSeCalcula>
            <p>La línea base son las primeras 4 semanas con datos. Cada mes se compara contra ella: faltantes evitados = (tasa de ventas perdidas de la base − la del mes) × ventas del mes; merma reducida y margen recuperado, igual con sus porcentajes.</p>
            <p>Plata liberada = plata parada de la base − plata parada al cierre del mes (stock a costo de productos con más de 30 días de stock). ▲ mejora, ▼ empeora.</p>
          </ComoSeCalcula>
        </div>
      </Tarjeta>
    </div>
  );
}
