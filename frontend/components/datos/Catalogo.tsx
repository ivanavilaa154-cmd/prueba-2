"use client";
// Cola del catálogo: líneas de listas de proveedor sin producto y productos con código de barras que el maestro no conoce.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fecha, numero, plata } from "@/lib/formato";
import { Aviso, Boton, Entrada, Etiqueta, Tabla, Tarjeta, Vacio } from "@/components/ui";

type Sugerencia = { producto_id: number; nombre: string; codigo: string; confianza: number };
type Linea = { id: number; codigo: string | null; descripcion: string | null; costo: string; vigencia_desde: string; proveedor: string; sugerencias: Sugerencia[] };
type SinMapear = { id: number; codigo_interno: string; nombre: string; ean: string; marca: string | null;
  sugerencias: { maestro_id: number; ean: string; nombre: string; confianza: number }[] };
type Pendientes = { productos_sin_mapear: SinMapear[]; lineas_sin_producto: Linea[] };
type Encontrado = { id: number; nombre: string; codigo_interno: string; ean: string | null };

function Buscador({ onElegir }: { onElegir: (id: number) => void }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<Encontrado[]>([]);
  useEffect(() => {
    if (q.trim().length < 2) {
      setRes([]);
      return;
    }
    const t = setTimeout(() => api<Encontrado[]>(`/catalogo/buscar?q=${encodeURIComponent(q)}`).then(setRes).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <div className="grid gap-1">
      <Entrada className="w-64" placeholder="Buscar otro producto…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar producto" />
      {res.length > 0 && (
        <ul className="max-h-40 w-64 overflow-auto rounded-lg border border-borde bg-panel text-sm">
          {res.map((p) => (
            <li key={p.id}><button className="w-full px-2 py-1 text-left hover:bg-panel-2" onClick={() => onElegir(p.id)}>{p.nombre} <span className="text-suave">· {p.codigo_interno}</span></button></li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Catalogo() {
  const [datos, setDatos] = useState<Pendientes | null>(null);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const cargar = useCallback(() => api<Pendientes>("/catalogo/pendientes").then(setDatos).catch((e) => setMensaje({ tipo: "error", texto: e.message })), []);
  useEffect(() => { cargar(); }, [cargar]);

  async function accion(f: () => Promise<unknown>, ok: string) {
    try {
      await f();
      setMensaje({ tipo: "ok", texto: ok });
      cargar();
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo guardar." });
    }
  }
  const emparejar = (linea: number, producto: number) =>
    accion(() => api(`/catalogo/lineas/${linea}`, { metodo: "POST", cuerpo: { producto_id: producto } }), "Emparejado. La próxima lista de ese proveedor lo reconoce sola.");
  const maestro = (producto: number, maestroId: number | null) =>
    accion(() => api(`/catalogo/productos/${producto}/maestro`, { metodo: "POST", cuerpo: { maestro_id: maestroId } }),
      maestroId ? "Vinculado al catálogo maestro." : "Queda como producto propio.");

  if (!datos) return <Tarjeta titulo="Catálogo"><p className="text-sm text-suave">Cargando…</p></Tarjeta>;
  return (
    <div className="grid grid-cols-1 gap-4">
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
      <Tarjeta titulo={`Listas de proveedores sin emparejar · ${numero(datos.lineas_sin_producto.length)}`}>
        <p className="mb-3 text-sm text-suave">Productos de la lista del proveedor que no pudimos asociar con seguridad. Elegí el tuyo: queda guardado para la próxima.</p>
        {datos.lineas_sin_producto.length === 0 ? <Vacio titulo="Todo emparejado" /> : (
          <Tabla columnas={["Proveedor", "En la lista", "Costo", "¿Cuál es?", ""]}>
            {datos.lineas_sin_producto.map((l) => (
              <tr key={l.id} className="align-top">
                <td>{l.proveedor}<div className="text-xs text-suave">desde {fecha(l.vigencia_desde)}</div></td>
                <td>{l.descripcion ?? "—"}<div className="text-xs text-suave">{l.codigo ?? "sin código"}</div></td>
                <td className="whitespace-nowrap">{plata(l.costo)}</td>
                <td>
                  <div className="grid gap-1">
                    {l.sugerencias.map((s) => (
                      <Boton key={s.producto_id} variante="secundario" className="justify-start text-left" onClick={() => emparejar(l.id, s.producto_id)}>
                        {s.nombre} <Etiqueta tono={s.confianza >= 0.7 ? "ok" : "gris"}>{numero(s.confianza * 100)} %</Etiqueta>
                      </Boton>
                    ))}
                    <Buscador onElegir={(id) => emparejar(l.id, id)} />
                  </div>
                </td>
                <td><button className="text-sm text-suave underline" onClick={() => accion(() => api(`/catalogo/lineas/${l.id}`, { metodo: "DELETE" }), "Descartado.")}>No lo vendo</button></td>
              </tr>
            ))}
          </Tabla>
        )}
      </Tarjeta>
      <Tarjeta titulo={`Productos sin vincular al catálogo maestro · ${numero(datos.productos_sin_mapear.length)}`}>
        <p className="mb-3 text-sm text-suave">Tienen código de barras que el catálogo maestro no conoce. Vincularlos permite comparar precios e inflación con el mercado.</p>
        {datos.productos_sin_mapear.length === 0 ? <Vacio titulo="Nada pendiente" /> : (
          <Tabla columnas={["Producto", "Código de barras", "Sugerencias del maestro", ""]}>
            {datos.productos_sin_mapear.map((p) => (
              <tr key={p.id} className="align-top">
                <td>{p.nombre}<div className="text-xs text-suave">{p.codigo_interno}</div></td>
                <td>{p.ean}</td>
                <td>
                  {p.sugerencias.length === 0 ? <span className="text-sm text-suave">Sin parecidos</span> : (
                    <div className="grid gap-1">
                      {p.sugerencias.map((s) => (
                        <Boton key={s.maestro_id} variante="secundario" className="justify-start text-left" onClick={() => maestro(p.id, s.maestro_id)}>
                          {s.nombre} <span className="text-xs text-suave">{s.ean}</span>
                        </Boton>
                      ))}
                    </div>
                  )}
                </td>
                <td><button className="text-sm text-suave underline" onClick={() => maestro(p.id, null)}>Es propio</button></td>
              </tr>
            ))}
          </Tabla>
        )}
      </Tarjeta>
    </div>
  );
}
