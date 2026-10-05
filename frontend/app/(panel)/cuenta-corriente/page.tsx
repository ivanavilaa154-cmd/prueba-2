"use client";
// Cuenta corriente de los clientes (SPEC v2, 12B.4 y 12B.7): deuda por antigüedad, clientes que siguen comprando con deuda vencida o pasan
// su límite (bloqueo sugerido), cobranza por vendedor y compromisos de pago.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { TRAMOS, type DeudaCliente } from "@/lib/distribuidor";
import { fechaCorta, numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Cifra } from "@/components/distribuidor/Cifra";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, Boton, Campo, ComoSeCalcula, Entrada, Etiqueta, Selector, Tabla, Tarjeta, Vacio, cx } from "@/components/ui";

type R = { clientes: DeudaCliente[]; totales: Record<string, number>; alertas: { sigue_comprando: number; supera_limite: number };
  por_vendedor: { vendedor_id: number | null; vendedor: string; vencido: number; saldo: number; clientes_con_deuda_vencida: number; cobrado_30_dias: number }[] };
const COLORES = ["bg-panel-2", "bg-alerta/40", "bg-alerta", "bg-peligro/70", "bg-peligro"];

export default function CuentaCorriente() {
  const { puede } = useSesion();
  const [r, setR] = useState<R | null>(null);
  const [filtro, setFiltro] = useState("vencido");
  const [elegido, setElegido] = useState<DeudaCliente | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cargar = () => api<R>("/distribuidor/cuenta-corriente").then(setR).catch((e) => setError(e.message));
  useEffect(() => { cargar(); }, []);
  if (error) return <Aviso tipo="error">{error}</Aviso>;
  if (!r) return <p className="text-sm text-suave">Cargando…</p>;
  const total = Math.max(1, TRAMOS.reduce((s, [k]) => s + (r.totales[k] ?? 0), 0));
  const filas = r.clientes.filter((c) => filtro === "todos" || (filtro === "vencido" ? c.vencido > 0 : filtro === "alertas" ? c.alertas.length > 0 : c.d90_mas > 0));
  return (
    <div className="grid grid-cols-1 gap-4">
      <div>
        <h1 className="text-2xl font-semibold">Cuenta corriente</h1>
        <p className="text-sm text-suave">Quién te debe, desde cuándo, y a quién conviene frenarle los pedidos hasta que pague.</p>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Cifra titulo="Saldo a cobrar" valor={plataCorta(r.totales.saldo)} nota="con IVA, todos los clientes" />
        <Cifra titulo="Vencido" valor={plataCorta(r.totales.vencido)} nota={`${numero((r.totales.vencido / Math.max(1, r.totales.saldo)) * 100)} % del saldo`} tono="peligro" />
        <Cifra titulo="Más de 90 días" valor={plataCorta(r.totales.d90_mas)} nota="difícil de cobrar" tono="peligro" />
        <Cifra titulo="Alertas" valor={`${r.alertas.sigue_comprando + r.alertas.supera_limite}`}
          nota={`${r.alertas.sigue_comprando} compran con deuda vencida · ${r.alertas.supera_limite} pasan su límite`} />
      </div>
      <Tarjeta titulo="Antigüedad de la deuda">
        <div className="flex h-6 w-full overflow-hidden rounded-full" role="img" aria-label="Deuda por tramo de antigüedad">
          {TRAMOS.map(([k, n], i) => (
            <div key={k} className={cx(COLORES[i], "border-r-2 border-panel last:border-r-0")} style={{ width: `${((r.totales[k] ?? 0) / total) * 100}%` }} title={`${n}: ${plata(Math.round(r.totales[k] ?? 0))}`} />
          ))}
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2 text-sm sm:grid-cols-5">
          {TRAMOS.map(([k, n], i) => (
            <div key={k} className="flex items-center gap-2"><span className={cx("size-3 rounded-sm", COLORES[i])} aria-hidden="true" />
              <span>{n}<br /><strong>{plataCorta(r.totales[k])}</strong></span></div>
          ))}
        </div>
      </Tarjeta>
      <Tarjeta titulo="Clientes con deuda" accion={
        <Selector value={filtro} onChange={(e) => setFiltro(e.target.value)} aria-label="Filtro">
          <option value="vencido">Con deuda vencida</option><option value="alertas">Con alertas</option><option value="90">Más de 90 días</option><option value="todos">Todos</option>
        </Selector>}>
        <TablaDatos filas={filas} idFila={(f) => String(f.cliente_id)} nombreArchivo="cuenta-corriente" alHacerClic={setElegido}
          vacio={<Vacio titulo="Nadie con deuda en ese filtro" />}
          columnas={[
            { id: "cliente", titulo: "Cliente", valor: (f) => f.cliente,
              render: (f) => <div><span className="font-medium">{f.cliente}</span><div className="text-xs text-suave">{f.vendedor ?? "Sin vendedor"}</div>
                {f.alertas.map((a) => <div key={a} className="text-xs text-peligro">● {a}</div>)}</div> },
            { id: "saldo", titulo: "Saldo", derecha: true, valor: (f) => f.saldo, render: (f) => plata(Math.round(f.saldo)) },
            { id: "vencido", titulo: "Vencido", derecha: true, valor: (f) => f.vencido, render: (f) => <strong>{plata(Math.round(f.vencido))}</strong> },
            ...TRAMOS.slice(1).map(([k, n]) => ({ id: String(k), titulo: n, derecha: true, ocultarEnCelular: true, valor: (f: DeudaCliente) => Number(f[k]),
              render: (f: DeudaCliente) => (Number(f[k]) ? plataCorta(Number(f[k])) : "—") })),
            { id: "atraso", titulo: "Mayor atraso", derecha: true, valor: (f) => f.dias_mayor_atraso, render: (f) => (f.dias_mayor_atraso ? `${f.dias_mayor_atraso} d` : "—") },
            { id: "bloqueo", titulo: "", valor: (f) => (f.bloqueo_sugerido ? 1 : 0), render: (f) => (f.bloqueo_sugerido ? <Etiqueta tono="peligro">Frenar pedidos</Etiqueta> : null) },
          ]} />
        <ComoSeCalcula>Cada comprobante con saldo se ubica según los días desde su vencimiento. Se sugiere frenar pedidos si el saldo pasa el límite de crédito,
          o si debe hace más de 60 días y sigue comprando.</ComoSeCalcula>
      </Tarjeta>
      <Tarjeta titulo="Por vendedor">
        <Tabla columnas={["Vendedor", "Vencido", "Clientes con deuda vencida", "Cobrado (30 días)"]}>
          {r.por_vendedor.map((v) => (
            <tr key={v.vendedor}><td>{v.vendedor}</td><td className="text-right">{plata(Math.round(v.vencido))}</td>
              <td className="text-right">{v.clientes_con_deuda_vencida}</td><td className="text-right">{plata(Math.round(v.cobrado_30_dias))}</td></tr>
          ))}
        </Tabla>
      </Tarjeta>
      {elegido && <Detalle c={elegido} cerrar={() => setElegido(null)} puedeCobrar={puede("gestionar_cobranza")} alGuardar={() => { setElegido(null); cargar(); }} />}
    </div>
  );
}

