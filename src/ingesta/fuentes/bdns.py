"""
Conector a la BDNS (Base de Datos Nacional de Subvenciones).

API pública, sin autenticación:
  https://www.infosubvenciones.es/bdnstrans/api

Flujo:
  1. buscar_convocatorias()  → lista básica (id, numero, descripcion, nivel1, nivel2...)
  2. obtener_detalle()       → detalle completo (importe, plazo, lista de PDFs)
  3. obtener_candidatos()    → combina todo y devuelve CandidatoFuente listos para el pipeline
"""

import argparse
import json
import sys
import time
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ingesta.modelos import CandidatoFuente


def _json_utf8(respuesta: requests.Response) -> any:
    """Decodifica la respuesta JSON forzando UTF-8 (la BDNS no siempre declara charset)."""
    return json.loads(respuesta.content.decode("utf-8"))


def _campo_texto(campo) -> str:
    """Normaliza campos que pueden ser str o lista de dicts con 'descripcion'."""
    if not campo:
        return ""
    if isinstance(campo, str):
        return campo
    if isinstance(campo, list):
        return ", ".join(
            item.get("descripcion", str(item)) for item in campo if item
        )
    return str(campo)

BASE_URL = "https://www.infosubvenciones.es/bdnstrans/api"
VPD = "GE"
PAGE_SIZE = 100
PAUSA = 0.3  # segundos entre peticiones para no saturar el servidor

# Palabras clave de búsqueda para cada categoría del sistema.
# La BDNS no tiene categorías propias, así que buscamos por términos.
BUSQUEDAS = {
    "vivienda":    ["alquiler joven", "bono alquiler", "vivienda rehabilitacion",
                    "plan vivienda", "ayuda alquiler"],
    "carnet":      ["carnet conducir", "permiso conducir B", "autoescuela"],
    "formacion":   ["becas educacion", "becas universitarias", "beca fp",
                    "formacion profesional beca", "estudios superiores"],
    "empleo":      ["empleo joven", "primer empleo", "autonomo alta",
                    "emprendimiento joven", "garantia juvenil"],
    "movilidad":   ["erasmus", "movilidad internacional becas", "practicas europeas"],
    "cultura":     ["ayudas cultura", "artes escenicas", "patrimonio cultural"],
    "dependencia": ["dependencia cuidadores", "discapacidad ayudas", "atencion mayores"],
}

# Fragmentos del campo nivel2 de la BDNS → ambito interno del sistema
NIVEL2_A_AMBITO = {
    "rioja":            "larioja",
    "murcia":           "murcia",
    "extremadura":      "extremadura",
    "andaluc":          "andalucia",
    "madrid":           "madrid",
    "catalu":           "cataluna",
    "valencian":        "valencia",
    "vasco":            "paisvasco",
    "galicia":          "galicia",
    "castilla y leon":  "castillaleon",
    "castilla-la mancha": "castillalamancha",
    "canarias":         "canarias",
    "aragon":           "aragon",
    "navarra":          "navarra",
    "asturias":         "asturias",
    "cantabria":        "cantabria",
    "baleares":         "baleares",
}


def inferir_ambito(nivel1: str, nivel2: str, nivel3: str = "") -> str:
    """Convierte los campos nivel1/nivel2/nivel3 de la BDNS al ambito interno del sistema."""
    n1 = nivel1.upper().strip()
    if n1 == "ESTADO":
        return "estatal"
    if n1 == "AUTONOMICA":
        nivel2_lower = (nivel2 or "").lower()
        for fragmento, ambito in NIVEL2_A_AMBITO.items():
            if fragmento in nivel2_lower:
                return ambito
    if n1 == "LOCAL":
        # Para entidades locales (ayuntamientos, diputaciones) buscamos en nivel2+nivel3
        combinado = ((nivel2 or "") + " " + (nivel3 or "")).lower()
        for fragmento, ambito in NIVEL2_A_AMBITO.items():
            if fragmento in combinado:
                return ambito
    return "desconocido"


BLACKLIST_DESC = [
    "instrumental",           # convocatorias instrumentales (administrativas, no abiertas)
    "por real decreto",       # subvenciones directas concedidas por decreto, no competitivas
    "cooperacion internacional",  # cooperación con países extranjeros
    "subvencion directa a",   # subvención nominativa a una entidad concreta
]


def _es_convocatoria_abierta(descripcion: str) -> bool:
    """Descarta convocatorias administrativas o nominativas que no son ayudas a ciudadanos."""
    d = descripcion.lower()
    return not any(b in d for b in BLACKLIST_DESC)


def _a_formato_bdns(fecha_iso: str) -> str:
    """Convierte YYYY-MM-DD al formato DD/MM/YYYY que espera la BDNS."""
    return datetime.strptime(fecha_iso, "%Y-%m-%d").strftime("%d/%m/%Y")


