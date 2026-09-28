"use client";
// Surtido óptimo (10.12): marcas y presentaciones por subcategoría, duplicados de bajo rendimiento, qué discontinuar y qué sumar.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Aviso, Selector, Tabla, Tarjeta, Vacio } from "@/components/ui";

type Sub = { categoria: string; subcategoria: string; productos: number; marcas: number; presentaciones: number; facturacion: string;
  duplicados: { se_queda: string; bajo_rendimiento: string; participacion: number }[]; participacion: { nombre: string; participacion: number }[] };
type R = { subcategorias: Sub[]; discontinuar: { producto_id: number; nombre: string; subcategoria: string; ganancia_90d: string; participacion: number; sustituto: string }[];
  faltan_en_sucursal: { producto_id: number; nombre: string; facturacion_otras: string; sucursales: number }[] };

export function Surtido() {
  const { yo, puede } = useSesion();
  const [ubic, setUbic] = useState("");
  const [r, setR] = useState<R | null>(null);
  useEffect(() => { if (puede("ver_costos")) { setR(null); api<R>(`/surtido${ubic ? `?ubicacion_id=${ubic}` : ""}`).then(setR).catch(() => {}); } }, [ubic, puede]);
  if (!puede("ver_costos")) return <Aviso>El análisis de surtido lo ven el dueño y el comprador.</Aviso>;
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-suave">Sucursal:</span>
        <Selector className="w-56" value={ubic} onChange={(e) => setUbic(e.target.value)}>
          <option value="">Todas</option>{yo?.ubicaciones.filter((u) => u.tipo !== "deposito").map((u) => <option key={u.id} value={u.id}>{u.nombre}</option>)}
        </Selector>
      </div>
      {!r ? <p className="text-sm text-suave">Cargando…</p> : (
        <>
          <Tarjeta titulo={`Para discontinuar · ${r.discontinuar.length}`}>
            <p className="mb-2 text-sm text-suave">Clase C, de las que menos ganancia dejan en su subcategoría y con un sustituto que se vende bien.</p>
            {r.discontinuar.length === 0 ? <Vacio titulo="Nada para sacar" /> : (
              <Tabla columnas={["Producto", "Subcategoría", "Ganancia 90 días", "Participación", "Lo reemplaza"]}>
                {r.discontinuar.slice(0, 20).map((d) => (
                  <tr key={d.producto_id}><td>{d.nombre}</td><td>{d.subcategoria}</td><td className="whitespace-nowrap text-right">{plata(d.ganancia_90d)}</td>
                    <td className="text-right">{numero(d.participacion * 100, 1)} %</td><td>{d.sustituto}</td></tr>
                ))}
              </Tabla>
            )}
          </Tarjeta>
          {ubic && (
            <Tarjeta titulo="Se venden bien en otras sucursales y acá no están">
              {r.faltan_en_sucursal.length === 0 ? <Vacio titulo="No falta nada importante" /> : (
                <Tabla columnas={["Producto", "Facturación 90 días en otras", "Sucursales que lo venden"]}>
                  {r.faltan_en_sucursal.map((f) => <tr key={f.producto_id}><td>{f.nombre}</td><td className="text-right">{plataCorta(f.facturacion_otras)}</td><td className="text-right">{f.sucursales}</td></tr>)}
                </Tabla>
              )}
            </Tarjeta>
          )}
          <Tarjeta titulo="Por subcategoría">
            <Tabla columnas={["Subcategoría", "Productos", "Marcas", "Presentaciones", "Facturación 90 días", "El que más vende", "Duplicados flojos"]}>
              {r.subcategorias.map((s) => (
                <tr key={`${s.categoria}-${s.subcategoria}`} className="align-top">
                  <td>{s.subcategoria}<span className="block text-xs text-suave">{s.categoria}</span></td>
                  <td className="text-right">{s.productos}</td><td className="text-right">{s.marcas}</td><td className="text-right">{s.presentaciones}</td>
                  <td className="whitespace-nowrap text-right">{plataCorta(s.facturacion)}</td>
                  <td className="text-sm">{s.participacion[0] ? `${s.participacion[0].nombre} (${numero(s.participacion[0].participacion * 100)} %)` : "—"}</td>
                  <td className="text-sm">{s.duplicados.length ? s.duplicados.map((d) => `${d.bajo_rendimiento} (${numero(d.participacion * 100, 1)} %)`).join(", ") : "—"}</td>
                </tr>
              ))}
            </Tabla>
          </Tarjeta>
        </>
      )}
    </div>
  );
}
