# Retail — criterios de aceptación (sección 17)

Cada criterio tiene una prueba automatizada. Se corren todas con `cd backend && pytest -q tests/test_retail_*.py`.
Tiempos con la demo completa (13 meses, ~187.000 tickets): `python -m app.retail.tiempos --url http://localhost:8000 --clave demo-retail-2026`.

| Criterio | Prueba | Estado |
|---|---|---|
| La venta promedio diaria excluye los días sin stock | `test_retail_calculos.py::test_vpd_excluye_dias_sin_stock`, `test_retail_demo.py::test_faltante_conocido_excluido_de_la_vpd` | ✓ |
| La cantidad sugerida respeta horizonte, stock de seguridad, tránsito, pedidos abiertos y múltiplo de bulto | `test_retail_calculos.py::test_cantidad_sugerida_con_calculo_manual`, `::test_horizonte_con_calculo_manual` | ✓ |
| En modelo mixto se transfiere antes que comprar y el origen no queda bajo su mínimo | `test_retail_reposicion.py::test_mixto_transfiere_antes_de_comprar_sin_dejar_al_origen_bajo_su_minimo` | ✓ |
| En modelo centralizado ninguna sucursal genera OC | `test_retail_reposicion.py::test_centralizado_ninguna_sucursal_genera_oc` | ✓ |
| Las OC respetan el pedido mínimo o proponen completarlo | `test_retail_reposicion.py::test_oc_respeta_pedido_minimo_o_propone_completarlo` | ✓ |
| Las aprobaciones respetan los límites de monto por rol | `test_retail_reposicion.py::test_aprobacion_respeta_limites_por_rol`, `test_retail_base.py::test_limites_de_aprobacion` | ✓ |
| La clase ABC suma exactamente 100 % y coincide con el cálculo manual | `test_retail_calculos.py::test_abc_suma_100_y_coincide_con_calculo_manual`, `test_retail_ventas.py::test_pareto_suma_100_y_coincide_con_calculo_manual` | ✓ |
| Las ventas deflactadas coinciden con el cálculo manual | `test_retail_ventas.py::test_ventas_deflactadas_coinciden_con_calculo_manual` | ✓ |
| La ganancia por canal descuenta comisiones y envíos | `test_retail_canales.py::test_ganancia_real_descuenta_comisiones_envios_medios_y_publicidad`, `test_retail_precios.py::test_canal_online_suma_sus_costos` | ✓ |
| Un encargado no ve sucursales no asignadas; nadie ve otra empresa | `test_retail_base.py::test_encargado_solo_ve_sus_sucursales`, `::test_una_empresa_no_ve_a_otra`, `::test_la_app_no_saltea_rls`, `test_retail_demo.py::test_encargado_no_ve_metricas_de_otras_sucursales`, `test_retail_ventas.py::test_encargado_solo_ve_su_sucursal_en_ventas` | ✓ |
| Reimportar el mismo archivo no duplica ventas | `test_retail_importar.py::test_reimportar_el_mismo_archivo_no_duplica_ventas`, `test_retail_odoo.py::test_sincroniza_tickets_pagos_productos_y_stock_sin_duplicar` | ✓ |
| Cada alerta muestra impacto en pesos, explicación y acción | `test_retail_avisos.py::test_cada_alerta_tiene_impacto_explicacion_y_accion` | ✓ |
| El copiloto no responde cifras que no vengan de sus herramientas | `test_retail_copiloto.py::test_responde_con_cifras_de_las_herramientas`, `::test_las_herramientas_respetan_sucursales_y_permisos` (herramientas predefinidas, sin SQL libre, con RLS; la regla va en el prompt de sistema) | ✓ (la respuesta final la redacta el modelo: se verifica con el cliente de IA falso) |
| Todas las pantallas cargan en menos de 3 s con la demo | `test_retail_aceptacion.py::test_todas_las_pantallas_cargan_en_menos_de_3_segundos` (demo reducida) y `app.retail.tiempos` (demo completa) | ✓ |

## Tiempos medidos con la demo completa (28/09/2026)

| Pantalla | Segundos |
|---|---|
| Inicio | 0,62 |
| Comprar y reponer | 0,35 |
| Detalle de producto | 0,30 |
| Transferencias y OC | 0,96 |
| Ventas · ganadores | 1,30 |
| Ventas · Pareto | 0,93 |
| Ventas · inflación | 1,30 |
| Ventas · ticket y tráfico | 1,68 |
| Precios | 0,55 |
| Caja y control | 0,94 |
| Avisos | 0,03 |
| Datos (importar, catálogo, documentos, conexiones) | ≤ 0,04 |
| Configuración | 0,09 |
