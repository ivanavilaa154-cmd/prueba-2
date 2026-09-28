"use client";
// Proveedores (10.11): nivel de servicio, puntualidad, costos contra la inflación, rentabilidad y configuración.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { numero, plata } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, Boton, Campo, ComoSeCalcula, Entrada, Etiqueta, Tarjeta, cx } from "@/components/ui";

type Costos = { variacion: number; inflacion: number | null; contra_inflacion: number | null; productos: number } | null;
type Prov = { id: number; razon_social: string; cuit: string | null; email_oc: string | null; telefono: string | null; dias_visita: number[]; demora_entrega_dias: number | null;
  pedido_minimo_monto: string; pedido_minimo_bultos: number; condiciones_pago: string | null; servicio_unidades: number | null; servicio_lineas: number | null; ordenes: number;
  puntualidad: number | null; atraso_promedio_dias: number | null; ganancia_90d: string; facturacion_90d: string; merma_90d: string; plata_parada: string; gmroi: number | null;
  costos: Costos; sin_configurar: string[] };
const DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const pct = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? "—" : `${numero(v * 100, d)} %`);

function Servicio({ v }: { v: number | null }) {
  if (v === null) return <span className="text-suave">—</span>;
  const [icono, color] = v >= 0.95 ? ["✓", "var(--estado-bien)"] : v >= 0.85 ? ["▲", "var(--estado-alerta)"] : ["●", "var(--estado-critico)"];
  return <span className="whitespace-nowrap"><span aria-hidden="true" style={{ color }}>{icono}</span> {pct(v)}</span>;
}

