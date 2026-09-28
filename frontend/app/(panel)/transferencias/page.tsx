"use client";
// Transferencias y órdenes de compra (sección 7): sugeridas, aprobación por límite, envío (lo confirma una persona) y recepción.
import { useCallback, useEffect, useState } from "react";
import { api, BASE } from "@/lib/api";
import { fechaCorta, fechaHora, numero, plata, plataCorta } from "@/lib/formato";
import { Panel } from "@/components/Panel";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, Boton, ComoSeCalcula, Entrada, Etiqueta, Tabla, Tarjeta, cx } from "@/components/ui";

type Resumen = {
  ordenes: OC[]; transferencias: TR[]; limites: { orden_compra: string | null; transferencia: string | null };
  presupuesto: string | null; comprometido: string;
  puede_comprar: boolean; puede_aprobar_oc: boolean; puede_transferir: boolean; puede_recibir: boolean;
};
type OC = { id: number; numero: string; estado: string; origen: string; total: string; fecha_esperada: string | null; aprobacion: string | null;
  escalada_at: string | null; proveedor: string; ubicacion: string; lineas: number; explicacion: Record<string, unknown> };
type TR = { id: number; numero: string; estado: string; motivo: string; valor: string; aprobacion: string | null; origen: string; destino: string; lineas: number };
type LineaOC = { id: number; producto_id: number; ubicacion_id: number | null; nombre: string; codigo_interno: string; ubicacion: string | null; cantidad: string;
  cantidad_sugerida: string | null; bultos: string | null; costo: string | null; cantidad_recibida: string; adelantada: boolean; explicacion: Record<string, unknown> };
type DetalleOC = OC & { lineas: LineaOC[]; email_oc: string | null; notas: string | null; aprobada_por_nombre: string | null; enviada_por_nombre: string | null;
  enviada_at: string | null; aprobada_at: string | null; limite: string | null; proveedor_id: number; ubicacion_id: number | null };
type DetalleTR = TR & { origen_id: number; destino_id: number; lineas: { id: number; nombre: string; cantidad: string; cantidad_recibida: string | null; lote: string | null; costo: string | null }[];
  explicacion: Record<string, unknown> };

const ESTADOS: Record<string, [string, "gris" | "ok" | "alerta" | "peligro" | "acento"]> = {
  sugerida: ["Sugerida", "acento"], borrador: ["Borrador", "gris"], aprobada: ["Aprobada", "ok"], enviada: ["Enviada", "ok"],
  recibida_parcial: ["Recibida en parte", "alerta"], recibida: ["Recibida", "gris"], cancelada: ["Cancelada", "gris"],
};

