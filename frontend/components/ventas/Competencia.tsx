"use client";
// (16) Precios de la competencia: relevamientos cargados a mano o con archivo, precio probable de hoy (con inflación) y qué hacer.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaCorta, numero, plata } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, ComoSeCalcula, Tabla, Tarjeta, Vacio } from "@/components/ui";

type Comp = { id: number; competidor: string; precio: number; fecha: string; estimado_hoy: number };
type P = { producto_id: number; producto: string; codigo: string; propio: number | null; competidores: Comp[]; mas_barato: string; precio_mas_barato_hoy: number;
  diferencia: number | null; elasticidad: number | null; unidades_30d_si_igualas: number | null; sugerencia: string };
type R = { productos: P[]; relevados: number; mas_caros: number; competidores: string[]; inflacion_mensual: number };

export function Competencia() {
  const { puede } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const cargar = () => api<R>("/competencia").then(setR).catch((e) => setMensaje({ tipo: "error", texto: e.message }));
  useEffect(() => { cargar(); }, []);
  async function subir(e: React.ChangeEvent<HTMLInputElement>) {
    const archivo = e.target.files?.[0];
    if (!archivo) return;
    const form = new FormData();
    form.append("archivo", archivo);
    try {
      const res = await api<{ cargados: number; errores: { fila: number; error: string }[] }>("/competencia/archivo", { metodo: "POST", formulario: form });
      setMensaje({ tipo: res.errores.length ? "error" : "ok", texto: `Se cargaron ${res.cargados} precios.` + (res.errores.length ? ` Filas con error: ${res.errores.map((x) => `${x.fila} (${x.error})`).join(", ")}.` : "") });
      cargar();
    } catch (err) { setMensaje({ tipo: "error", texto: err instanceof Error ? err.message : "No se pudo cargar." }); }
    e.target.value = "";
  }
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  return (
    <div className="grid grid-cols-1 gap-4">
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
      <Tarjeta titulo="Cargar relevamiento" accion={puede("remarcar") ? (
        <label className="inline-flex min-h-9 cursor-pointer items-center rounded-lg bg-acento px-3.5 text-sm font-medium text-acento-texto">
          Subir archivo<input type="file" accept=".csv,.txt" className="sr-only" onChange={subir} /></label>) : null}>
        <p className="text-sm text-suave">Un CSV con las columnas <strong>codigo</strong> (EAN o código interno), <strong>competidor</strong>, <strong>precio</strong> y <strong>fecha</strong>.
          Sirve una planilla de Excel guardada como CSV. Los precios de más de 90 días no se usan.</p>
      </Tarjeta>
      {!r.productos.length ? <Vacio titulo="Todavía no hay precios de la competencia">Subí un relevamiento para comparar.</Vacio> : (
        <Tarjeta titulo={`${r.relevados} productos relevados · sos más caro en ${r.mas_caros}`}>
          <Tabla columnas={["Producto", "Tu precio", "Más barato hoy (estimado)", "Diferencia", "Si igualás: unidades en 30 días", "Qué hacer"]}>
            {r.productos.map((p) => (
              <tr key={p.producto_id}>
                <td><span className="font-medium">{p.producto}</span><br />
                  <span className="text-xs text-suave">{p.competidores.map((c) => `${c.competidor}: ${plata(c.precio)} el ${fechaCorta(c.fecha)}`).join(" · ")}</span></td>
                <td className="whitespace-nowrap text-right">{plata(p.propio)}</td>
                <td className="whitespace-nowrap text-right">{plata(p.precio_mas_barato_hoy)}<br /><span className="text-xs text-suave">{p.mas_barato}</span></td>
                <td className={`whitespace-nowrap text-right font-semibold ${(p.diferencia ?? 0) > 0.05 ? "text-peligro" : ""}`}>
                  {p.diferencia === null ? "—" : `${p.diferencia > 0 ? "▲ +" : p.diferencia < 0 ? "▼ " : ""}${numero(p.diferencia * 100, 1)} %`}</td>
                <td className="text-right">{p.unidades_30d_si_igualas === null ? "—" : `+${numero(p.unidades_30d_si_igualas)}`}</td>
                <td className="text-sm">{p.sugerencia}</td>
              </tr>
            ))}
          </Tabla>
        </Tarjeta>
      )}
      <ComoSeCalcula>
        <p>Precio de hoy del competidor: su último precio relevado × (1 + inflación mensual de {numero(r.inflacion_mensual * 100, 1)} %) por cada mes que pasó desde el relevamiento.</p>
        <p>Unidades si igualás: venta diaria pronosticada × 30 × ((precio del competidor ÷ el tuyo) elevado a la sensibilidad al precio del producto − 1).
          Solo es una sugerencia: los precios se cambian en Precios.</p>
      </ComoSeCalcula>
    </div>
  );
}
