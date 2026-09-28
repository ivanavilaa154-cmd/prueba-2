"use client";
import { useEffect, useState } from "react";
import { useSesion } from "@/components/Sesion";
import { cx } from "@/components/ui";
import { Auditoria } from "@/components/config/Auditoria";
import { Canales } from "@/components/config/Canales";
import { Cuenta } from "@/components/config/Cuenta";
import { Empresa } from "@/components/config/Empresa";
import { Limites } from "@/components/config/Limites";
import { MediosPago } from "@/components/config/MediosPago";
import { Precios } from "@/components/config/Precios";
import { Sucursales } from "@/components/config/Sucursales";
import { Usuarios } from "@/components/config/Usuarios";

const PESTANAS = [
  { id: "empresa", nombre: "Empresa", permiso: null, componente: Empresa },
  { id: "sucursales", nombre: "Sucursales", permiso: null, componente: Sucursales },
  { id: "canales", nombre: "Canales", permiso: null, componente: Canales },
  { id: "usuarios", nombre: "Usuarios", permiso: "gestionar_usuarios", componente: Usuarios },
  { id: "limites", nombre: "Límites de aprobación", permiso: "gestionar_usuarios", componente: Limites },
  { id: "precios", nombre: "Precios", permiso: "ver_costos", componente: Precios },
  { id: "medios", nombre: "Medios de pago", permiso: "ver_ventas", componente: MediosPago },
  { id: "auditoria", nombre: "Auditoría", permiso: "ver_auditoria", componente: Auditoria },
  { id: "cuenta", nombre: "Mi cuenta", permiso: null, componente: Cuenta },
] as const;

export default function Configuracion() {
  const { puede, yo } = useSesion();
  const distribuidor = yo.usuario.rol === "distribuidor";   // solo su cuenta
  const visibles = PESTANAS.filter((p) => (distribuidor ? p.id === "cuenta" : !p.permiso || puede(p.permiso)));
  const [activa, setActiva] = useState<string>(distribuidor ? "cuenta" : "empresa");

  useEffect(() => {
    const leer = () => {
      const id = location.hash.replace("#", "");
      if (visibles.some((p) => p.id === id)) setActiva(id);
    };
    leer();
    window.addEventListener("hashchange", leer);
    return () => window.removeEventListener("hashchange", leer);
  }, [visibles]);

  const Actual = (visibles.find((p) => p.id === activa) ?? visibles[0]).componente;
  return (
    <div className="grid gap-4">
      <h1 className="text-2xl font-semibold">Configuración</h1>
      <div role="tablist" aria-label="Secciones de configuración" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1">
        {visibles.map((p) => (
          <a key={p.id} role="tab" aria-selected={p.id === activa} href={`#${p.id}`}
            className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm", p.id === activa ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>
            {p.nombre}
          </a>
        ))}
      </div>
      <Actual />
    </div>
  );
}
