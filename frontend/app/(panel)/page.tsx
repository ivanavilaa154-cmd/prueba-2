"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { TarjetaAviso, type AvisoDatos } from "@/components/Aviso";
import { useSesion } from "@/components/Sesion";
import { Etiqueta, Tarjeta } from "@/components/ui";
import { fechaCorta, MODELOS, numero, plataCorta } from "@/lib/formato";

type Resumen = { ayer: string; comparado_con: string; ventas_ayer: string; ventas_semana_anterior: string; var_ventas: string | null;
  ganancia_ayer: string | null; var_ganancia: string | null; tickets_ayer: number; ventas_hoy: string; tickets_hoy: number; var_hoy: string | null;
  productos_en_rojo: number; plata_parada: string | null; plata_en_riesgo: string | null; anomalias_caja: number;
  avisos: AvisoDatos[]; acciones: AvisoDatos[] };

function Clave({ titulo, valor, variacion, nota, href }: { titulo: string; valor: string; variacion?: string | null; nota?: string; href: string }) {
  const v = variacion === null || variacion === undefined ? null : Number(variacion);
  return (
    <Link href={href} className="rounded-xl border border-borde bg-panel p-4 hover:border-acento">
      <p className="text-sm text-suave">{titulo}</p>
      <p className="mt-1 text-2xl font-semibold">{valor}</p>
      {v !== null && <p className={`text-xs ${Math.abs(v) < 0.5 ? "text-suave" : v > 0 ? "text-ok" : "text-peligro"}`}>{v > 0 ? "▲ +" : v < 0 ? "▼ " : "= "}{numero(v, 1)} %</p>}
      {nota && <p className="text-xs text-suave">{nota}</p>}
    </Link>
  );
}

type Paso = { titulo: string; estado: "listo" | "pendiente" | "proximamente"; detalle: string; ir?: string; cuando?: string };

