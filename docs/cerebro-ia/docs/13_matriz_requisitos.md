# 13 — Matriz de requisitos: columna canónica → KPIs

> Generado. Sirve para el onboarding: al mapear una columna se ve qué KPIs habilita. `O` = obligatoria, `A` = obligatoria en una variante, `o` = opcional.

## Por tabla

### `dim_campana`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `canal_marketing` | — | — | MKT-01 |
| `objetivo` | — | — | MKT-01, MKT-05, MKT-08, MKT-15 |

### `dim_cliente`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `region` | — | — | VEN-10 |
| `tipo_cliente` | — | — | VEN-10, VEN-15 |

### `dim_cuenta_contable`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `codigo_estandar` | FIN-06 | FIN-01, FIN-02, FIN-03, FIN-04, FIN-05, FIN-19, FIN-20, FIN-22 | MKT-22 |

### `dim_cuenta_tesoreria`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `es_disponible` | FIN-07, FIN-09, FIN-16 | — | — |

### `dim_producto`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `activo` | INV-06 | — | — |
| `categoria_n1` | — | — | INV-01, VEN-08 |
| `categoria_n2` | — | — | VEN-08 |
| `categoria_n3` | — | — | VEN-08 |
| `costo_estandar` | — | INV-01, VEN-27 | — |
| `dias_retiro_antes_vencimiento` | — | — | INV-20 |
| `proveedor_principal_id` | — | INV-15 | — |
| `temporada` | — | — | INV-18 |

### `dim_promocion`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `aporte_proveedor_monto` | — | — | VEN-26 |
| `costo_comunicacion` | — | — | VEN-26 |
| `fecha_fin` | VEN-26 | — | — |
| `fecha_inicio` | VEN-26 | — | — |

### `dim_proveedor`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `categoria_proveedor` | — | — | FIN-13 |
| `lead_time_dias_estandar` | — | INV-15 | — |

### `fct_ads_diario`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `alcance` | MKT-20 | — | — |
| `clics_enlace` | MKT-03, MKT-04, MKT-20 | — | — |
| `conversiones_plataforma` | — | MKT-05 | MKT-19 |
| `fecha` | MKT-01 | — | — |
| `frecuencia` | MKT-20 | — | — |
| `gasto` | MKT-01, MKT-02, MKT-04, MKT-05, MKT-06, MKT-07, MKT-08, MKT-09, MKT-19, MKT-22 | — | MKT-15, VEN-09 |
| `impresiones` | MKT-02, MKT-03, MKT-20 | — | — |
| `leads_plataforma` | — | MKT-05, MKT-15 | — |
| `valor_conversiones_plataforma` | MKT-06 | — | MKT-19 |

### `fct_asiento_linea`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `centro_costo_id` | — | — | FIN-04, FIN-05, FIN-22 |
| `cuenta_id` | FIN-06 | FIN-01, FIN-02, FIN-03, FIN-04, FIN-05, FIN-19, FIN-20, FIN-22 | — |
| `fecha_contable` | FIN-06 | FIN-01, FIN-02, FIN-03, FIN-04, FIN-05, FIN-19, FIN-20, FIN-22 | — |
| `saldo` | FIN-06 | FIN-01, FIN-02, FIN-03, FIN-04, FIN-05, FIN-19, FIN-20, FIN-22 | MKT-22 |

### `fct_atribucion_pedido`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `campana_id` | — | — | MKT-07, MKT-14, MKT-19 |
| `canal_marketing` | MKT-14 | MKT-21 | MKT-07, MKT-08, MKT-19, VEN-11 |

### `fct_cobro`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `fecha_cobro` | FIN-15 | — | — |
| `importe` | FIN-15 | — | — |
| `importe_retenciones` | — | — | FIN-21 |

