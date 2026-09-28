"use client";
// Control de caja y anomalías (sección 10.7).
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { parametrosFiltro } from "@/lib/consulta";
import { fechaCorta, fechaHora, numero, plata } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, ComoSeCalcula, Tabla, Tarjeta } from "@/components/ui";

type Cajero = { ubicacion: string; cajero: string; tickets: number; anulaciones: number; monto_anulado: string; devoluciones: number; monto_devuelto: string;
  descuentos_manuales: number; monto_descuentos: string; fuera_de_lista: number; tasa_anulaciones: string; tasa_descuentos: string; tasa_devoluciones: string;
  z_tasa_anulaciones: number | null; z_tasa_descuentos: number | null };
type R = { periodo: { desde: string; hasta: string; etiqueta: string }; cajeros: Cajero[];
  alertas: { ubicacion: string; cajero: string; medida: string; valor: string; promedio_otros: number; z: number; monto: string }[];
  por_turno: { ubicacion: string; turno: string; tickets: number; anulaciones: number; devoluciones: number }[];
  detalle: { tipo: string; cajero: string; motivo: string; fecha_hora: string; monto: string; ubicacion: string; numero_externo: string }[];
  diferencias_inventario: { ubicacion: string; faltantes: number; monto: string }[] };

export default function Caja() {
  const { filtro } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setR(null); api<R>(`/caja?${parametrosFiltro(filtro)}`).then(setR).catch((e) => setError(e.message)); }, [filtro]);
  return (
    <div className="grid gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Caja y control</h1>
        <p className="text-sm text-suave">Anulaciones, devoluciones y descuentos manuales por cajero y turno, y lo que se aparta de lo normal.</p>
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {!r ? !error && <p className="text-sm text-suave">Cargando…</p> : (
        <>
          <p className="text-sm text-suave">Período: {r.periodo.etiqueta} ({fechaCorta(r.periodo.desde)} a {fechaCorta(r.periodo.hasta)}).</p>
          {r.alertas.length === 0 ? <Aviso tipo="ok">No hay cajeros que se aparten del resto en este período.</Aviso> : (
            <Tarjeta titulo="Para revisar">
              <ul className="grid gap-2">
                {r.alertas.map((a, i) => (
                  <li key={i} className="flex gap-3 rounded-lg border border-peligro/30 bg-peligro/5 p-3 text-sm">
                    <span aria-hidden="true" className="text-lg text-peligro">▲</span>
                    <span><strong>{a.cajero}</strong> ({a.ubicacion}): {numero(a.valor, 1)} % de tickets con {a.medida}, contra {numero(a.promedio_otros, 1)} % del resto de la sucursal
                      ({a.z > 10 ? "más de 10" : numero(a.z, 1)} desvíos). Monto: {plata(a.monto)}. Revisá los tickets de abajo y hablá con el encargado del turno.</span>
                  </li>
                ))}
              </ul>
            </Tarjeta>
          )}
          <Tarjeta titulo="Por cajero">
            <TablaDatos filas={r.cajeros} idFila={(c) => `${c.ubicacion}-${c.cajero}`} nombreArchivo="control-de-caja"
              columnas={[
                { id: "suc", titulo: "Sucursal", valor: (c) => c.ubicacion },
                { id: "cajero", titulo: "Cajero", valor: (c) => c.cajero, render: (c) => <span>{c.cajero}{(c.z_tasa_anulaciones ?? 0) >= 2 || (c.z_tasa_descuentos ?? 0) >= 2 ? <span className="ml-1 text-peligro">▲</span> : null}</span> },
                { id: "tk", titulo: "Tickets", valor: (c) => c.tickets, derecha: true },
                { id: "anu", titulo: "Anulaciones", valor: (c) => Number(c.tasa_anulaciones), render: (c) => `${c.anulaciones} (${numero(c.tasa_anulaciones, 1)} %)`, derecha: true },
                { id: "monanu", titulo: "$ anulado", valor: (c) => Number(c.monto_anulado), render: (c) => plata(c.monto_anulado), derecha: true, ocultarEnCelular: true },
                { id: "desc", titulo: "Desc. manuales", valor: (c) => Number(c.tasa_descuentos), render: (c) => `${c.descuentos_manuales} (${numero(c.tasa_descuentos, 1)} %)`, derecha: true },
                { id: "mondesc", titulo: "$ descontado", valor: (c) => Number(c.monto_descuentos), render: (c) => plata(c.monto_descuentos), derecha: true, ocultarEnCelular: true },
                { id: "dev", titulo: "Devoluciones", valor: (c) => c.devoluciones, derecha: true },
                { id: "lista", titulo: "Fuera de lista", valor: (c) => c.fuera_de_lista, derecha: true, ocultarEnCelular: true },
              ]} />
          </Tarjeta>
          <div className="grid gap-4 lg:grid-cols-2">
            <Tarjeta titulo="Por turno">
              <Tabla columnas={["Sucursal", "Turno", "Tickets", "Anulaciones", "Devoluciones"]}>
                {r.por_turno.map((t) => <tr key={t.ubicacion + t.turno}><td>{t.ubicacion}</td><td>{t.turno}</td><td className="cifra text-right">{numero(t.tickets)}</td>
                  <td className="cifra text-right">{numero(t.anulaciones)}</td><td className="cifra text-right">{numero(t.devoluciones)}</td></tr>)}
              </Tabla>
            </Tarjeta>
            <Tarjeta titulo="Faltantes en recuentos (90 días)">
              {r.diferencias_inventario.length === 0 ? <p className="text-sm text-suave">Sin recuentos con faltantes.</p> : (
                <Tabla columnas={["Sucursal", "Productos con faltante", "Plata"]}>
                  {r.diferencias_inventario.map((d) => <tr key={d.ubicacion}><td>{d.ubicacion}</td><td className="cifra text-right">{numero(d.faltantes)}</td><td className="cifra text-right">{plata(d.monto)}</td></tr>)}
                </Tabla>
              )}
            </Tarjeta>
          </div>
          <Tarjeta titulo="Anulaciones y devoluciones (detalle)">
            <TablaDatos filas={r.detalle} idFila={(d) => `${d.numero_externo}-${d.fecha_hora}-${d.tipo}`} nombreArchivo="anulaciones-y-devoluciones" porPagina={15}
              columnas={[
                { id: "cuando", titulo: "Cuándo", valor: (d) => d.fecha_hora, render: (d) => fechaHora(d.fecha_hora) },
                { id: "tipo", titulo: "Tipo", valor: (d) => d.tipo, render: (d) => (d.tipo === "anulacion" ? "Anulación" : "Devolución") },
                { id: "suc", titulo: "Sucursal", valor: (d) => d.ubicacion },
                { id: "cajero", titulo: "Cajero", valor: (d) => d.cajero },
                { id: "motivo", titulo: "Motivo", valor: (d) => d.motivo },
                { id: "ticket", titulo: "Ticket", valor: (d) => d.numero_externo, ocultarEnCelular: true },
                { id: "monto", titulo: "Monto", valor: (d) => Number(d.monto), render: (d) => plata(d.monto), derecha: true },
              ]} />
          </Tarjeta>
        </>
      )}
      <ComoSeCalcula>
        <p>Para cada cajero se calcula el % de tickets con anulaciones, descuentos manuales y devoluciones, y cuántos desvíos estándar se aleja del resto de los cajeros de su sucursal. Se marca cuando está a 2 desvíos o más y además supera en un 50 % el promedio de los demás.</p>
        <p>«Fuera de lista» = líneas cobradas a un precio distinto del de lista sin una promoción cargada.</p>
      </ComoSeCalcula>
    </div>
  );
}
