"use client";
// Multisucursal (sección 8): comparativos, matriz producto × sucursal, el mismo producto en cada sucursal, precios distintos y ajustes.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { parametrosFiltro } from "@/lib/consulta";
import { fechaCorta, fechaHora, numero, plata } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Semaforo } from "@/components/Semaforo";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, ComoSeCalcula, Entrada, Tabla, Tarjeta, Vacio, cx } from "@/components/ui";

type Suc = { ubicacion_id: number; ubicacion: string; ventas: string; ganancia: string | null; margen: number | null; tickets: number; ticket_promedio: string | null;
  plata_parada: string | null; merma: string; productos_en_rojo: number; productos_sin_stock: number; diferencias_inventario: string; productos_contados: number;
  perdida_pct: number; promedio_otras_pct: number; sospechoso: boolean };
type Comparativo = { periodo: { etiqueta: string; desde: string; hasta: string }; sucursales: Suc[]; ver_costos: boolean };
type Celda = { disponible: string; dias_stock: string | null; semaforo: string | null; vence: string | null };
type Matriz = { ubicaciones: { id: number; nombre: string; tipo: string }[]; total: number;
  productos: { producto_id: number; nombre: string; codigo_interno: string; categoria: string | null; celdas: Record<string, Celda>; venta_diaria: string; en_transito: string; rojos: number }[] };
type PorSucursal = { producto: { nombre: string; codigo_interno: string }; sucursales: { ubicacion: string; unidades_30d: string | null; facturacion_30d: string | null;
  puesto: number | null; de: number | null; vpd: string | null; disponible: string | null; dias_stock: string | null; semaforo: string | null; precio: string | null; vs_mejor: number | null }[] };
type Distinto = { producto_id: number; nombre: string; codigo_interno: string; ubicacion: string; precio_sucursal: string; precio_general: string; diferencia: number; desde: string };
type Ajuste = { id: number; fecha: string; tipo: string; cantidad: string; motivo: string | null; producto: string; ubicacion: string; usuario: string; monto: string };

const PESTANAS = [["comparar", "Comparar sucursales"], ["matriz", "Matriz de stock"], ["precios", "Precios distintos"], ["ajustes", "Ajustes de stock"]] as const;
const TIPO_AJUSTE: Record<string, string> = { ajuste: "Ajuste por recuento", merma: "Merma", vencimiento: "Vencido" };

function Comparar() {
  const { filtro } = useSesion();
  const [r, setR] = useState<Comparativo | null>(null);
  useEffect(() => { setR(null); api<Comparativo>(`/sucursales/comparativo?${parametrosFiltro(filtro)}`).then(setR).catch(() => {}); }, [filtro]);
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const mejor = (k: keyof Suc, menor = false) => {
    const vals = r.sucursales.map((s) => Number(s[k] ?? 0));
    return menor ? Math.min(...vals) : Math.max(...vals);
  };
  const filas: { titulo: string; k: keyof Suc; fmt: (s: Suc) => string; menor?: boolean; costos?: boolean }[] = [
    { titulo: "Ventas", k: "ventas", fmt: (s) => plata(s.ventas) },
    { titulo: "Ganancia", k: "ganancia", fmt: (s) => plata(s.ganancia), costos: true },
    { titulo: "Margen", k: "margen", fmt: (s) => (s.margen === null ? "—" : `${numero(s.margen * 100, 1)} %`), costos: true },
    { titulo: "Tickets", k: "tickets", fmt: (s) => numero(s.tickets) },
    { titulo: "Ticket promedio", k: "ticket_promedio", fmt: (s) => plata(s.ticket_promedio) },
    { titulo: "Plata parada", k: "plata_parada", fmt: (s) => plata(s.plata_parada), menor: true, costos: true },
    { titulo: "Merma", k: "merma", fmt: (s) => plata(s.merma), menor: true },
    { titulo: "Diferencias de inventario", k: "diferencias_inventario", fmt: (s) => plata(s.diferencias_inventario), menor: true },
    { titulo: "Productos por agotarse", k: "productos_en_rojo", fmt: (s) => numero(s.productos_en_rojo), menor: true },
    { titulo: "Productos sin stock", k: "productos_sin_stock", fmt: (s) => numero(s.productos_sin_stock), menor: true },
  ];
  const sospechosas = r.sucursales.filter((s) => s.sospechoso);
  return (
    <div className="grid grid-cols-1 gap-4">
      {sospechosas.map((s) => (
        <Aviso key={s.ubicacion_id} tipo="error">
          ▲ <strong>{s.ubicacion}</strong>: merma y diferencias de inventario por {numero(s.perdida_pct * 100, 1)} % de lo vendido, contra {numero(s.promedio_otras_pct * 100, 1)} % en las demás sucursales. Revisá recuentos, recepciones y el control de caja.
        </Aviso>
      ))}
      <Tarjeta titulo={`Sucursales · ${r.periodo.etiqueta}`}>
        <Tabla columnas={["", ...r.sucursales.map((s) => s.ubicacion)]}>
          {filas.filter((f) => !f.costos || r.ver_costos).map((f) => {
            const m = mejor(f.k, f.menor);
            return (
              <tr key={f.titulo}>
                <td className="text-suave">{f.titulo}</td>
                {r.sucursales.map((s) => {
                  const destacado = r.sucursales.length > 1 && Number(s[f.k] ?? 0) === m;
                  return <td key={s.ubicacion_id} className={cx("whitespace-nowrap text-right", destacado && "font-semibold")}>{f.fmt(s)}{destacado && <span className="ml-1 text-ok" aria-label="mejor">✓</span>}</td>;
                })}
              </tr>
            );
          })}
        </Tabla>
        <div className="mt-3">
          <ComoSeCalcula>
            <p>✓ marca la mejor sucursal en cada fila (mayor en ventas y margen; menor en merma, faltantes y plata parada).</p>
            <p>Faltantes sospechosos: merma + diferencias de inventario, en % de lo vendido, 1,5 veces o más que el promedio de las demás sucursales.</p>
          </ComoSeCalcula>
        </div>
      </Tarjeta>
    </div>
  );
}

