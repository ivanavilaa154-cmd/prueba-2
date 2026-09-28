"use client";
import { useCallback, useEffect, useState } from "react";
import { api, type Canal, type Plataforma } from "@/lib/api";
import { useSesion } from "@/components/Sesion";
import { Aviso, Etiqueta, Tarjeta } from "@/components/ui";

export function Canales() {
  const { puede, recargar } = useSesion();
  const [datos, setDatos] = useState<{ canales: Canal[]; plataformas: Plataforma[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const editable = puede("configurar_empresa");
  const cargar = useCallback(() => api<{ canales: Canal[]; plataformas: Plataforma[] }>("/canales").then(setDatos).catch((e) => setError(e.message)), []);
  useEffect(() => { void cargar(); }, [cargar]);

  async function alternar(c: Canal) {
    try {
      await api(`/canales/${c.id}`, { metodo: "PUT", cuerpo: { activo: !c.activo } });
      await cargar();
      await recargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo cambiar.");
    }
  }

  return (
    <Tarjeta titulo="Canales de venta">
      <p className="mb-3 text-sm text-suave">El canal está en todos los reportes y cálculos desde el primer día, aunque hoy vendas solo en el local.</p>
      {error && <div className="mb-3"><Aviso tipo="error">{error}</Aviso></div>}
      <ul className="grid gap-2 sm:grid-cols-2">
        {datos?.canales.map((c) => (
          <li key={c.id} className="flex items-center justify-between rounded-lg border border-borde p-3">
            <span className="font-medium">{c.nombre}</span>
            <span className="flex items-center gap-2">
              {c.activo ? <Etiqueta tono="ok">Activo</Etiqueta> : <Etiqueta>Inactivo</Etiqueta>}
              {editable && <button className="text-sm text-acento underline" onClick={() => alternar(c)}>{c.activo ? "Desactivar" : "Activar"}</button>}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-sm text-suave">
        Plataformas conectadas: {datos?.plataformas.length ? datos.plataformas.map((p) => p.nombre).join(", ") : "ninguna todavía"}.
        Odoo Punto de Venta se conecta en la parte 4; Tiendanube y Mercado Libre, en la fase 2.
      </p>
    </Tarjeta>
  );
}
