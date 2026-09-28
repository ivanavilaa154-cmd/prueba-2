"use client";
// Lector de facturas, remitos y listas de precios con IA: subir → revisar cada línea → confirmar.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaHora, numero, plata } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Campo, Entrada, Etiqueta, Selector, Tabla, Tarjeta, Vacio } from "@/components/ui";

type Candidato = { producto_id: number; nombre: string; codigo: string; confianza: number };
type Linea = { codigo: string | null; descripcion: string; cantidad: number | null; costo_unitario: number | null; lote: string | null;
  vencimiento: string | null; confianza: number; producto_id: number | null; emparejado_por: string; candidatos: Candidato[]; revisar: boolean };
type Leido = { id: number; tipo: string; proveedor: string | null; cuit: string | null; numero: string | null; fecha: string | null;
  observaciones: string | null; lineas: Linea[]; proveedor_encontrado: { id: number; razon_social: string } | null };
type Proveedor = { id: number; razon_social: string; ordenes_abiertas: { id: number; numero: string; ubicacion_id: number | null; total: string }[] };
type Registro = { id: number; tipo: string; estado: string; nombre_archivo: string | null; created_at: string; proveedor: string | null;
  numero: string | null; lineas: number; mensaje: string | null; usuario: string | null };
type Encontrado = { id: number; nombre: string; codigo_interno: string };

const TIPOS = [{ id: "factura", nombre: "Factura" }, { id: "remito", nombre: "Remito" }, { id: "lista_precios", nombre: "Lista de precios" }];

