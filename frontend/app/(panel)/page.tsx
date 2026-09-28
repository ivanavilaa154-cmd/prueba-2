"use client";
import Link from "next/link";
import { useSesion } from "@/components/Sesion";
import { Etiqueta, Tarjeta } from "@/components/ui";
import { MODELOS } from "@/lib/formato";

type Paso = { titulo: string; estado: "listo" | "pendiente" | "proximamente"; detalle: string; ir?: string; cuando?: string };

export default function Inicio() {
  const { yo, puede } = useSesion();
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

  const tarjetas = ["Ventas vs. período anterior", "Ganancia", "Productos en rojo", "Plata parada", "Plata en riesgo", "Anomalías de caja"];

  return (
    <div className="grid gap-5">
      <div>
        <h1 className="text-2xl font-semibold">Hola, {yo.usuario.nombre.split(" ")[0]}</h1>
        <p className="text-suave">{yo.empresa?.nombre} · {new Date().toLocaleDateString("es-AR", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" })}</p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {tarjetas.map((t) => (
          <div key={t} className="rounded-xl border border-borde bg-panel p-4">
            <p className="text-sm text-suave">{t}</p>
            <p className="mt-1 text-2xl font-semibold text-suave">—</p>
            <p className="mt-1 text-xs text-suave">Sin datos todavía: aparece cuando conectes tus ventas y tu stock.</p>
          </div>
        ))}
      </div>

      {!configura && (
        <Tarjeta titulo="Tu trabajo en la plataforma">
          <p className="text-sm text-suave">
            Ves {yo.usuario.todas_ubicaciones ? "todas las sucursales" : yo.ubicaciones.map((u) => u.nombre).join(", ")}.
            Cuando se conecten las ventas y el stock, acá vas a encontrar tus tareas del día: recuentos, recepciones y avisos.
          </p>
        </Tarjeta>
      )}
      {configura && <Tarjeta titulo="Primeros pasos">
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
      </Tarjeta>}
    </div>
  );
}
