"use client";
// 10.3 Ventas reales ajustadas por inflación: nominal vs. en pesos del último mes (misma unidad: un solo eje).
import { useEffect, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { parametrosFiltro } from "@/lib/consulta";
import { numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, ComoSeCalcula, Tabla, Tarjeta } from "@/components/ui";

type Efectos = { efecto_precio: string; efecto_cantidad: string; variacion: string };
type Mes = { mes: string; nominal: string; unidades: string; real: string | null; indice: string; mes_incompleto: boolean; dias: number;
  var_mensual_real?: string; var_interanual_real?: string; var_interanual_nominal?: string; efectos_mensual?: Efectos; efectos_interanual?: Efectos };
const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const nombreMes = (iso: string) => `${MESES[Number(iso.slice(5, 7)) - 1]} ${iso.slice(2, 4)}`;

function Variacion({ v }: { v?: string }) {
  if (v === undefined) return <span className="text-suave">—</span>;
  const n = Number(v);
  return <span className={n > 0.5 ? "text-ok" : n < -0.5 ? "text-peligro" : "text-suave"}>{n > 0 ? "▲ +" : n < 0 ? "▼ " : ""}{numero(n, 1)} %</span>;
}

export function Inflacion() {
  const { filtro } = useSesion();
  const [r, setR] = useState<{ meses: Mes[]; base: string; fuente_ipc: string; aviso?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<typeof r>(`/ventas/inflacion?${parametrosFiltro(filtro)}`).then(setR).catch((e) => setError(e.message)); }, [filtro]);
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  if (r.aviso) return <Aviso tipo="info">{r.aviso}</Aviso>;
  const completos = r.meses.filter((m) => !m.mes_incompleto);
  const ultimo = completos[completos.length - 1];
  const datos = r.meses.map((m) => ({ mes: nombreMes(m.mes), nominal: Number(m.nominal), real: Number(m.real) }));
  return (
    <div className="grid gap-4">
      {ultimo && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-borde bg-panel p-4"><p className="text-sm text-suave">Ventas de {nombreMes(ultimo.mes)}</p><p className="mt-1 text-2xl font-semibold">{plataCorta(ultimo.nominal)}</p></div>
          <div className="rounded-xl border border-borde bg-panel p-4"><p className="text-sm text-suave">Contra el mes anterior, sin inflación</p><p className="mt-1 text-2xl font-semibold"><Variacion v={ultimo.var_mensual_real} /></p></div>
          <div className="rounded-xl border border-borde bg-panel p-4"><p className="text-sm text-suave">Contra el mismo mes del año pasado, sin inflación</p><p className="mt-1 text-2xl font-semibold"><Variacion v={ultimo.var_interanual_real} /></p>
            {ultimo.var_interanual_nominal && <p className="text-xs text-suave">En pesos corrientes: {numero(ultimo.var_interanual_nominal, 1)} %</p>}</div>
        </div>
      )}
      <Tarjeta titulo="Ventas por mes: nominales y en pesos de hoy">
        <div className="h-64">
          <ResponsiveContainer>
            <LineChart data={datos} margin={{ top: 4, right: 12, left: 8, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
              <XAxis dataKey="mes" tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
              <YAxis tickFormatter={(v: number) => plataCorta(v).replace("$ ", "")} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" width={56} />
              <Tooltip formatter={(v, n) => [plata(Number(v).toFixed(0)), n === "real" ? "En pesos de hoy" : "Nominal"]} />
              <Legend formatter={(v) => (v === "real" ? "En pesos de hoy (ajustado por IPC)" : "Nominal (pesos de cada mes)")} />
              <Line dataKey="nominal" stroke="var(--serie-2)" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
              <Line dataKey="real" stroke="var(--serie-1)" strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-1 text-xs text-suave">Índice: {r.fuente_ipc}. El último mes puede estar incompleto.</p>
      </Tarjeta>
      <Tarjeta titulo="Detalle mensual">
        <Tabla columnas={["Mes", "Nominal", "En pesos de hoy", "Unidades", "Var. real mensual", "Var. real interanual", "Efecto precio", "Efecto cantidad"]}>
          {[...r.meses].reverse().map((m) => (
            <tr key={m.mes}>
              <td>{nombreMes(m.mes)}{m.mes_incompleto && <span className="text-xs text-suave"> (en curso)</span>}</td>
              <td className="cifra text-right">{plata(Number(m.nominal).toFixed(0))}</td>
              <td className="cifra text-right">{plata(Number(m.real).toFixed(0))}</td>
              <td className="cifra text-right">{numero(m.unidades, 0)}</td>
              <td className="text-right"><Variacion v={m.var_mensual_real} /></td>
              <td className="text-right"><Variacion v={m.var_interanual_real} /></td>
              <td className="cifra text-right">{m.efectos_mensual ? plata(Number(m.efectos_mensual.efecto_precio).toFixed(0)) : "—"}</td>
              <td className="cifra text-right">{m.efectos_mensual ? plata(Number(m.efectos_mensual.efecto_cantidad).toFixed(0)) : "—"}</td>
            </tr>
          ))}
        </Tabla>
      </Tarjeta>
      <ComoSeCalcula>
        <p>Venta en pesos de hoy = venta del mes × índice del último mes ÷ índice de ese mes (IPC). Así se comparan meses sin el efecto de la inflación.</p>
        <p>La variación de la facturación se separa en efecto precio (cuánto subió el precio promedio, sobre lo vendido este mes) y efecto cantidad (cuántas unidades más o menos, al precio del mes anterior). Los dos suman la variación total.</p>
      </ComoSeCalcula>
    </div>
  );
}
