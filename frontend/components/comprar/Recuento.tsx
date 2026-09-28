"use client";
// Recuento guiado desde el celular: lista corta del día, priorizada; se carga lo contado y se ajusta con motivo.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { numero, plata } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Etiqueta, Selector, Tarjeta, Vacio } from "@/components/ui";

type Linea = { id: number; producto_id: number; nombre: string; codigo_interno: string; ean: string | null; unidad: string; motivo_seleccion: string;
  stock_actual: string | null; contado: string | null; diferencia: string | null; diferencia_pesos: string | null; estado: string };

const MOTIVOS: Record<string, string> = {
  stock_fantasma: "No se vende hace días y el sistema dice que hay", stock_negativo: "El sistema marca stock negativo",
  marcado: "Marcado para contar", diferencia_previa: "Tuvo diferencias en recuentos anteriores", clase_a: "Producto clase A",
  alto_valor: "Mucha plata en stock",
};
const ESTADO: Record<string, [string, "gris" | "ok" | "alerta" | "peligro"]> = {
  pendiente: ["Sin contar", "gris"], sin_diferencia: ["Sin diferencia", "ok"], ajustado: ["Ajustado", "ok"],
  pendiente_aprobacion: ["Espera aprobación", "alerta"], rechazado: ["Ajuste rechazado", "peligro"],
};
const RAZONES = ["Rotura", "Vencido", "Faltante sin explicar", "Error de carga anterior", "Mercadería sin ingresar", "Robo"];

export function Recuento() {
  const { yo } = useSesion();
  const sucursales = yo.ubicaciones.filter((u) => u.tipo !== "deposito");
  const [uid, setUid] = useState<number | null>(sucursales[0]?.id ?? null);
  const [lineas, setLineas] = useState<Linea[] | null>(null);
  const [valores, setValores] = useState<Record<number, { contado: string; motivo: string }>>({});
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error" | "alerta"; texto: string } | null>(null);

  const cargar = useCallback(() => {
    if (!uid) return;
    api<{ lineas: Linea[] }>(`/recuentos/hoy?ubicacion_id=${uid}`).then((r) => setLineas(r.lineas)).catch((e) => setMensaje({ tipo: "error", texto: e.message }));
  }, [uid]);
  useEffect(() => { cargar(); }, [cargar]);

  async function guardar(l: Linea) {
    const v = valores[l.id];
    if (!v?.contado) return;
    setMensaje(null);
    try {
      const r = await api<{ estado: string; diferencia: string; diferencia_pesos: string }>(`/recuentos/lineas/${l.id}`, {
        metodo: "PUT", cuerpo: { contado: Number(v.contado.replace(",", ".")), motivo: v.motivo || null } });
      setMensaje(r.estado === "pendiente_aprobacion"
        ? { tipo: "alerta", texto: `Diferencia de ${numero(r.diferencia, 0)} (${plata(r.diferencia_pesos)}): supera tu límite, queda esperando que la apruebe el dueño.` }
        : { tipo: "ok", texto: Number(r.diferencia) === 0 ? "Coincide con el sistema." : `Ajustado: ${numero(r.diferencia, 0)} unidades (${plata(r.diferencia_pesos)}).` });
      cargar();
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo guardar." });
    }
  }

  return (
    <Tarjeta titulo="Recuento del día" accion={sucursales.length > 1 && (
      <Selector aria-label="Sucursal" className="w-auto" value={uid ?? ""} onChange={(e) => setUid(Number(e.target.value))}>
        {sucursales.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
      </Selector>
    )}>
      <p className="mb-3 text-sm text-suave">Contá estos productos en góndola y depósito. La lista prioriza los que más probablemente tengan diferencias.</p>
      {mensaje && <div className="mb-3"><Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso></div>}
      {!lineas && !mensaje && <p className="text-sm text-suave">Cargando la lista del día…</p>}
      {lineas && lineas.length === 0 && <Vacio titulo="No hay nada para contar hoy" />}
      <ul className="grid gap-2">
        {lineas?.map((l) => {
          const hecho = l.estado !== "pendiente";
          const v = valores[l.id] ?? { contado: "", motivo: "" };
          const difiere = v.contado !== "" && Number(v.contado.replace(",", ".")) !== Number(l.stock_actual ?? 0);
          return (
            <li key={l.id} className="rounded-lg border border-borde p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="font-medium">{l.nombre}</p>
                  <p className="text-xs text-suave">{l.ean ?? l.codigo_interno} · {MOTIVOS[l.motivo_seleccion] ?? l.motivo_seleccion}</p>
                </div>
                <Etiqueta tono={ESTADO[l.estado]?.[1] ?? "gris"}>{ESTADO[l.estado]?.[0] ?? l.estado}</Etiqueta>
              </div>
              {hecho ? (
                <p className="mt-2 text-sm text-suave">Contado: {numero(l.contado, 0)} · Sistema: {numero(Number(l.contado) - Number(l.diferencia ?? 0), 0)} ·
                  Diferencia: {numero(l.diferencia, 0)} ({plata(l.diferencia_pesos)})</p>
              ) : (
                <div className="mt-2 grid gap-2 sm:grid-cols-[140px_1fr_auto] sm:items-end">
                  <label className="grid gap-1 text-sm">
                    <span>Contado ({l.unidad === "kg" ? "kg" : "unidades"})</span>
                    <input inputMode="decimal" className="min-h-10 rounded-lg border border-borde bg-panel px-3 text-base" value={v.contado}
                      onChange={(e) => setValores({ ...valores, [l.id]: { ...v, contado: e.target.value } })} />
                  </label>
                  {difiere ? (
                    <label className="grid gap-1 text-sm">
                      <span>No coincide con el sistema: indicá el motivo</span>
                      <select className="min-h-10 rounded-lg border border-borde bg-panel px-2" value={v.motivo}
                        onChange={(e) => setValores({ ...valores, [l.id]: { ...v, motivo: e.target.value } })}>
                        <option value="">Elegí un motivo…</option>
                        {RAZONES.map((r) => <option key={r}>{r}</option>)}
                      </select>
                    </label>
                  ) : <span />}
                  <Boton onClick={() => guardar(l)} disabled={!v.contado || (difiere && !v.motivo)}>Guardar</Boton>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Tarjeta>
  );
}