function ProductoEnSucursales({ id, cerrar }: { id: number; cerrar: () => void }) {
  const [r, setR] = useState<PorSucursal | null>(null);
  useEffect(() => { api<PorSucursal>(`/sucursales/producto/${id}`).then(setR).catch(() => {}); }, [id]);
  return (
    <Tarjeta titulo={r ? `${r.producto.nombre} en cada sucursal` : "Cargando…"} accion={<button className="text-sm text-acento underline" onClick={cerrar}>Cerrar</button>}>
      {r && (
        <Tabla columnas={["Sucursal", "Venta diaria", "Frente a la mejor", "Ranking 30 días", "Precio", "Stock", "Estado"]}>
          {r.sucursales.map((s) => (
            <tr key={s.ubicacion}>
              <td>{s.ubicacion}</td>
              <td className="text-right">{numero(s.vpd ?? 0, 1)}</td>
              <td className="min-w-[8rem]">
                <div className="flex items-center gap-2">
                  <div className="h-2 flex-1 rounded bg-panel-2"><div className="h-2 rounded" style={{ width: `${(s.vs_mejor ?? 0) * 100}%`, background: "var(--serie-1)" }} /></div>
                  <span className="text-xs">{numero((s.vs_mejor ?? 0) * 100)} %</span>
                </div>
              </td>
              <td className="text-right">{s.puesto ? `${s.puesto}.º de ${s.de}` : "sin ventas"}</td>
              <td className="text-right">{plata(s.precio)}</td>
              <td className="text-right">{numero(s.disponible ?? 0)}</td>
              <td><Semaforo valor={s.semaforo} /></td>
            </tr>
          ))}
        </Tabla>
      )}
    </Tarjeta>
  );
}

