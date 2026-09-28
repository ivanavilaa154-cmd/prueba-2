"use client";
// Medios de pago (10.8): participación, costo real (comisión + plazo) e impacto en el margen; cuenta corriente (fiado).
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { parametrosFiltro } from "@/lib/consulta";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Indicador } from "@/components/Indicador";
import { Aviso, ComoSeCalcula, Etiqueta, Tabla, Tarjeta, Vacio } from "@/components/ui";

type Medio = { medio: string; nombre: string; monto: string; tickets: number; participacion: number; comision_pct: number | null; acreditacion_dias: number; costo: string; costo_pct: number; impacto_margen_pct: number | null };
type R = { periodo: { etiqueta: string }; total: string; costo_total: string; ganancia: string | null; impacto_margen_pct: number | null; tasa_financiera_mensual: string;
  medios: Medio[]; por_ubicacion: ({ nombre: string; total: string } & Record<string, string>)[] };
type Cliente = { cliente_id: number; nombre: string; identificador: string; saldo: string; vencido: string; ultimo_pago: string | null; tramos: Record<string, string> };
type Cuentas = { clientes: Cliente[]; total: string; vencido: string; tramos: Record<string, string> };
const COLORES = ["var(--serie-1)", "var(--serie-2)", "var(--serie-3)", "var(--serie-4)"];
const TRAMOS: [string, string][] = [["0_30", "Hasta 30 días"], ["31_60", "31 a 60"], ["61_90", "61 a 90"], ["mas_90", "Más de 90"]];

export function MediosDePago() {
  const { filtro } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [cc, setCc] = useState<Cuentas | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setR(null); api<R>(`/ventas/medios?${parametrosFiltro(filtro)}`).then(setR).catch((e) => setError(e.message)); }, [filtro]);
  useEffect(() => { api<Cuentas>("/cuentas-corrientes").then(setCc).catch(() => {}); }, []);
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  // Hasta 4 medios con color propio (orden fijo por monto); el resto va a «Otros».
  const principales = r.medios.slice(0, 4);
  const otros = r.medios.slice(4).reduce((s, m) => s + m.participacion, 0);
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Indicador titulo={`Cobrado · ${r.periodo.etiqueta}`} valor={plataCorta(r.total)} />
        <Indicador titulo="Costo de cobrar" valor={plataCorta(r.costo_total)} nota="comisiones + plazo de acreditación" />
        <Indicador titulo="Se come del margen" valor={r.impacto_margen_pct === null ? "—" : `${numero(r.impacto_margen_pct * 100, 1)} %`} nota="de la ganancia bruta" />
        {cc && <Indicador titulo="Fiado pendiente" valor={plataCorta(cc.total)} nota={`${plataCorta(cc.vencido)} vencido`} />}
      </div>
      <Tarjeta titulo="Cómo te pagan">
        <div className="flex h-7 w-full gap-0.5 overflow-hidden rounded-md" role="img" aria-label="Participación de cada medio de pago">
          {principales.map((m, i) => <div key={m.medio} title={`${m.nombre}: ${numero(m.participacion * 100, 1)} %`} style={{ width: `${m.participacion * 100}%`, background: COLORES[i] }} />)}
          {otros > 0 && <div title={`Otros: ${numero(otros * 100, 1)} %`} style={{ width: `${otros * 100}%`, background: "var(--gris)" }} />}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {principales.map((m, i) => <span key={m.medio}><span style={{ color: COLORES[i] }}>■</span> {m.nombre} {numero(m.participacion * 100, 1)} %</span>)}
          {otros > 0 && <span><span style={{ color: "var(--gris)" }}>■</span> Otros {numero(otros * 100, 1)} %</span>}
        </div>
        <div className="mt-4">
          <Tabla columnas={["Medio", "Cobrado", "Participación", "Comisión", "Acreditación", "Costo real", "Sobre la ganancia"]}>
            {r.medios.map((m) => (
              <tr key={m.medio}>
                <td>{m.nombre}</td>
                <td className="text-right">{plata(m.monto)}</td>
                <td className="text-right">{numero(m.participacion * 100, 1)} %</td>
                <td className="text-right">{m.comision_pct === null ? "—" : `${numero(m.comision_pct * 100, 2)} %`}</td>
                <td className="text-right">{m.acreditacion_dias ? `${m.acreditacion_dias} días` : "en el día"}</td>
                <td className="text-right">{plata(m.costo)} <span className="text-xs text-suave">({numero(m.costo_pct * 100, 2)} %)</span></td>
                <td className="text-right">{m.impacto_margen_pct === null ? "—" : `${numero(m.impacto_margen_pct * 100, 1)} %`}</td>
              </tr>
            ))}
          </Tabla>
        </div>
        <div className="mt-3">
          <ComoSeCalcula>
            <p>Costo real = comisión del medio × lo cobrado + costo financiero de esperar la acreditación (tasa de {numero(Number(r.tasa_financiera_mensual) * 100, 1)} % mensual prorrateada por día).</p>
            <p>Las comisiones y plazos se cambian en Configuración → Medios de pago.</p>
          </ComoSeCalcula>
        </div>
      </Tarjeta>
      <Tarjeta titulo="Por sucursal">
        <Tabla columnas={["Sucursal", "Total", ...principales.map((m) => m.nombre)]}>
          {r.por_ubicacion.map((u) => (
            <tr key={u.nombre}><td>{u.nombre}</td><td className="text-right">{plata(u.total)}</td>
              {principales.map((m) => <td key={m.medio} className="text-right">{Number(u.total) ? `${numero((Number(u[m.medio] ?? 0) / Number(u.total)) * 100, 1)} %` : "—"}</td>)}</tr>
          ))}
        </Tabla>
      </Tarjeta>
      <Tarjeta titulo="Cuenta corriente (fiado)">
        {!cc ? <p className="text-sm text-suave">Cargando…</p> : cc.clientes.length === 0 ? <Vacio titulo="Nadie te debe" /> : (
          <>
            <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {TRAMOS.map(([k, t]) => (
                <div key={k} className="rounded-lg border border-borde p-2 text-sm"><p className="text-xs text-suave">{t}</p><p className="font-semibold">{plata(cc.tramos[k] ?? 0)}</p></div>
              ))}
            </div>
            <Tabla columnas={["Cliente", "Debe", "Vencido", ...TRAMOS.map(([, t]) => t), "Último pago"]}>
              {cc.clientes.map((c) => (
                <tr key={c.cliente_id}>
                  <td>{c.nombre}{Number(c.tramos.mas_90) + Number(c.tramos["61_90"]) > 0 && <span className="ml-2"><Etiqueta tono="peligro">▲ Moroso</Etiqueta></span>}</td>
                  <td className="text-right">{plata(c.saldo)}</td>
                  <td className="text-right">{plata(c.vencido)}</td>
                  {TRAMOS.map(([k]) => <td key={k} className="text-right">{Number(c.tramos[k]) ? plata(c.tramos[k]) : "—"}</td>)}
                  <td className="whitespace-nowrap">{c.ultimo_pago ? fechaCorta(c.ultimo_pago) : "nunca"}</td>
                </tr>
              ))}
            </Tabla>
            <p className="mt-2 text-xs text-suave">Los pagos cancelan primero las compras más viejas. Vencido: compras con más de 30 días.</p>
          </>
        )}
      </Tarjeta>
    </div>
  );
}
