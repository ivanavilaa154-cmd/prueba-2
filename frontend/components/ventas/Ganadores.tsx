"use client";
// 10.1 Productos ganadores: top y peores 10 por criterio, comparados con el período anterior, y rol del producto.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { parametrosFiltro } from "@/lib/consulta";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { Indicador } from "@/components/Indicador";
import { useSesion } from "@/components/Sesion";
import { Aviso, ComoSeCalcula, Selector, Tabla, Tarjeta, cx } from "@/components/ui";

type Item = { producto_id: number; nombre: string; codigo: string; categoria: string; clase_abc: string; rol: string; posicion: number;
  valor: string | number | null; valor_anterior: string | number | null; posicion_anterior: number | null; cambio: string };
type R = { periodo: { desde: string; hasta: string; desde_anterior: string; hasta_anterior: string; etiqueta: string };
  criterios: Record<string, string>; rankings: Record<string, { mejores: Item[]; peores: Item[] }>;
  resumen: Record<string, string>; roles: Record<string, number>; productos: number };

const ROLES: [string, string, string][] = [
  ["estrella", "Estrellas", "Venden mucho y dejan buen margen: cuidá que nunca falten."],
  ["iman", "Imanes", "Venden mucho con poco margen: atraen clientes, no los encarezcas."],
  ["joya", "Joyas", "Venden poco con buen margen: dales visibilidad."],
  ["peso_muerto", "Pesos muertos", "Venden poco y dejan poco: candidatos a revisar o sacar."],
];
const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

function formatear(crit: string, v: string | number | null) {
  if (v === null || v === undefined) return "—";
  if (crit === "facturacion" || crit === "ganancia") return plata(Number(v).toFixed(0));
  if (crit === "margen" || crit === "frecuencia") return `${numero(v, 1)} %`;
  if (crit === "ganancia_por_peso") return numero(v, 2);
  return numero(v, 0);
}

export function Ganadores() {
  const { filtro } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [crit, setCrit] = useState("ganancia");
  const [extra, setExtra] = useState({ dia_semana: "", franja: "" });
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setR(null);
    api<R>(`/ventas/ganadores?${parametrosFiltro(filtro, extra)}`).then(setR).catch((e) => setError(e.message));
  }, [filtro, extra]);
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const cambio = (i: Item) => i.cambio === "nuevo" ? <span className="text-acento">nuevo</span>
    : i.cambio === "sube" ? <span className="text-ok" title={`Antes estaba ${i.posicion_anterior}°`}>▲{(i.posicion_anterior ?? 0) - i.posicion}</span>
    : i.cambio === "baja" ? <span className="text-peligro" title={`Antes estaba ${i.posicion_anterior}°`}>▼{i.posicion - (i.posicion_anterior ?? 0)}</span> : <span className="text-suave">=</span>;
  const tabla = (items: Item[]) => (
    <Tabla columnas={["#", "Producto", r.criterios[crit], "Antes", "Puestos"]}>
      {items.map((i) => (
        <tr key={i.producto_id}>
          <td className="cifra text-suave">{i.posicion}</td>
          <td><span className="font-medium">{i.nombre}</span><br /><span className="text-xs text-suave">{i.categoria} · clase {i.clase_abc}</span></td>
          <td className="cifra text-right">{formatear(crit, i.valor)}</td>
          <td className="cifra text-right text-suave">{formatear(crit, i.valor_anterior)}</td>
          <td className="text-xs">{cambio(i)}</td>
        </tr>
      ))}
    </Tabla>
  );
  return (
    <div className="grid gap-4">
      <p className="text-sm text-suave">Período: {r.periodo.etiqueta} ({fechaCorta(r.periodo.desde)} a {fechaCorta(r.periodo.hasta)}), comparado con {fechaCorta(r.periodo.desde_anterior)} a {fechaCorta(r.periodo.hasta_anterior)}.</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Indicador titulo="Facturación" valor={plataCorta(r.resumen.facturacion)} actual={r.resumen.facturacion} anterior={r.resumen.facturacion_anterior} />
        <Indicador titulo="Ganancia bruta" valor={plataCorta(r.resumen.ganancia)} actual={r.resumen.ganancia} anterior={r.resumen.ganancia_anterior} />
        <Indicador titulo="Unidades" valor={numero(r.resumen.unidades, 0)} actual={r.resumen.unidades} anterior={r.resumen.unidades_anterior} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div role="tablist" aria-label="Criterio" className="flex flex-wrap gap-1">
          {Object.entries(r.criterios).map(([k, n]) => (
            <button key={k} role="tab" aria-selected={crit === k} onClick={() => setCrit(k)}
              className={cx("rounded-lg px-3 py-1.5 text-sm", crit === k ? "bg-acento text-acento-texto" : "border border-borde bg-panel")}>{n}</button>
          ))}
        </div>
        <Selector aria-label="Día de la semana" className="w-auto" value={extra.dia_semana} onChange={(e) => setExtra({ ...extra, dia_semana: e.target.value })}>
          <option value="">Todos los días</option>{DIAS.map((d, i) => <option key={d} value={i}>{d}</option>)}
        </Selector>
        <Selector aria-label="Franja horaria" className="w-auto" value={extra.franja} onChange={(e) => setExtra({ ...extra, franja: e.target.value })}>
          <option value="">Todo el día</option><option value="8-12">8 a 12 h</option><option value="12-16">12 a 16 h</option><option value="16-20">16 a 20 h</option><option value="20-24">20 a 24 h</option>
        </Selector>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Tarjeta titulo={`Los 10 mejores por ${r.criterios[crit].toLowerCase()}`}>{tabla(r.rankings[crit].mejores)}</Tarjeta>
        <Tarjeta titulo={`Los 10 peores por ${r.criterios[crit].toLowerCase()}`}>{tabla(r.rankings[crit].peores)}</Tarjeta>
      </div>
      <Tarjeta titulo="Rol de cada producto (volumen × margen)">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {ROLES.map(([k, n, d]) => (
            <div key={k} className="rounded-lg border border-borde p-3"><p className="text-2xl font-semibold">{numero(r.roles[k] ?? 0)}</p><p className="font-medium">{n}</p><p className="text-xs text-suave">{d}</p></div>
          ))}
        </div>
      </Tarjeta>
      <ComoSeCalcula>
        <p>Ganancia = lo cobrado − costo al momento de la venta. Margen = ganancia ÷ facturación. Ganancia por peso en stock = ganancia del período ÷ plata inmovilizada hoy en ese producto. Frecuencia = % de tickets que lo incluyen.</p>
        <p>El período anterior tiene la misma duración (el mes se compara con el mismo tramo del mes anterior). «Nuevo» = no estaba en el ranking anterior.</p>
        <p>Rol: se compara el volumen (unidades de 90 días) y el margen de cada producto contra la mediana de todos.</p>
      </ComoSeCalcula>
    </div>
  );
}
