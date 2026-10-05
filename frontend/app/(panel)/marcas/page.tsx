"use client";
// Marcas representadas (SPEC v2, 12B.6): venta, cobertura y mix por marca, su evolución, y los objetivos de cada marca con la
// bonificación en riesgo («faltan 120 unidades para cobrar $X»).
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Cifra } from "@/components/distribuidor/Cifra";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, Boton, Campo, ComoSeCalcula, Entrada, Etiqueta, Selector, Tabla, Tarjeta, cx } from "@/components/ui";

type Objetivo = { marca: string; tipo: string; desde: string; hasta: string; objetivo: number; logrado: number; avance: number; proyectado: number;
  bonificacion: number; en_riesgo: boolean; falta: number; mensaje: string };
type Marca = { marca: string; venta: number; ganancia: number; margen: number | null; unidades: number; participacion: number | null; variacion: number | null;
  clientes: number; cobertura: number | null; productos_vendidos: number; productos_marca: number; mix: number | null;
  mensual: { mes: string; venta: number }[]; objetivos: Objetivo[] };
type Fila = { id: number; marca: string; desde: string; hasta: string; tipo: string; objetivo: string; bonificacion: string };
type R = { desde: string; hasta: string; marcas: Marca[]; clientes_compradores: number; objetivos: Objetivo[]; todos_los_objetivos: Fila[] };

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${numero(v * 100, 1)} %`);
const TIPOS: Record<string, string> = { volumen: "Volumen (unidades)", cobertura: "Cobertura (clientes)", mix: "Mix (productos distintos)" };
const VACIO = { id: 0, marca: "", desde: "", hasta: "", tipo: "volumen", objetivo: "", bonificacion: "" };

function Barras({ datos }: { datos: { mes: string; venta: number }[] }) {
  const max = Math.max(1, ...datos.map((d) => d.venta));
  return (
    <div className="flex h-8 w-28 items-end gap-px" role="img" aria-label="Venta de los últimos 12 meses">
      {datos.slice(-12).map((d) => <span key={d.mes} title={`${d.mes.slice(0, 7)}: ${plata(Math.round(d.venta))}`} className="flex-1 rounded-t-sm bg-acento/70"
        style={{ height: `${Math.max(2, (d.venta / max) * 100)}%` }} />)}
    </div>
  );
}

export default function Marcas() {
  const { puede } = useSesion();
  const [periodo, setPeriodo] = useState("90d");
  const [r, setR] = useState<R | null>(null);
  const [form, setForm] = useState<typeof VACIO | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cargar = useCallback(() => api<R>(`/distribuidor/marcas?periodo=${periodo}`).then(setR).catch((e) => setError(e.message)), [periodo]);
  useEffect(() => { cargar(); }, [cargar]);

  async function guardar() {
    if (!form) return;
    setError(null);
    const cuerpo = { marca: form.marca, desde: form.desde, hasta: form.hasta, tipo: form.tipo, objetivo: Number(form.objetivo.replace(",", ".")),
      bonificacion: Number((form.bonificacion || "0").replace(/\./g, "").replace(",", ".")) };
    try {
      await api(form.id ? `/distribuidor/objetivos-marca/${form.id}` : "/distribuidor/objetivos-marca", { metodo: form.id ? "PUT" : "POST", cuerpo });
      setForm(null);
      cargar();
    } catch (e) { setError(e instanceof Error ? e.message : "No se pudo guardar."); }
  }
  async function borrar(id: number) {
    if (!confirm("¿Borrar este objetivo?")) return;
    await api(`/distribuidor/objetivos-marca/${id}`, { metodo: "DELETE" });
    cargar();
  }

  const enRiesgo = r?.objetivos.filter((o) => o.en_riesgo) ?? [];
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Marcas</h1>
          <p className="text-sm text-suave">Cuánto vendés de cada marca, a cuántos clientes llega y si vas a cobrar sus bonificaciones.</p>
        </div>
        <Selector className="w-48" value={periodo} onChange={(e) => setPeriodo(e.target.value)} aria-label="Período">
          <option value="mes">Últimos 30 días</option><option value="90d">Últimos 90 días</option><option value="anio">Último año</option>
        </Selector>
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {!r ? <p className="text-sm text-suave">Cargando…</p> : <>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Cifra titulo="Marcas vendidas" valor={numero(r.marcas.length)} nota={`${fechaCorta(r.desde)} al ${fechaCorta(r.hasta)}`} />
          <Cifra titulo="Marca principal" valor={r.marcas[0]?.marca ?? "—"} nota={r.marcas[0] ? `${pct(r.marcas[0].participacion)} de la venta` : undefined} />
          <Cifra titulo="Objetivos vigentes" valor={numero(r.objetivos.length)} nota={`${enRiesgo.length} en riesgo`} tono={enRiesgo.length ? "peligro" : undefined} />
          <Cifra titulo="Bonificaciones en riesgo" valor={plataCorta(enRiesgo.reduce((s, o) => s + o.bonificacion, 0))} nota="si no se cumplen los objetivos" tono={enRiesgo.length ? "peligro" : "ok"} />
        </div>
        {r.objetivos.length > 0 && (
          <Tarjeta titulo="Objetivos vigentes">
            <div className="grid gap-3 md:grid-cols-3">
              {r.objetivos.map((m) => (
                <div key={`${m.marca}${m.desde}${m.tipo}`} className="rounded-xl border border-borde p-3">
                  <div className="flex items-center justify-between gap-2"><strong>{m.marca}</strong>
                    <Etiqueta tono={m.falta === 0 ? "ok" : m.en_riesgo ? "peligro" : "alerta"}>{m.falta === 0 ? "✓ Cumplido" : m.en_riesgo ? "● En riesgo" : "▲ En camino"}</Etiqueta></div>
                  <p className="text-xs text-suave">{TIPOS[m.tipo]} · {fechaCorta(m.desde)} al {fechaCorta(m.hasta)}</p>
                  <div className="mt-2 h-2 rounded-full bg-panel-2"><div className={cx("h-2 rounded-full", m.falta === 0 ? "bg-ok" : m.en_riesgo ? "bg-peligro" : "bg-alerta")}
                    style={{ width: `${Math.min(100, m.avance * 100)}%` }} /></div>
                  <p className="mt-1 text-sm">{numero(m.logrado)} de {numero(m.objetivo)} · bonificación {plata(m.bonificacion)}</p>
                  <p className="text-xs text-suave">{m.mensaje}{m.tipo === "volumen" && m.falta > 0 ? ` A este ritmo cierra en ${numero(m.proyectado)}.` : ""}</p>
                </div>
              ))}
            </div>
          </Tarjeta>
        )}
        <Tarjeta titulo="Venta, cobertura y mix por marca">
          <TablaDatos filas={r.marcas} idFila={(f) => f.marca} nombreArchivo="marcas"
            columnas={[
              { id: "marca", titulo: "Marca", valor: (f) => f.marca, render: (f) => <span className="font-medium">{f.marca}</span> },
              { id: "venta", titulo: "Venta", derecha: true, valor: (f) => f.venta,
                render: (f) => <span>{plataCorta(f.venta)}<div className={cx("text-xs", (f.variacion ?? 0) < 0 ? "text-peligro" : "text-ok")}>
                  {f.variacion === null ? "" : `${f.variacion > 0 ? "▲ +" : "▼ "}${numero(f.variacion * 100, 1)} %`}</div></span> },
              { id: "part", titulo: "Participación", derecha: true, valor: (f) => f.participacion, render: (f) => pct(f.participacion) },
              { id: "margen", titulo: "Margen", derecha: true, valor: (f) => f.margen, render: (f) => pct(f.margen), ocultarEnCelular: true },
              { id: "cobertura", titulo: "Cobertura", derecha: true, valor: (f) => f.cobertura,
                render: (f) => <span>{pct(f.cobertura)}<div className="text-xs text-suave">{f.clientes} de {r.clientes_compradores} clientes</div></span> },
              { id: "mix", titulo: "Mix", derecha: true, valor: (f) => f.mix,
                render: (f) => <span>{pct(f.mix)}<div className="text-xs text-suave">{f.productos_vendidos} de {f.productos_marca} productos</div></span> },
              { id: "evolucion", titulo: "12 meses", valor: (f) => f.venta, render: (f) => <Barras datos={f.mensual} />, ocultarEnCelular: true },
            ]} />
          <ComoSeCalcula>Venta sin IVA de lo entregado (o pedido, si está en camino). Cobertura: clientes que compraron la marca sobre los que compraron algo en el período.
            Mix: productos distintos de la marca que se vendieron sobre los que tenés en el catálogo.</ComoSeCalcula>
        </Tarjeta>
        <Tarjeta titulo="Objetivos de las marcas" accion={puede("gestionar_vendedores") && !form ? <Boton onClick={() => setForm({ ...VACIO })}>Nuevo objetivo</Boton> : undefined}>
          {form && (
            <div className="mb-4 grid gap-2 rounded-xl border border-borde p-3 sm:grid-cols-3">
              <Campo etiqueta="Marca"><Selector value={form.marca} onChange={(e) => setForm({ ...form, marca: e.target.value })}>
                <option value="">Elegí…</option>{r.marcas.map((m) => <option key={m.marca}>{m.marca}</option>)}</Selector></Campo>
              <Campo etiqueta="Tipo"><Selector value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value })}>
                {Object.entries(TIPOS).map(([k, n]) => <option key={k} value={k}>{n}</option>)}</Selector></Campo>
              <Campo etiqueta="Objetivo"><Entrada inputMode="decimal" value={form.objetivo} onChange={(e) => setForm({ ...form, objetivo: e.target.value })} /></Campo>
              <Campo etiqueta="Desde"><Entrada type="date" value={form.desde} onChange={(e) => setForm({ ...form, desde: e.target.value })} /></Campo>
              <Campo etiqueta="Hasta"><Entrada type="date" value={form.hasta} onChange={(e) => setForm({ ...form, hasta: e.target.value })} /></Campo>
              <Campo etiqueta="Bonificación ($)"><Entrada inputMode="decimal" value={form.bonificacion} onChange={(e) => setForm({ ...form, bonificacion: e.target.value })} /></Campo>
              <div className="flex gap-2 sm:col-span-3"><Boton disabled={!form.marca || !form.desde || !form.hasta || !form.objetivo} onClick={guardar}>Guardar</Boton>
                <Boton variante="fantasma" onClick={() => setForm(null)}>Cancelar</Boton></div>
            </div>
          )}
          <Tabla columnas={["Marca", "Tipo", "Período", "Objetivo", "Bonificación", ""]}>
            {r.todos_los_objetivos.map((o) => (
              <tr key={o.id}><td>{o.marca}</td><td>{TIPOS[o.tipo]}</td><td>{fechaCorta(o.desde)} al {fechaCorta(o.hasta)}</td>
                <td className="text-right">{numero(o.objetivo)}</td><td className="text-right">{plata(o.bonificacion)}</td>
                <td>{puede("gestionar_vendedores") && <span className="flex gap-1">
                  <Boton variante="fantasma" onClick={() => setForm({ id: o.id, marca: o.marca, desde: o.desde, hasta: o.hasta, tipo: o.tipo, objetivo: String(Number(o.objetivo)),
                    bonificacion: String(Number(o.bonificacion)) })}>Editar</Boton>
                  <Boton variante="peligro" onClick={() => borrar(o.id)}>Borrar</Boton></span>}</td></tr>
            ))}
          </Tabla>
        </Tarjeta>
      </>}
    </div>
  );
}