function Editor({ p, alGuardar, cerrar }: { p: Prov; alGuardar: () => void; cerrar: () => void }) {
  const [d, setD] = useState({ email_oc: p.email_oc ?? "", telefono: p.telefono ?? "", dias_visita: p.dias_visita, demora_entrega_dias: p.demora_entrega_dias?.toString() ?? "",
    pedido_minimo_monto: String(Math.round(Number(p.pedido_minimo_monto))), pedido_minimo_bultos: String(p.pedido_minimo_bultos), condiciones_pago: p.condiciones_pago ?? "" });
  const [error, setError] = useState<string | null>(null);
  async function guardar() {
    try {
      await api(`/proveedores/${p.id}`, { metodo: "PUT", cuerpo: { ...d, demora_entrega_dias: d.demora_entrega_dias === "" ? null : Number(d.demora_entrega_dias),
        pedido_minimo_monto: d.pedido_minimo_monto || "0", pedido_minimo_bultos: Number(d.pedido_minimo_bultos || 0) } });
      alGuardar();
      cerrar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar.");
    }
  }
  return (
    <Tarjeta titulo={`Configurar ${p.razon_social}`} accion={<button className="text-sm text-acento underline" onClick={cerrar}>Cerrar</button>}>
      {error && <div className="mb-3"><Aviso tipo="error">{error}</Aviso></div>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Campo etiqueta="Días de visita" ayuda="Los días que pasa a tomar el pedido.">
          <div className="flex flex-wrap gap-1">
            {DIAS.map((n, i) => (
              <button key={n} type="button" aria-pressed={d.dias_visita.includes(i)}
                onClick={() => setD({ ...d, dias_visita: d.dias_visita.includes(i) ? d.dias_visita.filter((x) => x !== i) : [...d.dias_visita, i] })}
                className={cx("rounded-md border px-2 py-1 text-sm", d.dias_visita.includes(i) ? "border-acento bg-acento text-acento-texto" : "border-borde")}>{n}</button>
            ))}
          </div>
        </Campo>
        <Campo etiqueta="Demora de entrega (días)"><Entrada inputMode="numeric" value={d.demora_entrega_dias} onChange={(e) => setD({ ...d, demora_entrega_dias: e.target.value })} /></Campo>
        <Campo etiqueta="Email para órdenes de compra"><Entrada type="email" value={d.email_oc} onChange={(e) => setD({ ...d, email_oc: e.target.value })} /></Campo>
        <Campo etiqueta="Pedido mínimo ($)"><Entrada inputMode="numeric" value={d.pedido_minimo_monto} onChange={(e) => setD({ ...d, pedido_minimo_monto: e.target.value })} /></Campo>
        <Campo etiqueta="Pedido mínimo (bultos)"><Entrada inputMode="numeric" value={d.pedido_minimo_bultos} onChange={(e) => setD({ ...d, pedido_minimo_bultos: e.target.value })} /></Campo>
        <Campo etiqueta="Condiciones de pago"><Entrada value={d.condiciones_pago} onChange={(e) => setD({ ...d, condiciones_pago: e.target.value })} placeholder="Ej.: 30 días" /></Campo>
      </div>
      <div className="mt-4"><Boton onClick={guardar}>Guardar</Boton></div>
    </Tarjeta>
  );
}

export default function Proveedores() {
  const { puede } = useSesion();
  const [r, setR] = useState<Prov[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editando, setEditando] = useState<Prov | null>(null);
  const cargar = useCallback(() => api<{ proveedores: Prov[] }>("/proveedores/analisis").then((d) => setR(d.proveedores)).catch((e) => setError(e.message)), []);
  useEffect(() => { cargar(); }, [cargar]);
  const faltan = r?.filter((p) => p.sin_configurar.length) ?? [];
  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Proveedores</h1>
        <p className="text-sm text-suave">Quién te entrega completo y a tiempo, cuánto te subió y cuánta plata te deja cada uno.</p>
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {faltan.length > 0 && (
        <Aviso tipo="alerta">▲ {faltan.length} proveedores sin configurar del todo ({faltan.map((p) => `${p.razon_social}: ${p.sin_configurar.join(", ")}`).join(" · ")}). Sin días de visita ni demora, el pedido sugerido supone lo peor.</Aviso>
      )}
      {editando && <Editor p={editando} alGuardar={cargar} cerrar={() => setEditando(null)} />}
      {!r ? !error && <p className="text-sm text-suave">Cargando…</p> : (
        <Tarjeta titulo="Todos los proveedores">
          <TablaDatos filas={r} idFila={(p) => String(p.id)} nombreArchivo="proveedores"
            columnas={[
              { id: "prov", titulo: "Proveedor", valor: (p) => p.razon_social, render: (p) => (
                <span>{p.razon_social}<span className="block text-xs text-suave">{p.dias_visita.length ? p.dias_visita.map((x) => DIAS[x]).join(", ") : "sin días"} · {p.demora_entrega_dias ?? "?"} d de demora</span>
                  {p.sin_configurar.length > 0 && <Etiqueta tono="alerta">▲ Falta configurar</Etiqueta>}</span>) },
              { id: "serv", titulo: "Entrega completa", valor: (p) => p.servicio_unidades, render: (p) => <span><Servicio v={p.servicio_unidades} /><span className="block text-xs text-suave">{pct(p.servicio_lineas)} de líneas</span></span>, derecha: true },
              { id: "punt", titulo: "Puntualidad", valor: (p) => p.puntualidad, render: (p) => <span><Servicio v={p.puntualidad} />{p.atraso_promedio_dias ? <span className="block text-xs text-suave">{numero(p.atraso_promedio_dias, 1)} d de atraso prom.</span> : null}</span>, derecha: true },
              { id: "costo", titulo: "Costo 12 meses", valor: (p) => p.costos?.variacion ?? null, render: (p) => !p.costos ? "—" : (
                <span className="whitespace-nowrap">▲ {pct(p.costos.variacion, 1)}<span className="block text-xs text-suave">
                  {p.costos.contra_inflacion === null ? "" : p.costos.contra_inflacion > 0.01 ? `▲ ${pct(p.costos.contra_inflacion, 1)} sobre la inflación` : p.costos.contra_inflacion < -0.01 ? `▼ ${pct(-p.costos.contra_inflacion, 1)} bajo la inflación` : "= a la inflación"}</span></span>), derecha: true },
              { id: "gan", titulo: "Ganancia 90 d", valor: (p) => Number(p.ganancia_90d), render: (p) => plata(p.ganancia_90d), derecha: true },
              { id: "gmroi", titulo: "GMROI", valor: (p) => p.gmroi, render: (p) => (p.gmroi === null ? "—" : numero(p.gmroi, 2)), derecha: true, ocultarEnCelular: true },
              { id: "merma", titulo: "Merma 90 d", valor: (p) => Number(p.merma_90d), render: (p) => plata(p.merma_90d), derecha: true, ocultarEnCelular: true },
              { id: "parada", titulo: "Plata parada", valor: (p) => Number(p.plata_parada), render: (p) => plata(p.plata_parada), derecha: true, ocultarEnCelular: true },
              { id: "acc", titulo: "", valor: () => "", render: (p) => puede("gestionar_proveedores") && <button className="text-sm text-acento underline" onClick={() => { setEditando(p); window.scrollTo({ top: 0, behavior: "smooth" }); }}>Configurar</button> },
            ]} />
          <div className="mt-3">
            <ComoSeCalcula>
              <p>Entrega completa = unidades recibidas ÷ pedidas en las órdenes de los últimos 180 días. Puntualidad = recepciones que llegaron hasta la fecha esperada.</p>
              <p>Costo 12 meses: cuánto subió el costo de sus productos (con los costos de cada recepción, ponderado por unidades), comparado con la inflación del mismo período.</p>
              <p>GMROI = ganancia de sus productos en 90 días ÷ stock promedio a costo.</p>
            </ComoSeCalcula>
          </div>
        </Tarjeta>
      )}
    </div>
  );
}
