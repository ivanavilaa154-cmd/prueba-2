"use client";
// Sensibilidad al precio (10.10): qué productos aguantan un aumento y cuáles pierden ventas.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { numero } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, ComoSeCalcula, Tarjeta } from "@/components/ui";

type P = { producto_id: number; nombre: string; elasticidad: number | null; r2: number | null; n: number; clase: string; fuente: string; recomendacion: string };
const CLASE: Record<string, { texto: string; icono: string; color: string }> = {
  poco_sensible: { texto: "Poco sensible", icono: "▲", color: "var(--estado-bien)" }, sensible: { texto: "Sensible", icono: "●", color: "var(--estado-alerta)" },
  sin_datos: { texto: "Sin datos", icono: "–", color: "var(--gris)" },
};

export function Sensibilidad() {
  const { puede } = useSesion();
  const [r, setR] = useState<{ productos: P[]; resumen: Record<string, number> } | null>(null);
  useEffect(() => { if (puede("ver_costos")) api<typeof r>("/precios/sensibilidad").then(setR).catch(() => {}); }, [puede]);
  if (!puede("ver_costos")) return <Aviso>La sensibilidad al precio la ven el dueño y el comprador.</Aviso>;
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  return (
    <Tarjeta titulo="Cómo reacciona cada producto a los cambios de precio">
      <div className="mb-3 flex flex-wrap gap-4 text-sm">
        {Object.entries(CLASE).map(([k, c]) => <span key={k}><span style={{ color: c.color }} aria-hidden="true">{c.icono}</span> {c.texto}: {numero(r.resumen[k] ?? 0)}</span>)}
      </div>
      <TablaDatos filas={r.productos} idFila={(p) => String(p.producto_id)} nombreArchivo="sensibilidad-precio"
        columnas={[
          { id: "prod", titulo: "Producto", valor: (p) => p.nombre },
          { id: "clase", titulo: "Sensibilidad", valor: (p) => CLASE[p.clase].texto, render: (p) => <span className="whitespace-nowrap"><span aria-hidden="true" style={{ color: CLASE[p.clase].color }}>{CLASE[p.clase].icono}</span> {CLASE[p.clase].texto}</span> },
          { id: "e", titulo: "Elasticidad", valor: (p) => p.elasticidad, render: (p) => (p.elasticidad === null ? "—" : numero(p.elasticidad, 2)), derecha: true },
          { id: "fuente", titulo: "Medida con", valor: (p) => p.fuente, render: (p) => (p.fuente === "categoría" ? "su categoría" : p.fuente === "—" ? "—" : `${p.n} semanas${p.fuente === "producto y categoría" ? " + su categoría" : ""}`), ocultarEnCelular: true },
          { id: "rec", titulo: "Qué significa", valor: (p) => p.recomendacion, render: (p) => <span className="text-sm">{p.recomendacion}</span> },
        ]} />
      <div className="mt-3">
        <ComoSeCalcula>
          <p>Elasticidad: cuánto cambian las unidades cuando cambia el precio. −2 quiere decir que si el precio baja 10 %, se vende alrededor de 20 % más. Más cerca de 0 = aguanta aumentos.</p>
          <p>Se mide con las ventas semanales del último año sin promociones, con precios sin inflación y descontando la estacionalidad de la categoría. Cada producto se combina con su categoría: con pocos datos pesa más la categoría. Se usa para remarcar y para calcular el descuento de liquidación.</p>
        </ComoSeCalcula>
      </div>
    </Tarjeta>
  );
}
