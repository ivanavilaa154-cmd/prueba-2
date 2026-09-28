"""Catálogo de la demo del NOA: categorías, subcategorías, marcas, presentaciones y precios de referencia (ARS, fin del período).

Los nombres son de ejemplo. Cada subcategoría: (nombre, perecedero, margen objetivo, proveedor, estacionalidad, [marcas], [(variante, presentación, precio)]).
Estacionalidad: "verano" (más venta dic-feb), "invierno" (más venta jun-ago) o None.
"""
from __future__ import annotations

CATEGORIAS = {
    "Bebidas": [
        ("Gaseosas", False, 0.30, "Distribuidora Andina", "verano", ["Cola Norte", "Pomelo Andino", "Lima Sol", "Naranja Valle"],
         [("{m}", "500 ml", 1350), ("{m}", "1,5 L", 2600), ("{m}", "2,25 L", 3400)]),
        ("Aguas", False, 0.32, "Distribuidora Andina", "verano", ["Agua Cumbre", "Agua Salteña"],
         [("{m} sin gas", "500 ml", 900), ("{m} sin gas", "2 L", 1600), ("{m} con gas", "1,5 L", 1500), ("{m} saborizada pomelo", "1,5 L", 2100)]),
        ("Jugos", False, 0.32, "Distribuidora Andina", "verano", ["Jugo Valle", "Jugo Cítrico"],
         [("{m} naranja", "1 L", 1900), ("{m} multifruta", "1 L", 1900), ("{m} en polvo naranja", "18 g", 450)]),
        ("Cervezas", False, 0.25, "Cervecería del Norte", "verano", ["Cerveza Salta", "Cerveza Quilmeña", "Cerveza Roja Andina"],
         [("{m} rubia", "1 L", 3100), ("{m} lata", "473 ml", 1800), ("{m} six pack lata", "6 x 473 ml", 10200)]),
        ("Vinos y aperitivos", False, 0.30, "Distribuidora Andina", "invierno", ["Bodega Cafayate", "Viñas del Valle", "Fernet Serrano"],
         [("{m} tinto", "750 ml", 4800), ("{m} blanco torrontés", "750 ml", 5200), ("{m} tetra tinto", "1 L", 2400)]),
    ],
    "Almacén": [
        ("Yerba mate", False, 0.22, "Yerbatera Misionera", "invierno", ["Yerba Tradición", "Yerba Suave", "Yerba Campo"],
         [("{m}", "500 g", 3300), ("{m}", "1 kg", 6300)]),
        ("Fideos y arroz", False, 0.28, "Molinos del NOA", None, ["Fideos Don Pepe", "Arroz Grano Largo", "Fideos Integral"],
         [("{m} tallarín", "500 g", 1300), ("{m} mostachol", "500 g", 1300), ("{m} largo fino", "1 kg", 2100), ("{m} guiseros", "500 g", 1250)]),
        ("Aceites", False, 0.20, "Almacén Mayorista NOA", None, ["Aceite Girasol Sur", "Aceite Mezcla Hogar"],
         [("{m}", "900 ml", 3600), ("{m}", "1,5 L", 5600)]),
        ("Azúcar y endulzantes", False, 0.18, "Almacén Mayorista NOA", None, ["Azúcar Ingenio Norte", "Endulzante Liviano"],
         [("{m}", "1 kg", 1500), ("{m} sobres", "50 u", 1900)]),
        ("Harinas y panificados", False, 0.26, "Molinos del NOA", "invierno", ["Harina 000 Molino", "Pan Lactal Casero", "Premezcla Bizcochuelo"],
         [("{m}", "1 kg", 1100), ("{m} grande", "550 g", 2900), ("{m}", "500 g", 1900)]),
        ("Conservas", False, 0.30, "Almacén Mayorista NOA", None, ["Conservas Valle", "Atún del Mar"],
         [("{m} tomate triturado", "520 g", 1150), ("{m} arvejas", "300 g", 950), ("{m} en aceite", "170 g", 2600), ("{m} duraznos", "820 g", 3300)]),
        ("Galletitas", False, 0.32, "Golosinas del Norte", None, ["Galletitas Crocante", "Galletitas Dulce Hogar", "Galletitas de Agua"],
         [("{m}", "150 g", 1100), ("{m} rellenas", "118 g", 1300), ("{m} paquete familiar", "400 g", 2600)]),
        ("Condimentos y salsas", False, 0.34, "Almacén Mayorista NOA", None, ["Mayonesa Clásica", "Ketchup Rojo", "Sal Fina"],
         [("{m}", "250 g", 1700), ("{m} doypack", "500 g", 2900)]),
    ],
    "Lácteos": [
        ("Leches", True, 0.18, "Lácteos del Valle", None, ["Leche La Vaquita", "Leche Valle Verde"],
         [("{m} entera sachet", "1 L", 1350), ("{m} descremada sachet", "1 L", 1350), ("{m} larga vida", "1 L", 1700), ("{m} en polvo", "400 g", 5200)]),
        ("Yogures", True, 0.28, "Lácteos del Valle", "verano", ["Yogur Cremoso", "Yogur Light Valle"],
         [("{m} frutilla", "190 g", 950), ("{m} vainilla bebible", "900 g", 2400), ("{m} con cereales", "165 g", 1250)]),
        ("Quesos", True, 0.26, "Lácteos del Valle", None, ["Queso Cremón", "Queso Rallado Norte", "Queso Untable"],
         [("{m}", "300 g", 3900), ("{m}", "150 g", 2100)]),
        ("Mantecas y cremas", True, 0.25, "Lácteos del Valle", "invierno", ["Manteca Valle", "Crema de Leche Tambo", "Dulce de Leche Colonial"],
         [("{m}", "200 g", 2300), ("{m}", "400 g", 3400)]),
    ],
    "Fiambrería": [
        ("Fiambres", True, 0.35, "Fiambres Salteños", None, ["Jamón Cocido Salteño", "Salame Colonia", "Mortadela Norte", "Paleta Cocida"],
         [("{m} feteado", "200 g", 3600), ("{m} al corte", "1 kg", 15500)]),
        ("Salchichas", True, 0.30, "Fiambres Salteños", "verano", ["Salchichas Viena", "Salchichas Parrilleras"],
         [("{m}", "6 u", 2100), ("{m}", "12 u", 3900)]),
    ],
    "Limpieza": [
        ("Lavandinas", False, 0.33, "Limpieza Total", None, ["Lavandina Brillo", "Lavandina Gel Hogar"],
         [("{m}", "1 L", 1100), ("{m}", "2 L", 1900)]),
        ("Detergentes", False, 0.33, "Limpieza Total", None, ["Detergente Limón", "Detergente Concentrado"],
         [("{m}", "500 ml", 1500), ("{m} repuesto", "750 ml", 2100)]),
        ("Ropa", False, 0.30, "Limpieza Total", None, ["Jabón en Polvo Nube", "Suavizante Algodón", "Jabón Líquido Nube"],
         [("{m}", "800 g", 4200), ("{m}", "3 L", 9800)]),
        ("Papeles", False, 0.30, "Limpieza Total", None, ["Papel Higiénico Suave", "Rollo de Cocina Absorbe", "Servilletas Blancas"],
         [("{m} 4 rollos", "4 x 30 m", 2600), ("{m} 12 rollos", "12 x 30 m", 7300)]),
    ],
    "Perfumería": [
        ("Cuidado capilar", False, 0.36, "Perfumería Norte", None, ["Shampoo Seda", "Acondicionador Seda", "Shampoo Anticaspa"],
         [("{m}", "400 ml", 4300), ("{m}", "200 ml", 2600)]),
        ("Higiene personal", False, 0.35, "Perfumería Norte", None, ["Jabón de Tocador Rosa", "Desodorante Fresh", "Crema Dental Blanca", "Cepillo Dental Medio"],
         [("{m}", "90 g", 1100), ("{m} pack", "3 u", 2900)]),
    ],
    "Golosinas": [
        ("Alfajores", False, 0.38, "Golosinas del Norte", "invierno", ["Alfajor Triple Norte", "Alfajor Maicena", "Alfajor Negro"],
         [("{m}", "unidad", 900), ("{m} caja", "6 u", 4800)]),
        ("Chocolates", False, 0.38, "Golosinas del Norte", "invierno", ["Chocolate Leche Cacao", "Chocolate Amargo Puna"],
         [("{m}", "25 g", 800), ("{m}", "100 g", 2700)]),
        ("Caramelos y chicles", False, 0.40, "Golosinas del Norte", None, ["Caramelos Frutales", "Chicles Menta", "Pastillas Limón"],
         [("{m}", "bolsa 150 g", 1400), ("{m}", "unidad", 350)]),
    ],
    "Cigarrillos": [
        ("Cigarrillos", False, 0.12, "Tabacalera Distribución", None, ["Cigarrillos Andes", "Cigarrillos Puna", "Cigarrillos Cumbre"],
         [("{m} box", "20 u", 3200), ("{m} común", "20 u", 3000), ("{m} mentolado", "20 u", 3300)]),
    ],
    "Congelados": [
        ("Hamburguesas y rebozados", True, 0.30, "Frío Sur Congelados", "verano", ["Hamburguesas Criollas", "Medallones de Pollo", "Milanesas de Soja"],
         [("{m}", "4 u", 3400), ("{m} caja", "12 u", 9200)]),
        ("Helados", True, 0.40, "Frío Sur Congelados", "verano", ["Helado Palito Norte", "Helado Pote Artesanal"],
         [("{m} frutilla", "unidad", 900), ("{m} chocolate", "unidad", 900), ("{m} dulce de leche", "1 L", 7200), ("{m} vainilla", "1 L", 7200)]),
        ("Vegetales congelados", True, 0.32, "Frío Sur Congelados", None, ["Vegetales del Campo", "Papas Prefritas Valle"],
         [("{m}", "400 g", 2500), ("{m}", "1 kg", 4800)]),
    ],
}

