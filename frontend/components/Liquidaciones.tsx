"use client";
// Liquidaciones activas: una fila por producto y sucursal con ubicación, descuento, stock, vaciado proyectado, ejecución y acción.
import { useCallback, useEffect, useState } from "react";
import { api, BASE } from "@/lib/api";
import { fecha, fechaHora, numero, plata } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, ComoSeCalcula, Etiqueta, Selector, Tabla, Tarjeta, Vacio } from "@/components/ui";

type F = { id: number; nombre: string; producto: string; codigo_interno: string; origen: string; desde: string; hasta: string; ubicacion: string; ubicacion_id: number;
  descuento: number; precio_oferta: string; precio_normal: string; stock_inicial: number | null; vendidas: number; stock: number; ritmo_diario: number;
  ritmo_origen: string; dias_restantes: number; vaciado_proyectado: string | null; llega_a_tiempo: boolean; exhibicion: string; capacidad_exhibicion: number | null;
  reponer_cada_horas: number | null; ejecucion: string; ultimo_control: { armada: boolean; cartel: boolean; precio_ok: boolean; foto: string | null; created_at: string } | null;
  diferencias_precio: number; diferencia_plata: string; accion: string; accion_texto: string; escalon_siguiente: number | null };
type R = { filas: F[]; resumen: { activas: number; no_llegan: number; sin_control: number; diferencias_precio: number; stock_por_liquidar: number };
  exhibicion: Record<string, { factor: number; casos: number; medido: boolean }> };
const EXHIB: Record<string, string> = { puntera: "Puntera", isla: "Isla", gondola: "Góndola" };
const TONO: Record<string, "peligro" | "alerta" | "ok" | "gris"> = { corregir_precio: "peligro", controlar: "alerta", bajar_escalon: "alerta", mover: "alerta",
  reponer: "alerta", revisar: "peligro", cerrar: "gris", seguir: "ok" };

