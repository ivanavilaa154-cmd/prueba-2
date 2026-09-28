"use client";
// Bandeja de avisos (sección 13.1).
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { numero, plataCorta } from "@/lib/formato";
import { TarjetaAviso, type AvisoDatos } from "@/components/Aviso";
import { Aviso, ComoSeCalcula, Selector, Vacio, cx } from "@/components/ui";

type R = { avisos: (AvisoDatos & { tipo: string })[]; conteo: { prioridad: string; n: number; impacto: string }[]; etiquetas: Record<string, string> };

export default function Avisos() {
  const [estado, setEstado] = useState("abiertas");
  const [tipo, setTipo] = useState("");
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { const t = new URLSearchParams(location.search).get("tipo"); if (t) setTipo(t); }, []);
  const cargar = useCallback(() => {
    api<R>(`/avisos?estado=${estado}${tipo ? `&tipo=${tipo}` : ""}`).then(setR).catch((e) => setError(e.message));
  }, [estado, tipo]);
  useEffect(() => { cargar(); }, [cargar]);
  const conteo = (p: string) => r?.conteo.find((c) => c.prioridad === p);
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Avisos</h1>
          <p className="text-sm text-suave">Cada aviso dice cuánta plata está en juego, por qué y qué hacer.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <div role="tablist" className="flex gap-1">
            {[["abiertas", "Abiertos"], ["cerradas", "Resueltos"]].map(([k, n]) => (
              <button key={k} role="tab" aria-selected={estado === k} onClick={() => setEstado(k)}
                className={cx("rounded-lg px-3 py-1.5 text-sm", estado === k ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>{n}</button>
            ))}
          </div>
          {r && (
            <Selector aria-label="Tipo de aviso" className="w-auto" value={tipo} onChange={(e) => setTipo(e.target.value)}>
              <option value="">Todos los tipos</option>
              {Object.entries(r.etiquetas).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Selector>
          )}
        </div>
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {r && estado === "abiertas" && (
        <div className="grid grid-cols-3 gap-3">
          {[["urgente", "Urgentes", "●", "var(--estado-critico)"], ["normal", "Normales", "▲", "var(--estado-alerta)"], ["preventiva", "Preventivos", "◆", "var(--acento)"]].map(([k, n, i, c]) => (
            <div key={k} className="rounded-xl border border-borde bg-panel p-4">
              <p className="flex items-center gap-1.5 text-sm text-suave"><span style={{ color: c }} aria-hidden="true">{i}</span>{n}</p>
              <p className="mt-1 text-2xl font-semibold">{numero(conteo(k)?.n ?? 0)}</p>
              <p className="text-xs text-suave">{plataCorta(conteo(k)?.impacto ?? 0)} en juego</p>
            </div>
          ))}
        </div>
      )}
      {!r ? !error && <p className="text-sm text-suave">Cargando…</p> : r.avisos.length === 0 ? (
        <Vacio titulo={estado === "abiertas" ? "No hay avisos abiertos" : "Todavía no hay avisos resueltos"}>Los avisos se generan después de cada cálculo (cada hora y cada noche).</Vacio>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {r.avisos.map((a) => <TarjetaAviso key={a.id} a={a} alCambiar={estado === "abiertas" ? cargar : undefined} />)}
        </div>
      )}
      <ComoSeCalcula>
        <p>Los avisos se revisan cada hora y cada noche. Si el problema se soluciona (por ejemplo, se aprobó la transferencia), el aviso se cierra solo. Si vence sin resolverse, se escala al dueño.</p>
        <p>No se repite el mismo aviso mientras siga abierto: se actualiza con los números nuevos. Los urgentes llegan también por email (se puede desactivar en Mi cuenta).</p>
        <p>Impacto: «que perdés» = ventas o plata que se pierden si no hacés nada; «en riesgo» = plata que puede perderse; «recuperable» = plata que podés recuperar o no gastar.</p>
      </ComoSeCalcula>
    </div>
  );
}
