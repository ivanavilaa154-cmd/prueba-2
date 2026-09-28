"use client";
// Rentabilidad del inventario (10.6): GMROI, rotación y días de inventario por producto, categoría, proveedor o sucursal.
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { numero, plata, plataCorta } from "@/lib/formato";
import { useSesion } from "@/components/Sesion";
import { Indicador } from "@/components/Indicador";
import { TablaDatos } from "@/components/TablaDatos";
import { Aviso, ComoSeCalcula, Selector, Tarjeta } from "@/components/ui";

type Fila = { clave: string; nombre: string; ganancia: string; facturacion: string; inventario_promedio: string; gmroi: number | null; rotacion: number | null; dias_inventario: number | null };
type R = { dias: number; filas: Fila[]; total: { ganancia: string; inventario_promedio: string; gmroi: number | null; rotacion: number | null; dias_inventario: number | null } };

export function Rentabilidad() {
  const { filtro, puede } = useSesion();
  const [nivel, setNivel] = useState("categoria");
  const [dias, setDias] = useState(90);
  const [r, setR] = useState<R | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!puede("ver_costos")) return;
    setR(null);
    const u = filtro.ubicaciones.length ? `&ubicaciones=${filtro.ubicaciones.join(",")}` : "";
    api<R>(`/ventas/rentabilidad?nivel=${nivel}&dias=${dias}${u}`).then(setR).catch((e) => setError(e.message));
  }, [nivel, dias, filtro, puede]);
  if (!puede("ver_costos")) return <Aviso>Tu rol no ve costos: la rentabilidad del inventario la ven el dueño y el comprador.</Aviso>;
  return (
    <div className="grid grid-cols-1 gap-4">
      {error && <Aviso tipo="error">{error}</Aviso>}
      {r && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Indicador titulo={`Ganancia (${r.dias} días)`} valor={plataCorta(r.total.ganancia)} />
          <Indicador titulo="Inventario promedio a costo" valor={plataCorta(r.total.inventario_promedio)} />
          <Indicador titulo="GMROI" valor={r.total.gmroi === null ? "—" : `${numero(r.total.gmroi, 2)}`} nota="pesos de ganancia por peso en stock" />
          <Indicador titulo="Rotación anual" valor={r.total.rotacion === null ? "—" : `${numero(r.total.rotacion, 1)} veces`} nota={r.total.dias_inventario ? `${numero(r.total.dias_inventario)} días de inventario` : undefined} />
        </div>
      )}
      <Tarjeta titulo="Rentabilidad del stock" accion={
        <div className="flex flex-wrap gap-2">
          <Selector className="w-40" value={nivel} onChange={(e) => setNivel(e.target.value)} aria-label="Ver por">
            <option value="categoria">Por categoría</option><option value="producto">Por producto</option><option value="proveedor">Por proveedor</option><option value="ubicacion">Por sucursal</option>
          </Selector>
          <Selector className="w-36" value={dias} onChange={(e) => setDias(Number(e.target.value))} aria-label="Período">
            <option value={30}>30 días</option><option value={90}>90 días</option><option value={180}>180 días</option><option value={365}>12 meses</option>
          </Selector>
        </div>}>
        {!r ? <p className="text-sm text-suave">Cargando…</p> : (
          <TablaDatos filas={r.filas} idFila={(f) => f.clave} nombreArchivo={`rentabilidad-${nivel}`}
            columnas={[
              { id: "nombre", titulo: { producto: "Producto", categoria: "Categoría", proveedor: "Proveedor", ubicacion: "Sucursal" }[nivel] ?? "", valor: (f) => f.nombre },
              { id: "gan", titulo: "Ganancia", valor: (f) => Number(f.ganancia), render: (f) => plata(f.ganancia), derecha: true },
              { id: "inv", titulo: "Stock promedio a costo", valor: (f) => Number(f.inventario_promedio), render: (f) => plata(f.inventario_promedio), derecha: true },
              { id: "gmroi", titulo: "GMROI", valor: (f) => f.gmroi, render: (f) => (f.gmroi === null ? "—" : numero(f.gmroi, 2)), derecha: true },
              { id: "rot", titulo: "Rotación anual", valor: (f) => f.rotacion, render: (f) => (f.rotacion === null ? "—" : `${numero(f.rotacion, 1)}×`), derecha: true },
              { id: "dias", titulo: "Días de inventario", valor: (f) => f.dias_inventario, render: (f) => (f.dias_inventario === null ? "—" : numero(f.dias_inventario)), derecha: true, ocultarEnCelular: true },
            ]} />
        )}
        <div className="mt-3">
          <ComoSeCalcula>
            <p>GMROI = ganancia bruta del período ÷ stock promedio a costo. Un GMROI de 2 quiere decir que cada peso invertido en mercadería dejó 2 pesos de ganancia.</p>
            <p>Rotación anual = costo de lo vendido ÷ stock promedio a costo × 365 ÷ días del período. Días de inventario = 365 ÷ rotación.</p>
          </ComoSeCalcula>
        </div>
      </Tarjeta>
    </div>
  );
}
