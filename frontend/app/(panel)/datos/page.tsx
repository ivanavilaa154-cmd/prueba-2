"use client";
import { useEffect, useState } from "react";
import { useSesion } from "@/components/Sesion";
import { cx } from "@/components/ui";
import { Catalogo } from "@/components/datos/Catalogo";
import { Importar } from "@/components/datos/Importar";

const PESTANAS = [
  { id: "importar", nombre: "Importar archivos", permiso: "importar_datos", componente: Importar },
  { id: "catalogo", nombre: "Catálogo", permiso: "gestionar_proveedores", componente: Catalogo },
] as const;

export default function Datos() {
  const { puede } = useSesion();
  const visibles = PESTANAS.filter((p) => puede(p.permiso));
  const [activa, setActiva] = useState<string>("importar");

  useEffect(() => {
    const leer = () => {
      const id = location.hash.replace("#", "");
      if (visibles.some((p) => p.id === id)) setActiva(id);
    };
    leer();
    window.addEventListener("hashchange", leer);
    return () => window.removeEventListener("hashchange", leer);
  }, [visibles]);

  if (visibles.length === 0) return <p className="text-sm text-suave">Tu rol no tiene acceso a la carga de datos.</p>;
  const Actual = (visibles.find((p) => p.id === activa) ?? visibles[0]).componente;
  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Datos</h1>
        <p className="text-sm text-suave">Cómo llegan tus ventas, stock, productos y costos a la plataforma.</p>
      </div>
      <div role="tablist" aria-label="Carga de datos" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1">
        {visibles.map((p) => (
          <a key={p.id} role="tab" aria-selected={p.id === activa} href={`#${p.id}`}
            className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm", p.id === activa ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>
            {p.nombre}
          </a>
        ))}
      </div>
      <Actual />
    </div>
  );
}
