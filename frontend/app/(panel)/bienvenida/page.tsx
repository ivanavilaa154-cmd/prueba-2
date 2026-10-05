"use client";
// Primer ingreso guiado (SPEC v2, sección 15): seis pasos, de a uno, con lo que falta en cada uno y el botón para hacerlo.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Etiqueta, Tarjeta, cx } from "@/components/ui";

type Paso = { paso: string; titulo: string; listo: boolean; confirmado: string | null; detalle: string; ir: string; accion: string; se_confirma: boolean };
type PrimerIngreso = { pasos: Paso[]; listos: number; total: number; actual: string | null; completo_at: string | null; omitido: boolean; mostrar: boolean };

const AYUDA: Record<string, string> = {
  datos: "Una sola conexión alcanza: Odoo trae ventas, productos y stock (y en modo distribuidor, clientes, pedidos y cuenta corriente). Si tu caja no tiene internet, instalá el agente en la PC del local.",
  sucursales: "Cada sucursal y depósito con su nombre real. Las recomendaciones de compra y las transferencias se calculan por sucursal.",
  productos: "Vincular tus productos al catálogo maestro permite comparar precios y detectar duplicados. Lo seguro se vincula solo; lo dudoso lo confirmás vos una vez.",
  proveedores: "Con el día de visita, la demora y el pedido mínimo de cada proveedor se calcula cuándo pedir y cuánto, para no quedarte sin stock ni comprar de más.",
  modelo: "Centralizado: compra el depósito y reparte. Descentralizado: cada sucursal compra. Mixto: según el proveedor. Los márgenes objetivo guían la remarcación.",
  recomendaciones: "Empezá por lo que está en rojo: productos que se agotan antes de que llegue el próximo pedido. Cada número tiene su «¿cómo se calcula?».",
};

export default function Bienvenida() {
  const { yo, puede } = useSesion();
  const [r, setR] = useState<PrimerIngreso | null>(null);
  const [elegido, setElegido] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cargar = useCallback(() => api<PrimerIngreso>("/primer-ingreso").then((x) => { setR(x); setElegido((e) => e ?? x.actual ?? x.pasos[0].paso); })
    .catch((e) => setError(e.message)), []);
  useEffect(() => { if (puede("configurar_empresa")) cargar(); }, [cargar, puede]);
  if (!puede("configurar_empresa")) return <Aviso tipo="info">La puesta en marcha la hace el dueño de la empresa.</Aviso>;
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;

  async function confirmar(paso: string) {
    try {
      const x = await api<PrimerIngreso>(`/primer-ingreso/${paso}`, { metodo: "POST" });
      setR(x);
      setElegido(x.actual ?? paso);
    } catch (e) { setError(e instanceof Error ? e.message : "No se pudo guardar."); }
  }
  async function omitir() {
    await api("/primer-ingreso", { metodo: "PUT", cuerpo: { omitir: true } });
    location.href = location.pathname.replace(/bienvenida\/?$/, "");
  }
  const i = r.pasos.findIndex((p) => p.paso === elegido);
  const p = r.pasos[i];
  return (
    <div className="mx-auto grid w-full max-w-3xl gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Bienvenido a {yo.empresa?.nombre}</h1>
        <p className="text-sm text-suave">Seis pasos para que las recomendaciones usen tus datos reales. Podés dejar alguno para después.</p>
      </div>
      {r.completo_at && <Aviso tipo="ok">¡Listo! La puesta en marcha está completa. <Link className="underline" href="/">Ir al inicio</Link></Aviso>}
      <div className="h-2 rounded-full bg-panel-2" role="progressbar" aria-valuenow={r.listos} aria-valuemin={0} aria-valuemax={r.total} aria-label="Avance">
        <div className="h-2 rounded-full bg-acento" style={{ width: `${(r.listos / r.total) * 100}%` }} />
      </div>
      <ol className="grid grid-cols-3 gap-2 sm:grid-cols-6" aria-label="Pasos">
        {r.pasos.map((x, k) => (
          <li key={x.paso}>
            <button onClick={() => setElegido(x.paso)} aria-current={x.paso === elegido ? "step" : undefined}
              className={cx("grid w-full gap-1 rounded-lg border p-2 text-left text-xs", x.paso === elegido ? "border-acento bg-acento/10" : "border-borde bg-panel hover:bg-panel-2")}>
              <span className={cx("grid size-6 place-items-center rounded-full font-semibold", x.listo ? "bg-ok/15 text-ok" : "bg-panel-2 text-suave")}>{x.listo ? "✓" : k + 1}</span>
              <span className="leading-tight">{x.titulo}</span>
            </button>
          </li>
        ))}
      </ol>
      {p && (
        <Tarjeta titulo={`Paso ${i + 1} de ${r.total}: ${p.titulo}`} accion={p.listo ? <Etiqueta tono="ok">✓ Listo</Etiqueta> : <Etiqueta tono="alerta">Pendiente</Etiqueta>}>
          <p className="text-sm">{p.detalle}</p>
          <p className="mt-2 text-sm text-suave">{AYUDA[p.paso]}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Link href={p.ir} className="rounded-lg bg-acento px-3.5 py-2 text-sm font-medium text-acento-texto">{p.accion}</Link>
            {p.se_confirma && !p.confirmado && <Boton variante="secundario" onClick={() => confirmar(p.paso)}>Ya lo revisé, seguir</Boton>}
            {!p.se_confirma && !p.listo && <span className="self-center text-xs text-suave">Este paso se marca solo cuando los datos están.</span>}
            {i < r.pasos.length - 1 && <Boton variante="fantasma" onClick={() => setElegido(r.pasos[i + 1].paso)}>Siguiente →</Boton>}
          </div>
        </Tarjeta>
      )}
      {!r.completo_at && <div><Boton variante="fantasma" onClick={omitir}>Lo hago después</Boton></div>}
    </div>
  );
}
