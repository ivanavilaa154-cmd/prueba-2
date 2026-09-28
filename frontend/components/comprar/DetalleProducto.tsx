"use client";
// Detalle de un producto en una sucursal: por qué se sugiere lo que se sugiere, ventas y stock en el tiempo, pronóstico,
// lotes y proveedores. Dos gráficos separados (ventas y stock tienen escalas distintas: nunca doble eje).
import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { fechaCorta, numero, plata } from "@/lib/formato";
import { Aviso, ComoSeCalcula, Etiqueta, Tabla } from "@/components/ui";
import { Semaforo } from "@/components/Semaforo";

type Detalle = {
  producto: { id: number; nombre: string; codigo_interno: string; ean: string | null; categoria: string; subcategoria: string; clase_abc: string; rol_producto: string; unidad: string };
  ubicacion_id: number;
  metricas: { ubicacion_id: number; ubicacion: string; tipo: string; disponible: string; vpd: string; dias_stock: string | null; fecha_quiebre: string | null; cantidad_sugerida: string; semaforo: string }[];
  actual: { semaforo: string; explicacion: Record<string, unknown>; confianza: string; clase_abc: string; tendencia: string };
  serie: { fecha: string; unidades: string | number; stock: string | null; sin_stock: boolean }[];
  pronostico: { fecha: string; unidades: number }[];
  lotes: { lote: string; cantidad: string; vencimiento: string | null }[];
  proveedores: { id: number; razon_social: string; costo: string | null; unidades_por_bulto: number; demora_entrega_dias: number | null; dias_visita: number[]; principal: boolean }[];
  texto_sugerencia: string;
  texto_semaforo: string;
};

const DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];
const ROL: Record<string, string> = { estrella: "Estrella", iman: "Imán", joya: "Joya", peso_muerto: "Peso muerto" };

function Consejo({ active, payload, label, unidad }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string; unidad: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-borde bg-panel px-3 py-2 text-xs shadow">
      <p className="font-medium">{fechaCorta(label)}</p>
      {payload.filter((p) => p.value !== null && p.value !== undefined).map((p) => (
        <p key={p.name} className="text-suave"><span style={{ color: p.color }}>■</span> {p.name}: <span className="text-texto">{numero(p.value, 1)} {unidad}</span></p>
      ))}
    </div>
  );
}

