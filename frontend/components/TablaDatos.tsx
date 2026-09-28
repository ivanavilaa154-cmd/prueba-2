"use client";
// Tabla estándar (sección 15): orden, búsqueda, paginación, selección para acciones masivas y exportación a Excel/CSV.
import { useMemo, useState, type ReactNode } from "react";
import {
  columnFilteringFeature, createColumnHelper, createFilteredRowModel, createPaginatedRowModel, createSortedRowModel,
  filterFn_includesString, globalFilteringFeature, rowPaginationFeature, rowSelectionFeature, rowSortingFeature, tableFeatures, useTable,
} from "@tanstack/react-table";
import { BASE } from "@/lib/api";
import { Boton, cx } from "./ui";

export type Columna<T> = {
  id: string;
  titulo: string;
  valor: (fila: T) => string | number | null | undefined;   // para ordenar, buscar y exportar
  render?: (fila: T) => ReactNode;
  derecha?: boolean;
  ocultarEnCelular?: boolean;
};

const features = tableFeatures({
  columnFilteringFeature,
  globalFilteringFeature,
  filteredRowModel: createFilteredRowModel(),
  filterFns: { includesString: filterFn_includesString },
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  rowPaginationFeature,
  paginatedRowModel: createPaginatedRowModel(),
  rowSelectionFeature,
});

function csv(valor: unknown): string {
  if (valor === null || valor === undefined) return "";
  const texto = typeof valor === "number" ? String(valor).replace(".", ",") : String(valor);
  return /[";\n]/.test(texto) ? `"${texto.replaceAll('"', '""')}"` : texto;
}

export function TablaDatos<T extends object>({ filas, columnas, idFila, nombreArchivo, acciones, alHacerClic, porPagina = 25, vacio, buscador = true }: {
  filas: T[];
  columnas: Columna<T>[];
  idFila: (f: T) => string;
  nombreArchivo: string;
  acciones?: (seleccion: T[], limpiar: () => void) => ReactNode;
  alHacerClic?: (f: T) => void;
  porPagina?: number;
  vacio?: ReactNode;
  buscador?: boolean;
}) {
  const helper = createColumnHelper<typeof features, T>();
  const defs = useMemo(() => helper.columns(columnas.map((c) =>
    helper.accessor((f: T) => c.valor(f) ?? null, {
      id: c.id,
      header: c.titulo,
      sortUndefined: "last",
      cell: (info) => (c.render ? c.render(info.row.original) : (info.getValue() as ReactNode)),
    }))), [columnas]);  // eslint-disable-line react-hooks/exhaustive-deps
  const table = useTable({
    features, columns: defs, data: filas, getRowId: (f: T) => idFila(f),
    globalFilterFn: "includesString" as const,
    initialState: { pagination: { pageIndex: 0, pageSize: porPagina } },
  });
  const [exportando, setExportando] = useState(false);
  const seleccion = table.getSelectedRowModel().rows.map((r) => r.original);
  const conSeleccion = !!acciones;

  const matriz = () => table.getFilteredRowModel().rows.map((r) => columnas.map((c) => c.valor(r.original) ?? ""));

  function exportarCSV() {
    const texto = "﻿" + [columnas.map((c) => csv(c.titulo)).join(";"), ...matriz().map((f) => f.map(csv).join(";"))].join("\n");
    const url = URL.createObjectURL(new Blob([texto], { type: "text/csv;charset=utf-8" }));
    Object.assign(document.createElement("a"), { href: url, download: `${nombreArchivo}.csv` }).click();
    URL.revokeObjectURL(url);
  }
  async function exportarExcel() {
    setExportando(true);
    try {
      const r = await fetch(`${BASE}/api/exportar`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ nombre: nombreArchivo, columnas: columnas.map((c) => c.titulo), filas: matriz() }) });
      if (!r.ok) throw new Error();
      const url = URL.createObjectURL(await r.blob());
      Object.assign(document.createElement("a"), { href: url, download: `${nombreArchivo}.xlsx` }).click();
      URL.revokeObjectURL(url);
    } finally {
      setExportando(false);
    }
  }

  const pagina = table.state.pagination;
  const total = table.getFilteredRowModel().rows.length;
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {buscador && (
          <input type="search" placeholder="Buscar…" aria-label="Buscar en la tabla" value={(table.state.globalFilter as string) ?? ""}
            onChange={(e) => table.setGlobalFilter(e.target.value)}
            className="min-h-9 w-full rounded-lg border border-borde bg-panel px-3 text-sm sm:w-64" />
        )}
        {conSeleccion && seleccion.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg bg-acento/10 px-2 py-1 text-sm">
            <span>{seleccion.length} seleccionado{seleccion.length === 1 ? "" : "s"}</span>
            {acciones!(seleccion, () => table.resetRowSelection())}
          </div>
        )}
        <div className="ml-auto flex gap-1">
          <Boton variante="fantasma" onClick={exportarExcel} disabled={exportando || !total}>Excel</Boton>
          <Boton variante="fantasma" onClick={exportarCSV} disabled={!total}>CSV</Boton>
        </div>
      </div>
      <div className="relative -mx-4 overflow-x-auto sm:mx-0">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            {table.getHeaderGroups().map((g) => (
              <tr key={g.id} className="border-b border-borde text-left text-xs uppercase tracking-wide text-suave">
                {conSeleccion && (
                  <th className="w-8 px-2 py-2">
                    <input type="checkbox" aria-label="Seleccionar todo lo visible" checked={table.getIsAllPageRowsSelected()}
                      onChange={table.getToggleAllPageRowsSelectedHandler()} />
                  </th>
                )}
                {g.headers.map((h, i) => {
                  const orden = h.column.getIsSorted();
                  return (
                    <th key={h.id} className={cx("px-3 py-2 font-medium", columnas[i]?.derecha && "text-right", columnas[i]?.ocultarEnCelular && "hidden md:table-cell")}
                      aria-sort={orden === "asc" ? "ascending" : orden === "desc" ? "descending" : "none"}>
                      <button className="inline-flex items-center gap-1 uppercase hover:text-texto" onClick={h.column.getToggleSortingHandler()}>
                        <table.FlexRender header={h} />
                        <span aria-hidden="true">{orden === "asc" ? "▲" : orden === "desc" ? "▼" : ""}</span>
                      </button>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className={cx("border-b border-borde/60", alHacerClic && "cursor-pointer hover:bg-panel-2", row.getIsSelected() && "bg-acento/5")}
                onClick={() => alHacerClic?.(row.original)}>
                {conSeleccion && (
                  <td className="px-2 py-2" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" aria-label="Seleccionar fila" checked={row.getIsSelected()} onChange={row.getToggleSelectedHandler()} />
                  </td>
                )}
                {row.getAllCells().map((cell, i) => (
                  <td key={cell.id} className={cx("px-3 py-2 align-top", columnas[i]?.derecha && "cifra text-right", columnas[i]?.ocultarEnCelular && "hidden md:table-cell")}>
                    <table.FlexRender cell={cell} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {total === 0 && <div className="py-8 text-center text-sm text-suave">{vacio ?? "No hay filas para mostrar."}</div>}
      </div>
      {total > pagina.pageSize && (
        <div className="flex items-center justify-between text-sm text-suave">
          <span>{pagina.pageIndex * pagina.pageSize + 1}–{Math.min(total, (pagina.pageIndex + 1) * pagina.pageSize)} de {total}</span>
          <span className="flex gap-1">
            <Boton variante="secundario" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>Anterior</Boton>
            <Boton variante="secundario" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>Siguiente</Boton>
          </span>
        </div>
      )}
    </div>
  );
}
