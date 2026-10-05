"use client";
// Rendimiento por vendedor (SPEC v2, 12B.1 y 12B.7): ventas, margen después de descuentos, descuentos otorgados, metas con proyección
// de cierre, mix vendido contra el equipo y clientes que se le están yendo. Abajo, los objetivos de las marcas representadas.
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { PERIODOS } from "@/lib/distribuidor";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { Cifra } from "@/components/distribuidor/Cifra";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, ComoSeCalcula, Etiqueta, Selector, Tarjeta, cx } from "@/components/ui";

type Vendedor = { vendedor_id: number; vendedor: string; zona: string | null; venta: number; ganancia: number; margen: number | null; descuentos: number;
  descuento_pct: number | null; venta_anterior: number; variacion: number | null; pedidos: number; clientes: number; productos_por_cliente: number | null;
  categorias_por_cliente: number | null; meta_mes: number | null; venta_mes: number; proyeccion_mes: number; cumplimiento_proyectado: number | null;
  clientes_en_riesgo: number; clientes_perdidos: number; plata_en_riesgo_mes: number; ranking: number };
type Marca = { marca: string; tipo: string; desde: string; hasta: string; objetivo: number; logrado: number; avance: number; proyectado: number;
  bonificacion: number; en_riesgo: boolean; falta: number; mensaje: string };
type R = { desde: string; hasta: string; vendedores: Vendedor[]; equipo: { venta: number; ganancia: number; descuentos: number; margen: number | null;
  productos_por_cliente: number | null; categorias_por_cliente: number | null }; marcas: Marca[] };

const pct = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? "—" : `${numero(v * 100, d)} %`);

