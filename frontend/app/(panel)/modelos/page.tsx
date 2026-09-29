"use client";
// Salud de los pronósticos (predicciones con IA): cuánto se equivocan, hacia qué lado y si el rango de confianza se cumple.
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { fecha, fechaHora, numero, plata } from "@/lib/formato";
import { Indicador } from "@/components/Indicador";
import { Aviso, ComoSeCalcula, Tabla, Tarjeta, Vacio } from "@/components/ui";

type Metrica = { wape: number | null; sesgo: number | null; cobertura: number | null; n: number; real: number };
type Salud = {
  global: Metrica; semanas: (Metrica & { semana: string })[]; por_categoria: (Metrica & { categoria: string })[];
  por_ubicacion: (Metrica & { ubicacion: string })[]; evaluados: number; excluidos_por_quiebre: number; origen_prueba: number;
  peores: { producto_id: number; nombre: string; codigo_interno: string; ubicacion: string; error_semanal: number; error_pesos: number;
    pronostico_semanal: number; real_semanal: number; sesgo: number }[];
  datos: { productos: number; sin_costo: number; sin_mapear: number; poca_historia: number; stock_negativo: number; ultima_venta: string | null;
    calculado_at: string | null; ultima_sincronizacion: string | null; dias_historia: number };
  avisos: string[];
};
const pct = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? "—" : `${numero(v * 100, d)} %`);
const lado = (s: number | null) => (s === null ? "—" : Math.abs(s) < 0.03 ? "= parejo" : s > 0 ? `▲ sobreestima ${pct(s)}` : `▼ subestima ${pct(-s)}`);

function Filas<T extends Metrica>({ filas, clave, titulo }: { filas: T[]; clave: keyof T; titulo: string }) {
  return (
    <Tabla columnas={[titulo, "Error (WAPE)", "Sesgo", "Dentro del rango", "Unidades"]}>
      {filas.map((f) => (
        <tr key={String(f[clave])}><td>{String(f[clave])}</td><td className="text-right">{pct(f.wape)}</td><td className="whitespace-nowrap">{lado(f.sesgo)}</td>
          <td className="text-right">{pct(f.cobertura)}</td><td className="text-right">{numero(f.real)}</td></tr>
      ))}
    </Tabla>
  );
}

