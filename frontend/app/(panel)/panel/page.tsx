"use client";
// Panel para distribuidores y marcas (sección 13.3): datos agregados y anónimos de los comercios que dieron su consentimiento,
// con umbral mínimo de comercios por grupo, y portal de recepción de pedidos.
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { fecha, fechaHora, numero, plata, plataCorta } from "@/lib/formato";
import { Indicador } from "@/components/Indicador";
import { Aviso, Boton, ComoSeCalcula, Entrada, Etiqueta, Tabla, Tarjeta, Vacio, cx } from "@/components/ui";

type Umbral = { min_comercios: number; max_participacion: number };
type Zona = { zona: string; comercios: number; mercado: number; facturacion?: number; unidades?: number; participacion?: number; reservado?: boolean };
type Semana = { semana: string; hasta: string; facturacion?: number; unidades?: number; reservado?: boolean };
type Marca = { marca: string; tuya: boolean; facturacion: number; participacion: number };
type Sub = { subcategoria: string; facturacion?: number; marcas?: Marca[]; tuya?: number; reservado?: boolean };
type Producto = { id: number; producto: string; marca: string; subcategoria: string; facturacion?: number; unidades?: number; variacion?: number;
  cobertura?: number; comercios_categoria?: number; quiebres?: number; comercios_con_quiebre?: number; reservado?: boolean };
type Oportunidad = { zona: string; producto: string; marca: string; comercios_sin: number; comercios_categoria: number; potencial_4s?: number };
type Promo = { producto: string; marca: string; comercios: number; desde: string; hasta: string; diaria_antes: number; diaria_durante: number; incremento: number };
type Panel = { distribuidor: string; marcas: string[]; umbral: Umbral; hasta: string | null; desde?: string; semanas: number; sin_datos: boolean;
  reservado?: boolean; motivo?: string; kpis?: { comercios: number; zonas: number; zonas_reservadas: number; facturacion_4s?: number; unidades_4s?: number;
    variacion_4s?: number; participacion?: number };
  zonas?: Zona[]; serie?: Semana[]; mercado?: Sub[]; productos?: Producto[]; oportunidades?: Oportunidad[]; promociones?: Promo[] };
type Linea = { producto: string; ean: string | null; codigo: string | null; cantidad: string; bultos: string | null; costo: string | null };
type Pedido = { id: number; numero: string; estado: string; total: string; fecha_esperada: string | null; enviada_at: string; confirmada_proveedor_at: string | null;
  entrega_prometida: string | null; nota_proveedor: string | null; comercio: string; sucursal: string | null; direccion: string | null; localidad: string | null; lineas: Linea[] };

const PESTANAS = [["resumen", "Resumen"], ["productos", "Productos"], ["mercado", "Participación"], ["promociones", "Promociones"], ["pedidos", "Pedidos"]] as const;
const pct = (v: number | undefined | null, d = 1) => (v === undefined || v === null ? "—" : `${numero(v * 100, d)} %`);
const Reservado = ({ umbral }: { umbral: Umbral }) => (
  <span className="text-xs text-suave" title={`Menos de ${umbral.min_comercios} comercios o uno solo con más del ${numero(umbral.max_participacion * 100)} %`}>Reservado</span>
);

