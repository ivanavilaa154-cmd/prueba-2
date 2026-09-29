"use client";
// Finanzas (predicciones 40 y 41): flujo de caja proyectado y riesgo de cobro.
import { useEffect, useState } from "react";
import { cx } from "@/components/ui";
import { FlujoCaja } from "@/components/finanzas/FlujoCaja";
import { RiesgoCobro } from "@/components/finanzas/RiesgoCobro";

const PESTANAS = [{ id: "flujo", nombre: "Flujo de caja", componente: FlujoCaja }, { id: "cobro", nombre: "Riesgo de cobro", componente: RiesgoCobro }];

export default function Finanzas() {
  const [activa, setActiva] = useState("flujo");
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
        <h1 className="text-2xl font-semibold">Finanzas</h1>
        <p className="text-sm text-suave">Cuánta plata vas a tener en los próximos 90 días y qué deuda de clientes está en riesgo.</p>
      </div>
      <div role="tablist" aria-label="Finanzas" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1">
        {PESTANAS.map((p) => (
          <a key={p.id} role="tab" aria-selected={activa === p.id} href={`#${p.id}`}
            className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm", activa === p.id ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>{p.nombre}</a>
        ))}
      </div>
      <Actual />
    </div>
  );
}
