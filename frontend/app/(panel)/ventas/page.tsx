"use client";
// Ventas, rendimiento y análisis retail (sección 10): ganadores, Pareto, inflación, ticket y tráfico.
import { useEffect, useState } from "react";
import { Canasta } from "@/components/ventas/Canasta";
import { Clientes } from "@/components/ventas/Clientes";
import { Competencia } from "@/components/ventas/Competencia";
import { Gondola } from "@/components/ventas/Gondola";
import { Lanzamientos } from "@/components/ventas/Lanzamientos";
import { Ganadores } from "@/components/ventas/Ganadores";
import { Impacto } from "@/components/ventas/Impacto";
import { Inflacion } from "@/components/ventas/Inflacion";
import { MediosDePago } from "@/components/ventas/MediosDePago";
import { Metas } from "@/components/ventas/Metas";
import { Pareto } from "@/components/ventas/Pareto";
import { Promociones } from "@/components/ventas/Promociones";
import { Rentabilidad } from "@/components/ventas/Rentabilidad";
import { Sensibilidad } from "@/components/ventas/Sensibilidad";
import { Surtido } from "@/components/ventas/Surtido";
import { Ticket } from "@/components/ventas/Ticket";
import { cx } from "@/components/ui";
import { NoIncluido } from "@/components/NoIncluido";
import { useSesion } from "@/components/Sesion";

const PESTANAS: { id: string; nombre: string; componente: () => React.ReactNode; modulo?: string }[] = [
  { id: "ganadores", nombre: "Ganadores", componente: Ganadores },
  { id: "pareto", nombre: "Pareto ABC", componente: Pareto },
  { id: "inflacion", nombre: "Sin inflación", componente: Inflacion },
  { id: "ticket", nombre: "Ticket y tráfico", componente: Ticket },
  { id: "canasta", modulo: "completo", nombre: "Canasta", componente: Canasta },
  { id: "promociones", modulo: "completo", nombre: "Promociones", componente: Promociones },
  { id: "sensibilidad", modulo: "completo", nombre: "Sensibilidad al precio", componente: Sensibilidad },
  { id: "surtido", modulo: "completo", nombre: "Surtido", componente: Surtido },
  { id: "clientes", modulo: "completo", nombre: "Clientes", componente: Clientes },
  { id: "lanzamientos", modulo: "completo", nombre: "Lanzamientos", componente: Lanzamientos },
  { id: "competencia", modulo: "completo", nombre: "Competencia", componente: Competencia },
  { id: "gondola", modulo: "completo", nombre: "Góndola", componente: Gondola },
  { id: "rentabilidad", modulo: "avanzado", nombre: "Rentabilidad del stock", componente: Rentabilidad },
  { id: "medios", modulo: "avanzado", nombre: "Medios de pago y fiado", componente: MediosDePago },
  { id: "metas", modulo: "avanzado", nombre: "Metas", componente: Metas },
  { id: "impacto", modulo: "avanzado", nombre: "Impacto", componente: Impacto },
];

export default function Ventas() {
  const { incluye } = useSesion();
  const [activa, setActiva] = useState("ganadores");
  useEffect(() => {
    const leer = () => { const id = location.hash.slice(1); if (PESTANAS.some((p) => p.id === id)) setActiva(id); };
    leer();
    window.addEventListener("hashchange", leer);
    return () => window.removeEventListener("hashchange", leer);
  }, []);
  const actual = PESTANAS.find((p) => p.id === activa)!;
  const Actual = actual.componente;
  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Ventas y ganadores</h1>
        <p className="text-sm text-suave">Qué productos te dejan plata, cómo venden en términos reales, quién te compra y cuándo viene la gente.</p>
      </div>
      <div role="tablist" aria-label="Análisis de ventas" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1">
        {PESTANAS.map((p) => (
          <a key={p.id} role="tab" aria-selected={activa === p.id} href={`#${p.id}`}
            className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm", activa === p.id ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>
            {p.nombre}{p.modulo && !incluye(p.modulo) ? " 🔒" : ""}</a>
        ))}
      </div>
      {actual.modulo && !incluye(actual.modulo) ? <NoIncluido /> : <Actual />}
    </div>
  );
}
