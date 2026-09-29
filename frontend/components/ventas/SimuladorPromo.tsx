"use client";
// (14) Simulador de promoción: qué pasaría antes de lanzarla.
import { useState } from "react";
import { api } from "@/lib/api";
import { numero, plata } from "@/lib/formato";
import { Aviso, Boton, Campo, Entrada, Tarjeta } from "@/components/ui";

type Prod = { producto_id: number; nombre: string; codigo: string };
type R = { producto: string; precio: number; precio_oferta: number; elasticidad: number | null; fuente_elasticidad: string; efecto_precio: number;
  efecto_exhibicion: number; promos_pasadas: number; unidades_sin_promo: number; unidades_con_promo: number; unidades_extra: number;
  limitado_por_stock: boolean; stock: number; ganancia_sin_promo: number | null; ganancia_con_promo: number | null; incremento_ganancia: number | null;
  canibalizacion: number; neto: number | null; recomendacion: string };

export function SimuladorPromo() {
  const [q, setQ] = useState("");
  const [opciones, setOpciones] = useState<Prod[]>([]);
  const [prod, setProd] = useState<Prod | null>(null);
  const [descuento, setDescuento] = useState("20");
  const [dias, setDias] = useState("7");
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function buscar() {
    const x = await api<{ filas: { producto_id: number; nombre: string; codigo: string }[] }>(`/comprar?buscar=${encodeURIComponent(q)}`).catch(() => ({ filas: [] }));
    const vistos = new Set<number>();
    setOpciones(x.filas.filter((f) => !vistos.has(f.producto_id) && vistos.add(f.producto_id)).slice(0, 8));
  }
  async function simular() {
    if (!prod) return;
    setError(null);
    try {
      setR(await api<R>("/promociones/simular", { metodo: "POST", cuerpo: { producto_id: prod.producto_id, descuento: Number(descuento) / 100, dias: Number(dias) } }));
    } catch (e) { setError(e instanceof Error ? e.message : "No se pudo simular."); }
  }
  return (
    <Tarjeta titulo="Simular una promoción antes de lanzarla">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_auto_auto_auto] sm:items-end">
        <Campo etiqueta="Producto">
          <div className="flex gap-2"><Entrada value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nombre o código" onKeyDown={(e) => e.key === "Enter" && buscar()} />
            <Boton variante="secundario" onClick={buscar}>Buscar</Boton></div>
        </Campo>
        <Campo etiqueta="Descuento %"><Entrada inputMode="numeric" value={descuento} onChange={(e) => setDescuento(e.target.value)} /></Campo>
        <Campo etiqueta="Días"><Entrada inputMode="numeric" value={dias} onChange={(e) => setDias(e.target.value)} /></Campo>
        <Boton disabled={!prod} onClick={simular}>Simular</Boton>
      </div>
      {opciones.length > 0 && !prod && (
        <ul className="mt-2 grid gap-1 text-sm">{opciones.map((o) => <li key={o.producto_id}><button className="text-acento underline" onClick={() => { setProd(o); setOpciones([]); }}>{o.nombre} ({o.codigo})</button></li>)}</ul>
      )}
      {prod && <p className="mt-2 text-sm">Producto: <strong>{prod.nombre}</strong> <button className="text-suave underline" onClick={() => { setProd(null); setR(null); }}>cambiar</button></p>}
      {error && <div className="mt-2"><Aviso tipo="error">{error}</Aviso></div>}
      {r && (
        <div className="mt-3 grid gap-2 text-sm">
          <Aviso tipo={r.neto !== null && r.neto > 0 ? "ok" : "alerta"}>{r.recomendacion}</Aviso>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <p><span className="text-suave">Precio:</span> {plata(r.precio)} → <strong>{plata(r.precio_oferta)}</strong></p>
            <p><span className="text-suave">Unidades:</span> {numero(r.unidades_sin_promo)} → <strong>{numero(r.unidades_con_promo)}</strong> ({r.unidades_extra >= 0 ? "+" : ""}{numero(r.unidades_extra)})</p>
            <p><span className="text-suave">Ganancia:</span> {plata(r.ganancia_sin_promo)} → <strong>{plata(r.ganancia_con_promo)}</strong></p>
            <p><span className="text-suave">− Canibalización estimada:</span> {plata(r.canibalizacion)}</p>
            <p><span className="text-suave">Neto:</span> <strong className={r.neto !== null && r.neto >= 0 ? "text-ok" : "text-peligro"}>{r.neto !== null && r.neto >= 0 ? "▲ " : "▼ "}{plata(r.neto)}</strong></p>
            {r.limitado_por_stock && <p className="text-alerta">▲ Limitado por el stock ({numero(r.stock)} u.)</p>}
          </div>
          <p className="text-xs text-suave">Efecto del precio ×{numero(r.efecto_precio, 2)} (sensibilidad {r.elasticidad === null ? "—" : numero(r.elasticidad, 2)}, de {r.fuente_elasticidad});
            efecto de la exhibición ×{numero(r.efecto_exhibicion, 2)} ({r.promos_pasadas ? `${r.promos_pasadas} promos parecidas` : "sin promos parecidas: no se suma"}).</p>
        </div>
      )}
    </Tarjeta>
  );
}
