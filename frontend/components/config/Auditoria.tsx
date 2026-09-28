"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaHora } from "@/lib/formato";
import { Aviso, Tabla, Tarjeta } from "@/components/ui";

type Registro = { id: number; created_at: string; usuario: string | null; accion: string; objeto: string; objeto_id: string | null; detalle: Record<string, unknown>; ip: string | null };
const ACCIONES: Record<string, string> = {
  ingreso: "Ingresó", ingreso_fallido: "Intento de ingreso fallido", ingreso_clave_ok: "Clave correcta (falta el código)",
  segundo_factor_fallido: "Código de segundo factor incorrecto", crear: "Creó", modificar: "Modificó", borrar: "Borró",
  guardar: "Guardó", activar: "Activó", desactivar: "Desactivó", cambio_clave: "Cambió su clave", blanquear_clave: "Generó una clave nueva",
  segundo_factor_activado: "Activó el segundo factor", segundo_factor_desactivado: "Desactivó el segundo factor",
  entrar_como_plataforma: "Entró como administración de la plataforma",
};

export function Auditoria() {
  const [lista, setLista] = useState<Registro[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api<Registro[]>("/auditoria").then(setLista).catch((e) => setError(e.message)); }, []);
  return (
    <Tarjeta titulo="Auditoría">
      <p className="mb-3 text-sm text-suave">Quién hizo qué y cuándo. Los últimos 200 movimientos.</p>
      {error && <Aviso tipo="error">{error}</Aviso>}
      <Tabla columnas={["Cuándo", "Quién", "Qué", "Detalle"]}>
        {lista?.map((r) => (
          <tr key={r.id}>
            <td className="whitespace-nowrap text-suave">{fechaHora(r.created_at)}</td>
            <td>{r.usuario ?? "—"}</td>
            <td>{ACCIONES[r.accion] ?? r.accion} {r.objeto !== "sesion" && <span className="text-suave">{r.objeto.replaceAll("_", " ")}{r.objeto_id ? ` #${r.objeto_id}` : ""}</span>}</td>
            <td className="max-w-80 truncate text-xs text-suave" title={JSON.stringify(r.detalle)}>{Object.keys(r.detalle ?? {}).length ? JSON.stringify(r.detalle) : ""}</td>
          </tr>
        ))}
      </Tabla>
    </Tarjeta>
  );
}
