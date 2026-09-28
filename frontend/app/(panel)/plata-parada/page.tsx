"use client";
// Dónde está parada la plata (sección 9): capital en stock, sobrestock, stock muerto, lo que dejó de venderse y merma.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Indicador } from "@/components/Indicador";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, Boton, Campo, ComoSeCalcula, Entrada, Selector, Tabla, Tarjeta, cx } from "@/components/ui";

type Estado = "sano" | "sobrestock" | "muerto";
type Item = { producto_id: number; ubicacion_id: number; nombre: string; codigo_interno: string; ubicacion: string; categoria: string | null;
  proveedor: string | null; disponible: string; dias_stock: string | null; dias_sin_venta: number | null; capital: string | null; tendencia: string | null;
  estado: Estado; costo: string | null; precio: string | null; recomendacion: string; causas: string[];
  variaciones: { ultimos_30_vs_anteriores?: number | null; mes_vs_anio_anterior?: number | null; "4_semanas_vs_3_meses"?: number | null } };
type Fila = { nombre: string; sano: string; sobrestock: string; muerto: string; total: string };
type R = { umbrales: { sobrestock: number; muerto: number };
  tarjetas: { plata_parada: string; capital_total: string; cobertura_dias: number | null; riesgo_vencimiento_mes: string; dejaron_de_venderse: number;
    ofertas_sugeridas: number; plata_recuperable: string };
  distribucion: Record<Estado, { capital: string; productos: number }>; sin_ventas: { dias: number; productos: number; capital: string }[];
  por_categoria: Fila[]; por_proveedor: Fila[]; por_ubicacion: Fila[]; items: Item[] };
type Merma = { total: string; por_producto: { nombre: string; unidades: string; costo: string }[]; por_categoria: { nombre: string; costo: string }[];
  por_ubicacion: { nombre: string; costo: string }[]; por_proveedor: { nombre: string; costo: string }[]; mensual: { mes: string; vencimiento: string; merma: string }[] };

const ESTADOS: Record<Estado, { texto: string; icono: string; color: string }> = {
  sano: { texto: "Sano", icono: "✓", color: "var(--estado-bien)" },
  sobrestock: { texto: "Sobrestock", icono: "▲", color: "var(--estado-alerta)" },
  muerto: { texto: "Stock muerto", icono: "✕", color: "var(--estado-critico)" },
};
const TENDENCIA: Record<string, string> = { creciendo: "▲ Creciendo", estable: "= Estable", cayendo: "▼ Cayendo", muerto: "✕ Sin ventas" };

function EstadoStock({ valor }: { valor: Estado }) {
  const e = ESTADOS[valor];
  return <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm"><span aria-hidden="true" style={{ color: e.color }}>{e.icono}</span>{e.texto}</span>;
}

function pct(v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  return `${v > 0 ? "▲ +" : v < 0 ? "▼ " : "= "}${numero(v * 100, 0)} %`;
}

