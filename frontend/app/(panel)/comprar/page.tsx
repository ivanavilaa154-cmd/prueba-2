"use client";
// Qué me falta y qué comprar (sección 6).
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { fechaCorta, fechaHora, numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Semaforo } from "@/components/Semaforo";
import { Panel } from "@/components/Panel";
import { TablaDatos, type Columna } from "@/components/TablaDatos";
import { DetalleProducto } from "@/components/comprar/DetalleProducto";
import { Recuento } from "@/components/comprar/Recuento";
import { Aviso, Boton, ComoSeCalcula, Selector, Tarjeta, cx } from "@/components/ui";

type Fila = {
  producto_id: number; ubicacion_id: number; codigo: string; nombre: string; ubicacion: string; categoria: string; subcategoria: string;
  stock: string; vpd: string; dias_stock: string | null; fecha_quiebre: string | null; dia_quiebre: string | null; cantidad_sugerida: string;
  bultos: number; semaforo: string; clase_abc: string; proveedor: string | null; proveedor_id: number | null; monto_sugerido: string;
  ventas_en_riesgo: string | null; confianza: string; stock_negativo: boolean; sin_costo: boolean; tipo_ubicacion: string;
  pronostico_7d: string | null; pronostico_7d_min: string | null; pronostico_7d_max: string | null; prob_quiebre: string | null;
};
type Respuesta = {
  tarjetas: { productos_en_rojo: number; productos_en_amarillo: number; plata_a_comprar: string; ventas_en_riesgo: string };
  filas: Fila[];
  resumen_categorias: { categoria_id: number; categoria: string; rojos: number; amarillos: number; productos: number; monto_a_comprar: string; cobertura_mediana: number | null }[];
  opciones: { categorias: { id: number; nombre: string }[]; proveedores: { id: number; nombre: string }[] };
  calculado_at: string | null;
  puede_comprar: boolean; puede_transferir: boolean; puede_recontar: boolean;
};