### `fct_comprobante`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `categoria_gasto` | — | FIN-04, FIN-05, FIN-19, FIN-20, FIN-22 | — |
| `circuito` | FIN-13, FIN-18, FIN-21 | FIN-01, FIN-03, FIN-04, FIN-05, FIN-19, FIN-20, FIN-22 | — |
| `clase` | FIN-18 | FIN-01, FIN-03, FIN-04, FIN-05, FIN-19, FIN-20, FIN-22 | — |
| `codigo_autorizacion_fiscal` | — | — | FIN-18 |
| `estado` | FIN-12, FIN-21 | FIN-01, FIN-03, FIN-04, FIN-05, FIN-19, FIN-20, FIN-22 | — |
| `fecha_emision` | FIN-12, FIN-13, FIN-15, FIN-18, FIN-21 | FIN-01, FIN-03, FIN-04, FIN-05, FIN-19, FIN-20, FIN-22 | — |
| `importe_impuesto` | FIN-21 | — | — |
| `importe_neto` | — | FIN-01, FIN-03, FIN-04, FIN-05, FIN-19, FIN-20, FIN-22 | — |
| `importe_total` | FIN-12, FIN-13, FIN-15, FIN-18 | — | — |
| `numero` | FIN-18 | — | — |
| `punto_emision` | FIN-18 | — | — |
| `signo` | FIN-21 | — | — |

### `fct_conteo_inventario`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `cantidad_contada` | INV-13 | — | — |
| `cantidad_sistema` | INV-13 | — | — |

### `fct_devolucion`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `cantidad` | VEN-16 | — | — |
| `fecha_recepcion` | VEN-16 | — | LOG-18, VEN-01 |
| `fecha_solicitud` | — | — | LOG-18 |
| `importe_neto` | — | — | VEN-01, VEN-16 |
| `motivo` | — | LOG-15 | LOG-07, LOG-10, LOG-18, VEN-16 |
| `pedido_linea_id` | — | — | VEN-16 |

### `fct_documento_cxc`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `fecha_vencimiento` | FIN-10, FIN-11, FIN-15 | — | FIN-16 |
| `saldo_pendiente` | FIN-10, FIN-11, FIN-12, FIN-14, FIN-15 | — | FIN-16 |

### `fct_documento_cxp`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `fecha_vencimiento` | FIN-13 | — | FIN-16 |
| `saldo_pendiente` | FIN-13, FIN-14 | — | FIN-16 |

### `fct_email_campana`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `aperturas_unicas` | — | — | MKT-17 |
| `bajas` | — | — | MKT-17 |
| `clics_unicos` | MKT-17 | — | — |
| `entregados` | MKT-17 | — | — |
| `ingresos_atribuidos` | — | — | MKT-17 |

### `fct_envio`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `cantidad_intentos` | — | LOG-08 | LOG-17 |
| `costo_envio` | LOG-11, LOG-12, LOG-13, LOG-17, LOG-18, LOG-19 | — | — |
| `despacho_at` | LOG-01, LOG-03, LOG-05, LOG-10, LOG-11, LOG-14, LOG-17, LOG-19 | LOG-02 | — |
| `entrega_at` | LOG-04, LOG-05, LOG-06, LOG-07, LOG-17, LOG-19 | — | — |
| `es_devolucion` | LOG-18 | — | — |
| `estado` | LOG-01, LOG-03, LOG-04, LOG-05, LOG-06, LOG-07, LOG-08, LOG-09, LOG-10, LOG-14, LOG-17, LOG-18 | — | — |
| `fecha_limite_despacho` | LOG-03, LOG-14 | — | — |
| `fecha_promesa` | LOG-06, LOG-07, LOG-17 | — | — |
| `finalizado_at` | — | — | LOG-09 |
| `listo_despacho_at` | — | LOG-02 | — |
| `motivo_no_entrega` | — | — | LOG-09 |
| `pedido_at` | LOG-02, LOG-04, LOG-14 | — | — |
| `zona_destino` | — | — | LOG-04, LOG-05, LOG-11, LOG-17, LOG-19 |

### `fct_evento_envio`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `estado` | — | LOG-08 | — |
| `evento_at` | — | LOG-08 | LOG-05, LOG-09 |

### `fct_lead`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `canal_marketing` | — | — | MKT-15, MKT-16 |
| `estado` | MKT-16 | — | — |
| `fecha_conversion` | — | — | MKT-16 |
| `fecha_creacion` | MKT-16 | MKT-15 | — |
| `primer_contacto_at` | — | — | MKT-16 |
| `utm_campaign` | — | — | MKT-15 |