export default function Vendedores() {
  const [periodo, setPeriodo] = useState("mes_actual");
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<R>(`/distribuidor/vendedores?periodo=${periodo}`).then(setR).catch((e) => setError(e.message)); }, [periodo]);

  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Vendedores</h1>
          <p className="text-sm text-suave">Quién vende, con qué margen, cuánto descuenta y si llega a su meta.</p>
        </div>
        <Selector value={periodo} onChange={(e) => setPeriodo(e.target.value)} aria-label="Período">
          {PERIODOS.map(([v, n]) => <option key={v} value={v}>{n}</option>)}
        </Selector>
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {!r ? <p className="text-sm text-suave">Cargando…</p> : <>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Cifra titulo="Venta del equipo" valor={plataCorta(r.equipo.venta)} nota={`${fechaCorta(r.desde)} al ${fechaCorta(r.hasta)} · sin IVA`} />
          <Cifra titulo="Ganancia" valor={plataCorta(r.equipo.ganancia)} nota={`margen ${pct(r.equipo.margen)}`} />
          <Cifra titulo="Descuentos otorgados" valor={plataCorta(r.equipo.descuentos)} nota="sobre la lista de cada cliente" />
          <Cifra titulo="Mix promedio" valor={`${numero(r.equipo.productos_por_cliente ?? 0, 1)} productos`}
            nota={`y ${numero(r.equipo.categorias_por_cliente ?? 0, 1)} categorías por cliente`} />
        </div>
        <Tarjeta titulo="Ranking">
          <TablaDatos filas={r.vendedores} idFila={(f) => String(f.vendedor_id)} nombreArchivo="vendedores" buscador={false}
            columnas={[
              { id: "vendedor", titulo: "Vendedor", valor: (f) => f.vendedor,
                render: (f) => <div><span className="font-medium">{f.ranking}. {f.vendedor}</span><div className="text-xs text-suave">{f.zona} ·{" "}
                  <Link className="text-acento underline" href={`/mi-cartera/?vendedor=${f.vendedor_id}`}>ver su cartera</Link></div></div> },
              { id: "venta", titulo: "Venta", derecha: true, valor: (f) => f.venta,
                render: (f) => <span>{plataCorta(f.venta)}<div className={cx("text-xs", (f.variacion ?? 0) < 0 ? "text-peligro" : "text-ok")}>
                  {f.variacion === null ? "" : `${f.variacion > 0 ? "▲ +" : "▼ "}${numero(f.variacion * 100, 1)} %`}</div></span> },
              { id: "margen", titulo: "Margen", derecha: true, valor: (f) => f.margen,
                render: (f) => <span className={cx(!!r.equipo.margen && f.margen !== null && f.margen < r.equipo.margen * 0.85 && "font-semibold text-peligro")}>{pct(f.margen)}</span> },
              { id: "desc", titulo: "Descuento", derecha: true, valor: (f) => f.descuento_pct,
                render: (f) => <span>{pct(f.descuento_pct)}<div className="text-xs text-suave">{plataCorta(f.descuentos)}</div></span> },
              { id: "meta", titulo: "Meta del mes", valor: (f) => f.cumplimiento_proyectado, render: (f) => <Meta v={f} /> },
              { id: "mix", titulo: "Productos por cliente", derecha: true, ocultarEnCelular: true, valor: (f) => f.productos_por_cliente,
                render: (f) => <span>{numero(f.productos_por_cliente ?? 0, 1)}<div className="text-xs text-suave">equipo {numero(r.equipo.productos_por_cliente ?? 0, 1)}</div></span> },
              { id: "riesgo", titulo: "Clientes que se van", derecha: true, valor: (f) => f.plata_en_riesgo_mes,
                render: (f) => <span>{f.clientes_perdidos} perdidos · {f.clientes_en_riesgo} en riesgo<div className="text-xs text-peligro">{plataCorta(f.plata_en_riesgo_mes)}/mes</div></span> },
            ]} />
          <ComoSeCalcula>
            Venta: lo entregado de cada pedido (o lo pedido, si todavía está en camino), sin IVA. Margen: (venta − costo) / venta, ya con los descuentos que dio el vendedor.
            Descuento: diferencia entre la lista del cliente y el precio cobrado. Proyección: lo vendido en el mes, llevado al mes completo a este ritmo.
          </ComoSeCalcula>
        </Tarjeta>
        {r.marcas.length > 0 && (
          <Tarjeta titulo="Objetivos de marcas representadas">
            <div className="grid gap-3 md:grid-cols-3">
              {r.marcas.map((m) => (
                <div key={m.marca} className="rounded-xl border border-borde p-3">
                  <div className="flex items-center justify-between gap-2"><strong>{m.marca}</strong>
                    <Etiqueta tono={m.falta === 0 ? "ok" : m.en_riesgo ? "peligro" : "alerta"}>{m.falta === 0 ? "✓ Cumplido" : m.en_riesgo ? "● En riesgo" : "▲ En camino"}</Etiqueta></div>
                  <p className="text-xs text-suave">{m.tipo === "volumen" ? "Volumen (unidades)" : m.tipo === "cobertura" ? "Cobertura (clientes)" : "Mix (productos)"} · {fechaCorta(m.desde)} al {fechaCorta(m.hasta)}</p>
                  <div className="mt-2 h-2 rounded-full bg-panel-2" role="img" aria-label={`Avance ${numero(m.avance * 100)} %`}>
                    <div className={cx("h-2 rounded-full", m.falta === 0 ? "bg-ok" : m.en_riesgo ? "bg-peligro" : "bg-alerta")} style={{ width: `${Math.min(100, m.avance * 100)}%` }} />
                  </div>
                  <p className="mt-1 text-sm">{numero(m.logrado)} de {numero(m.objetivo)} · bonificación {plata(m.bonificacion)}</p>
                  <p className="text-xs text-suave">{m.mensaje}{m.tipo === "volumen" && m.falta > 0 ? ` A este ritmo cierra en ${numero(m.proyectado)}.` : ""}</p>
                </div>
              ))}
            </div>
          </Tarjeta>
        )}
      </>}
    </div>
  );
}

function Meta({ v }: { v: Vendedor }) {
  if (!v.meta_mes) return <span className="text-suave">Sin meta</span>;
  const avance = v.venta_mes / v.meta_mes;
  const proy = v.cumplimiento_proyectado ?? 0;
  return (
    <div className="min-w-32">
      <div className="h-2 rounded-full bg-panel-2"><div className={cx("h-2 rounded-full", proy >= 1 ? "bg-ok" : proy >= 0.9 ? "bg-alerta" : "bg-peligro")}
        style={{ width: `${Math.min(100, avance * 100)}%` }} /></div>
      <p className="text-xs">{pct(avance, 0)} de {plataCorta(v.meta_mes)}</p>
      <p className="text-xs text-suave">cierra en {pct(proy, 0)} a este ritmo</p>
    </div>
  );
}
