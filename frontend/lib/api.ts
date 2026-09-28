// Llamadas a la API de Retail (/retail/api). La sesión viaja en una cookie httpOnly.
export const BASE = "/retail";

export class ErrorApi extends Error {
  constructor(public estado: number, mensaje: string) {
    super(mensaje);
  }
}

export async function api<T = unknown>(ruta: string, opciones: { metodo?: string; cuerpo?: unknown } = {}): Promise<T> {
  const r = await fetch(`${BASE}/api${ruta}`, {
    method: opciones.metodo ?? "GET",
    headers: opciones.cuerpo !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: opciones.cuerpo !== undefined ? JSON.stringify(opciones.cuerpo) : undefined,
    credentials: "same-origin",
  });
  let datos: unknown = null;
  try {
    datos = await r.json();
  } catch {
    datos = null;
  }
  if (!r.ok) {
    const detalle = (datos as { detail?: unknown } | null)?.detail;
    const mensaje = typeof detalle === "string" ? detalle : "No se pudo completar la operación. Probá de nuevo.";
    throw new ErrorApi(r.status, mensaje);
  }
  return datos as T;
}

export type Ubicacion = {
  id: number;
  nombre: string;
  tipo: "venta" | "deposito" | "ambos";
  direccion?: string | null;
  localidad?: string | null;
  codigo_externo?: string | null;
  activa?: boolean;
};
export type Canal = { id: number; codigo: string; nombre: string; activo?: boolean };
export type Plataforma = { id: number; tipo: string; nombre: string; canal_id: number; ubicacion_despacho_id?: number | null };
export type Empresa = {
  id: number;
  nombre: string;
  cuit: string | null;
  plan: string;
  zona_horaria: string;
  moneda: string;
  modelo_abastecimiento: "centralizado" | "descentralizado" | "mixto";
  consentimiento_datos: boolean;
  consentimiento_fecha: string | null;
};
export type Yo = {
  usuario: {
    id: number;
    nombre: string;
    email: string;
    rol: string | null;
    es_superadmin: boolean;
    segundo_factor: boolean;
    todas_ubicaciones: boolean;
  };
  empresa: Empresa | null;
  permisos: string[];
  ubicaciones: Ubicacion[];
  canales: Canal[];
  plataformas: Plataforma[];
};
