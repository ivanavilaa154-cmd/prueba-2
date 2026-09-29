"use client";
// Privacidad (13.5): descargar los datos de la empresa, pedir la baja con plazo de arrepentimiento y suprimir datos de un cliente final.
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, BASE } from "@/lib/api";
import { fecha, fechaHora } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Campo, Entrada, Tabla, Tarjeta } from "@/components/ui";

type Estado = { version: string; aceptada: boolean; aceptada_at: string | null; baja: { solicitada: string; se_borra: string } | null; dias_baja: number };
type Cliente = { id: number; identificador: string | null; nombre: string | null; alta: string };

export function TusDatos() {
  const { yo } = useSesion();
  const [e, setE] = useState<Estado | null>(null);
  const [confirmacion, setConfirmacion] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [clientes, setClientes] = useState<Cliente[]>([]);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const cargar = useCallback(() => api<Estado>("/privacidad").then(setE).catch(() => {}), []);
  useEffect(() => { cargar(); }, [cargar]);

  async function accion(f: () => Promise<unknown>, ok: string) {
    setMensaje(null);
    try { await f(); setMensaje({ tipo: "ok", texto: ok }); cargar(); } catch (err) { setMensaje({ tipo: "error", texto: err instanceof Error ? err.message : "No se pudo." }); }
  }
  async function buscar() {
    setClientes(await api<Cliente[]>(`/clientes/buscar?q=${encodeURIComponent(busqueda)}`).catch(() => []));
  }
  if (!e) return <p className="text-sm text-suave">Cargando…</p>;
  const nombre = yo.empresa?.nombre ?? "";
  return (
    <div className="grid grid-cols-1 gap-4">
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
      <Tarjeta titulo="Descargar los datos de tu empresa">
        <p className="text-sm text-suave">Un archivo ZIP con un CSV por tabla: ventas, stock, productos, compras, usuarios, auditoría… Sin claves ni credenciales.
          Es tu derecho de acceso (Ley 25.326).</p>
        <div className="mt-3"><a className="inline-flex min-h-9 items-center rounded-lg bg-acento px-3.5 py-1.5 text-sm font-medium text-acento-texto" href={`${BASE}/api/empresa/exportar`}>Descargar mis datos</a></div>
      </Tarjeta>
      <Tarjeta titulo="Suprimir los datos de un cliente">
        <p className="text-sm text-suave">Si un cliente te pide que borres sus datos: se borran su nombre y su identificador; sus compras quedan sin identificar (tus ventas no cambian).</p>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <Campo etiqueta="Nombre, DNI o identificador"><Entrada value={busqueda} onChange={(x) => setBusqueda(x.target.value)} /></Campo>
          <Boton variante="secundario" disabled={busqueda.trim().length < 3} onClick={buscar}>Buscar</Boton>
        </div>
        {clientes.length > 0 && (
          <div className="mt-3">
            <Tabla columnas={["Cliente", "Identificador", "Alta", ""]}>
              {clientes.map((c) => (
                <tr key={c.id}><td>{c.nombre ?? "—"}</td><td>{c.identificador}</td><td>{fecha(c.alta)}</td>
                  <td><Boton variante="peligro" onClick={() => { if (confirm(`¿Suprimir los datos de ${c.nombre ?? c.identificador}? No se puede deshacer.`))
                    void accion(() => api(`/clientes/${c.id}/suprimir`, { metodo: "POST" }).then(buscar), "Datos del cliente suprimidos."); }}>Suprimir</Boton></td></tr>
              ))}
            </Tabla>
          </div>
        )}
      </Tarjeta>
      <Tarjeta titulo="Dar de baja la empresa">
        {e.baja ? (
          <>
            <Aviso tipo="alerta">Pediste la baja el {fechaHora(e.baja.solicitada)}. El {fecha(e.baja.se_borra)} se borran la empresa y todos sus datos. Hasta ese día podés arrepentirte.</Aviso>
            <div className="mt-3"><Boton onClick={() => accion(() => api("/empresa/baja", { metodo: "DELETE" }), "Baja cancelada: la empresa sigue igual.")}>Cancelar la baja</Boton></div>
          </>
        ) : (
          <>
            <p className="text-sm text-suave">Se borran la empresa, sus sucursales, usuarios y todos sus datos {e.dias_baja} días después de pedirlo (antes podés cancelarlo).
              Te conviene descargar tus datos primero.</p>
            <div className="mt-3 flex flex-wrap items-end gap-2">
              <Campo etiqueta={`Para confirmar escribí «${nombre}»`}><Entrada value={confirmacion} onChange={(x) => setConfirmacion(x.target.value)} /></Campo>
              <Boton variante="peligro" disabled={confirmacion.trim().toLowerCase() !== nombre.trim().toLowerCase()}
                onClick={() => accion(() => api("/empresa/baja", { metodo: "POST", cuerpo: { confirmacion } }), "Baja pedida.")}>Pedir la baja</Boton>
            </div>
          </>
        )}
      </Tarjeta>
      <p className="text-xs text-suave">Aceptaste la <Link className="text-acento underline" href="/privacidad/">política de privacidad</Link> versión {e.version}
        {e.aceptada_at ? ` el ${fechaHora(e.aceptada_at)}` : ""}.</p>
    </div>
  );
}
