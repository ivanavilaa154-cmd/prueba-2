"use client";
// Un aviso: prioridad (ícono + texto), impacto en pesos, explicación y botón de acción.
import Link from "next/link";
import { api } from "@/lib/api";
import { plata } from "@/lib/formato";
import { Boton, cx } from "./ui";

export type AvisoDatos = { id: number; tipo: string; prioridad: string; titulo: string; explicacion: string; impacto: string; tipo_impacto: string;
  accion: { etiqueta: string; tipo: string; destino?: string; datos?: { producto_id: number; ubicacion_id: number } }; estado: string;
  ubicacion?: string | null; created_at?: string };

const PRIORIDAD: Record<string, { icono: string; texto: string; color: string }> = {
  urgente: { icono: "●", texto: "Urgente", color: "var(--estado-critico)" },
  normal: { icono: "▲", texto: "Normal", color: "var(--estado-alerta)" },
  preventiva: { icono: "◆", texto: "Preventiva", color: "var(--acento)" },
};
const IMPACTO: Record<string, string> = { perdida: "que perdés", en_riesgo: "en riesgo", recuperable: "recuperable" };

export function TarjetaAviso({ a, alCambiar, compacto = false, sinPrioridad = false }: { a: AvisoDatos; alCambiar?: () => void; compacto?: boolean; sinPrioridad?: boolean }) {
  const p = PRIORIDAD[a.prioridad] ?? PRIORIDAD.normal;
  async function accion() {
    if (a.accion.tipo === "recuento" && a.accion.datos) {
      await api("/recuentos/marcar", { metodo: "POST", cuerpo: [a.accion.datos] });
      await api(`/avisos/${a.id}`, { metodo: "PUT", cuerpo: { estado: "resuelta" } });
      alCambiar?.();
    }
  }
  async function cerrar(estado: "resuelta" | "descartada") {
    const motivo = estado === "descartada" ? prompt("¿Por qué la descartás? (así el sistema aprende)") : null;
    if (estado === "descartada" && !motivo) return;
    await api(`/avisos/${a.id}`, { metodo: "PUT", cuerpo: { estado, motivo } });
    alCambiar?.();
  }
  return (
    <article className={cx("rounded-xl border bg-panel p-4", a.estado === "escalada" ? "border-peligro/50" : "border-borde")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className={cx("flex items-center gap-1.5 text-xs font-medium", sinPrioridad && "invisible")} style={{ color: p.color }}>
          <span aria-hidden="true">{p.icono}</span><span>{a.estado === "escalada" ? "Escalada al dueño" : p.texto}</span>
          {a.ubicacion && <span className="font-normal text-suave">· {a.ubicacion}</span>}
        </p>
        <p className="text-right"><span className="cifra text-lg font-semibold">{plata(Number(a.impacto).toFixed(0))}</span><br />
          <span className="text-xs text-suave">{IMPACTO[a.tipo_impacto] ?? ""}</span></p>
      </div>
      <h3 className="mt-1 font-semibold">{a.titulo}</h3>
      {!compacto && <p className="mt-1 text-sm text-suave">{a.explicacion}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {a.accion.tipo === "ir" && a.accion.destino
          ? <Link href={a.accion.destino} className="inline-flex min-h-9 items-center rounded-lg bg-acento px-3.5 text-sm font-medium text-acento-texto">{a.accion.etiqueta}</Link>
          : <Boton onClick={accion}>{a.accion.etiqueta}</Boton>}
        {alCambiar && !compacto && <>
          <Boton variante="fantasma" onClick={() => cerrar("resuelta")}>Ya lo resolví</Boton>
          <Boton variante="fantasma" onClick={() => cerrar("descartada")}>Descartar</Boton>
        </>}
      </div>
    </article>
  );
}
