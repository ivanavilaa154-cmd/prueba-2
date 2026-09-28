"use client";
import { useCallback, useEffect, useState } from "react";
import { api, BASE } from "@/lib/api";
import { fecha } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Campo, Entrada, Tabla, Tarjeta } from "@/components/ui";

type Fila = { id: number; nombre: string; cuit: string | null; plan: string; activa: boolean; created_at: string; ubicaciones: number; usuarios: number };

export default function Plataforma() {
  const { yo } = useSesion();
  const [lista, setLista] = useState<Fila[]>([]);
  const [nueva, setNueva] = useState({ nombre: "", cuit: "", email_dueno: "", nombre_dueno: "" });
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const cargar = useCallback(() => api<Fila[]>("/plataforma/empresas").then(setLista).catch((e) => setMensaje({ tipo: "error", texto: e.message })), []);
  useEffect(() => { if (yo.usuario.es_superadmin) void cargar(); }, [cargar, yo.usuario.es_superadmin]);

  if (!yo.usuario.es_superadmin) return <Aviso tipo="error">Esta pantalla es solo para la administración de la plataforma.</Aviso>;

  async function entrar(id: number) {
    await api("/plataforma/entrar", { metodo: "POST", cuerpo: { org_id: id } });
    location.href = `${BASE}/`;
  }
  async function crear() {
    setMensaje(null);
    try {
      const r = await api<{ clave_temporal_dueno: string }>("/plataforma/empresas", { metodo: "POST", cuerpo: { ...nueva, cuit: nueva.cuit || null } });
      setMensaje({ tipo: "ok", texto: `Empresa creada. Clave temporal de ${nueva.nombre_dueno} (${nueva.email_dueno}): ${r.clave_temporal_dueno} — se muestra una sola vez.` });
      setNueva({ nombre: "", cuit: "", email_dueno: "", nombre_dueno: "" });
      await cargar();
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo crear." });
    }
  }

  return (
    <div className="grid gap-4">
      <h1 className="text-2xl font-semibold">Plataforma</h1>
      {mensaje && <Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso>}
      <Tarjeta titulo="Empresas">
        <Tabla columnas={["Empresa", "Plan", "Sucursales", "Usuarios", "Alta", ""]}>
          {lista.map((e) => (
            <tr key={e.id}>
              <td><span className="font-medium">{e.nombre}</span><br /><span className="text-xs text-suave">{e.cuit ?? "Sin CUIT"}</span></td>
              <td>{e.plan}</td>
              <td className="cifra">{e.ubicaciones}</td>
              <td className="cifra">{e.usuarios}</td>
              <td className="text-suave">{fecha(e.created_at)}</td>
              <td className="text-right"><Boton variante="secundario" onClick={() => entrar(e.id)}>Entrar</Boton></td>
            </tr>
          ))}
        </Tabla>
      </Tarjeta>
      <Tarjeta titulo="Nueva empresa">
        <div className="grid gap-3 sm:grid-cols-2">
          <Campo etiqueta="Nombre del comercio"><Entrada value={nueva.nombre} onChange={(e) => setNueva({ ...nueva, nombre: e.target.value })} /></Campo>
          <Campo etiqueta="CUIT (opcional)"><Entrada value={nueva.cuit} onChange={(e) => setNueva({ ...nueva, cuit: e.target.value })} /></Campo>
          <Campo etiqueta="Nombre del dueño"><Entrada value={nueva.nombre_dueno} onChange={(e) => setNueva({ ...nueva, nombre_dueno: e.target.value })} /></Campo>
          <Campo etiqueta="Email del dueño"><Entrada type="email" value={nueva.email_dueno} onChange={(e) => setNueva({ ...nueva, email_dueno: e.target.value })} /></Campo>
        </div>
        <Boton className="mt-3" onClick={crear} disabled={!nueva.nombre || !nueva.email_dueno || !nueva.nombre_dueno}>Crear empresa</Boton>
      </Tarjeta>
    </div>
  );
}
