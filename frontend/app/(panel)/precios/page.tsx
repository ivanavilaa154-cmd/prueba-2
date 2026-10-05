"use client";
// Precios y remarcación (sección 11).
import { useCallback, useEffect, useMemo, useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, BASE } from "@/lib/api";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Panel } from "@/components/Panel";
import { TablaDatos, type Columna } from "@/components/TablaDatos";
import { Aviso, Boton, ComoSeCalcula, Etiqueta, Selector, Tabla, Tarjeta } from "@/components/ui";

type Item = { id: number; nombre: string; codigo_interno: string; ean: string | null; rol_producto: string | null; clase_abc: string; categoria: string;
  proveedor: string | null; precio: string | null; costo: string | null; costo_anterior: string | null; margen_objetivo: string; margen_actual: string | null;
  sugerido: string | null; aumento_pct: string | null; perdida_diaria: string; estado: string; erosionado?: boolean; parcial?: boolean; cambio_pct?: string;
  motivo: string | null; fecha_lista: string | null; venta_diaria: string; iva?: string; costo_reposicion?: string | null; costo_historico?: string | null };
type R = { items: Item[]; tarjetas: { a_remarcar: number; perdida_diaria: string; erosionados: number; aumentos: number };
  listas_recientes: { id: number; vigencia_desde: string; proveedor: string; productos: number; aumento_promedio: string | null }[];
  canal_costo_pct: string; puede_remarcar: boolean; hoy: string };

const ESTADO: Record<string, [string, "peligro" | "ok" | "gris" | "alerta" | "acento"]> = {
  subir: ["Remarcar", "peligro"], ok: ["Bien", "ok"], podria_bajar: ["Margen alto", "acento"], sin_costo: ["Sin costo", "alerta"], sin_precio: ["Sin precio", "alerta"], revisar: ["Revisar", "alerta"],
};

