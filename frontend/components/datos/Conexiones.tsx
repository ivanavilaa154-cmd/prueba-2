"use client";
// Conexión con Odoo Punto de Venta: credenciales (la API key se guarda cifrada), detección de almacenes y cajas, sincronización.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaHora, numero } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Campo, Entrada, Etiqueta, Selector, Tabla, Tarjeta } from "@/components/ui";

type Conexion = { id: number; nombre: string; activa: boolean; config: { url: string; base: string; usuario: string; almacenes?: Record<string, number> };
  ultima_sincronizacion: string | null; sincronizado_hasta: string | null; estado_sincronizacion: string | null; error_sincronizacion: string | null; tiene_clave: boolean };
type Deteccion = { version: string; almacenes: { id: number; nombre: string; codigo: string | null; ubicacion_sugerida: number | null }[];
  cajas: { id: number; nombre: string; almacen_id: number | null }[]; conteos: { tickets: number; productos: number } };

const ESTADOS: Record<string, { texto: string; tono: "ok" | "alerta" | "peligro" | "gris" }> = {
  ok: { texto: "✓ Sincronizada", tono: "ok" },
  sincronizando: { texto: "⟳ Sincronizando…", tono: "alerta" },
  error: { texto: "✕ Con error", tono: "peligro" },
  sin_probar: { texto: "Sin sincronizar", tono: "gris" },
};

