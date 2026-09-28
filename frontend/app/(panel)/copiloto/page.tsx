"use client";
// Copiloto (sección 13.2): preguntas en español sobre los datos; responde con cifras de sus herramientas y propone acciones para confirmar.
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { numero } from "@/lib/formato";
import { Aviso, Boton, Etiqueta, Tarjeta } from "@/components/ui";

type Item = { producto_id: number; ubicacion_id: number; cantidad?: number; descuento?: number; hasta?: string; producto: string; sucursal: string };
type Propuesta = { tipo: "orden_compra" | "transferencia" | "oferta"; motivo: string; items: Item[] };
type Mensaje = { rol: "usuario" | "copiloto"; texto: string; herramientas?: { herramienta: string; entrada: Record<string, unknown> }[]; propuestas?: Propuesta[] };
type R = { texto: string; herramientas: Mensaje["herramientas"]; propuestas: Propuesta[]; historial: unknown[] };

const SUGERENCIAS = ["¿Cuánto vendí hoy contra el mismo día de la semana pasada?", "¿Qué me conviene comprar esta semana?",
  "¿Cuáles son mis 10 productos que más ganancia dejan este mes?", "¿Dónde tengo plata parada?", "¿Qué avisos importantes tengo abiertos?"];
const NOMBRE_HERRAMIENTA: Record<string, string> = { contexto: "fecha y sucursales", ventas: "ventas", ranking_productos: "ranking de productos",
  buscar_producto: "búsqueda de productos", explicar_sugerencia: "cálculo de la sugerencia", que_comprar: "qué comprar", alertas_abiertas: "avisos",
  plata_parada: "plata parada", proponer_accion: "propuesta" };
const NOMBRE_ACCION = { orden_compra: "Crear borrador de orden de compra", transferencia: "Crear transferencia", oferta: "Crear oferta" };

function PropuestaAccion({ p }: { p: Propuesta }) {
  const [estado, setEstado] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  async function confirmar() {
    try {
      if (p.tipo === "oferta") {
        for (const i of p.items) {
          await api("/ofertas", { metodo: "POST", cuerpo: { producto_id: i.producto_id, ubicacion_id: i.ubicacion_id, descuento: i.descuento ?? 0.1,
            hasta: i.hasta ?? new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10), origen: "sobrestock" } });
        }
        setEstado({ tipo: "ok", texto: "Oferta creada. Está en Vencimientos y ofertas." });
      } else {
        await api("/documentos/desde-seleccion", { metodo: "POST", cuerpo: { tipo: p.tipo, items: p.items.map((i) => ({ producto_id: i.producto_id, ubicacion_id: i.ubicacion_id, cantidad: i.cantidad })) } });
        setEstado({ tipo: "ok", texto: "Borrador creado. Revisalo y aprobalo en Transferencias y OC." });
      }
    } catch (e) {
      setEstado({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo crear." });
    }
  }
  return (
    <div className="mt-2 rounded-lg border border-acento/40 bg-acento/5 p-3 text-sm">
      <p className="font-medium">{NOMBRE_ACCION[p.tipo]}: {p.motivo}</p>
      <ul className="mt-1 list-disc pl-5">
        {p.items.map((i) => <li key={`${i.producto_id}-${i.ubicacion_id}`}>{i.producto} · {i.sucursal}{i.cantidad ? ` · ${numero(i.cantidad)} u` : ""}{i.descuento ? ` · ${numero(i.descuento * 100)} % off` : ""}</li>)}
      </ul>
      {estado ? <div className="mt-2"><Aviso tipo={estado.tipo}>{estado.texto}</Aviso></div> : <Boton className="mt-2" onClick={confirmar}>Confirmar</Boton>}
    </div>
  );
}

export default function Copiloto() {
  const [mensajes, setMensajes] = useState<Mensaje[]>([]);
  const [historial, setHistorial] = useState<unknown[]>([]);
  const [texto, setTexto] = useState("");
  const [pensando, setPensando] = useState(false);
  const fin = useRef<HTMLDivElement>(null);
  useEffect(() => { fin.current?.scrollIntoView({ behavior: "smooth" }); }, [mensajes, pensando]);

  async function preguntar(pregunta: string) {
    if (!pregunta.trim() || pensando) return;
    setMensajes((m) => [...m, { rol: "usuario", texto: pregunta }]);
    setTexto("");
    setPensando(true);
    try {
      const r = await api<R>("/copiloto", { metodo: "POST", cuerpo: { mensaje: pregunta, historial } });
      setHistorial(r.historial);
      setMensajes((m) => [...m, { rol: "copiloto", texto: r.texto, herramientas: r.herramientas, propuestas: r.propuestas }]);
    } catch (e) {
      setMensajes((m) => [...m, { rol: "copiloto", texto: e instanceof Error ? e.message : "No pude responder." }]);
    } finally {
      setPensando(false);
    }
  }

  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Copiloto</h1>
          <p className="text-sm text-suave">Preguntale a tus datos. Responde solo con cifras de la plataforma y te dice de qué período son.</p>
        </div>
        {mensajes.length > 0 && <Boton variante="secundario" onClick={() => { setMensajes([]); setHistorial([]); }}>Nueva conversación</Boton>}
      </div>
      <Tarjeta>
        <div className="grid max-h-[60vh] min-h-[16rem] gap-3 overflow-y-auto">
          {mensajes.length === 0 && (
            <div className="grid gap-2">
              <p className="text-sm text-suave">Por ejemplo:</p>
              {SUGERENCIAS.map((s) => <button key={s} className="rounded-lg border border-borde px-3 py-2 text-left text-sm hover:bg-panel-2" onClick={() => preguntar(s)}>{s}</button>)}
            </div>
          )}
          {mensajes.map((m, i) => (
            <div key={i} className={m.rol === "usuario" ? "justify-self-end" : "justify-self-start"}>
              <div className={m.rol === "usuario" ? "max-w-prose rounded-2xl bg-acento px-4 py-2 text-acento-texto" : "max-w-prose rounded-2xl bg-panel-2 px-4 py-2"}>
                <p className="whitespace-pre-wrap text-sm">{m.texto}</p>
              </div>
              {m.herramientas && m.herramientas.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  <span className="text-xs text-suave">Consultó:</span>
                  {[...new Set(m.herramientas.map((h) => h.herramienta))].map((h) => <Etiqueta key={h}>{NOMBRE_HERRAMIENTA[h] ?? h}</Etiqueta>)}
                </div>
              )}
              {m.propuestas?.map((p, j) => <PropuestaAccion key={j} p={p} />)}
            </div>
          ))}
          {pensando && <p className="text-sm text-suave" role="status">Buscando en tus datos…</p>}
          <div ref={fin} />
        </div>
        <form className="mt-3 flex gap-2" onSubmit={(e) => { e.preventDefault(); preguntar(texto); }}>
          <input className="min-h-10 flex-1 rounded-lg border border-borde bg-panel px-3 text-sm" placeholder="Escribí tu pregunta…" value={texto}
            onChange={(e) => setTexto(e.target.value)} aria-label="Pregunta" maxLength={2000} />
          <Boton type="submit" disabled={pensando || !texto.trim()}>Preguntar</Boton>
        </form>
      </Tarjeta>
    </div>
  );
}