### `fct_liquidacion_pasarela`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `comision` | FIN-17 | — | VEN-09 |
| `costo_financiacion` | — | — | FIN-17 |
| `fecha_acreditacion` | — | — | FIN-16 |
| `importe_bruto` | FIN-17 | — | — |
| `importe_neto` | — | — | FIN-16 |
| `retenciones` | — | — | FIN-17, FIN-21 |

### `fct_lista_precio_proveedor`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `costo_neto` | — | VEN-27 | — |

### `fct_movimiento_stock`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `cantidad` | INV-14 | FIN-02 | — |
| `costo_unitario` | INV-14 | FIN-02, INV-03, INV-04 | — |
| `motivo_ajuste` | — | — | INV-14 |
| `tipo_movimiento` | INV-14 | FIN-02, INV-03, INV-04 | — |

### `fct_movimiento_tesoreria`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `fecha` | FIN-07, FIN-08, FIN-09, FIN-16 | — | — |
| `importe` | FIN-07, FIN-08, FIN-09, FIN-16 | — | — |
| `saldo_informado` | — | — | FIN-07, FIN-09 |
| `tipo` | FIN-08, FIN-09 | — | FIN-04, FIN-05, FIN-16, FIN-17 |

### `fct_oportunidad`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `esta_cerrada` | VEN-19, VEN-20, VEN-21, VEN-22 | — | — |
| `esta_ganada` | VEN-20, VEN-21, VEN-22 | — | — |
| `etapa` | VEN-19 | — | — |
| `fecha_cierre` | VEN-20, VEN-21, VEN-22 | — | — |
| `fecha_cierre_esperada` | VEN-19 | — | VEN-20, VEN-21, VEN-22 |
| `fecha_creacion` | VEN-21, VEN-22 | — | — |
| `importe` | VEN-19, VEN-20, VEN-22 | — | — |
| `probabilidad` | — | — | VEN-19 |
| `vendedor_id` | — | — | VEN-19, VEN-20 |

### `fct_oportunidad_historial_etapa`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `entrada_at` | VEN-21 | — | — |
| `etapa` | VEN-21 | — | — |

### `fct_orden_compra`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `estado` | INV-16, INV-19 | — | — |
| `fecha_emision` | INV-16, INV-17, INV-19 | INV-15 | — |

### `fct_orden_compra_linea`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `cantidad_pedida` | INV-16, INV-19 | — | — |
| `cantidad_recibida` | INV-16, INV-19 | — | — |
| `fecha_entrega_prometida` | INV-16, INV-17, INV-19 | — | — |

### `fct_pago`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `fecha_pago` | — | — | FIN-13 |
| `importe` | — | — | FIN-13 |

### `fct_pedido`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `canal_id` | VEN-05, VEN-09 | MKT-11 | VEN-01, VEN-02, VEN-07, VEN-11, VEN-17, VEN-18, VEN-24 |
| `cliente_id` | MKT-08, MKT-09, VEN-10, VEN-11, VEN-12, VEN-13, VEN-14, VEN-15 | — | VEN-23 |
| `comision_canal` | — | — | FIN-17, VEN-09 |
| `costo_envio_vendedor` | — | — | VEN-09 |
| `costo_financiacion` | — | — | FIN-17, VEN-09 |
| `es_fuente_verdad` | VEN-01, VEN-02, VEN-03, VEN-04 | — | — |
| `es_primera_compra` | — | — | VEN-03 |
| `estado` | INV-08, LOG-14, VEN-01, VEN-02, VEN-03, VEN-04, VEN-17 | — | — |
| `estado_pago` | VEN-17 | — | VEN-01, VEN-02 |
| `fecha_confirmacion` | LOG-14 | — | — |
| `fecha_pedido` | INV-09, MKT-08, MKT-09, VEN-01, VEN-02, VEN-03, VEN-04, VEN-05, VEN-06, VEN-07, VEN-10, VEN-11, VEN-12, VEN-13, VEN-14, VEN-15, VEN-24 | FIN-02, MKT-11 | — |
| `importe_bruto` | VEN-18 | — | — |
| `importe_descuento` | VEN-18 | — | VEN-25 |
| `importe_envio_cobrado` | — | — | LOG-12, LOG-13, VEN-09 |
| `importe_neto` | LOG-12, MKT-07, MKT-14, MKT-22, VEN-01, VEN-03, VEN-05, VEN-06, VEN-07, VEN-09, VEN-11, VEN-23, VEN-24, VEN-25 | — | — |
| `medio_pago` | — | — | FIN-17, VEN-17 |
| `pedido_at` | INV-21 | — | — |
| `utm_campaign` | — | — | MKT-07, MKT-14 |
| `utm_medium` | — | — | MKT-07, MKT-14 |
| `utm_source` | — | — | MKT-07, MKT-14 |
| `vendedor_id` | VEN-25 | — | VEN-07, VEN-15, VEN-18 |

