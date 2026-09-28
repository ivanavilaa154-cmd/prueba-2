"use client";
// Análisis de canasta (10.5): qué se compra junto, productos arrastre y sugerencias de combos y ubicación en góndola.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { numero, plata } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, ComoSeCalcula, Selector, Tabla, Tarjeta } from "@/components/ui";

type Regla = { si_compra: string; tambien: string; tickets_juntos: number; soporte: number; confianza: number; lift: number; texto: string };
type R = { suficiente: boolean; tickets: number; minimo?: number; reglas: Regla[]; ticket_promedio?: string;
  arrastre: { producto_id: number; nombre: string; presencia: number; ticket_vs_promedio: number; ticket_promedio: string }[];
  sugerencias: { tipo: string; texto: string }[] };

export function Canasta() {
  const { yo } = useSesion();
  const [ubic, setUbic] = useState("");
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setR(null); api<R>(`/ventas/canasta${ubic ? `?ubicacion_id=${ubic}` : ""}`).then(setR).catch((e) => setError(e.message)); }, [ubic]);
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  return (
    <div className="grid grid-cols-1 gap-4">
      <Tarjeta titulo="Qué se compra junto · últimos 90 días" accion={
        <Selector className="w-52" value={ubic} onChange={(e) => setUbic(e.target.value)} aria-label="Sucursal">
          <option value="">Todas las sucursales</option>{yo?.ubicaciones.filter((u) => u.tipo !== "deposito").map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
        </Selector>}>
        {!r ? <p className="text-sm text-suave">Cargando…</p> : !r.suficiente ? (
          <Aviso>Hace falta más historial: hay {numero(r.tickets)} tickets y se necesitan al menos {numero(r.minimo ?? 500)} para que las asociaciones sean confiables.</Aviso>
        ) : (
          <>
            <ul className="grid gap-2">
              {r.reglas.slice(0, 12).map((x, i) => (
                <li key={i} className="rounded-lg border border-borde p-3 text-sm">
                  {x.texto}
                  <span className="mt-1 block text-xs text-suave">{numero(x.tickets_juntos)} tickets juntos · soporte {numero(x.soporte * 100, 2)} % · lift {numero(x.lift, 1)}</span>
                </li>
              ))}
            </ul>
            <div className="mt-3">
              <ComoSeCalcula>
                <p>Confianza: de los tickets que tienen el primer producto, cuántos tienen también el segundo. Lift: cuántas veces más probable es llevar el segundo si se lleva el primero (1 = da lo mismo).</p>
                <p>Soporte: en qué parte de todos los tickets aparecen juntos. Se analizan {numero(r.tickets)} tickets.</p>
              </ComoSeCalcula>
            </div>
          </>
        )}
      </Tarjeta>
      {r?.suficiente && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Tarjeta titulo="Productos arrastre">
            <p className="mb-2 text-sm text-suave">Están en muchos tickets y esos tickets son más grandes que el promedio ({plata(r.ticket_promedio)}): no pueden faltar.</p>
            <Tabla columnas={["Producto", "En tickets", "Ticket con el producto"]}>
              {r.arrastre.map((a) => (
                <tr key={a.producto_id}><td>{a.nombre}</td><td className="text-right">{numero(a.presencia * 100, 1)} %</td>
                  <td className="whitespace-nowrap text-right">{plata(a.ticket_promedio)} <span className="text-xs text-suave">(×{numero(a.ticket_vs_promedio, 2)})</span></td></tr>
              ))}
            </Tabla>
          </Tarjeta>
          <Tarjeta titulo="Ideas para vender más">
            <ul className="grid gap-2 text-sm">{r.sugerencias.map((s, i) => <li key={i}>{s.tipo === "combo" ? "🛒" : "📍"} {s.texto}</li>)}</ul>
          </Tarjeta>
        </div>
      )}
    </div>
  );
}