PROVEEDORES = [
    # razón social, días de visita (0 = lunes), demora (días), pedido mínimo $, bultos mínimos, condiciones
    ("Distribuidora Andina", [0, 3], 1, 250000, 0, "30 días"),
    ("Cervecería del Norte", [1, 4], 1, 300000, 10, "15 días"),
    ("Yerbatera Misionera", [2], 3, 150000, 0, "30 días"),
    ("Molinos del NOA", [1], 2, 180000, 0, "30 días"),
    ("Almacén Mayorista NOA", [0, 2, 4], 1, 200000, 0, "contado"),
    ("Golosinas del Norte", [3], 2, 120000, 0, "15 días"),
    ("Lácteos del Valle", [0, 2, 4], 1, 100000, 0, "7 días"),
    ("Fiambres Salteños", [1, 4], 1, 90000, 0, "7 días"),
    ("Limpieza Total", [2], 3, 160000, 0, "30 días"),
    ("Perfumería Norte", [], None, 140000, 0, "30 días"),     # proveedor sin días configurados (caso de borde)
    ("Tabacalera Distribución", [0, 3], 1, 200000, 0, "contado"),
    ("Frío Sur Congelados", [2], 2, 180000, 0, "15 días"),
]

UNIDADES_POR_BULTO = {"Gaseosas": 6, "Aguas": 6, "Jugos": 12, "Cervezas": 12, "Vinos y aperitivos": 6, "Yerba mate": 10,
                      "Fideos y arroz": 20, "Aceites": 12, "Azúcar y endulzantes": 10, "Harinas y panificados": 10, "Conservas": 24,
                      "Galletitas": 24, "Condimentos y salsas": 12, "Leches": 12, "Yogures": 12, "Quesos": 6, "Mantecas y cremas": 12,
                      "Fiambres": 4, "Salchichas": 10, "Lavandinas": 12, "Detergentes": 12, "Ropa": 6, "Papeles": 8,
                      "Cuidado capilar": 12, "Higiene personal": 24, "Alfajores": 24, "Chocolates": 20, "Caramelos y chicles": 30,
                      "Cigarrillos": 10, "Hamburguesas y rebozados": 8, "Helados": 12, "Vegetales congelados": 10}


