import Link from "next/link";
import { notFound } from "next/navigation";
import { PROXIMAS, SECCIONES } from "@/lib/secciones";

export const dynamicParams = false;

export function generateStaticParams() {
  return PROXIMAS.map((seccion) => ({ seccion }));
}

export default async function SeccionProxima({ params }: PageProps<"/[seccion]">) {
  const { seccion } = await params;
  const s = SECCIONES.find((x) => x.ruta === `/${seccion}/`);
  if (!s) notFound();
  return (
    <div className="mx-auto max-w-2xl py-6">
      <p className="text-xs font-semibold uppercase tracking-wider text-suave">{s.llega}</p>
      <h1 className="mt-1 text-2xl font-semibold">{s.nombre}</h1>
      <p className="mt-3 text-suave">{s.que_hace}</p>
      <div className="mt-6 rounded-xl border border-dashed border-borde p-5 text-sm">
        Esta sección todavía no está construida. Se habilita en la etapa indicada arriba, cuando la plataforma ya tenga los datos
        que necesita (ventas, stock, proveedores). Mientras tanto podés dejar lista la <Link className="text-acento underline" href="/configuracion/">configuración</Link>.
      </div>
    </div>
  );
}
