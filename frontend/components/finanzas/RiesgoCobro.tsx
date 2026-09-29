"use client";
// (41) Riesgo de cobro de las cuentas corrientes (fiado).
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fecha, numero, plata, plataCorta } from "@/lib/formato";
import { Indicador } from "@/components/Indicador";
import { ComoSeCalcula, Etiqueta, Tabla, Tarjeta, Vacio } from "@/components/ui";

type C = { cliente_id: number; nombre: string; saldo: string; vencido: string; ultimo_pago: string | null; prob_no_cobro: number; en_riesgo: number;
  semaforo: string; razones: string[]; accion: string };

export function RiesgoCobro() {
  const [r, setR] = useState<{ clientes: C[]; saldo: number; en_riesgo: number; rojos: number } | null>(null);
  useEffect(() => { api<typeof r>("/cuentas-corrientes/riesgo").then(setR).catch(() => {}); }, []);
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <Indicador titulo="Saldo en cuentas corrientes" valor={plataCorta(r.saldo)} />
        <Indicador titulo="Deuda en riesgo" valor={plataCorta(r.en_riesgo)} nota="saldo × probabilidad de no cobrar" />
        <Indicador titulo="Clientes en rojo" valor={numero(r.rojos)} />
      </div>
      <Tarjeta titulo="Clientes por riesgo">
        {r.clientes.length === 0 ? <Vacio titulo="No hay saldos de fiado" /> : (
          <Tabla columnas={["Cliente", "Saldo", "Vencido", "Riesgo", "Por qué", "Qué hacer"]}>
            {r.clientes.map((c) => (
              <tr key={c.cliente_id} className="align-top">
                <td>{c.nombre}<span className="block text-xs text-suave">último pago {c.ultimo_pago ? fecha(c.ultimo_pago) : "—"}</span></td>
                <td className="text-right">{plata(c.saldo)}</td><td className="text-right">{plata(c.vencido)}</td>
                <td><Etiqueta tono={c.semaforo === "rojo" ? "peligro" : c.semaforo === "amarillo" ? "alerta" : "ok"}>{c.semaforo === "rojo" ? "▲ " : ""}{numero(c.prob_no_cobro * 100)} %</Etiqueta></td>
                <td className="text-sm">{c.razones.join(" · ") || "—"}</td><td className="min-w-[12rem] text-sm">{c.accion}</td>
              </tr>
            ))}
          </Tabla>
        )}
      </Tarjeta>
      <ComoSeCalcula>
        <p>Probabilidad de no cobrar: suma puntos por la parte vencida, la deuda de más de 60 días, más de 45 días sin pagar y un saldo que crece; resta si viene pagando lo que compra. Los puntos se pasan a una probabilidad (curva logística).</p>
      </ComoSeCalcula>
    </div>
  );
}