function Detalle({ c, cerrar, puedeCobrar, alGuardar }: { c: DeudaCliente; cerrar: () => void; puedeCobrar: boolean; alGuardar: () => void }) {
  const [fecha, setFecha] = useState("");
  const [monto, setMonto] = useState("");
  const [nota, setNota] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function guardar() {
    try {
      await api("/distribuidor/compromisos", { metodo: "POST", cuerpo: { cliente_id: c.cliente_id, fecha, monto: Number(monto.replace(/\./g, "").replace(",", ".")), nota: nota || null } });
      alGuardar();
    } catch (e) { setError(e instanceof Error ? e.message : "No se pudo guardar."); }
  }
  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label={`Deuda de ${c.cliente}`}>
      <button className="absolute inset-0 bg-black/40" aria-label="Cerrar" onClick={cerrar} />
      <div className="relative grid h-full w-full max-w-md content-start gap-4 overflow-y-auto bg-fondo p-4 shadow-xl sm:p-6">
        <div className="flex items-start justify-between"><h2 className="text-xl font-semibold">{c.cliente}</h2>
          <button onClick={cerrar} className="rounded-lg px-2 py-1 text-suave hover:bg-panel-2" aria-label="Cerrar">✕</button></div>
        <p className="text-sm">Saldo {plata(Math.round(c.saldo))} · vencido {plata(Math.round(c.vencido))}{c.limite_credito ? ` · límite ${plata(c.limite_credito)}` : ""}
          {c.ultima_compra ? ` · última compra ${fechaCorta(c.ultima_compra)}` : ""}</p>
        {c.alertas.map((a) => <Aviso key={a} tipo="alerta">{a}</Aviso>)}
        <Tarjeta titulo="Compromisos de pago">
          {c.compromisos.length === 0 ? <p className="text-sm text-suave">Sin compromisos.</p> : (
            <ul className="grid gap-1 text-sm">{c.compromisos.map((p) => (
              <li key={p.id}>{fechaCorta(p.fecha)} · {plata(p.monto)} · <Etiqueta tono={p.estado === "cumplido" ? "ok" : p.incumplido ? "peligro" : "gris"}>
                {p.estado === "cumplido" ? "Cumplido" : p.incumplido ? "Incumplido" : "Pendiente"}</Etiqueta>{p.nota && <span className="text-suave"> · {p.nota}</span>}</li>))}</ul>
          )}
          {puedeCobrar && (
            <div className="mt-3 grid gap-2">
              {error && <Aviso tipo="error">{error}</Aviso>}
              <Campo etiqueta="Fecha prometida"><Entrada type="date" value={fecha} onChange={(e) => setFecha(e.target.value)} /></Campo>
              <Campo etiqueta="Monto"><Entrada inputMode="decimal" value={monto} onChange={(e) => setMonto(e.target.value)} /></Campo>
              <Campo etiqueta="Nota"><Entrada value={nota} onChange={(e) => setNota(e.target.value)} /></Campo>
              <div><Boton disabled={!fecha || !monto} onClick={guardar}>Registrar compromiso</Boton></div>
            </div>
          )}
        </Tarjeta>
      </div>
    </div>
  );
}