def buscar_convocatorias(
    descripcion: str,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    page_size: int = PAGE_SIZE,
) -> list[dict]:
    """
    Llama al endpoint de búsqueda de la BDNS.
    Devuelve lista de resultados básicos (id, numeroConvocatoria, descripcion, nivel1...).
    Nota: las fechas deben estar en formato YYYY-MM-DD, la conversión a DD/MM/YYYY es interna.
    """
    params: dict = {"vpd": VPD, "pageSize": page_size, "descripcion": descripcion}
    if fecha_desde:
        params["fechaDesde"] = _a_formato_bdns(fecha_desde)
    if fecha_hasta:
        params["fechaHasta"] = _a_formato_bdns(fecha_hasta)

    respuesta = requests.get(f"{BASE_URL}/convocatorias/busqueda", params=params, timeout=30)
    respuesta.raise_for_status()
    datos = _json_utf8(respuesta)

    # La API devuelve un objeto Spring Page: {"content": [...], "totalElements": N, ...}
    if isinstance(datos, list):
        return datos
    return datos.get("content", [])


def obtener_detalle(numero_convocatoria: str) -> dict | None:
    """
    Obtiene el detalle completo de una convocatoria por su número BDNS.
    Campos útiles: presupuestoTotal, fechaFinSolicitud, descripcionFinalidad,
                   regiones, tiposBeneficiarios, documentos (lista de PDFs), anuncios.
    """
    try:
        respuesta = requests.get(
            f"{BASE_URL}/convocatorias",
            params={"numConv": numero_convocatoria, "vpd": VPD},
            timeout=30,
        )
        respuesta.raise_for_status()
        return _json_utf8(respuesta)
    except Exception:
        return None


def url_pdf(id_documento: int) -> str:
    return f"{BASE_URL}/convocatorias/documentos?idDocumento={id_documento}&vpd={VPD}"


def primer_pdf(detalle: dict) -> str | None:
    """Devuelve la URL de descarga del primer PDF disponible en el detalle."""
    docs = detalle.get("documentos", [])
    for doc in docs:
        nombre = (doc.get("nombreFic") or "").lower()
        if doc.get("id") and nombre.endswith(".pdf"):
            return url_pdf(doc["id"])
    # Sin .pdf explícito: usa el primer documento disponible
    if docs and docs[0].get("id"):
        return url_pdf(docs[0]["id"])
    return None


def _strip_html(html: str) -> str:
    """Extrae texto plano de HTML usando el parser de la stdlib."""
    class _Extractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.partes: list[str] = []
        def handle_data(self, data: str) -> None:
            t = data.strip()
            if t:
                self.partes.append(t)

    ext = _Extractor()
    ext.feed(html)
    return " ".join(ext.partes)


def texto_anuncio(detalle: dict) -> str:
    """Extrae el texto del primer anuncio del boletín oficial (BOR/BOE) si existe."""
    anuncios = detalle.get("anuncios", [])
    if not anuncios:
        return ""
    html = anuncios[0].get("texto", "") or ""
    return _strip_html(html)


def url_web(numero_convocatoria: str) -> str:
    """URL de la página web de la convocatoria (la que verá el usuario)."""
    return f"https://www.infosubvenciones.es/bdnstrans/GE/es/convocatoria/{numero_convocatoria}"


