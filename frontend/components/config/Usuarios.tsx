"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fechaHora, ROLES } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Campo, Entrada, Etiqueta, Selector, Tabla, Tarjeta } from "@/components/ui";

type Usuario = { id: number; email: string; nombre: string; rol: string; activo: boolean; ultimo_ingreso: string | null;
  segundo_factor: boolean; bloqueado: boolean | null; ubicaciones: number[]; vendedor_id: number | null };
type Edicion = { id?: number; email: string; nombre: string; rol: string; activo: boolean; ubicaciones: number[]; vendedor_id?: number | null };
const DEL_DISTRIBUIDOR = ["jefe_ventas", "vendedor", "cobranzas"];
const CON_SUCURSAL = ["encargado", "cajero"];

export function Usuarios() {
  const { yo } = useSesion();
  const [lista, setLista] = useState<Usuario[]>([]);
  const [vendedores, setVendedores] = useState<{ id: number; nombre: string; zona: string | null }[]>([]);
  const distribuidor = (yo.empresa?.modos ?? []).includes("distribuidor");
  const [edicion, setEdicion] = useState<Edicion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [claveNueva, setClaveNueva] = useState<{ nombre: string; clave: string } | null>(null);
  const nombreUbic = (id: number) => yo.ubicaciones.find((u) => u.id === id)?.nombre ?? `#${id}`;

  const cargar = useCallback(() => api<{ usuarios: Usuario[]; vendedores: { id: number; nombre: string; zona: string | null }[] }>("/usuarios")
    .then((d) => { setLista(d.usuarios); setVendedores(d.vendedores ?? []); }).catch((e) => setError(e.message)), []);
  useEffect(() => { void cargar(); }, [cargar]);

  async function guardar() {
    if (!edicion) return;
    setError(null);
    try {
      if (edicion.id) {
        await api(`/usuarios/${edicion.id}`, { metodo: "PUT", cuerpo: { nombre: edicion.nombre, rol: edicion.rol, activo: edicion.activo, ubicaciones: edicion.ubicaciones, vendedor_id: edicion.vendedor_id ?? null } });
      } else {
        const r = await api<{ clave_temporal: string }>("/usuarios", { metodo: "POST", cuerpo: { email: edicion.email, nombre: edicion.nombre, rol: edicion.rol, ubicaciones: edicion.ubicaciones, vendedor_id: edicion.vendedor_id ?? null } });
        setClaveNueva({ nombre: edicion.nombre, clave: r.clave_temporal });
      }
      setEdicion(null);
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar.");
    }
  }

  async function blanquear(u: Usuario) {
    if (!confirm(`¿Generar una clave nueva para ${u.nombre}? Se cierran sus sesiones abiertas.`)) return;
    try {
      const r = await api<{ clave_temporal: string }>(`/usuarios/${u.id}/clave`, { metodo: "POST" });
      setClaveNueva({ nombre: u.nombre, clave: r.clave_temporal });
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo generar.");
    }
  }

  function alternarUbicacion(id: number) {
    if (!edicion) return;
    const s = new Set(edicion.ubicaciones);
    if (s.has(id)) s.delete(id); else s.add(id);
    setEdicion({ ...edicion, ubicaciones: [...s] });
  }

  return (
    <Tarjeta titulo="Usuarios" accion={!edicion && <Boton variante="secundario" onClick={() => setEdicion({ email: "", nombre: "", rol: "encargado", activo: true, ubicaciones: [] })}>Agregar usuario</Boton>}>
      {error && <div className="mb-3"><Aviso tipo="error">{error}</Aviso></div>}
      {claveNueva && (
        <div className="mb-3">
          <Aviso tipo="ok">
            Clave temporal de <strong>{claveNueva.nombre}</strong>: <code className="rounded bg-panel px-1.5 py-0.5 font-mono">{claveNueva.clave}</code>.
            Pasásela por un medio privado; se muestra una sola vez. Puede cambiarla desde «Mi cuenta».
            <button className="ml-2 underline" onClick={() => setClaveNueva(null)}>Listo</button>
          </Aviso>
        </div>
      )}
      {edicion && (
        <div className="mb-4 grid gap-3 rounded-lg border border-borde bg-panel-2 p-3 sm:grid-cols-2">
          <Campo etiqueta="Nombre"><Entrada value={edicion.nombre} onChange={(e) => setEdicion({ ...edicion, nombre: e.target.value })} autoFocus /></Campo>
          <Campo etiqueta="Email"><Entrada type="email" disabled={!!edicion.id} value={edicion.email} onChange={(e) => setEdicion({ ...edicion, email: e.target.value })} /></Campo>
          <Campo etiqueta="Rol">
            <Selector value={edicion.rol} onChange={(e) => setEdicion({ ...edicion, rol: e.target.value })}>
              {Object.entries(ROLES).filter(([k]) => distribuidor || !DEL_DISTRIBUIDOR.includes(k)).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Selector>
          </Campo>
          {edicion.id && (
            <label className="flex items-center gap-2 self-end pb-2 text-sm">
              <input type="checkbox" checked={edicion.activo} onChange={(e) => setEdicion({ ...edicion, activo: e.target.checked })} /> Activo
            </label>
          )}
          {edicion.rol === "vendedor" ? (
            <Campo etiqueta="Ficha del vendedor" ayuda="Ve solo los clientes de esta ficha (su cartera).">
              <Selector value={edicion.vendedor_id ?? ""} onChange={(e) => setEdicion({ ...edicion, vendedor_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">Elegí…</option>
                {vendedores.map((v) => <option key={v.id} value={v.id}>{v.nombre}{v.zona ? ` · ${v.zona}` : ""}</option>)}
              </Selector>
            </Campo>
          ) : CON_SUCURSAL.includes(edicion.rol) ? (
            <fieldset className="sm:col-span-2">
              <legend className="mb-1 text-sm font-medium">Sucursales que ve</legend>
              <div className="flex flex-wrap gap-2">
                {yo.ubicaciones.map((u) => (
                  <label key={u.id} className="flex items-center gap-1.5 rounded-lg border border-borde bg-panel px-2.5 py-1.5 text-sm">
                    <input type="checkbox" checked={edicion.ubicaciones.includes(u.id)} onChange={() => alternarUbicacion(u.id)} /> {u.nombre}
                  </label>
                ))}
              </div>
            </fieldset>
          ) : (
            <p className="text-sm text-suave sm:col-span-2">{edicion.rol === "distribuidor" ? "Este rol solo verá el panel agregado y anónimo (fase 3)."
              : edicion.rol === "cobranzas" ? "Ve las cuentas corrientes y la deuda de todos los clientes." : edicion.rol === "jefe_ventas" ? "Ve a todos los vendedores, clientes y cuentas corrientes."
              : "Este rol ve todas las sucursales de la empresa."}</p>
          )}
          <div className="flex gap-2 sm:col-span-2">
            <Boton onClick={guardar}>{edicion.id ? "Guardar" : "Crear y generar clave"}</Boton>
            <Boton variante="fantasma" onClick={() => setEdicion(null)}>Cancelar</Boton>
          </div>
        </div>
      )}
      <Tabla columnas={["Nombre", "Rol", "Sucursales", "Último ingreso", ""]}>
        {lista.map((u) => (
          <tr key={u.id} className={u.activo ? "" : "opacity-60"}>
            <td><span className="font-medium">{u.nombre}</span><br /><span className="text-xs text-suave">{u.email}</span></td>
            <td>
              {ROLES[u.rol]}
              <span className="ml-1 inline-flex gap-1">
                {!u.activo && <Etiqueta>Inactivo</Etiqueta>}
                {u.bloqueado && <Etiqueta tono="peligro">Bloqueado</Etiqueta>}
                {u.segundo_factor && <Etiqueta tono="acento">2FA</Etiqueta>}
              </span>
            </td>
            <td className="text-suave">{CON_SUCURSAL.includes(u.rol) ? u.ubicaciones.map(nombreUbic).join(", ") : "Todas"}</td>
            <td className="text-suave">{fechaHora(u.ultimo_ingreso)}</td>
            <td className="whitespace-nowrap text-right">
              <button className="text-acento underline" onClick={() => setEdicion({ ...u })}>Editar</button>
              <button className="ml-3 text-acento underline" onClick={() => blanquear(u)}>Clave nueva</button>
            </td>
          </tr>
        ))}
      </Tabla>
    </Tarjeta>
  );
}