export default function Modelos() {
  const [s, setS] = useState<Salud | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<Salud>("/modelos/salud").then(setS).catch((e) => setError(e.message)); }, []);
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!s) return <p className="text-sm text-suave">Cargando…</p>;
  const g = s.global;
  const serie = s.semanas.map((x) => ({ semana: fecha(x.semana).slice(0, 5), wape: x.wape === null ? null : Math.round(x.wape * 1000) / 10,
    cobertura: x.cobertura === null ? null : Math.round(x.cobertura * 1000) / 10 }));
  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Salud de los pronósticos</h1>
        <p className="text-sm text-suave">Cada semana se compara lo pronosticado con lo que se vendió: cuánto se equivoca, hacia qué lado y si el rango de confianza se cumple.</p>
      </div>
      {s.evaluados === 0 ? <Vacio titulo="Todavía no hay semanas para medir">Se necesitan al menos 2 semanas de ventas.</Vacio> : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Indicador titulo="Error del pronóstico (WAPE)" valor={pct(g.wape)} nota="Por producto y sucursal, semana a semana" />
            <Indicador titulo="Sesgo" valor={lado(g.sesgo)} nota="Si pide de más o de menos en forma sistemática" />
            <Indicador titulo="Dentro del rango del 80 %" valor={pct(g.cobertura)} nota="Ideal: cerca de 80 %" />
            <Indicador titulo="Semanas medidas" valor={numero(g.n)} nota={`${numero(s.excluidos_por_quiebre)} excluidas por quiebre de stock`} />
          </div>
          {s.origen_prueba > 0 && <Aviso>Las primeras semanas se midieron con una prueba sobre el pasado: el pronóstico se recalculó con los datos que había en cada fecha.</Aviso>}
          <Tarjeta titulo="Error semana a semana">
            <div className="h-56">
              <ResponsiveContainer>
                <BarChart data={serie} margin={{ top: 4, right: 4, left: -10, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
                  <XAxis dataKey="semana" tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
                  <YAxis tickFormatter={(v: number) => `${v} %`} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
                  <Tooltip formatter={(v) => [`${numero(Number(v), 1)} %`, "Error (WAPE)"]} labelFormatter={(l) => `Semana del ${l}`} cursor={{ fill: "var(--panel-2)" }} />
                  <ReferenceLine y={(g.wape ?? 0) * 100} stroke="var(--grafico-eje)" strokeDasharray="4 4" />
                  <Bar dataKey="wape" fill="var(--serie-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-1 text-xs text-suave">Cada barra: pronóstico hecho ese día para los 7 siguientes contra lo vendido. La línea punteada es el promedio.</p>
          </Tarjeta>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Tarjeta titulo="Por categoría"><Filas filas={s.por_categoria} clave="categoria" titulo="Categoría" /></Tarjeta>
            <Tarjeta titulo="Por sucursal"><Filas filas={s.por_ubicacion} clave="ubicacion" titulo="Sucursal" /></Tarjeta>
          </div>
          <Tarjeta titulo="Productos donde más se equivoca (en pesos)">
            <Tabla columnas={["Producto", "Sucursal", "Pronóstico por semana", "Vendido por semana", "Error por semana"]}>
              {s.peores.map((p) => (
                <tr key={`${p.producto_id}-${p.ubicacion}`}>
                  <td>{p.nombre}<span className="block text-xs text-suave">{p.codigo_interno} · {lado(p.sesgo)}</span></td><td>{p.ubicacion}</td>
                  <td className="text-right">{numero(p.pronostico_semanal, 1)}</td><td className="text-right">{numero(p.real_semanal, 1)}</td>
                  <td className="text-right">{numero(p.error_semanal, 1)} u.<span className="block text-xs text-suave">{p.error_pesos ? plata(p.error_pesos) : ""}</span></td>
                </tr>
              ))}
            </Tabla>
          </Tarjeta>
        </>
      )}
      <Tarjeta titulo="Calidad de los datos">
        <div className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
          <p><span className="text-suave">Historia:</span> {numero(s.datos.dias_historia)} días</p>
          <p><span className="text-suave">Última venta recibida:</span> {fechaHora(s.datos.ultima_venta)}</p>
          <p><span className="text-suave">Último cálculo:</span> {fechaHora(s.datos.calculado_at)}</p>
          <p><span className="text-suave">Productos sin costo:</span> {numero(s.datos.sin_costo)} de {numero(s.datos.productos)}</p>
          <p><span className="text-suave">Sin emparejar al catálogo:</span> {numero(s.datos.sin_mapear)}</p>
          <p><span className="text-suave">Con stock negativo:</span> {numero(s.datos.stock_negativo)}</p>
        </div>
        {s.avisos.length > 0 && <ul className="mt-3 grid gap-1 text-sm">{s.avisos.map((a) => <li key={a}>• {a}</li>)}</ul>}
      </Tarjeta>
      <ComoSeCalcula>
        <p>WAPE = suma de |vendido − pronóstico| ÷ suma de lo vendido, por producto × sucursal y semana (pesa más lo que más se vende). Sesgo = suma de (pronóstico − vendido) ÷ vendido: positivo, sobreestima; negativo, subestima.</p>
        <p>Rango del 80 %: pronóstico ± 1,28 × desvío semanal × √(días ÷ 7). El desvío sale de cómo variaron las últimas 8 semanas con stock (con un mínimo para los productos de poca venta), más la incertidumbre de estimar el promedio.</p>
        <p>Las semanas con más de un día sin stock no se miden: ahí se vendió menos porque no había.</p>
      </ComoSeCalcula>
    </div>
  );
}
