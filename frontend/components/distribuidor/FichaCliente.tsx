"use client";
// Ficha de un cliente del distribuidor: estado contra su propio ritmo, compras por mes, qué ofrecerle, deuda y últimos pedidos.
import { ESTADO_CLIENTE, type FilaCliente, type Oportunidad } from "@/lib/distribuidor";
import { fechaCorta, plata } from "@/lib/formato";
import { Aviso, Tabla, Tarjeta } from "@/components/ui";

export type Ficha = { cliente: Record<string, string | number | null>; estado: FilaCliente | null; meses: { mes: string; pedidos: number; venta: string }[];
  pedidos: { id: number; numero: string; fecha: string; estado: string; total: string; total_entregado: string }[];
  deuda: { tipo: string; numero: string; fecha: string; vencimiento: string | null; importe: string; saldo: string }[]; oportunidades: Oportunidad[] };

export function FichaCliente({ ficha, cerrar }: { ficha: Ficha; cerrar: () => void }) {
  const c = ficha.cliente;
  const max = Math.max(1, ...ficha.meses.map((m) => Number(m.venta)));
  const deuda = ficha.deuda.reduce((s, d) => s + Number(d.saldo), 0);
  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label={`Cliente ${c.razon_social}`}>
      <button className="absolute inset-0 bg-black/40" aria-label="Cerrar" onClick={cerrar} />
      <div className="relative grid h-full w-full max-w-xl content-start gap-4 overflow-y-auto bg-fondo p-4 shadow-xl sm:p-6">
        <div className="flex items-start justify-between gap-2">
          <div>
            <h2 className="text-xl font-semibold">{String(c.nombre_fantasia ?? c.razon_social)}</h2>
            <p className="text-sm text-suave">{[c.razon_social, c.cuit, c.direccion, c.localidad].filter(Boolean).join(" · ")}</p>
            <p className="text-sm text-suave">Vendedor: {String(c.vendedor ?? "—")} · {String(c.canal ?? "")} · lista {String(c.lista_precios ?? "general")}</p>
          </div>
          <button onClick={cerrar} className="rounded-lg px-2 py-1 text-suave hover:bg-panel-2" aria-label="Cerrar">✕</button>
        </div>
        {ficha.estado && (
          <Aviso tipo={ficha.estado.estado === "perdido" ? "error" : ficha.estado.estado === "en_riesgo" ? "alerta" : "ok"}>
            <strong>{ESTADO_CLIENTE[ficha.estado.estado].texto}.</strong> {ficha.estado.explicacion}
            {ficha.estado.deja_de_facturar_mes > 0 && <> Se dejan de facturar unos {plata(Math.round(ficha.estado.deja_de_facturar_mes))} por mes.</>}
          </Aviso>
        )}
        <Tarjeta titulo="Compras por mes">
          <div className="flex h-28 items-end gap-1" role="img" aria-label="Venta por mes del último año">
            {ficha.meses.map((m) => (
              <div key={m.mes} className="group relative flex-1" title={`${m.mes.slice(0, 7)}: ${plata(Math.round(Number(m.venta)))} (${m.pedidos} pedidos)`}>
                <div className="rounded-t bg-acento" style={{ height: `${Math.max(2, (Number(m.venta) / max) * 100)}px` }} />
              </div>
            ))}
          </div>
          <p className="mt-1 text-xs text-suave">Pasá el mouse por cada barra para ver el mes.</p>
        </Tarjeta>
        {ficha.oportunidades.length > 0 && (
          <Tarjeta titulo="Qué ofrecerle (pedido sugerido)">
            <ul className="grid gap-2 text-sm">
              {ficha.oportunidades.map((o) => (
                <li key={o.categoria_id} className="rounded-lg border border-borde p-2">
                  <strong>{o.cantidad_sugerida} × {o.producto}</strong> <span className="text-suave">({o.categoria})</span>
                  <div className="text-xs text-suave">{o.explicacion} Le dejaría unos {plata(Math.round(o.ganancia_mes_estimada))} de ganancia por mes.</div>
                </li>
              ))}
            </ul>
          </Tarjeta>
        )}
        <Tarjeta titulo={`Cuenta corriente · saldo ${plata(Math.round(deuda))}`}>
          {ficha.deuda.length === 0 ? <p className="text-sm text-suave">No debe nada.</p> : (
            <Tabla columnas={["Comprobante", "Vence", "Saldo"]}>
              {ficha.deuda.map((d) => (
                <tr key={d.numero}><td>{d.numero}<div className="text-xs text-suave">{d.tipo.replace("_", " ")} del {fechaCorta(d.fecha)}</div></td>
                  <td>{fechaCorta(d.vencimiento ?? d.fecha)}</td><td className="text-right">{plata(d.saldo)}</td></tr>
              ))}
            </Tabla>
          )}
        </Tarjeta>
        <Tarjeta titulo="Últimos pedidos">
          <Tabla columnas={["Pedido", "Estado", "Pedido $", "Entregado $"]}>
            {ficha.pedidos.map((p) => (
              <tr key={p.id}><td>{p.numero}<div className="text-xs text-suave">{fechaCorta(p.fecha)}</div></td><td>{p.estado.replace("_", " ")}</td>
                <td className="text-right">{plata(Math.round(Number(p.total)))}</td><td className="text-right">{plata(Math.round(Number(p.total_entregado)))}</td></tr>
            ))}
          </Tabla>
        </Tarjeta>
      </div>
    </div>
  );
}