function Distribucion({ d }: { d: R["distribucion"] }) {
  const total = (Object.keys(ESTADOS) as Estado[]).reduce((s, e) => s + Number(d[e].capital), 0) || 1;
  return (
    <div>
      <div className="flex h-7 w-full gap-0.5 overflow-hidden rounded-md" role="img" aria-label="Distribución del capital en stock">
        {(Object.keys(ESTADOS) as Estado[]).map((e) => Number(d[e].capital) > 0 && (
          <div key={e} title={`${ESTADOS[e].texto}: ${plata(d[e].capital)}`} style={{ width: `${(Number(d[e].capital) / total) * 100}%`, background: ESTADOS[e].color }} />
        ))}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        {(Object.keys(ESTADOS) as Estado[]).map((e) => (
          <div key={e} className="text-sm">
            <EstadoStock valor={e} />
            <div className="font-semibold">{plata(d[e].capital)} <span className="font-normal text-suave">· {numero((Number(d[e].capital) / total) * 100, 0)} %</span></div>
            <div className="text-xs text-suave">{numero(d[e].productos)} productos × sucursal</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RegistrarMerma({ alGuardar }: { alGuardar: () => void }) {
  const { yo } = useSesion();
  const [q, setQ] = useState("");
  const [opciones, setOpciones] = useState<{ id: number; nombre: string; codigo_interno: string }[]>([]);
  const [datos, setDatos] = useState({ producto_id: 0, ubicacion_id: yo?.ubicaciones[0]?.id ?? 0, cantidad: "", motivo: "vencimiento", detalle: "" });
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  useEffect(() => {
    if (q.trim().length < 2) return setOpciones([]);
    const t = setTimeout(() => api<typeof opciones>(`/catalogo/buscar?q=${encodeURIComponent(q)}`).then(setOpciones).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [q]);
  async function guardar() {
    try {
      const r = await api<{ costo: string | null }>("/merma", { metodo: "POST", cuerpo: { ...datos, cantidad: Number(datos.cantidad.replace(",", ".")), detalle: datos.detalle || null } });
      setMensaje({ tipo: "ok", texto: `Merma registrada${r.costo ? ` (${plata(r.costo)} a costo)` : ""}. Se descontó del stock.` });
      setDatos({ ...datos, producto_id: 0, cantidad: "", detalle: "" });
      setQ("");
      alGuardar();
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo guardar." });
    }
  }
  return (
    <div className="grid gap-3">
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Campo etiqueta="Producto">
          <Entrada placeholder="Buscar por nombre o código" value={q} onChange={(e) => { setQ(e.target.value); setDatos({ ...datos, producto_id: 0 }); }} />
          {opciones.length > 0 && !datos.producto_id && (
            <ul className="max-h-40 overflow-auto rounded-lg border border-borde bg-panel text-sm">
              {opciones.map((o) => <li key={o.id}><button className="w-full px-2 py-1 text-left hover:bg-panel-2" onClick={() => { setDatos({ ...datos, producto_id: o.id }); setQ(o.nombre); }}>{o.nombre}</button></li>)}
            </ul>
          )}
        </Campo>
        <Campo etiqueta="Sucursal">
          <Selector value={datos.ubicacion_id} onChange={(e) => setDatos({ ...datos, ubicacion_id: Number(e.target.value) })}>
            {yo?.ubicaciones.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
          </Selector>
        </Campo>
        <Campo etiqueta="Cantidad"><Entrada inputMode="decimal" value={datos.cantidad} onChange={(e) => setDatos({ ...datos, cantidad: e.target.value })} /></Campo>
        <Campo etiqueta="Motivo">
          <Selector value={datos.motivo} onChange={(e) => setDatos({ ...datos, motivo: e.target.value })}>
            <option value="vencimiento">Vencido</option><option value="rotura">Roto</option><option value="robo">Robo</option><option value="otro">Otro</option>
          </Selector>
        </Campo>
      </div>
      <div><Boton disabled={!datos.producto_id || !datos.cantidad} onClick={guardar}>Registrar merma</Boton></div>
    </div>
  );
}

export default function PlataParada() {
  const { filtro, puede } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [merma, setMerma] = useState<Merma | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [vista, setVista] = useState<"categoria" | "proveedor" | "ubicacion">("categoria");
  const [estado, setEstado] = useState<"todos" | Estado>("todos");
  const [mensaje, setMensaje] = useState<string | null>(null);
  const ubic = filtro.ubicaciones.length ? `ubicaciones=${filtro.ubicaciones.join(",")}` : "";
  const cargar = useCallback(() => {
    api<R>(`/plata-parada?${ubic}`).then(setR).catch((e) => setError(e.message));
    api<Merma>(`/merma?${ubic}`).then(setMerma).catch(() => {});
  }, [ubic]);
  useEffect(() => { setR(null); cargar(); }, [cargar]);

  async function ofertar(i: Item, tipo: "segunda_unidad" | "liquidacion") {
    const hasta = new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10);
    const descuento = tipo === "liquidacion" && i.costo && i.precio ? Math.max(0.05, Math.min(0.6, 1 - Number(i.costo) / Number(i.precio))) : 0.5;
    try {
      const o = await api<{ nombre: string; precio_oferta: string }>("/ofertas", { metodo: "POST", cuerpo: {
        producto_id: i.producto_id, ubicacion_id: i.ubicacion_id, descuento: Math.round(descuento * 100) / 100, hasta,
        origen: tipo === "liquidacion" ? "liquidacion" : "sobrestock", tipo: tipo === "liquidacion" ? "descuento_pct" : "segunda_unidad" } });
      setMensaje(`Oferta creada: ${o.nombre} (${plata(o.precio_oferta)}). Imprimí el cartel desde Vencimientos y ofertas.`);
    } catch (e) {
      setMensaje(e instanceof Error ? e.message : "No se pudo crear la oferta.");
    }
  }

  const items = r ? r.items.filter((i) => estado === "todos" || i.estado === estado) : [];
  const tabla = r ? { categoria: r.por_categoria, proveedor: r.por_proveedor, ubicacion: r.por_ubicacion }[vista] : [];
  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Plata parada</h1>
        <p className="text-sm text-suave">Cuánta plata tenés en mercadería que no se vende a tiempo, dónde está y qué hacer con ella.</p>
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {mensaje && <Aviso tipo="ok">{mensaje}</Aviso>}
      {!r ? !error && <p className="text-sm text-suave">Cargando…</p> : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Indicador titulo="Plata parada" valor={plataCorta(r.tarjetas.plata_parada)} nota={`sobrestock + stock muerto, de ${plataCorta(r.tarjetas.capital_total)} en stock`} />
            <Indicador titulo="Cobertura del stock" valor={r.tarjetas.cobertura_dias ? `${numero(r.tarjetas.cobertura_dias)} días` : "—"} nota="al ritmo de venta de los últimos 30 días" />
            <Link href="/vencimientos/" className="block"><Indicador titulo="Riesgo de vencimiento este mes" valor={plataCorta(r.tarjetas.riesgo_vencimiento_mes)} nota="mercadería que vence sin venderse →" /></Link>
            <Link href="/vencimientos/" className="block"><Indicador titulo="Ofertas sugeridas hoy" valor={numero(r.tarjetas.ofertas_sugeridas)} nota={`recuperan ${plataCorta(r.tarjetas.plata_recuperable)} →`} /></Link>
          </div>
          <Tarjeta titulo="Cómo está el capital en stock">
            <Distribucion d={r.distribucion} />
            <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
              <span className="text-suave">Ver por:</span>
              {(["categoria", "proveedor", "ubicacion"] as const).map((v) => (
                <button key={v} onClick={() => setVista(v)} className={cx("rounded-lg px-3 py-1", vista === v ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>
                  {{ categoria: "Categoría", proveedor: "Proveedor", ubicacion: "Sucursal" }[v]}
                </button>
              ))}
            </div>
            <div className="mt-2">
              <Tabla columnas={["", "Sano", "Sobrestock", "Stock muerto", "Total"]}>
                {tabla.slice(0, 12).map((f) => (
                  <tr key={f.nombre}><td>{f.nombre}</td>{(["sano", "sobrestock", "muerto", "total"] as const).map((k) => <td key={k} className="whitespace-nowrap text-right">{plata(f[k])}</td>)}</tr>
                ))}
              </Tabla>
            </div>
            <div className="mt-3">
              <ComoSeCalcula>
                <p>Capital = stock × costo del proveedor principal. Sano: hasta {r.umbrales.sobrestock} días de stock. Sobrestock: más de {r.umbrales.sobrestock} días. Stock muerto: sin ventas en {r.umbrales.muerto} días o más.</p>
                <p>Cobertura = capital total ÷ costo de lo vendido por día en los últimos 30 días.</p>
              </ComoSeCalcula>
            </div>
          </Tarjeta>
          <Tarjeta titulo="Lo que dejó de venderse">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {r.sin_ventas.map((t) => (
                <div key={t.dias} className="rounded-lg border border-borde p-3">
                  <p className="text-xs text-suave">Sin ventas en {t.dias} días o más</p>
                  <p className="text-lg font-semibold">{numero(t.productos)}</p>
                  <p className="text-xs text-suave">{plata(t.capital)} atrapados</p>
                </div>
              ))}
            </div>
          </Tarjeta>
          <Tarjeta titulo="Qué hacer, producto por producto" accion={
            <Selector className="w-44" value={estado} onChange={(e) => setEstado(e.target.value as typeof estado)} aria-label="Filtrar por estado">
              <option value="todos">Todos</option><option value="sobrestock">Sobrestock</option><option value="muerto">Stock muerto</option><option value="sano">Cayendo</option>
            </Selector>}>
            <TablaDatos filas={items} idFila={(i) => `${i.producto_id}-${i.ubicacion_id}`} nombreArchivo="plata-parada"
              columnas={[
                { id: "prod", titulo: "Producto", valor: (i) => i.nombre, render: (i) => <span>{i.nombre}<span className="block text-xs text-suave">{i.codigo_interno} · {i.ubicacion}</span></span> },
                { id: "estado", titulo: "Estado", valor: (i) => ESTADOS[i.estado].texto, render: (i) => <EstadoStock valor={i.estado} /> },
                { id: "cap", titulo: "Capital", valor: (i) => Number(i.capital ?? 0), render: (i) => plata(i.capital), derecha: true },
                { id: "dias", titulo: "Stock / ventas", valor: (i) => (i.dias_stock ? Number(i.dias_stock) : null), render: (i) => (
                  <span className="whitespace-nowrap text-xs">{i.dias_stock ? `${numero(Math.min(Number(i.dias_stock), 999))}${Number(i.dias_stock) > 999 ? "+" : ""} días de stock` : "—"}
                    <span className="block text-suave">{i.dias_sin_venta === null ? "nunca vendió" : i.dias_sin_venta === 0 ? "vendió hoy" : `última venta hace ${i.dias_sin_venta} d`}</span></span>) },
                { id: "tend", titulo: "Tendencia", valor: (i) => i.variaciones.ultimos_30_vs_anteriores, ocultarEnCelular: true, render: (i) => (
                  <span className="whitespace-nowrap text-xs">{TENDENCIA[i.tendencia ?? ""] ?? "—"}
                    <span className="block text-suave">30 d: {pct(i.variaciones.ultimos_30_vs_anteriores)} · año: {pct(i.variaciones.mes_vs_anio_anterior)}</span></span>) },
                { id: "rec", titulo: "Qué hacer", valor: (i) => i.recomendacion, render: (i) => (
                  <div className="grid min-w-[14rem] gap-1 text-xs">
                    <span className="font-medium">{i.recomendacion}</span>
                    {i.causas.length > 0 && <span className="text-suave">Posible causa: {i.causas.join(" · ")}</span>}
                    {puede("remarcar") && i.estado === "sobrestock" && <button className="text-left text-acento underline" onClick={() => ofertar(i, "segunda_unidad")}>Ofertar 2.ª unidad al 50 %</button>}
                    {puede("remarcar") && i.estado === "muerto" && i.precio && <button className="text-left text-acento underline" onClick={() => ofertar(i, "liquidacion")}>Liquidar al costo</button>}
                  </div>) },
              ]} />
          </Tarjeta>
          {merma && (
            <Tarjeta titulo={`Merma de los últimos 6 meses · ${plata(merma.total)}`}>
              {merma.mensual.length > 0 && (
                <>
                  <p className="mb-2 text-xs text-suave"><span style={{ color: "var(--serie-2)" }}>■</span> Vencidos · <span style={{ color: "var(--serie-1)" }}>■</span> Roturas y otras</p>
                  <div className="h-48">
                    <ResponsiveContainer>
                      <BarChart data={merma.mensual.map((m) => ({ mes: m.mes.slice(5, 7) + "/" + m.mes.slice(2, 4), vencimiento: Number(m.vencimiento), merma: Number(m.merma) }))}
                        barCategoryGap="30%" margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
                        <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
                        <XAxis dataKey="mes" tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
                        <YAxis tickFormatter={(v: number) => plataCorta(v)} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" width={60} />
                        <Tooltip formatter={(v, n) => [plata(Number(v).toFixed(0)), n === "vencimiento" ? "Vencidos" : "Roturas y otras"]} cursor={{ fill: "var(--panel-2)" }} />
                        <Bar dataKey="vencimiento" stackId="m" fill="var(--serie-2)" stroke="var(--panel)" strokeWidth={2} isAnimationActive={false} />
                        <Bar dataKey="merma" stackId="m" fill="var(--serie-1)" stroke="var(--panel)" strokeWidth={2} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </>
              )}
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <Tabla columnas={["Productos con más merma", "Unidades", "A costo"]}>
                  {merma.por_producto.slice(0, 8).map((p) => <tr key={p.nombre}><td>{p.nombre}</td><td className="text-right">{numero(p.unidades)}</td><td className="text-right">{plata(p.costo)}</td></tr>)}
                </Tabla>
                <Tabla columnas={["Por sucursal", "A costo"]}>
                  {merma.por_ubicacion.map((p) => <tr key={p.nombre}><td>{p.nombre}</td><td className="text-right">{plata(p.costo)}</td></tr>)}
                </Tabla>
              </div>
              <p className="mt-3 text-sm text-suave">La merma de los perecederos baja su pedido sugerido: si en 90 días se tiró más del 5 % de lo que entró en juego, se pide esa proporción menos.</p>
              {puede("recuentos") && <div className="mt-4 border-t border-borde pt-4"><h3 className="mb-2 text-sm font-semibold">Registrar merma</h3><RegistrarMerma alGuardar={cargar} /></div>}
            </Tarjeta>
          )}
        </>
      )}
    </div>
  );
}