export default function Comprar() {
  const { filtro, yo } = useSesion();
  const [vista, setVista] = useState<"productos" | "categorias" | "recuento">("productos");
  const [datos, setDatos] = useState<Respuesta | null>(null);
  const [local, setLocal] = useState({ categoria: "", proveedor: "", semaforo: "", abc: "" });
  const [detalle, setDetalle] = useState<Fila | null>(null);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: React.ReactNode } | null>(null);
  const [cargando, setCargando] = useState(true);

  // Enlaces desde avisos e Inicio: ?semaforo=rojo · ?producto=ID&u=UBICACION (abre el detalle)
  useEffect(() => {
    const q = new URLSearchParams(location.search);
    if (q.get("semaforo")) setLocal((l) => ({ ...l, semaforo: q.get("semaforo") ?? "" }));
    if (location.hash === "#recuento") setVista("recuento");
  }, []);
  useEffect(() => {
    const q = new URLSearchParams(location.search);
    const pid = Number(q.get("producto"));
    if (!pid || !datos || detalle) return;
    const u = Number(q.get("u"));
    const fila = datos.filas.find((f) => f.producto_id === pid && (!u || f.ubicacion_id === u));
    if (fila) setDetalle(fila);
  }, [datos]); // eslint-disable-line react-hooks/exhaustive-deps

  const cargar = useCallback(() => {
    const q = new URLSearchParams();
    if (filtro.ubicaciones.length) q.set("ubicaciones", filtro.ubicaciones.join(","));
    if (filtro.canal !== "todos") q.set("canal", filtro.canal);
    Object.entries(local).forEach(([k, v]) => v && q.set(k, v));
    setCargando(true);
    api<Respuesta>(`/comprar?${q}`).then(setDatos).catch((e) => setMensaje({ tipo: "error", texto: e.message })).finally(() => setCargando(false));
  }, [filtro.ubicaciones, filtro.canal, local]);
  useEffect(() => { cargar(); }, [cargar]);

  const varias = yo.usuario.todas_ubicaciones || yo.ubicaciones.length > 1;
  const columnas = useMemo<Columna<Fila>[]>(() => [
    { id: "producto", titulo: "Producto", valor: (f) => f.nombre, render: (f) => (
      <span><span className="font-medium">{f.nombre}</span><br /><span className="text-xs text-suave">{f.codigo}{f.confianza === "baja" ? " · poca historia" : ""}{f.stock_negativo ? " · stock negativo" : ""}</span></span>) },
    ...(varias ? [{ id: "sucursal", titulo: "Sucursal", valor: (f: Fila) => f.ubicacion }] : []),
    { id: "categoria", titulo: "Categoría", valor: (f) => f.categoria, ocultarEnCelular: true },
    { id: "stock", titulo: "Stock", valor: (f) => Number(f.stock), render: (f) => numero(f.stock, 0), derecha: true },
    { id: "vpd", titulo: "Venta/día", valor: (f) => Number(f.vpd), render: (f) => numero(f.vpd, 1), derecha: true },
    { id: "pron7", titulo: "Venta 7 días", valor: (f) => (f.pronostico_7d === null ? null : Number(f.pronostico_7d)),
      render: (f) => (f.pronostico_7d === null ? "—" : <span title="Rango con 80 % de confianza">{numero(f.pronostico_7d, 0)}<br />
        <span className="text-xs text-suave">{numero(f.pronostico_7d_min, 0)}–{numero(f.pronostico_7d_max, 0)}</span></span>), derecha: true, ocultarEnCelular: true },
    { id: "riesgo", titulo: "Riesgo de quiebre", valor: (f) => (f.prob_quiebre === null ? null : Number(f.prob_quiebre)),
      render: (f) => (f.prob_quiebre === null ? "—" : <span className={Number(f.prob_quiebre) >= 0.5 ? "font-semibold text-peligro" : Number(f.prob_quiebre) >= 0.2 ? "text-alerta" : ""}>
        {Number(f.prob_quiebre) >= 0.5 ? "▲ " : ""}{numero(Number(f.prob_quiebre) * 100, 0)} %</span>), derecha: true },
    { id: "dias", titulo: "Días de stock", valor: (f) => (f.dias_stock === null ? null : Number(f.dias_stock)), render: (f) => (f.dias_stock === null ? "—" : numero(f.dias_stock, 0)), derecha: true },
    { id: "quiebre", titulo: "Se agota", valor: (f) => f.fecha_quiebre, render: (f) => (f.fecha_quiebre ? <span>{fechaCorta(f.fecha_quiebre).slice(0, 5)} <span className="text-suave">{f.dia_quiebre?.slice(0, 3)}</span></span> : "—") },
    { id: "sugerido", titulo: "Sugerido", valor: (f) => Number(f.cantidad_sugerida), render: (f) => (Number(f.cantidad_sugerida) > 0
      ? <span>{numero(f.cantidad_sugerida, 0)}<br /><span className="text-xs text-suave">{numero(f.bultos, f.bultos % 1 ? 1 : 0)} {f.bultos === 1 ? "bulto" : "bultos"}</span></span> : "—"), derecha: true },
    { id: "monto", titulo: "A comprar", valor: (f) => Number(f.monto_sugerido), render: (f) => (Number(f.monto_sugerido) ? plata(f.monto_sugerido) : "—"), derecha: true, ocultarEnCelular: true },
    { id: "proveedor", titulo: "Proveedor", valor: (f) => f.proveedor, ocultarEnCelular: true },
    { id: "semaforo", titulo: "Estado", valor: (f) => ["rojo", "amarillo", "verde", "gris"].indexOf(f.semaforo), render: (f) => <Semaforo valor={f.semaforo} /> },
    { id: "abc", titulo: "ABC", valor: (f) => f.clase_abc },
  ], [varias]);

  async function crear(tipo: "orden_compra" | "transferencia", sel: Fila[], limpiar: () => void) {
    try {
      const r = await api<{ creados: { tipo: string; id: number }[] }>("/documentos/desde-seleccion", {
        metodo: "POST", cuerpo: { tipo, items: sel.map((f) => ({ producto_id: f.producto_id, ubicacion_id: f.ubicacion_id })) } });
      limpiar();
      setMensaje({ tipo: "ok", texto: <>Se {r.creados.length === 1 ? "creó" : "crearon"} {r.creados.length} {tipo === "orden_compra" ? "orden(es) de compra en borrador" : "transferencia(s) sugerida(s)"}. <Link className="underline" href="/transferencias/">Revisalas y aprobalas</Link>.</> });
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo crear." });
    }
  }
  async function marcar(sel: Fila[], limpiar: () => void) {
    try {
      const r = await api<{ agregados: number }>("/recuentos/marcar", { metodo: "POST", cuerpo: sel.map((f) => ({ producto_id: f.producto_id, ubicacion_id: f.ubicacion_id })) });
      limpiar();
      setMensaje({ tipo: "ok", texto: `${r.agregados} producto(s) agregados al recuento de hoy.` });
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo marcar." });
    }
  }

  const t = datos?.tarjetas;
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Comprar y reponer</h1>
          <p className="text-sm text-suave">Qué te falta, cuándo se agota y cuánto comprar.{datos?.calculado_at && ` Calculado el ${fechaHora(datos.calculado_at)}.`}</p>
        </div>
        <div role="tablist" className="flex gap-1">
          {([["productos", "Productos"], ["categorias", "Por categoría"], ...(datos?.puede_recontar ? [["recuento", "Recuento del día"]] : [])] as [typeof vista, string][]).map(([k, n]) => (
            <button key={k} role="tab" aria-selected={vista === k} onClick={() => setVista(k)}
              className={cx("rounded-lg px-3 py-1.5 text-sm", vista === k ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>{n}</button>
          ))}
        </div>
      </div>
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}

      {vista !== "recuento" && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <button className="rounded-xl border border-borde bg-panel p-4 text-left hover:border-acento" onClick={() => setLocal({ ...local, semaforo: local.semaforo === "rojo" ? "" : "rojo" })}>
            <p className="text-sm text-suave">Productos en rojo</p>
            <p className="mt-1 text-3xl font-semibold">{t ? numero(t.productos_en_rojo) : "…"}</p>
            <p className="mt-1 text-xs text-suave">{t ? `y ${numero(t.productos_en_amarillo)} para incluir en el próximo pedido` : ""}{local.semaforo === "rojo" ? " · filtrando" : ""}</p>
          </button>
          <div className="rounded-xl border border-borde bg-panel p-4">
            <p className="text-sm text-suave">Plata que falta comprar</p>
            <p className="mt-1 text-3xl font-semibold">{t ? plataCorta(t.plata_a_comprar) : "…"}</p>
            <p className="mt-1 text-xs text-suave">Suma de lo sugerido a costo</p>
          </div>
          <div className="rounded-xl border border-borde bg-panel p-4">
            <p className="text-sm text-suave">Ventas en riesgo por faltantes</p>
            <p className="mt-1 text-3xl font-semibold">{t ? plataCorta(t.ventas_en_riesgo) : "…"}</p>
            <p className="mt-1 text-xs text-suave">Lo que dejarías de vender hasta la próxima reposición</p>
          </div>
        </div>
      )}

      {vista !== "recuento" && datos && (
        <div className="flex flex-wrap gap-2">
          <Selector aria-label="Categoría" className="w-auto" value={local.categoria} onChange={(e) => setLocal({ ...local, categoria: e.target.value })}>
            <option value="">Todas las categorías</option>
            {datos.opciones.categorias.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
          </Selector>
          <Selector aria-label="Proveedor" className="w-auto" value={local.proveedor} onChange={(e) => setLocal({ ...local, proveedor: e.target.value })}>
            <option value="">Todos los proveedores</option>
            {datos.opciones.proveedores.map((c) => <option key={c.id} value={c.id}>{c.nombre}</option>)}
          </Selector>
          <Selector aria-label="Estado" className="w-auto" value={local.semaforo} onChange={(e) => setLocal({ ...local, semaforo: e.target.value })}>
            <option value="">Todos los estados</option>
            <option value="rojo">● Se agota</option><option value="amarillo">▲ Pedir</option><option value="verde">✓ Cubierto</option><option value="gris">■ Sobrestock</option>
          </Selector>
          <Selector aria-label="Clase ABC" className="w-auto" value={local.abc} onChange={(e) => setLocal({ ...local, abc: e.target.value })}>
            <option value="">Clase A, B y C</option><option value="A">Clase A</option><option value="B">Clase B</option><option value="C">Clase C</option>
          </Selector>
        </div>
      )}

      {vista === "productos" && (
        <Tarjeta>
          {cargando && !datos ? <p className="text-sm text-suave">Cargando…</p> : datos && (
            <TablaDatos filas={datos.filas} columnas={columnas} idFila={(f) => `${f.producto_id}-${f.ubicacion_id}`} nombreArchivo="comprar-y-reponer"
              alHacerClic={setDetalle}
              vacio="No hay productos con estos filtros. Si todavía no conectaste tus datos, empezá por Configuración → Importar."
              acciones={(sel, limpiar) => (
                <>
                  {datos.puede_comprar && <Boton onClick={() => crear("orden_compra", sel, limpiar)}>Generar OC por proveedor</Boton>}
                  {datos.puede_transferir && <Boton variante="secundario" onClick={() => crear("transferencia", sel, limpiar)}>Generar transferencia</Boton>}
                  {datos.puede_recontar && <Boton variante="secundario" onClick={() => marcar(sel, limpiar)}>Marcar para recuento</Boton>}
                </>
              )} />
          )}
        </Tarjeta>
      )}

      {vista === "categorias" && datos && (
        <Tarjeta titulo="Resumen por categoría">
          <TablaDatos filas={datos.resumen_categorias} idFila={(c) => String(c.categoria_id)} nombreArchivo="comprar-por-categoria" buscador={false}
            alHacerClic={(c) => { setLocal({ ...local, categoria: String(c.categoria_id) }); setVista("productos"); }}
            columnas={[
              { id: "cat", titulo: "Categoría", valor: (c) => c.categoria },
              { id: "rojos", titulo: "En rojo", valor: (c) => c.rojos, derecha: true },
              { id: "amarillos", titulo: "Para pedir", valor: (c) => c.amarillos, derecha: true },
              { id: "monto", titulo: "Monto a comprar", valor: (c) => Number(c.monto_a_comprar), render: (c) => plata(c.monto_a_comprar), derecha: true },
              { id: "cob", titulo: "Cobertura (mediana)", valor: (c) => c.cobertura_mediana, render: (c) => (c.cobertura_mediana === null ? "—" : `${numero(c.cobertura_mediana, 0)} días`), derecha: true },
            ]} />
        </Tarjeta>
      )}

      {vista === "recuento" && <Recuento />}

      {vista !== "recuento" && (
        <ComoSeCalcula>
          <p>Para cada producto en cada sucursal: venta promedio diaria de los últimos 28 días sin contar los días sin stock; pronóstico con el patrón de la semana, inicio de mes, feriados, estacionalidad y tendencia; días de stock = disponible ÷ pronóstico; horizonte = hasta que llegue el pedido siguiente (días de visita del proveedor + demora).</p>
          <p>Sugerido = pronóstico del horizonte + stock de seguridad − disponible − en tránsito − ya pedido, redondeado al bulto. Tocá un producto para ver su cuenta completa.</p>
          <p>Venta 7 días: el pronóstico con su rango del 80 % (lo real cae dentro 8 de cada 10 veces; lo medimos en <a className="text-acento underline" href="../modelos/">Salud de los pronósticos</a>).
            Riesgo de quiebre: probabilidad de que la venta supere lo disponible (más lo que está en camino) antes de la próxima entrega.</p>
          <p>Semáforo: <Semaforo valor="rojo" /> se agota antes de que pueda llegar la próxima reposición · <Semaforo valor="amarillo" /> incluirlo en el próximo pedido · <Semaforo valor="verde" /> cubierto · <Semaforo valor="gris" /> más de 30 días de stock.</p>
        </ComoSeCalcula>
      )}

      <Panel abierto={!!detalle} alCerrar={() => setDetalle(null)} titulo={detalle && (
        <div><p className="font-semibold">{detalle.nombre}</p><p className="text-xs text-suave">{detalle.codigo} · {detalle.categoria} › {detalle.subcategoria}</p></div>)}>
        {detalle && <DetalleProducto productoId={detalle.producto_id} ubicacionId={detalle.ubicacion_id} />}
      </Panel>
    </div>
  );
}
