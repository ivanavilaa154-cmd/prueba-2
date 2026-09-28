"use client";
// Estructura común: menú lateral, barra superior con la empresa y el filtro global, y cuenta del usuario.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";
import { api, BASE } from "@/lib/api";
import { ROLES } from "@/lib/formato";
import { SECCIONES } from "@/lib/secciones";
import { cx } from "./ui";
import { FiltroGlobal } from "./FiltroGlobal";
import { useSesion } from "./Sesion";

function alternarTema() {
  const oscuro = document.documentElement.classList.toggle("dark");
  try {
    localStorage.setItem("retail_tema", oscuro ? "oscuro" : "claro");
  } catch {
    /* sin almacenamiento local */
  }
}

export function Marco({ children }: { children: ReactNode }) {
  const { yo } = useSesion();
  const ruta = usePathname();
  const [menuAbierto, setMenuAbierto] = useState(false);

  async function salir() {
    await api("/sesion", { metodo: "DELETE" }).catch(() => null);
    location.href = `${BASE}/ingresar/`;
  }
  async function salirDeEmpresa() {
    await api("/plataforma/entrar", { metodo: "POST", cuerpo: { org_id: null } });
    location.href = `${BASE}/plataforma/`;
  }

  const activa = (r: string) => (r === "/" ? ruta === "/" : ruta.startsWith(r));
  const menu = (
    <nav aria-label="Secciones" className="grid gap-0.5 p-2">
      {SECCIONES.map((s) => (
        <Link key={s.ruta} href={s.ruta} onClick={() => setMenuAbierto(false)}
          className={cx("flex items-center justify-between rounded-lg px-3 py-2 text-sm",
            activa(s.ruta) ? "bg-acento/12 font-semibold text-acento" : "text-texto hover:bg-panel-2")}>
          <span>{s.nombre}</span>
          {s.llega && <span className="text-[10px] uppercase tracking-wide text-suave">pronto</span>}
        </Link>
      ))}
      {yo.usuario.es_superadmin && (
        <Link href="/plataforma/" className="mt-2 rounded-lg px-3 py-2 text-sm text-suave hover:bg-panel-2">Plataforma (todas las empresas)</Link>
      )}
    </nav>
  );

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[240px_1fr]">
      <aside className="sticky top-0 hidden h-dvh overflow-y-auto border-r border-borde bg-panel lg:block">
        <div className="px-5 pb-2 pt-5">
          <p className="text-xs font-semibold uppercase tracking-wider text-suave">Retail IA</p>
          <p className="truncate font-semibold" title={yo.empresa?.nombre}>{yo.empresa?.nombre ?? "Sin empresa"}</p>
        </div>
        {menu}
      </aside>

      {menuAbierto && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menú">
          <button className="absolute inset-0 bg-black/40" aria-label="Cerrar menú" onClick={() => setMenuAbierto(false)} />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85vw] overflow-y-auto bg-panel shadow-xl">
            <div className="px-5 pb-2 pt-5 font-semibold">{yo.empresa?.nombre}</div>
            {menu}
          </div>
        </div>
      )}

      <div className="min-w-0">
        {yo.usuario.es_superadmin && yo.empresa && (
          <div className="flex flex-wrap items-center justify-between gap-2 bg-alerta/15 px-4 py-2 text-sm">
            <span>Estás dentro de <strong>{yo.empresa.nombre}</strong> como administración de la plataforma. Todo lo que hagas queda auditado.</span>
            <button className="underline" onClick={salirDeEmpresa}>Salir de esta empresa</button>
          </div>
        )}
        <header className="sticky top-0 z-30 border-b border-borde bg-panel/95 backdrop-blur">
          <div className="flex items-center gap-2 px-4 py-2.5">
            <button className="rounded-lg p-2 hover:bg-panel-2 lg:hidden" aria-label="Abrir menú" onClick={() => setMenuAbierto(true)}>
              <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
            </button>
            <span className="truncate font-semibold lg:hidden">{yo.empresa?.nombre}</span>
            <div className="ml-auto flex items-center gap-1">
              <button onClick={alternarTema} className="rounded-lg p-2 text-suave hover:bg-panel-2" aria-label="Cambiar entre modo claro y oscuro" title="Modo claro / oscuro">
                <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2a8 8 0 1 0 0 16V2Z" fill="currentColor" /><circle cx="10" cy="10" r="7.2" fill="none" stroke="currentColor" strokeWidth="1.6" /></svg>
              </button>
              <details className="relative">
                <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-panel-2">
                  <span className="grid size-7 place-items-center rounded-full bg-acento/15 text-xs font-semibold text-acento">{yo.usuario.nombre.slice(0, 1)}</span>
                  <span className="hidden text-left text-sm leading-tight sm:block">
                    {yo.usuario.nombre}<br /><span className="text-xs text-suave">{yo.usuario.es_superadmin ? "Plataforma" : ROLES[yo.usuario.rol ?? ""]}</span>
                  </span>
                </summary>
                <div className="absolute right-0 z-50 mt-1 w-52 rounded-lg border border-borde bg-panel p-1 shadow-lg">
                  <Link href="/configuracion/#cuenta" className="block rounded-md px-3 py-2 text-sm hover:bg-panel-2">Mi cuenta</Link>
                  <button onClick={salir} className="block w-full rounded-md px-3 py-2 text-left text-sm hover:bg-panel-2">Salir</button>
                </div>
              </details>
            </div>
          </div>
          {yo.empresa && <FiltroGlobal />}
        </header>
        <main className="mx-auto max-w-6xl px-4 py-5 sm:py-6">{children}</main>
      </div>
    </div>
  );
}
