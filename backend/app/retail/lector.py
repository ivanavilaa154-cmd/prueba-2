"""Lector de documentos con IA (sección 5.3): facturas, remitos y listas de precios en PDF o foto.

1. Claude lee el documento y devuelve datos estructurados (proveedor, número, fecha y cada línea con su confianza).
2. Cada línea se empareja con el catálogo (código del proveedor, alias aprendidos, similitud de texto).
3. Nada se carga solo: la persona revisa, corrige y confirma. Lo confirmado se guarda como alias para la próxima vez.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from .. import config
from . import catalogo, db

CARPETA = Path(__file__).resolve().parents[2] / "documentos" / "leidos"
TIPOS_ARCHIVO = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
CONFIANZA_BAJA = 0.7


class LineaLeida(BaseModel):
    codigo: str | None = Field(description="Código del artículo del proveedor o código de barras, tal como figura; null si no hay")
    descripcion: str = Field(description="Descripción del artículo tal como figura en el documento")
    cantidad: float | None = Field(description="Unidades (no bultos: si dice bultos y unidades por bulto, multiplicar). null en listas de precios")
    costo_unitario: float | None = Field(description="Precio unitario neto de bonificaciones, sin IVA si está discriminado")
    lote: str | None = None
    vencimiento: str | None = Field(default=None, description="Fecha de vencimiento en formato AAAA-MM-DD, si figura")
    confianza: float = Field(description="0 a 1: qué tan seguro estás de haber leído bien esta línea (baja si está borrosa, cortada o manuscrita)")


class DocumentoLeido(BaseModel):
    tipo: str = Field(description="factura, remito o lista_precios")
    proveedor: str | None = Field(description="Razón social del emisor")
    cuit: str | None = Field(description="CUIT del emisor, solo dígitos")
    numero: str | None = Field(description="Número del comprobante (ej. 0003-00012345)")
    fecha: str | None = Field(description="Fecha del comprobante AAAA-MM-DD")
    vigencia_desde: str | None = Field(description="En listas de precios: desde cuándo rige, AAAA-MM-DD")
    total: float | None = None
    lineas: list[LineaLeida]
    observaciones: str | None = Field(description="Lo que no se pudo leer o conviene revisar, en una frase; null si nada")


INSTRUCCIONES = """Leés documentos comerciales de proveedores de comercios minoristas de Argentina (facturas, remitos y listas de precios).
Extraé los datos tal como figuran, sin inventar: si un dato no está o no se lee, dejalo en null y bajá la confianza de esa línea.
Los números usan coma decimal y punto de miles (1.234,56 = 1234.56). Devolvé una línea por artículo; ignorá subtotales, percepciones e impuestos."""


class ErrorLector(Exception):
    pass


def _cliente():
    import anthropic  # importación diferida: las pruebas usan un cliente falso
    return anthropic.Anthropic()


def extraer(contenido: bytes, nombre: str, tipo: str, cliente=None) -> DocumentoLeido:
    extension = Path(nombre).suffix.lower()
    if extension not in TIPOS_ARCHIVO:
        raise ErrorLector("Subí un PDF o una foto (JPG, PNG o WEBP). Las listas en Excel se cargan desde Importar archivos.")
    import anthropic
    datos = base64.standard_b64encode(contenido).decode("ascii")
    media = TIPOS_ARCHIVO[extension]
    bloque = ({"type": "document", "source": {"type": "base64", "media_type": media, "data": datos}} if media == "application/pdf"
              else {"type": "image", "source": {"type": "base64", "media_type": media, "data": datos}})
    pedido = {"factura": "Es una factura de compra.", "remito": "Es un remito de entrega.", "lista_precios": "Es una lista de precios del proveedor."}[tipo]
    try:
        cliente = cliente or _cliente()
        r = cliente.messages.parse(
            model=config.ANTHROPIC_MODEL, max_tokens=16000, system=INSTRUCCIONES,
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": [bloque, {"type": "text", "text": f"{pedido} Extraé todos sus datos."}]}],
            output_format=DocumentoLeido,
        )
    except anthropic.AuthenticationError:
        raise ErrorLector("Falta configurar la clave de la IA (ANTHROPIC_API_KEY en backend/.env).")
    except anthropic.RateLimitError:
        raise ErrorLector("La IA está ocupada. Probá de nuevo en un minuto.")
    except anthropic.BadRequestError as e:
        raise ErrorLector(f"La IA no pudo abrir el archivo ({e.message}). Probá con otra foto o con el PDF original.")
    except anthropic.APIConnectionError:
        raise ErrorLector("No hay conexión con la IA. Revisá la conexión a internet y probá de nuevo.")
    except anthropic.APIStatusError as e:
        raise ErrorLector(f"La IA respondió con un error ({e.status_code}). Probá de nuevo más tarde.")
    if r.stop_reason == "refusal":
        raise ErrorLector("La IA no quiso leer este archivo. Revisá que sea un documento comercial.")
    if r.stop_reason == "max_tokens" or r.parsed_output is None:
        raise ErrorLector("El documento es demasiado largo para leerlo de una vez: dividilo en partes.")
    return r.parsed_output


def _fecha(texto: str | None) -> date | None:
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        return None


def proveedor_de(conn, leido: DocumentoLeido) -> dict | None:
    cuit = "".join(c for c in (leido.cuit or "") if c.isdigit())
    if cuit:
        for p in db.filas(conn, "SELECT id, razon_social, cuit FROM proveedores WHERE cuit IS NOT NULL"):
            if "".join(c for c in p["cuit"] if c.isdigit()) == cuit:
                return p
    if leido.proveedor:
        mejores = sorted(((catalogo.similitud(leido.proveedor, p["razon_social"]), p) for p in db.filas(conn, "SELECT id, razon_social, cuit FROM proveedores")),
                         key=lambda x: -x[0])
        if mejores and mejores[0][0] >= 0.6:
            return mejores[0][1]
    return None


def leer(conn, ctx, contenido: bytes, nombre: str, tipo: str, ubicacion_id: int | None, cliente=None) -> dict:
    leido = extraer(contenido, nombre, tipo, cliente)
    CARPETA.mkdir(parents=True, exist_ok=True)
    archivo = CARPETA / f"{hashlib.sha256(contenido).hexdigest()[:20]}{Path(nombre).suffix.lower()}"
    archivo.write_bytes(contenido)
    proveedor = proveedor_de(conn, leido)
    productos = db.filas(conn, "SELECT id, nombre, marca, codigo_interno, ean FROM productos WHERE activo")
    lineas = []
    for l in leido.lineas:
        codigo = (l.codigo or "").strip() or None
        e = catalogo.emparejar(conn, ean=codigo if codigo and codigo.isdigit() and len(codigo) in (8, 12, 13, 14) else None, codigo=codigo,
                               texto=l.descripcion, origen="proveedor", origen_id=proveedor["id"] if proveedor else None, productos=productos)
        lineas.append({**l.model_dump(), "producto_id": e.producto_id, "emparejado_por": e.metodo, "confianza_producto": e.confianza,
                       "candidatos": e.candidatos[:3], "revisar": l.confianza < CONFIANZA_BAJA or not e.producto_id})
    extraido = {**leido.model_dump(exclude={"lineas"}), "lineas": lineas}
    d = db.fila(conn, "INSERT INTO documentos_leidos (org_id, tipo, archivo, nombre_archivo, proveedor_id, extraido, ubicacion_id, created_by) "
                      "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (ctx.org_id, tipo, str(archivo), nombre, proveedor["id"] if proveedor else None, json.dumps(extraido, default=str), ubicacion_id, ctx.usuario_id))
    return {"id": d["id"], **extraido, "tipo": tipo, "proveedor_encontrado": proveedor}


def confirmar(conn, ctx, documento_id: int, proveedor_id: int, ubicacion_id: int | None, lineas: list[dict], orden_id: int | None = None) -> dict:
    """lineas: [{producto_id, codigo, descripcion, cantidad, costo_unitario, lote, vencimiento}] ya revisadas por la persona."""
    from .api_documentos import LineaRecibida, _oc, registrar_recepcion
    d = db.fila(conn, "SELECT * FROM documentos_leidos WHERE id=%s", (documento_id,))
    if not d or d["estado"] != "leido":
        raise ErrorLector("Ese documento ya se confirmó o se descartó.")
    if not db.fila(conn, "SELECT 1 FROM proveedores WHERE id=%s", (proveedor_id,)):
        raise ErrorLector("Elegí el proveedor.")
    validas = [l for l in lineas if l.get("producto_id")]
    if not validas:
        raise ErrorLector("No hay ninguna línea con producto asignado.")
    for l in validas:
        catalogo.guardar_alias(conn, ctx.org_id, l["producto_id"], "proveedor", proveedor_id, (l.get("codigo") or None), l.get("descripcion"), ctx.usuario_id)
    extraido = d["extraido"]
    if d["tipo"] == "lista_precios":
        vigencia = _fecha(extraido.get("vigencia_desde")) or _fecha(extraido.get("fecha")) or date.today()
        lista = db.fila(conn, "INSERT INTO listas_precios_proveedor (org_id, proveedor_id, vigencia_desde, origen, documento_id, created_by) "
                              "VALUES (%s,%s,%s,'documento',%s,%s) RETURNING id", (ctx.org_id, proveedor_id, vigencia, documento_id, ctx.usuario_id))["id"]
        with conn.cursor() as cur:
            for l in validas:
                if l.get("costo_unitario") in (None, ""):
                    continue
                anterior = db.fila(conn, "SELECT costo FROM producto_proveedores WHERE producto_id=%s AND proveedor_id=%s", (l["producto_id"], proveedor_id))
                cur.execute("INSERT INTO listas_precios_proveedor_lineas (org_id, lista_id, producto_id, codigo, descripcion, costo, costo_anterior) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s)", (ctx.org_id, lista, l["producto_id"], l.get("codigo"), l.get("descripcion"),
                                                              str(l["costo_unitario"]), anterior["costo"] if anterior else None))
                cur.execute("INSERT INTO producto_proveedores (org_id, producto_id, proveedor_id, costo, codigo_proveedor) VALUES (%s,%s,%s,%s,%s) "
                            "ON CONFLICT (producto_id, proveedor_id) DO UPDATE SET costo=EXCLUDED.costo, "
                            "codigo_proveedor=coalesce(EXCLUDED.codigo_proveedor, producto_proveedores.codigo_proveedor), updated_at=now()",
                            (ctx.org_id, l["producto_id"], proveedor_id, str(l["costo_unitario"]), l.get("codigo")))
        resultado = {"lista_id": lista, "mensaje": f"Lista de precios cargada: {len(validas)} costos actualizados"}
    else:
        if not ubicacion_id:
            raise ErrorLector("Elegí la sucursal que recibe la mercadería.")
        oc = _oc(conn, orden_id) if orden_id else None
        r = registrar_recepcion(conn, ctx, oc, proveedor_id, ubicacion_id,
                                [LineaRecibida(producto_id=l["producto_id"], ubicacion_id=ubicacion_id, cantidad=float(l.get("cantidad") or 0),
                                               costo=str(l["costo_unitario"]) if l.get("costo_unitario") not in (None, "") else None,
                                               lote=l.get("lote") or None, vencimiento=_fecha(l.get("vencimiento")))
                                 for l in validas], extraido.get("numero"), documento_id)
        resultado = {**r, "mensaje": f"Mercadería recibida: {len(validas)} productos"}
    with conn.cursor() as cur:
        cur.execute("UPDATE documentos_leidos SET estado='confirmado', proveedor_id=%s, ubicacion_id=%s, resultado=%s WHERE id=%s",
                    (proveedor_id, ubicacion_id, json.dumps({**resultado, "lineas": len(validas)}, default=str), documento_id))
    return resultado
