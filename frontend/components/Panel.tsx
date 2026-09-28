"use client";
// Panel lateral (a pantalla completa en el celular) para ver un detalle sin perder la tabla.
import { useEffect, type ReactNode } from "react";

export function Panel({ abierto, titulo, alCerrar, children }: { abierto: boolean; titulo: ReactNode; alCerrar: () => void; children: ReactNode }) {
  useEffect(() => {
    if (!abierto) return;
    const tecla = (e: KeyboardEvent) => e.key === "Escape" && alCerrar();
    window.addEventListener("keydown", tecla);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", tecla);
      document.body.style.overflow = "";
    };
  }, [abierto, alCerrar]);
  if (!abierto) return null;
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true">
      <button className="absolute inset-0 bg-black/40" aria-label="Cerrar" onClick={alCerrar} />
      <div className="absolute inset-y-0 right-0 flex w-full max-w-3xl flex-col bg-fondo shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-borde bg-panel px-4 py-3">
          <div className="min-w-0">{titulo}</div>
          <button onClick={alCerrar} className="rounded-lg px-2 py-1 text-suave hover:bg-panel-2" aria-label="Cerrar panel">✕</button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
      </div>
    </div>
  );
}