export function Liquidaciones() {
  const { puede } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [control, setControl] = useState<F | null>(null);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const cargar = useCallback(() => api<R>("/liquidaciones").then(setR).catch(() => {}), []);
  useEffect(() => { cargar(); }, [cargar]);
  async function hacer(f: () => Promise<{ mensaje?: string } | unknown>, ok: string) {
    setMensaje(null);
    try { const x = await f() as { mensaje?: string }; setMensaje({ tipo: "ok", texto: x?.mensaje ?? ok }); cargar(); }
    catch (e) { setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo." }); }
  }
  async function enviarControl(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!control) return;
    const datos = new FormData(e.currentTarget);
    datos.set("ubicacion_id", String(control.ubicacion_id));
    for (const k of ["armada", "cartel", "precio_ok"]) datos.set(k, datos.get(k) ? "true" : "false");
    await hacer(() => api(`/liquidaciones/${control.id}/control`, { formulario: datos }), "Control guardado.");
    setControl(null);
  }
  if (!r) return null;
  return (
    <Tarjeta titulo={`Liquidaciones activas · ${r.resumen.activas}`}>
      {mensaje && <div className="mb-3"><Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso></div>}
      {r.filas.length === 0 ? <Vacio titulo="No hay liquidaciones activas">Creá una oferta desde los lotes por vencer o desde Plata parada.</Vacio> : (
        <>
          <p className="mb-3 text-sm text-suave">{numero(r.resumen.stock_por_liquidar)} unidades por liquidar · {r.resumen.no_llegan} no llegan a vaciarse a tiempo ·
            {" "}{r.resumen.sin_control} sin control al día · {r.resumen.diferencias_precio} cobros por encima del precio de oferta.</p>
          <Tabla columnas={["Producto", "Ubicación", "Oferta", "Stock", "Vaciado", "Ejecución", "Qué hacer"]}>
            {r.filas.map((f) => (
              <tr key={`${f.id}-${f.ubicacion_id}`} className="align-top">
                <td>{f.producto}<span className="block text-xs text-suave">{f.codigo_interno} · {f.ubicacion}</span></td>
                <td>{EXHIB[f.exhibicion] ?? f.exhibicion}{f.reponer_cada_horas ? <span className="block text-xs text-suave">reponer cada {numero(f.reponer_cada_horas, 1)} h</span> : null}</td>
                <td className="whitespace-nowrap">{numero(f.descuento * 100)} % · {plata(f.precio_oferta)}<span className="block text-xs text-suave">hasta {fecha(f.hasta)} ({f.dias_restantes} d)</span></td>
                <td className="text-right">{numero(f.stock)}<span className="block text-xs text-suave">vendidas {numero(f.vendidas)} · {numero(f.ritmo_diario, 1)}/día{f.ritmo_origen === "estimado" ? " (estimado)" : ""}</span></td>
                <td className="whitespace-nowrap">{f.vaciado_proyectado ? fecha(f.vaciado_proyectado) : "—"}
                  <span className="block text-xs">{f.llega_a_tiempo ? <span className="text-ok">✓ a tiempo</span> : <span className="text-peligro">▲ no llega</span>}</span></td>
                <td>{f.ejecucion === "ok" ? <Etiqueta tono="ok">✓ Armada</Etiqueta> : f.ejecucion === "con_fallas" ? <Etiqueta tono="alerta">Con fallas</Etiqueta> : <Etiqueta>Sin control</Etiqueta>}
                  {f.ultimo_control && <span className="block text-xs text-suave">{fechaHora(f.ultimo_control.created_at)}{f.ultimo_control.foto && <> · <a className="text-acento underline" target="_blank" rel="noreferrer" href={`${BASE}/api/liquidaciones/fotos/${f.ultimo_control.foto}`}>foto</a></>}</span>}
                  {f.diferencias_precio > 0 && <span className="block text-xs text-peligro">▲ {f.diferencias_precio} cobros de más ({plata(f.diferencia_plata)})</span>}</td>
                <td className="min-w-[14rem]">
                  <Etiqueta tono={TONO[f.accion] ?? "gris"}>{f.accion_texto}</Etiqueta>
                  <div className="mt-1 flex flex-wrap gap-2 text-sm">
                    {f.escalon_siguiente && puede("remarcar") && <button className="text-acento underline" onClick={() => hacer(() => api(`/liquidaciones/${f.id}/escalon`, { metodo: "POST" }), "")}>Bajar a {numero(f.escalon_siguiente * 100)} %</button>}
                    {puede("recuentos") && <button className="text-acento underline" onClick={() => setControl(f)}>Controlar</button>}
                    {puede("recuentos") && f.capacidad_exhibicion && <button className="text-acento underline" onClick={() => {
                      const d = new FormData(); d.set("ubicacion_id", String(f.ubicacion_id)); d.set("tipo", "reposicion");
                      hacer(() => api(`/liquidaciones/${f.id}/control`, { formulario: d }), "Reposición registrada.");
                    }}>Repuse</button>}
                    <a className="text-acento underline" href={`${BASE}/api/ofertas/${f.id}/cartel?tamano=a5`} target="_blank" rel="noreferrer">Cartel</a>
                  </div>
                </td>
              </tr>
            ))}
          </Tabla>
        </>
      )}
      {control && (
        <form onSubmit={enviarControl} className="mt-3 grid gap-2 rounded-xl border border-borde p-3 text-sm">
          <p className="font-medium">Control de {control.producto} en {control.ubicacion}</p>
          <label><input type="checkbox" name="armada" defaultChecked /> Exhibición armada y llena</label>
          <label><input type="checkbox" name="cartel" defaultChecked /> Cartel con el precio de oferta</label>
          <label><input type="checkbox" name="precio_ok" defaultChecked /> Precio cargado en la caja ({plata(control.precio_oferta)})</label>
          <label className="grid gap-1">Ubicación
            <Selector name="exhibicion_actual" defaultValue={control.exhibicion} onChange={(e) => {
              const d = new FormData(); d.set("ubicacion_id", String(control.ubicacion_id)); d.set("tipo", "exhibicion"); d.set("exhibicion", e.target.value);
              hacer(() => api(`/liquidaciones/${control.id}/control`, { formulario: d }), "Ubicación actualizada.");
            }}>{Object.entries(EXHIB).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Selector></label>
          <label className="grid gap-1">Foto (opcional)<input type="file" name="foto" accept="image/jpeg,image/png,image/webp" capture="environment" /></label>
          <div className="flex gap-2"><Boton type="submit">Guardar control</Boton><Boton type="button" variante="fantasma" onClick={() => setControl(null)}>Cancelar</Boton></div>
        </form>
      )}
      <div className="mt-3">
        <ComoSeCalcula>
          <p>Vaciado proyectado = stock ÷ ritmo de venta desde que empezó la oferta (los primeros 2 días, estimado con el pronóstico, el descuento y la exhibición).</p>
          <p>Venta extra por ubicación: puntera ×{numero(r.exhibicion.puntera?.factor ?? 1.35, 2)}, isla ×{numero(r.exhibicion.isla?.factor ?? 1.2, 2)}, góndola ×{numero(r.exhibicion.gondola?.factor ?? 1, 2)}
            {Object.values(r.exhibicion).some((x) => x.medido) ? " (medido en tus liquidaciones)" : " (valores de partida hasta medir 3 liquidaciones de cada tipo)"}.</p>
          <p>Diferencias de precio: ventas posteriores a la oferta cobradas más de 1 % por encima del precio de oferta. Bajar un escalón cambia el precio de la oferta acá; el de la caja lo cargás vos.</p>
        </ComoSeCalcula>
      </div>
    </Tarjeta>
  );
}