function Resumen({ p }: { p: Panel }) {
  const k = p.kpis!;
  const serie = (p.serie ?? []).map((s) => ({ semana: fecha(s.hasta).slice(0, 5), facturacion: s.facturacion ?? null }));
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Indicador titulo="Sell-out de tus marcas · 4 semanas" valor={k.facturacion_4s !== undefined ? plataCorta(k.facturacion_4s) : "Reservado"}
          actual={k.facturacion_4s} anterior={k.facturacion_4s !== undefined && k.variacion_4s !== undefined ? k.facturacion_4s / (1 + k.variacion_4s) : undefined} />
        <Indicador titulo="Unidades · 4 semanas" valor={numero(k.unidades_4s)} />
        <Indicador titulo="Participación en tus categorías" valor={pct(k.participacion)} nota={`${p.semanas} semanas`} />
        <Indicador titulo="Comercios en el panel" valor={numero(k.comercios)} nota={`${k.zonas} zona${k.zonas === 1 ? "" : "s"}${k.zonas_reservadas ? ` · ${k.zonas_reservadas} reservada${k.zonas_reservadas > 1 ? "s" : ""}` : ""}`} />
      </div>
      <Tarjeta titulo="Sell-out semanal de tus marcas">
        <div className="h-60">
          <ResponsiveContainer>
            <BarChart data={serie} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
              <XAxis dataKey="semana" tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" interval="preserveStartEnd" />
              <YAxis tickFormatter={(v: number) => plataCorta(v)} width={70} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
              <Tooltip formatter={(v) => [plata(Number(v)), "Sell-out"]} labelFormatter={(l) => `Semana al ${l}`} cursor={{ fill: "var(--panel-2)" }} />
              <Bar dataKey="facturacion" fill="var(--serie-1)" radius={[4, 4, 0, 0]} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-1 text-xs text-suave">Cada barra son 7 días que terminan en la fecha indicada. A precios de venta al público.</p>
      </Tarjeta>
      <Tarjeta titulo="Por zona">
        <Tabla columnas={["Zona", "Comercios", "Mercado de tus categorías", "Tus marcas", "Unidades", "Participación"]}>
          {(p.zonas ?? []).map((z) => (
            <tr key={z.zona}>
              <td>{z.zona}</td><td className="text-right">{z.comercios}</td><td className="text-right">{plataCorta(z.mercado)}</td>
              {z.reservado ? <td colSpan={3} className="text-right"><Reservado umbral={p.umbral} /></td> : (
                <><td className="text-right">{plataCorta(z.facturacion)}</td><td className="text-right">{numero(z.unidades)}</td>
                  <td className="text-right font-semibold">{pct(z.participacion)}</td></>
              )}
            </tr>
          ))}
        </Tabla>
      </Tarjeta>
    </div>
  );
}

