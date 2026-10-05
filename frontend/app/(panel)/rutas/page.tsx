"use client";
// Rutas y cobertura (SPEC v2, 12B.3): cumplimiento y efectividad de las visitas, clientes sin visita, cobertura por zona y armado de rutas.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ESTADO_CLIENTE, type EstadoCliente } from "@/lib/distribuidor";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Cifra } from "@/components/distribuidor/Cifra";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, Boton, ComoSeCalcula, Entrada, Etiqueta, Selector, Tabla, Tarjeta, Vacio, cx } from "@/components/ui";

type Dia = { planificadas: number; realizadas: number; cumplimiento: number | null };
type Vend = { vendedor_id: number; vendedor: string; planificadas: number; realizadas: number; con_pedido: number; fuera_de_ruta: number;
  cumplimiento: number | null; efectividad: number | null; dias: Record<string, Dia> };
type SinVisita = { cliente_id: number; cliente: string; localidad: string | null; zona: string | null; vendedor: string | null; estado: EstadoCliente;
  venta_mensual: number; ultima_visita: string | null; dias_sin_visita: number | null };
type Zona = { zona: string; clientes: number; activos: number; prospectos: number; cobertura: number | null };
type DiaRuta = { dia: number | null; nombre: string; clientes: { cliente_id: number; cliente: string; localidad: string | null }[] };
type R = { hoy: string; cumplimiento: { vendedores: Vend[]; total: { cumplimiento: number | null; efectividad: number | null; planificadas: number; realizadas: number };
  motivos: { resultado: string; n: number }[]; dias: string[] }; sin_visita: { dias: number; filas: SinVisita[]; plata_mensual: number };
  cobertura: { zonas: Zona[]; hay_prospectos: boolean }; vendedores: { id: number; nombre: string; zona: string | null }[]; rutas: DiaRuta[] | null };
