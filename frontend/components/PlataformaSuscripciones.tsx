"use client";
// Administración de la plataforma (13.6): plan y estado de cada empresa, registrar pagos y editar los planes.
import { useCallback, useEffect, useState } from "react";
import { api, type Suscripcion } from "@/lib/api";
import { fecha, parsearMonto, plata } from "@/lib/formato";
import { Aviso, Boton, Campo, Entrada, Etiqueta, Selector, Tabla, Tarjeta } from "@/components/ui";

type PlanFila = { codigo: string; nombre: string; max_sucursales: number | null; modulos: string[]; precio_mensual: string | null };
type Empresa = Suscripcion & { id: number; nombre: string };
type Datos = { planes: PlanFila[]; modulos: Record<string, string>; medios: string[]; empresas: Empresa[] };

export function PlataformaSuscripciones() {
  const [d, setD] = useState<Datos | null>(null);
  const [pago, setPago] = useState<{ org: number; plan: string; monto: string; medio: string; cubre_hasta: string } | null>(null);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const cargar = useCallback(() => api<Datos>("/plataforma/suscripciones").then(setD).catch((e) => setMensaje({ tipo: "error", texto: e.message })), []);
  useEffect(() => { cargar(); }, [cargar]);
  async function hacer(f: () => Promise<unknown>, ok: string) {
    setMensaje(null);
    try { await f(); setMensaje({ tipo: "ok", texto: ok }); await cargar(); } catch (e) { setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo." }); }
  }
  if (!d) return null;
  const pagos = d.planes.filter((p) => p.codigo !== "prueba");
  const enUnMes = new Date(Date.now() + 31 * 864e5).toISOString().slice(0, 10);
  return (
    <>
      <Tarjeta titulo="Suscripciones">
        {mensaje && <div className="mb-3"><Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso></div>}
        <Tabla columnas={["Empresa", "Plan", "Estado", "Sucursales", ""]}>
          {d.empresas.map((e) => (
            <tr key={e.id}>
              <td>{e.nombre}</td>
              <td>
                <Selector aria-label={`Plan de ${e.nombre}`} value={e.plan} onChange={(x) => hacer(() => api(`/plataforma/empresas/${e.id}/plan`, { metodo: "PUT", cuerpo: { plan: x.target.value } }), "Plan cambiado.")}>
                  {d.planes.map((p) => <option key={p.codigo} value={p.codigo}>{p.nombre}</option>)}
                </Selector>
              </td>
              <td>{e.al_dia ? <Etiqueta tono={e.por_vencer ? "alerta" : "ok"}>{e.en_prueba ? "Prueba" : "Al día"} hasta {fecha(e.hasta)}</Etiqueta>
                : <Etiqueta tono="peligro">Vencida {fecha(e.hasta)} · solo lectura</Etiqueta>}</td>
              <td>{e.sucursales} / {e.max_sucursales ?? "∞"}</td>
              <td><Boton variante="secundario" onClick={() => setPago({ org: e.id, plan: e.plan === "prueba" ? pagos[0]?.codigo ?? "" : e.plan, monto: "", medio: "transferencia", cubre_hasta: enUnMes })}>Registrar pago</Boton></td>
            </tr>
          ))}
        </Tabla>
        {pago && (
          <div className="mt-3 grid grid-cols-1 gap-3 rounded-xl border border-borde p-3 sm:grid-cols-2 lg:grid-cols-5">
            <Campo etiqueta="Plan"><Selector value={pago.plan} onChange={(x) => setPago({ ...pago, plan: x.target.value })}>{pagos.map((p) => <option key={p.codigo} value={p.codigo}>{p.nombre}</option>)}</Selector></Campo>
            <Campo etiqueta="Monto"><Entrada inputMode="decimal" value={pago.monto} onChange={(x) => setPago({ ...pago, monto: x.target.value })} /></Campo>
            <Campo etiqueta="Medio"><Selector value={pago.medio} onChange={(x) => setPago({ ...pago, medio: x.target.value })}>{d.medios.map((m) => <option key={m} value={m}>{m.replace("_", " ")}</option>)}</Selector></Campo>
            <Campo etiqueta="Cubre hasta"><Entrada type="date" value={pago.cubre_hasta} onChange={(x) => setPago({ ...pago, cubre_hasta: x.target.value })} /></Campo>
            <div className="flex items-end gap-2">
              <Boton disabled={!pago.monto || !pago.plan} onClick={() => hacer(() => api(`/plataforma/empresas/${pago.org}/pagos`, { metodo: "POST",
                cuerpo: { plan: pago.plan, monto: parsearMonto(pago.monto), medio: pago.medio, cubre_hasta: pago.cubre_hasta } }).then(() => setPago(null)), "Pago registrado: la empresa quedó al día.")}>Guardar</Boton>
              <Boton variante="fantasma" onClick={() => setPago(null)}>Cancelar</Boton>
            </div>
          </div>
        )}
      </Tarjeta>
      <Tarjeta titulo="Planes y precios">
        <Tabla columnas={["Plan", "Sucursales máx.", "Módulos", "Precio por mes", ""]}>
          {pagos.map((p) => <FilaPlan key={p.codigo} p={p} modulos={d.modulos} guardar={(x) => hacer(() => api(`/plataforma/planes/${p.codigo}`, { metodo: "PUT", cuerpo: x }), "Plan guardado.")} />)}
        </Tabla>
        <p className="mt-2 text-xs text-suave">Precio vacío = «a definir». El cobro automático con Mercado Pago se activa cuando cargues la cuenta de la plataforma; mientras tanto registrá cada pago acá.</p>
      </Tarjeta>
    </>
  );
}

function FilaPlan({ p, modulos, guardar }: { p: PlanFila; modulos: Record<string, string>; guardar: (x: object) => void }) {
  const [f, setF] = useState({ nombre: p.nombre, max: p.max_sucursales?.toString() ?? "", precio: p.precio_mensual ?? "", modulos: p.modulos });
  return (
    <tr>
      <td><Entrada aria-label="Nombre" value={f.nombre} onChange={(x) => setF({ ...f, nombre: x.target.value })} /></td>
      <td><Entrada aria-label="Sucursales máximas" inputMode="numeric" placeholder="Sin límite" value={f.max} onChange={(x) => setF({ ...f, max: x.target.value })} /></td>
      <td className="whitespace-nowrap">{Object.entries(modulos).map(([k, v]) => (
        <label key={k} className="mr-3 text-xs"><input type="checkbox" disabled={k === "base"} checked={f.modulos.includes(k)}
          onChange={(x) => setF({ ...f, modulos: x.target.checked ? [...f.modulos, k] : f.modulos.filter((m) => m !== k) })} /> {v}</label>
      ))}</td>
      <td><Entrada aria-label="Precio" inputMode="decimal" placeholder="A definir" value={f.precio} onChange={(x) => setF({ ...f, precio: x.target.value })} />
        {p.precio_mensual && <span className="text-xs text-suave">{plata(p.precio_mensual)}</span>}</td>
      <td><Boton variante="secundario" onClick={() => guardar({ nombre: f.nombre, max_sucursales: f.max ? Number(f.max) : null, modulos: f.modulos,
        precio_mensual: f.precio ? parsearMonto(f.precio) : null })}>Guardar</Boton></td>
    </tr>
  );
}
