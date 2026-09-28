"use client";
// Canales de venta y e-commerce (sección 12): ganancia real por canal, participación, stock unificado, sobreventa y métricas online.
import Link from "next/link";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { parametrosFiltro } from "@/lib/consulta";
import { fechaHora, numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, ComoSeCalcula, Etiqueta, Tabla, Tarjeta, Vacio, cx } from "@/components/ui";

type Fila = { canal: string; codigo: string; plataforma: string; plataforma_id: number | null; tickets: number; ventas: string; costo_mercaderia: string; ganancia_bruta: string;
  comision: string; envio: string; costo_medios: string; publicidad: string; ganancia_real: string; margen_bruto: number | null; margen_real: number | null;
  ticket_promedio: string | null; participacion: number };
type Resultado = { periodo: { etiqueta: string }; filas: Fila[]; evolucion: { mes: string; canal: string; ventas: string }[] };
type Sobre = { id: number; plataforma: string; nombre: string; codigo_interno: string; stock_publicado: string; disponible: string; reservado: string; exceso: string; en_riesgo: string; ubicacion: string };
type Stock = { sobreventa: Sobre[]; pendientes: { ticket_id: number; numero_externo: string; plataforma: string; creado_at: string; total: string; ubicacion: string; lineas: number }[];
  reservado: { r: string; productos: number } };
type Ecom = { totales: { pedidos: number; cancelados: number; devueltos: number; reclamos: number };
  por_producto: { producto_id: number; nombre: string; pedidos: number; cancelados: number; devueltos: number; reclamos: number }[];
  despacho: { ubicacion: string; plataforma: string; despachados: number; horas_promedio: number; en_24h: number }[];
  no_publicados: { producto_id: number; nombre: string; codigo_interno: string; unidades_30d: string; facturacion_30d: string }[] };
const PESTANAS = [["resultado", "Ganancia por canal"], ["stock", "Stock y sobreventa"], ["online", "Tienda online"]] as const;
const COLORES = ["var(--serie-1)", "var(--serie-2)", "var(--serie-3)", "var(--serie-4)"];

function Resultado() {
  const { filtro, puede } = useSesion();
  const [r, setR] = useState<Resultado | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (puede("ver_costos")) { setR(null); api<Resultado>(`/canales/resultado?${parametrosFiltro(filtro)}`).then(setR).catch((e) => setError(e.message)); } }, [filtro, puede]);
  if (!puede("ver_costos")) return <Aviso>La ganancia por canal la ven el dueño y el comprador.</Aviso>;
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const canales = [...new Set(r.evolucion.map((e) => e.canal))];
  const meses = [...new Set(r.evolucion.map((e) => e.mes))].sort();
  const serie = meses.map((m) => {
    const fila: Record<string, number | string> = { mes: m.slice(5, 7) + "/" + m.slice(2, 4) };
    const total = r.evolucion.filter((e) => e.mes === m).reduce((s, e) => s + Number(e.ventas), 0) || 1;
    for (const c of canales) fila[c] = (Number(r.evolucion.find((e) => e.mes === m && e.canal === c)?.ventas ?? 0) / total) * 100;
    return fila;
  });
  const renglones: { t: string; f: (x: Fila) => string; resta?: boolean; fuerte?: boolean }[] = [
    { t: "Ventas", f: (x) => plata(x.ventas) }, { t: "Costo de la mercadería", f: (x) => plata(x.costo_mercaderia), resta: true },
    { t: "Comisión de la plataforma", f: (x) => plata(x.comision), resta: true }, { t: "Envío a tu cargo", f: (x) => plata(x.envio), resta: true },
    { t: "Costo de cobrar (medios de pago)", f: (x) => plata(x.costo_medios), resta: true }, { t: "Publicidad", f: (x) => plata(x.publicidad), resta: true },
    { t: "Ganancia real", f: (x) => plata(x.ganancia_real), fuerte: true },
    { t: "Margen bruto → real", f: (x) => `${numero((x.margen_bruto ?? 0) * 100, 1)} % → ${numero((x.margen_real ?? 0) * 100, 1)} %` },
    { t: "Participación en ventas", f: (x) => `${numero(x.participacion * 100, 1)} %` }, { t: "Ticket promedio", f: (x) => plata(x.ticket_promedio) },
  ];
  return (
    <div className="grid grid-cols-1 gap-4">
      <Tarjeta titulo={`Ganancia real por canal · ${r.periodo.etiqueta}`}>
        <Tabla columnas={["", ...r.filas.map((x) => x.plataforma)]}>
          {renglones.map((g) => (
            <tr key={g.t} className={g.fuerte ? "font-semibold" : ""}>
              <td className="text-suave">{g.resta ? "− " : ""}{g.t}</td>
              {r.filas.map((x) => <td key={x.plataforma} className="whitespace-nowrap text-right">{g.f(x)}</td>)}
            </tr>
          ))}
        </Tabla>
        <div className="mt-3">
          <ComoSeCalcula>
            <p>Ganancia real = ventas − costo de la mercadería − comisión de la plataforma − envío a cargo tuyo − costo del medio de pago − publicidad del período (prorrateada por días).</p>
            <p>El precio online sugerido que cubre estos costos está en <Link className="text-acento underline" href="/precios/">Precios</Link>, eligiendo el canal online en el filtro de arriba.</p>
          </ComoSeCalcula>
        </div>
      </Tarjeta>
      {serie.length > 1 && (
        <Tarjeta titulo="Participación de cada canal, mes a mes">
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={serie} barCategoryGap="25%" margin={{ top: 4, right: 4, left: -10, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--grafico-grilla)" />
                <XAxis dataKey="mes" tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
                <YAxis tickFormatter={(v: number) => `${Math.round(v)} %`} domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fontSize: 11, fill: "var(--grafico-tinta)" }} stroke="var(--grafico-eje)" />
                <Tooltip formatter={(v) => `${numero(Number(v), 1)} %`} cursor={{ fill: "var(--panel-2)" }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {canales.map((c, i) => <Bar key={c} dataKey={c} stackId="c" fill={COLORES[i % 4]} stroke="var(--panel)" strokeWidth={2} isAnimationActive={false} />)}
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Tarjeta>
      )}
    </div>
  );
}

