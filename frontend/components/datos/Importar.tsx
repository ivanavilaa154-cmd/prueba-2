"use client";
// Asistente de importación: 1) subir el archivo, 2) decir qué columna es cada dato, 3) revisar errores y confirmar.
import { useCallback, useEffect, useState } from "react";
import { api, BASE } from "@/lib/api";
import { fechaHora, numero } from "@/lib/formato";
import { Aviso, Boton, Campo, Etiqueta, Selector, Tabla, Tarjeta, Vacio, cx } from "@/components/ui";

type Tipo = { tipo: string; titulo: string; campos: { campo: string; etiqueta: string; obligatorio: boolean }[] };
type Analisis = {
  lote_id: number; encabezados: string[]; muestra: Record<string, unknown>[]; filas: number;
  campos: Tipo["campos"]; mapeo: Record<string, string | null>; mapeo_recordado: boolean;
  ya_importado: { lote: number; fecha: string; filas: number } | null;
};
type Validacion = { lote_id: number; filas: number; validas: number; con_error: number; errores: { fila: number; error: string }[];
  productos_no_encontrados: [string, number][] };
type Resultado = { importadas: number; duplicadas?: number; mensaje: string };
type Lote = { id: number; tipo: string; origen: string; nombre_archivo: string | null; estado: string; filas_total: number; filas_ok: number;
  filas_error: number; filas_duplicadas: number; mensaje: string | null; created_at: string; usuario: string | null };

const PASOS = ["Archivo", "Columnas", "Revisar y confirmar"];