def ean13(base12: str) -> str:
    suma = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(base12))
    return base12 + str((10 - suma % 10) % 10)


def productos() -> list[dict]:
    """~400 productos: marca × variante de cada subcategoría."""
    lista = []
    n = 0
    for categoria, subs in CATEGORIAS.items():
        for sub, perecedero, margen, proveedor, estacion, marcas, variantes in subs:
            # Marcas líderes + dos de segunda línea (propia del comercio y económica), más baratas.
            todas = [(m, m, 1.0) for m in marcas] + [(f"{sub} Norte Selección", "Norte Selección", 0.86),
                                                      (f"{sub} Precio Justo", "Precio Justo", 0.76)]
            for i, (nombre_marca, marca, factor) in enumerate(todas):
                for j, (fmt, presentacion, precio) in enumerate(variantes):
                    if factor < 1 and j >= 3:
                        continue   # la segunda línea tiene menos presentaciones
                    precio = precio * factor
                    n += 1
                    lista.append({
                        "codigo": f"P{n:04d}", "nombre": f"{fmt.format(m=nombre_marca)} {presentacion}", "marca": marca,
                        "categoria": categoria, "subcategoria": sub, "perecedero": perecedero, "margen": margen,
                        "proveedor": proveedor, "estacion": estacion, "presentacion": presentacion,
                        "precio": round(precio * (1 + 0.07 * ((i * 3 + j) % 4 - 1.5) / 1.5) / 10) * 10,
                        "ean": ean13(f"779{n:09d}"), "bulto": UNIDADES_POR_BULTO.get(sub, 12),
                    })
    # Elaboración propia y a granel: sin código de barras ni producto maestro (sección 5.5).
    for nombre, precio, unidad in PROPIOS:
        n += 1
        lista.append({"codigo": f"P{n:04d}", "nombre": nombre, "marca": "Elaboración propia", "categoria": "Panadería y rotisería",
                      "subcategoria": "Elaboración propia", "perecedero": True, "margen": 0.45, "proveedor": "Molinos del NOA",
                      "estacion": "invierno" if "Empanadas" in nombre else None, "presentacion": unidad, "precio": precio,
                      "ean": None, "bulto": 1, "unidad": "kg" if unidad == "kg" else "unidad"})
    return lista


PROPIOS = [("Pan francés", 2600, "kg"), ("Facturas surtidas docena", 6500, "docena"), ("Empanadas salteñas docena", 14400, "docena"),
           ("Tortilla a la parrilla", 700, "unidad"), ("Pizza muzzarella", 8900, "unidad"), ("Bizcochos de grasa", 3200, "kg"),
           ("Pollo al spiedo", 11500, "unidad"), ("Milanesas caseras", 12800, "kg"), ("Tamales", 2400, "unidad"),
           ("Humitas en chala", 2600, "unidad"), ("Sándwich de miga docena", 9600, "docena"), ("Chipá", 5200, "kg")]
