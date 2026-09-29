"use client";
// Pronósticos (predicciones con IA, parte B): venta por sucursal y canal, año y eventos, afluencia y personal.
import { useEffect, useState } from "react";
import { cx } from "@/components/ui";
import { Afluencia } from "@/components/pronosticos/Afluencia";
import { CurvaAnual } from "@/components/pronosticos/CurvaAnual";
import { VentasFuturas } from "@/components/pronosticos/VentasFuturas";

const PESTANAS = [
  { id: "ventas", nombre: "Venta por sucursal y canal", componente: VentasFuturas },
  { id: "anual", nombre: "Año y eventos", componente: CurvaAnual },
  { id: "afluencia", nombre: "Afluencia y personal", componente: Afluencia },
];

export default function Pronosticos() {
  const [activa, setActiva] = useState("ventas");
  useEffect(() => {
    const leer = () => { const id = location.hash.slice(1); if (PESTANAS.some((p) => p.id === id)) setActiva(id); };
    leer();
    window.addEventListener("hashchange", leer);
    return () => window.removeEventListener("hashchange", leer);
  }, []);
  const Actual = PESTANAS.find((p) => p.id === activa)!.componente;
  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Pronósticos</h1>
        <p className="text-sm text-suave">Cuánto vas a vender, cuándo viene la gente y cuántas cajas necesitás, con su rango de confianza.</p>
      </div>
      <div role="tablist" aria-label="Pronósticos" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1">
        {PESTANAS.map((p) => (
          <a key={p.id} role="tab" aria-selected={activa === p.id} href={`#${p.id}`}
            className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm", activa === p.id ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>{p.nombre}</a>
        ))}
      </div>
      <Actual />
    </div>
  );
}
