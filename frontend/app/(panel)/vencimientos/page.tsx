"use client";
// Próximos a vencer y qué ofertar (sección 9): lotes que no llegan a venderse, descuento mínimo y seguimiento de las ofertas.
import { useCallback, useEffect, useState } from "react";
import { api, BASE } from "@/lib/api";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Indicador } from "@/components/Indicador";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, Boton, ComoSeCalcula, Etiqueta, Tabla, Tarjeta, Vacio } from "@/components/ui";
import { Liquidaciones } from "@/components/Liquidaciones";

type Oferta = { descuento: number | null; precio_oferta?: string; sin_oferta: string; con_oferta?: string; recuperable: string; texto: string };
type Lote = { producto_id: number; ubicacion_id: number; nombre: string; codigo_interno: string; ubicacion: string; lote: string; vencimiento: string; dias: number;
  tramo: string; cantidad: string; no_llegan: string; plata_en_riesgo: string; precio: string | null; en_oferta: boolean; oferta: Oferta | null };
type R = { lotes: Lote[]; tramos: { tramo: string; lotes: number; plata_en_riesgo: string }[]; plata_en_riesgo: string; recuperable: string; puede_ofertar: boolean };
type Seguimiento = { id: number; nombre: string; tipo: string; desde: string; hasta: string; origen: string; vigente: boolean; vendidas: string; plata_recuperada: string;
  parametros: { precio_oferta: string; precio_normal: string; unidades_objetivo: number | null } };

const ORIGEN: Record<string, string> = { vencimiento: "Por vencer", sobrestock: "Sobrestock", liquidacion: "Liquidación" };

