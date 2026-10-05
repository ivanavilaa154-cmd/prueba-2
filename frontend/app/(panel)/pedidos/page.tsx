"use client";
// Pedidos y entregas del distribuidor (SPEC v2, 12B.5): pedidos por estado, fill rate, lo que no se facturó por faltantes de stock
// (eso mismo alimenta «Comprar y reponer») y rechazos por motivo.
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { Cifra } from "@/components/distribuidor/Cifra";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, ComoSeCalcula, Etiqueta, Selector, Tabla, Tarjeta } from "@/components/ui";

type R = { desde: string; hasta: string; fill_rate_unidades: number | null; fill_rate_lineas: number | null; no_facturado_faltantes: number;
  estados: { estado: string; n: number; total: string }[]; rechazos: { motivo: string; n: number; total: string }[];
  faltantes: { producto_id: number; producto: string; unidades: string; plata: string }[];
  recientes: { id: number; numero: string; fecha: string; estado: string; total: string; total_entregado: string; cliente: string; vendedor: string | null }[];
  tiempos: { entregas: number; dias_promedio: number | null; a_tiempo: number | null; distribucion: Record<string, number> };
  por: Record<string, { devoluciones: { nombre: string; unidades: string; plata: string; pedidos: number }[]; rechazos: { nombre: string; pedidos: number; plata: string }[] }>;
  repartidores: { id: number; nombre: string; zona: string | null; entregas: number; rechazadas: number; rechazo: number | null; dias_promedio: number | null;
    a_tiempo: number | null; devuelto: string }[]; devuelto: number };
const DIMENSIONES = [["motivo", "Motivo"], ["cliente", "Cliente"], ["producto", "Producto"], ["repartidor", "Repartidor"]] as const;
const TRAMOS_ENTREGA: [string, string][] = [["mismo_dia", "Mismo día"], ["1_dia", "Al día siguiente"], ["2_dias", "A los 2 días"], ["3_o_mas", "3 días o más"]];
const ESTADOS: Record<string, [string, "ok" | "alerta" | "peligro" | "gris" | "acento"]> = {
  tomado: ["Tomado", "acento"], preparado: ["Preparado", "acento"], despachado: ["En reparto", "acento"], entregado: ["Entregado", "ok"],
  entregado_parcial: ["Entrega parcial", "alerta"], rechazado: ["Rechazado", "peligro"], anulado: ["Anulado", "gris"],
};

