"use client";
// Unidades, impuestos y descuentos de proveedor (SPEC v2, sección 4): con esto el margen se calcula con el costo de reposición
// y sin impuestos recuperables, y las compras en bultos o cajas entran en unidades exactas.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fecha, numero } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Campo, ComoSeCalcula, Entrada, Selector, Tabla, Tarjeta } from "@/components/ui";

type Regla = { id: number; iva: string; impuestos_internos: string; nombre: string; nivel: string };
type Conv = { id: number; producto: string; base: string; unidad: string; factor: string; proveedor: string | null };
type Desc = { id: number; proveedor: string; producto: string | null; categoria: string | null; tipo: string; porcentaje: string | null;
  compra_unidades: number | null; bonifica_unidades: number | null; desde_cantidad: string; vigente_desde: string; vigente_hasta: string | null; descripcion: string | null };
type R = { costos_con_iva: boolean; reglas: Regla[]; categorias: { id: number; nombre: string }[]; conversiones: Conv[]; descuentos: Desc[];
  proveedores: { id: number; razon_social: string }[] };
const IVAS = [["0.21", "21 %"], ["0.105", "10,5 %"], ["0.27", "27 %"], ["0.025", "2,5 %"], ["0", "Exento"]];
const pct = (x: string | number | null) => (x === null ? "—" : `${numero(Number(x) * 100, 1)} %`);