export default function Vencimientos() {
  const { filtro } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [ofertas, setOfertas] = useState<Seguimiento[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [mensaje, setMensaje] = useState<string | null>(null);
  const [soloRiesgo, setSoloRiesgo] = useState(true);
  const ubic = filtro.ubicaciones.length ? `ubicaciones=${filtro.ubicaciones.join(",")}` : "";
  const cargar = useCallback(() => {
    api<R>(`/vencimientos?${ubic}`).then(setR).catch((e) => setError(e.message));
    api<Seguimiento[]>("/ofertas").then(setOfertas).catch(() => {});
  }, [ubic]);
  useEffect(() => { setR(null); cargar(); }, [cargar]);

  async function crear(l: Lote) {
    if (!l.oferta?.descuento) return;
    try {
      const o = await api<{ id: number; nombre: string }>("/ofertas", { metodo: "POST", cuerpo: {
        producto_id: l.producto_id, ubicacion_id: l.ubicacion_id, descuento: l.oferta.descuento, hasta: l.vencimiento, origen: "vencimiento",
        unidades_objetivo: Number(l.no_llegan), exhibicion: "puntera",
        escalera: [l.oferta.descuento + 0.15, l.oferta.descuento + 0.3].filter((x) => x < 0.8).map((x) => Math.round(x * 100) / 100) } });
      setMensaje(`Oferta creada: ${o.nombre}. Imprimí el cartel desde «Ofertas en curso».`);
      cargar();
    } catch (e) {
      setMensaje(e instanceof Error ? e.message : "No se pudo crear la oferta.");
    }
  }
  async function finalizar(id: number) {
    await api(`/ofertas/${id}/finalizar`, { metodo: "POST" }).catch(() => {});
    cargar();
  }
  const lotes = r ? r.lotes.filter((l) => !soloRiesgo || Number(l.no_llegan) > 0) : [];

  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Vencimientos y ofertas</h1>
        <p className="text-sm text-suave">Qué lotes no llegan a venderse antes de vencer, cuánta plata está en juego y la oferta mínima para rescatarla.</p>
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {mensaje && <Aviso tipo="ok">{mensaje}</Aviso>}
      {!r ? !error && <p className="text-sm text-suave">Cargando…</p> : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {r.tramos.slice(0, 3).map((t) => (
              <Indicador key={t.tramo} titulo={`Vencen en ${t.tramo}`} valor={plataCorta(t.plata_en_riesgo)} nota={`${numero(t.lotes)} lotes · plata en riesgo`} />
            ))}
            <Indicador titulo="Recuperable con ofertas" valor={plataCorta(r.recuperable)} nota="frente a no hacer nada" />
          </div>
          <Tarjeta titulo="Lotes próximos a vencer" accion={
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={soloRiesgo} onChange={(e) => setSoloRiesgo(e.target.checked)} /> Solo los que no llegan a venderse</label>}>
            <TablaDatos filas={lotes} idFila={(l) => `${l.producto_id}-${l.ubicacion_id}-${l.lote}`} nombreArchivo="vencimientos"
              vacio={<Vacio titulo="No hay lotes en riesgo">Los lotes con vencimiento se cargan al recibir mercadería o al importar el stock.</Vacio>}
              columnas={[
                { id: "prod", titulo: "Producto", valor: (l) => l.nombre, render: (l) => <span>{l.nombre}<span className="block text-xs text-suave">{l.ubicacion} · lote {l.lote}</span></span> },
                { id: "vence", titulo: "Vence", valor: (l) => l.dias, render: (l) => (
                  <span className="whitespace-nowrap">{fechaCorta(l.vencimiento)}<span className="block text-xs text-suave">{l.dias === 0 ? "hoy" : `en ${l.dias} días`}</span></span>) },
                { id: "cant", titulo: "Cantidad", valor: (l) => Number(l.cantidad), render: (l) => numero(l.cantidad), derecha: true },
                { id: "no", titulo: "No llegan", valor: (l) => Number(l.no_llegan), render: (l) => numero(l.no_llegan), derecha: true },
                { id: "riesgo", titulo: "Plata en riesgo", valor: (l) => Number(l.plata_en_riesgo), render: (l) => plata(l.plata_en_riesgo), derecha: true },
                { id: "oferta", titulo: "Qué ofertar", valor: (l) => l.oferta?.texto ?? "", render: (l) => !l.oferta ? "—" : (
                  <div className="grid max-w-xs gap-1 text-xs">
                    {l.oferta.descuento ? (
                      <>
                        <span><strong>{numero(l.oferta.descuento * 100)} % off</strong> → {plata(l.oferta.precio_oferta)}</span>
                        <span className="text-suave">Sin hacer nada cobrás {plata(l.oferta.sin_oferta)}; con la oferta, {plata(l.oferta.con_oferta)}.</span>
                        {l.en_oferta ? <Etiqueta tono="ok">✓ En oferta</Etiqueta> : r.puede_ofertar && <Boton variante="secundario" className="justify-self-start" onClick={() => crear(l)}>Crear oferta</Boton>}
                      </>
                    ) : <span>{l.oferta.texto}</span>}
                  </div>) },
              ]} />
            <div className="mt-3">
              <ComoSeCalcula>
                <p>Por lote, el que vence antes se vende primero: no llegan = cantidad − pronóstico de venta acumulado hasta el vencimiento (descontando lo que se llevan los lotes anteriores).</p>
                <p>Plata en riesgo = unidades que no llegan × costo.</p>
                <p>Descuento mínimo: el menor de la escala (10 % vende 1,3 veces más, 20 % → 1,7, 30 % → 2,2, 40 % → 2,8, 50 % → 3,5) con el que se vende todo el lote antes de vencer.</p>
              </ComoSeCalcula>
            </div>
          </Tarjeta>
          <Liquidaciones />
          <Tarjeta titulo="Ofertas en curso y resultado">
            {ofertas.length === 0 ? <Vacio titulo="Todavía no hay ofertas">Creá una desde la lista de arriba o desde Plata parada.</Vacio> : (
              <Tabla columnas={["Oferta", "Motivo", "Vigencia", "Vendidas", "Plata recuperada", ""]}>
                {ofertas.map((o) => (
                  <tr key={o.id} className="align-top">
                    <td>{o.nombre}<span className="block text-xs text-suave">{plata(o.parametros.precio_normal)} → {plata(o.parametros.precio_oferta)}</span></td>
                    <td>{ORIGEN[o.origen] ?? o.origen}</td>
                    <td className="whitespace-nowrap">{fechaCorta(o.desde)} a {fechaCorta(o.hasta)}{!o.vigente && <span className="block text-xs text-suave">Terminada</span>}</td>
                    <td className="text-right">{numero(o.vendidas)}{o.parametros.unidades_objetivo ? <span className="block text-xs text-suave">de {numero(o.parametros.unidades_objetivo)}</span> : null}</td>
                    <td className="text-right">{plata(o.plata_recuperada)}</td>
                    <td>
                      <div className="flex flex-wrap gap-2 text-sm">
                        <a className="text-acento underline" href={`${BASE}/api/ofertas/${o.id}/cartel?tamano=a5`} target="_blank" rel="noreferrer">Cartel A5</a>
                        <a className="text-acento underline" href={`${BASE}/api/ofertas/${o.id}/cartel?tamano=a6`} target="_blank" rel="noreferrer">A6</a>
                        {o.vigente && r.puede_ofertar && <button className="text-suave underline" onClick={() => finalizar(o.id)}>Terminar</button>}
                      </div>
                    </td>
                  </tr>
                ))}
              </Tabla>
            )}
          </Tarjeta>
        </>
      )}
    </div>
  );
}