function Productos({ p }: { p: Panel }) {
  const [marca, setMarca] = useState("");
  const filas = (p.productos ?? []).filter((x) => !marca || x.marca === marca);
  return (
    <div className="grid grid-cols-1 gap-4">
      <Tarjeta titulo="Tus productos · últimas 4 semanas" accion={
        <select aria-label="Marca" className="rounded-lg border border-borde bg-panel px-2 py-1 text-sm" value={marca} onChange={(e) => setMarca(e.target.value)}>
          <option value="">Todas las marcas</option>
          {p.marcas.map((m) => <option key={m}>{m}</option>)}
        </select>}>
        <Tabla columnas={["Producto", "Sell-out", "Unidades", "vs. 4 semanas antes", "Cobertura", "Quiebres"]}>
          {filas.map((x) => (
            <tr key={x.id}>
              <td>{x.producto}<span className="block text-xs text-suave">{x.marca} · {x.subcategoria}</span></td>
              {x.reservado ? <td colSpan={3} className="text-right"><Reservado umbral={p.umbral} /></td> : (
                <><td className="text-right">{plataCorta(x.facturacion)}</td><td className="text-right">{numero(x.unidades)}</td>
                  <td className="whitespace-nowrap text-right">{x.variacion === undefined ? "—" : `${x.variacion > 0 ? "▲ +" : x.variacion < 0 ? "▼ " : ""}${numero(x.variacion * 100, 1)} %`}</td></>
              )}
              <td className="text-right">{x.cobertura === undefined ? "—" : <>{pct(x.cobertura, 0)}<span className="block text-xs text-suave">de {x.comercios_categoria} comercios</span></>}</td>
              <td className="text-right">{x.quiebres === undefined ? "—" : (
                <span className={cx(x.quiebres >= 0.15 && "font-semibold text-peligro")}>{x.quiebres >= 0.15 ? "▲ " : ""}{pct(x.quiebres)}</span>)}</td>
            </tr>
          ))}
        </Tabla>
        <div className="mt-3">
          <ComoSeCalcula>
            <p>Cobertura: de los comercios que vendieron la subcategoría en las últimas 4 semanas, cuántos vendieron este producto.</p>
            <p>Quiebres: días sin stock ÷ días con registro de stock, en los comercios que trabajan el producto.</p>
            <p>«Reservado»: menos de {p.umbral.min_comercios} comercios, o uno solo con más del {numero(p.umbral.max_participacion * 100)} % de la venta. Para que nadie
              pueda despejar un dato reservado restando, a veces también se reserva el más chico de los que sí pasarían.</p>
          </ComoSeCalcula>
        </div>
      </Tarjeta>
      <Tarjeta titulo="Oportunidades: comercios que venden la categoría pero no tu producto">
        {(p.oportunidades ?? []).length === 0 ? <Vacio titulo="Sin oportunidades con datos suficientes" /> : (
          <Tabla columnas={["Zona", "Producto", "Comercios sin el producto", "Potencial (4 semanas)"]}>
            {p.oportunidades!.map((o) => (
              <tr key={`${o.zona}-${o.producto}`}>
                <td>{o.zona}</td><td>{o.producto}<span className="block text-xs text-suave">{o.marca}</span></td>
                <td className="text-right">{o.comercios_sin} de {o.comercios_categoria}</td>
                <td className="text-right">{o.potencial_4s === undefined ? "—" : plataCorta(o.potencial_4s)}</td>
              </tr>
            ))}
          </Tabla>
        )}
        <p className="mt-2 text-xs text-suave">Potencial = venta promedio de los comercios de la zona que sí lo tienen × comercios que no lo tienen. Solo cantidades: nunca qué comercios son.</p>
      </Tarjeta>
    </div>
  );
}

function Mercado({ p }: { p: Panel }) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {(p.mercado ?? []).map((s) => (
        <Tarjeta key={s.subcategoria} titulo={`${s.subcategoria}${s.tuya !== undefined ? ` · tus marcas ${pct(s.tuya)}` : ""}`}>
          {s.reservado ? <Aviso>Reservado: no hay suficientes comercios para mostrar esta categoría.</Aviso> : (
            <ul className="grid gap-2">
              {s.marcas!.map((m) => (
                <li key={m.marca} className="grid grid-cols-[minmax(0,10rem)_1fr_4rem] items-center gap-2 text-sm">
                  <span className="truncate">{m.marca} {m.tuya && <Etiqueta tono="acento">tuya</Etiqueta>}</span>
                  <span className="h-3 rounded-full bg-panel-2">
                    <span className="block h-3 rounded-full" style={{ width: `${Math.max(1, m.participacion * 100)}%`, background: m.tuya ? "var(--serie-1)" : "var(--serie-4)" }} />
                  </span>
                  <span className="text-right tabular-nums">{pct(m.participacion)}</span>
                </li>
              ))}
            </ul>
          )}
          {s.facturacion !== undefined && <p className="mt-2 text-xs text-suave">Mercado: {plataCorta(s.facturacion)} en {p.semanas} semanas. «Otras marcas» junta las que no llegan al umbral.</p>}
        </Tarjeta>
      ))}
    </div>
  );
}

