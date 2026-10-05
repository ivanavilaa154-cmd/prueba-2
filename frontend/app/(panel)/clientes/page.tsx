"use client";
// Clientes del distribuidor (SPEC v2, 12B.2 y 12B.7): los que dejaron de comprar o están en riesgo según su propio ritmo, con la plata
// que se deja de facturar; ficha de cada cliente con su historia, deuda y qué ofrecerle; Pareto de clientes y de productos.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ESTADO_CLIENTE, type FilaCliente, type ResumenClientes } from "@/lib/distribuidor";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { FichaCliente, type Ficha } from "@/components/distribuidor/FichaCliente";
import { Cifra } from "@/components/distribuidor/Cifra";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, ComoSeCalcula, Etiqueta, Selector, Tarjeta, Vacio, cx } from "@/components/ui";

type R = { hoy: string; resumen: ResumenClientes; filas: FilaCliente[]; umbrales: { riesgo: number; perdido: number; min_dias: number };
  zonas: string[]; vendedores: { id: number; nombre: string }[] };
type Pareto = { filas: { id: number; nombre: string; venta: number; ganancia: number; clase: string; participacion: number; acumulado: number }[];
  cantidad: number; clase_a: number; mensaje: string };

export default function Clientes() {
  const { puede } = useSesion();
  const [pestana, setPestana] = useState<"estado" | "pareto">("estado");
  const [r, setR] = useState<R | null>(null);
  const [filtro, setFiltro] = useState<string>("perdiendo");
  const [vendedor, setVendedor] = useState("");
  const [zona, setZona] = useState("");
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const q = new URLSearchParams();
    if (vendedor) q.set("vendedor", vendedor);
    if (zona) q.set("zona", zona);
    api<R>(`/distribuidor/clientes?${q}`).then(setR).catch((e) => setError(e.message));
  }, [vendedor, zona]);

  async function abrir(id: number) {
    setFicha(null);
    try { setFicha(await api<Ficha>(`/distribuidor/clientes/${id}`)); } catch (e) { setError(e instanceof Error ? e.message : "No se pudo abrir."); }
  }
  const filas = (r?.filas ?? []).filter((f) => filtro === "todos" || (filtro === "perdiendo" ? f.estado === "perdido" || f.estado === "en_riesgo" : f.estado === filtro));

  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Clientes</h1>
        <p className="text-sm text-suave">Cada cliente se compara con su propio ritmo de compra: así se ve a tiempo quién se está yendo y cuánta plata se deja de facturar.</p>
      </div>
      {puede("ver_ventas") && (
        <div role="tablist" className="flex gap-1">
          {([["estado", "Dejaron de comprar"], ["pareto", "Pareto de clientes y productos"]] as const).map(([id, nombre]) => (
            <button key={id} role="tab" aria-selected={pestana === id} onClick={() => setPestana(id)}
              className={cx("rounded-lg px-3 py-1.5 text-sm", pestana === id ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>{nombre}</button>
          ))}
        </div>
      )}
      {error && <Aviso tipo="error">{error}</Aviso>}
      {pestana === "pareto" ? <ParetoVista /> : !r ? <p className="text-sm text-suave">Cargando…</p> : <>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Cifra titulo="Dejaron de comprar" valor={numero(r.resumen.perdido)} nota={`${plataCorta(r.resumen.en_juego_perdidos)} por mes que ya no entran`} tono="peligro" />
          <Cifra titulo="En riesgo" valor={numero(r.resumen.en_riesgo)} nota={`${plataCorta(r.resumen.en_juego_riesgo)} por mes en juego`} tono="alerta" />
          <Cifra titulo="Activos" valor={numero(r.resumen.activo)} nota={`de ${numero(r.resumen.total)} clientes`} />
          <Cifra titulo="Plata que se deja de facturar" valor={plataCorta(r.resumen.deja_de_facturar_mes)} nota="por mes, entre perdidos y en riesgo" tono="peligro" />
        </div>
        <Tarjeta titulo="Clientes" accion={
          <div className="flex flex-wrap gap-2">
            <Selector value={filtro} onChange={(e) => setFiltro(e.target.value)} aria-label="Estado">
              <option value="perdiendo">Perdidos y en riesgo</option><option value="perdido">Dejaron de comprar</option>
              <option value="en_riesgo">En riesgo</option><option value="activo">Activos</option><option value="todos">Todos</option>
            </Selector>
            {r.vendedores.length > 0 && (
              <Selector value={vendedor} onChange={(e) => setVendedor(e.target.value)} aria-label="Vendedor">
                <option value="">Todos los vendedores</option>{r.vendedores.map((v) => <option key={v.id} value={v.id}>{v.nombre}</option>)}
              </Selector>
            )}
            {r.zonas.length > 1 && (
              <Selector value={zona} onChange={(e) => setZona(e.target.value)} aria-label="Zona">
                <option value="">Todas las zonas</option>{r.zonas.map((z) => <option key={z}>{z}</option>)}
              </Selector>
            )}
          </div>}>
          <TablaDatos filas={filas} idFila={(f) => String(f.cliente_id)} nombreArchivo="clientes" alHacerClic={(f) => abrir(f.cliente_id)}
            vacio={<Vacio titulo="No hay clientes con ese filtro" />}
            columnas={[
              { id: "cliente", titulo: "Cliente", valor: (f) => f.cliente,
                render: (f) => <div><span className="font-medium">{f.cliente}</span><div className="text-xs text-suave">{[f.localidad, f.canal].filter(Boolean).join(" · ")}</div></div> },
              { id: "estado", titulo: "Estado", valor: (f) => ESTADO_CLIENTE[f.estado].texto,
                render: (f) => <Etiqueta tono={ESTADO_CLIENTE[f.estado].tono}>{ESTADO_CLIENTE[f.estado].texto}</Etiqueta> },
              { id: "dias", titulo: "Sin comprar", derecha: true, valor: (f) => f.dias_sin_comprar,
                render: (f) => f.dias_sin_comprar === null ? "—" : <span>{f.dias_sin_comprar} días<div className="text-xs text-suave">ritmo: cada {numero(f.intervalo ?? 0)} d</div></span> },
              { id: "vendedor", titulo: "Vendedor", valor: (f) => f.vendedor, ocultarEnCelular: true },
              { id: "venta", titulo: "Compraba por mes", derecha: true, valor: (f) => f.venta_mensual, render: (f) => plata(Math.round(f.venta_mensual)) },
              { id: "juego", titulo: "Se deja de facturar", derecha: true, valor: (f) => f.deja_de_facturar_mes,
                render: (f) => f.deja_de_facturar_mes ? <strong>{plata(Math.round(f.deja_de_facturar_mes))}</strong> : "—" },
              { id: "ultima", titulo: "Última compra", valor: (f) => f.ultima_compra, render: (f) => fechaCorta(f.ultima_compra), ocultarEnCelular: true },
            ]} />
          <ComoSeCalcula>
            El ritmo de cada cliente es la mediana de sus últimos intervalos entre compras (con menos de 3 compras se toma 30 días).
            En riesgo: lleva más de {numero(r.umbrales.riesgo, 1)} veces su ritmo sin comprar. Dejó de comprar: más de {numero(r.umbrales.perdido, 1)} veces
            (y al menos {r.umbrales.min_dias} días). La plata que se deja de facturar es lo que compraba por mes en los 6 meses anteriores a su última compra.
            Una compra es un pedido que no se anuló ni se rechazó.
          </ComoSeCalcula>
        </Tarjeta>
      </>}
      {ficha && <FichaCliente ficha={ficha} cerrar={() => setFicha(null)} />}
    </div>
  );
}

