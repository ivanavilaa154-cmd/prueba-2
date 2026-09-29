"use client";
// (2, 6) Venta por sucursal × canal × día con rango del 80 %, y el total de la empresa.
import { useEffect, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { fecha, numero, plataCorta } from "@/lib/formato";
import { Indicador } from "@/components/Indicador";
import { ComoSeCalcula, Selector, Tabla, Tarjeta } from "@/components/ui";

type Dia = { fecha: string; pronostico: number; minimo: number; maximo: number };
type Serie = { ubicacion_id: number; ubicacion: string; canal: string; canal_nombre: string; dias: Dia[]; total: number; minimo: number; maximo: number;
  ultimos_28: { fecha: string; real: number }[]; real_28: number };
type R = { hoy: string; dias: number; inflacion_mensual: number; series: Serie[]; total: Dia[]; total_periodo: number; eventos: { fecha: string; tipo: string; nombre: string }[] };

export function VentasFuturas() {
  const [dias, setDias] = useState(30);
  const [r, setR] = useState<R | null>(null);
  const [sel, setSel] = useState("total");
  useEffect(() => { setR(null); api<R>(`/pronosticos/ventas?dias=${dias}`).then(setR).catch(() => {}); }, [dias]);
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const serie = sel === "total" ? null : r.series.find((s) => `${s.ubicacion_id}-${s.canal}` === sel);
  const reales = serie ? serie.ultimos_28 : r.series.reduce<Record<string, number>>((acc, s) => { s.ultimos_28.forEach((x) => { acc[x.fecha] = (acc[x.fecha] ?? 0) + x.real; }); return acc; }, {});
  const pasado = serie ? (reales as { fecha: string; real: number }[]).map((x) => ({ fecha: x.fecha, real: x.real }))
    : Object.entries(reales as Record<string, number>).sort().map(([f, v]) => ({ fecha: f, real: v }));
  const futuro = (serie ? serie.dias : r.total).map((d) => ({ fecha: d.fecha, pronostico: d.pronostico, rango: [d.minimo, d.maximo] as [number, number] }));
  const datos = [...pasado.slice(-21), ...futuro].map((x) => ({ ...x, etiqueta: fecha(x.fecha).slice(0, 5) }));
  const minimo = serie ? serie.minimo : r.total.reduce((s, d) => s + d.minimo, 0);
  const maximo = serie ? serie.maximo : r.total.reduce((s, d) => s + d.maximo, 0);
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex flex-wrap gap-2">
        <Selector aria-label="Serie" value={sel} onChange={(e) => setSel(e.target.value)}>
          <option value="total">Toda la empresa</option>
          {r.series.map((s) => <option key={`${s.ubicacion_id}-${s.canal}`} value={`${s.ubicacion_id}-${s.canal}`}>{s.ubicacion} · {s.canal_nombre}</option>)}
        </Selector>
        <Selector aria-label="Días" value={dias} onChange={(e) => setDias(Number(e.target.value))}>
          {[7, 14, 30, 60].map((d) => <option key={d} value={d}>Próximos {d} días</option>)}
        </Selector>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Indicador titulo={`Venta proyectada · ${dias} días`} valor={plataCorta(serie ? serie.total : r.total_periodo)} nota={`entre ${plataCorta(minimo)} y ${plataCorta(maximo)} (80 %)`} />
        <Indicador titulo="Inflación mensual considerada" valor={`${numero(r.inflacion_mensual * 100, 1)} %`} nota="promedio de los últimos 3 meses del IPC" />
        {serie && <Indicador titulo="Vendido últimos 28 días" valor={plataCorta(serie.real_28)} />}
      </div>
      <Tarjeta titulo="Real y pronóstico por día">
        <div className="h-72">
          <ResponsiveContainer>
            <ComposedChart data={datos} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
              <XAxis dataKey="etiqueta" tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" interval="preserveStartEnd" />
              <YAxis tickFormatter={(v: number) => plataCorta(v)} width={70} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
              <Tooltip formatter={(v, n) => [Array.isArray(v) ? `${plataCorta(v[0])} a ${plataCorta(v[1])}` : plataCorta(Number(v)), n === "rango" ? "Rango 80 %" : n === "real" ? "Real" : "Pronóstico"]} />
              <Area dataKey="rango" stroke="none" fill="var(--serie-1)" fillOpacity={0.15} isAnimationActive={false} />
              <Line dataKey="real" stroke="var(--grafico-tinta)" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="pronostico" stroke="var(--serie-1)" strokeWidth={2} strokeDasharray="5 3" dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-1 text-xs text-suave">Línea llena: vendido. Punteada: pronóstico. Banda: rango con 80 % de confianza.</p>
      </Tarjeta>
      <Tarjeta titulo="Por sucursal y canal">
        <Tabla columnas={["Sucursal", "Canal", `Próximos ${dias} días`, "Rango 80 %", "Últimos 28 días"]}>
          {r.series.map((s) => (
            <tr key={`${s.ubicacion_id}-${s.canal}`}><td>{s.ubicacion}</td><td>{s.canal_nombre}</td><td className="text-right font-semibold">{plataCorta(s.total)}</td>
              <td className="whitespace-nowrap text-right text-suave">{plataCorta(s.minimo)} – {plataCorta(s.maximo)}</td><td className="text-right">{plataCorta(s.real_28)}</td></tr>
          ))}
        </Tabla>
      </Tarjeta>
      {r.eventos.length > 0 && (
        <Tarjeta titulo="Fechas que mueven la venta en el período">
          <ul className="grid gap-1 text-sm">{r.eventos.map((e) => <li key={e.fecha + e.nombre}>{fecha(e.fecha)} · {e.nombre} <span className="text-suave">({e.tipo})</span></li>)}</ul>
        </Tarjeta>
      )}
      <ComoSeCalcula>
        <p>Mismo modelo que por producto, aplicado a la facturación diaria de cada sucursal y canal: promedio ponderado de las últimas 4 semanas × patrón del día de la semana, inicio y fin de mes, feriados, estacionalidad y tendencia, más la inflación mensual.</p>
        <p>Rango: cómo variaron las últimas 8 semanas (80 % de confianza). El total de la empresa suma los pronósticos y combina los rangos.</p>
      </ComoSeCalcula>
    </div>
  );
}
