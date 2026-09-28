"use client";
import { useState, type FormEvent } from "react";
import { api, BASE } from "@/lib/api";
import { Aviso, Boton, Campo, Entrada } from "@/components/ui";

export default function Ingresar() {
  const [email, setEmail] = useState("");
  const [clave, setClave] = useState("");
  const [codigo, setCodigo] = useState("");
  const [paso, setPaso] = useState<"clave" | "codigo">("clave");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  async function enviar(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setEnviando(true);
    try {
      if (paso === "clave") {
        const r = await api<{ requiere_segundo_factor: boolean }>("/sesion", { metodo: "POST", cuerpo: { email, clave } });
        if (r.requiere_segundo_factor) {
          setPaso("codigo");
          return;
        }
      } else {
        await api("/sesion/segundo-factor", { metodo: "POST", cuerpo: { codigo } });
      }
      location.href = `${BASE}/`;
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo ingresar.");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <form onSubmit={enviar} className="grid w-full max-w-sm gap-4 rounded-2xl border border-borde bg-panel p-6 shadow-sm">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-suave">Retail IA</p>
          <h1 className="text-xl font-semibold">{paso === "clave" ? "Ingresá a tu comercio" : "Segundo factor"}</h1>
        </div>
        {error && <Aviso tipo="error">{error}</Aviso>}
        {paso === "clave" ? (
          <>
            <Campo etiqueta="Email">
              <Entrada type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
            </Campo>
            <Campo etiqueta="Clave">
              <Entrada type="password" autoComplete="current-password" required value={clave} onChange={(e) => setClave(e.target.value)} />
            </Campo>
          </>
        ) : (
          <Campo etiqueta="Código de 6 dígitos" ayuda="Lo ves en la app de autenticación de tu celular.">
            <Entrada inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" required value={codigo}
              onChange={(e) => setCodigo(e.target.value)} autoFocus />
          </Campo>
        )}
        <Boton type="submit" disabled={enviando}>{enviando ? "Ingresando…" : paso === "clave" ? "Ingresar" : "Confirmar"}</Boton>
        <p className="text-center text-xs text-suave">¿Te olvidaste la clave? Pedile al dueño de tu comercio que te genere una nueva.</p>
      </form>
    </main>
  );
}