export function Importar() {
  const [tipos, setTipos] = useState<Tipo[]>([]);
  const [tipo, setTipo] = useState("ventas");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [analisis, setAnalisis] = useState<Analisis | null>(null);
  const [mapeo, setMapeo] = useState<Record<string, string | null>>({});
  const [validacion, setValidacion] = useState<Validacion | null>(null);
  const [resultado, setResultado] = useState<Resultado | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [lotes, setLotes] = useState<Lote[]>([]);
  const paso = resultado ? 3 : validacion ? 2 : analisis ? 1 : 0;

  const cargarLotes = useCallback(() => api<Lote[]>("/importar/lotes").then(setLotes).catch(() => {}), []);
  useEffect(() => {
    api<Tipo[]>("/importar/tipos").then(setTipos).catch((e) => setError(e.message));
    cargarLotes();
  }, [cargarLotes]);

  async function correr<T>(f: () => Promise<T>): Promise<T | undefined> {
    setOcupado(true);
    setError(null);
    try {
      return await f();
    } catch (e) {
      setError(e instanceof Error ? e.message : "No se pudo completar.");
    } finally {
      setOcupado(false);
    }
  }

  async function analizar() {
    if (!archivo) return;
    const form = new FormData();
    form.append("tipo", tipo);
    form.append("archivo", archivo);
    const a = await correr(() => api<Analisis>("/importar/analizar", { formulario: form }));
    if (a) {
      setAnalisis(a);
      setMapeo(a.mapeo);
    }
  }
  async function validar() {
    if (!analisis) return;
    const v = await correr(() => api<Validacion>(`/importar/${analisis.lote_id}/validar`, { metodo: "POST", cuerpo: { mapeo } }));
    if (v) setValidacion(v);
  }
  async function confirmar() {
    if (!analisis) return;
    const r = await correr(() => api<Resultado>(`/importar/${analisis.lote_id}/confirmar`, { metodo: "POST" }));
    if (r) {
      setResultado(r);
      cargarLotes();
    }
  }
  function reiniciar() {
    setArchivo(null);
    setAnalisis(null);
    setValidacion(null);
    setResultado(null);
    setError(null);
  }

  const actual = tipos.find((t) => t.tipo === tipo);
  return (
    <div className="grid grid-cols-1 gap-4">
      <ol className="flex flex-wrap gap-2 text-sm" aria-label="Pasos">
        {PASOS.map((p, i) => (
          <li key={p} aria-current={i === Math.min(paso, 2) ? "step" : undefined}
            className={cx("rounded-full px-3 py-1", i === Math.min(paso, 2) ? "bg-acento text-acento-texto" : i < paso ? "bg-ok/15 text-ok" : "bg-panel-2 text-suave")}>
            {i + 1}. {p}
          </li>
        ))}
      </ol>
      {error && <Aviso tipo="error">{error}</Aviso>}

      {paso === 0 && (
        <Tarjeta titulo="¿Qué querés importar?">
          <div className="grid gap-4 sm:grid-cols-2">
            <Campo etiqueta="Tipo de datos">
              <Selector value={tipo} onChange={(e) => setTipo(e.target.value)}>
                {tipos.map((t) => <option key={t.tipo} value={t.tipo}>{t.titulo}</option>)}
              </Selector>
            </Campo>
            <Campo etiqueta="Archivo (Excel .xlsx o CSV)" ayuda="Hasta 200.000 filas. Si reimportás el mismo archivo, no se duplica nada.">
              <input type="file" accept=".xlsx,.xlsm,.csv,.txt" onChange={(e) => setArchivo(e.target.files?.[0] ?? null)}
                className="text-sm file:mr-3 file:rounded-lg file:border file:border-borde file:bg-panel file:px-3 file:py-1.5 file:text-sm" />
            </Campo>
          </div>
          {actual && (
            <p className="mt-3 text-sm text-suave">
              Necesita: {actual.campos.filter((c) => c.obligatorio).map((c) => c.etiqueta.toLowerCase()).join(", ")}.
              {" "}Opcional: {actual.campos.filter((c) => !c.obligatorio).map((c) => c.etiqueta.toLowerCase()).join(", ") || "nada más"}.
              {" "}<a className="text-acento underline" href={`${BASE}/api/importar/plantilla/${tipo}`}>Bajar planilla modelo</a>
            </p>
          )}
          <div className="mt-4"><Boton disabled={!archivo || ocupado} onClick={analizar}>{ocupado ? "Leyendo…" : "Siguiente"}</Boton></div>
        </Tarjeta>
      )}

      {paso === 1 && analisis && (
        <Tarjeta titulo={`¿Qué columna es cada dato? · ${numero(analisis.filas)} filas`}>
          {analisis.ya_importado && (
            <div className="mb-3"><Aviso tipo="alerta">
              Este mismo archivo ya se importó el {fechaHora(analisis.ya_importado.fecha)} ({numero(analisis.ya_importado.filas)} registros).
              Podés seguir: lo que ya está cargado no se duplica.
            </Aviso></div>
          )}
          {analisis.mapeo_recordado && <p className="mb-3 text-sm text-suave">Usamos las columnas que elegiste la última vez para este formato de archivo.</p>}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {analisis.campos.map((c) => (
              <Campo key={c.campo} etiqueta={`${c.etiqueta}${c.obligatorio ? " *" : ""}`}>
                <Selector value={mapeo[c.campo] ?? ""} onChange={(e) => setMapeo({ ...mapeo, [c.campo]: e.target.value || null })}>
                  <option value="">{c.obligatorio ? "Elegí una columna" : "No está en el archivo"}</option>
                  {analisis.encabezados.map((h) => <option key={h} value={h}>{h}</option>)}
                </Selector>
              </Campo>
            ))}
          </div>
          <h3 className="mt-5 mb-2 text-sm font-medium">Primeras filas del archivo</h3>
          <Tabla columnas={analisis.encabezados}>
            {analisis.muestra.map((f, i) => (
              <tr key={i}>{analisis.encabezados.map((h) => <td key={h} className="whitespace-nowrap">{String(f[h] ?? "")}</td>)}</tr>
            ))}
          </Tabla>
          <div className="mt-4 flex gap-2">
            <Boton variante="secundario" onClick={reiniciar}>Volver</Boton>
            <Boton disabled={ocupado} onClick={validar}>{ocupado ? "Revisando…" : "Revisar filas"}</Boton>
          </div>
        </Tarjeta>
      )}

      {paso === 2 && validacion && analisis && (
        <Tarjeta titulo="Revisión">
          <div className="flex flex-wrap gap-2">
            <Etiqueta tono="ok">✓ {numero(validacion.validas)} filas listas</Etiqueta>
            {validacion.con_error > 0 && <Etiqueta tono="peligro">✕ {numero(validacion.con_error)} con error</Etiqueta>}
          </div>
          {validacion.productos_no_encontrados.length > 0 && (
            <div className="mt-3"><Aviso tipo="alerta">
              Productos que no reconocemos: {validacion.productos_no_encontrados.slice(0, 8).map(([p, n]) => `${p} (${n})`).join(", ")}
              {validacion.productos_no_encontrados.length > 8 ? "…" : ""}. Importá primero los productos o emparejalos en Catálogo.
            </Aviso></div>
          )}
          {validacion.errores.length > 0 && (
            <>
              <h3 className="mt-4 mb-2 text-sm font-medium">Filas con error</h3>
              <Tabla columnas={["Fila", "Problema"]}>
                {validacion.errores.slice(0, 50).map((e) => <tr key={e.fila}><td className="w-16">{e.fila}</td><td>{e.error}</td></tr>)}
              </Tabla>
              <a className="mt-2 inline-block text-sm text-acento underline" href={`${BASE}/api/importar/${analisis.lote_id}/errores.csv`}>
                Bajar las filas con error para corregirlas
              </a>
            </>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <Boton variante="secundario" onClick={() => setValidacion(null)}>Cambiar columnas</Boton>
            <Boton disabled={ocupado || validacion.validas === 0} onClick={confirmar}>
              {ocupado ? "Importando…" : `Importar ${numero(validacion.validas)} filas`}
            </Boton>
          </div>
        </Tarjeta>
      )}

      {paso === 3 && resultado && (
        <Tarjeta titulo="Listo">
          <Aviso tipo="ok">{resultado.mensaje}. Los indicadores se recalculan en segundo plano (tarda un minuto).</Aviso>
          <div className="mt-4"><Boton onClick={reiniciar}>Importar otro archivo</Boton></div>
        </Tarjeta>
      )}

      <Tarjeta titulo="Últimas importaciones">
        {lotes.length === 0 ? <Vacio titulo="Todavía no importaste nada" /> : (
          <Tabla columnas={["Fecha", "Tipo", "Archivo", "Resultado", "Quién"]}>
            {lotes.map((l) => (
              <tr key={l.id}>
                <td className="whitespace-nowrap">{fechaHora(l.created_at)}</td>
                <td>{tipos.find((t) => t.tipo === l.tipo)?.titulo ?? l.tipo}</td>
                <td className="max-w-[16rem] truncate">{l.nombre_archivo ?? l.origen}</td>
                <td>{l.estado === "importado" ? l.mensaje ?? `${numero(l.filas_ok)} registros` :
                  <Etiqueta tono={l.estado === "con_errores" ? "peligro" : "gris"}>{l.estado === "con_errores" ? "Con errores, sin importar" : "Sin confirmar"}</Etiqueta>}</td>
                <td>{l.usuario ?? "Sistema"}</td>
              </tr>
            ))}
          </Tabla>
        )}
      </Tarjeta>
    </div>
  );
}