### `fct_pedido_linea`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `cantidad` | INV-05, INV-06, INV-07, INV-08, INV-10, INV-12, INV-15, INV-18, INV-20, INV-21, LOG-07, VEN-04, VEN-16, VEN-26 | — | — |
| `cantidad_entregada` | INV-08, LOG-07 | — | — |
| `costo_total` | INV-11, INV-12, LOG-10, MKT-09, VEN-08, VEN-09, VEN-14, VEN-26 | FIN-02, FIN-03, FIN-05, FIN-19, FIN-20, INV-03, INV-04 | VEN-25 |
| `costo_unitario` | VEN-08 | — | — |
| `importe_neto` | INV-07, INV-11, INV-12, VEN-08, VEN-14, VEN-23, VEN-26 | — | VEN-01 |
| `producto_id` | INV-05, INV-06, INV-09, INV-12, INV-21, VEN-04, VEN-08, VEN-23 | — | VEN-01 |
| `promocion_id` | — | — | VEN-26 |

### `fct_precio_venta`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `precio` | VEN-27 | — | — |
| `vigente_desde` | VEN-27 | — | — |

### `fct_preparacion`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `fin_at` | LOG-16 | — | LOG-02 |
| `inicio_at` | LOG-16 | — | LOG-02 |
| `lineas_con_error` | — | LOG-15 | — |

### `fct_presupuesto`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `eerr_linea` | FIN-19 | — | — |
| `importe` | FIN-19, VEN-07 | — | VEN-25 |

### `fct_promocion_producto`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `producto_id` | VEN-26 | — | — |

### `fct_recepcion`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `cantidad_recibida` | — | INV-20 | — |
| `fecha_recepcion` | INV-16, INV-17 | INV-15 | INV-18 |
| `fecha_vencimiento` | — | INV-20 | — |

### `fct_stock_diario`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `costo_unitario` | FIN-14, INV-03, INV-04, INV-09, INV-10, INV-11 | INV-01, INV-20 | — |
| `stock_disponible` | INV-21 | — | — |
| `stock_en_transito` | — | — | INV-02, INV-05, INV-15 |
| `stock_fisico` | FIN-14, INV-01, INV-02, INV-03, INV-04, INV-05, INV-06, INV-07, INV-09, INV-10, INV-11, INV-15, INV-18 | — | — |
| `stock_reservado` | — | — | INV-02, INV-05, INV-06, INV-15 |

### `fct_stock_lote`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `cantidad` | — | INV-20 | — |
| `costo_unitario` | — | INV-20 | — |
| `fecha_vencimiento` | — | INV-20 | — |

### `fct_suscriptores_diario`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `altas` | MKT-18 | — | — |
| `bajas` | MKT-18 | — | — |
| `suscriptores_activos` | MKT-18 | — | — |

### `fct_web_diario`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `agregados_carrito` | MKT-12, MKT-13 | — | — |
| `canal_marketing` | — | MKT-21 | MKT-10, MKT-11 |
| `checkouts_iniciados` | MKT-12 | — | — |
| `dispositivo` | — | — | MKT-10 |
| `leads_web` | — | MKT-15 | — |
| `sesiones` | MKT-10, MKT-11, MKT-12 | MKT-21 | — |
| `transacciones` | MKT-12, MKT-13 | MKT-11 | MKT-11 |
| `usuarios` | — | — | MKT-10 |
| `vistas_producto` | MKT-12 | — | — |