type Prospecto = { id: number; razon_social: string; direccion: string | null; localidad: string | null; zona: string | null; canal: string | null };

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${numero(v * 100)} %`);
const RESULTADOS: Record<string, string> = { no_visitado: "No se visitó", sin_pedido: "Sin pedido", cerrado: "Estaba cerrado", no_atendio: "No lo atendieron" };
const PESTANAS = [["cumplimiento", "Cumplimiento"], ["sin_visita", "Sin visita"], ["cobertura", "Cobertura por zona"], ["armar", "Armar rutas"]] as const;

export default function Rutas() {
  const { puede } = useSesion();
  const [pestana, setPestana] = useState<(typeof PESTANAS)[number][0]>("cumplimiento");
  const [periodo, setPeriodo] = useState("mes");
  const [vendedor, setVendedor] = useState<string>("");
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cargar = useCallback(() => api<R>(`/distribuidor/rutas?periodo=${periodo}${vendedor ? `&vendedor=${vendedor}` : ""}`).then((x) => {
    setR(x);
    if (!vendedor && x.vendedores[0]) setVendedor(String(x.vendedores[0].id));
  }).catch((e) => setError(e.message)), [periodo, vendedor]);
  useEffect(() => { cargar(); }, [cargar]);

  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Rutas</h1>
          <p className="text-sm text-suave">Si se visita a quien hay que visitar, si esas visitas terminan en pedido y cuánto de cada zona ya es cliente.</p>
        </div>
        <Selector className="w-48" value={periodo} onChange={(e) => setPeriodo(e.target.value)} aria-label="Período">
          <option value="semana">Últimos 7 días</option><option value="mes">Últimos 30 días</option><option value="90d">Últimos 90 días</option>
        </Selector>
      </div>
      <div role="tablist" className="-mx-4 flex gap-1 overflow-x-auto px-4">
        {PESTANAS.map(([id, nombre]) => (
          <button key={id} role="tab" aria-selected={pestana === id} onClick={() => setPestana(id)}
            className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm", pestana === id ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>{nombre}</button>
        ))}
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {!r ? <p className="text-sm text-suave">Cargando…</p> : <>
        {pestana === "cumplimiento" && <Cumplimiento r={r} />}
        {pestana === "sin_visita" && <SinVisitaVista r={r} puede={puede("gestionar_vendedores")} recargar={cargar} />}
        {pestana === "cobertura" && <Cobertura r={r} puede={puede("gestionar_vendedores")} recargar={cargar} />}
        {pestana === "armar" && <Armar r={r} vendedor={vendedor} setVendedor={setVendedor} puede={puede("gestionar_vendedores")} setR={setR} />}
      </>}
    </div>
  );
}

function Cumplimiento({ r }: { r: R }) {
  const c = r.cumplimiento;
  return <>
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <Cifra titulo="Visitas realizadas" valor={pct(c.total.cumplimiento)} nota={`${numero(c.total.realizadas)} de ${numero(c.total.planificadas)} planificadas`}
        tono={(c.total.cumplimiento ?? 1) < 0.85 ? "peligro" : undefined} />
      <Cifra titulo="Efectividad" valor={pct(c.total.efectividad)} nota="visitas que terminaron en pedido" />
      <Cifra titulo="Clientes sin visita" valor={numero(r.sin_visita.filas.length)} nota={`hace más de ${r.sin_visita.dias} días · ${plataCorta(r.sin_visita.plata_mensual)}/mes`} />
      <Cifra titulo="Visitas sin pedido" valor={numero(c.motivos.reduce((s, m) => s + m.n, 0))}
        nota={c.motivos.slice(0, 3).map((m) => `${RESULTADOS[m.resultado] ?? m.resultado}: ${m.n}`).join(" · ")} />
    </div>
    <Tarjeta titulo="Por vendedor y día">
      <Tabla columnas={["Vendedor", ...c.dias, "Total", "Efectividad"]}>
        {c.vendedores.map((v) => (
          <tr key={v.vendedor_id}>
            <td className="font-medium">{v.vendedor}</td>
            {c.dias.map((d) => {
              const x = v.dias[d];
              return <td key={d} className={cx("text-right", x?.cumplimiento != null && x.cumplimiento < 0.8 && "font-semibold text-peligro")}
                title={x ? `${x.realizadas} de ${x.planificadas}` : ""}>{x ? pct(x.cumplimiento) : "—"}</td>;
            })}
            <td className={cx("text-right font-semibold", (v.cumplimiento ?? 1) < 0.85 && "text-peligro")}>{pct(v.cumplimiento)}</td>
            <td className="text-right">{pct(v.efectividad)}</td>
          </tr>
        ))}
      </Tabla>
      <ComoSeCalcula>Cumplimiento: visitas planificadas en la ruta que se hicieron. Efectividad: visitas hechas (en ruta o no) que terminaron en pedido.
        En rojo, menos del 80 % en el día o del 85 % en total.</ComoSeCalcula>
    </Tarjeta>
  </>;
}

function SinVisitaVista({ r, puede, recargar }: { r: R; puede: boolean; recargar: () => void }) {
  const [dias, setDias] = useState(String(r.sin_visita.dias));
  return (
    <Tarjeta titulo={`Clientes sin visita hace más de ${r.sin_visita.dias} días`} accion={puede ? (
      <div className="flex items-center gap-2 text-sm">Días:<Entrada className="w-16" inputMode="numeric" value={dias} onChange={(e) => setDias(e.target.value)} />
        <Boton variante="secundario" onClick={async () => { await api("/distribuidor/rutas/dias-sin-visita", { metodo: "PUT", cuerpo: { dias: Number(dias) } }); recargar(); }}>Guardar</Boton></div>
    ) : undefined}>
      <TablaDatos filas={r.sin_visita.filas} idFila={(f) => String(f.cliente_id)} nombreArchivo="clientes-sin-visita" vacio={<Vacio titulo="Todos tus clientes tienen visita reciente" />}
        columnas={[
          { id: "cliente", titulo: "Cliente", valor: (f) => f.cliente, render: (f) => <span>{f.cliente}<div className="text-xs text-suave">{[f.localidad, f.zona].filter(Boolean).join(" · ")}</div></span> },
          { id: "vendedor", titulo: "Vendedor", valor: (f) => f.vendedor },
          { id: "estado", titulo: "Estado", valor: (f) => f.estado, render: (f) => <Etiqueta tono={ESTADO_CLIENTE[f.estado].tono}>{ESTADO_CLIENTE[f.estado].texto}</Etiqueta> },
          { id: "dias", titulo: "Sin visita", derecha: true, valor: (f) => f.dias_sin_visita ?? 9999,
            render: (f) => (f.dias_sin_visita === null ? "Nunca" : <span>{f.dias_sin_visita} días<div className="text-xs text-suave">{fechaCorta(f.ultima_visita)}</div></span>) },
          { id: "venta", titulo: "Compra por mes", derecha: true, valor: (f) => f.venta_mensual, render: (f) => plata(Math.round(f.venta_mensual)) },
        ]} />
    </Tarjeta>
  );
}

function Cobertura({ r, puede, recargar }: { r: R; puede: boolean; recargar: () => void }) {
  const [zona, setZona] = useState<string | null>(null);
  const [lista, setLista] = useState<Prospecto[]>([]);
  const [vend, setVend] = useState<string>(String(r.vendedores[0]?.id ?? ""));
  useEffect(() => { if (zona) api<Prospecto[]>(`/distribuidor/prospectos?zona=${encodeURIComponent(zona)}`).then(setLista).catch(() => {}); }, [zona]);
  return <>
    <Tarjeta titulo="Cobertura por zona">
      {!r.cobertura.hay_prospectos && <div className="mb-3"><Aviso tipo="info">Cargá los comercios de cada zona que todavía no son clientes (Datos → Importar → «Comercios de la zona») para ver cuánto mercado te falta.</Aviso></div>}
      <Tabla columnas={["Zona", "Clientes activos", "Clientes", "Comercios sin cubrir", "Cobertura", ""]}>
        {r.cobertura.zonas.map((z) => (
          <tr key={z.zona}>
            <td className="font-medium">{z.zona}</td><td className="text-right">{z.activos}</td><td className="text-right">{z.clientes}</td><td className="text-right">{z.prospectos}</td>
            <td><div className="flex items-center gap-2"><div className="h-2 w-24 rounded-full bg-panel-2"><div className={cx("h-2 rounded-full", (z.cobertura ?? 0) < 0.5 ? "bg-peligro" : (z.cobertura ?? 0) < 0.7 ? "bg-alerta" : "bg-ok")}
              style={{ width: `${(z.cobertura ?? 0) * 100}%` }} /></div>{pct(z.cobertura)}</div></td>
            <td>{z.prospectos > 0 && <Boton variante="fantasma" onClick={() => setZona(z.zona)}>Ver comercios</Boton>}</td>
          </tr>
        ))}
      </Tabla>
      <ComoSeCalcula>Cobertura: clientes que compraron en los últimos 90 días sobre todos los comercios conocidos de la zona (clientes y comercios relevados).</ComoSeCalcula>
    </Tarjeta>
    {zona && (
      <Tarjeta titulo={`Comercios de ${zona} que todavía no son clientes`} accion={puede ? (
        <Selector value={vend} onChange={(e) => setVend(e.target.value)} aria-label="Vendedor para los nuevos clientes">
          {r.vendedores.map((v) => <option key={v.id} value={v.id}>{v.nombre}</option>)}
        </Selector>) : undefined}>
        <Tabla columnas={["Comercio", "Dirección", "Canal", ""]}>
          {lista.map((p) => (
            <tr key={p.id}><td>{p.razon_social}</td><td>{[p.direccion, p.localidad].filter(Boolean).join(", ")}</td><td>{p.canal ?? "—"}</td>
              <td>{puede && <Boton variante="secundario" onClick={async () => {
                await api(`/distribuidor/prospectos/${p.id}/convertir`, { metodo: "POST", cuerpo: { vendedor_id: Number(vend) } });
                setLista(lista.filter((x) => x.id !== p.id)); recargar();
              }}>Es cliente</Boton>}</td></tr>
          ))}
        </Tabla>
      </Tarjeta>
    )}
  </>;
}

function Armar({ r, vendedor, setVendedor, puede, setR }: { r: R; vendedor: string; setVendedor: (v: string) => void; puede: boolean; setR: (r: R) => void }) {
  const [rutas, setRutas] = useState<DiaRuta[]>(r.rutas ?? []);
  const [cambios, setCambios] = useState<Set<number>>(new Set());
  const [mensaje, setMensaje] = useState<string | null>(null);
  useEffect(() => { setRutas(r.rutas ?? []); setCambios(new Set()); }, [r.rutas]);
  function mover(desde: number, i: number, hacia: number | "arriba" | "abajo") {
    const copia = rutas.map((d) => ({ ...d, clientes: [...d.clientes] }));
    const origen = copia[desde];
    const [c] = origen.clientes.splice(i, 1);
    let destino = desde;
    if (hacia === "arriba") origen.clientes.splice(Math.max(0, i - 1), 0, c);
    else if (hacia === "abajo") origen.clientes.splice(Math.min(origen.clientes.length, i + 1), 0, c);
    else { destino = hacia; copia[hacia].clientes.push(c); }
    setRutas(copia);
    setCambios(new Set([...cambios, desde, destino]));
  }
  async function guardar() {
    let ultimo: R["rutas"] = null;
    for (const k of cambios) {
      const d = rutas[k];
      if (d.dia === null) continue;
      const x = await api<{ rutas: DiaRuta[] }>(`/distribuidor/rutas/${vendedor}/${d.dia}`, { metodo: "PUT", cuerpo: { clientes: d.clientes.map((c) => c.cliente_id) } });
      ultimo = x.rutas;
    }
    if (ultimo) setR({ ...r, rutas: ultimo });
    setMensaje("Rutas guardadas.");
  }
  return (
    <Tarjeta titulo="Armar rutas" accion={
      <div className="flex gap-2">
        <Selector value={vendedor} onChange={(e) => setVendedor(e.target.value)} aria-label="Vendedor">
          {r.vendedores.map((v) => <option key={v.id} value={v.id}>{v.nombre}</option>)}
        </Selector>
        {puede && <Boton disabled={!cambios.size} onClick={guardar}>Guardar cambios</Boton>}
      </div>}>
      {mensaje && <div className="mb-3"><Aviso tipo="ok">{mensaje}</Aviso></div>}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
        {rutas.map((d, k) => (
          <div key={d.nombre} className={cx("min-w-0 rounded-xl border p-3", d.dia === null ? "border-dashed border-borde" : "border-borde")}>
            <p className="mb-2 font-semibold">{d.nombre} <span className="text-xs font-normal text-suave">· {d.clientes.length} clientes</span></p>
            <ol className="grid gap-1 text-sm">
              {d.clientes.map((c, i) => (
                <li key={c.cliente_id} className="flex min-w-0 items-center justify-between gap-1 rounded bg-panel-2 px-2 py-1">
                  <span className="min-w-0 truncate" title={c.localidad ?? ""}>{d.dia !== null && `${i + 1}. `}{c.cliente}</span>
                  {puede && <span className="flex shrink-0 items-center gap-0.5">
                    {d.dia !== null && <><button aria-label="Subir" className="px-1 text-suave hover:text-texto" onClick={() => mover(k, i, "arriba")}>↑</button>
                      <button aria-label="Bajar" className="px-1 text-suave hover:text-texto" onClick={() => mover(k, i, "abajo")}>↓</button></>}
                    <select aria-label="Pasar a otro día" title="Pasar a otro día" className="w-12 rounded border border-borde bg-panel text-xs" value="" onChange={(e) => mover(k, i, Number(e.target.value))}>
                      <option value="">→</option>{rutas.map((o, j) => o.dia !== null && j !== k && <option key={o.nombre} value={j}>{o.nombre}</option>)}
                    </select>
                  </span>}
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-suave">El orden es el recorrido del día. Un cliente puede estar en más de un día si se lo visita dos veces por semana.</p>
    </Tarjeta>
  );
}
