"use client";
// Mi cartera (SPEC v2, sección 15 y 13.7): la vista del vendedor, pensada para el celular. Muestra lo que gana él: la ruta de hoy con qué
// ofrecerle a cada cliente, los clientes a recuperar, su meta y la deuda de su cartera. El jefe de ventas la ve de cualquier vendedor.
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ESTADO_CLIENTE, type DeudaCliente, type FilaCliente, type Oportunidad, type ResumenClientes } from "@/lib/distribuidor";
import { DIAS_SEMANA, fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Boton, Etiqueta, Selector, Tarjeta, Vacio, cx } from "@/components/ui";

type Parada = Pick<FilaCliente, "cliente_id" | "cliente" | "localidad" | "estado" | "dias_sin_comprar" | "venta_mensual" | "explicacion"> & {
  orden: number; vencido: number; alertas_deuda: string[]; oportunidades: Oportunidad[]; visita: { realizada: boolean; resultado: string | null } | null };
type Meta = { venta_mes: number; meta_mes: number | null; proyeccion_mes: number; cumplimiento_proyectado: number | null; margen: number | null };
type R = { hoy: string; vendedor: { id: number; nombre: string; zona: string | null } | null; ruta: Parada[];
  recuperar: (FilaCliente & { oportunidades: Oportunidad[] })[]; resumen: ResumenClientes; meta: Meta | null;
  deuda: { vencido: number; saldo: number; clientes: DeudaCliente[] } };
const RESULTADOS: [string, string][] = [["pedido", "Hizo pedido"], ["sin_pedido", "Sin pedido"], ["cerrado", "Cerrado"], ["no_atendio", "No atendió"]];

