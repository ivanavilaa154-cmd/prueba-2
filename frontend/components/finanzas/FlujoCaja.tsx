"use client";
// (40) Flujo de caja a 90 días con rango y mínimo aceptable.
import { useEffect, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { fecha, parsearMonto, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Indicador } from "@/components/Indicador";
import { Aviso, Boton, Campo, ComoSeCalcula, Entrada, Tarjeta } from "@/components/ui";

type Gasto = { concepto: string; monto: number; dia: number };
type R = { configurado: boolean; saldo_inicial: number; minimo_aceptable: number; gastos_fijos: Gasto[]; saldo_final: number; primer_dia_bajo_minimo: string | null;
  linea: { fecha: string; entradas: number; salidas: number; saldo: number; saldo_min: number; saldo_max: number }[]; totales: Record<string, number> };
const NOMBRES: Record<string, string> = { cobro_ventas: "Cobro de ventas (neto de comisiones)", cobro_fiado: "Cobro de cuentas corrientes",
  pago_proveedores: "Órdenes de compra pendientes", compras_futuras: "Compras para reponer lo vendido", gastos_fijos: "Gastos fijos" };

export function FlujoCaja() {
  const { puede } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [f, setF] = useState({ saldo: "", minimo: "", gastos: [] as { concepto: string; monto: string; dia: string }[] });
  const [error, setError] = useState<string | null>(null);
  const cargar = () => api<R>("/finanzas/flujo?dias=90").then((x) => {
    setR(x);
    setF({ saldo: String(x.saldo_inicial || ""), minimo: String(x.minimo_aceptable || ""),
      gastos: x.gastos_fijos.map((g) => ({ concepto: g.concepto, monto: String(g.monto), dia: String(g.dia) })) });
  }).catch((e) => setError(e.message));
  useEffect(() => { cargar(); }, []);
  async function guardar() {
    setError(null);
    try {
      await api("/finanzas/flujo/config", { metodo: "PUT", cuerpo: { saldo_inicial: parsearMonto(f.saldo || "0"), minimo_aceptable: parsearMonto(f.minimo || "0"),
        gastos_fijos: f.gastos.filter((g) => g.concepto && g.monto).map((g) => ({ concepto: g.concepto, monto: Number(parsearMonto(g.monto)), dia: Number(g.dia || 1) })) } });
      cargar();
    } catch (e) { setError(e instanceof Error ? e.message : "No se pudo guardar."); }
  }
  if (error && !r) return <Aviso tipo="error">{error}</Aviso>;
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const datos = r.linea.map((x) => ({ ...x, etiqueta: fecha(x.fecha).slice(0, 5), rango: [x.saldo_min, x.saldo_max] as [number, number] }));
  return (
    <div className="grid grid-cols-1 gap-4">
      {!r.configurado && <Aviso tipo="alerta">Cargá el saldo de hoy y tus gastos fijos (abajo) para que la proyección sea completa.</Aviso>}
      {r.primer_dia_bajo_minimo && <Aviso tipo="error">▲ El {fecha(r.primer_dia_bajo_minimo)} la caja podría quedar por debajo del mínimo que definiste ({plata(r.minimo_aceptable)}). Adelantá cobros, pedí plazo a proveedores o financiate antes.</Aviso>}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Indicador titulo="Saldo hoy" valor={plataCorta(r.saldo_inicial)} />
        <Indicador titulo="Saldo en 90 días" valor={plataCorta(r.saldo_final)} />
        <Indicador titulo="Entra (90 días)" valor={plataCorta((r.totales.cobro_ventas ?? 0) + (r.totales.cobro_fiado ?? 0))} />
        <Indicador titulo="Sale (90 días)" valor={plataCorta((r.totales.pago_proveedores ?? 0) + (r.totales.compras_futuras ?? 0) + (r.totales.gastos_fijos ?? 0))} />
      </div>
      <Tarjeta titulo="Saldo proyectado">
        <div className="h-72">
          <ResponsiveContainer>
            <ComposedChart data={datos} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
              <XAxis dataKey="etiqueta" tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" interval="preserveStartEnd" />
              <YAxis tickFormatter={(v: number) => plataCorta(v)} width={72} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
              <Tooltip formatter={(v, n) => [Array.isArray(v) ? `${plataCorta(v[0])} a ${plataCorta(v[1])}` : plata(Number(v)), n === "rango" ? "Rango 80 %" : "Saldo"]} />
              <Area dataKey="rango" stroke="none" fill="var(--serie-1)" fillOpacity={0.15} isAnimationActive={false} />
              <Line dataKey="saldo" stroke="var(--serie-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
              {r.minimo_aceptable > 0 && <ReferenceLine y={r.minimo_aceptable} stroke="var(--peligro)" strokeDasharray="4 4" label={{ value: "mínimo", fontSize: 11, fill: "var(--peligro)" }} />}
            </ComposedChart>
          </ResponsiveContainer>
        </div>
        <ul className="mt-2 grid gap-1 text-sm sm:grid-cols-2">
          {Object.entries(r.totales).map(([k, v]) => <li key={k}><span className="text-suave">{NOMBRES[k] ?? k}:</span> {plataCorta(v)}</li>)}
        </ul>
      </Tarjeta>
      {puede("configurar_empresa") && (
        <Tarjeta titulo="Saldo, mínimo y gastos fijos">
          {error && <div className="mb-2"><Aviso tipo="error">{error}</Aviso></div>}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Campo etiqueta="Saldo de caja y bancos hoy"><Entrada inputMode="decimal" value={f.saldo} onChange={(e) => setF({ ...f, saldo: e.target.value })} /></Campo>
            <Campo etiqueta="Mínimo aceptable"><Entrada inputMode="decimal" value={f.minimo} onChange={(e) => setF({ ...f, minimo: e.target.value })} /></Campo>
          </div>
          <div className="mt-3 grid gap-2">
            {f.gastos.map((g, i) => (
              <div key={i} className="grid grid-cols-[1fr_8rem_5rem_auto] gap-2">
                <Entrada aria-label="Concepto" placeholder="Sueldos, alquiler…" value={g.concepto} onChange={(e) => setF({ ...f, gastos: f.gastos.map((x, j) => (j === i ? { ...x, concepto: e.target.value } : x)) })} />
                <Entrada aria-label="Monto" inputMode="decimal" value={g.monto} onChange={(e) => setF({ ...f, gastos: f.gastos.map((x, j) => (j === i ? { ...x, monto: e.target.value } : x)) })} />
                <Entrada aria-label="Día del mes" inputMode="numeric" value={g.dia} onChange={(e) => setF({ ...f, gastos: f.gastos.map((x, j) => (j === i ? { ...x, dia: e.target.value } : x)) })} />
                <Boton variante="fantasma" onClick={() => setF({ ...f, gastos: f.gastos.filter((_, j) => j !== i) })}>Quitar</Boton>
              </div>
            ))}
            <div className="flex gap-2"><Boton variante="secundario" onClick={() => setF({ ...f, gastos: [...f.gastos, { concepto: "", monto: "", dia: "5" }] })}>+ Gasto fijo</Boton>
              <Boton onClick={guardar}>Guardar</Boton></div>
          </div>
        </Tarjeta>
      )}
      <ComoSeCalcula>
        <p>Entradas: venta pronosticada de cada día repartida según tus medios de pago, neta de comisión, el día que se acredita cada uno; más el saldo de cuentas corrientes por su probabilidad de cobro.</p>
        <p>Salidas: órdenes de compra aprobadas o enviadas según las condiciones de pago del proveedor, compras para reponer lo que se vende (venta × (1 − margen), con el plazo de pago promedio) y tus gastos fijos. El rango sale de la incertidumbre de la venta.</p>
      </ComoSeCalcula>
    </div>
  );
}