export default function Pedidos() {
  const [periodo, setPeriodo] = useState("mes");
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dim, setDim] = useState<(typeof DIMENSIONES)[number][0]>("motivo");
  useEffect(() => { api<R>(`/distribuidor/pedidos?periodo=${periodo}`).then(setR).catch((e) => setError(e.message)); }, [periodo]);
  const pct = (v: number | null) => (v === null ? "—" : `${numero(v * 100, 1)} %`);
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Pedidos y entregas</h1>
          <p className="text-sm text-suave">Cuánto de lo que piden tus clientes llega y se factura, y por qué no.</p>
        </div>
        <Selector className="w-48" value={periodo} onChange={(e) => setPeriodo(e.target.value)} aria-label="Período">
          <option value="semana">Últimos 7 días</option><option value="mes">Últimos 30 días</option><option value="90d">Últimos 90 días</option>
        </Selector>
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {!r ? <p className="text-sm text-suave">Cargando…</p> : <>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Cifra titulo="Fill rate (unidades)" valor={pct(r.fill_rate_unidades)} nota="unidades entregadas / pedidas" tono={(r.fill_rate_unidades ?? 1) < 0.95 ? "peligro" : "ok"} />
          <Cifra titulo="Líneas completas" valor={pct(r.fill_rate_lineas)} nota="líneas entregadas enteras" />
          <Cifra titulo="No facturado por faltantes" valor={plataCorta(r.no_facturado_faltantes)} nota={`${fechaCorta(r.desde)} al ${fechaCorta(r.hasta)}`} tono="peligro" />
          <Cifra titulo="Pedidos" valor={numero(r.estados.reduce((s, e) => s + e.n, 0))}
            nota={r.estados.map((e) => `${e.n} ${(ESTADOS[e.estado]?.[0] ?? e.estado).toLowerCase()}`).join(" · ")} />
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          <Tarjeta titulo="Faltantes de stock que frenaron ventas" accion={<Link href="/comprar/" className="text-sm text-acento underline">Qué comprar hoy →</Link>}>
            {r.faltantes.length === 0 ? <p className="text-sm text-suave">No hubo faltantes en el período.</p> : (
              <Tabla columnas={["Producto", "Unidades", "No facturado"]} compacta>
                {r.faltantes.map((f) => (
                  <tr key={f.producto_id}><td>{f.producto}</td><td className="text-right">{numero(f.unidades)}</td><td className="whitespace-nowrap text-right">{plataCorta(Number(f.plata))}</td></tr>
                ))}
              </Tabla>
            )}
            <p className="mt-2 text-xs text-suave">Lo que tus clientes pidieron y no se entregó cuenta como demanda en «Comprar y reponer»: así el pedido sugerido no se achica por haberte quedado sin stock.</p>
          </Tarjeta>
          <Tarjeta titulo="Tiempo de entrega">
            <p className="text-sm">{r.tiempos.dias_promedio === null ? "Sin entregas en el período." : <>Los pedidos llegan en <strong>{numero(r.tiempos.dias_promedio, 1)} días</strong> en promedio;
              el <strong>{pct(r.tiempos.a_tiempo)}</strong> llega para la fecha prometida.</>}</p>
            <ul className="mt-3 grid gap-1.5 text-sm">
              {TRAMOS_ENTREGA.map(([k, n]) => {
                const v = r.tiempos.distribucion[k] ?? 0;
                return <li key={k} className="grid grid-cols-[8rem_1fr_3rem] items-center gap-2"><span>{n}</span>
                  <span className="h-2 rounded-full bg-panel-2"><span className="block h-2 rounded-full bg-acento" style={{ width: `${r.tiempos.entregas ? (v / r.tiempos.entregas) * 100 : 0}%` }} /></span>
                  <span className="text-right">{numero(v)}</span></li>;
              })}
            </ul>
          </Tarjeta>
        </div>
        <Tarjeta titulo="Repartidores">
          <Tabla columnas={["Repartidor", "Entregas", "Rechazos", "A tiempo", "Días promedio", "Devuelto en la entrega"]}>
            {r.repartidores.map((x) => (
              <tr key={x.id}><td><span className="font-medium">{x.nombre}</span><div className="text-xs text-suave">{x.zona}</div></td>
                <td className="text-right">{numero(x.entregas)}</td>
                <td className={`text-right ${(x.rechazo ?? 0) > 0.04 ? "font-semibold text-peligro" : ""}`}>{pct(x.rechazo)}</td>
                <td className={`text-right ${(x.a_tiempo ?? 1) < 0.85 ? "font-semibold text-peligro" : ""}`}>{pct(x.a_tiempo)}</td>
                <td className="text-right">{x.dias_promedio === null ? "—" : numero(x.dias_promedio, 1)}</td>
                <td className="text-right">{plata(Math.round(Number(x.devuelto)))}</td></tr>
            ))}
          </Tabla>
        </Tarjeta>
        <Tarjeta titulo={`Rechazos y devoluciones · ${plataCorta(r.devuelto)} devueltos en la entrega`} accion={
          <Selector className="w-40" value={dim} onChange={(e) => setDim(e.target.value as typeof dim)} aria-label="Ver por">
            {DIMENSIONES.map(([k, n]) => <option key={k} value={k}>Por {n.toLowerCase()}</option>)}
          </Selector>}>
          <div className="grid gap-4 lg:grid-cols-2">
            <div><h3 className="mb-1 text-sm font-semibold">Pedidos rechazados</h3>
              {dim === "producto" ? <p className="text-sm text-suave">El rechazo es del pedido entero: miralo por motivo, cliente o repartidor.</p>
                : r.por[dim].rechazos.length === 0 ? <p className="text-sm text-suave">Sin rechazos en el período.</p> : (
                <Tabla columnas={[DIMENSIONES.find(([k]) => k === dim)![1], "Pedidos", "Monto"]} compacta>
                  {r.por[dim].rechazos.map((x) => <tr key={x.nombre}><td>{x.nombre}</td><td className="text-right">{x.pedidos}</td><td className="text-right">{plataCorta(Number(x.plata))}</td></tr>)}
                </Tabla>)}
            </div>
            <div><h3 className="mb-1 text-sm font-semibold">Devuelto en la entrega</h3>
              {r.por[dim].devoluciones.length === 0 ? <p className="text-sm text-suave">Sin devoluciones en el período.</p> : (
                <Tabla columnas={[DIMENSIONES.find(([k]) => k === dim)![1], "Unidades", "Monto"]} compacta>
                  {r.por[dim].devoluciones.map((x) => <tr key={x.nombre}><td>{x.nombre}</td><td className="text-right">{numero(x.unidades)}</td><td className="text-right">{plataCorta(Number(x.plata))}</td></tr>)}
                </Tabla>)}
            </div>
          </div>
        </Tarjeta>
        <Tarjeta titulo="Últimos pedidos">
          <TablaDatos filas={r.recientes} idFila={(f) => String(f.id)} nombreArchivo="pedidos" porPagina={15}
            columnas={[
              { id: "numero", titulo: "Pedido", valor: (f) => f.numero, render: (f) => <span>{f.numero}<div className="text-xs text-suave">{fechaCorta(f.fecha)}</div></span> },
              { id: "cliente", titulo: "Cliente", valor: (f) => f.cliente },
              { id: "vendedor", titulo: "Vendedor", valor: (f) => f.vendedor, ocultarEnCelular: true },
              { id: "estado", titulo: "Estado", valor: (f) => f.estado,
                render: (f) => <Etiqueta tono={ESTADOS[f.estado]?.[1] ?? "gris"}>{ESTADOS[f.estado]?.[0] ?? f.estado}</Etiqueta> },
              { id: "total", titulo: "Pedido", derecha: true, valor: (f) => Number(f.total), render: (f) => plata(Math.round(Number(f.total))) },
              { id: "entregado", titulo: "Entregado", derecha: true, valor: (f) => Number(f.total_entregado), render: (f) => plata(Math.round(Number(f.total_entregado))) },
            ]} />
          <ComoSeCalcula>Fill rate: unidades entregadas sobre pedidas, en los pedidos ya entregados, parciales o rechazados del período. Importes sin IVA.</ComoSeCalcula>
        </Tarjeta>
      </>}
    </div>
  );
}
