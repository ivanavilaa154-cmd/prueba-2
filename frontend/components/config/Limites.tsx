"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DOCUMENTOS, parsearMonto, pesos, ROLES } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Campo, ComoSeCalcula, Entrada, Selector, Tabla, Tarjeta } from "@/components/ui";

type Limite = { id: number; tipo_documento: string; rol: string | null; usuario_id: number | null; usuario: string | null; monto_maximo: string };

export function Limites() {
  const { yo } = useSesion();
  const [lista, setLista] = useState<Limite[]>([]);
  const [nuevo, setNuevo] = useState({ tipo_documento: "orden_compra", rol: "comprador", monto: "" });
  const [error, setError] = useState<string | null>(null);
  const cargar = useCallback(() => api<{ limites: Limite[] }>("/limites").then((d) => setLista(d.limites)).catch((e) => setError(e.message)), []);
  useEffect(() => { void cargar(); }, [cargar]);

  async function guardar() {
    setError(null);
    const monto = parsearMonto(nuevo.monto);
    try {
      await api("/limites", { metodo: "PUT", cuerpo: { tipo_documento: nuevo.tipo_documento, rol: nuevo.rol, monto_maximo: monto } });
      setNuevo({ ...nuevo, monto: "" });
      await cargar();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo guardar.");
    }
  }
  async function borrar(l: Limite) {
    await api(`/limites/${l.id}`, { metodo: "DELETE" }).catch((e) => setError(e.message));
    await cargar();
  }

  return (
    <Tarjeta titulo="Límites de aprobación">
      <p className="mb-3 text-sm text-suave">Hasta qué monto puede aprobar cada rol. Por encima, la aprobación pasa al dueño ({yo.empresa?.moneda}).</p>
      {error && <div className="mb-3"><Aviso tipo="error">{error}</Aviso></div>}
      <Tabla columnas={["Documento", "Para", "Hasta", ""]}>
        {lista.map((l) => (
          <tr key={l.id}>
            <td>{DOCUMENTOS[l.tipo_documento]}</td>
            <td>{l.rol ? ROLES[l.rol] : `${l.usuario} (solo esta persona)`}</td>
            <td className="cifra">{pesos(l.monto_maximo, yo.empresa?.moneda)}</td>
            <td className="text-right"><button className="text-peligro underline" onClick={() => borrar(l)}>Quitar</button></td>
          </tr>
        ))}
      </Tabla>
      <div className="mt-4 grid gap-3 sm:grid-cols-4 sm:items-end">
        <Campo etiqueta="Documento">
          <Selector value={nuevo.tipo_documento} onChange={(e) => setNuevo({ ...nuevo, tipo_documento: e.target.value })}>
            {Object.entries(DOCUMENTOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </Selector>
        </Campo>
        <Campo etiqueta="Rol">
          <Selector value={nuevo.rol} onChange={(e) => setNuevo({ ...nuevo, rol: e.target.value })}>
            {["comprador", "encargado", "cajero"].map((r) => <option key={r} value={r}>{ROLES[r]}</option>)}
          </Selector>
        </Campo>
        <Campo etiqueta="Monto máximo"><Entrada inputMode="decimal" placeholder="500.000,00" value={nuevo.monto} onChange={(e) => setNuevo({ ...nuevo, monto: e.target.value })} /></Campo>
        <Boton onClick={guardar} disabled={!nuevo.monto}>Guardar límite</Boton>
      </div>
      <div className="mt-4">
        <ComoSeCalcula>
          <p>Para aprobar un documento se usa primero el límite propio de la persona (si tiene uno) y si no, el de su rol.</p>
          <p>Si un rol no tiene límite cargado, no puede aprobar: el documento queda esperando al dueño. El dueño aprueba cualquier monto.</p>
          <p>Aunque una orden de compra quede aprobada sola por estar bajo el límite, el envío al proveedor siempre lo confirma una persona.</p>
        </ComoSeCalcula>
      </div>
    </Tarjeta>
  );
}