function MatrizStock() {
  const [q, setQ] = useState("");
  const [soloProblemas, setSoloProblemas] = useState(false);
  const [r, setR] = useState<Matriz | null>(null);
  const [elegido, setElegido] = useState<number | null>(null);
  useEffect(() => {
    const t = setTimeout(() => api<Matriz>(`/sucursales/matriz?solo_problemas=${soloProblemas}${q.trim() ? `&q=${encodeURIComponent(q.trim())}` : ""}`).then(setR).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [q, soloProblemas]);
  return (
    <div className="grid grid-cols-1 gap-4">
      {elegido && <ProductoEnSucursales id={elegido} cerrar={() => setElegido(null)} />}
      <Tarjeta titulo="Producto × sucursal" accion={
        <div className="flex flex-wrap items-center gap-3">
          <Entrada className="w-56" placeholder="Buscar producto…" value={q} onChange={(e) => setQ(e.target.value)} />
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={soloProblemas} onChange={(e) => setSoloProblemas(e.target.checked)} /> Solo los que se agotan</label>
        </div>}>
        {!r ? <p className="text-sm text-suave">Cargando…</p> : r.productos.length === 0 ? <Vacio titulo="Nada para mostrar" /> : (
          <>
            <Tabla columnas={["Producto", ...r.ubicaciones.map((u) => u.nombre), "En tránsito"]}>
              {r.productos.map((p) => (
                <tr key={p.producto_id}>
                  <td className="min-w-[12rem]"><button className="text-left hover:underline" onClick={() => setElegido(p.producto_id)}>{p.nombre}</button>
                    <span className="block text-xs text-suave">{p.codigo_interno} · {numero(p.venta_diaria, 1)} u/día en total</span></td>
                  {r.ubicaciones.map((u) => {
                    const c = p.celdas[String(u.id)];
                    if (!c) return <td key={u.id} className="text-center text-suave">—</td>;
                    return (
                      <td key={u.id} className="whitespace-nowrap text-sm">
                        {u.tipo === "deposito" ? <span>{numero(c.disponible)} u</span> : <Semaforo valor={c.semaforo} corto />}
                        {u.tipo !== "deposito" && <span className="ml-1">{c.dias_stock ? `${numero(Math.min(Number(c.dias_stock), 999))} d` : "—"}</span>}
                        {(u.tipo !== "deposito" || c.vence) && <span className="block text-xs text-suave">{u.tipo !== "deposito" ? `${numero(c.disponible)} u` : ""}{c.vence ? `${u.tipo !== "deposito" ? " · " : ""}vence ${fechaCorta(c.vence).slice(0, 5)}` : ""}</span>}
                      </td>
                    );
                  })}
                  <td className="text-right">{Number(p.en_transito) ? numero(p.en_transito) : "—"}</td>
                </tr>
              ))}
            </Tabla>
            <p className="mt-2 text-xs text-suave">{r.productos.length} de {r.total} productos, los más vendidos primero. Tocá un producto para compararlo entre sucursales.</p>
          </>
        )}
      </Tarjeta>
    </div>
  );
}

function PreciosDistintos() {
  const [r, setR] = useState<{ umbral: string; productos: Distinto[] } | null>(null);
  useEffect(() => { api<typeof r>("/sucursales/precios-distintos").then(setR).catch(() => {}); }, []);
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  return (
    <Tarjeta titulo="El mismo producto con precios distintos entre sucursales">
      <p className="mb-3 text-sm text-suave">Precios propios de una sucursal que se apartan más de {numero(Number(r.umbral) * 100)} % del precio general.</p>
      {r.productos.length === 0 ? <Vacio titulo="Todas las sucursales tienen el mismo precio" /> : (
        <Tabla columnas={["Producto", "Sucursal", "Precio general", "En la sucursal", "Diferencia", "Desde"]}>
          {r.productos.map((p) => (
            <tr key={`${p.producto_id}-${p.ubicacion}`}>
              <td>{p.nombre}<span className="block text-xs text-suave">{p.codigo_interno}</span></td>
              <td>{p.ubicacion}</td>
              <td className="text-right">{plata(p.precio_general)}</td>
              <td className="text-right">{plata(p.precio_sucursal)}</td>
              <td className="text-right">{p.diferencia > 0 ? "▲ +" : "▼ "}{numero(p.diferencia * 100, 1)} %</td>
              <td>{fechaCorta(p.desde)}</td>
            </tr>
          ))}
        </Tabla>
      )}
    </Tarjeta>
  );
}

function Ajustes() {
  const { filtro } = useSesion();
  const [r, setR] = useState<Ajuste[] | null>(null);
  useEffect(() => {
    api<Ajuste[]>(`/sucursales/ajustes?dias=30${filtro.ubicaciones.length ? `&ubicaciones=${filtro.ubicaciones.join(",")}` : ""}`).then(setR).catch(() => {});
  }, [filtro]);
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  return (
    <Tarjeta titulo="Ajustes de stock de los últimos 30 días">
      <TablaDatos filas={r} idFila={(a) => String(a.id)} nombreArchivo="ajustes-de-stock" vacio={<Vacio titulo="No hubo ajustes" />}
        columnas={[
          { id: "fecha", titulo: "Cuándo", valor: (a) => a.fecha, render: (a) => <span className="whitespace-nowrap">{fechaHora(a.fecha)}</span> },
          { id: "suc", titulo: "Sucursal", valor: (a) => a.ubicacion },
          { id: "prod", titulo: "Producto", valor: (a) => a.producto },
          { id: "tipo", titulo: "Tipo", valor: (a) => TIPO_AJUSTE[a.tipo] ?? a.tipo },
          { id: "cant", titulo: "Cantidad", valor: (a) => Number(a.cantidad), render: (a) => `${Number(a.cantidad) > 0 ? "+" : ""}${numero(a.cantidad)}`, derecha: true },
          { id: "monto", titulo: "A costo", valor: (a) => Number(a.monto), render: (a) => plata(a.monto), derecha: true },
          { id: "quien", titulo: "Quién", valor: (a) => a.usuario },
          { id: "motivo", titulo: "Motivo", valor: (a) => a.motivo ?? "", ocultarEnCelular: true },
        ]} />
    </Tarjeta>
  );
}

export default function Sucursales() {
  const [activa, setActiva] = useState<string>("comparar");
  useEffect(() => {
    const leer = () => { const id = location.hash.replace("#", ""); if (PESTANAS.some(([p]) => p === id)) setActiva(id); };
    leer();
    window.addEventListener("hashchange", leer);
    return () => window.removeEventListener("hashchange", leer);
  }, []);
  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Sucursales</h1>
        <p className="text-sm text-suave">Cómo le va a cada sucursal, dónde está cada producto y qué se aparta de lo normal.</p>
      </div>
      <div role="tablist" aria-label="Sucursales" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1">
        {PESTANAS.map(([id, nombre]) => (
          <a key={id} role="tab" aria-selected={id === activa} href={`#${id}`}
            className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm", id === activa ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>{nombre}</a>
        ))}
      </div>
      {activa === "comparar" && <Comparar />}
      {activa === "matriz" && <MatrizStock />}
      {activa === "precios" && <PreciosDistintos />}
      {activa === "ajustes" && <Ajustes />}
    </div>
  );
}
