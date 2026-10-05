// Tipos y etiquetas del modo distribuidor (SPEC v2, 12B).
export type EstadoCliente = "activo" | "en_riesgo" | "perdido" | "sin_compras";
export const ESTADO_CLIENTE: Record<EstadoCliente, { texto: string; tono: "ok" | "alerta" | "peligro" | "gris" }> = {
  activo: { texto: "✓ Activo", tono: "ok" },
  en_riesgo: { texto: "▲ En riesgo", tono: "alerta" },
  perdido: { texto: "● Dejó de comprar", tono: "peligro" },
  sin_compras: { texto: "Sin compras en el año", tono: "gris" },
};

export type Oportunidad = { categoria_id: number; categoria: string; compran_parecidos: number; producto_id: number; producto: string;
  cantidad_sugerida: number; precio: number; ganancia_mes_estimada: number; explicacion: string };

export type FilaCliente = { cliente_id: number; cliente: string; razon_social: string; localidad: string | null; zona: string | null; canal: string | null;
  vendedor_id: number | null; vendedor: string | null; estado: EstadoCliente; intervalo: number | null; dias_sin_comprar: number | null;
  ultima_compra: string | null; proxima_esperada: string | null; pocas_compras: boolean; venta_mensual: number; ganancia_mensual: number;
  deja_de_facturar_mes: number; explicacion: string };

export type ResumenClientes = { total: number; activo: number; en_riesgo: number; perdido: number; sin_compras: number;
  deja_de_facturar_mes: number; en_juego_perdidos: number; en_juego_riesgo: number };

export type DeudaCliente = { cliente_id: number; cliente: string; vendedor_id: number | null; vendedor: string | null; a_vencer: number; d0_30: number;
  d31_60: number; d61_90: number; d90_mas: number; a_favor: number; saldo: number; vencido: number; dias_mayor_atraso: number;
  limite_credito: number | null; sigue_comprando: boolean; supera_limite: boolean; bloqueo_sugerido: boolean; ultima_compra: string | null;
  compromisos: { id: number; fecha: string; monto: string; estado: string; nota: string | null; incumplido: boolean }[]; alertas: string[] };

export const TRAMOS: [keyof DeudaCliente, string][] = [["a_vencer", "A vencer"], ["d0_30", "1–30 días"], ["d31_60", "31–60 días"],
  ["d61_90", "61–90 días"], ["d90_mas", "Más de 90"]];

export const PERIODOS = [["mes_actual", "Este mes"], ["mes", "Últimos 30 días"], ["90d", "Últimos 90 días"], ["anio", "Último año"]] as const;
