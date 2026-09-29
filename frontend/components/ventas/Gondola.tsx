"use client";
// (24) Rendimiento por metro de góndola: ganancia (o venta) por metro por semana contra la mediana de su categoría, y cambios de frentes sugeridos.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { numero, plata } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, ComoSeCalcula, Etiqueta, Selector, Tabla, Tarjeta, Vacio } from "@/components/ui";

type F = { producto_id: number; nombre: string; categoria: string; frentes: number; metros: number; venta_semana: number; ganancia_semana: number;
  por_metro: number; indice: number | null; estado: string; dias_stock: number | null };
type R = { sucursales: { id: number; nombre: string; productos: number }[]; ubicacion?: { id: number; nombre: string }; medida: string; productos: F[];
  movimientos: { categoria: string; sacar_de: string; dar_a: string; metros: number; efecto_semana: number }[]; metros_totales: number };
const ESTADO: Record<string, [string, "ok" | "alerta" | "peligro" | "gris"]> = {
  rinde_poco: ["▼ Rinde poco", "peligro"], le_falta_espacio: ["▲ Le falta espacio", "alerta"], normal: ["Normal", "gris"],
};

export function Gondola() {
  const { puede } = useSesion();
  const [ubic, setUbic] = useState<number | null>(null);
  const [r, setR] = useState<R | null>(null);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const cargar = () => api<R>(`/gondola${ubic ? `?ubicacion_id=${ubic}` : ""}`).then(setR).catch((e) => setMensaje({ tipo: "error", texto: e.message }));
  useEffect(() => { cargar(); }, [ubic]); // eslint-disable-line react-hooks/exhaustive-deps
  async function subir(e: React.ChangeEvent<HTMLInputElement>) {
    const archivo = e.target.files?.[0];
    if (!archivo) return;
    const form = new FormData();
    form.append("archivo", archivo);
    try {
      const res = await api<{ cargados: number; errores: { fila: number; error: string }[] }>("/gondola/archivo", { metodo: "POST", formulario: form });
      setMensaje({ tipo: res.errores.length ? "error" : "ok", texto: `Se cargaron ${res.cargados} productos.` + (res.errores.length ? ` Filas con error: ${res.errores.map((x) => `${x.fila} (${x.error})`).join(", ")}.` : "") });
      cargar();
    } catch (err) { setMensaje({ tipo: "error", texto: err instanceof Error ? err.message : "No se pudo cargar." }); }
    e.target.value = "";
  }
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const medida = r.medida === "ganancia" ? "Ganancia" : "Venta";
  return (
    <div className="grid grid-cols-1 gap-4">
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
      <Tarjeta titulo="Espacio en góndola" accion={puede("recuentos") ? (
        <label className="inline-flex min-h-9 cursor-pointer items-center rounded-lg bg-acento px-3.5 text-sm font-medium text-acento-texto">
          Subir archivo<input type="file" accept=".csv,.txt" className="sr-only" onChange={subir} /></label>) : null}>
        <p className="text-sm text-suave">Un CSV con <strong>codigo</strong>, <strong>sucursal</strong>, <strong>frentes</strong> y <strong>metros</strong> (lineales) de cada producto.</p>
        {r.sucursales.length > 1 && (
          <div className="mt-2"><Selector aria-label="Sucursal" value={r.ubicacion?.id ?? ""} onChange={(e) => setUbic(Number(e.target.value))}>
            {r.sucursales.map((s) => <option key={s.id} value={s.id}>{s.nombre} · {s.productos} productos cargados</option>)}
          </Selector></div>
        )}
      </Tarjeta>
      {!r.productos.length ? <Vacio titulo="Sin espacio cargado en esta sucursal">Subí el archivo con los frentes y metros.</Vacio> : <>
        {r.movimientos.length > 0 && (
          <Tarjeta titulo="Cambios de frentes sugeridos">
            <Tabla columnas={["Categoría", "Sacar un frente de", "Dárselo a", "Metros", `${medida} extra por semana`]}>
              {r.movimientos.map((m, i) => <tr key={i}><td>{m.categoria}</td><td>{m.sacar_de}</td><td>{m.dar_a}</td><td className="text-right">{numero(m.metros, 2)}</td>
                <td className="whitespace-nowrap text-right font-semibold">{plata(m.efecto_semana)}</td></tr>)}
            </Tabla>
          </Tarjeta>
        )}
        <Tarjeta titulo={`${numero(r.metros_totales, 1)} metros cargados en ${r.ubicacion?.nombre ?? ""}`}>
          <Tabla columnas={["Producto", "Frentes", "Metros", `${medida} por semana`, "Por metro", "Contra su categoría", "Estado"]}>
            {r.productos.map((f) => (
              <tr key={f.producto_id}>
                <td><span className="font-medium">{f.nombre}</span><br /><span className="text-xs text-suave">{f.categoria}</span></td>
                <td className="text-right">{f.frentes}</td><td className="text-right">{numero(f.metros, 2)}</td>
                <td className="whitespace-nowrap text-right">{plata(r.medida === "ganancia" ? f.ganancia_semana : f.venta_semana)}</td>
                <td className="whitespace-nowrap text-right font-semibold">{plata(f.por_metro)}</td>
                <td className="text-right">{f.indice === null ? "—" : `${numero(f.indice * 100)} %`}</td>
                <td><Etiqueta tono={ESTADO[f.estado][1]}>{ESTADO[f.estado][0]}</Etiqueta></td>
              </tr>
            ))}
          </Tabla>
        </Tarjeta>
      </>}
      <ComoSeCalcula>
        <p>{medida} de las últimas 4 semanas ÷ 4 ÷ metros lineales. «Contra su categoría»: comparado con la mediana de los productos de la misma categoría en la sucursal.</p>
        <p>Rinde poco: menos de la mitad de su categoría y más de un frente. Le falta espacio: más de 1,5 veces su categoría.
          El efecto de mover un frente usa una elasticidad venta-espacio de 0,2 (un 10 % más de espacio vende un 2 % más).</p>
      </ComoSeCalcula>
    </div>
  );
}
