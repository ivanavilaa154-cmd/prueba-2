"use client";
// Clientes (10.14): segmentación RFM, clientes de mayor valor y los que dejaron de venir; valor de vida a 12 meses (19) y próxima
// compra (20). Solo si la caja identifica clientes.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { Aviso, ComoSeCalcula, Tabla, Tarjeta } from "@/components/ui";

type Cli = { cliente: string; ultima_compra: string; dias_sin_comprar: number; compras_180d: number; gasto_180d: string; rfm: string; segmento: string;
  valor_12m?: number; prob_activo?: number; compras_por_mes?: number };
type Proxima = { cliente: string; ultima_compra: string; cada_dias: number; proxima: string; entre: string; y: string; ticket_promedio: number; atrasada: boolean };
type R = { activo: boolean; como_activar?: string; clientes: number; segmentos: { segmento: string; nombre: string; clientes: number; gasto: string }[];
  mayor_valor: Cli[]; valor_de_vida: Cli[]; proximas_compras: Proxima[]; retencion_mensual: number; valor_12m_total: number; dejaron_de_venir: { cliente: string; dias_sin_comprar: number; compras_antes: number; gasto_antes: string }[] };
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
        <Tarjeta titulo="Valor de vida · próximos 12 meses">
          <p className="mb-2 text-sm text-suave">Ganancia que se espera de cada cliente en un año: {plataCorta(r.valor_12m_total)} entre todos. Retención mensual medida: {numero(r.retencion_mensual * 100)} %.</p>
          <Tabla columnas={["Cliente", "Valor 12 meses", "Sigue activo", "Compras por mes"]}>
            {r.valor_de_vida.map((c) => <tr key={c.cliente}><td>{c.cliente}</td><td className="whitespace-nowrap text-right font-semibold">{plata(c.valor_12m)}</td>
              <td className="text-right">{numero((c.prob_activo ?? 0) * 100)} %</td><td className="text-right">{numero(c.compras_por_mes, 1)}</td></tr>)}
          </Tabla>
        </Tarjeta>
        <Tarjeta titulo="Próxima compra">
          <p className="mb-2 text-sm text-suave">Quién debería volver en las próximas 2 semanas y cuándo, según su ritmo. Primero los atrasados: son a quienes conviene recordarles.</p>
          <Tabla columnas={["Cliente", "Esperada", "Rango", "Cada", "Compra promedio"]}>
            {r.proximas_compras.map((c) => <tr key={c.cliente}><td>{c.cliente}{c.atrasada && <span className="ml-1 text-xs text-alerta">▲ atrasado</span>}</td>
              <td className="whitespace-nowrap">{fechaCorta(c.proxima)}</td><td className="whitespace-nowrap text-suave">{fechaCorta(c.entre)} – {fechaCorta(c.y)}</td>
              <td className="whitespace-nowrap text-right">{c.cada_dias} días</td><td className="whitespace-nowrap text-right">{plata(c.ticket_promedio)}</td></tr>)}
          </Tabla>
        </Tarjeta>
      </div>
      <ComoSeCalcula>
        <p>Próxima compra: la última compra más la mediana de sus intervalos; el rango va del 10 % al 90 % de esos intervalos (hace falta que haya comprado 3 veces).</p>
        <p>Valor de vida: ganancia mensual promedio del último año × probabilidad de que siga activo (baja a la mitad por cada intervalo de atraso) × la retención mensual de tus clientes sumada en 12 meses.</p>
      </ComoSeCalcula>
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
