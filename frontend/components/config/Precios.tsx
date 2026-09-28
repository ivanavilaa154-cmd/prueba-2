"use client";
// Configuración de precios: margen objetivo por categoría y reglas de redondeo.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { numero, plata } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Entrada, Tabla, Tarjeta } from "@/components/ui";

type Cfg = { margenes: { id: number; categoria_id: number | null; categoria: string | null; producto: string | null; canal: string | null; margen: string }[];
  redondeo: { desde_precio: string; hasta_precio: string | null; multiplo: string; terminaciones: number[]; umbral_minimo_cambio: string }[];
  categorias: { id: number; nombre: string }[]; margen_defecto: string };

export function Precios() {
  const { puede } = useSesion();
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [margenes, setMargenes] = useState<Record<number, string>>({});
  const [reglas, setReglas] = useState<Cfg["redondeo"]>([]);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const editable = puede("remarcar");
  const cargar = useCallback(() => api<Cfg>("/config/precios").then((c) => {
    setCfg(c);
    setReglas(c.redondeo);
    setMargenes(Object.fromEntries(c.categorias.map((cat) => {
      const m = c.margenes.find((x) => x.categoria_id === cat.id && !x.canal);
      return [cat.id, m ? String(Math.round(Number(m.margen) * 1000) / 10) : ""];
    })));
  }), []);
  useEffect(() => { cargar(); }, [cargar]);

  async function guardarMargen(id: number) {
    try {
      await api("/config/margenes", { metodo: "PUT", cuerpo: { categoria_id: id, margen: margenes[id] } });
      setMensaje({ tipo: "ok", texto: "Margen guardado." });
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo guardar." });
    }
  }
  async function guardarReglas() {
    try {
      await api("/config/redondeo", { metodo: "PUT", cuerpo: { reglas } });
      setMensaje({ tipo: "ok", texto: "Reglas de redondeo guardadas." });
      cargar();
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo guardar." });
    }
  }
  if (!cfg) return <Tarjeta titulo="Precios"><p className="text-sm text-suave">Cargando…</p></Tarjeta>;
  return (
    <div className="grid gap-4">
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
      <Tarjeta titulo="Margen objetivo por categoría">
        <p className="mb-3 text-sm text-suave">Sobre el precio de venta. Sin margen cargado se usa {numero(Number(cfg.margen_defecto) * 100, 0)} %. También se puede cargar por producto o por canal.</p>
        <Tabla columnas={["Categoría", "Margen objetivo", ""]}>
          {cfg.categorias.map((c) => (
            <tr key={c.id}>
              <td>{c.nombre}</td>
              <td><span className="inline-flex items-center gap-1"><Entrada className="w-20 text-right" inputMode="decimal" disabled={!editable} value={margenes[c.id] ?? ""}
                onChange={(e) => setMargenes({ ...margenes, [c.id]: e.target.value })} /> %</span></td>
              <td className="text-right">{editable && <Boton variante="secundario" onClick={() => guardarMargen(c.id)}>Guardar</Boton>}</td>
            </tr>
          ))}
        </Tabla>
      </Tarjeta>
      <Tarjeta titulo="Redondeo de precios">
        <p className="mb-3 text-sm text-suave">Por tramo de precio: se redondea hacia arriba al múltiplo y, si hay terminaciones, a la primera que coincida (ej.: 0, 5, 9).</p>
        <Tabla columnas={["Desde", "Hasta", "Múltiplo", "Terminaciones", ""]}>
          {reglas.map((r, i) => (
            <tr key={i}>
              <td><Entrada className="w-24" disabled={!editable} value={r.desde_precio} onChange={(e) => setReglas(reglas.map((x, k) => (k === i ? { ...x, desde_precio: e.target.value } : x)))} /></td>
              <td><Entrada className="w-24" disabled={!editable} placeholder="sin tope" value={r.hasta_precio ?? ""} onChange={(e) => setReglas(reglas.map((x, k) => (k === i ? { ...x, hasta_precio: e.target.value || null } : x)))} /></td>
              <td><Entrada className="w-20" disabled={!editable} value={r.multiplo} onChange={(e) => setReglas(reglas.map((x, k) => (k === i ? { ...x, multiplo: e.target.value } : x)))} /></td>
              <td><Entrada className="w-28" disabled={!editable} value={r.terminaciones.join(", ")} onChange={(e) => setReglas(reglas.map((x, k) => (k === i ? { ...x, terminaciones: e.target.value.split(",").map((t) => parseInt(t.trim())).filter((t) => !isNaN(t)) } : x)))} /></td>
              <td>{editable && <button className="text-sm text-peligro underline" onClick={() => setReglas(reglas.filter((_, k) => k !== i))}>Quitar</button>}</td>
            </tr>
          ))}
        </Tabla>
        {editable && (
          <div className="mt-3 flex gap-2">
            <Boton variante="secundario" onClick={() => setReglas([...reglas, { desde_precio: "0", hasta_precio: null, multiplo: "10", terminaciones: [], umbral_minimo_cambio: "0.01" }])}>Agregar tramo</Boton>
            <Boton onClick={guardarReglas}>Guardar reglas</Boton>
          </div>
        )}
        <p className="mt-2 text-xs text-suave">Ejemplo con el primer tramo: {plata(1234)} → {reglas[0] ? `se redondea a múltiplos de ${reglas[0].multiplo}` : "sin reglas"}.</p>
      </Tarjeta>
    </div>
  );
}