export function Conexiones() {
  const { yo } = useSesion();
  const [lista, setLista] = useState<Conexion[]>([]);
  const [editando, setEditando] = useState<number | null>(null);
  const [form, setForm] = useState({ url: "", base: "", usuario: "", api_key: "" });
  const [deteccion, setDeteccion] = useState<Deteccion | null>(null);
  const [almacenes, setAlmacenes] = useState<Record<number, number | "">>({});
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const activas = lista.filter((c) => c.activa);

  const cargar = useCallback(() => api<Conexion[]>("/conexiones").then(setLista).catch(() => {}), []);
  useEffect(() => { cargar(); }, [cargar]);
  useEffect(() => {        // mientras sincroniza, refrescar el estado
    if (!lista.some((c) => c.estado_sincronizacion === "sincronizando")) return;
    const t = setInterval(cargar, 4000);
    return () => clearInterval(t);
  }, [lista, cargar]);

  const consulta = editando ? `?plataforma_id=${editando}` : "";
  async function probar() {
    setOcupado(true);
    setMensaje(null);
    try {
      const d = await api<Deteccion>(`/conexiones/odoo/probar${consulta}`, { metodo: "POST", cuerpo: { ...form, api_key: form.api_key || null } });
      setDeteccion(d);
      const guardados = lista.find((c) => c.id === editando)?.config.almacenes ?? {};
      setAlmacenes(Object.fromEntries(d.almacenes.map((a) => [a.id, guardados[String(a.id)] ?? a.ubicacion_sugerida ?? ""])));
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo conectar." });
    } finally {
      setOcupado(false);
    }
  }
  async function guardar() {
    setOcupado(true);
    try {
      const r = await api<{ id: number }>(`/conexiones/odoo${consulta}`, { metodo: "POST",
        cuerpo: { ...form, api_key: form.api_key || null, almacenes: Object.fromEntries(Object.entries(almacenes).map(([k, v]) => [k, v || null])) } });
      await api(`/conexiones/${r.id}/sincronizar`, { metodo: "POST" });
      setMensaje({ tipo: "ok", texto: "Conexión guardada. Empezó la sincronización: la primera vez trae el último año de tickets y puede tardar unos minutos." });
      setDeteccion(null);
      setEditando(null);
      setForm({ url: "", base: "", usuario: "", api_key: "" });
      cargar();
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo guardar." });
    } finally {
      setOcupado(false);
    }
  }
  async function sincronizar(id: number) {
    const r = await api<{ mensaje: string }>(`/conexiones/${id}/sincronizar`, { metodo: "POST" }).catch((e) => ({ mensaje: e.message }));
    setMensaje({ tipo: "ok", texto: r.mensaje });
    cargar();
  }
  async function desconectar(id: number) {
    if (!confirm("¿Desconectar Odoo? Se borra la clave guardada; lo ya sincronizado queda.")) return;
    await api(`/conexiones/${id}`, { metodo: "DELETE" });
    cargar();
  }
  function editar(c: Conexion) {
    setEditando(c.id);
    setForm({ url: c.config.url, base: c.config.base, usuario: c.config.usuario, api_key: "" });
    setDeteccion(null);
  }
  const listo = form.url && form.base && form.usuario && (form.api_key || editando);

  return (
    <div className="grid grid-cols-1 gap-4">
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
      {activas.length > 0 && (
        <Tarjeta titulo="Cajas conectadas">
          <Tabla columnas={["Conexión", "Estado", "Última sincronización", ""]}>
            {activas.map((c) => {
              const e = ESTADOS[c.estado_sincronizacion ?? "sin_probar"] ?? ESTADOS.sin_probar;
              return (
                <tr key={c.id} className="align-top">
                  <td>{c.nombre}<div className="text-xs text-suave">{c.config.url}</div></td>
                  <td><Etiqueta tono={e.tono}>{e.texto}</Etiqueta>{c.error_sincronizacion && <div className="mt-1 max-w-xs text-xs text-peligro">{c.error_sincronizacion}</div>}</td>
                  <td className="whitespace-nowrap">{c.ultima_sincronizacion ? fechaHora(c.ultima_sincronizacion) : "—"}
                    {c.sincronizado_hasta && <div className="text-xs text-suave">tickets hasta {fechaHora(c.sincronizado_hasta)}</div>}</td>
                  <td>
                    <div className="flex flex-wrap gap-2">
                      <Boton variante="secundario" disabled={c.estado_sincronizacion === "sincronizando"} onClick={() => sincronizar(c.id)}>Sincronizar ahora</Boton>
                      <Boton variante="fantasma" onClick={() => editar(c)}>Editar</Boton>
                      <Boton variante="peligro" onClick={() => desconectar(c.id)}>Desconectar</Boton>
                    </div>
                  </td>
                </tr>
              );
            })}
          </Tabla>
          <p className="mt-3 text-sm text-suave">Se sincroniza sola cada hora. Solo lectura: la plataforma nunca modifica nada en Odoo.</p>
        </Tarjeta>
      )}

      <Tarjeta titulo={editando ? "Editar conexión con Odoo" : "Conectar Odoo Punto de Venta"}>
        <p className="mb-3 text-sm text-suave">
          En Odoo: tu usuario → Preferencias → Seguridad de la cuenta → Nueva clave API. Usá un usuario con los roles Punto de Venta: Usuario e Inventario: Usuario.
          La clave se guarda cifrada y no se vuelve a mostrar.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Campo etiqueta="URL de Odoo"><Entrada placeholder="https://tuempresa.odoo.com" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} /></Campo>
          <Campo etiqueta="Base de datos"><Entrada value={form.base} onChange={(e) => setForm({ ...form, base: e.target.value })} /></Campo>
          <Campo etiqueta="Usuario (email)"><Entrada type="email" autoComplete="off" value={form.usuario} onChange={(e) => setForm({ ...form, usuario: e.target.value })} /></Campo>
          <Campo etiqueta="Clave API" ayuda={editando ? "Dejala vacía para mantener la guardada." : undefined}>
            <Entrada type="password" autoComplete="new-password" value={form.api_key} onChange={(e) => setForm({ ...form, api_key: e.target.value })} />
          </Campo>
        </div>
        <div className="mt-4 flex gap-2">
          {editando && <Boton variante="secundario" onClick={() => { setEditando(null); setDeteccion(null); }}>Cancelar</Boton>}
          <Boton disabled={!listo || ocupado} onClick={probar}>{ocupado && !deteccion ? "Probando…" : "Probar conexión"}</Boton>
        </div>

        {deteccion && (
          <div className="mt-5 grid gap-3">
            <Aviso tipo="ok">Conectado a Odoo {deteccion.version}: {numero(deteccion.conteos.tickets)} tickets y {numero(deteccion.conteos.productos)} productos a la venta.</Aviso>
            <h3 className="text-sm font-medium">¿A qué sucursal corresponde cada almacén de Odoo?</h3>
            <Tabla columnas={["Almacén en Odoo", "Cajas", "Sucursal"]}>
              {deteccion.almacenes.map((a) => (
                <tr key={a.id}>
                  <td>{a.nombre}{a.codigo && <span className="text-suave"> · {a.codigo}</span>}</td>
                  <td className="text-sm">{deteccion.cajas.filter((x) => x.almacen_id === a.id).map((x) => x.nombre).join(", ") || "—"}</td>
                  <td>
                    <Selector className="w-56" value={almacenes[a.id] ?? ""} onChange={(e) => setAlmacenes({ ...almacenes, [a.id]: e.target.value ? Number(e.target.value) : "" })}>
                      <option value="">No sincronizar</option>
                      {yo?.ubicaciones.map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
                    </Selector>
                  </td>
                </tr>
              ))}
            </Tabla>
            <div><Boton disabled={ocupado || !Object.values(almacenes).some(Boolean)} onClick={guardar}>Confirmar y sincronizar</Boton></div>
          </div>
        )}
      </Tarjeta>
    </div>
  );
}
