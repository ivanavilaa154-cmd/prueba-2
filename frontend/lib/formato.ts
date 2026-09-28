// Formatos argentinos: $ con punto de miles y coma decimal, fechas DD/MM/AAAA.
// Los importes llegan de la API como texto (nunca float) y se formatean sin pasar por aritmética.

export function pesos(valor: string | number | null | undefined, moneda = "ARS"): string {
  if (valor === null || valor === undefined || valor === "") return "—";
  const texto = String(valor);
  const negativo = texto.startsWith("-");
  const [entero, decimales = ""] = texto.replace("-", "").split(".");
  const miles = entero.replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  const signo = moneda === "USD" ? "US$" : "$";
  return `${negativo ? "-" : ""}${signo} ${miles},${(decimales + "00").slice(0, 2)}`;
}

export function fecha(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString("es-AR", { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function fechaHora(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${fecha(iso)} ${d.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" })}`;
}

export const ROLES: Record<string, string> = {
  dueno: "Dueño",
  comprador: "Comprador",
  encargado: "Encargado de sucursal",
  cajero: "Cajero / operativo",
  distribuidor: "Distribuidor / marca",
};

export const TIPO_UBICACION: Record<string, string> = { venta: "Sucursal", deposito: "Depósito", ambos: "Sucursal y depósito" };

export const MODELOS: Record<string, { nombre: string; explicacion: string }> = {
  centralizado: { nombre: "Centralizado", explicacion: "Todo entra al depósito central; las sucursales solo reciben transferencias." },
  descentralizado: { nombre: "Descentralizado", explicacion: "Cada sucursal genera sus propias órdenes de compra." },
  mixto: { nombre: "Mixto", explicacion: "Primero se transfiere desde donde sobra; si no alcanza, se compra." },
};

export const DOCUMENTOS: Record<string, string> = {
  orden_compra: "Órdenes de compra",
  transferencia: "Transferencias",
  ajuste_stock: "Ajustes de stock",
  precio: "Cambios de precio",
};

/** "500.000,50" → "500000.50". Con coma, los puntos son de miles; sin coma, un punto seguido de 3 dígitos también. */
export function parsearMonto(texto: string): string {
  const t = texto.replace(/[$\s]/g, "");
  if (t.includes(",")) return t.replaceAll(".", "").replace(",", ".");
  if (/^\d{1,3}(\.\d{3})+$/.test(t)) return t.replaceAll(".", "");
  return t;
}
