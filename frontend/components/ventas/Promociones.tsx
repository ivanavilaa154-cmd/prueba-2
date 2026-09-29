"use client";
// Efectividad de promociones (10.9): incremento real sobre la línea base, canibalización, rebote y resultado neto.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaCorta, numero, plata } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, ComoSeCalcula, Tabla, Tarjeta, Vacio } from "@/components/ui";
import { SimuladorPromo } from "./SimuladorPromo";

type P = { id: number; nombre: string; desde: string; hasta: string; productos: number[]; incremento_unidades: string; incremento_ganancia: string;
  canibalizacion: string; rebote: string; neto: string; recomendacion: string };

export function Promociones() {
  const { puede } = useSesion();
  const [r, setR] = useState<{ promociones: P[]; neto_total: string } | null>(null);
  useEffect(() => { if (puede("ver_costos")) api<typeof r>("/promociones/efectividad").then(setR).catch(() => {}); }, [puede]);
  if (!puede("ver_costos")) return <Aviso>La efectividad de las promociones la ven el dueño y el comprador.</Aviso>;
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  return (
    <div className="grid grid-cols-1 gap-4">
    <SimuladorPromo />
    <Tarjeta titulo={`Promociones terminadas · resultado neto ${plata(r.neto_total)}`}>
      {r.promociones.length === 0 ? <Vacio titulo="Todavía no hay promociones terminadas" /> : (
        <Tabla columnas={["Promoción", "Unidades extra", "Ganancia extra", "− Canibalización", "− Rebote", "Neto", "Qué hacer"]}>
          {r.promociones.map((p) => (
            <tr key={p.id} className="align-top">
              <td>{p.nombre}<span className="block text-xs text-suave">{fechaCorta(p.desde)} a {fechaCorta(p.hasta)} · {p.productos.length} productos</span></td>
              <td className="text-right">{Number(p.incremento_unidades) >= 0 ? "▲ " : "▼ "}{numero(p.incremento_unidades)}</td>
              <td className="whitespace-nowrap text-right">{plata(p.incremento_ganancia)}</td>
              <td className="whitespace-nowrap text-right">{plata(p.canibalizacion)}</td>
              <td className="whitespace-nowrap text-right">{plata(p.rebote)}</td>
              <td className={`whitespace-nowrap text-right font-semibold ${Number(p.neto) >= 0 ? "text-ok" : "text-peligro"}`}>{Number(p.neto) >= 0 ? "▲ " : "▼ "}{plata(Math.abs(Number(p.neto)))}</td>
              <td className="min-w-[12rem] text-sm">{p.recomendacion}</td>
            </tr>
          ))}
        </Tabla>
      )}
      <div className="mt-3">
        <ComoSeCalcula>
          <p>Línea base: lo que se vendía por día en las 4 semanas anteriores, por los días de la promoción. Unidades y ganancia extra = lo vendido en la promo − la línea base.</p>
          <p>Canibalización: lo que dejaron de vender los otros productos de la misma subcategoría. Rebote: la caída de las 2 semanas siguientes. Neto = ganancia extra − canibalización − rebote.</p>
        </ComoSeCalcula>
      </div>
    </Tarjeta>
    </div>
  );
}