function Promociones({ p }: { p: Panel }) {
  const lista = p.promociones ?? [];
  return (
    <Tarjeta titulo="Efectividad de promociones sobre tus productos">
      {lista.length === 0 ? <Vacio titulo="Sin promociones con datos suficientes">Se muestran cuando al menos {p.umbral.min_comercios} comercios hicieron la promoción.</Vacio> : (
        <Tabla columnas={["Producto", "Comercios", "Período", "Venta diaria antes", "Durante", "Incremento"]}>
          {lista.map((x) => (
            <tr key={x.producto}>
              <td>{x.producto}<span className="block text-xs text-suave">{x.marca}</span></td><td className="text-right">{x.comercios}</td>
              <td className="whitespace-nowrap">{fecha(x.desde)} – {fecha(x.hasta)}</td>
              <td className="text-right">{numero(x.diaria_antes, 1)} u.</td><td className="text-right">{numero(x.diaria_durante, 1)} u.</td>
              <td className="text-right font-semibold">{x.incremento > 0 ? "▲ +" : "▼ "}{numero(x.incremento * 100, 0)} %</td>
            </tr>
          ))}
        </Tabla>
      )}
      <p className="mt-2 text-xs text-suave">Venta diaria de todos los comercios durante la promoción contra sus 4 semanas previas.</p>
    </Tarjeta>
  );
}

function Pedidos() {
  const [lista, setLista] = useState<Pedido[] | null>(null);
  const [motivo, setMotivo] = useState<string | null>(null);
  const [abierto, setAbierto] = useState<number | null>(null);
  const [entrega, setEntrega] = useState("");
  const [nota, setNota] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ver, setVer] = useState<"pendientes" | "recibidos">("pendientes");
  const cargar = () => api<{ pedidos: Pedido[]; motivo?: string }>("/panel/pedidos").then((r) => { setLista(r.pedidos); setMotivo(r.motivo ?? null); }).catch((e) => setError(e.message));
  useEffect(() => { cargar(); }, []);
  async function confirmar(id: number) {
    setError(null);
    try {
      await api(`/panel/pedidos/${id}/confirmar`, { metodo: "POST", cuerpo: { entrega_prometida: entrega || null, nota: nota || null } });
      setAbierto(null); setEntrega(""); setNota("");
      cargar();
    } catch (e) { setError((e as Error).message); }
  }
  if (!lista) return error ? <Aviso tipo="error">{error}</Aviso> : <p className="text-sm text-suave">Cargando…</p>;
  if (motivo) return <Aviso>{motivo}</Aviso>;
  const pendientes = lista.filter((x) => x.estado === "enviada");
  const visibles = ver === "pendientes" ? pendientes : lista.filter((x) => x.estado !== "enviada");
  return (
    <Tarjeta titulo={`Pedidos de tus clientes · últimos 60 días`} accion={
      <div className="flex gap-1">
        {([["pendientes", `Por entregar (${pendientes.length})`], ["recibidos", `Recibidos (${lista.length - pendientes.length})`]] as const).map(([id, t]) => (
          <Boton key={id} variante={ver === id ? "primario" : "secundario"} onClick={() => setVer(id)}>{t}</Boton>
        ))}
      </div>}>
      {error && <div className="mb-3"><Aviso tipo="error">{error}</Aviso></div>}
      {visibles.length === 0 ? <Vacio titulo={ver === "pendientes" ? "No hay pedidos por entregar" : "Sin pedidos recibidos"}>Aparecen cuando un comercio te envía una orden de compra con tu CUIT.</Vacio> : (
        <ul className="grid gap-3">
          {visibles.map((x) => (
            <li key={x.id} className="rounded-xl border border-borde p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-semibold">{x.comercio} · {x.numero}</p>
                  <p className="text-xs text-suave">{x.sucursal}{x.direccion ? ` · ${x.direccion}` : ""}{x.localidad ? `, ${x.localidad}` : ""} · enviada {fechaHora(x.enviada_at)}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{plata(x.total)}</span>
                  {x.estado !== "enviada" ? <Etiqueta tono="ok">✓ Recibida</Etiqueta>
                    : x.confirmada_proveedor_at ? <Etiqueta tono="acento">Confirmada · entrega {fecha(x.entrega_prometida)}</Etiqueta>
                    : <Etiqueta tono="alerta">Sin confirmar</Etiqueta>}
                </div>
              </div>
              <details className="mt-2 text-sm">
                <summary className="cursor-pointer text-acento">{x.lineas.length} productos · espera la entrega el {fecha(x.fecha_esperada)}</summary>
                <Tabla columnas={["Producto", "EAN", "Cantidad", "Bultos", "Costo"]}>
                  {x.lineas.map((l) => (
                    <tr key={`${x.id}-${l.producto}`}><td>{l.producto}</td><td className="text-xs">{l.ean ?? "—"}</td><td className="text-right">{numero(l.cantidad)}</td>
                      <td className="text-right">{numero(l.bultos)}</td><td className="text-right">{plata(l.costo)}</td></tr>
                  ))}
                </Tabla>
              </details>
              {x.nota_proveedor && <p className="mt-1 text-xs text-suave">Tu nota: {x.nota_proveedor}</p>}
              {x.estado === "enviada" && (abierto === x.id ? (
                <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-[auto_1fr_auto] sm:items-end">
                  <label className="text-sm">Entrega prometida<Entrada type="date" value={entrega} onChange={(e) => setEntrega(e.target.value)} /></label>
                  <label className="text-sm">Nota para el comercio<Entrada value={nota} maxLength={300} onChange={(e) => setNota(e.target.value)} placeholder="Ej.: sale en el reparto del jueves" /></label>
                  <div className="flex gap-2"><Boton onClick={() => confirmar(x.id)}>Confirmar</Boton><Boton variante="secundario" onClick={() => setAbierto(null)}>Cancelar</Boton></div>
                </div>
              ) : <div className="mt-2"><Boton variante="secundario" onClick={() => setAbierto(x.id)}>{x.confirmada_proveedor_at ? "Cambiar fecha" : "Confirmar pedido"}</Boton></div>)}
            </li>
          ))}
        </ul>
      )}
    </Tarjeta>
  );
}

