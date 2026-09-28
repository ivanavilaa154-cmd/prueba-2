"use client";
import { useCallback, useEffect, useState } from "react";
import { api, type Ubicacion } from "@/lib/api";
import { TIPO_UBICACION } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Campo, Entrada, Etiqueta, Selector, Tabla, Tarjeta, Vacio } from "@/components/ui";

const VACIA: Omit<Ubicacion, "id"> = { nombre: "", tipo: "venta", direccion: "", localidad: "", codigo_externo: "", activa: true };

export function Sucursales() {
  const { puede, recargar } = useSesion();
  const [lista, setLista] = useState<Ubicacion[] | null>(null);
  const [edicion, setEdicion] = useState<(Omit<Ubicacion, "id"> & { id?: number }) | null>(null);
  const [error, setError] = useState<string | null>(null);
  const editable = puede("gestionar_ubicaciones");

  const cargar = useCallback(() => api<Ubicacion[]>("/ubicaciones").then(setLista).catch((e) => setError(e.message)), []);
  useEffect(() => { void cargar(); }, [cargar]);

  async function guardar() {
    if (!edicion) return;
    setError(null);
    const { id, ...cuerpo } = edicion;
    try {
      await api(id ? `/ubicaciones/${id}` : "/ubicaciones", { metodo: id ? "PUT" : "POST", cuerpo: { ...cuerpo, horarios: {} } });
      setEdicion(null);
      await cargar();
      await recargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar.");
    }
  }

  return (
    <Tarjeta titulo="Sucursales y depósitos" accion={editable && !edicion && <Boton variante="secundario" onClick={() => setEdicion({ ...VACIA })}>Agregar</Boton>}>
      {error && <div className="mb-3"><Aviso tipo="error">{error}</Aviso></div>}
      {edicion && (
        <div className="mb-4 grid gap-3 rounded-lg border border-borde bg-panel-2 p-3 sm:grid-cols-2">
          <Campo etiqueta="Nombre"><Entrada value={edicion.nombre} onChange={(e) => setEdicion({ ...edicion, nombre: e.target.value })} autoFocus /></Campo>
          <Campo etiqueta="Tipo">
            <Selector value={edicion.tipo} onChange={(e) => setEdicion({ ...edicion, tipo: e.target.value as Ubicacion["tipo"] })}>
              {Object.entries(TIPO_UBICACION).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Selector>
          </Campo>
          <Campo etiqueta="Dirección"><Entrada value={edicion.direccion ?? ""} onChange={(e) => setEdicion({ ...edicion, direccion: e.target.value })} /></Campo>
          <Campo etiqueta="Localidad"><Entrada value={edicion.localidad ?? ""} onChange={(e) => setEdicion({ ...edicion, localidad: e.target.value })} /></Campo>
          <Campo etiqueta="Código en el sistema de caja" ayuda="Opcional. Se completa solo cuando conectes la caja y confirmes la detección.">
            <Entrada value={edicion.codigo_externo ?? ""} onChange={(e) => setEdicion({ ...edicion, codigo_externo: e.target.value })} />
          </Campo>
          <label className="flex items-center gap-2 self-end pb-2 text-sm">
            <input type="checkbox" checked={edicion.activa ?? true} onChange={(e) => setEdicion({ ...edicion, activa: e.target.checked })} /> Activa
          </label>
          <div className="flex gap-2 sm:col-span-2">
            <Boton onClick={guardar}>Guardar</Boton>
            <Boton variante="fantasma" onClick={() => setEdicion(null)}>Cancelar</Boton>
          </div>
        </div>
      )}
      {lista && lista.length === 0 && <Vacio titulo="Todavía no hay sucursales">Agregalas a mano o esperá a conectar tu sistema de caja: las detecta y te pide confirmarlas.</Vacio>}
      {lista && lista.length > 0 && (
        <Tabla columnas={["Nombre", "Tipo", "Dirección", "Estado", ""]}>
          {lista.map((u) => (
            <tr key={u.id}>
              <td className="font-medium">{u.nombre}</td>
              <td>{TIPO_UBICACION[u.tipo]}</td>
              <td className="text-suave">{[u.direccion, u.localidad].filter(Boolean).join(", ") || "—"}</td>
              <td>{u.activa ? <Etiqueta tono="ok">Activa</Etiqueta> : <Etiqueta>Inactiva</Etiqueta>}</td>
              <td className="text-right">{editable && <button className="text-acento underline" onClick={() => setEdicion({ ...u })}>Editar</button>}</td>
            </tr>
          ))}
        </Tabla>
      )}
      {!editable && <p className="mt-3 text-xs text-suave">Ves solo las sucursales que tenés asignadas.</p>}
    </Tarjeta>
  );
}
