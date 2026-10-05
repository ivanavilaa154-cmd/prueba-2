"use client";
// Calidad de datos (SPEC v2, sección 5.6): qué tan confiables son los datos antes de seguir las recomendaciones, qué corregir y
// el resumen comercial («perdiste $X en faltantes y tenés $Y parados»).
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fecha, numero, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, ComoSeCalcula, Etiqueta, Tarjeta, Vacio } from "@/components/ui";

type Problema = { codigo: string; titulo: string; explicacion: string; accion: string; grave: boolean; cantidad: number; venta_90_dias: string;
  productos: { id: number; nombre: string; codigo: string }[] };
type Detalle = { fecha: string; puntaje: string; productos: number; problemas: Problema[]; comercial: { faltantes_90_dias: string; plata_parada: string } };
type R = { ultimo: { fecha: string; puntaje: string; detalle: Detalle; origen: string } | null; historia: { fecha: string; puntaje: string }[];
  confianza: Record<string, number> };
const DONDE: Record<string, string> = { duplicado: "/datos/#catalogo", sin_categoria: "/datos/#catalogo", conversion_dudosa: "/configuracion/#impuestos",
  sin_costo: "/datos/#documentos", costo_viejo: "/datos/#documentos", compras_no_registradas: "/datos/#documentos", stock_negativo: "/comprar/" };

export default function Calidad() {
  const { puede } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [abierto, setAbierto] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cargar = () => api<R>("/calidad").then(setR).catch((e) => setError(e.message));
  useEffect(() => { cargar(); }, []);
  async function revisar() {
    setOcupado(true);
    try { await api("/calidad/revisar", { metodo: "POST" }); await cargar(); } catch (e) { setError(e instanceof Error ? e.message : "No se pudo revisar."); }
    setOcupado(false);
  }
  const d = r?.ultimo?.detalle;
  const puntaje = d ? Number(d.puntaje) : null;
  const tono = puntaje === null ? "gris" : puntaje >= 85 ? "ok" : puntaje >= 65 ? "alerta" : "peligro";
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">Calidad de datos</h1>
          <p className="text-sm text-suave">Qué tan confiables son tus datos y qué corregir para que las recomendaciones acierten. Se revisa al conectar y cada semana.</p>
        </div>
        {puede("importar_datos") && <Boton disabled={ocupado} onClick={revisar}>{ocupado ? "Revisando…" : "Revisar ahora"}</Boton>}
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {!r ? <p className="text-sm text-suave">Cargando…</p> : !d ? (
        <Vacio titulo="Todavía no hay diagnóstico">Se hace solo al conectar tus datos, o tocá «Revisar ahora».</Vacio>
      ) : <>
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="rounded-xl border border-borde bg-panel p-4">
            <p className="text-sm text-suave">Puntaje</p>
            <p className="mt-1 text-3xl font-semibold">{numero(puntaje!, 0)} <span className="text-base text-suave">/ 100</span></p>
            <Etiqueta tono={tono}>{tono === "ok" ? "✓ Datos confiables" : tono === "alerta" ? "▲ Revisar" : "● Muchos problemas"}</Etiqueta>
          </div>
          <div className="rounded-xl border border-borde bg-panel p-4">
            <p className="text-sm text-suave">Productos con confianza baja</p>
            <p className="mt-1 text-2xl font-semibold">{numero(r.confianza.baja ?? 0)}</p>
            <p className="text-xs text-suave">de {numero(d.productos)} · media: {numero(r.confianza.media ?? 0)}</p>
          </div>
          <div className="rounded-xl border border-borde bg-panel p-4">
            <p className="text-sm text-suave">Perdiste en faltantes (90 días)</p>
            <p className="mt-1 text-2xl font-semibold">{plataCorta(d.comercial.faltantes_90_dias)}</p>
            <p className="text-xs text-suave">días sin stock × lo que se vende por día</p>
          </div>
          <div className="rounded-xl border border-borde bg-panel p-4">
            <p className="text-sm text-suave">Tenés parado</p>
            <p className="mt-1 text-2xl font-semibold">{plataCorta(d.comercial.plata_parada)}</p>
            <p className="text-xs text-suave">sobrestock y stock sin venta en 90 días</p>
          </div>
        </div>
        <p className="text-xs text-suave">Revisado el {fecha(d.fecha)}{r.historia.length > 1 && ` · antes: ${r.historia.slice(0, -1).map((h) => `${fecha(h.fecha)} ${numero(Number(h.puntaje))}`).join(" · ")}`}</p>
        {d.problemas.length === 0 ? <Aviso tipo="ok">No se encontraron problemas.</Aviso> : (
          <div className="grid gap-3">
            {d.problemas.map((p) => (
              <Tarjeta key={p.codigo} titulo={<span className="flex flex-wrap items-center gap-2">{p.titulo}
                <Etiqueta tono={p.grave ? "peligro" : "alerta"}>{p.grave ? "● Grave" : "▲ A revisar"}</Etiqueta>
                <span className="text-sm font-normal text-suave">{numero(p.cantidad)} productos · venden {plataCorta(p.venta_90_dias)} en 90 días</span></span>}
                accion={DONDE[p.codigo] ? <Link className="text-sm text-acento underline" href={DONDE[p.codigo]}>Corregir</Link> : null}>
                <p className="text-sm">{p.explicacion}</p>
                <p className="mt-1 text-sm text-suave">Qué hacer: {p.accion}</p>
                <button className="mt-2 text-sm text-acento underline" onClick={() => setAbierto(abierto === p.codigo ? null : p.codigo)}>
                  {abierto === p.codigo ? "Ocultar productos" : "Ver productos"}</button>
                {abierto === p.codigo && (
                  <ul className="mt-2 grid gap-1 text-sm sm:grid-cols-2">{p.productos.map((x) => <li key={x.id}>{x.nombre} <span className="text-suave">· {x.codigo}</span></li>)}</ul>
                )}
              </Tarjeta>
            ))}
          </div>
        )}
      </>}
      <ComoSeCalcula>
        <p>Puntaje = 100 × (1 − peso de los productos con problemas), donde cada producto pesa lo que vendió en 90 días (más un mínimo para los que no venden).
          Un problema grave (stock negativo, stock que no se mueve, compras sin cargar, sin costo o unidad dudosa) cuenta entero; uno a revisar, la mitad.</p>
        <p>Cada producto queda con confianza alta, media o baja, que se muestra junto a sus recomendaciones en Comprar y reponer.</p>
      </ComoSeCalcula>
    </div>
  );
}
