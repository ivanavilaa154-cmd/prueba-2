"use client";
// Plan y suscripción de la empresa (13.6): qué incluye, cuánto falta para vencer, sucursales usadas y pagos registrados.
import { useEffect, useState } from "react";
import { api, type Suscripcion } from "@/lib/api";
import { fecha, plata } from "@/lib/formato";
import { Aviso, Etiqueta, Tabla, Tarjeta } from "@/components/ui";

type PlanFila = { codigo: string; nombre: string; max_sucursales: number | null; modulos: string[]; precio_mensual: string | null };
type Datos = { estado: Suscripcion; planes: PlanFila[]; modulos: Record<string, string>;
  pagos: { fecha: string; plan: string; monto: string; medio: string; cubre_hasta: string; nota: string | null }[] };

export function Plan() {
  const [d, setD] = useState<Datos | null>(null);
  useEffect(() => { api<Datos>("/suscripcion").then(setD).catch(() => {}); }, []);
  if (!d) return <p className="text-sm text-suave">Cargando…</p>;
  const e = d.estado;
  return (
    <div className="grid grid-cols-1 gap-4">
      <Tarjeta titulo={`Tu plan: ${e.plan_nombre}`}>
        {e.al_dia ? (
          <Aviso tipo={e.por_vencer ? "alerta" : "ok"}>
            {e.en_prueba ? "Período de prueba" : "Suscripción al día"} hasta el {fecha(e.hasta)} ({e.dias_restantes} día{e.dias_restantes === 1 ? "" : "s"}).
          </Aviso>
        ) : <Aviso tipo="error">La suscripción venció el {fecha(e.hasta)}: la cuenta está en solo lectura. Tus datos están intactos; al registrarse el pago vuelve a funcionar todo.</Aviso>}
        <div className="mt-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
          <p><span className="text-suave">Sucursales:</span> {e.sucursales} de {e.max_sucursales ?? "sin límite"}</p>
          <p><span className="text-suave">Incluye:</span> {e.modulos.map((m) => d.modulos[m]).join(", ")}</p>
          <p><span className="text-suave">Precio:</span> {e.precio_mensual ? `${plata(e.precio_mensual)} por mes` : "a definir"}</p>
        </div>
        <p className="mt-3 text-sm text-suave">Para pagar o cambiar de plan, contactá a la administración de la plataforma: registra el pago (transferencia o Mercado Pago) y la cuenta queda al día al instante.</p>
      </Tarjeta>
      <Tarjeta titulo="Planes">
        <Tabla columnas={["Plan", "Sucursales", "Incluye", "Precio por mes"]}>
          {d.planes.filter((p) => p.codigo !== "prueba").map((p) => (
            <tr key={p.codigo}>
              <td>{p.nombre} {p.codigo === e.plan && <Etiqueta tono="acento">tu plan</Etiqueta>}</td>
              <td>{p.max_sucursales ?? "Sin límite"}</td>
              <td>{p.modulos.map((m) => d.modulos[m]).join(" + ")}</td>
              <td className="text-right">{p.precio_mensual ? plata(p.precio_mensual) : "A definir"}</td>
            </tr>
          ))}
        </Tabla>
        <p className="mt-2 text-xs text-suave">Operación diaria: comprar y reponer, transferencias y OC, precios, ventas, caja, avisos y datos. Gestión avanzada: plata parada,
          vencimientos, sucursales, proveedores, canales, copiloto, metas e impacto. Análisis avanzado: canasta, promociones, sensibilidad al precio, surtido y clientes.</p>
      </Tarjeta>
      {d.pagos.length > 0 && (
        <Tarjeta titulo="Pagos registrados">
          <Tabla columnas={["Fecha", "Plan", "Monto", "Medio", "Cubre hasta"]}>
            {d.pagos.map((p, i) => <tr key={i}><td>{fecha(p.fecha)}</td><td>{p.plan}</td><td className="text-right">{plata(p.monto)}</td><td>{p.medio.replace("_", " ")}</td><td>{fecha(p.cubre_hasta)}</td></tr>)}
          </Tabla>
        </Tarjeta>
      )}
    </div>
  );
}