function ParetoVista() {
  const [periodo, setPeriodo] = useState("90d");
  const [r, setR] = useState<{ clientes: Pareto; productos: Pareto } | null>(null);
  useEffect(() => { api<{ clientes: Pareto; productos: Pareto }>(`/distribuidor/pareto?periodo=${periodo}`).then(setR).catch(() => {}); }, [periodo]);
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {([["clientes", "Clientes"], ["productos", "Productos"]] as const).map(([clave, titulo]) => (
        <Tarjeta key={clave} titulo={`Pareto de ${titulo.toLowerCase()} por ganancia`} accion={clave === "clientes" ? (
          <Selector value={periodo} onChange={(e) => setPeriodo(e.target.value)} aria-label="Período">
            <option value="mes">Últimos 30 días</option><option value="90d">Últimos 90 días</option><option value="anio">Último año</option>
          </Selector>) : undefined}>
          <p className="mb-2 text-sm">{r[clave].mensaje}</p>
          <TablaDatos filas={r[clave].filas} idFila={(f) => String(f.id)} nombreArchivo={`pareto-${clave}`} porPagina={15}
            columnas={[
              { id: "nombre", titulo: titulo.slice(0, -1), valor: (f) => f.nombre },
              { id: "clase", titulo: "Clase", valor: (f) => f.clase, render: (f) => <Etiqueta tono={f.clase === "A" ? "acento" : "gris"}>{f.clase}</Etiqueta> },
              { id: "ganancia", titulo: "Ganancia", derecha: true, valor: (f) => f.ganancia, render: (f) => plata(Math.round(f.ganancia)) },
              { id: "part", titulo: "% del total", derecha: true, valor: (f) => f.participacion, render: (f) => `${numero(f.participacion * 100, 1)} %` },
              { id: "acum", titulo: "Acumulado", derecha: true, valor: (f) => f.acumulado, render: (f) => `${numero(f.acumulado * 100, 1)} %`, ocultarEnCelular: true },
            ]} />
        </Tarjeta>
      ))}
    </div>
  );
}
