"use client";
// Comisión y plazo de acreditación de cada medio de pago (para el costo real de cobrar).
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Entrada, Tabla, Tarjeta } from "@/components/ui";

const MEDIOS: [string, string][] = [["efectivo", "Efectivo"], ["debito", "Débito"], ["credito", "Crédito"], ["qr", "QR / billetera"], ["transferencia", "Transferencia"],
  ["cuenta_corriente", "Cuenta corriente"]];
type Cfg = Record<string, { comision: number; acreditacion_dias: number }>;

export function MediosPago() {
  const { puede } = useSesion();
  const [cfg, setCfg] = useState<Record<string, { comision: string; dias: string }>>({});
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  useEffect(() => {
    api<Cfg>("/config/medios").then((c) => setCfg(Object.fromEntries(MEDIOS.map(([m]) => [m, {
      comision: c[m] ? String(Math.round(c[m].comision * 10000) / 100) : "0", dias: c[m] ? String(c[m].acreditacion_dias) : "0" }])))).catch(() => {});
  }, []);
  async function guardar() {
    try {
      await api("/config/medios", { metodo: "PUT", cuerpo: MEDIOS.map(([m]) => ({ medio: m, comision: Number((cfg[m]?.comision ?? "0").replace(",", ".")) / 100,
        acreditacion_dias: Number(cfg[m]?.dias ?? 0) })) });
      setMensaje({ tipo: "ok", texto: "Guardado. El costo de cada medio se recalcula en Ventas → Medios de pago." });
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo guardar." });
    }
  }
  const editable = puede("configurar_empresa");
  return (
    <Tarjeta titulo="Medios de pago">
      {mensaje && <div className="mb-3"><Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso></div>}
      <p className="mb-3 text-sm text-suave">Lo que te cobra el procesador y cuántos días tarda en acreditarte. Sirve para calcular cuánto te cuesta cada forma de cobro.</p>
      <Tabla columnas={["Medio", "Comisión", "Acreditación"]}>
        {MEDIOS.map(([m, n]) => (
          <tr key={m}>
            <td>{n}</td>
            <td><span className="inline-flex items-center gap-1"><Entrada className="w-20 text-right" inputMode="decimal" disabled={!editable} value={cfg[m]?.comision ?? ""}
              onChange={(e) => setCfg({ ...cfg, [m]: { ...cfg[m], comision: e.target.value } })} /> %</span></td>
            <td><span className="inline-flex items-center gap-1"><Entrada className="w-20 text-right" inputMode="numeric" disabled={!editable} value={cfg[m]?.dias ?? ""}
              onChange={(e) => setCfg({ ...cfg, [m]: { ...cfg[m], dias: e.target.value } })} /> días</span></td>
          </tr>
        ))}
      </Tabla>
      {editable && <div className="mt-3"><Boton onClick={guardar}>Guardar</Boton></div>}
    </Tarjeta>
  );
}
