"use client";
// Pedir ayuda a la plataforma (13.7: cada pedido queda registrado por empresa para medir el soporte).
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { Aviso, Boton, Campo, Entrada, Etiqueta, Selector, Tarjeta } from "@/components/ui";

type Ticket = { id: number; asunto: string; tema: string; estado: string; respuesta: string | null; created_at: string; resuelto_at: string | null };
export const TEMAS: Record<string, string> = { uso: "Cómo usar algo", datos: "Carga de datos", conexion: "Conexión con la caja u Odoo",
  error: "Algo no funciona", implementacion: "Puesta en marcha", facturacion: "Plan y pagos", otro: "Otro" };

export function Ayuda() {
  const [lista, setLista] = useState<Ticket[]>([]);
  const [f, setF] = useState({ asunto: "", detalle: "", tema: "uso" });
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const cargar = useCallback(() => api<Ticket[]>("/soporte").then(setLista).catch(() => {}), []);
  useEffect(() => { cargar(); }, [cargar]);
  async function enviar() {
    try {
      const r = await api<{ mensaje: string }>("/soporte", { metodo: "POST", cuerpo: { ...f, detalle: f.detalle || null } });
      setMensaje({ tipo: "ok", texto: r.mensaje });
      setF({ asunto: "", detalle: "", tema: "uso" });
      cargar();
    } catch (e) { setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo enviar." }); }
  }
  return (
    <div className="grid gap-4">
      <Tarjeta titulo="Pedir ayuda">
        <div className="grid max-w-xl gap-3">
          {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
          <Campo etiqueta="Tema"><Selector value={f.tema} onChange={(e) => setF({ ...f, tema: e.target.value })}>
            {Object.entries(TEMAS).map(([k, n]) => <option key={k} value={k}>{n}</option>)}</Selector></Campo>
          <Campo etiqueta="¿Qué necesitás?"><Entrada value={f.asunto} onChange={(e) => setF({ ...f, asunto: e.target.value })} /></Campo>
          <Campo etiqueta="Detalle (opcional)">
            <textarea className="min-h-24 rounded-lg border border-borde bg-panel px-3 py-2 text-sm" value={f.detalle} onChange={(e) => setF({ ...f, detalle: e.target.value })} />
          </Campo>
          <div><Boton disabled={f.asunto.trim().length < 3} onClick={enviar}>Enviar</Boton></div>
        </div>
      </Tarjeta>
      {lista.length > 0 && (
        <Tarjeta titulo="Tus pedidos de ayuda">
          <ul className="grid gap-2 text-sm">
            {lista.map((t) => (
              <li key={t.id} className="rounded-lg border border-borde p-2">
                <div className="flex justify-between gap-2"><strong>{t.asunto}</strong>
                  <Etiqueta tono={t.estado === "resuelto" ? "ok" : "alerta"}>{t.estado === "resuelto" ? "✓ Resuelto" : "▲ Abierto"}</Etiqueta></div>
                <p className="text-xs text-suave">{TEMAS[t.tema] ?? t.tema} · {fechaHora(t.created_at)}</p>
                {t.respuesta && <p className="mt-1">{t.respuesta}</p>}
              </li>
            ))}
          </ul>
        </Tarjeta>
      )}
    </div>
  );
}