export default function Precios() {
  const { filtro } = useSesion();
  const [vista, setVista] = useState("a_remarcar");
  const [r, setR] = useState<R | null>(null);
  const [editado, setEditado] = useState<Record<number, string>>({});
  const [detalle, setDetalle] = useState<Item | null>(null);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: React.ReactNode } | null>(null);
  const canal = filtro.canal === "todos" ? "" : filtro.canal;
  useEffect(() => { const f = new URLSearchParams(location.search).get("filtro"); if (f) setVista(f); }, []);

  const cargar = useCallback(() => {
    setR(null);
    api<R>(`/precios/remarcacion?filtro=${vista}${canal ? `&canal=${canal}` : ""}`).then(setR).catch((e) => setMensaje({ tipo: "error", texto: e.message }));
  }, [vista, canal]);
  useEffect(() => { cargar(); }, [cargar]);

  async function aplicar(sel: Item[], limpiar: () => void) {
    const cambios = sel.filter((i) => editado[i.id] || i.sugerido).map((i) => ({ producto_id: i.id, precio: (editado[i.id] || i.sugerido || "").replace(",", "."), canal: canal || null }));
    if (!cambios.length) return;
    if (!confirm(`¿Aplicar ${cambios.length} precio(s) nuevo(s) desde hoy?`)) return;
    try {
      const res = await api<{ aplicados: number; desde: string }>("/precios/aplicar", { metodo: "POST", cuerpo: { cambios } });
      limpiar();
      setMensaje({ tipo: "ok", texto: <>Se aplicaron {res.aplicados} precios. <a className="underline" href={`${BASE}/api/precios/etiquetas?desde=${res.desde}&productos=${cambios.map((c) => c.producto_id).join(",")}`} target="_blank" rel="noreferrer">Imprimir etiquetas de góndola</a> · exportá la tabla (Excel/CSV) para cargarlos en la caja.</> });
      cargar();
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo aplicar." });
    }
  }

  const columnas = useMemo<Columna<Item>[]>(() => [
    { id: "producto", titulo: "Producto", valor: (i) => i.nombre, render: (i) => (
      <span><span className="font-medium">{i.nombre}</span><br /><span className="text-xs text-suave">{i.codigo_interno} · {i.categoria}{i.rol_producto === "iman" ? " · imán" : ""}</span></span>) },
    { id: "estado", titulo: "Estado", valor: (i) => i.estado, render: (i) => <Etiqueta tono={ESTADO[i.estado]?.[1] ?? "gris"}>{ESTADO[i.estado]?.[0] ?? i.estado}</Etiqueta> },
    { id: "costo", titulo: "Costo", valor: (i) => Number(i.costo ?? 0), render: (i) => (
      <span>{plata(i.costo)}{i.aumento_pct && Number(i.aumento_pct) > 0.005 ? <><br /><span className="text-xs text-peligro">▲ {numero(Number(i.aumento_pct) * 100, 1)} %</span></> : null}</span>), derecha: true },
    { id: "precio", titulo: "Precio", valor: (i) => Number(i.precio ?? 0), render: (i) => plata(i.precio), derecha: true },
    { id: "margen", titulo: "Margen", valor: (i) => Number(i.margen_actual ?? 0), render: (i) => (i.margen_actual === null ? "—" : (
      <span className={i.erosionado ? "text-peligro" : ""}>{numero(Number(i.margen_actual) * 100, 1)} %<br /><span className="text-xs text-suave">objetivo {numero(Number(i.margen_objetivo) * 100, 0)} %</span></span>)), derecha: true },
    { id: "sugerido", titulo: "Sugerido", valor: (i) => Number(i.sugerido ?? 0), render: (i) => (i.sugerido === null ? "—" : (
      <span onClick={(e) => e.stopPropagation()}>
        <input inputMode="decimal" aria-label={`Precio nuevo de ${i.nombre}`} className="w-24 rounded border border-borde bg-panel px-2 py-1 text-right"
          value={editado[i.id] ?? Number(i.sugerido).toString()} onChange={(e) => setEditado((x) => ({ ...x, [i.id]: e.target.value }))} />
        {i.cambio_pct && Math.abs(Number(i.cambio_pct)) >= 0.005 && <><br /><span className="text-xs text-suave">{Number(i.cambio_pct) > 0 ? "+" : ""}{numero(Number(i.cambio_pct) * 100, 1)} %</span></>}
      </span>)), derecha: true },
    { id: "perdida", titulo: "Pierde por día", valor: (i) => Number(i.perdida_diaria), render: (i) => (Number(i.perdida_diaria) > 0 ? plata(Number(i.perdida_diaria).toFixed(0)) : "—"), derecha: true },
    { id: "motivo", titulo: "Por qué", valor: (i) => i.motivo, render: (i) => <span className="text-xs text-suave">{i.motivo ?? ""}</span>, ocultarEnCelular: true },
    { id: "ean", titulo: "EAN", valor: (i) => i.ean, ocultarEnCelular: true },
  ], [editado]);

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Precios y remarcación</h1>
          <p className="text-sm text-suave">Qué remarcar primero para no perder margen{canal ? ` en ${canal === "ecommerce" ? "e-commerce (incluye comisiones y envíos)" : canal}` : ""}.</p>
        </div>
        <Selector aria-label="Qué mostrar" className="w-auto" value={vista} onChange={(e) => setVista(e.target.value)}>
          <option value="a_remarcar">Para remarcar</option><option value="aumentos">Con aumento del proveedor</option>
          <option value="erosionados">Con margen erosionado</option><option value="todos">Todos los productos</option>
        </Selector>
      </div>
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
      {r && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Dato titulo="Para remarcar" valor={numero(r.tarjetas.a_remarcar)} />
          <Dato titulo="Margen que perdés por día" valor={plataCorta(r.tarjetas.perdida_diaria)} nota="si no remarcás lo sugerido" />
          <Dato titulo="Margen erosionado" valor={numero(r.tarjetas.erosionados)} nota="por debajo del objetivo" />
          <Dato titulo="Aumentos del proveedor" valor={numero(r.tarjetas.aumentos)} nota="en los últimos 30 días" />
        </div>
      )}
      {r && r.listas_recientes.length > 0 && (
        <Tarjeta titulo="Listas de precios recientes de proveedores">
          <div className="flex flex-wrap gap-2 text-sm">
            {r.listas_recientes.slice(0, 8).map((l) => (
              <span key={l.id} className="rounded-lg border border-borde px-3 py-1.5">{l.proveedor} · {fechaCorta(l.vigencia_desde)} · {l.productos} productos
                {l.aumento_promedio !== null && <span className={Number(l.aumento_promedio) > 0.005 ? " text-peligro" : " text-suave"}> · {Number(l.aumento_promedio) > 0 ? "+" : ""}{numero(Number(l.aumento_promedio) * 100, 1)} %</span>}</span>
            ))}
          </div>
        </Tarjeta>
      )}
      <Tarjeta>
        {!r ? <p className="text-sm text-suave">Cargando…</p> : (
          <TablaDatos filas={r.items} columnas={columnas} idFila={(i) => String(i.id)} nombreArchivo={`precios-${vista}`} alHacerClic={setDetalle}
            vacio="No hay productos en esta vista."
            acciones={r.puede_remarcar ? (sel, limpiar) => (
              <>
                <Boton onClick={() => aplicar(sel, limpiar)}>Aplicar precios</Boton>
                <a className="inline-flex min-h-9 items-center rounded-lg border border-borde bg-panel px-3 text-sm" target="_blank" rel="noreferrer"
                  href={`${BASE}/api/precios/etiquetas?desde=2000-01-01&productos=${sel.map((i) => i.id).join(",")}`}>Etiquetas de estos</a>
              </>
            ) : undefined} />
        )}
      </Tarjeta>
      <ComoSeCalcula>
        <p>Precio sugerido = costo ÷ (1 − margen objetivo{canal ? " − costos del canal (comisión, envíos y publicidad sobre lo vendido online)" : ""}), redondeado según los tramos configurados (por ejemplo, terminaciones en 0, 5 o 9). Si el cambio es menor al 1 %, no se sugiere remarcar.</p>
        <p>Margen objetivo: el del producto; si no tiene, el de su subcategoría o categoría; si no, 30 %. Se configura en Configuración → Precios.</p>
        <p>Prioridad: primero lo que más margen te hace perder por día (cuánto de más cuesta respecto del costo que daría el margen objetivo, por las unidades que vendés por día).</p>
        <p>Imanes (venden mucho con poco margen): se sugiere trasladar solo la mitad del aumento para no espantar clientes.</p>
        <p>Los precios nuevos quedan registrados con fecha. La caja no se modifica desde acá: exportá la tabla para cargarla e imprimí las etiquetas de lo que cambió.</p>
      </ComoSeCalcula>
      <Panel abierto={!!detalle} alCerrar={() => setDetalle(null)} titulo={detalle && <div><p className="font-semibold">{detalle.nombre}</p><p className="text-xs text-suave">Historial de precio y costo</p></div>}>
        {detalle && <Historial item={detalle} />}
      </Panel>
    </div>
  );
}