export function DetalleProducto({ productoId, ubicacionId }: { productoId: number; ubicacionId: number }) {
  const [d, setD] = useState<Detalle | null>(null);
  const [uid, setUid] = useState(ubicacionId);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<Detalle>(`/productos/${productoId}?ubicacion_id=${uid}`).then(setD).catch((e) => setError(e.message));
  }, [productoId, uid]);

  const ventas = useMemo(() => {
    if (!d) return [];
    const hist = d.serie.slice(-90).map((s) => ({ fecha: s.fecha, vendido: Number(s.unidades), pronostico: null as number | null }));
    const futuro = d.pronostico.slice(1).map((p) => ({ fecha: p.fecha, vendido: null as number | null, pronostico: p.unidades }));
    return [...hist, ...futuro];
  }, [d]);
  const stock = useMemo(() => (d ? d.serie.slice(-90).map((s) => ({ fecha: s.fecha, stock: s.stock === null ? null : Number(s.stock) })) : []), [d]);
  const tramosSinStock = useMemo(() => {
    if (!d) return [];
    const tramos: { desde: string; hasta: string }[] = [];
    for (const s of d.serie.slice(-90)) {
      if (!s.sin_stock) continue;
      const ult = tramos[tramos.length - 1];
      if (ult && new Date(s.fecha).getTime() - new Date(ult.hasta).getTime() <= 86400000 * 1.5) ult.hasta = s.fecha;
      else tramos.push({ desde: s.fecha, hasta: s.fecha });
    }
    return tramos;
  }, [d]);

  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!d) return <p className="text-sm text-suave">Cargando…</p>;
  const e = d.actual.explicacion as Record<string, number | string | boolean | null | number[]>;
  const unidad = d.producto.unidad === "kg" ? "kg" : "u.";
  const factores = (e.factores ?? {}) as Record<string, unknown>;

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Semaforo valor={d.actual.semaforo} />
        <Etiqueta>Clase {d.actual.clase_abc}</Etiqueta>
        {d.producto.rol_producto && <Etiqueta>{ROL[d.producto.rol_producto] ?? d.producto.rol_producto}</Etiqueta>}
        {d.actual.confianza === "baja" && <Etiqueta tono="alerta">Poca historia</Etiqueta>}
        {Boolean(e.stock_negativo) && <Etiqueta tono="peligro">Stock negativo: contar</Etiqueta>}
        {Boolean(e.sin_costo) && <Etiqueta tono="alerta">Sin costo cargado</Etiqueta>}
      </div>
      {d.metricas.length > 1 && (
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Sucursal">
          {d.metricas.map((m) => (
            <button key={m.ubicacion_id} role="tab" aria-selected={m.ubicacion_id === d.ubicacion_id} onClick={() => setUid(m.ubicacion_id)}
              className={`rounded-lg px-3 py-1.5 text-sm ${m.ubicacion_id === d.ubicacion_id ? "bg-acento text-acento-texto" : "border border-borde bg-panel"}`}>
              {m.ubicacion}
            </button>
          ))}
        </div>
      )}
      <div className="rounded-xl border border-acento/30 bg-acento/5 p-4">
        <p className="text-base leading-relaxed">{d.texto_sugerencia}</p>
        <p className="mt-2 text-sm text-suave">{d.texto_semaforo}</p>
      </div>

      <section className="rounded-xl border border-borde bg-panel p-4">
        <h3 className="text-sm font-semibold">Ventas por día (últimos 90 días) y pronóstico</h3>
        <p className="mb-2 text-xs text-suave"><span style={{ color: "var(--serie-1)" }}>■</span> Vendido · <span style={{ color: "var(--serie-1)", opacity: 0.45 }}>■</span> Pronóstico de los próximos días</p>
        <div className="h-48">
          <ResponsiveContainer>
            <BarChart data={ventas} barCategoryGap="15%" margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
              <XAxis dataKey="fecha" tickFormatter={(v: string) => fechaCorta(v).slice(0, 5)} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }}
                interval="preserveStartEnd" minTickGap={40} stroke="var(--grafico-eje)" />
              <YAxis tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" allowDecimals={false} />
              <Tooltip content={<Consejo unidad={unidad} />} cursor={{ fill: "var(--panel-2)" }} />
              <Bar dataKey="vendido" name="Vendido" stackId="v" fill="var(--serie-1)" radius={[3, 3, 0, 0]} isAnimationActive={false} />
              <Bar dataKey="pronostico" name="Pronóstico" stackId="v" fill="var(--serie-1)" fillOpacity={0.45} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
      <section className="rounded-xl border border-borde bg-panel p-4">
        <h3 className="text-sm font-semibold">Stock al cierre de cada día</h3>
        <p className="mb-2 text-xs text-suave">Las franjas grises son días sin stock: no cuentan para la venta promedio.</p>
        <div className="h-40">
          <ResponsiveContainer>
            <LineChart data={stock} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
              {tramosSinStock.map((t) => <ReferenceArea key={t.desde} x1={t.desde} x2={t.hasta} fill="var(--gris)" fillOpacity={0.18} ifOverflow="extendDomain" />)}
              <XAxis dataKey="fecha" tickFormatter={(v: string) => fechaCorta(v).slice(0, 5)} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }}
                interval="preserveStartEnd" minTickGap={40} stroke="var(--grafico-eje)" />
              <YAxis tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
              <Tooltip content={<Consejo unidad={unidad} />} />
              <Line dataKey="stock" name="Stock" stroke="var(--serie-2)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className="rounded-xl border border-borde bg-panel p-4">
        <h3 className="mb-2 text-sm font-semibold">En cada sucursal</h3>
        <Tabla columnas={["Sucursal", "Stock", "Venta/día", "Días de stock", "Se agota", "Sugerido", ""]}>
          {d.metricas.map((m) => (
            <tr key={m.ubicacion_id}>
              <td>{m.ubicacion}</td>
              <td className="cifra">{numero(m.disponible, 0)}</td>
              <td className="cifra">{numero(m.vpd, 1)}</td>
              <td className="cifra">{m.dias_stock === null ? "—" : numero(m.dias_stock, 0)}</td>
              <td>{fechaCorta(m.fecha_quiebre)}</td>
              <td className="cifra">{numero(m.cantidad_sugerida, 0)}</td>
              <td><Semaforo valor={m.semaforo} corto /></td>
            </tr>
          ))}
        </Tabla>
      </section>

      {d.lotes.length > 0 && (
        <section className="rounded-xl border border-borde bg-panel p-4">
          <h3 className="mb-2 text-sm font-semibold">Lotes y vencimientos</h3>
          <Tabla columnas={["Lote", "Cantidad", "Vence"]}>
            {d.lotes.map((l) => <tr key={l.lote}><td>{l.lote}</td><td className="cifra">{numero(l.cantidad, 0)}</td><td>{fechaCorta(l.vencimiento)}</td></tr>)}
          </Tabla>
        </section>
      )}
      <section className="rounded-xl border border-borde bg-panel p-4">
        <h3 className="mb-2 text-sm font-semibold">Proveedores</h3>
        <Tabla columnas={["Proveedor", "Costo", "Bulto", "Pasa", "Demora"]}>
          {d.proveedores.map((p) => (
            <tr key={p.id}>
              <td>{p.razon_social}{p.principal && <span className="ml-1 text-xs text-suave">(principal)</span>}</td>
              <td className="cifra">{plata(p.costo)}</td>
              <td className="cifra">{p.unidades_por_bulto} u.</td>
              <td>{p.dias_visita.length ? p.dias_visita.map((x) => DIAS[x]).join(", ") : "sin días cargados"}</td>
              <td>{p.demora_entrega_dias ?? "—"} días</td>
            </tr>
          ))}
        </Tabla>
      </section>

      <ComoSeCalcula>
        <p><strong>Venta promedio diaria:</strong> unidades de los últimos 28 días ÷ días CON stock ({String(e.dias_con_stock)} con stock, {String(e.dias_sin_stock)} sin stock → {numero(e.vpd as number, 2)} por día).</p>
        <p><strong>Pronóstico:</strong> venta ponderada (40 % la última semana, 30 %, 20 % y 10 % las anteriores = {numero(e.vpd_ponderada as number, 2)}) × factor del día de la semana × inicio o fin de mes × feriados × estacionalidad × tendencia ({numero(factores.tendencia as number, 2)}). Factores calculados con la historia del {factores.origen === "producto" ? "producto" : "promedio de su categoría"}.</p>
        <p><strong>Horizonte:</strong> días hasta que se pueda pedir + días hasta el pedido siguiente + demora de entrega = {String(e.horizonte)} días.</p>
        <p><strong>Stock de seguridad:</strong> según la clase ABC ({String(e.clase_abc)}) y cuánto varía la venta diaria = {numero(e.stock_seguridad as number, 1)}.</p>
        <p><strong>Cantidad sugerida:</strong> pronóstico del horizonte ({numero(e.pronostico_horizonte as number, 1)}) + seguridad − disponible − en tránsito − ya pedido, redondeado al bulto ({String(e.multiplo)}).</p>
        <p><strong>Semáforo:</strong> rojo si se agota antes de que pueda llegar la próxima reposición; amarillo si hay que incluirlo en ese pedido; verde si está cubierto; gris si hay más de 30 días de stock.</p>
      </ComoSeCalcula>
    </div>
  );
}
