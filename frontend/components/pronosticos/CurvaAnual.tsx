"use client";
// (3) Curva anual: meses reales y proyectados con la estacionalidad aprendida, y los eventos del año.
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { fecha, numero, plataCorta } from "@/lib/formato";
import { Aviso, Tabla, Tarjeta } from "@/components/ui";

type R = { real: { mes: string; real: number }[]; proyectado: { mes: string; proyectado: number; indice_estacional: number }[];
  eventos: { fecha: string; tipo: string; nombre: string }[]; categorias: { categoria: string; mes_pico: number; mes_valle: number; amplitud: number }[];
  meses_historia: number };
const MESES = ["", "ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

export function CurvaAnual() {
  const [r, setR] = useState<R | null>(null);
  useEffect(() => { api<R>("/pronosticos/anual").then(setR).catch(() => {}); }, []);
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const datos = [...r.real.slice(-12).map((x) => ({ mes: x.mes, real: x.real, proyectado: null as number | null })),
    ...r.proyectado.map((x) => ({ mes: x.mes, real: null as number | null, proyectado: x.proyectado }))]
    .map((x) => ({ ...x, etiqueta: `${MESES[Number(x.mes.slice(5, 7))]} ${x.mes.slice(2, 4)}` }));
  return (
    <div className="grid grid-cols-1 gap-4">
      {r.meses_historia < 13 && <Aviso tipo="alerta">Hay {r.meses_historia} meses de historia: la estacionalidad se completa con 12 meses (mejor 24).</Aviso>}
      <Tarjeta titulo="Últimos 12 meses y próximos 12">
        <div className="h-72">
          <ResponsiveContainer>
            <BarChart data={datos} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
              <XAxis dataKey="etiqueta" tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" interval={1} />
              <YAxis tickFormatter={(v: number) => plataCorta(v)} width={70} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
              <Tooltip formatter={(v, n) => [plataCorta(Number(v)), n === "real" ? "Real" : "Proyectado"]} cursor={{ fill: "var(--panel-2)" }} />
              <Bar dataKey="real" fill="var(--serie-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
              <Bar dataKey="proyectado" fill="var(--serie-2)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-1 text-xs text-suave">Proyectado = venta diaria actual sin estacionalidad × índice del mes × días × inflación esperada. En pesos corrientes.</p>
      </Tarjeta>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Tarjeta titulo="Categorías más estacionales">
          <Tabla columnas={["Categoría", "Mes pico", "Mes flojo", "Diferencia"]}>
            {r.categorias.slice(0, 10).map((c) => (
              <tr key={c.categoria}><td>{c.categoria}</td><td>{MESES[c.mes_pico]}</td><td>{MESES[c.mes_valle]}</td><td className="text-right">{numero(c.amplitud * 100)} %</td></tr>
            ))}
          </Tabla>
          <p className="mt-2 text-xs text-suave">Comprá antes del pico: el pedido anticipado evita quiebres en las fechas fuertes.</p>
        </Tarjeta>
        <Tarjeta titulo="Eventos de los próximos 12 meses">
          <ul className="grid max-h-80 gap-1 overflow-y-auto text-sm">
            {r.eventos.map((e) => <li key={e.fecha + e.nombre}>{fecha(e.fecha)} · {e.nombre} <span className="text-suave">({e.tipo})</span></li>)}
          </ul>
        </Tarjeta>
      </div>
    </div>
  );
}