function Dato({ titulo, valor, nota }: { titulo: string; valor: string; nota?: string }) {
  return <div className="rounded-xl border border-borde bg-panel p-4"><p className="text-sm text-suave">{titulo}</p><p className="mt-1 text-2xl font-semibold">{valor}</p>{nota && <p className="text-xs text-suave">{nota}</p>}</div>;
}

function Historial({ item }: { item: Item }) {
  const [h, setH] = useState<{ precios: { precio: string; desde: string; hasta: string | null; origen: string; canal: string }[]; semanal: { semana: string; costo: string; precio: string }[] } | null>(null);
  useEffect(() => { api<typeof h>(`/precios/historial/${item.id}`).then(setH); }, [item.id]);
  if (!h) return <p className="text-sm text-suave">Cargando…</p>;
  const datos = h.semanal.map((s) => ({ semana: s.semana, precio: Number(s.precio), costo: s.costo === null ? null : Number(s.costo) }));
  return (
    <div className="grid gap-4">
      {item.motivo && <Aviso tipo="info">{item.motivo}</Aviso>}
      <div className="grid grid-cols-2 gap-3">
        <Dato titulo="Costo de reposición" valor={plata(item.costo_reposicion)} nota="lista vigente, sin IVA y con descuentos: lo usa el margen" />
        <Dato titulo="Costo histórico" valor={plata(item.costo_historico)} nota="promedio ponderado de las compras de 12 meses, sin IVA" />
      </div>
      {item.iva !== undefined && <p className="text-xs text-suave">IVA del producto: {Number(item.iva) === 0 ? "exento" : `${numero(Number(item.iva) * 100, 1)} %`}. El margen se calcula sin IVA.</p>}
      <Tarjeta titulo="Precio cobrado y costo por semana">
        <div className="h-56">
          <ResponsiveContainer>
            <LineChart data={datos} margin={{ top: 4, right: 12, left: 8, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
              <XAxis dataKey="semana" tickFormatter={(v: string) => fechaCorta(v).slice(3)} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" minTickGap={30} />
              <YAxis tickFormatter={(v: number) => plataCorta(v).replace("$ ", "")} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" width={52} />
              <Tooltip formatter={(v, n) => [plata(Number(v).toFixed(2)), n === "precio" ? "Precio promedio cobrado" : "Costo"]} labelFormatter={(v) => `Semana del ${fechaCorta(String(v))}`} />
              <Legend formatter={(v) => (v === "precio" ? "Precio cobrado" : "Costo")} />
              <Line dataKey="precio" stroke="var(--serie-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line dataKey="costo" stroke="var(--serie-2)" strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Tarjeta>
      <Tarjeta titulo="Cambios de precio">
        <Tabla columnas={["Desde", "Hasta", "Precio", "Canal", "Origen"]}>
          {[...h.precios].reverse().slice(0, 20).map((p, i) => (
            <tr key={i}><td>{fechaCorta(p.desde)}</td><td>{p.hasta ? fechaCorta(p.hasta) : "vigente"}</td><td className="cifra text-right">{plata(p.precio)}</td><td>{p.canal}</td>
              <td>{p.origen === "remarcacion" ? "Remarcación" : p.origen === "demo" ? "Lista" : p.origen}</td></tr>
          ))}
        </Tabla>
      </Tarjeta>
    </div>
  );
}
