"use client";
// (28, 29) Afluencia por hora y cajas necesarias por turno, próximos días.
import { Fragment, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fecha, numero } from "@/lib/formato";
import { ComoSeCalcula, Selector, Tabla, Tarjeta } from "@/components/ui";

type Hora = { hora: number; tickets: number; maximo: number; cajas: number; cajas_pico: number };
type Dia = { fecha: string; feriado: boolean; tickets: number; horas: Hora[]; turnos: { turno: string; tickets: number; cajas_max: number; horas_caja: number; hora_pico: number }[] };
type R = { ubicaciones: { id: number; nombre: string }[]; ubicacion_id: number; horas: number[]; dias: Dia[]; capacidad_caja_hora: number; capacidad_origen: string; tendencia: number };
const DIAS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];

export function Afluencia() {
  const [uid, setUid] = useState<number | null>(null);
  const [r, setR] = useState<R | null>(null);
  const [ver, setVer] = useState<"tickets" | "cajas">("tickets");
  useEffect(() => { api<R>(`/tienda/afluencia?dias=14${uid ? `&ubicacion_id=${uid}` : ""}`).then(setR).catch(() => {}); }, [uid]);
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const max = Math.max(1, ...r.dias.flatMap((d) => d.horas.map((h) => h.tickets)));
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex flex-wrap gap-2">
        <Selector aria-label="Sucursal" value={r.ubicacion_id} onChange={(e) => setUid(Number(e.target.value))}>
          {r.ubicaciones.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
        </Selector>
        <Selector aria-label="Ver" value={ver} onChange={(e) => setVer(e.target.value as "tickets" | "cajas")}>
          <option value="tickets">Clientes (tickets) por hora</option><option value="cajas">Cajas necesarias por hora</option>
        </Selector>
      </div>
      <Tarjeta titulo={ver === "tickets" ? "Afluencia esperada por hora" : "Cajas abiertas necesarias por hora"}>
        <div className="relative -mx-4 overflow-x-auto sm:mx-0">
          <div className="grid min-w-[640px] gap-px text-[11px]" style={{ gridTemplateColumns: `4.5rem repeat(${r.horas.length}, minmax(0, 1fr))` }}>
            <div />
            {r.horas.map((h) => <div key={h} className="text-center text-suave">{h}</div>)}
            {r.dias.map((d) => (
              <Fragment key={d.fecha}>
                <div className="pr-2 text-right">{DIAS[new Date(d.fecha + "T12:00").getDay()]} {fecha(d.fecha).slice(0, 5)}{d.feriado ? " ★" : ""}</div>
                {d.horas.map((h) => {
                  const intensidad = h.tickets / max;
                  return (
                    <div key={h.hora} title={`${numero(h.tickets)} tickets (hasta ${numero(h.maximo)}) · ${h.cajas} caja(s)`}
                      className="rounded-sm py-1 text-center" style={{ background: `color-mix(in oklab, var(--serie-1) ${Math.round(intensidad * 85)}%, var(--panel-2))`,
                        color: intensidad > 0.55 ? "white" : "var(--texto)" }}>
                      {ver === "tickets" ? (h.tickets >= 1 ? Math.round(h.tickets) : "") : (h.cajas || "")}
                    </div>
                  );
                })}
              </Fragment>
            ))}
          </div>
        </div>
        <p className="mt-2 text-xs text-suave">★ feriado. Pasá el mouse para ver el rango y las cajas. Una caja atiende {numero(r.capacidad_caja_hora)} tickets por hora ({r.capacidad_origen === "medido" ? "medido en tus tickets" : "valor de partida"}).</p>
      </Tarjeta>
      <Tarjeta titulo="Personal de caja por turno">
        <Tabla columnas={["Día", "Turno", "Tickets", "Cajas en el pico", "Horas de caja", "Hora pico"]}>
          {r.dias.slice(0, 7).flatMap((d) => d.turnos.map((t) => (
            <tr key={d.fecha + t.turno}><td>{DIAS[new Date(d.fecha + "T12:00").getDay()]} {fecha(d.fecha).slice(0, 5)}</td><td>{t.turno}</td>
              <td className="text-right">{numero(t.tickets)}</td><td className="text-right font-semibold">{t.cajas_max}</td><td className="text-right">{t.horas_caja}</td><td className="text-right">{t.hora_pico} h</td></tr>
          )))}
        </Tabla>
      </Tarjeta>
      <ComoSeCalcula>
        <p>Afluencia: tickets promedio de cada día de la semana y hora en las últimas 8 semanas (sin feriados), por la tendencia de las últimas 4 semanas ({numero((r.tendencia - 1) * 100, 1)} %); los feriados, al 70 %.</p>
        <p>Cajas = tickets de la hora ÷ tickets que atiende una caja por hora (el 90 % más alto de lo que atendió cada cajero en sus horas de trabajo). Para cubrir el pico con 80 % de confianza, mirá «cajas en el pico» al pasar el mouse.</p>
      </ComoSeCalcula>
    </div>
  );
}