function ElegirProducto({ linea, onCambio }: { linea: Linea; onCambio: (id: number | null, nombre?: string) => void }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<Encontrado[]>([]);
  useEffect(() => {
    if (q.trim().length < 2) return setRes([]);
    const t = setTimeout(() => api<Encontrado[]>(`/catalogo/buscar?q=${encodeURIComponent(q)}`).then(setRes).catch(() => {}), 250);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <div className="grid gap-1">
      <Selector className="w-56" value={linea.producto_id ?? ""} onChange={(e) => onCambio(e.target.value ? Number(e.target.value) : null)} aria-label="Producto">
        <option value="">Sin asignar (no se carga)</option>
        {linea.candidatos.map((c) => <option key={c.producto_id} value={c.producto_id}>{c.nombre} · {numero(c.confianza * 100)} %</option>)}
        {res.map((p) => <option key={`b${p.id}`} value={p.id}>{p.nombre} · {p.codigo_interno}</option>)}
      </Selector>
      <Entrada className="w-56" placeholder="Buscar otro…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Buscar producto" />
    </div>
  );
}

export function Documentos() {
  const { yo, puede } = useSesion();
  const tipos = TIPOS.filter((t) => (t.id === "lista_precios" ? puede("gestionar_proveedores") : puede("recepciones")));
  const [tipo, setTipo] = useState(tipos[0]?.id ?? "remito");
  const [ubicacion, setUbicacion] = useState<number | "">(yo?.ubicaciones[0]?.id ?? "");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [leido, setLeido] = useState<Leido | null>(null);
  const [lineas, setLineas] = useState<Linea[]>([]);
  const [proveedores, setProveedores] = useState<Proveedor[]>([]);
  const [proveedor, setProveedor] = useState<number | "">("");
  const [orden, setOrden] = useState<number | "">("");
  const [registros, setRegistros] = useState<Registro[]>([]);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => api<Registro[]>("/lector").then(setRegistros).catch(() => {}), []);
  useEffect(() => {
    cargar();
    api<Proveedor[]>("/proveedores").then(setProveedores).catch(() => {});
  }, [cargar]);

  async function leer() {
    if (!archivo) return;
    setOcupado(true);
    setMensaje(null);
    const form = new FormData();
    form.append("tipo", tipo);
    if (ubicacion) form.append("ubicacion_id", String(ubicacion));
    form.append("archivo", archivo);
    try {
      const r = await api<Leido>("/lector/leer", { formulario: form });
      setLeido(r);
      setLineas(r.lineas);
      setProveedor(r.proveedor_encontrado?.id ?? "");
      setOrden("");
      cargar();
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo leer." });
    } finally {
      setOcupado(false);
    }
  }
  async function confirmar() {
    if (!leido) return;
    setOcupado(true);
    try {
      const r = await api<{ mensaje: string }>(`/lector/${leido.id}/confirmar`, { metodo: "POST",
        cuerpo: { proveedor_id: proveedor, ubicacion_id: ubicacion || null, orden_id: orden || null, lineas } });
      setMensaje({ tipo: "ok", texto: `${r.mensaje}.` });
      setLeido(null);
      setArchivo(null);
      cargar();
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo confirmar." });
    } finally {
      setOcupado(false);
    }
  }
  async function descartar() {
    if (!leido) return;
    await api(`/lector/${leido.id}/descartar`, { metodo: "POST" }).catch(() => {});
    setLeido(null);
    cargar();
  }
  const cambiar = (i: number, cambio: Partial<Linea>) => setLineas(lineas.map((l, k) => (k === i ? { ...l, ...cambio } : l)));
  const esLista = leido?.tipo === "lista_precios";
  const abiertas = proveedores.find((p) => p.id === proveedor)?.ordenes_abiertas ?? [];
  const asignadas = lineas.filter((l) => l.producto_id).length;

  return (
    <div className="grid grid-cols-1 gap-4">
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
      {!leido && (
        <Tarjeta titulo="Leer un documento con IA">
          <p className="mb-3 text-sm text-suave">Sacale una foto a la factura, al remito o a la lista de precios (o subí el PDF). La IA lee cada línea; vos revisás antes de cargar nada.</p>
          <div className="grid gap-4 sm:grid-cols-3">
            <Campo etiqueta="Qué es">
              <Selector value={tipo} onChange={(e) => setTipo(e.target.value)}>{tipos.map((t) => <option key={t.id} value={t.id}>{t.nombre}</option>)}</Selector>
            </Campo>
            {tipo !== "lista_precios" && (
              <Campo etiqueta="Sucursal que recibe">
                <Selector value={ubicacion} onChange={(e) => setUbicacion(e.target.value ? Number(e.target.value) : "")}>
                  {yo?.ubicaciones.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
                </Selector>
              </Campo>
            )}
            <Campo etiqueta="Foto o PDF">
              <input type="file" accept=".pdf,.jpg,.jpeg,.png,.webp,image/*" capture="environment" onChange={(e) => setArchivo(e.target.files?.[0] ?? null)}
                className="text-sm file:mr-3 file:rounded-lg file:border file:border-borde file:bg-panel file:px-3 file:py-1.5 file:text-sm" />
            </Campo>
          </div>
          <div className="mt-4"><Boton disabled={!archivo || ocupado} onClick={leer}>{ocupado ? "Leyendo (puede tardar un minuto)…" : "Leer documento"}</Boton></div>
        </Tarjeta>
      )}

      {leido && (
        <Tarjeta titulo={`Revisá lo que leyó la IA${leido.numero ? ` · ${leido.numero}` : ""}`}>
          {leido.observaciones && <div className="mb-3"><Aviso tipo="alerta">{leido.observaciones}</Aviso></div>}
          <div className="grid gap-3 sm:grid-cols-3">
            <Campo etiqueta="Proveedor" ayuda={leido.proveedor ? `En el documento: ${leido.proveedor}${leido.cuit ? ` (CUIT ${leido.cuit})` : ""}` : undefined}>
              <Selector value={proveedor} onChange={(e) => { setProveedor(e.target.value ? Number(e.target.value) : ""); setOrden(""); }}>
                <option value="">Elegí el proveedor</option>
                {proveedores.map((p) => <option key={p.id} value={p.id}>{p.razon_social}</option>)}
              </Selector>
            </Campo>
            {!esLista && abiertas.length > 0 && (
              <Campo etiqueta="¿Corresponde a una orden de compra?" ayuda="Así se comparan cantidades y costos con lo pedido.">
                <Selector value={orden} onChange={(e) => setOrden(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">Sin orden</option>
                  {abiertas.map((o) => <option key={o.id} value={o.id}>{o.numero} · {plata(o.total)}</option>)}
                </Selector>
              </Campo>
            )}
          </div>
          <div className="mt-4">
            <Tabla columnas={["En el documento", "Producto", ...(esLista ? [] : ["Cantidad"]), "Costo unit.", ...(esLista ? [] : ["Lote", "Vence"])]}>
              {lineas.map((l, i) => (
                <tr key={i} className="align-top">
                  <td className="min-w-[12rem]">
                    {l.descripcion}
                    <div className="text-xs text-suave">{l.codigo ?? "sin código"}</div>
                    {l.revisar && <div className="mt-1"><Etiqueta tono="alerta">⚠ Revisar{l.confianza < 0.7 ? " · lectura dudosa" : ""}</Etiqueta></div>}
                  </td>
                  <td><ElegirProducto linea={l} onCambio={(id) => cambiar(i, { producto_id: id })} /></td>
                  {!esLista && <td><Entrada className="w-20 text-right" inputMode="decimal" value={l.cantidad ?? ""} onChange={(e) => cambiar(i, { cantidad: e.target.value === "" ? null : Number(e.target.value.replace(",", ".")) })} /></td>}
                  <td><Entrada className="w-24 text-right" inputMode="decimal" value={l.costo_unitario ?? ""} onChange={(e) => cambiar(i, { costo_unitario: e.target.value === "" ? null : Number(e.target.value.replace(",", ".")) })} /></td>
                  {!esLista && <td><Entrada className="w-24" value={l.lote ?? ""} onChange={(e) => cambiar(i, { lote: e.target.value || null })} /></td>}
                  {!esLista && <td><Entrada className="w-36" type="date" value={l.vencimiento ?? ""} onChange={(e) => cambiar(i, { vencimiento: e.target.value || null })} /></td>}
                </tr>
              ))}
            </Tabla>
          </div>
          <p className="mt-3 text-sm text-suave">{asignadas} de {lineas.length} líneas con producto. Las que quedan sin asignar no se cargan. Lo que corrijas se recuerda para la próxima factura de este proveedor.</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Boton variante="secundario" onClick={descartar}>Descartar</Boton>
            <Boton disabled={ocupado || !proveedor || asignadas === 0 || (!esLista && !ubicacion)} onClick={confirmar}>
              {esLista ? "Cargar costos" : "Recibir mercadería"}
            </Boton>
          </div>
        </Tarjeta>
      )}

      <Tarjeta titulo="Documentos leídos">
        {registros.length === 0 ? <Vacio titulo="Todavía no leíste documentos" /> : (
          <Tabla columnas={["Fecha", "Tipo", "Proveedor", "Número", "Estado"]}>
            {registros.map((r) => (
              <tr key={r.id}>
                <td className="whitespace-nowrap">{fechaHora(r.created_at)}</td>
                <td>{TIPOS.find((t) => t.id === r.tipo)?.nombre ?? r.tipo}</td>
                <td>{r.proveedor ?? "—"}</td>
                <td>{r.numero ?? "—"}</td>
                <td>{r.estado === "confirmado" ? r.mensaje ?? "Cargado" : <Etiqueta tono={r.estado === "leido" ? "alerta" : "gris"}>{r.estado === "leido" ? "Sin confirmar" : "Descartado"}</Etiqueta>}</td>
              </tr>
            ))}
          </Tabla>
        )}
      </Tarjeta>
    </div>
  );
}
