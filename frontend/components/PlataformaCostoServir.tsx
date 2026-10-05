"use client";
// Panel interno (13.7): precisión de los pronósticos por empresa, tiempo de implementación y soporte (para controlar el costo de servir).
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fecha, fechaHora, numero } from "@/lib/formato";
import { TEMAS } from "@/components/config/Ayuda";
import { Aviso, Boton, Campo, ComoSeCalcula, Entrada, Etiqueta, Selector, Tabla, Tarjeta, cx } from "@/components/ui";

type Precision = { fecha: string; wape: string | null; mape: string | null; sesgo: string | null; cobertura: string | null; evaluados: number };
type Empresa = { id: number; nombre: string; plan: string; modos: string[]; created_at: string; implementacion_lista_at: string | null;
  implementacion_horas: string; primer_ingreso_completo_at: string | null; primer_ingreso_confirmados: number; dias_implementacion: number | null; dias_desde_alta: number; abiertos: number; tickets_90: number;
  horas_soporte_90: number; usuarios_activos_30: number; precision: Precision | null; wape_hace_4_semanas: string | null };
type Ticket = { id: number; org_id: number; empresa: string; asunto: string; detalle: string | null; tema: string; estado: string; origen: string;
  minutos: number; respuesta: string | null; created_at: string; resuelto_at: string | null; autor: string | null };
type R = { resumen: { empresas: number; abiertos: number; horas_soporte_90: number; dias_implementacion_promedio: number | null; sin_implementar: number };
  empresas: Empresa[]; tickets: Ticket[] };

const pct = (v: string | number | null | undefined) => (v === null || v === undefined ? "—" : `${numero(Number(v) * 100, 1)} %`);

