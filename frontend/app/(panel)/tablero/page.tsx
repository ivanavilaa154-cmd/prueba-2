"use client";
// Mi tablero (predicciones, parte D): una vista por rol con los mismos bloques —indicadores, avisos por plata en juego,
// pronóstico con rango, detalle y atajos—. Pensada primero para el celular (la de Sucursal se usa en la góndola).
import Link from "next/link";
import { useEffect, useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { fecha, numero, plataCorta } from "@/lib/formato";
import { TarjetaAviso, type AvisoDatos } from "@/components/Aviso";
import { Aviso, ComoSeCalcula, Selector, Tabla, Tarjeta, Vacio, cx } from "@/components/ui";

type Kpi = { nombre: string; valor: number | string | null; formato: string; detalle: string | null; variacion: number | null; bueno_si_sube: boolean };
type Punto = { fecha: string; real?: number; pronostico?: number; rango?: [number, number] };
type Vista = { vista: string; nombre: string; hoy: string; vistas: { codigo: string; nombre: string }[]; kpis: Kpi[]; alertas: AvisoDatos[];
  ubicacion: { elegida: { id: number; nombre: string }; opciones: { id: number; nombre: string }[] } | null;
  pronostico: { titulo: string; medida: string; puntos: Punto[]; total: number; minimo: number; maximo: number; linea_minimo?: number } | null;
  detalle: { titulo: string; columnas: string[]; filas: Record<string, string | number | null>[] } | null;
  atajos: { etiqueta: string; ruta: string }[]; bloqueado?: string };

function valorKpi(k: Kpi): string {
  if (k.valor === null || k.valor === undefined) return "—";
  if (k.formato === "numero") return numero(k.valor);
  if (k.formato === "pct") return `${numero(k.valor, 1)} %`;
  if (k.formato === "fecha") return fecha(String(k.valor));
  return plataCorta(k.valor);
}

function detalleKpi(k: Kpi): string | null {
  // El rango llega en pesos crudos desde el servidor: se muestra abreviado.
  const m = k.detalle?.match(/^rango 80 %: (-?\d+) a (-?\d+)$/);
  if (m) return `entre ${plataCorta(m[1])} y ${plataCorta(m[2])} (80 %)`;
  const d = k.detalle?.match(/^de (-?\d+) (.*)$/);
  if (d) return `de ${plataCorta(d[1])} ${d[2]}`;
  return k.detalle;
}

function TarjetaKpi({ k }: { k: Kpi }) {
  const v = k.variacion;
  const bueno = v !== null && (k.bueno_si_sube ? v > 0 : v < 0);
  const puntos = k.formato === "pct";
  return (
    <div className="rounded-xl border border-borde bg-panel p-4">
      <p className="text-sm text-suave">{k.nombre}</p>
      <p className="cifra mt-1 text-2xl font-semibold">{valorKpi(k)}</p>
      {v !== null && (
        <p className={cx("mt-1 text-xs", Math.abs(v) < 0.5 ? "text-suave" : bueno ? "text-ok" : "text-peligro")}>
          {v > 0 ? "▲" : v < 0 ? "▼" : "="} {v > 0 ? "+" : ""}{numero(v, 1)}{puntos ? " pp" : " %"}
        </p>
      )}
      {detalleKpi(k) && <p className="mt-1 text-xs text-suave">{detalleKpi(k)}</p>}
    </div>
  );
}

function celda(col: string, x: string | number | null) {
  if (x === null || x === undefined) return "—";
  if (typeof x === "number") {
    if (/%/.test(col)) return `${x > 0 && /Variación/.test(col) ? "+" : ""}${numero(x, Number.isInteger(x) ? 0 : 1)}`;
    if (/Venta|Saldo|riesgo$|En riesgo/.test(col)) return plataCorta(x);
    return numero(x, Number.isInteger(x) ? 0 : 1);
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(x)) return fecha(x);
  return x;
}

export default function Tablero() {
  const [lista, setLista] = useState<{ codigo: string; nombre: string }[] | null>(null);
  const [activa, setActiva] = useState<string | null>(null);
  const [ubicacion, setUbicacion] = useState<number | null>(null);
  const [v, setV] = useState<Vista | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ vistas: { codigo: string; nombre: string }[]; por_defecto: string | null }>("/vistas").then((r) => {
      setLista(r.vistas);
      const pedida = location.hash.slice(1);
      setActiva(r.vistas.some((x) => x.codigo === pedida) ? pedida : r.por_defecto && r.vistas.some((x) => x.codigo === r.por_defecto) ? r.por_defecto : r.vistas[0]?.codigo ?? null);
    }).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!activa) return;
    setV(null); setError(null);
    history.replaceState(null, "", `#${activa}`);
    api<Vista>(`/vistas/${activa}${activa === "sucursal" && ubicacion ? `?ubicacion_id=${ubicacion}` : ""}`).then(setV).catch((e) => setError(e.message));
  }, [activa, ubicacion]);

  if (lista && lista.length === 0) return <Vacio titulo="Tu rol no tiene un tablero">Usá las secciones del menú.</Vacio>;
  const p = v?.pronostico;
  const datos = (p?.puntos ?? []).map((x) => ({ ...x, etiqueta: fecha(x.fecha).slice(0, 5) }));
  const tinta = p?.medida === "tickets" ? (n: number) => numero(n) : (n: number) => plataCorta(n);
  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Mi tablero</h1>
        <p className="text-sm text-suave">Lo que tenés que mirar hoy según tu función: indicadores, avisos por plata en juego y lo que viene, con su rango.</p>
      </div>
      {lista && lista.length > 1 && (
        <div role="tablist" aria-label="Vistas" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1">
          {lista.map((x) => (
            <button key={x.codigo} role="tab" aria-selected={activa === x.codigo} onClick={() => setActiva(x.codigo)}
              className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm", activa === x.codigo ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>{x.nombre}</button>
          ))}
        </div>
      )}
      {error && <Aviso tipo="error">{error}</Aviso>}
      {!v && !error && <p className="text-sm text-suave">Cargando…</p>}
      {v && <>
        {v.ubicacion && v.ubicacion.opciones.length > 1 && (
          <Selector aria-label="Sucursal" value={v.ubicacion.elegida.id} onChange={(e) => setUbicacion(Number(e.target.value))}>
            {v.ubicacion.opciones.map((o) => <option key={o.id} value={o.id}>{o.nombre}</option>)}
          </Selector>
        )}
        {v.bloqueado && <Aviso tipo="info">{v.bloqueado} <Link className="underline" href="/configuracion/#plan">Ver planes</Link></Aviso>}
        {v.kpis.length > 0 && <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{v.kpis.map((k) => <TarjetaKpi key={k.nombre} k={k} />)}</div>}
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
          <div className="grid min-w-0 grid-cols-1 content-start gap-3 xl:col-span-2">
            <h2 className="font-semibold">Avisos por plata en juego</h2>
            {v.alertas.length === 0 ? <Vacio titulo="Sin avisos abiertos">Nada urgente para esta vista.</Vacio>
              : v.alertas.map((a) => <TarjetaAviso key={a.id} a={a} compacto />)}
            <Link href="/avisos/" className="text-sm text-acento underline">Ver todos los avisos</Link>
          </div>
          <div className="grid min-w-0 grid-cols-1 content-start gap-4 xl:col-span-3">
            {p && p.puntos.length > 0 && (
              <Tarjeta titulo={p.titulo}>
                <div className="h-64">
                  <ResponsiveContainer>
                    <ComposedChart data={datos} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
                      <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
                      <XAxis dataKey="etiqueta" tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" interval="preserveStartEnd" />
                      <YAxis tickFormatter={tinta} width={64} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
                      <Tooltip formatter={(x, n) => [Array.isArray(x) ? `${tinta(Number(x[0]))} a ${tinta(Number(x[1]))}` : tinta(Number(x)),
                        n === "rango" ? "Rango 80 %" : n === "real" ? "Real" : "Pronóstico"]} />
                      {p.linea_minimo ? <ReferenceLine y={p.linea_minimo} stroke="var(--estado-critico)" strokeDasharray="4 3" /> : null}
                      <Area dataKey="rango" stroke="none" fill="var(--serie-1)" fillOpacity={0.15} isAnimationActive={false} />
                      <Line dataKey="real" stroke="var(--grafico-tinta)" strokeWidth={2} dot={false} isAnimationActive={false} />
                      <Line dataKey="pronostico" stroke="var(--serie-1)" strokeWidth={2} strokeDasharray="5 3" dot={false} isAnimationActive={false} />
                    </ComposedChart>
                  </ResponsiveContainer>
                </div>
                <p className="mt-1 text-xs text-suave">
                  {p.medida === "saldo" ? "Saldo proyectado" : "Total proyectado"}: <strong>{tinta(p.total)}</strong> (entre {tinta(p.minimo)} y {tinta(p.maximo)}, 80 %).
                  {p.medida !== "saldo" && " Línea llena: real. Punteada: pronóstico."}
                </p>
              </Tarjeta>
            )}
            {v.detalle && (
              <Tarjeta titulo={v.detalle.titulo}>
                {v.detalle.filas.length === 0 ? <p className="text-sm text-suave">Nada para mostrar.</p> : (
                  <Tabla columnas={v.detalle.columnas}>
                    {v.detalle.filas.map((f, i) => (
                      <tr key={i}>{v.detalle!.columnas.map((c, j) => (
                        <td key={c} className={cx(j > 0 && typeof f[c] === "number" && "text-right", j === 0 && "font-medium")}>{celda(c, f[c])}</td>
                      ))}</tr>
                    ))}
                  </Tabla>
                )}
              </Tarjeta>
            )}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {v.atajos.map((a) => (
                <Link key={a.ruta} href={a.ruta} className="rounded-lg border border-borde bg-panel px-3 py-3 text-center text-sm font-medium hover:bg-panel-2">{a.etiqueta}</Link>
              ))}
            </div>
          </div>
        </div>
        <ComoSeCalcula>
          <p>Cada vista usa los mismos cálculos que el resto de la plataforma: los avisos se ordenan por la plata que está en juego, el pronóstico es el de
            Pronósticos (con rango del 80 %) y los indicadores comparan contra el período anterior de igual largo.</p>
          <p>Dirección: toda la empresa. Comercial: quiebres, categorías y plata parada. Sucursal: tu local, para usar en el celular. Marketing: tráfico,
            ticket y promociones. Finanzas: caja a 90 días y cuentas corrientes.</p>
        </ComoSeCalcula>
      </>}
    </div>
  );
}
