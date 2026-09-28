"use client";
// Filtro global persistente (sección 15): período, sucursales y canal. Queda guardado por usuario y empresa.
import { useState } from "react";
import { useSesion, type Periodo } from "./Sesion";
import { cx } from "./ui";

const PERIODOS: [Periodo, string][] = [
  ["hoy", "Hoy"], ["ayer", "Ayer"], ["7d", "Últimos 7 días"], ["mes", "Este mes"], ["mes_anterior", "Mes anterior"], ["personalizado", "Rango…"],
];

export function FiltroGlobal() {
  const { yo, filtro, setFiltro } = useSesion();
  const [abierto, setAbierto] = useState(false);
  const nombreSucursales = filtro.ubicaciones.length === 0
    ? (yo.usuario.todas_ubicaciones ? "Todas las sucursales" : yo.ubicaciones.map((u) => u.nombre).join(", ") || "Sin sucursales")
    : yo.ubicaciones.filter((u) => filtro.ubicaciones.includes(u.id)).map((u) => u.nombre).join(", ");
  const nombreCanal = filtro.canal === "todos" ? "Todos los canales" : yo.canales.find((c) => c.codigo === filtro.canal)?.nombre ?? filtro.canal;
  const nombrePeriodo = PERIODOS.find(([p]) => p === filtro.periodo)?.[1] ?? "";
  const control = "min-h-9 rounded-lg border border-borde bg-panel px-2.5 py-1 text-sm";

  function alternarSucursal(id: number) {
    const actual = new Set(filtro.ubicaciones);
    if (actual.has(id)) actual.delete(id); else actual.add(id);
    setFiltro({ ...filtro, ubicaciones: [...actual] });
  }

  return (
    <div className="border-t border-borde/60 px-4 py-2">
      <button className="flex w-full items-center justify-between text-left text-sm sm:hidden" aria-expanded={abierto} onClick={() => setAbierto(!abierto)}>
        <span className="truncate text-suave">{nombrePeriodo} · {nombreSucursales} · {nombreCanal}</span>
        <span className="ml-2 text-acento">{abierto ? "Cerrar" : "Filtros"}</span>
      </button>
      <div className={cx("mt-2 flex-wrap items-center gap-2 sm:mt-0 sm:flex", abierto ? "grid" : "hidden")}>
        <label className="sr-only" htmlFor="filtro-periodo">Período</label>
        <select id="filtro-periodo" className={control} value={filtro.periodo} onChange={(e) => setFiltro({ ...filtro, periodo: e.target.value as Periodo })}>
          {PERIODOS.map(([p, n]) => <option key={p} value={p}>{n}</option>)}
        </select>
        {filtro.periodo === "personalizado" && (
          <span className="flex items-center gap-1 text-sm">
            <input type="date" aria-label="Desde" className={control} value={filtro.desde} onChange={(e) => setFiltro({ ...filtro, desde: e.target.value })} />
            <span className="text-suave">a</span>
            <input type="date" aria-label="Hasta" className={control} value={filtro.hasta} onChange={(e) => setFiltro({ ...filtro, hasta: e.target.value })} />
          </span>
        )}
        <details className="relative">
          <summary className={cx(control, "flex max-w-72 cursor-pointer list-none items-center truncate")}>{nombreSucursales}</summary>
          <div className="absolute z-50 mt-1 w-64 rounded-lg border border-borde bg-panel p-2 shadow-lg">
            {yo.ubicaciones.length === 0 && <p className="px-2 py-1 text-sm text-suave">Todavía no hay sucursales cargadas.</p>}
            {yo.ubicaciones.map((u) => (
              <label key={u.id} className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-panel-2">
                <input type="checkbox" checked={filtro.ubicaciones.includes(u.id)} onChange={() => alternarSucursal(u.id)} />
                {u.nombre}{u.tipo === "deposito" && <span className="text-xs text-suave">(depósito)</span>}
              </label>
            ))}
            {filtro.ubicaciones.length > 0 && (
              <button className="mt-1 w-full rounded-md px-2 py-1.5 text-left text-sm text-acento hover:bg-panel-2" onClick={() => setFiltro({ ...filtro, ubicaciones: [] })}>
                Ver todas las mías
              </button>
            )}
          </div>
        </details>
        <label className="sr-only" htmlFor="filtro-canal">Canal</label>
        <select id="filtro-canal" className={control} value={filtro.canal} onChange={(e) => setFiltro({ ...filtro, canal: e.target.value })}>
          <option value="todos">Todos los canales</option>
          {yo.canales.map((c) => <option key={c.id} value={c.codigo}>{c.nombre}</option>)}
        </select>
      </div>
    </div>
  );
}
