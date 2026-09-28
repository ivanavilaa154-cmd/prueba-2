"use client";
// Metas y proyección (10.13): cumplimiento al ritmo actual, con el patrón de los días que faltan.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaCorta, numero, plata } from "@/lib/formato";
import { Aviso, Boton, ComoSeCalcula, Entrada, Tabla, Tarjeta } from "@/components/ui";

type Metrica = { metrica: "ventas" | "ganancia" | "margen"; meta: string | null; actual: number; proyeccion: number; cumplimiento: number | null; semaforo: string };
type R = { mes: string; hasta: string; dias_transcurridos: number; dias_mes: number; puede_editar: boolean; filas: { ubicacion_id: number | null; ubicacion: string; metricas: Metrica[] }[] };
const NOMBRE = { ventas: "Ventas", ganancia: "Ganancia", margen: "Margen" };
const ESTADO: Record<string, { texto: string; icono: string; color: string }> = {
  verde: { texto: "Se cumple", icono: "✓", color: "var(--estado-bien)" }, amarillo: { texto: "Justo", icono: "▲", color: "var(--estado-alerta)" },
  rojo: { texto: "No llega", icono: "●", color: "var(--estado-critico)" }, gris: { texto: "Sin meta", icono: "", color: "var(--gris)" },
};
const valor = (m: Metrica, v: number | string | null) => (v === null ? "—" : m.metrica === "margen" ? `${numero(Number(v) * 100, 1)} %` : plata(v));

export function Metas() {
  const [r, setR] = useState<R | null>(null);
  const [editar, setEditar] = useState(false);
  const [valores, setValores] = useState<Record<string, string>>({});
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const cargar = useCallback(() => api<R>("/metas").then((d) => {
    setR(d);
    setValores(Object.fromEntries(d.filas.filter((f) => f.ubicacion_id !== null).flatMap((f) => f.metricas.map((m) => [
      `${f.ubicacion_id}-${m.metrica}`, m.meta === null ? "" : m.metrica === "margen" ? String(Math.round(Number(m.meta) * 1000) / 10) : String(Math.round(Number(m.meta)))]))));
  }), []);
  useEffect(() => { cargar(); }, [cargar]);
  async function guardar() {
    if (!r) return;
    const cuerpo = Object.entries(valores).map(([k, v]) => {
      const [u, metrica] = k.split("-");
      const n = v.trim() === "" ? null : Number(v.replace(/\./g, "").replace(",", "."));
      return { mes: r.mes, ubicacion_id: Number(u), metrica, valor: n === null ? null : metrica === "margen" ? n / 100 : n };
    });
    try {
      await api("/metas", { metodo: "PUT", cuerpo });
      setMensaje({ tipo: "ok", texto: "Metas guardadas." });
      setEditar(false);
      cargar();
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo guardar." });
    }
  }
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const metricas = r.filas[0]?.metricas.map((m) => m.metrica) ?? [];
  return (
    <div className="grid grid-cols-1 gap-4">
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
      <Tarjeta titulo={`Metas del mes · al ${fechaCorta(r.hasta)} (día ${r.dias_transcurridos} de ${r.dias_mes})`}
        accion={r.puede_editar && (editar ? <div className="flex gap-2"><Boton variante="secundario" onClick={() => setEditar(false)}>Cancelar</Boton><Boton onClick={guardar}>Guardar metas</Boton></div>
          : <Boton variante="secundario" onClick={() => setEditar(true)}>Cargar metas</Boton>)}>
        <Tabla columnas={["", ...metricas.flatMap((m) => [`${NOMBRE[m]}: meta`, "Proyección", ""])]}>
          {r.filas.map((f) => (
            <tr key={f.ubicacion} className={f.ubicacion_id === null ? "font-semibold" : ""}>
              <td>{f.ubicacion}</td>
              {f.metricas.flatMap((m) => {
                const e = ESTADO[m.semaforo];
                return [
                  <td key={`${m.metrica}-m`} className="whitespace-nowrap text-right">
                    {editar && f.ubicacion_id !== null ? (
                      <Entrada className="w-28 text-right" inputMode="decimal" value={valores[`${f.ubicacion_id}-${m.metrica}`] ?? ""} placeholder={m.metrica === "margen" ? "%" : "$"}
                        onChange={(ev) => setValores({ ...valores, [`${f.ubicacion_id}-${m.metrica}`]: ev.target.value })} />
                    ) : valor(m, m.meta)}
                  </td>,
                  <td key={`${m.metrica}-p`} className="whitespace-nowrap text-right">{valor(m, m.proyeccion)}<span className="block text-xs font-normal text-suave">hoy {valor(m, m.actual)}</span></td>,
                  <td key={`${m.metrica}-s`} className="whitespace-nowrap text-sm font-normal">
                    {m.semaforo !== "gris" && <><span aria-hidden="true" style={{ color: e.color }}>{e.icono}</span> {e.texto}{m.cumplimiento !== null && ` (${numero(m.cumplimiento * 100, 1)} %)`}</>}
                  </td>,
                ];
              })}
            </tr>
          ))}
        </Tabla>
        <div className="mt-3">
          <ComoSeCalcula>
            <p>Proyección = lo vendido hasta hoy + cada día que falta a la venta diaria reciente, ajustada por el día de la semana (los sábados se vende más) y por el inicio de mes (días 1 a 5).</p>
            <p>✓ Se cumple: la proyección llega a la meta. ▲ Justo: entre 95 % y 100 %. ● No llega: menos de 95 %.</p>
          </ComoSeCalcula>
        </div>
      </Tarjeta>
    </div>
  );
}