def obtener_candidatos(
    categorias: list[str],
    ambitos: list[str],
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    max_por_busqueda: int = 100,
) -> list[CandidatoFuente]:
    """
    Busca en la BDNS, filtra por ambito y devuelve CandidatoFuente listos para indexar.
    """
    candidatos: list[CandidatoFuente] = []
    urls_vistas: set[str] = set()

    for categoria in categorias:
        keywords = BUSQUEDAS.get(categoria, [categoria])

        for keyword in keywords:
            print(f"  [{categoria}] buscando '{keyword}'...")
            try:
                resultados = buscar_convocatorias(
                    descripcion=keyword,
                    fecha_desde=fecha_desde,
                    fecha_hasta=fecha_hasta,
                    page_size=min(max_por_busqueda, PAGE_SIZE),
                )
            except Exception as e:
                print(f"    [ERROR] {e}")
                continue

            # Filtrar por ambito antes de pedir detalles (evita peticiones innecesarias)
            filtrados = [
                (r, inferir_ambito(r.get("nivel1", ""), r.get("nivel2", ""), r.get("nivel3", "")))
                for r in resultados
                if _es_convocatoria_abierta(r.get("descripcion", ""))
            ]
            filtrados = [(r, a) for r, a in filtrados if a in ambitos]
            print(f"    {len(resultados)} resultados -> {len(filtrados)} en {ambitos}")

            for conv, ambito in filtrados:
                num = conv.get("numeroConvocatoria")
                if not num:
                    continue

                time.sleep(PAUSA)
                detalle = obtener_detalle(num)
                if not detalle:
                    continue

                importe = detalle.get("presupuestoTotal")
                plazo = _campo_texto(detalle.get("fechaFinSolicitud", ""))
                finalidad = _campo_texto(detalle.get("descripcionFinalidad", ""))
                beneficiarios = _campo_texto(detalle.get("tiposBeneficiarios", ""))
                regiones = _campo_texto(detalle.get("regiones", ""))

                notas_partes = []
                if importe:
                    notas_partes.append(f"Importe: {importe}€")
                if plazo:
                    notas_partes.append(f"Plazo: {plazo}")
                if finalidad:
                    notas_partes.append(finalidad)

                pdf = primer_pdf(detalle)
                url_base = url_web(num)

                if pdf:
                    if pdf in urls_vistas:
                        continue
                    urls_vistas.add(pdf)
                    candidatos.append(CandidatoFuente(
                        nombre=conv["descripcion"][:200],
                        ambito=ambito,
                        categoria=categoria,
                        url_oficial=url_base,
                        tipo_fuente="pdf",
                        organismo=conv.get("nivel3"),
                        url_descarga=pdf,
                        notas=" | ".join(notas_partes) or None,
                    ))
                else:
                    # Sin PDF: intentar texto del boletín oficial, si no metadata básica
                    if url_base in urls_vistas:
                        continue
                    urls_vistas.add(url_base)
                    texto_boletin = texto_anuncio(detalle)
                    if texto_boletin:
                        partes_texto = [texto_boletin]
                    else:
                        partes_texto = [conv["descripcion"]]
                        if finalidad:
                            partes_texto.append(finalidad)
                        if beneficiarios:
                            partes_texto.append(f"Beneficiarios: {beneficiarios}")
                        if regiones:
                            partes_texto.append(f"Ambito territorial: {regiones}")
                    candidatos.append(CandidatoFuente(
                        nombre=conv["descripcion"][:200],
                        ambito=ambito,
                        categoria=categoria,
                        url_oficial=url_base,
                        tipo_fuente="bdns_api",
                        organismo=conv.get("nivel3"),
                        url_descarga=None,
                        notas=" | ".join(notas_partes) or None,
                        texto_inline="\n\n".join(partes_texto),
                    ))

            time.sleep(PAUSA)

    return candidatos


def escribir_jsonl(candidatos: list[CandidatoFuente], ruta: Path) -> None:
    with ruta.open("w", encoding="utf-8") as f:
        for c in candidatos:
            fila: dict = {
                "nombre": c.nombre,
                "ambito": c.ambito,
                "categoria": c.categoria,
                "url_oficial": c.url_oficial,
                "tipo_fuente": c.tipo_fuente,
                "organismo": c.organismo,
                "url_descarga": c.url_descarga,
                "notas": c.notas,
            }
            if c.texto_inline:
                fila["texto_inline"] = c.texto_inline
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")


def main() -> None:
    hoy = str(date.today())
    inicio_anio = str(date.today().replace(month=1, day=1))

    parser = argparse.ArgumentParser(
        description="Busca convocatorias en la BDNS y genera candidatos.jsonl para indexar."
    )
    parser.add_argument("--desde", default=inicio_anio,
                        help=f"Fecha inicio YYYY-MM-DD (defecto: {inicio_anio})")
    parser.add_argument("--hasta", default=hoy,
                        help=f"Fecha fin YYYY-MM-DD (defecto: hoy)")
    parser.add_argument("--ambito", nargs="+", default=["estatal", "larioja"],
                        help="Ámbitos a incluir. Ej: estatal larioja murcia extremadura")
    parser.add_argument("--categorias", nargs="+", default=list(BUSQUEDAS.keys()),
                        help="Categorías a buscar. Por defecto todas.")
    parser.add_argument("--max", type=int, default=100,
                        help="Máximo resultados por búsqueda (máx 10000)")
    parser.add_argument(
        "--salida",
        type=Path,
        default=Path(__file__).parent.parent.parent.parent / "data" / "candidatos_bdns.jsonl",
        help="Archivo JSONL de salida",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Busqueda BDNS")
    print("=" * 60)
    print(f"  Periodo:    {args.desde} a {args.hasta}")
    print(f"  Ambitos:    {args.ambito}")
    print(f"  Categorias: {args.categorias}")
    print()

    candidatos = obtener_candidatos(
        categorias=args.categorias,
        ambitos=args.ambito,
        fecha_desde=args.desde,
        fecha_hasta=args.hasta,
        max_por_busqueda=args.max,
    )

    if not candidatos:
        print("\nNo se encontraron convocatorias con esos filtros.")
        return

    escribir_jsonl(candidatos, args.salida)
    print(f"\nListo. {len(candidatos)} candidatos -> {args.salida}")
    print(f"\nPara indexarlos:")
    print(f"  python src/ingestar_fuentes.py --candidatos {args.salida} --indexar")


if __name__ == "__main__":
    main()
