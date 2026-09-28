"use client";
// 10.4 Ticket y tráfico: cantidad de tickets, ticket promedio, descomposición clientes/gasto y mapa de calor día × hora.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { parametrosFiltro } from "@/lib/consulta";
import { numero, plata, plataCorta } from "@/lib/formato";
import { Indicador } from "@/components/Indicador";
import { useSesion } from "@/components/Sesion";
import { Aviso, ComoSeCalcula, Tabla, Tarjeta } from "@/components/ui";

type Fila = { clave: string | number; tickets: number; ventas: string; promedio: string; unidades_promedio: string };
type R = { periodo: { etiqueta: string }; actual: { tickets: number; ventas: string; promedio: string; unidades_promedio: string };
  anterior: { tickets: number; ventas: string; promedio: string }; descomposicion: { variacion: string; efecto_clientes: string; efecto_gasto: string };
  por: Record<string, Fila[]>; mapa_calor: { dia: number; hora: number; tickets: string; facturacion: string; dias: number }[] };
const DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
// Escala secuencial de un solo tono (azul), de claro a oscuro.
const ESCALA = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"];

export function Ticket() {
  const { filtro } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [medida, setMedida] = useState<"tickets" | "facturacion">("tickets");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setR(null); api<R>(`/ventas/ticket?${parametrosFiltro(filtro)}`).then(setR).catch((e) => setError(e.message)); }, [filtro]);
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const horas = [...new Set(r.mapa_calor.map((c) => c.hora))].sort((a, b) => a - b);
  const celda = (d: number, h: number) => r.mapa_calor.find((c) => c.dia === d && c.hora === h);
  const valor = (c?: R["mapa_calor"][number]) => (c ? Number(medida === "tickets" ? c.tickets : c.facturacion) / Math.max(1, c.dias) : 0);
  const maximo = Math.max(1, ...r.mapa_calor.map((c) => valor(c)));
  const d = r.descomposicion;
  const clientes = Number(d.efecto_clientes), gasto = Number(d.efecto_gasto);
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Indicador titulo="Tickets" valor={numero(r.actual.tickets)} actual={r.actual.tickets} anterior={r.anterior.tickets} />
        <Indicador titulo="Ticket promedio" valor={plata(Number(r.actual.promedio).toFixed(0))} actual={r.actual.promedio} anterior={r.anterior.promedio} />
        <Indicador titulo="Unidades por ticket" valor={numero(r.actual.unidades_promedio, 1)} />
      </div>
      <Aviso tipo="info">
        Contra el período anterior la facturación {Number(d.variacion) >= 0 ? "subió" : "bajó"} {plataCorta(Math.abs(Number(d.variacion)))}:
        {" "}{plataCorta(Math.abs(clientes))} por {clientes >= 0 ? "más" : "menos"} clientes y {plataCorta(Math.abs(gasto))} porque cada cliente gastó {gasto >= 0 ? "más" : "menos"}.
      </Aviso>
      <Tarjeta titulo="¿Cuándo viene la gente? (promedio por día)" accion={
        <div className="flex gap-1 text-sm">
          {(["tickets", "facturacion"] as const).map((m) => (
            <button key={m} onClick={() => setMedida(m)} aria-pressed={medida === m} className={`rounded-lg px-2.5 py-1 ${medida === m ? "bg-acento text-acento-texto" : "border border-borde"}`}>{m === "tickets" ? "Tickets" : "Facturación"}</button>
          ))}
        </div>}>
        <div className="overflow-x-auto">
          <table className="border-separate border-spacing-0.5 text-xs">
            <thead><tr><th />{horas.map((h) => <th key={h} className="px-1 font-normal text-suave">{h}h</th>)}</tr></thead>
            <tbody>
              {DIAS.map((nombre, di) => (
                <tr key={nombre}>
                  <th className="pr-2 text-left font-normal text-suave">{nombre}</th>
                  {horas.map((h) => {
                    const c = celda(di, h);
                    const v = valor(c);
                    const nivel = v <= 0 ? -1 : Math.min(ESCALA.length - 1, Math.floor((v / maximo) * ESCALA.length));
                    const texto = medida === "tickets" ? `${numero(v, 0)} tickets` : plataCorta(v);
                    return (
                      <td key={h} title={`${nombre} ${h} h: ${texto} en promedio`} className="h-7 min-w-9 rounded text-center"
                        style={{ background: nivel < 0 ? "var(--panel-2)" : ESCALA[nivel], color: nivel >= 4 ? "#fff" : "#0b0b0b" }}>
                        {medida === "tickets" && v > 0 ? numero(v, 0) : ""}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-suave">Más oscuro = más movimiento. Usalo para planificar turnos y reposición de góndola.</p>
      </Tarjeta>
      <div className="grid gap-4 lg:grid-cols-2">
        {(["ubicacion", "canal"] as const).map((dim) => (
          <Tarjeta key={dim} titulo={dim === "ubicacion" ? "Por sucursal" : "Por canal"}>
            <Tabla columnas={[dim === "ubicacion" ? "Sucursal" : "Canal", "Tickets", "Ticket promedio", "Unid./ticket"]}>
              {r.por[dim].map((f) => (
                <tr key={String(f.clave)}><td>{f.clave}</td><td className="cifra text-right">{numero(f.tickets)}</td>
                  <td className="cifra text-right">{plata(Number(f.promedio).toFixed(0))}</td><td className="cifra text-right">{numero(f.unidades_promedio, 1)}</td></tr>
              ))}
            </Tabla>
          </Tarjeta>
        ))}
      </div>
      <ComoSeCalcula>
        <p>Ticket promedio = facturación ÷ cantidad de tickets. La variación se separa en: (tickets de ahora − tickets de antes) × ticket promedio de antes (más o menos clientes) y el resto (cuánto gasta cada cliente). Las dos partes suman la variación.</p>
        <p>El mapa de calor usa al menos las últimas 4 semanas y muestra el promedio por día de cada franja horaria.</p>
      </ComoSeCalcula>
    </div>
  );
}
