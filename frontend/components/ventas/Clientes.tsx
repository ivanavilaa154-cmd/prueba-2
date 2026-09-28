"use client";
// Clientes (10.14): segmentación RFM, clientes de mayor valor y los que dejaron de venir. Solo si la caja identifica clientes.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { Aviso, ComoSeCalcula, Tabla, Tarjeta } from "@/components/ui";

type Cli = { cliente: string; ultima_compra: string; dias_sin_comprar: number; compras_180d: number; gasto_180d: string; rfm: string; segmento: string };
type R = { activo: boolean; como_activar?: string; clientes: number; segmentos: { segmento: string; nombre: string; clientes: number; gasto: string }[];
  mayor_valor: Cli[]; dejaron_de_venir: { cliente: string; dias_sin_comprar: number; compras_antes: number; gasto_antes: string }[] };
const NOMBRES: Record<string, string> = { campeones: "Campeones", leales: "Leales", nuevos: "Nuevos", ocasionales: "Ocasionales", en_riesgo: "En riesgo", perdidos: "Perdidos" };

export function Clientes() {
  const [r, setR] = useState<R | null>(null);
  useEffect(() => { api<R>("/clientes").then(setR).catch(() => {}); }, []);
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  if (!r.activo) return <Tarjeta titulo="Clientes"><Aviso>{r.como_activar}</Aviso></Tarjeta>;
  return (
    <div className="grid grid-cols-1 gap-4">
      <Tarjeta titulo={`${numero(r.clientes)} clientes identificados en los últimos 6 meses`}>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
          {r.segmentos.map((s) => (
            <div key={s.segmento} className="rounded-lg border border-borde p-3">
              <p className="text-sm font-medium">{s.nombre}</p>
              <p className="text-xl font-semibold">{numero(s.clientes)}</p>
              <p className="text-xs text-suave">{plataCorta(s.gasto)} en 6 meses</p>
            </div>
          ))}
        </div>
        <div className="mt-3">
          <ComoSeCalcula>
            <p>Cada cliente recibe de 1 a 5 puntos en recencia (hace cuánto compró), frecuencia (cuántas veces) y gasto, según en qué quinto cae. Campeones: compran seguido y hace poco. En riesgo: compraban seguido pero hace rato que no vienen.</p>
          </ComoSeCalcula>
        </div>
      </Tarjeta>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Tarjeta titulo="Dejaron de venir">
          <p className="mb-2 text-sm text-suave">Eran habituales y ya pasó el triple de su tiempo normal entre compras.</p>
          <Tabla columnas={["Cliente", "Sin comprar", "Compras antes", "Gastaba"]}>
            {r.dejaron_de_venir.map((c) => <tr key={c.cliente}><td>{c.cliente}</td><td className="text-right">{c.dias_sin_comprar} días</td><td className="text-right">{c.compras_antes}</td><td className="whitespace-nowrap text-right">{plata(c.gasto_antes)}</td></tr>)}
          </Tabla>
        </Tarjeta>
        <Tarjeta titulo="Los de mayor valor">
          <Tabla columnas={["Cliente", "Segmento", "Compras", "Gasto 6 meses", "Última"]}>
            {r.mayor_valor.map((c) => <tr key={c.cliente}><td>{c.cliente}</td><td>{NOMBRES[c.segmento]}</td><td className="text-right">{c.compras_180d}</td>
              <td className="whitespace-nowrap text-right">{plata(c.gasto_180d)}</td><td className="whitespace-nowrap">{fechaCorta(c.ultima_compra)}</td></tr>)}
          </Tabla>
        </Tarjeta>
      </div>
    </div>
  );
}
