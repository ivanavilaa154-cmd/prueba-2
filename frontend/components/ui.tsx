"use client";
// Componentes base (al estilo shadcn/ui, escritos a mano para no depender de su CLI).
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

export function cx(...clases: (string | false | null | undefined)[]) {
  return clases.filter(Boolean).join(" ");
}

type Variante = "primario" | "secundario" | "peligro" | "fantasma";
export function Boton({ variante = "primario", className, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variante?: Variante }) {
  const estilos: Record<Variante, string> = {
    primario: "bg-acento text-acento-texto hover:opacity-90",
    secundario: "border border-borde bg-panel text-texto hover:bg-panel-2",
    peligro: "border border-peligro/40 text-peligro hover:bg-peligro/10",
    fantasma: "text-suave hover:bg-panel-2 hover:text-texto",
  };
  return (
    <button
      {...props}
      className={cx("inline-flex min-h-9 items-center justify-center gap-2 rounded-lg px-3.5 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        estilos[variante], className)}
    />
  );
}

export function Tarjeta({ titulo, accion, children, className }: { titulo?: ReactNode; accion?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-xl border border-borde bg-panel p-4 sm:p-5", className)}>
      {(titulo || accion) && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          {titulo && <h2 className="text-base font-semibold">{titulo}</h2>}
          {accion}
        </div>
      )}
      {children}
    </section>
  );
}

export function Campo({ etiqueta, ayuda, children }: { etiqueta: string; ayuda?: ReactNode; children: ReactNode }) {
  return (
    <label className="grid gap-1 text-sm">
      <span className="font-medium">{etiqueta}</span>
      {children}
      {ayuda && <span className="text-xs text-suave">{ayuda}</span>}
    </label>
  );
}

const control = "min-h-9 rounded-lg border border-borde bg-panel px-3 py-1.5 text-sm text-texto placeholder:text-suave";
// Ancho completo salvo que se indique otro ancho (w-auto, w-40, max-w-xs…).
const ancho = (clase?: string) => (clase && /(^|\s)w-/.test(clase) ? "" : "w-full");
export function Entrada(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(control, ancho(props.className), props.className)} />;
}
export function Selector(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(control, ancho(props.className), props.className)} />;
}

export function Aviso({ tipo = "info", children }: { tipo?: "info" | "error" | "ok" | "alerta"; children: ReactNode }) {
  const estilos = {
    info: "border-acento/30 bg-acento/5",
    error: "border-peligro/40 bg-peligro/10 text-peligro",
    ok: "border-ok/40 bg-ok/10",
    alerta: "border-alerta/40 bg-alerta/10",
  };
  return <div role={tipo === "error" ? "alert" : "status"} className={cx("rounded-lg border px-3 py-2 text-sm", estilos[tipo])}>{children}</div>;
}

export function Etiqueta({ children, tono = "gris" }: { children: ReactNode; tono?: "gris" | "ok" | "alerta" | "peligro" | "acento" }) {
  const estilos = {
    gris: "bg-panel-2 text-suave",
    ok: "bg-ok/15 text-ok",
    alerta: "bg-alerta/15 text-alerta",
    peligro: "bg-peligro/15 text-peligro",
    acento: "bg-acento/15 text-acento",
  };
  return <span className={cx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", estilos[tono])}>{children}</span>;
}

export function Vacio({ titulo, children }: { titulo: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-borde px-4 py-8 text-center">
      <p className="font-medium">{titulo}</p>
      {children && <div className="mt-1 text-sm text-suave">{children}</div>}
    </div>
  );
}

// compacta: sin ancho mínimo, para tablas de 2 o 3 columnas dentro de una tarjeta angosta.
export function Tabla({ columnas, children, compacta = false }: { columnas: string[]; children: ReactNode; compacta?: boolean }) {
  return (
    <div className="relative -mx-4 overflow-x-auto sm:mx-0">
      <table className={cx("w-full border-collapse text-sm", !compacta && "min-w-[560px]")}>
        <thead>
          <tr className="border-b border-borde text-left text-xs uppercase tracking-wide text-suave">
            {columnas.map((c) => <th key={c} className="px-3 py-2 font-medium">{c}</th>)}
          </tr>
        </thead>
        <tbody className="[&>tr]:border-b [&>tr]:border-borde/60 [&_td]:px-3 [&_td]:py-2">{children}</tbody>
      </table>
    </div>
  );
}

export function ComoSeCalcula({ children }: { children: ReactNode }) {
  return (
    <details className="text-sm text-suave">
      <summary className="cursor-pointer select-none text-acento">¿Cómo se calcula esto?</summary>
      <div className="mt-2 space-y-1">{children}</div>
    </details>
  );
}