function BuscarProducto({ alElegir }: { alElegir: (p: { id: number; nombre: string }) => void }) {
  const [q, setQ] = useState("");
  const [lista, setLista] = useState<{ id: number; nombre: string; codigo_interno: string }[]>([]);
  useEffect(() => {
    if (q.trim().length < 2) { setLista([]); return; }
    const t = setTimeout(() => api<typeof lista>(`/catalogo/buscar?q=${encodeURIComponent(q)}`).then(setLista).catch(() => setLista([])), 250);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <div className="relative">
      <Entrada placeholder="Buscar producto por nombre o código" value={q} onChange={(e) => setQ(e.target.value)} />
      {lista.length > 0 && (
        <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-auto rounded-lg border border-borde bg-panel shadow">
          {lista.map((p) => <li key={p.id}><button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-panel-2"
            onClick={() => { alElegir(p); setQ(p.nombre); setLista([]); }}>{p.nombre} <span className="text-suave">· {p.codigo_interno}</span></button></li>)}
        </ul>
      )}
    </div>
  );
}

export function Impuestos() {
  const { puede } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [msg, setMsg] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const [regla, setRegla] = useState({ categoria_id: "", iva: "0.21", internos: "0" });
  const [conv, setConv] = useState<{ producto?: { id: number; nombre: string }; unidad: string; factor: string; proveedor_id: string }>({ unidad: "bulto", factor: "", proveedor_id: "" });
  const [desc, setDesc] = useState({ proveedor_id: "", categoria_id: "", tipo: "porcentaje", porcentaje: "", compra: "12", bonifica: "1", desde: "0", descripcion: "" });
  const cargar = useCallback(() => api<R>("/costos/config").then(setR).catch((e) => setMsg({ tipo: "error", texto: e.message })), []);
  useEffect(() => { cargar(); }, [cargar]);
  async function hacer(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ tipo: "ok", texto: ok }); cargar(); } catch (e) { setMsg({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo guardar." }); }
  }
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const config = puede("configurar_empresa"), compras = puede("gestionar_proveedores");
  return (
    <div className="grid grid-cols-1 gap-4">
      {msg && <Aviso tipo={msg.tipo}>{msg.texto}</Aviso>}
      <Tarjeta titulo="Impuestos">
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1" disabled={!config} checked={r.costos_con_iva}
            onChange={(e) => hacer(() => api("/costos/config", { metodo: "PUT", cuerpo: { costos_con_iva: e.target.checked } }), "Guardado. Los márgenes se recalculan en unos minutos.")} />
          <span>Los costos de mis productos están cargados <strong>con IVA</strong>. Dejalo sin marcar si cargás el costo neto de la factura
            (responsable inscripto): es lo habitual y lo que trae Odoo.</span>
        </label>
        <h3 className="mt-4 text-sm font-medium">IVA e impuestos internos por categoría o producto</h3>
        <p className="text-xs text-suave">Sin regla, el producto lleva 21 %. Los internos (cigarrillos, algunas bebidas) no se recuperan: quedan en el costo.</p>
        {r.reglas.length > 0 && (
          <Tabla columnas={["Aplica a", "IVA", "Internos", ""]}>
            {r.reglas.map((x) => (
              <tr key={x.id}><td>{x.nombre} <span className="text-xs text-suave">({x.nivel})</span></td><td>{Number(x.iva) === 0 ? "Exento" : pct(x.iva)}</td>
                <td>{pct(x.impuestos_internos)}</td>
                <td>{config && <Boton variante="fantasma" onClick={() => hacer(() => api(`/costos/impuestos/${x.id}`, { metodo: "DELETE" }), "Regla borrada.")}>Borrar</Boton>}</td></tr>
            ))}
          </Tabla>
        )}
        {config && (
          <div className="mt-3 grid gap-2 sm:grid-cols-4">
            <Selector aria-label="Categoría" value={regla.categoria_id} onChange={(e) => setRegla({ ...regla, categoria_id: e.target.value })}>
              <option value="">Categoría…</option>{r.categorias.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
            </Selector>
            <Selector aria-label="IVA" value={regla.iva} onChange={(e) => setRegla({ ...regla, iva: e.target.value })}>
              {IVAS.map(([v, n]) => <option key={v} value={v}>IVA {n}</option>)}
            </Selector>
            <Entrada aria-label="Impuestos internos %" inputMode="decimal" placeholder="Internos %" value={regla.internos} onChange={(e) => setRegla({ ...regla, internos: e.target.value })} />
            <Boton disabled={!regla.categoria_id} onClick={() => hacer(() => api("/costos/impuestos", { metodo: "POST", cuerpo: {
              categoria_id: Number(regla.categoria_id), iva: regla.iva, impuestos_internos: String(Number(regla.internos.replace(",", ".") || 0) / 100) } }), "Regla guardada.")}>Agregar</Boton>
          </div>
        )}
      </Tarjeta>

      <Tarjeta titulo="Unidades de compra">
        <p className="text-sm text-suave">Cuántas unidades base trae cada bulto, caja o pack. Así una factura de «2 bultos» suma las unidades exactas y el costo queda por unidad.
          Sin factor cargado, el bulto usa las unidades por bulto del proveedor.</p>
        {r.conversiones.length > 0 && (
          <Tabla columnas={["Producto", "1 de…", "Equivale a", "Proveedor", ""]}>
            {r.conversiones.map((x) => (
              <tr key={x.id}><td>{x.producto}</td><td>{x.unidad}</td><td>{numero(Number(x.factor), Number(x.factor) % 1 ? 3 : 0)} {x.base === "kg" ? "kg" : "u."}</td>
                <td>{x.proveedor ?? "Todos"}</td>
                <td>{compras && <Boton variante="fantasma" onClick={() => hacer(() => api(`/costos/conversiones/${x.id}`, { metodo: "DELETE" }), "Borrada.")}>Borrar</Boton>}</td></tr>
            ))}
          </Tabla>
        )}
        {compras && (
          <div className="mt-3 grid gap-2 sm:grid-cols-5">
            <div className="sm:col-span-2"><BuscarProducto alElegir={(p) => setConv({ ...conv, producto: p })} /></div>
            <Selector aria-label="Unidad" value={conv.unidad} onChange={(e) => setConv({ ...conv, unidad: e.target.value })}>
              {["bulto", "caja", "pack", "display", "fardo"].map((u) => <option key={u}>{u}</option>)}
            </Selector>
            <Entrada aria-label="Unidades por" inputMode="decimal" placeholder="Unidades" value={conv.factor} onChange={(e) => setConv({ ...conv, factor: e.target.value })} />
            <Boton disabled={!conv.producto || !conv.factor} onClick={() => hacer(() => api("/costos/conversiones", { metodo: "POST", cuerpo: {
              producto_id: conv.producto!.id, unidad: conv.unidad, factor: conv.factor.replace(",", "."), proveedor_id: conv.proveedor_id ? Number(conv.proveedor_id) : null } }), "Conversión guardada.")}>Agregar</Boton>
          </div>
        )}
      </Tarjeta>

      <Tarjeta titulo="Descuentos y bonificaciones de proveedores">
        <p className="text-sm text-suave">Bajan el costo de reposición: los porcentajes se aplican en cascada y una bonificación «12 + 1» equivale a 7,7 %.</p>
        {r.descuentos.length > 0 && (
          <Tabla columnas={["Proveedor", "Aplica a", "Descuento", "Desde cantidad", "Vigencia", ""]}>
            {r.descuentos.map((x) => (
              <tr key={x.id}><td>{x.proveedor}</td><td>{x.producto ?? x.categoria ?? "Todo el proveedor"}</td>
                <td>{x.tipo === "bonificacion" ? `${x.compra_unidades} + ${x.bonifica_unidades}` : pct(x.porcentaje)}{x.descripcion && <span className="block text-xs text-suave">{x.descripcion}</span>}</td>
                <td className="text-right">{numero(Number(x.desde_cantidad))}</td>
                <td className="whitespace-nowrap">{fecha(x.vigente_desde)}{x.vigente_hasta ? ` – ${fecha(x.vigente_hasta)}` : ""}</td>
                <td>{compras && <Boton variante="fantasma" onClick={() => hacer(() => api(`/costos/descuentos/${x.id}`, { metodo: "DELETE" }), "Borrado.")}>Borrar</Boton>}</td></tr>
            ))}
          </Tabla>
        )}
        {compras && (
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            <Selector aria-label="Proveedor" value={desc.proveedor_id} onChange={(e) => setDesc({ ...desc, proveedor_id: e.target.value })}>
              <option value="">Proveedor…</option>{r.proveedores.map((p) => <option key={p.id} value={p.id}>{p.razon_social}</option>)}
            </Selector>
            <Selector aria-label="Categoría" value={desc.categoria_id} onChange={(e) => setDesc({ ...desc, categoria_id: e.target.value })}>
              <option value="">Todos sus productos</option>{r.categorias.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
            </Selector>
            <Selector aria-label="Tipo" value={desc.tipo} onChange={(e) => setDesc({ ...desc, tipo: e.target.value })}>
              <option value="porcentaje">Porcentaje</option><option value="bonificacion">Bonificación en unidades</option><option value="nota_credito">Nota de crédito (porcentaje)</option>
            </Selector>
            {desc.tipo === "bonificacion" ? (
              <div className="flex items-center gap-2"><Entrada aria-label="Compra" value={desc.compra} onChange={(e) => setDesc({ ...desc, compra: e.target.value })} /> +
                <Entrada aria-label="Sin cargo" value={desc.bonifica} onChange={(e) => setDesc({ ...desc, bonifica: e.target.value })} /></div>
            ) : <Entrada aria-label="Porcentaje" inputMode="decimal" placeholder="Porcentaje (ej. 5)" value={desc.porcentaje} onChange={(e) => setDesc({ ...desc, porcentaje: e.target.value })} />}
            <Campo etiqueta="Desde cantidad (escala)"><Entrada inputMode="decimal" value={desc.desde} onChange={(e) => setDesc({ ...desc, desde: e.target.value })} /></Campo>
            <Boton disabled={!desc.proveedor_id} onClick={() => hacer(() => api("/costos/descuentos", { metodo: "POST", cuerpo: {
              proveedor_id: Number(desc.proveedor_id), categoria_id: desc.categoria_id ? Number(desc.categoria_id) : null, tipo: desc.tipo,
              porcentaje: desc.tipo === "bonificacion" ? null : String(Number(desc.porcentaje.replace(",", ".") || 0) / 100),
              compra_unidades: desc.tipo === "bonificacion" ? Number(desc.compra) : null, bonifica_unidades: desc.tipo === "bonificacion" ? Number(desc.bonifica) : null,
              desde_cantidad: desc.desde || "0" } }), "Descuento guardado. Los costos se recalculan en unos minutos.")}>Agregar</Boton>
          </div>
        )}
      </Tarjeta>
      <ComoSeCalcula>
        <p>Costo de reposición = costo de la lista vigente del proveedor principal, sin IVA ni percepciones (si los cargás con IVA) y menos sus descuentos.
          Costo histórico = promedio ponderado de lo que recibiste en los últimos 12 meses. El margen y la remarcación usan el de reposición.</p>
        <p>Margen = (precio sin IVA − costo de reposición) ÷ precio sin IVA. La ganancia de todos los reportes también es sin IVA.</p>
      </ComoSeCalcula>
    </div>
  );
}
