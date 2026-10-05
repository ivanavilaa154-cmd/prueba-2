"use client";
// Agente de sincronización: un programa en la PC del local que sube las exportaciones del sistema de caja desde una carpeta.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaHora, numero } from "@/lib/formato";
import { Aviso, Boton, Campo, Entrada, Etiqueta, Tabla, Tarjeta } from "@/components/ui";

type Agente = { id: number; nombre: string; activo: boolean; version: string | null; equipo: string | null; carpeta: string | null;
  ultima_conexion: string | null; ultima_subida: string | null; archivos_subidos: number; pendientes: number; ultimo_error: string | null;
  ultimo_error_at: string | null; created_at: string };
type Esperando = { id: number; agente_id: number; tipo: string; nombre_archivo: string | null; created_at: string };

// Sin noticias en más de 2 horas: la PC está apagada, sin internet o el agente no corre.
function estado(a: Agente): { texto: string; tono: "ok" | "alerta" | "peligro" | "gris" } {
  if (!a.activo) return { texto: "Revocado", tono: "gris" };
  if (!a.ultima_conexion) return { texto: "Nunca se conectó", tono: "gris" };
  if (Date.now() - new Date(a.ultima_conexion).getTime() > 2 * 3600 * 1000) return { texto: "Sin noticias", tono: "peligro" };
  if (a.pendientes > 0) return { texto: `${a.pendientes} en cola`, tono: "alerta" };
  return { texto: "✓ Conectado", tono: "ok" };
}

export function AgenteSincronizacion() {
  const [agentes, setAgentes] = useState<Agente[]>([]);
  const [esperando, setEsperando] = useState<Esperando[]>([]);
  const [nombre, setNombre] = useState("PC de la caja");
  const [token, setToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(() => api<{ agentes: Agente[]; esperando_columnas: Esperando[] }>("/agentes")
    .then((r) => { setAgentes(r.agentes); setEsperando(r.esperando_columnas); }).catch(() => {}), []);
  useEffect(() => { cargar(); }, [cargar]);

  async function crear() {
    setError(null);
    try {
      const r = await api<{ token: string }>("/agentes", { metodo: "POST", cuerpo: { nombre } });
      setToken(r.token);
      cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo crear.");
    }
  }
  async function revocar(id: number) {
    if (!confirm("¿Revocar este agente? Deja de poder subir archivos; lo ya importado queda.")) return;
    await api(`/agentes/${id}`, { metodo: "DELETE" });
    cargar();
  }

  return (
    <Tarjeta titulo="Agente de sincronización (sistema de caja en una PC)">
      <p className="text-sm text-suave">
        Si tu sistema de caja no tiene internet ni API, instalá el agente en la PC del local: mira la carpeta donde el sistema deja sus exportaciones
        (ventas_…, stock_…, productos_…, compras_…, precios_…) y las sube solas por HTTPS. Sin internet, guarda los archivos y los manda cuando vuelve.
        La primera vez que llega un formato nuevo tenés que confirmar sus columnas; después entran solos.
      </p>
      {error && <div className="mt-3"><Aviso tipo="error">{error}</Aviso></div>}
      {token && (
        <div className="mt-3">
          <Aviso tipo="alerta">
            Copiá este token ahora: no se vuelve a mostrar. Pegalo en <code>agente.ini</code> de la PC del local.
            <code className="mt-2 block break-all rounded bg-panel-2 p-2 text-xs">{token}</code>
          </Aviso>
        </div>
      )}
      {esperando.length > 0 && (
        <div className="mt-3">
          <Aviso tipo="alerta">
            {esperando.length === 1 ? "Un archivo espera" : `${esperando.length} archivos esperan`} que confirmes sus columnas:
            <ul className="mt-1 list-disc pl-5">
              {esperando.map((l) => (
                <li key={l.id}><a className="text-acento underline" href={`#importar?lote=${l.id}`}>{l.nombre_archivo ?? `archivo ${l.id}`}</a>
                  <span className="text-suave"> · {l.tipo} · {fechaHora(l.created_at)}</span></li>
              ))}
            </ul>
          </Aviso>
        </div>
      )}
      {agentes.length > 0 && (
        <div className="mt-3">
          <Tabla columnas={["Agente", "Estado", "Última conexión", "Archivos", ""]}>
            {agentes.map((a) => {
              const e = estado(a);
              return (
                <tr key={a.id} className="align-top">
                  <td>{a.nombre}<div className="text-xs text-suave">{[a.equipo, a.carpeta, a.version && `v${a.version}`].filter(Boolean).join(" · ") || "—"}</div></td>
                  <td><Etiqueta tono={e.tono}>{e.texto}</Etiqueta>
                    {a.activo && a.ultimo_error && <div className="mt-1 max-w-xs text-xs text-peligro">{a.ultimo_error}</div>}</td>
                  <td className="whitespace-nowrap">{a.ultima_conexion ? fechaHora(a.ultima_conexion) : "—"}
                    {a.ultima_subida && <div className="text-xs text-suave">última subida {fechaHora(a.ultima_subida)}</div>}</td>
                  <td>{numero(a.archivos_subidos)}</td>
                  <td>{a.activo && <Boton variante="peligro" onClick={() => revocar(a.id)}>Revocar</Boton>}</td>
                </tr>
              );
            })}
          </Tabla>
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <Campo etiqueta="Nombre del agente"><Entrada value={nombre} onChange={(e) => setNombre(e.target.value)} /></Campo>
        <Boton disabled={nombre.trim().length < 2} onClick={crear}>Crear agente</Boton>
      </div>
    </Tarjeta>
  );
}
