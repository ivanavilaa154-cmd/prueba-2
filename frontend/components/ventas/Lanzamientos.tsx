"use client";
// (26) Éxito de un lanzamiento: productos nuevos de los últimos 120 días, cuánto van a vender a los 90 días y si llegan a vender
// como un producto normal de su categoría.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaCorta, numero, plataCorta } from "@/lib/formato";
import { ComoSeCalcula, Etiqueta, Tabla, Tarjeta, Vacio } from "@/components/ui";

type L = { producto_id: number; producto: string; codigo: string; categoria: string; lanzado: string; dias: number; vendidas: number; facturado: number;
  venta_diaria: number; tendencia: number; venta_diaria_90: number; objetivo_categoria: number | null; unidades_90: number; unidades_90_min: number;
  unidades_90_max: number; prob_exito: number | null; veredicto: string; accion: string };
const VEREDICTO: Record<string, [string, "ok" | "alerta" | "peligro" | "gris"]> = {
  va_bien: ["✓ Va bien", "ok"], en_duda: ["▲ En duda", "alerta"], no_despega: ["● No despega", "peligro"], sin_referencia: ["Sin referencia", "gris"],
};

export function Lanzamientos() {
  const [r, setR] = useState<{ lanzamientos: L[] } | null>(null);
  useEffect(() => { api<{ lanzamientos: L[] }>("/lanzamientos").then(setR).catch(() => {}); }, []);
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  if (!r.lanzamientos.length) return <Vacio titulo="No hay lanzamientos recientes">Cuando empieces a vender un producto nuevo, acá vas a ver si despega.</Vacio>;
  return (
    <div className="grid grid-cols-1 gap-4">
      <Tarjeta titulo="Productos lanzados en los últimos 120 días">
        <Tabla columnas={["Producto", "Lanzado", "Vendidas", "Venta por día", "A los 90 días", "Rango 80 %", "Probabilidad de éxito", "Qué hacer"]}>
          {r.lanzamientos.map((l) => (
            <tr key={l.producto_id}>
              <td><span className="font-medium">{l.producto}</span><br /><span className="text-xs text-suave">{l.categoria} · {plataCorta(l.facturado)} facturado</span></td>
              <td className="whitespace-nowrap">{fechaCorta(l.lanzado)}<br /><span className="text-xs text-suave">hace {l.dias} días</span></td>
              <td className="text-right">{numero(l.vendidas)}</td>
              <td className="whitespace-nowrap text-right">{numero(l.venta_diaria, 1)}<br /><span className="text-xs text-suave">su categoría: {l.objetivo_categoria === null ? "—" : numero(l.objetivo_categoria, 1)}</span></td>
              <td className="text-right font-semibold">{numero(l.unidades_90)} u.</td>
              <td className="whitespace-nowrap text-right text-suave">{numero(l.unidades_90_min)} – {numero(l.unidades_90_max)}</td>
              <td className="whitespace-nowrap"><Etiqueta tono={VEREDICTO[l.veredicto][1]}>{VEREDICTO[l.veredicto][0]}</Etiqueta>
                {l.prob_exito !== null && <span className="ml-1 text-sm">{numero(l.prob_exito * 100)} %</span>}</td>
              <td className="text-sm">{l.accion}</td>
            </tr>
          ))}
        </Tabla>
      </Tarjeta>
      <ComoSeCalcula>
        <p>Venta por día de las últimas 2 semanas, ajustada por su tendencia (comparada con las 2 semanas anteriores), proyectada hasta cumplir 90 días.</p>
        <p>Éxito: vender al menos como el producto que está en el 40 % de su categoría (la mayoría de los productos establecidos de la categoría venden más que eso).
          La probabilidad sale del rango de su venta diaria; con pocos días el rango es más ancho.</p>
      </ComoSeCalcula>
    </div>
  );
}
