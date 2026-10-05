// Navegación lateral (sección 15 del documento). «llega» marca una sección todavía no construida (se muestra «pronto»).
// modo: solo si la empresa tiene ese modo (comercio o distribuidor); permiso: solo si el rol lo tiene.
export type Seccion = { ruta: string; nombre: string; llega?: string; que_hace: string; modulo?: string; modo?: string; permiso?: string };

// Distribuidor o marca (13.3): solo su panel agregado y anónimo, los pedidos que le envían y su cuenta.
export const SECCIONES_DISTRIBUIDOR: Seccion[] = [
  { ruta: "/panel/", nombre: "Panel de marcas",
    que_hace: "Sell-out, cobertura, quiebres, participación, promociones y oportunidades, agregados y anónimos; y los pedidos de tus clientes." },
  { ruta: "/configuracion/", nombre: "Mi cuenta", que_hace: "Tu clave y el segundo factor." },
];

export const SECCIONES: Seccion[] = [
  { ruta: "/", nombre: "Inicio", que_hace: "Resumen del día, tarjetas clave y acciones con botón." },
  { ruta: "/tablero/", nombre: "Mi tablero",
    que_hace: "Vista por rol (Dirección, Comercial, Sucursal, Marketing, Finanzas): indicadores, avisos por plata en juego y pronóstico con rango." },
  { ruta: "/mi-cartera/", nombre: "Mi cartera", modo: "distribuidor", permiso: "ver_cartera",
    que_hace: "Tu ruta de hoy con qué ofrecer a cada cliente, los clientes a recuperar, tu meta y la deuda de tu cartera." },
  { ruta: "/clientes/", nombre: "Clientes", modo: "distribuidor", permiso: "ver_clientes_b2b",
    que_hace: "Clientes que dejaron de comprar o están en riesgo, con la plata que se deja de facturar; Pareto de clientes y productos." },
  { ruta: "/vendedores/", nombre: "Vendedores", modo: "distribuidor", permiso: "ver_vendedores",
    que_hace: "Ventas, margen, descuentos y metas por vendedor; objetivos de las marcas representadas." },
  { ruta: "/rutas/", nombre: "Rutas", modo: "distribuidor", permiso: "ver_vendedores",
    que_hace: "Visitas planificadas contra realizadas, efectividad, clientes sin visita, cobertura por zona y armado de rutas." },
  { ruta: "/pedidos/", nombre: "Pedidos y entregas", modo: "distribuidor", permiso: "ver_ventas",
    que_hace: "Pedidos por estado, entregas completas, parciales y rechazos; lo que no se facturó por faltantes." },
  { ruta: "/marcas/", nombre: "Marcas", modo: "distribuidor", permiso: "ver_ventas",
    que_hace: "Venta, cobertura y mix por marca representada, y los objetivos con la bonificación en riesgo." },
  { ruta: "/cuenta-corriente/", nombre: "Cuenta corriente", modo: "distribuidor", permiso: "ver_cuenta_corriente",
    que_hace: "Deuda por cliente y antigüedad, clientes que compran con deuda vencida o pasan su límite, compromisos de pago." },
  { ruta: "/comprar/", nombre: "Comprar y reponer",
    que_hace: "Qué te falta, cuándo se agota cada producto y cuánto comprar, con semáforo y explicación del cálculo." },
  { ruta: "/transferencias/", nombre: "Transferencias y OC",
    que_hace: "Transferencias y órdenes de compra sugeridas, aprobaciones por monto y recepción de mercadería." },
  { ruta: "/plata-parada/", modulo: "avanzado", nombre: "Plata parada",
    que_hace: "Capital inmovilizado en stock, sobrestock y productos que dejaron de venderse." },
  { ruta: "/vencimientos/", modulo: "avanzado", nombre: "Vencimientos y ofertas",
    que_hace: "Lotes que no llegan a venderse antes de vencer y la oferta mínima para rescatarlos." },
  { ruta: "/ventas/", nombre: "Ventas y ganadores",
    que_hace: "Productos ganadores, Pareto ABC, ventas ajustadas por inflación, ticket y tráfico." },
  { ruta: "/precios/", nombre: "Precios",
    que_hace: "Aumentos de proveedores, remarcación priorizada, margen erosionado y etiquetas de góndola." },
  { ruta: "/sucursales/", modulo: "avanzado", nombre: "Sucursales",
    que_hace: "Comparativos entre sucursales, matriz producto × sucursal, precios distintos y ajustes de stock." },
  { ruta: "/canales/", modulo: "avanzado", nombre: "Canales",
    que_hace: "Ganancia real por canal (comisiones y envíos), stock unificado y sobreventa online." },
  { ruta: "/caja/", nombre: "Caja y control", modo: "comercio",
    que_hace: "Anulaciones, devoluciones, descuentos manuales y valores atípicos por cajero y turno." },
  { ruta: "/proveedores/", modulo: "avanzado", nombre: "Proveedores",
    que_hace: "Días de visita, demoras, pedidos mínimos, nivel de servicio y rentabilidad por proveedor." },
  { ruta: "/pronosticos/", nombre: "Pronósticos",
    que_hace: "Venta por sucursal, canal y día con su rango, curva del año con eventos, afluencia por hora y cajas por turno." },
  { ruta: "/finanzas/", modulo: "avanzado", nombre: "Finanzas",
    que_hace: "Flujo de caja proyectado a 90 días y riesgo de cobro de las cuentas corrientes." },
  { ruta: "/modelos/", nombre: "Salud de los pronósticos",
    que_hace: "Cuánto se equivoca cada pronóstico, hacia qué lado y si el rango de confianza se cumple; calidad de los datos." },
  { ruta: "/avisos/", nombre: "Avisos",
    que_hace: "Bandeja de avisos con prioridad, impacto en pesos, explicación y acción, más el resumen diario por email." },
  { ruta: "/copiloto/", modulo: "avanzado", nombre: "Copiloto",
    que_hace: "Preguntale a tus datos en español; responde solo con cifras de sus herramientas." },
  { ruta: "/calidad/", nombre: "Calidad de datos",
    que_hace: "Puntaje de confianza de tus datos, problemas a corregir (stock negativo, costos viejos, duplicados…) y lo que perdés en faltantes." },
  { ruta: "/datos/", nombre: "Datos",
    que_hace: "Importar Excel o CSV, conectar la caja, leer facturas y listas con IA, y emparejar el catálogo." },
  { ruta: "/configuracion/", nombre: "Configuración", que_hace: "Empresa, sucursales, canales, usuarios, límites, auditoría y tu cuenta." },
];


// Vendedor y cobranzas solo usan las pantallas del modo distribuidor (la base les cierra el resto).
export const ROLES_SOLO_DISTRIBUIDOR = ["vendedor", "cobranzas"];
export const INICIO_POR_ROL: Record<string, string> = { vendedor: "/mi-cartera/", cobranzas: "/cuenta-corriente/" };