export default function MiCartera() {
  const { yo } = useSesion();
  const esVendedor = yo.usuario.rol === "vendedor";
  const [vendedor, setVendedor] = useState<string>(() => (typeof location !== "undefined" ? new URLSearchParams(location.search).get("vendedor") ?? "" : ""));
  const [vendedores, setVendedores] = useState<{ id: number; nombre: string }[]>([]);
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cargar = useCallback(() => {
    if (!esVendedor && !vendedor) return;
    api<R>(`/distribuidor/mi-cartera${vendedor && !esVendedor ? `?vendedor=${vendedor}` : ""}`).then(setR).catch((e) => setError(e.message));
  }, [esVendedor, vendedor]);
  useEffect(() => { cargar(); }, [cargar]);
  useEffect(() => {
    if (esVendedor) return;
    api<{ vendedores: { id: number; nombre: string }[] }>("/distribuidor/clientes").then((x) => {
      setVendedores(x.vendedores);
      if (!vendedor && x.vendedores[0]) setVendedor(String(x.vendedores[0].id));
    }).catch(() => {});
  }, [esVendedor, vendedor]);

  async function marcar(cliente_id: number, resultado: string) {
    try {
      await api("/distribuidor/visitas", { metodo: "POST", cuerpo: { cliente_id, resultado } });
      cargar();
    } catch (e) { setError(e instanceof Error ? e.message : "No se pudo guardar."); }
  }

  const dia = r ? DIAS_SEMANA[(new Date(`${r.hoy}T12:00:00`).getDay() + 6) % 7] : "";
  return (
    <div className="mx-auto grid w-full max-w-2xl grid-cols-1 gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-semibold">{esVendedor ? "Mi cartera" : `Cartera de ${r?.vendedor?.nombre ?? "…"}`}</h1>
          <p className="text-sm text-suave">{r ? `Hoy, ${dia} ${fechaCorta(r.hoy)}` : ""}{r?.vendedor?.zona ? ` · ${r.vendedor.zona}` : ""}</p>
        </div>
        {!esVendedor && vendedores.length > 0 && (
          <Selector value={vendedor} onChange={(e) => setVendedor(e.target.value)} aria-label="Vendedor">
            {vendedores.map((v) => <option key={v.id} value={v.id}>{v.nombre}</option>)}
          </Selector>
        )}
      </div>
      {error && <Aviso tipo="error">{error}</Aviso>}
      {!r ? <p className="text-sm text-suave">Cargando…</p> : <>
        <div className="grid grid-cols-3 gap-2">
          <Mini titulo="Meta del mes" valor={r.meta?.meta_mes ? `${numero((r.meta.venta_mes / r.meta.meta_mes) * 100)} %` : "—"}
            nota={r.meta?.meta_mes ? `cierra en ${numero((r.meta.cumplimiento_proyectado ?? 0) * 100)} %` : "sin meta"}
            tono={r.meta?.cumplimiento_proyectado != null ? (r.meta.cumplimiento_proyectado >= 1 ? "ok" : r.meta.cumplimiento_proyectado >= 0.9 ? "alerta" : "peligro") : undefined} />
          <Mini titulo="A recuperar" valor={String(r.resumen.perdido + r.resumen.en_riesgo)} nota={`${plataCorta(r.resumen.deja_de_facturar_mes)}/mes`} tono="peligro" />
          <Mini titulo="Deuda vencida" valor={plataCorta(r.deuda.vencido)} nota="de tu cartera" />
        </div>

        <Tarjeta titulo={`Ruta de hoy (${r.ruta.length})`}>
          {r.ruta.length === 0 ? <Vacio titulo="Hoy no tenés ruta">Mirá los clientes a recuperar, abajo.</Vacio> : (
            <ol className="grid gap-3">
              {r.ruta.map((p) => (
                <li key={p.cliente_id} className={cx("rounded-xl border p-3", p.visita?.realizada ? "border-borde opacity-70" : "border-borde")}>
                  <div className="flex items-start justify-between gap-2">
                    <div><span className="text-suave">{p.orden}.</span> <strong>{p.cliente}</strong><div className="text-xs text-suave">{p.localidad}</div></div>
                    <Etiqueta tono={ESTADO_CLIENTE[p.estado].tono}>{ESTADO_CLIENTE[p.estado].texto}</Etiqueta>
                  </div>
                  {p.estado !== "activo" && <p className="mt-1 text-sm">{p.explicacion}</p>}
                  {p.vencido > 0 && <p className="mt-1 text-sm text-peligro">Debe {plata(Math.round(p.vencido))} vencido. {p.alertas_deuda.join(" ")}</p>}
                  {p.oportunidades.length > 0 && (
                    <div className="mt-2 rounded-lg bg-panel-2 p-2 text-sm">
                      <p className="font-medium">Ofrecele:</p>
                      <ul>{p.oportunidades.map((o) => <li key={o.categoria_id}>• {o.cantidad_sugerida} × {o.producto} <span className="text-xs text-suave">({numero(o.compran_parecidos * 100)} % de comercios parecidos lo compra)</span></li>)}</ul>
                    </div>
                  )}
                  {esVendedor && (p.visita?.realizada ? <p className="mt-2 text-xs text-ok">✓ Visitado: {RESULTADOS.find(([k]) => k === p.visita?.resultado)?.[1] ?? "listo"}</p> : (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {RESULTADOS.map(([k, n]) => <Boton key={k} variante={k === "pedido" ? "primario" : "secundario"} className="px-2.5 py-1.5 text-xs" onClick={() => marcar(p.cliente_id, k)}>{n}</Boton>)}
                    </div>
                  ))}
                </li>
              ))}
            </ol>
          )}
        </Tarjeta>

        <Tarjeta titulo="Clientes a recuperar">
          {r.recuperar.length === 0 ? <p className="text-sm text-suave">Ninguno: todos tus clientes compran a su ritmo.</p> : (
            <ul className="grid gap-2">
              {r.recuperar.map((c) => (
                <li key={c.cliente_id} className="rounded-xl border border-borde p-3">
                  <div className="flex items-start justify-between gap-2"><strong>{c.cliente}</strong>
                    <Etiqueta tono={ESTADO_CLIENTE[c.estado].tono}>{ESTADO_CLIENTE[c.estado].texto}</Etiqueta></div>
                  <p className="text-sm">{c.explicacion} Compraba {plata(Math.round(c.venta_mensual))} por mes.</p>
                  {c.oportunidades[0] && <p className="text-xs text-suave">Para volver: {c.oportunidades.map((o) => o.producto).join(", ")}.</p>}
                </li>
              ))}
            </ul>
          )}
        </Tarjeta>

        {r.deuda.clientes.length > 0 && (
          <Tarjeta titulo="Deuda de tu cartera">
            <ul className="grid gap-1 text-sm">
              {r.deuda.clientes.filter((d) => d.vencido > 0).map((d) => (
                <li key={d.cliente_id} className="flex justify-between gap-2"><span>{d.cliente}{d.dias_mayor_atraso > 60 && <span className="text-peligro"> · {d.dias_mayor_atraso} días</span>}</span>
                  <strong>{plata(Math.round(d.vencido))}</strong></li>
              ))}
            </ul>
          </Tarjeta>
        )}
      </>}
    </div>
  );
}

function Mini({ titulo, valor, nota, tono }: { titulo: string; valor: string; nota: string; tono?: "ok" | "alerta" | "peligro" }) {
  return (
    <div className="min-w-0 rounded-xl border border-borde bg-panel p-2.5 sm:p-3">
      <p className="text-xs text-suave">{titulo}</p>
      <p className={cx("break-words text-base font-semibold sm:text-xl", tono === "peligro" && "text-peligro", tono === "ok" && "text-ok", tono === "alerta" && "text-alerta")}>{valor}</p>
      <p className="text-xs text-suave">{nota}</p>
    </div>
  );
}
