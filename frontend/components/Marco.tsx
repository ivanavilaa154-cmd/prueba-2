"use client";
// Estructura común: menú lateral, barra superior con la empresa y el filtro global, y cuenta del usuario.
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api, BASE } from "@/lib/api";
import { ROLES } from "@/lib/formato";
import { INICIO_POR_ROL, ROLES_SOLO_DISTRIBUIDOR, SECCIONES, SECCIONES_DISTRIBUIDOR } from "@/lib/secciones";
import { cx } from "./ui";
import { FiltroGlobal } from "./FiltroGlobal";
import { NoIncluido } from "./NoIncluido";
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
  const { yo, incluye } = useSesion();
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

  // Privacidad (13.5): cada usuario acepta la política vigente antes de usar la plataforma; si la empresa pidió la baja, se avisa.
  const [privacidad, setPrivacidad] = useState<{ aceptada: boolean; version: string; baja: { se_borra: string } | null } | null>(null);
  useEffect(() => { api<{ aceptada: boolean; version: string; baja: { se_borra: string } | null }>("/privacidad").then(setPrivacidad).catch(() => {}); }, []);
  async function aceptarPrivacidad() {
    await api("/privacidad/aceptar", { metodo: "POST" });
    setPrivacidad((p) => (p ? { ...p, aceptada: true } : p));
  }

  const router = useRouter();
  const rol = yo.usuario.es_superadmin ? "dueno" : yo.usuario.rol ?? "";
  const modos = yo.empresa?.modos ?? ["comercio"];
  const soloDistribuidor = ROLES_SOLO_DISTRIBUIDOR.includes(rol);
  const visibles = (rol === "distribuidor" ? SECCIONES_DISTRIBUIDOR : SECCIONES).filter((s) =>
    (!s.modo || modos.includes(s.modo)) && (!s.permiso || yo.permisos.includes(s.permiso))
    && (!soloDistribuidor || s.modo === "distribuidor"));
  if (soloDistribuidor) visibles.push({ ruta: "/configuracion/#cuenta", nombre: "Mi cuenta", que_hace: "Tu clave y el segundo factor." });
  useEffect(() => {        // el vendedor y cobranzas arrancan en su pantalla
    if (ruta === "/" && INICIO_POR_ROL[rol]) router.replace(INICIO_POR_ROL[rol]);
  }, [ruta, rol, router]);
  const seccion = SECCIONES.find((s) => s.ruta !== "/" && ruta.startsWith(s.ruta));
  const bloqueada = Boolean(seccion?.modulo && !incluye(seccion.modulo));
  const activa = (r: string) => (r === "/" ? ruta === "/" : ruta.startsWith(r));
  const menu = (
    <nav aria-label="Secciones" className="grid gap-0.5 p-2">
      {visibles.map((s) => (
        <Link key={s.ruta} href={s.ruta} onClick={() => setMenuAbierto(false)}
          className={cx("flex items-center justify-between rounded-lg px-3 py-2 text-sm",
            activa(s.ruta) ? "bg-acento/12 font-semibold text-acento" : s.modulo && !incluye(s.modulo) ? "text-suave hover:bg-panel-2" : "text-texto hover:bg-panel-2")}>
          <span>{s.nombre}</span>
          {s.llega && <span className="text-[10px] uppercase tracking-wide text-suave">pronto</span>}
          {s.modulo && !incluye(s.modulo) && <span className="text-[10px] uppercase tracking-wide text-suave" title="No incluido en tu plan">🔒 plan</span>}
        </Link>
      ))}
      {yo.usuario.es_superadmin && (
        <Link href="/plataforma/" className="mt-2 rounded-lg px-3 py-2 text-sm text-suave hover:bg-panel-2">Plataforma (todas las empresas)</Link>
      )}
      {(yo.usuario.es_superadmin || yo.usuario.rol === "dueno") && (
        <a href="/" className="rounded-lg px-3 py-2 text-sm text-suave hover:bg-panel-2">Panel ERP (chat y decisiones) ↗</a>
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

      {privacidad && !privacidad.aceptada && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4" role="dialog" aria-modal="true" aria-labelledby="titulo-privacidad">
          <div className="grid max-w-md gap-3 rounded-2xl bg-panel p-6 shadow-xl">
            <h2 id="titulo-privacidad" className="text-lg font-semibold">Política de privacidad</h2>
            <p className="text-sm text-suave">Para usar la plataforma tenés que aceptar la política de privacidad (Ley 25.326): qué datos se usan, para qué,
              cómo se protegen y cómo pedir el acceso o la supresión.</p>
            <a className="text-sm text-acento underline" href={`${BASE}/privacidad/`} target="_blank" rel="noreferrer">Leer la política (versión {privacidad.version}) ↗</a>
            <div className="flex gap-2"><button className="rounded-lg bg-acento px-3.5 py-2 text-sm font-medium text-acento-texto" onClick={aceptarPrivacidad}>Leí y acepto</button>
              <button className="rounded-lg border border-borde px-3.5 py-2 text-sm" onClick={salir}>Salir</button></div>
          </div>
        </div>
      )}
      <div className="min-w-0">
        {yo.suscripcion && !yo.usuario.es_superadmin && (!yo.suscripcion.al_dia || yo.suscripcion.por_vencer) && (
          <div className={cx("px-4 py-2 text-sm", yo.suscripcion.al_dia ? "bg-alerta/15" : "bg-peligro/15")}>
            {yo.suscripcion.al_dia
              ? `${yo.suscripcion.en_prueba ? "Tu período de prueba" : "Tu suscripción"} vence en ${yo.suscripcion.dias_restantes} día${yo.suscripcion.dias_restantes === 1 ? "" : "s"}.`
              : "La suscripción venció: la cuenta quedó en solo lectura (tus datos están intactos)."}{" "}
            <Link className="underline" href="/configuracion/#plan">Ver tu plan</Link>
          </div>
        )}
        {privacidad?.baja && (
          <div className="bg-peligro/15 px-4 py-2 text-sm">
            Esta empresa pidió la baja: el {new Date(privacidad.baja.se_borra).toLocaleDateString("es-AR")} se borran todos sus datos.{" "}
            <Link className="underline" href="/configuracion/#datos">Cancelar la baja</Link>
          </div>
        )}
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
          {yo.empresa && yo.usuario.rol !== "distribuidor" && !soloDistribuidor && <FiltroGlobal />}
        </header>
        <main className="mx-auto max-w-6xl px-4 py-5 sm:py-6">{bloqueada ? <NoIncluido /> : children}</main>
      </div>
    </div>
  );
}
