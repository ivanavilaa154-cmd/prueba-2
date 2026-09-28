"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ROLES } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Campo, Entrada, Tarjeta } from "@/components/ui";

export function Cuenta() {
  const { yo, recargar } = useSesion();
  const [clave, setClave] = useState({ actual: "", nueva: "", repetida: "" });
  const [factor, setFactor] = useState<{ secreto: string; uri: string } | null>(null);
  const [codigo, setCodigo] = useState("");
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const [pref, setPref] = useState<{ resumen_diario: boolean; hora_resumen: number; urgentes_por_email: boolean } | null>(null);
  useEffect(() => { if (yo.empresa) api<typeof pref>("/yo/preferencias").then(setPref).catch(() => null); }, [yo.empresa]);

  async function correr(accion: () => Promise<unknown>, ok: string) {
    setMensaje(null);
    try {
      await accion();
      setMensaje({ tipo: "ok", texto: ok });
    } catch (e) {
      setMensaje({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo completar." });
    }
  }

  return (
    <Tarjeta titulo="Mi cuenta">
      <p className="text-sm">{yo.usuario.nombre} · {yo.usuario.email} · {yo.usuario.es_superadmin ? "Administración de la plataforma" : ROLES[yo.usuario.rol ?? ""]}</p>
      {mensaje && <div className="mt-3"><Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso></div>}
      {pref && (
        <div className="mt-4 grid gap-2 rounded-lg border border-borde p-3 text-sm">
          <h3 className="font-medium">Emails</h3>
          <label className="flex items-center gap-2"><input type="checkbox" checked={pref.resumen_diario} onChange={(e) => setPref({ ...pref, resumen_diario: e.target.checked })} />
            Recibir el resumen del día a las
            <select className="rounded border border-borde bg-panel px-1" value={pref.hora_resumen} onChange={(e) => setPref({ ...pref, hora_resumen: Number(e.target.value) })}>
              {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
            </select></label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={pref.urgentes_por_email} onChange={(e) => setPref({ ...pref, urgentes_por_email: e.target.checked })} />
            Recibir los avisos urgentes por email</label>
          <div><Boton variante="secundario" onClick={() => correr(() => api("/yo/preferencias", { metodo: "PUT", cuerpo: pref }), "Preferencias guardadas.")}>Guardar preferencias</Boton></div>
        </div>
      )}
      <div className="mt-4 grid gap-6 md:grid-cols-2">
        <form className="grid gap-3" onSubmit={(e) => { e.preventDefault();
          if (clave.nueva !== clave.repetida) { setMensaje({ tipo: "error", texto: "Las dos claves nuevas no coinciden." }); return; }
          void correr(async () => { await api("/yo/clave", { metodo: "POST", cuerpo: { actual: clave.actual, nueva: clave.nueva } }); setClave({ actual: "", nueva: "", repetida: "" }); }, "Clave cambiada."); }}>
          <h3 className="font-medium">Cambiar clave</h3>
          <Campo etiqueta="Clave actual"><Entrada type="password" autoComplete="current-password" value={clave.actual} onChange={(e) => setClave({ ...clave, actual: e.target.value })} /></Campo>
          <Campo etiqueta="Clave nueva" ayuda="Al menos 10 caracteres, combinando letras con números o símbolos.">
            <Entrada type="password" autoComplete="new-password" value={clave.nueva} onChange={(e) => setClave({ ...clave, nueva: e.target.value })} />
          </Campo>
          <Campo etiqueta="Repetí la clave nueva"><Entrada type="password" autoComplete="new-password" value={clave.repetida} onChange={(e) => setClave({ ...clave, repetida: e.target.value })} /></Campo>
          <Boton type="submit" disabled={!clave.actual || !clave.nueva}>Cambiar clave</Boton>
        </form>
        <div className="grid content-start gap-3">
          <h3 className="font-medium">Segundo factor</h3>
          {yo.usuario.segundo_factor ? (
            <>
              <p className="text-sm text-suave">Está activo: al ingresar te pedimos el código de la app de autenticación.</p>
              <Campo etiqueta="Código actual para desactivarlo"><Entrada inputMode="numeric" value={codigo} onChange={(e) => setCodigo(e.target.value)} /></Campo>
              <Boton variante="peligro" disabled={!codigo} onClick={() => correr(async () => { await api("/yo/segundo-factor", { metodo: "DELETE", cuerpo: { codigo } }); setCodigo(""); await recargar(); }, "Segundo factor desactivado.")}>Desactivar</Boton>
            </>
          ) : factor ? (
            <>
              <p className="text-sm">1. En la app de autenticación de tu celular (Google Authenticator, Microsoft Authenticator u otra) agregá una cuenta con esta clave:</p>
              <code className="break-all rounded-lg bg-panel-2 px-3 py-2 font-mono text-sm">{factor.secreto.match(/.{1,4}/g)?.join(" ")}</code>
              <p className="text-sm">2. Escribí el código de 6 dígitos que te muestra:</p>
              <Entrada inputMode="numeric" autoComplete="one-time-code" value={codigo} onChange={(e) => setCodigo(e.target.value)} />
              <Boton disabled={!codigo} onClick={() => correr(async () => { await api("/yo/segundo-factor", { metodo: "PUT", cuerpo: { secreto: factor.secreto, codigo } }); setFactor(null); setCodigo(""); await recargar(); }, "Segundo factor activado.")}>Activar</Boton>
            </>
          ) : (
            <>
              <p className="text-sm text-suave">Además de la clave, te pide un código del celular al ingresar. Recomendado para el dueño y el comprador.</p>
              <Boton variante="secundario" onClick={() => correr(async () => setFactor(await api("/yo/segundo-factor", { metodo: "POST" })), "Seguí los dos pasos.")}>Activar segundo factor</Boton>
            </>
          )}
        </div>
      </div>
    </Tarjeta>
  );
}
