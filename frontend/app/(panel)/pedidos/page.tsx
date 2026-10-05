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
  recientes: { id: number; numero: string; fecha: string; estado: string; total: string; total_entregado: string; cliente: string; vendedor: string | null }[] };
const ESTADOS: Record<string, [string, "ok" | "alerta" | "peligro" | "gris" | "acento"]> = {
  tomado: ["Tomado", "acento"], preparado: ["Preparado", "acento"], despachado: ["En reparto", "acento"], entregado: ["Entregado", "ok"],
  entregado_parcial: ["Entrega parcial", "alerta"], rechazado: ["Rechazado", "peligro"], anulado: ["Anulado", "gris"],
};

export default function Pedidos() {
  const [periodo, setPeriodo] = useState("mes");
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<R>(`/distribuidor/pedidos?periodo=${periodo}`).then(setR).catch((e) => setError(e.message)); }, [periodo]);
  const pct = (v: number | null) => (v === null ? "—" : `${numero(v * 100, 1)} %`);
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Pedidos y entregas</h1>
          <p className="text-sm text-suave">Cuánto de lo que piden tus clientes llega y se factura, y por qué no.</p>
        </div>
        <Selector value={periodo} onChange={(e) => setPeriodo(e.target.value)} aria-label="Período">
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
              <Tabla columnas={["Producto", "Unidades", "No facturado"]}>
                {r.faltantes.map((f) => (
                  <tr key={f.producto_id}><td>{f.producto}</td><td className="text-right">{numero(f.unidades)}</td><td className="text-right">{plata(Math.round(Number(f.plata)))}</td></tr>
                ))}
              </Tabla>
            )}
            <p className="mt-2 text-xs text-suave">Lo que tus clientes pidieron y no se entregó cuenta como demanda en «Comprar y reponer»: así el pedido sugerido no se achica por haberte quedado sin stock.</p>
          </Tarjeta>
          <Tarjeta titulo="Rechazos en la entrega">
            {r.rechazos.length === 0 ? <p className="text-sm text-suave">No hubo rechazos en el período.</p> : (
              <Tabla columnas={["Motivo", "Pedidos", "Monto"]}>
                {r.rechazos.map((x) => <tr key={x.motivo}><td>{x.motivo}</td><td className="text-right">{x.n}</td><td className="text-right">{plata(Math.round(Number(x.total)))}</td></tr>)}
              </Tabla>
            )}
          </Tarjeta>
        </div>
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