type Propuesta = { id: number; motivo: "sobreventa" | "falta_publicar"; stock_publicado: string; disponible: string; stock_propuesto: number; plataforma: string;
  nombre: string; codigo_interno: string; ubicacion: string; precio: string | null; se_puede_enviar: boolean };
type Historial = { id: number; estado: string; stock_publicado: string; stock_propuesto: number; resuelta_at: string; respuesta: string | null; plataforma: string;
  nombre: string; resuelta_por: string | null };
type Propuestas = { propuestas: Propuesta[]; historial: Historial[]; puede_aprobar: boolean };

// Stock publicado (fase 3): el sistema propone y una persona aprueba (CLAUDE.md, regla 4). Nada se envía sin ese clic.
function PropuestasStock({ alCambiar }: { alCambiar: () => void }) {
  const [r, setR] = useState<Propuestas | null>(null);
  const [elegidas, setElegidas] = useState<Set<number>>(new Set());
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error" | "alerta"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const cargar = () => api<Propuestas>("/canales/stock/propuestas").then((x) => { setR(x); setElegidas(new Set(x.propuestas.filter((p) => p.se_puede_enviar).map((p) => p.id))); }).catch(() => {});
  useEffect(() => { cargar(); }, []);
  async function accion(que: "aplicar" | "descartar") {
    setOcupado(true);
    try {
      const x = await api<{ mensaje?: string; descartadas?: number; aplicadas?: number; resultados?: { estado: string }[] }>(
        `/canales/stock/propuestas/${que}`, { metodo: "POST", cuerpo: { ids: [...elegidas] } });
      const fallas = (x.resultados ?? []).filter((y) => y.estado === "error").length;
      setMensaje({ tipo: fallas ? "alerta" : "ok", texto: x.mensaje ?? `${x.descartadas} propuestas descartadas.` });
      await cargar();
      alCambiar();
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo." });
    } finally {
      setOcupado(false);
    }
  }
  if (!r) return null;
  const alternar = (id: number) => setElegidas((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  return (
    <Tarjeta titulo={`Stock publicado para corregir · ${r.propuestas.length}`}>
      <p className="mb-3 text-sm text-suave">
        Comparamos lo publicado con lo disponible en la sucursal que despacha. Nada se cambia en las plataformas hasta que elegís y aprobás.
      </p>
      {mensaje && <div className="mb-3"><Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso></div>}
      {r.propuestas.length === 0 ? <Aviso tipo="ok">✓ Lo publicado coincide con lo disponible.</Aviso> : (
        <>
          <Tabla columnas={["", "Producto", "Plataforma", "Publicado", "Disponible", "Publicar", "Por qué"]}>
            {r.propuestas.map((p) => (
              <tr key={p.id}>
                <td><input type="checkbox" aria-label={`Elegir ${p.nombre} en ${p.plataforma}`} checked={elegidas.has(p.id)} disabled={!r.puede_aprobar || !p.se_puede_enviar}
                  onChange={() => alternar(p.id)} className="h-4 w-4" /></td>
                <td>{p.nombre}<span className="block text-xs text-suave">{p.codigo_interno} · despacha {p.ubicacion}</span></td>
                <td>{p.plataforma}{!p.se_puede_enviar && <span className="block text-xs text-peligro">Sin conexión</span>}</td>
                <td className="text-right">{numero(p.stock_publicado)}</td>
                <td className="text-right">{numero(p.disponible)}</td>
                <td className="text-right font-semibold">{numero(p.stock_propuesto)}</td>
                <td>{p.motivo === "sobreventa" ? <Etiqueta tono="peligro">▲ Publicás de más</Etiqueta> : <Etiqueta tono="alerta">Publicado en 0 con stock</Etiqueta>}</td>
              </tr>
            ))}
          </Tabla>
          {r.puede_aprobar ? (
            <div className="mt-3 flex flex-wrap gap-2">
              <Boton disabled={ocupado || elegidas.size === 0} onClick={() => accion("aplicar")}>Actualizar {elegidas.size} en las plataformas</Boton>
              <Boton variante="secundario" disabled={ocupado || elegidas.size === 0} onClick={() => accion("descartar")}>Descartar</Boton>
            </div>
          ) : <p className="mt-3 text-sm text-suave">Las aprueba el dueño (o quien gestiona las conexiones).</p>}
          <p className="mt-2 text-xs text-suave">Al aprobar se vuelve a calcular el disponible de ese momento y ese es el valor que se envía.</p>
        </>
      )}
      {r.historial.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-acento">Últimos cambios aprobados</summary>
          <Tabla columnas={["Cuándo", "Producto", "Plataforma", "Cambio", "Resultado"]}>
            {r.historial.map((h) => (
              <tr key={h.id}>
                <td className="whitespace-nowrap">{fechaHora(h.resuelta_at)}<span className="block text-xs text-suave">{h.resuelta_por}</span></td>
                <td>{h.nombre}</td><td>{h.plataforma}</td>
                <td className="whitespace-nowrap">{numero(h.stock_publicado)} → {numero(h.stock_propuesto)}</td>
                <td>{h.estado === "aplicada" ? <Etiqueta tono="ok">✓ Aplicado</Etiqueta> : h.estado === "descartada" ? <Etiqueta>Descartado</Etiqueta> : <Etiqueta tono="peligro">✕ Error</Etiqueta>}
                  {h.respuesta && <span className="block text-xs text-suave">{h.respuesta}</span>}</td>
              </tr>
            ))}
          </Tabla>
        </details>
      )}
    </Tarjeta>
  );
}

function StockOnline() {
  const [r, setR] = useState<Stock | null>(null);
  const cargar = () => api<Stock>("/canales/stock").then(setR).catch(() => {});
  useEffect(() => { cargar(); }, []);
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  return (
    <div className="grid grid-cols-1 gap-4">
      <PropuestasStock alCambiar={cargar} />
      <Tarjeta titulo={`Sobreventa · ${r.sobreventa.length} publicaciones`}>
        {r.sobreventa.length === 0 ? <Aviso tipo="ok">✓ Todo lo publicado tiene stock para cumplir.</Aviso> : (
          <>
            <Aviso tipo="error">▲ Estas publicaciones muestran más stock del que hay. Si entran esos pedidos vas a tener que cancelarlos: aprobá la corrección de arriba.</Aviso>
            <div className="mt-3">
              <Tabla columnas={["Producto", "Plataforma", "Publicado", "Disponible", "De más", "En riesgo"]}>
                {r.sobreventa.map((s) => (
                  <tr key={s.id}>
                    <td>{s.nombre}<span className="block text-xs text-suave">{s.codigo_interno} · despacha {s.ubicacion}</span></td>
                    <td>{s.plataforma}</td>
                    <td className="text-right">{numero(s.stock_publicado)}</td>
                    <td className="text-right">{numero(s.disponible)}{Number(s.reservado) > 0 && <span className="block text-xs text-suave">{numero(s.reservado)} reservadas</span>}</td>
                    <td className="text-right font-semibold">{numero(s.exceso)}</td>
                    <td className="text-right">{plata(s.en_riesgo)}</td>
                  </tr>
                ))}
              </Tabla>
            </div>
          </>
        )}
        <p className="mt-2 text-xs text-suave">Disponible = stock de la sucursal que despacha − lo reservado por pedidos online sin despachar.</p>
      </Tarjeta>
      <Tarjeta titulo={`Pedidos online sin despachar · ${r.pendientes.length}`}>
        {r.pendientes.length === 0 ? <Vacio titulo="No hay pedidos pendientes" /> : (
          <>
            <p className="mb-2 text-sm text-suave">Reservan {numero(r.reservado.r)} unidades de {numero(r.reservado.productos)} productos: todos los canales usan el mismo stock.</p>
            <Tabla columnas={["Pedido", "Plataforma", "Entró", "Productos", "Total"]}>
              {r.pendientes.map((p) => (
                <tr key={p.ticket_id}><td>{p.numero_externo}</td><td>{p.plataforma}</td><td className="whitespace-nowrap">{fechaHora(p.creado_at)}</td>
                  <td className="text-right">{p.lineas}</td><td className="text-right">{plata(p.total)}</td></tr>
              ))}
            </Tabla>
          </>
        )}
      </Tarjeta>
    </div>
  );
}

function Online() {
  const [r, setR] = useState<Ecom | null>(null);
  useEffect(() => { api<Ecom>("/canales/ecommerce").then(setR).catch(() => {}); }, []);
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const t = r.totales;
  const tasa = (n: number) => (t.pedidos ? `${numero((n / t.pedidos) * 100, 1)} %` : "—");
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[["Pedidos (90 días)", numero(t.pedidos)], ["Cancelados", `${numero(t.cancelados)} · ${tasa(t.cancelados)}`], ["Devueltos", `${numero(t.devueltos)} · ${tasa(t.devueltos)}`],
          ["Con reclamo", `${numero(t.reclamos)} · ${tasa(t.reclamos)}`]].map(([a, b]) => (
          <div key={a} className="rounded-xl border border-borde bg-panel p-4"><p className="text-sm text-suave">{a}</p><p className="mt-1 text-xl font-semibold">{b}</p></div>
        ))}
      </div>
      <Tarjeta titulo="Tiempo de despacho">
        <Tabla columnas={["Despacha", "Plataforma", "Pedidos", "Horas promedio", "En menos de 24 h"]}>
          {r.despacho.map((d) => (
            <tr key={`${d.ubicacion}-${d.plataforma}`}><td>{d.ubicacion}</td><td>{d.plataforma}</td><td className="text-right">{numero(d.despachados)}</td>
              <td className="text-right">{numero(d.horas_promedio, 1)}</td><td className="text-right">{numero(d.en_24h * 100)} %</td></tr>
          ))}
        </Tabla>
      </Tarjeta>
      <Tarjeta titulo="Productos con cancelaciones, devoluciones o reclamos">
        {r.por_producto.length === 0 ? <Vacio titulo="Sin problemas" /> : (
          <Tabla columnas={["Producto", "Pedidos", "Cancelados", "Devueltos", "Reclamos"]}>
            {r.por_producto.slice(0, 15).map((p) => (
              <tr key={p.producto_id}><td>{p.nombre}</td><td className="text-right">{p.pedidos}</td><td className="text-right">{p.cancelados}</td>
                <td className="text-right">{p.devueltos}</td><td className="text-right">{p.reclamos}</td></tr>
            ))}
          </Tabla>
        )}
      </Tarjeta>
      <Tarjeta titulo="Se venden bien en el local y no están publicados">
        {r.no_publicados.length === 0 ? <Vacio titulo="Nada para sumar">Conectá Tiendanube o Mercado Libre en Datos → Conectar la caja para comparar.</Vacio> : (
          <Tabla columnas={["Producto", "Unidades 30 días (local)", "Facturación 30 días"]}>
            {r.no_publicados.map((p) => (
              <tr key={p.producto_id}><td>{p.nombre}<span className="block text-xs text-suave">{p.codigo_interno}</span></td>
                <td className="text-right">{numero(p.unidades_30d)}</td><td className="text-right">{plataCorta(p.facturacion_30d)}</td></tr>
            ))}
          </Tabla>
        )}
      </Tarjeta>
    </div>
  );
}

export default function Canales() {
  const [activa, setActiva] = useState<string>("resultado");
  useEffect(() => {
    const leer = () => { const id = location.hash.slice(1); if (PESTANAS.some(([p]) => p === id)) setActiva(id); };
    leer();
    window.addEventListener("hashchange", leer);
    return () => window.removeEventListener("hashchange", leer);
  }, []);
  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Canales</h1>
        <p className="text-sm text-suave">Cuánto te deja de verdad cada canal, el stock que comparten y la tienda online.</p>
      </div>
      <div role="tablist" aria-label="Canales" className="-mx-4 flex gap-1 overflow-x-auto px-4 pb-1">
        {PESTANAS.map(([id, nombre]) => (
          <a key={id} role="tab" aria-selected={id === activa} href={`#${id}`}
            className={cx("whitespace-nowrap rounded-lg px-3 py-1.5 text-sm", id === activa ? "bg-acento text-acento-texto" : "text-suave hover:bg-panel-2")}>{nombre}</a>
        ))}
      </div>
      {activa === "resultado" && <Resultado />}
      {activa === "stock" && <StockOnline />}
      {activa === "online" && <Online />}
    </div>
  );
}