### `parametro_reposicion`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `lead_time_dias` | — | INV-15 | — |
| `punto_pedido` | — | — | INV-15 |
| `stock_maximo` | — | — | INV-10, INV-15 |

### `ref.feriado`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `fecha` | — | — | VEN-06, VEN-07, VEN-24 |

### `ref.indice_precios`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `indice` | FIN-22 | — | VEN-06 |

### `ref.tipo_cambio`

| Columna | KPIs (O) | KPIs (A) | KPIs (o) |
|---|---|---|---|
| `valor` | — | — | MKT-01 |

## Columnas obligatorias por entidad (para publicar un mapping)

| Entidad | Columnas |
|---|---|
| `fct_pedido` | fecha_pedido, estado, importe_neto, moneda_orig |
| `fct_pedido_linea` | pedido_id, producto_id, cantidad, importe_neto |
| `fct_comprobante` | circuito, clase, fecha_emision, importe_neto, importe_total, estado |
| `fct_comprobante_linea` | comprobante_id, importe_neto |
| `fct_devolucion` | fecha_recepcion, cantidad |
| `fct_oportunidad` | etapa, importe, fecha_creacion, esta_cerrada |
| `fct_lead` | fecha_creacion, estado |
| `fct_presupuesto` | periodo, concepto, importe |
| `fct_asiento_linea` | fecha_contable, cuenta_id, debe, haber, estado |
| `fct_documento_cxc` | cliente_id, fecha_emision, importe_original, saldo_pendiente |
| `fct_documento_cxp` | proveedor_id, fecha_emision, importe_original, saldo_pendiente |
| `fct_cobro` | fecha_cobro, importe |
| `fct_pago` | fecha_pago, importe |
| `fct_movimiento_tesoreria` | cuenta_tesoreria_id, fecha, importe |
| `fct_liquidacion_pasarela` | fecha_operacion, importe_bruto, estado |
| `fct_movimiento_stock` | fecha, producto_id, deposito_id, tipo_movimiento, cantidad |
| `fct_stock_diario` | fecha, producto_id, deposito_id, stock_fisico |
| `fct_orden_compra` | proveedor_id, fecha_emision, estado |
| `fct_orden_compra_linea` | orden_compra_id, producto_id, cantidad_pedida |
| `fct_recepcion` | fecha_recepcion, producto_id, cantidad_recibida |
| `fct_conteo_inventario` | fecha, producto_id, cantidad_sistema, cantidad_contada |
| `fct_envio` | estado |
| `fct_evento_envio` | envio_id, evento_at, estado |
| `fct_preparacion` | pedido_id, fin_at |
| `fct_ads_diario` | fecha, plataforma, campana_id, gasto |
| `fct_web_diario` | fecha, sesiones |
| `fct_email_campana` | fecha_envio, entregados |
| `fct_suscriptores_diario` | fecha, suscriptores_activos |
| `dim_cliente` | nombre |
| `dim_producto` | nombre |
| `dim_deposito` | nombre, tipo |
| `dim_cuenta_contable` | codigo, nombre |
| `dim_cuenta_tesoreria` | nombre, tipo, moneda |
| `dim_campana` | plataforma, nombre |
| `ref.tipo_cambio` | fecha, moneda_origen, moneda_destino, serie, valor |
| `ref.indice_precios` | serie, periodo, indice |
| `ref.feriado` | fecha, pais |
| `fct_lista_precio_proveedor` | proveedor_id, fecha_vigencia_desde, costo_neto |
| `fct_precio_venta` | producto_id, precio, vigente_desde |
| `dim_promocion` | nombre, mecanica, fecha_inicio, fecha_fin |
| `fct_promocion_producto` | promocion_id, producto_id |
| `fct_stock_lote` | fecha, producto_id, deposito_id, lote, fecha_vencimiento, cantidad |