export default function Documentos() {
  const [vista, setVista] = useState<"oc" | "tr">("oc");
  const [datos, setDatos] = useState<Resumen | null>(null);
  const [oc, setOc] = useState<DetalleOC | null>(null);
  const [tr, setTr] = useState<DetalleTR | null>(null);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error" | "alerta"; texto: string } | null>(null);

  const cargar = useCallback(() => { api<Resumen>("/documentos").then(setDatos).catch((e) => setMensaje({ tipo: "error", texto: e.message })); }, []);
  useEffect(() => { cargar(); }, [cargar]);

  async function accion<T>(fn: () => Promise<T>, ok: string, despues?: (r: T) => void) {
    setMensaje(null);
    try {
      const r = await fn();
      setMensaje({ tipo: "ok", texto: ok });
      despues?.(r);
      cargar();
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo completar." });
    }
  }
  const abrirOc = (id: number) => api<DetalleOC>(`/ordenes/${id}`).then(setOc).catch((e) => setMensaje({ tipo: "error", texto: e.message }));
  const abrirTr = (id: number) => api<DetalleTR>(`/transferencias/${id}`).then(setTr).catch((e) => setMensaje({ tipo: "error", texto: e.message }));

  // Enlaces desde avisos: #oc-ID abre la orden, #tr-ID la transferencia, #tr la pestaña de transferencias.
  useEffect(() => {
    const h = location.hash.slice(1);
    if (h.startsWith("tr")) setVista("tr");
    const m = h.match(/^(oc|tr)-(\d+)$/);
    if (m) (m[1] === "oc" ? abrirOc : abrirTr)(Number(m[2]));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const escaladas = datos?.ordenes.filter((o) => o.escalada_at && ["sugerida", "borrador"].includes(o.estado)) ?? [];
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Transferencias y órdenes de compra</h1>
          <p className="text-sm text-suave">Primero se transfiere desde donde sobra; lo que falta se compra. Nada se envía al proveedor sin que una persona lo confirme.</p>
        </div>
        <div role="tablist" className="flex gap-1">
          {([["oc", `Órdenes de compra${datos ? ` (${datos.ordenes.length})` : ""}`], ["tr", `Transferencias${datos ? ` (${datos.transferencias.length})` : ""}`]] as ["oc" | "tr", string][]).map(([k, n]) => (
            <button key={k} role="tab" aria-selected={vista === k} onClick={() => setVista(k)}
              className={cx("rounded-lg px-3 py-1.5 text-sm", vista === k ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>{n}</button>
          ))}
        </div>
      </div>
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
      {escaladas.length > 0 && (
        <Aviso tipo="alerta">{escaladas.length} orden(es) sin aprobar y hoy pasa su proveedor: {escaladas.map((o) => o.proveedor).join(", ")}.</Aviso>
      )}
      {datos && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Dato titulo="Para aprobar" valor={numero(datos.ordenes.filter((o) => ["sugerida", "borrador"].includes(o.estado)).length)} />
          <Dato titulo="Aprobadas sin enviar" valor={numero(datos.ordenes.filter((o) => o.estado === "aprobada").length)} />
          <Dato titulo="Presupuesto del mes" valor={datos.presupuesto ? plataCorta(datos.presupuesto) : "Sin cargar"} nota={datos.presupuesto ? `Comprometido ${plataCorta(datos.comprometido)}` : undefined} />
          <Dato titulo="Tu límite de aprobación" valor={datos.limites.orden_compra === null ? "Sin límite" : plataCorta(datos.limites.orden_compra)} nota="por orden de compra" />
        </div>
      )}
      {vista === "oc" && datos && (
        <Tarjeta>
          <TablaDatos filas={datos.ordenes} idFila={(o) => String(o.id)} nombreArchivo="ordenes-de-compra" alHacerClic={(o) => abrirOc(o.id)}
            vacio="No hay órdenes de compra. Las sugeridas aparecen después del cálculo de cada noche."
            columnas={[
              { id: "numero", titulo: "Número", valor: (o) => o.numero, render: (o) => <span className="font-medium">{o.numero}{o.escalada_at && ["sugerida", "borrador"].includes(o.estado) && <span className="ml-1 text-xs text-peligro">escalada</span>}</span> },
              { id: "prov", titulo: "Proveedor", valor: (o) => o.proveedor },
              { id: "suc", titulo: "Destino", valor: (o) => o.ubicacion },
              { id: "estado", titulo: "Estado", valor: (o) => o.estado, render: (o) => <span className="flex flex-wrap gap-1"><Etiqueta tono={ESTADOS[o.estado]?.[1]}>{ESTADOS[o.estado]?.[0] ?? o.estado}</Etiqueta>{o.aprobacion === "automatica" && <Etiqueta>automática</Etiqueta>}</span> },
              { id: "lineas", titulo: "Productos", valor: (o) => o.lineas, derecha: true, ocultarEnCelular: true },
              { id: "total", titulo: "Total", valor: (o) => Number(o.total), render: (o) => plata(o.total), derecha: true },
              { id: "min", titulo: "Pedido mínimo", valor: (o) => (o.explicacion?.cumple_minimo === false ? 0 : 1), render: (o) => (o.explicacion?.cumple_minimo === false
                ? <span className="text-alerta">▲ faltan {plata(o.explicacion.falta_para_minimo as string)}</span> : o.explicacion?.adelantos ? <span className="text-suave">completado con adelantos</span> : "✓"), ocultarEnCelular: true },
              { id: "llega", titulo: "Llega", valor: (o) => o.fecha_esperada, render: (o) => fechaCorta(o.fecha_esperada), ocultarEnCelular: true },
            ]} />
        </Tarjeta>
      )}
      {vista === "tr" && datos && (
        <Tarjeta>
          <TablaDatos filas={datos.transferencias} idFila={(t) => String(t.id)} nombreArchivo="transferencias" alHacerClic={(t) => abrirTr(t.id)}
            vacio="No hay transferencias. Se sugieren cuando una sucursal tiene de más y otra de menos."
            columnas={[
              { id: "numero", titulo: "Número", valor: (t) => t.numero },
              { id: "origen", titulo: "Desde", valor: (t) => t.origen },
              { id: "destino", titulo: "Hacia", valor: (t) => t.destino },
              { id: "motivo", titulo: "Motivo", valor: (t) => t.motivo, render: (t) => (t.motivo === "rescate_vencimiento" ? "Rescate de vencimiento" : t.motivo === "manual" ? "Manual" : "Reposición") },
              { id: "estado", titulo: "Estado", valor: (t) => t.estado, render: (t) => <Etiqueta tono={ESTADOS[t.estado]?.[1]}>{ESTADOS[t.estado]?.[0] ?? t.estado}</Etiqueta> },
              { id: "valor", titulo: "Valor a costo", valor: (t) => Number(t.valor), render: (t) => plata(t.valor), derecha: true },
            ]} />
        </Tarjeta>
      )}
      <ComoSeCalcula>
        <p>Cada noche, para cada producto que llegó a su punto de pedido: si el modelo es mixto o centralizado se busca primero una sucursal o el depósito con excedente (sin dejarlos por debajo de lo que necesitan: 14 días de venta o su horizonte más seguridad). Lo que no se cubre con transferencias se compra.</p>
        <p>Las compras se agrupan por proveedor. Si no llegan al pedido mínimo, se adelantan productos del mismo proveedor que se van a necesitar pronto y se muestra cuánta plata extra implica.</p>
        <p>Según la configuración, las órdenes quedan como aviso, borrador o aprobadas solas si están bajo el límite y dentro del presupuesto. El envío al proveedor siempre lo confirma una persona. Si una orden no se aprueba el día que pasa el proveedor, se escala al dueño.</p>
      </ComoSeCalcula>

      <Panel abierto={!!oc} alCerrar={() => setOc(null)} titulo={oc && <div><p className="font-semibold">{oc.numero} · {oc.proveedor}</p><p className="text-xs text-suave">{oc.ubicacion ?? "Consolidada"} · {ESTADOS[oc.estado]?.[0]}</p></div>}>
        {oc && datos && <DetalleOrden oc={oc} datos={datos} accion={accion} alCambiar={(x) => setOc(x)} />}
      </Panel>
      <Panel abierto={!!tr} alCerrar={() => setTr(null)} titulo={tr && <div><p className="font-semibold">{tr.numero}</p><p className="text-xs text-suave">{tr.origen} → {tr.destino} · {ESTADOS[tr.estado]?.[0]}</p></div>}>
        {tr && datos && <DetalleTransferencia tr={tr} datos={datos} accion={accion} alCambiar={(x) => setTr(x)} />}
      </Panel>
    </div>
  );
}

function Dato({ titulo, valor, nota }: { titulo: string; valor: string; nota?: string }) {
  return <div className="rounded-xl border border-borde bg-panel p-4"><p className="text-sm text-suave">{titulo}</p><p className="mt-1 text-2xl font-semibold">{valor}</p>{nota && <p className="text-xs text-suave">{nota}</p>}</div>;
}

type Accion = <T>(fn: () => Promise<T>, ok: string, despues?: (r: T) => void) => Promise<void>;

function DetalleOrden({ oc, datos, accion, alCambiar }: { oc: DetalleOC; datos: Resumen; accion: Accion; alCambiar: (o: DetalleOC | null) => void }) {
  const editable = ["sugerida", "borrador"].includes(oc.estado) && datos.puede_comprar;
  const [cantidades, setCantidades] = useState<Record<number, string>>(Object.fromEntries(oc.lineas.map((l) => [l.id, String(Number(l.cantidad))])));
  const [recibido, setRecibido] = useState<Record<number, { cantidad: string; costo: string; lote: string; vencimiento: string }>>(
    Object.fromEntries(oc.lineas.map((l) => [l.id, { cantidad: String(Number(l.cantidad) - Number(l.cantidad_recibida)), costo: l.costo ? String(Number(l.costo)) : "", lote: "", vencimiento: "" }])));
  const [email, setEmail] = useState(oc.email_oc ?? "");
  const [recibiendo, setRecibiendo] = useState(false);
  const recargar = () => api<DetalleOC>(`/ordenes/${oc.id}`).then(alCambiar);
  const cambiada = oc.lineas.some((l) => String(Number(l.cantidad)) !== cantidades[l.id]);
  const e = oc.explicacion ?? {};

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap gap-2 text-sm">
        <Etiqueta tono={ESTADOS[oc.estado]?.[1]}>{ESTADOS[oc.estado]?.[0]}</Etiqueta>
        {oc.aprobacion === "automatica" && <Etiqueta>Aprobada automáticamente (bajo el límite)</Etiqueta>}
        {oc.aprobada_por_nombre && <Etiqueta>Aprobó {oc.aprobada_por_nombre}</Etiqueta>}
        {oc.enviada_por_nombre && <Etiqueta>Envió {oc.enviada_por_nombre} · {fechaHora(oc.enviada_at)}</Etiqueta>}
      </div>
      {e.cumple_minimo === false && <Aviso tipo="alerta">No llega al pedido mínimo del proveedor ({plata(e.pedido_minimo_monto as string)}): faltan {plata(e.falta_para_minimo as string)}.</Aviso>}
      {Number(e.adelantos ?? 0) > 0 && <Aviso tipo="info">Para llegar al pedido mínimo se adelantaron {String(e.adelantos)} producto(s) que se iban a necesitar pronto: {plata(e.inversion_adelantos as string)} extra.</Aviso>}
      {Boolean(e.presupuesto) && (e.presupuesto as { dentro: boolean }).dentro === false && <Aviso tipo="alerta">Esta orden supera el presupuesto de compra disponible del mes.</Aviso>}
      <Tabla columnas={["Producto", "Sugerido", "Cantidad", "Costo", "Subtotal", ...(oc.estado.startsWith("recibida") || oc.estado === "enviada" ? ["Recibido"] : [])]}>
        {oc.lineas.map((l) => (
          <tr key={l.id}>
            <td>{l.nombre}{l.adelantada && <span className="ml-1 text-xs text-acento">adelantado</span>}<br /><span className="text-xs text-suave">{l.codigo_interno}{l.ubicacion ? ` · ${l.ubicacion}` : ""}</span></td>
            <td className="cifra">{l.cantidad_sugerida ? numero(l.cantidad_sugerida, 0) : "—"}</td>
            <td className="cifra">{editable ? (
              <input inputMode="numeric" aria-label={`Cantidad de ${l.nombre}`} className="w-20 rounded border border-borde bg-panel px-2 py-1 text-right" value={cantidades[l.id]}
                onChange={(ev) => setCantidades({ ...cantidades, [l.id]: ev.target.value })} />) : numero(l.cantidad, 0)}</td>
            <td className="cifra">{plata(l.costo)}</td>
            <td className="cifra">{plata(Number(cantidades[l.id] ?? l.cantidad) * Number(l.costo ?? 0))}</td>
            {(oc.estado.startsWith("recibida") || oc.estado === "enviada") && <td className="cifra">{numero(l.cantidad_recibida, 0)}</td>}
          </tr>
        ))}
        <tr><td colSpan={4} className="text-right font-medium">Total</td><td className="cifra font-semibold">{plata(oc.lineas.reduce((a, l) => a + Number(cantidades[l.id] ?? l.cantidad) * Number(l.costo ?? 0), 0))}</td></tr>
      </Tabla>
      <div className="flex flex-wrap gap-2">
        {editable && cambiada && <Boton variante="secundario" onClick={() => accion(() => api(`/ordenes/${oc.id}`, { metodo: "PUT", cuerpo: { lineas: oc.lineas.map((l) => ({ id: l.id, cantidad: Number(cantidades[l.id] || 0) })) } }), "Cambios guardados.", recargar)}>Guardar cambios</Boton>}
        {editable && datos.puede_aprobar_oc && !cambiada && <Boton onClick={() => accion(() => api(`/ordenes/${oc.id}/aprobar`, { metodo: "POST" }), "Orden aprobada.", recargar)}>Aprobar</Boton>}
        <a className="inline-flex min-h-9 items-center rounded-lg border border-borde px-3.5 text-sm" href={`${BASE}/api/ordenes/${oc.id}/pdf`} target="_blank" rel="noreferrer">Ver PDF</a>
        {["sugerida", "borrador", "aprobada"].includes(oc.estado) && datos.puede_comprar && (
          <Boton variante="peligro" onClick={() => { const motivo = prompt("¿Por qué se cancela?"); if (motivo) accion(() => api(`/ordenes/${oc.id}/cancelar`, { metodo: "POST", cuerpo: { motivo } }), "Orden cancelada.", () => alCambiar(null)); }}>Cancelar</Boton>
        )}
      </div>
      {oc.estado === "aprobada" && datos.puede_comprar && (
        <div className="grid gap-2 rounded-xl border border-borde bg-panel p-3">
          <p className="text-sm font-medium">Enviar al proveedor</p>
          <p className="text-xs text-suave">Se manda el PDF por email. Este paso siempre lo confirma una persona.</p>
          <div className="flex flex-wrap gap-2">
            <Entrada type="email" className="max-w-xs" value={email} placeholder="email del proveedor" onChange={(ev) => setEmail(ev.target.value)} />
            <Boton onClick={() => { if (confirm(`¿Enviar ${oc.numero} a ${email}?`)) accion(() => api(`/ordenes/${oc.id}/enviar`, { metodo: "POST", cuerpo: { email } }), "Orden enviada al proveedor.", recargar); }}>Confirmar y enviar</Boton>
          </div>
        </div>
      )}
      {["enviada", "aprobada", "recibida_parcial"].includes(oc.estado) && datos.puede_recibir && (
        !recibiendo ? <Boton variante="secundario" onClick={() => setRecibiendo(true)}>Registrar recepción</Boton> : (
          <div className="grid gap-2 rounded-xl border border-borde bg-panel p-3">
            <p className="text-sm font-medium">Recepción: cargá lo que llegó (con lote y vencimiento si los tiene)</p>
            {oc.lineas.map((l) => (
              <div key={l.id} className="grid gap-2 border-b border-borde/60 pb-2 sm:grid-cols-[1fr_80px_100px_100px_130px] sm:items-center">
                <span className="text-sm">{l.nombre}</span>
                <input inputMode="decimal" aria-label="Cantidad recibida" className="rounded border border-borde bg-panel px-2 py-1 text-right" value={recibido[l.id].cantidad} onChange={(ev) => setRecibido({ ...recibido, [l.id]: { ...recibido[l.id], cantidad: ev.target.value } })} />
                <input inputMode="decimal" aria-label="Costo" className="rounded border border-borde bg-panel px-2 py-1 text-right" value={recibido[l.id].costo} onChange={(ev) => setRecibido({ ...recibido, [l.id]: { ...recibido[l.id], costo: ev.target.value } })} />
                <input aria-label="Lote" placeholder="Lote" className="rounded border border-borde bg-panel px-2 py-1" value={recibido[l.id].lote} onChange={(ev) => setRecibido({ ...recibido, [l.id]: { ...recibido[l.id], lote: ev.target.value } })} />
                <input type="date" aria-label="Vencimiento" className="rounded border border-borde bg-panel px-2 py-1" value={recibido[l.id].vencimiento} onChange={(ev) => setRecibido({ ...recibido, [l.id]: { ...recibido[l.id], vencimiento: ev.target.value } })} />
              </div>
            ))}
            <Boton onClick={() => accion(() => api<{ diferencias: unknown[] }>(`/ordenes/${oc.id}/recepcion`, { metodo: "POST", cuerpo: { lineas: oc.lineas.map((l) => ({
              producto_id: l.producto_id, ubicacion_id: l.ubicacion_id, cantidad: Number(recibido[l.id].cantidad.replace(",", ".") || 0), costo: recibido[l.id].costo.replace(",", ".") || null,
              lote: recibido[l.id].lote || null, vencimiento: recibido[l.id].vencimiento || null })) } }), "Recepción registrada: el stock ya está actualizado.", () => { setRecibiendo(false); recargar(); })}>Confirmar recepción</Boton>
          </div>
        )
      )}
    </div>
  );
}

function DetalleTransferencia({ tr, datos, accion, alCambiar }: { tr: DetalleTR; datos: Resumen; accion: Accion; alCambiar: (t: DetalleTR | null) => void }) {
  const [recibido, setRecibido] = useState<Record<number, string>>(Object.fromEntries(tr.lineas.map((l) => [l.id, String(Number(l.cantidad))])));
  const recargar = () => api<DetalleTR>(`/transferencias/${tr.id}`).then(alCambiar);
  return (
    <div className="grid gap-4">
      {tr.motivo === "rescate_vencimiento" && <Aviso tipo="info">Rescate de vencimiento: en {tr.origen} este lote no llega a venderse antes de vencer; en {tr.destino} sí.</Aviso>}
      <Tabla columnas={["Producto", "Cantidad", "Lote", "Valor", ...(tr.estado === "enviada" ? ["Recibido"] : tr.estado === "recibida" ? ["Recibido"] : [])]}>
        {tr.lineas.map((l) => (
          <tr key={l.id}>
            <td>{l.nombre}</td>
            <td className="cifra">{numero(l.cantidad, 0)}</td>
            <td>{l.lote ?? "—"}</td>
            <td className="cifra">{plata(Number(l.cantidad) * Number(l.costo ?? 0))}</td>
            {tr.estado === "enviada" && <td><input inputMode="decimal" aria-label="Recibido" className="w-20 rounded border border-borde bg-panel px-2 py-1 text-right" value={recibido[l.id]} onChange={(ev) => setRecibido({ ...recibido, [l.id]: ev.target.value })} /></td>}
            {tr.estado === "recibida" && <td className="cifra">{numero(l.cantidad_recibida, 0)}</td>}
          </tr>
        ))}
      </Tabla>
      <div className="flex flex-wrap gap-2">
        {tr.estado === "sugerida" && datos.puede_transferir && <Boton onClick={() => accion(() => api(`/transferencias/${tr.id}/aprobar`, { metodo: "POST" }), "Transferencia aprobada.", recargar)}>Aprobar</Boton>}
        {tr.estado === "aprobada" && datos.puede_recibir && <Boton onClick={() => accion(() => api(`/transferencias/${tr.id}/enviar`, { metodo: "POST" }), "Enviada: se descontó del origen y queda en tránsito.", recargar)}>Marcar como enviada</Boton>}
        {tr.estado === "enviada" && datos.puede_recibir && <Boton onClick={() => accion(() => api(`/transferencias/${tr.id}/recibir`, { metodo: "POST", cuerpo: { lineas: tr.lineas.map((l) => ({ id: l.id, cantidad_recibida: Number(recibido[l.id].replace(",", ".")) })) } }), "Recibida: el stock del destino ya está actualizado.", recargar)}>Confirmar recepción</Boton>}
        {["sugerida", "aprobada"].includes(tr.estado) && datos.puede_transferir && <Boton variante="peligro" onClick={() => accion(() => api(`/transferencias/${tr.id}/cancelar`, { metodo: "POST" }), "Transferencia cancelada.", () => alCambiar(null))}>Cancelar</Boton>}
      </div>
    </div>
  );
}