export default function Inicio() {
  const { yo, puede } = useSesion();
  const distribuidor = yo.usuario.rol === "distribuidor";
  useEffect(() => { if (distribuidor) location.replace(`${location.pathname.replace(/\/$/, "")}/panel/`); }, [distribuidor]);
  const sucursales = yo.ubicaciones.filter((u) => u.tipo !== "deposito").length;
  const depositos = yo.ubicaciones.filter((u) => u.tipo === "deposito").length;
  const configura = puede("configurar_empresa");
  const modelo = MODELOS[yo.empresa?.modelo_abastecimiento ?? "mixto"];

  const pasos: Paso[] = [
    yo.datos?.productos
      ? { titulo: "Conectar tus datos", estado: "listo" as const,
          detalle: yo.datos.origen === "demo" ? `Estás viendo datos de demostración (${yo.datos.productos} productos, 13 meses de ventas). La conexión con tu caja llega en las partes 3 y 4.`
            : `${yo.datos.productos} productos cargados.` }
      : { titulo: "Conectar tus datos", estado: "proximamente" as const, cuando: "las partes 3 y 4",
          detalle: "Conexión con tu sistema de caja (Odoo Punto de Venta) o importación de Excel/CSV de ventas, stock y productos." },
    { titulo: "Confirmar sucursales y depósitos", estado: sucursales > 0 ? "listo" : "pendiente", ir: "/configuracion/#sucursales",
      detalle: sucursales > 0 ? `${sucursales} sucursal${sucursales === 1 ? "" : "es"} y ${depositos} depósito${depositos === 1 ? "" : "s"} cargados.` : "Cargá al menos una sucursal." },
    yo.datos?.productos && !yo.datos.sin_mapear
      ? { titulo: "Mapear productos", estado: "listo" as const, detalle: "Todos los productos están vinculados al catálogo (o son de elaboración propia)." }
      : { titulo: "Mapear productos", estado: "proximamente" as const, cuando: "la parte 6",
          detalle: "Vincular tus productos al catálogo maestro por código de barras; lo dudoso lo confirmás vos una vez." },
    yo.datos?.proveedores
      ? { titulo: "Configurar proveedores", estado: "listo" as const, detalle: `${yo.datos.proveedores} proveedores con días de visita, demora y pedido mínimo.` }
      : { titulo: "Configurar proveedores", estado: "proximamente" as const, cuando: "las partes 2 y 3",
          detalle: "Días de visita, demora de entrega y pedido mínimo de cada proveedor." },
    { titulo: "Modelo de abastecimiento y márgenes", estado: "listo", ir: "/configuracion/#empresa",
      detalle: `Modelo ${modelo.nombre.toLowerCase()}: ${modelo.explicacion.charAt(0).toLowerCase()}${modelo.explicacion.slice(1)} Los márgenes objetivo llegan en la parte 10.` },
    yo.datos?.calculado_at
      ? { titulo: "Ver las primeras recomendaciones", estado: "listo" as const, ir: "/comprar/",
          detalle: "Qué te falta, cuánto comprar y a quién, con la explicación de cada número." }
      : { titulo: "Ver las primeras recomendaciones", estado: "proximamente" as const, cuando: "la parte 8",
          detalle: "Qué te falta, cuánto comprar y a quién, con la explicación de cada número." },
  ];

  const [r, setR] = useState<Resumen | null>(null);
  const [recarga, setRecarga] = useState(0);
  useEffect(() => { if (yo.datos?.productos) api<Resumen>("/inicio").then(setR).catch(() => setR(null)); }, [yo.datos?.productos, recarga]);
  const tarjetas = ["Ventas vs. período anterior", "Ganancia", "Productos en rojo", "Plata parada", "Plata en riesgo", "Anomalías de caja"];

  return (
    <div className="grid gap-5">
      <div>
        <h1 className="text-2xl font-semibold">Hola, {yo.usuario.nombre.split(" ")[0]}</h1>
        <p className="text-suave">{yo.empresa?.nombre} · {new Date().toLocaleDateString("es-AR", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" })}</p>
      </div>

      {r && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <Clave titulo={`Ventas de ayer (${fechaCorta(r.ayer).slice(0, 5)})`} valor={plataCorta(r.ventas_ayer)} variacion={r.var_ventas}
              nota={`vs. ${fechaCorta(r.comparado_con).slice(0, 5)} · hoy van ${plataCorta(r.ventas_hoy)}`} href="/ventas/" />
            {r.ganancia_ayer !== null && <Clave titulo="Ganancia bruta de ayer" valor={plataCorta(r.ganancia_ayer)} variacion={r.var_ganancia} href="/ventas/" />}
            <Clave titulo="Productos en rojo" valor={numero(r.productos_en_rojo)} nota="se agotan antes de reponer" href="/comprar/?semaforo=rojo" />
            {r.plata_parada !== null && <Clave titulo="Plata parada" valor={plataCorta(r.plata_parada)} nota="sobrestock y sin ventas en 90 días" href="/comprar/?semaforo=gris" />}
            {r.plata_en_riesgo !== null && <Clave titulo="Plata en riesgo de vencimiento" valor={plataCorta(r.plata_en_riesgo)} nota="a costo" href="/avisos/?tipo=vencimiento" />}
            <Clave titulo="Anomalías de caja" valor={numero(r.anomalias_caja)} nota="cajeros fuera de lo normal" href="/caja/" />
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <Tarjeta titulo="Lo más importante hoy" accion={<Link href="/avisos/" className="text-sm text-acento underline">Todos los avisos</Link>}>
              <div className="grid gap-3">
                {r.avisos.length === 0 && <p className="text-sm text-suave">No hay avisos abiertos.</p>}
                {r.avisos.map((a) => <TarjetaAviso key={a.id} a={a} compacto alCambiar={() => setRecarga(recarga + 1)} />)}
              </div>
            </Tarjeta>
            <Tarjeta titulo="Acciones del día">
              <div className="grid gap-3">
                {r.acciones.length === 0 && <p className="text-sm text-suave">No hay acciones pendientes.</p>}
                {r.acciones.map((a) => <TarjetaAviso key={a.id} a={{ ...a, prioridad: "normal", explicacion: "", estado: "nueva" }} compacto sinPrioridad alCambiar={() => setRecarga(recarga + 1)} />)}
              </div>
            </Tarjeta>
          </div>
        </>
      )}

      {!r && <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {tarjetas.map((t) => (
          <div key={t} className="rounded-xl border border-borde bg-panel p-4">
            <p className="text-sm text-suave">{t}</p>
            <p className="mt-1 text-2xl font-semibold text-suave">—</p>
            <p className="mt-1 text-xs text-suave">{yo.datos?.productos ? "Cargando…" : "Sin datos todavía: aparece cuando conectes tus ventas y tu stock."}</p>
          </div>
        ))}
      </div>}

      {!configura && (
        <Tarjeta titulo="Tu trabajo en la plataforma">
          <p className="text-sm text-suave">
            Ves {yo.usuario.todas_ubicaciones ? "todas las sucursales" : yo.ubicaciones.map((u) => u.nombre).join(", ")}.
            Cuando se conecten las ventas y el stock, acá vas a encontrar tus tareas del día: recuentos, recepciones y avisos.
          </p>
        </Tarjeta>
      )}
      {configura && <details open={!yo.datos?.productos} className="rounded-xl border border-borde bg-panel p-4 sm:p-5">
        <summary className="cursor-pointer font-semibold">Primeros pasos</summary><div className="mt-3">
        <ol className="grid gap-3">
          {pasos.map((p, i) => (
            <li key={p.titulo} className="flex gap-3">
              <span className={`mt-0.5 grid size-6 shrink-0 place-items-center rounded-full text-xs font-semibold ${p.estado === "listo" ? "bg-ok/15 text-ok" : "bg-panel-2 text-suave"}`}>
                {p.estado === "listo" ? "✓" : i + 1}
              </span>
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-2 font-medium">
                  {p.titulo}
                  {p.estado === "listo" && <Etiqueta tono="ok">Listo</Etiqueta>}
                  {p.estado === "pendiente" && <Etiqueta tono="alerta">Pendiente</Etiqueta>}
                  {p.estado === "proximamente" && <Etiqueta>Llega en {p.cuando}</Etiqueta>}
                </p>
                <p className="text-sm text-suave">{p.detalle}</p>
                {p.ir && configura && <Link href={p.ir} className="text-sm text-acento underline">Revisar</Link>}
              </div>
            </li>
          ))}
        </ol>
      </div></details>}
    </div>
  );
}