export function PlataformaCostoServir() {
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nuevo, setNuevo] = useState({ org_id: "", asunto: "", tema: "uso", minutos: "", resuelto: true });
  const cargar = useCallback(() => api<R>("/plataforma/costo-de-servir").then(setR).catch((e) => setError(e.message)), []);
  useEffect(() => { cargar(); }, [cargar]);
  async function correr(f: () => Promise<unknown>) {
    setError(null);
    try { await f(); await cargar(); } catch (e) { setError(e instanceof Error ? e.message : "No se pudo guardar."); }
  }
  if (!r) return error ? <Aviso tipo="error">{error}</Aviso> : null;
  return (
    <Tarjeta titulo="Costo de servir: precisión, implementación y soporte">
      {error && <div className="mb-3"><Aviso tipo="error">{error}</Aviso></div>}
      <div className="mb-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <p>Implementación promedio<br /><strong className="text-lg">{r.resumen.dias_implementacion_promedio ?? "—"} días</strong></p>
        <p>Empresas sin implementar<br /><strong className="text-lg">{r.resumen.sin_implementar}</strong></p>
        <p>Tickets abiertos<br /><strong className="text-lg">{r.resumen.abiertos}</strong></p>
        <p>Horas de soporte (90 días)<br /><strong className="text-lg">{numero(r.resumen.horas_soporte_90, 1)}</strong></p>
      </div>
      <Tabla columnas={["Empresa", "Error (WAPE · MAPE)", "Sesgo · rango", "Implementación", "Soporte 90 días", "Usuarios activos"]}>
        {r.empresas.map((e) => {
          const w = e.precision?.wape !== null && e.precision?.wape !== undefined ? Number(e.precision.wape) : null;
          const antes = e.wape_hace_4_semanas !== null ? Number(e.wape_hace_4_semanas) : null;
          return (
            <tr key={e.id} className="align-top">
              <td><span className="font-medium">{e.nombre}</span><div className="text-xs text-suave">{e.plan} · {(e.modos ?? []).join(" y ")}</div></td>
              <td>{e.precision ? <>
                <span className={cx(w !== null && w > 0.5 ? "text-peligro" : w !== null && w > 0.3 ? "text-alerta" : "")}>{pct(w)}</span> · {pct(e.precision.mape)}
                <div className="text-xs text-suave">{antes !== null && w !== null ? `${w < antes ? "▼ mejoró" : "▲ empeoró"} desde ${pct(antes)} · ` : ""}{fecha(e.precision.fecha)}</div>
              </> : <span className="text-suave">Sin pronósticos vencidos</span>}</td>
              <td>{e.precision ? <>{pct(e.precision.sesgo)}<div className="text-xs text-suave">dentro del rango {pct(e.precision.cobertura)}</div></> : "—"}</td>
              <td>{e.dias_implementacion !== null ? `${e.dias_implementacion} días` : <Etiqueta tono="alerta">En curso ({e.dias_desde_alta} d)</Etiqueta>}
                <div className="text-xs text-suave">Guía: {e.primer_ingreso_completo_at ? "completa" : `${e.primer_ingreso_confirmados} de 4 pasos confirmados`}</div>
                <div className="flex items-center gap-1 text-xs text-suave">
                  <input aria-label={`Horas de implementación de ${e.nombre}`} className="w-14 rounded border border-borde bg-panel px-1" defaultValue={Number(e.implementacion_horas)}
                    onBlur={(ev) => { const h = Number(ev.target.value.replace(",", ".")); if (h !== Number(e.implementacion_horas) && h >= 0) void correr(() => api(`/plataforma/empresas/${e.id}/implementacion`, { metodo: "PUT", cuerpo: { horas: h } })); }} /> h dedicadas</div></td>
              <td>{e.tickets_90} tickets · {numero(e.horas_soporte_90, 1)} h{e.abiertos > 0 && <div><Etiqueta tono="alerta">{e.abiertos} abiertos</Etiqueta></div>}</td>
              <td className="text-right">{e.usuarios_activos_30}</td>
            </tr>
          );
        })}
      </Tabla>
      <ComoSeCalcula>WAPE: error total sobre la venta total de las últimas semanas (lo que mueve plata). MAPE: promedio del error porcentual de cada producto
        y semana con venta. Sesgo positivo: el pronóstico se pasa. Implementación: del alta de la empresa a su primer cálculo con datos.</ComoSeCalcula>

      <h3 className="mb-2 mt-5 font-semibold">Tickets</h3>
      <div className="mb-3 grid gap-2 sm:grid-cols-[1fr_2fr_1fr_6rem_auto] sm:items-end">
        <Campo etiqueta="Empresa"><Selector value={nuevo.org_id} onChange={(e) => setNuevo({ ...nuevo, org_id: e.target.value })}>
          <option value="">Elegí…</option>{r.empresas.map((e) => <option key={e.id} value={e.id}>{e.nombre}</option>)}</Selector></Campo>
        <Campo etiqueta="Asunto"><Entrada value={nuevo.asunto} onChange={(e) => setNuevo({ ...nuevo, asunto: e.target.value })} /></Campo>
        <Campo etiqueta="Tema"><Selector value={nuevo.tema} onChange={(e) => setNuevo({ ...nuevo, tema: e.target.value })}>
          {Object.entries(TEMAS).map(([k, n]) => <option key={k} value={k}>{n}</option>)}</Selector></Campo>
        <Campo etiqueta="Minutos"><Entrada inputMode="numeric" value={nuevo.minutos} onChange={(e) => setNuevo({ ...nuevo, minutos: e.target.value })} /></Campo>
        <Boton disabled={!nuevo.org_id || nuevo.asunto.trim().length < 3} onClick={() => correr(async () => {
          await api("/plataforma/soporte", { metodo: "POST", cuerpo: { ...nuevo, org_id: Number(nuevo.org_id), minutos: Number(nuevo.minutos || 0) } });
          setNuevo({ org_id: "", asunto: "", tema: "uso", minutos: "", resuelto: true });
        })}>Registrar atendido</Boton>
      </div>
      <Tabla columnas={["Ticket", "Empresa", "Tiempo", "Estado", ""]}>
        {r.tickets.map((t) => (
          <tr key={t.id} className="align-top">
            <td>{t.asunto}<div className="text-xs text-suave">{TEMAS[t.tema] ?? t.tema} · {t.origen === "cliente" ? `pedido por ${t.autor ?? "el cliente"}` : "registrado por la plataforma"} · {fechaHora(t.created_at)}</div>
              {t.detalle && <div className="text-xs">{t.detalle}</div>}{t.respuesta && <div className="text-xs text-suave">Respuesta: {t.respuesta}</div>}</td>
            <td>{t.empresa}</td>
            <td className="text-right">{t.minutos} min</td>
            <td><Etiqueta tono={t.estado === "resuelto" ? "ok" : "alerta"}>{t.estado === "resuelto" ? "Resuelto" : "Abierto"}</Etiqueta></td>
            <td>{t.estado === "abierto" && <Boton variante="secundario" onClick={() => {
              const minutos = Number(prompt("¿Cuántos minutos le dedicaste?", "15") ?? "0");
              const respuesta = prompt("Respuesta para el cliente (opcional)") || null;
              void correr(() => api(`/plataforma/soporte/${t.id}`, { metodo: "PUT", cuerpo: { minutos: Number.isFinite(minutos) ? minutos : 0, respuesta, resuelto: true } }));
            }}>Resolver</Boton>}</td>
          </tr>
        ))}
      </Tabla>
    </Tarjeta>
  );
}
