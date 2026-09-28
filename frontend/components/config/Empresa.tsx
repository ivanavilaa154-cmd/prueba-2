"use client";
import { useState } from "react";
import { api, type Empresa as TEmpresa } from "@/lib/api";
import { fecha, MODELOS } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Campo, Entrada, Selector, Tarjeta } from "@/components/ui";

const ZONAS = ["America/Argentina/Buenos_Aires", "America/Argentina/Salta", "America/Argentina/Jujuy", "America/Argentina/Tucuman",
  "America/Argentina/Cordoba", "America/Argentina/Mendoza", "America/Montevideo"];

export function Empresa() {
  const { yo, recargar, puede } = useSesion();
  const [e, setE] = useState<TEmpresa>(yo.empresa!);
  const [mensaje, setMensaje] = useState<{ tipo: "ok" | "error"; texto: string } | null>(null);
  const editable = puede("configurar_empresa");

  async function guardar() {
    setMensaje(null);
    try {
      await api("/empresa", { metodo: "PUT", cuerpo: {
        nombre: e.nombre, cuit: e.cuit || null, zona_horaria: e.zona_horaria, moneda: e.moneda,
        modelo_abastecimiento: e.modelo_abastecimiento, consentimiento_datos: e.consentimiento_datos } });
      await recargar();
      setMensaje({ tipo: "ok", texto: "Cambios guardados." });
    } catch (err) {
      setMensaje({ tipo: "error", texto: err instanceof Error ? err.message : "No se pudo guardar." });
    }
  }

  return (
    <Tarjeta titulo="Empresa">
      <fieldset disabled={!editable} className="grid gap-4 sm:grid-cols-2">
        <Campo etiqueta="Nombre"><Entrada value={e.nombre} onChange={(x) => setE({ ...e, nombre: x.target.value })} /></Campo>
        <Campo etiqueta="CUIT"><Entrada value={e.cuit ?? ""} placeholder="30-12345678-9" onChange={(x) => setE({ ...e, cuit: x.target.value })} /></Campo>
        <Campo etiqueta="Zona horaria" ayuda="Todas las fechas y los cierres del día se calculan en esta zona.">
          <Selector value={e.zona_horaria} onChange={(x) => setE({ ...e, zona_horaria: x.target.value })}>
            {[...new Set([e.zona_horaria, ...ZONAS])].map((z) => <option key={z} value={z}>{z.replace("America/", "").replaceAll("_", " ")}</option>)}
          </Selector>
        </Campo>
        <Campo etiqueta="Moneda">
          <Selector value={e.moneda} onChange={(x) => setE({ ...e, moneda: x.target.value })}>
            <option value="ARS">Pesos argentinos (ARS)</option><option value="USD">Dólares (USD)</option><option value="UYU">Pesos uruguayos (UYU)</option>
          </Selector>
        </Campo>
        <div className="sm:col-span-2">
          <p className="mb-2 text-sm font-medium">Modelo de abastecimiento</p>
          <div className="grid gap-2 sm:grid-cols-3">
            {Object.entries(MODELOS).map(([clave, m]) => (
              <label key={clave} className={`cursor-pointer rounded-lg border p-3 text-sm ${e.modelo_abastecimiento === clave ? "border-acento bg-acento/5" : "border-borde"}`}>
                <input type="radio" name="modelo" className="mr-2" checked={e.modelo_abastecimiento === clave}
                  onChange={() => setE({ ...e, modelo_abastecimiento: clave as TEmpresa["modelo_abastecimiento"] })} />
                <strong>{m.nombre}</strong>
                <span className="mt-1 block text-suave">{m.explicacion}</span>
              </label>
            ))}
          </div>
          <p className="mt-2 text-xs text-suave">Se puede cambiar por sucursal, categoría o proveedor cuando se carguen las reglas de reposición (parte 9).</p>
        </div>
        <label className="flex items-start gap-2 text-sm sm:col-span-2">
          <input type="checkbox" className="mt-1" checked={e.consentimiento_datos} onChange={(x) => setE({ ...e, consentimiento_datos: x.target.checked })} />
          <span>
            Autorizo usar los datos de mi comercio, <strong>agregados y anónimos</strong>, en el panel para distribuidores y marcas (fase 3).
            Nunca se muestra un comercio individual ni zonas con menos de 5 comercios.
            {e.consentimiento_fecha && <span className="block text-xs text-suave">Autorizado el {fecha(e.consentimiento_fecha)}.</span>}
          </span>
        </label>
      </fieldset>
      {mensaje && <div className="mt-4"><Aviso tipo={mensaje.tipo}>{mensaje.texto}</Aviso></div>}
      {editable && <div className="mt-4"><Boton onClick={guardar}>Guardar cambios</Boton></div>}
    </Tarjeta>
  );
}
