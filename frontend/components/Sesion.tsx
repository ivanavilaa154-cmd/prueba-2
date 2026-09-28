"use client";
// Datos de la sesión (usuario, empresa, permisos, sucursales y canales visibles) y el filtro global.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, BASE, ErrorApi, type Yo } from "@/lib/api";

export type Periodo = "hoy" | "ayer" | "7d" | "mes" | "mes_anterior" | "personalizado";
export type Filtro = { periodo: Periodo; desde: string; hasta: string; ubicaciones: number[]; canal: string };
const FILTRO_INICIAL: Filtro = { periodo: "mes", desde: "", hasta: "", ubicaciones: [], canal: "todos" };

type Valor = {
  yo: Yo;
  recargar: () => Promise<void>;
  puede: (permiso: string) => boolean;
  filtro: Filtro;
  setFiltro: (f: Filtro) => void;
};
const Contexto = createContext<Valor | null>(null);

export function useSesion(): Valor {
  const v = useContext(Contexto);
  if (!v) throw new Error("useSesion fuera de <ProveedorSesion>");
  return v;
}

function leerFiltro(clave: string): Filtro {
  try {
    const guardado = localStorage.getItem(clave);
    return guardado ? { ...FILTRO_INICIAL, ...JSON.parse(guardado) } : FILTRO_INICIAL;
  } catch {
    return FILTRO_INICIAL;
  }
}

export function ProveedorSesion({ children }: { children: ReactNode }) {
  const [yo, setYo] = useState<Yo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filtro, setFiltroEstado] = useState<Filtro>(FILTRO_INICIAL);

  const recargar = useCallback(async () => {
    try {
      const datos = await api<Yo>("/yo");
      setYo(datos);
      setFiltroEstado(leerFiltro(`retail_filtro_${datos.usuario.id}_${datos.empresa?.id ?? 0}`));
      if (datos.usuario.es_superadmin && !datos.empresa && !location.pathname.startsWith(`${BASE}/plataforma`)) {
        location.href = `${BASE}/plataforma/`;
      }
    } catch (e) {
      if (e instanceof ErrorApi && e.estado === 401) {
        location.href = `${BASE}/ingresar/`;
        return;
      }
      setError(e instanceof Error ? e.message : "No se pudo cargar la sesión.");
    }
  }, []);

  useEffect(() => {
    // Carga inicial de la sesión desde la API (sin servidor Node: es un sitio estático).
    void recargar();
  }, [recargar]);

  const setFiltro = useCallback((f: Filtro) => {
    // Solo sucursales que la persona puede ver: el filtro nunca amplía el alcance.
    const visibles = new Set((yo?.ubicaciones ?? []).map((u) => u.id));
    const limpio = { ...f, ubicaciones: f.ubicaciones.filter((u) => visibles.has(u)) };
    setFiltroEstado(limpio);
    try {
      localStorage.setItem(`retail_filtro_${yo?.usuario.id}_${yo?.empresa?.id ?? 0}`, JSON.stringify(limpio));
    } catch {
      /* sin almacenamiento local: el filtro vale hasta recargar */
    }
  }, [yo]);

  const valor = useMemo<Valor | null>(() => yo && {
    yo, recargar, filtro, setFiltro,
    puede: (p: string) => yo.permisos.includes(p),
  }, [yo, recargar, filtro, setFiltro]);

  if (error) {
    return <div className="mx-auto mt-20 max-w-md px-4 text-center"><p className="font-medium">No se pudo abrir Retail</p><p className="mt-1 text-sm text-suave">{error}</p></div>;
  }
  if (!valor) {
    return <div className="mt-24 text-center text-sm text-suave" aria-live="polite">Cargando…</div>;
  }
  return <Contexto.Provider value={valor}>{children}</Contexto.Provider>;
}
