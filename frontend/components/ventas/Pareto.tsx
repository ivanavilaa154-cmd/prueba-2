"use client";
// 10.2 Pareto ABC: participación de cada producto y acumulado (ambos en %: un solo eje), clases, Pareto cruzado e historial.
import { useEffect, useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { parametrosFiltro } from "@/lib/consulta";
import { numero, plata } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, ComoSeCalcula, Selector, Tarjeta } from "@/components/ui";

type Item = { id: number; nombre: string; unidades: string; facturacion: string; ganancia: string; clase: string; participacion: string; acumulado: string; cruzado: string | null };
type R = { items: Item[]; resumen: Record<string, { items: number; participacion: string }>; matriz_cruzada: Record<string, number>; periodo: { etiqueta: string } };
// Clases ordinales: un solo tono (azul) de oscuro a claro, nunca más claro que el paso 250 sobre fondo claro.
const COLOR_CLASE: Record<string, string> = { A: "#1c5cab", B: "#3987e5", C: "#86b6ef" };
const CRUCE: Record<string, string> = { AA: "Estrellas del surtido", AC: "Imanes: venden mucho y ganan poco", CA: "Joyas: poco volumen, mucha ganancia", CC: "Candidatos a revisar" };

export function Pareto() {
  const { filtro } = useSesion();
  const [criterio, setCriterio] = useState("ganancia");
  const [nivel, setNivel] = useState("producto");
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setR(null);
    // «Este mes» es poco para un Pareto: en ese caso se usan los últimos 90 días (lo mismo que la clase ABC del sistema).
    const q = parametrosFiltro(filtro, { criterio, nivel });
    api<R>(`/ventas/pareto?${filtro.periodo === "mes" ? q.replace("periodo=mes", "periodo=90d") : q}`).then(setR).catch((e) => setError(e.message));
  }, [filtro, criterio, nivel]);
  // Curva completa: eje X = % de ítems (ordenados de mayor a menor), eje Y = % acumulado. Las franjas marcan las clases.
  const datos = useMemo(() => {
    const items = r?.items ?? [];
    const n = items.length || 1;
    return [{ x: 0, acumulado: 0, nombre: "", clase: "A" },
      ...items.map((i, k) => ({ x: ((k + 1) / n) * 100, acumulado: Number(i.acumulado), nombre: i.nombre, clase: i.clase }))];
  }, [r]);
  const cortes = useMemo(() => {
    const items = r?.items ?? [];
    const n = items.length || 1;
    const hasta = (c: string) => (items.filter((i) => i.clase <= c).length / n) * 100;
    return { A: hasta("A"), B: hasta("B") };
  }, [r]);
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  const unidad = criterio === "unidades" ? "unidades" : criterio === "facturacion" ? "facturación" : "ganancia";
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap gap-2">
        <Selector aria-label="Criterio" className="w-auto" value={criterio} onChange={(e) => setCriterio(e.target.value)}>
          <option value="ganancia">Por ganancia</option><option value="facturacion">Por facturación</option><option value="unidades">Por unidades</option>
        </Selector>
        <Selector aria-label="Nivel" className="w-auto" value={nivel} onChange={(e) => setNivel(e.target.value)}>
          <option value="producto">Productos</option><option value="categoria">Categorías</option><option value="proveedor">Proveedores</option>
        </Selector>
        {r && <span className="self-center text-sm text-suave">{filtro.periodo === "mes" ? "Últimos 90 días" : r.periodo.etiqueta}</span>}
      </div>
      {!r ? <p className="text-sm text-suave">Cargando…</p> : (
        <>
          <div className="grid grid-cols-3 gap-3">
            {["A", "B", "C"].map((c) => (
              <div key={c} className="rounded-xl border border-borde bg-panel p-4">
                <p className="flex items-center gap-2 text-sm text-suave"><span className="inline-block size-3 rounded-sm" style={{ background: COLOR_CLASE[c] }} aria-hidden="true" />Clase {c}</p>
                <p className="mt-1 text-2xl font-semibold">{numero(r.resumen[c]?.items ?? 0)}</p>
                <p className="text-xs text-suave">{numero(r.resumen[c]?.participacion ?? 0, 1)} % de la {unidad}</p>
              </div>
            ))}
          </div>
          <Tarjeta titulo="Curva de Pareto">
            <p className="mb-2 text-xs text-suave">Cuánto del total ({unidad}) explica cada porcentaje de los {nivel === "producto" ? "productos" : nivel === "categoria" ? "categorías" : "proveedores"}, de mayor a menor. Franjas: clase A, B y C.</p>
            <div className="h-64">
              <ResponsiveContainer>
                <AreaChart data={datos} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
                  <ReferenceArea x1={0} x2={cortes.A} fill={COLOR_CLASE.A} fillOpacity={0.12} label={{ value: "A", position: "insideTopLeft", fill: "var(--grafico-tinta)", fontSize: 12 }} />
                  <ReferenceArea x1={cortes.A} x2={cortes.B} fill={COLOR_CLASE.B} fillOpacity={0.12} label={{ value: "B", position: "insideTopLeft", fill: "var(--grafico-tinta)", fontSize: 12 }} />
                  <ReferenceArea x1={cortes.B} x2={100} fill={COLOR_CLASE.C} fillOpacity={0.12} label={{ value: "C", position: "insideTopLeft", fill: "var(--grafico-tinta)", fontSize: 12 }} />
                  <XAxis dataKey="x" type="number" domain={[0, 100]} tickFormatter={(v: number) => `${Math.round(v)}%`} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
                  <YAxis domain={[0, 100]} tickFormatter={(v: number) => `${v}%`} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
                  <Tooltip formatter={(v) => [`${numero(v as number, 1)} %`, "Acumulado"]}
                    labelFormatter={(_, p) => (p?.[0]?.payload?.nombre ? `${p[0].payload.nombre} (clase ${p[0].payload.clase}) · ${numero(p[0].payload.x, 0)} % de los ítems` : "")} />
                  <Area dataKey="acumulado" type="monotone" stroke="var(--serie-1)" strokeWidth={2} fill="var(--serie-1)" fillOpacity={0.15} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-1 text-xs text-suave">Con el {numero(cortes.A, 0)} % de los ítems (clase A) se explica el 80 % de la {unidad}.</p>
          </Tarjeta>
          {nivel === "producto" && (
            <Tarjeta titulo="Pareto cruzado: clase por unidades × clase por ganancia">
              <table className="text-sm">
                <thead><tr><th /><th className="px-3 text-suave">Ganancia A</th><th className="px-3 text-suave">B</th><th className="px-3 text-suave">C</th></tr></thead>
                <tbody>
                  {["A", "B", "C"].map((u) => (
                    <tr key={u}><th className="py-1 pr-3 text-left text-suave">{u === "A" ? "Unidades A" : u}</th>
                      {["A", "B", "C"].map((g) => <td key={g} className="cifra px-3 py-1 text-center" title={CRUCE[u + g] ?? ""}>{numero(r.matriz_cruzada[u + g] ?? 0)}</td>)}</tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-suave">A en unidades y C en ganancia = imanes; C en unidades y A en ganancia = joyas.</p>
            </Tarjeta>
          )}
          <Tarjeta>
            <TablaDatos filas={r.items} idFila={(i) => String(i.id)} nombreArchivo={`pareto-${criterio}-${nivel}`}
              columnas={[
                { id: "nombre", titulo: nivel === "producto" ? "Producto" : nivel === "categoria" ? "Categoría" : "Proveedor", valor: (i) => i.nombre },
                { id: "clase", titulo: "Clase", valor: (i) => i.clase },
                ...(nivel === "producto" ? [{ id: "cruzado", titulo: "Unid.×Gan.", valor: (i: Item) => i.cruzado }] : []),
                { id: "part", titulo: "Participación", valor: (i) => Number(i.participacion), render: (i) => `${numero(i.participacion, 2)} %`, derecha: true },
                { id: "acum", titulo: "Acumulado", valor: (i) => Number(i.acumulado), render: (i) => `${numero(i.acumulado, 1)} %`, derecha: true },
                { id: "gan", titulo: "Ganancia", valor: (i) => Number(i.ganancia), render: (i) => plata(Number(i.ganancia).toFixed(0)), derecha: true },
                { id: "fac", titulo: "Facturación", valor: (i) => Number(i.facturacion), render: (i) => plata(Number(i.facturacion).toFixed(0)), derecha: true, ocultarEnCelular: true },
                { id: "uni", titulo: "Unidades", valor: (i) => Number(i.unidades), render: (i) => numero(i.unidades, 0), derecha: true, ocultarEnCelular: true },
              ]} />
          </Tarjeta>
        </>
      )}
      <ComoSeCalcula>
        <p>Se ordena de mayor a menor y se acumula el porcentaje. Un ítem es A si lo acumulado antes de él es menor al 80 % (el que cruza el 80 % también es A), B hasta el 95 %, C el resto. Ítems sin ganancia (o con pérdida) son C. Las participaciones suman exactamente 100 %.</p>
        <p>La clase ABC por ganancia de los últimos 90 días alimenta el stock de seguridad, la prioridad de avisos, los recuentos y los candidatos a liquidar. Se guarda un historial mensual.</p>
      </ComoSeCalcula>
    </div>
  );
}
