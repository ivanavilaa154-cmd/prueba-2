"use client";
// Ventas, rendimiento y análisis retail (sección 10): ganadores, Pareto, inflación, ticket y tráfico.
import { useEffect, useState } from "react";
import { Ganadores } from "@/components/ventas/Ganadores";
import { Impacto } from "@/components/ventas/Impacto";
import { Inflacion } from "@/components/ventas/Inflacion";
import { MediosDePago } from "@/components/ventas/MediosDePago";
import { Metas } from "@/components/ventas/Metas";
import { Pareto } from "@/components/ventas/Pareto";
import { Rentabilidad } from "@/components/ventas/Rentabilidad";
import { Ticket } from "@/components/ventas/Ticket";
import { cx } from "@/components/ui";

const PESTANAS = [
  { id: "ganadores", nombre: "Ganadores", componente: Ganadores },
  { id: "pareto", nombre: "Pareto ABC", componente: Pareto },
  { id: "inflacion", nombre: "Sin inflación", componente: Inflacion },
  { id: "ticket", nombre: "Ticket y tráfico", componente: Ticket },
  { id: "rentabilidad", nombre: "Rentabilidad del stock", componente: Rentabilidad },
  { id: "medios", nombre: "Medios de pago y fiado", componente: MediosDePago },
  { id: "metas", nombre: "Metas", componente: Metas },
  { id: "impacto", nombre: "Impacto", componente: Impacto },
];

export default function Ventas() {
  const [activa, setActiva] = useState("ganadores");
  useEffect(() => {
    const leer = () => { const id = location.hash.slice(1); if (PESTANAS.some((p) => p.id === id)) setActiva(id); };
    leer();
    window.addEventListener("hashchange", leer);
    return () => window.removeEventListener("hashchange", leer);
  }, []);
  const Actual = PESTANAS.find((p) => p.id === activa)!.componente;
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Ventas y ganadores</h1>
          <p className="text-sm text-suave">Qué productos te dejan plata, cómo venden en términos reales y cuándo viene la gente.</p>
        </div>
        <div role="tablist" className="-mx-4 flex gap-1 overflow-x-auto px-4">
          {PESTANAS.map((p) => (
            <a key={p.id} role="tab" aria-selected={activa === p.id} href={`#${p.id}`}
              className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm", activa === p.id ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>{p.nombre}</a>
          ))}
        </div>
      </div>
      <Actual />
    </div>
  );
}