export default function PanelDistribuidor() {
  const [activa, setActiva] = useState<string>("resumen");
  const [p, setP] = useState<Panel | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const leer = () => { const id = location.hash.slice(1); if (PESTANAS.some(([x]) => x === id)) setActiva(id); };
    leer();
    window.addEventListener("hashchange", leer);
    api<Panel>("/panel").then(setP).catch((e) => setError(e.message));
    return () => window.removeEventListener("hashchange", leer);
  }, []);
  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Panel de marcas</h1>
        <p className="text-sm text-suave">
          {p ? `${p.distribuidor} · ${p.marcas.length} marcas · ` : ""}Datos agregados y anónimos de los comercios que autorizaron compartirlos
          {p?.hasta ? `, hasta el ${fecha(p.hasta)}` : ""}.
        </p>
      </div>
      <div role="tablist" aria-label="Panel" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1">
        {PESTANAS.map(([id, nombre]) => (
          <a key={id} role="tab" aria-selected={id === activa} href={`#${id}`}
            className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm", id === activa ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>{nombre}</a>
        ))}
      </div>
      {activa === "pedidos" ? <Pedidos /> : error ? <Aviso tipo="error">{error}</Aviso> : !p ? <p className="text-sm text-suave">Cargando…</p>
        : p.sin_datos ? <Vacio titulo="Todavía no hay datos">{p.marcas.length ? "Aún no hay comercios con consentimiento que vendan tus marcas." : "Pedile a la administración de la plataforma que cargue tus marcas."}</Vacio>
        : p.reservado ? <Aviso>{p.motivo}</Aviso>
        : (
          <>
            {activa === "resumen" && <Resumen p={p} />}
            {activa === "productos" && <Productos p={p} />}
            {activa === "mercado" && <Mercado p={p} />}
            {activa === "promociones" && <Promociones p={p} />}
          </>
        )}
      <p className="text-xs text-suave">
        Nunca se muestra un comercio: cada dato junta al menos {p?.umbral.min_comercios ?? 5} comercios y ninguno puede pesar más del {numero((p?.umbral.max_participacion ?? 0.6) * 100)} %.
      </p>
    </div>
  );
}
