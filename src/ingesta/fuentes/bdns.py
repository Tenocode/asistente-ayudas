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
import re
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
    "vivienda":    ["alquiler joven", "bono alquiler", "bono alquiler joven",
                    "vivienda joven", "aval vivienda", "compra vivienda joven",
                    "vivienda rehabilitacion", "rehabilitacion vivienda",
                    "plan vivienda", "ayuda alquiler"],
    "carnet":      ["carnet conducir", "carne conducir", "permiso conducir",
                    "permiso conducir B", "autoescuela", "ayuda autoescuela"],
    "formacion":   ["becas educacion", "becas universitarias", "beca fp",
                    "formacion profesional beca", "estudios superiores"],
    "empleo":      ["empleo joven", "primer empleo", "autonomo alta",
                    "autonomos", "emprendedores", "emprendimiento",
                    "pymes", "empresa", "comercio", "inversion empresarial",
                    "digitalizacion empresas", "garantia juvenil"],
    "movilidad":   ["erasmus", "movilidad internacional becas", "practicas europeas"],
    "cultura":     ["ayudas cultura", "artes escenicas", "patrimonio cultural"],
    "dependencia": ["dependencia cuidadores", "discapacidad ayudas", "atencion mayores"],
}

# --- Barrido REGION-FIRST de La Rioja -------------------------------------
# El barrido por keyword solo ve convocatorias cuya descripcion casa un termino;
# se deja fuera el grueso del universo riojano. La API SI filtra por region con el
# parametro `regiones` (plural). Estos son los ids del arbol /regiones para La Rioja:
#   19 -> ES23  (NUTS2, nivel autonomico)
#   20 -> ES230 (NUTS3, nivel provincial)
# No se solapan del todo, asi que para barrer TODO hay que unir ambos y deduplicar.
REGIONES_LARIOJA = [19, 20]

# Clasificador: en el barrido por region las keywords dejan de ser un FILTRO y pasan
# a ser un CLASIFICADOR. Asignan categoria a una convocatoria ya garantizada riojana.
# Lo que no clasifica NO se descarta en silencio: va al informe de revision.
# Terminos en minuscula y sin tildes (la descripcion se normaliza con _normalizar_ascii).
# El orden importa: las categorias mas especificas/nicho van primero para ganar el match.
CLASIFICADOR = {
    "carnet":      ["carnet de conducir", "carne de conducir", "permiso de conducir",
                    "autoescuela", "permiso b"],
    "vivienda":    ["alquiler", "vivienda", "rehabilitacion", "entorno residencial",
                    "aval", "hipoteca", "emancipacion"],
    "movilidad":   ["erasmus", "movilidad internacional", "carne de transporte",
                    "carnet de transporte", "abono transporte", "bono transporte",
                    "bicicleta", "ciclos de pedales", "vehiculo electrico",
                    "practicas europeas"],
    "formacion":   ["beca", "libros de texto", "material escolar", "comedor",
                    "bono infantil", "formacion profesional", "estudios superiores",
                    "permanencia", "predoctoral", "gratuidad", "guarderia",
                    "educacion infantil", "ayudas a la formacion", "transporte escolar"],
    "empleo":      ["empleo", "autonomo", "emprend", "pyme", "comercio", "contratacion",
                    "garantia juvenil", "sngj", "cuenta ajena", "cuenta propia",
                    "desemplead", "inversion", "digitalizacion", "industria",
                    "innovacion", "empresa"],
    "cultura":     ["cultura", "artes escenicas", "patrimonio", "arte joven", "musica",
                    "audiovisual", "deporte", "deportivo", "teatro", "festival"],
    "dependencia": ["dependencia", "discapacit", "mayores", "cuidador",
                    "tercera edad", "autonomia personal", "accesibilidad"],
}

# Prioridad para el tope --max: primero las categorias con huecos (carnet, vivienda,
# dependencia, movilidad, formacion) y luego las que ya tienen cobertura (empleo, cultura).
PRIORIDAD_CATEGORIAS = ["carnet", "dependencia", "vivienda", "movilidad",
                        "formacion", "empleo", "cultura"]

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


# Municipios de La Rioja: las ayudas LOCALES llevan el nombre del pueblo en
# nivel2/nivel3 (ej. "LOGRONO", "AYUNTAMIENTO DE LOGRONO"), que no contienen
# "rioja" y por eso quedaban sin clasificar. Incluimos la capital y los
# municipios mas poblados, en forma sin tilde para casar con el texto normalizado.
# Se evitan nombres ambiguos compartidos con otras provincias salvo en su forma
# completa (ej. "santo domingo de la calzada").
MUNICIPIOS_LARIOJA = {
    "logrono", "calahorra", "arnedo", "haro", "alfaro", "najera", "lardero",
    "villamediana de iregua", "santo domingo de la calzada", "cervera del rio alhama",
    "autol", "rincon de soto", "pradejon", "aldeanueva de ebro", "navarrete",
    "ezcaray", "fuenmayor", "cenicero", "quel", "agoncillo", "alberite",
    "albelda de iregua", "entrena", "casalarreina", "munillo de rio leza",
}


def _normalizar_ascii(texto: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", (texto or "").lower()).encode("ascii", "ignore").decode("ascii")


def inferir_ambito(nivel1: str, nivel2: str, nivel3: str = "") -> str:
    """Convierte los campos nivel1/nivel2/nivel3 de la BDNS al ambito interno del sistema."""
    n1 = nivel1.upper().strip()
    if n1 == "ESTADO":
        return "estatal"
    if n1 in ("AUTONOMICA", "LOCAL"):
        # Para LOCAL miramos nivel2+nivel3 (ayuntamiento/pueblo); para AUTONOMICA, nivel2.
        combinado = _normalizar_ascii(nivel2) if n1 == "AUTONOMICA" else _normalizar_ascii(f"{nivel2} {nivel3}")
        for fragmento, ambito in NIVEL2_A_AMBITO.items():
            if fragmento in combinado:
                return ambito
        # Fallback por municipio riojano (Logrono y principales) para ayudas LOCALES.
        if any(m in combinado for m in MUNICIPIOS_LARIOJA):
            return "larioja"
    return "desconocido"


BLACKLIST_DESC = [
    "instrumental",           # convocatorias instrumentales (administrativas, no abiertas)
    "por real decreto",       # subvenciones directas concedidas por decreto, no competitivas
    "cooperacion internacional",  # cooperación con países extranjeros
    "subvencion directa a",   # subvención nominativa a una entidad concreta
    "adenda",                 # adendas a convenios; actos administrativos, no ayudas a ciudadanos
    "acuerdo de la junta de gobierno",  # actos de juntas de gobierno locales
    "acuerdo junta de gobierno",
    "convenio marco",         # convenios marco entre administraciones/entidades
]


def _es_convocatoria_abierta(descripcion: str) -> bool:
    """Descarta convocatorias administrativas o nominativas que no son ayudas a ciudadanos."""
    d = descripcion.lower()
    return not any(b in d for b in BLACKLIST_DESC)


# Blacklist ampliada para el barrido por region. Al enumerar TODO el universo riojano
# afloran muchos actos administrativos que no son ayudas a solicitar por un ciudadano:
# subvenciones nominativas a una entidad, convenios entre administraciones, premios y
# patrocinios. Se descartan (se cuentan, no se ocultan) para que el informe de revision
# quede legible. Mas conservadora que agresiva: no se descarta "concurso" (un concurso
# de emprendedores SI es una ayuda) ni terminos genericos de categoria.
BLACKLIST_REGION = BLACKLIST_DESC + [
    "nominativ",          # subvencion nominativa a una entidad concreta
    "convenio",           # convenios entre administraciones/entidades
    "premio",             # premios (no son ayudas a solicitar)
    "a favor de",         # "... a favor de Fundacion X"
    "patrocinio",         # patrocinios publicitarios
    "no comercializacion",
    "liquidacion",        # liquidaciones de cuotas, actos contables
    "proceso selectivo",  # seleccion de personal publico, no es ayuda a ciudadanos
    "bolsa de empleo",    # bolsas/listas de contratacion de personal
    "bolsa de trabajo",
    "lista de reserva",
]


def _pasa_blacklist_region(descripcion: str) -> bool:
    d = _normalizar_ascii(descripcion)
    return not any(b in d for b in BLACKLIST_REGION)


# Marcadores de ayudas cuyo BENEFICIARIO es otra administracion (ayuntamiento, EELL,
# mancomunidad), no un ciudadano. No son ruido total (a veces el dinero llega a vecinos
# via el municipio), asi que NO se descartan: van a su propio cubo del informe para que
# un humano decida. Asi cumplimos "no dejarnos nada" sin meter ruido en los candidatos.
INTER_ADMIN = [
    "a municipios", "a los municipios", "entidades locales", "a ayuntamientos",
    "a corporaciones locales", "mancomunidad", "a las entidades locales",
    "aytos", "a entidades locales", "agrupaciones de municipios",
]


def _es_inter_administrativa(descripcion: str) -> bool:
    d = _normalizar_ascii(descripcion)
    return any(m in d for m in INTER_ADMIN)


# Dedup de ediciones anuales: la misma ayuda se reconvoca cada año con un nombre casi
# idéntico salvo el año ("Bono Alquiler Joven 2025/2026", "... curso 24/25"). Para el RAG
# interesa la edición más reciente, no cinco años de la misma ayuda. Se agrupan por el
# nombre SIN tokens de año y se conserva la de año más alto (desempate: numeroConvocatoria).
_RE_ANIO = re.compile(r"\b(20\d{2})\b")
_RE_CURSO = re.compile(r"\b\d{2}\s*/\s*\d{2}\b")          # "24/25"
_RE_CURSO_LARGO = re.compile(r"\b20\d{2}\s*/\s*20\d{2}\b")  # "2024/2025"


def _anio_de(nombre: str) -> int:
    """Año más alto que aparece en el nombre (para elegir la edición más reciente)."""
    anios = [int(a) for a in _RE_ANIO.findall(nombre or "")]
    return max(anios) if anios else 0


def _clave_dedup(nombre: str) -> str:
    """Nombre normalizado SIN años ni 'curso XX/XX', para agrupar ediciones de la misma ayuda."""
    t = _normalizar_ascii(nombre)
    t = _RE_CURSO_LARGO.sub(" ", t)
    t = _RE_ANIO.sub(" ", t)
    t = _RE_CURSO.sub(" ", t)
    t = re.sub(r"[^a-z0-9% ]+", " ", t)   # quita puntuacion
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _dedup_ediciones(items: list[tuple]) -> tuple[list[tuple], int]:
    """
    Colapsa ediciones anuales en una lista de (conv, ambito, categoria).
    Devuelve (items_unicos, n_colapsadas). Conserva la edición de año más alto;
    desempate por numeroConvocatoria (id de registro, mayor = más reciente).
    """
    mejor: dict[str, tuple] = {}
    colapsadas = 0
    for it in items:
        conv = it[0]
        clave = _clave_dedup(conv.get("descripcion", ""))
        try:
            num = int(conv.get("numeroConvocatoria") or 0)
        except (TypeError, ValueError):
            num = 0
        rank = (_anio_de(conv.get("descripcion", "")), num)
        if clave not in mejor:
            mejor[clave] = (rank, it)
        else:
            colapsadas += 1
            if rank > mejor[clave][0]:
                mejor[clave] = (rank, it)
    return [v[1] for v in mejor.values()], colapsadas


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


def _construir_candidato(
    conv: dict,
    ambito: str,
    categoria: str,
    urls_vistas: set[str],
) -> CandidatoFuente | None:
    """
    A partir de una convocatoria basica, pide su detalle y construye un CandidatoFuente.
    Devuelve None si no hay numero, no hay detalle o la URL ya se vio (dedup).
    Lo comparten el barrido por keyword y el barrido por region.
    El caller es responsable de la pausa entre peticiones (time.sleep(PAUSA)).
    """
    num = conv.get("numeroConvocatoria")
    if not num:
        return None

    detalle = obtener_detalle(num)
    if not detalle:
        return None

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
            return None
        urls_vistas.add(pdf)
        return CandidatoFuente(
            nombre=conv["descripcion"][:200],
            ambito=ambito,
            categoria=categoria,
            url_oficial=url_base,
            tipo_fuente="pdf",
            organismo=conv.get("nivel3"),
            url_descarga=pdf,
            notas=" | ".join(notas_partes) or None,
        )

    # Sin PDF: intentar texto del boletín oficial, si no metadata básica
    if url_base in urls_vistas:
        return None
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
    return CandidatoFuente(
        nombre=conv["descripcion"][:200],
        ambito=ambito,
        categoria=categoria,
        url_oficial=url_base,
        tipo_fuente="bdns_api",
        organismo=conv.get("nivel3"),
        url_descarga=None,
        notas=" | ".join(notas_partes) or None,
        texto_inline="\n\n".join(partes_texto),
    )


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
                time.sleep(PAUSA)
                cand = _construir_candidato(conv, ambito, categoria, urls_vistas)
                if cand:
                    candidatos.append(cand)

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


# --- Barrido REGION-FIRST -------------------------------------------------

def buscar_por_region(
    region_ids: list[int],
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    max_paginas: int = 40,
    cache_path: Path | None = None,
    usar_cache: bool = False,
) -> list[dict]:
    """
    Enumera TODAS las convocatorias de las regiones dadas (paginando) y las deduplica
    por numeroConvocatoria. A diferencia de buscar_convocatorias(), NO usa keyword:
    barre el universo territorial completo. La API filtra con el parametro `regiones`.

    Cache opcional: si `usar_cache` y existe `cache_path`, carga el universo del disco en
    vez de pedirlo a la API (util para iterar la clasificacion sin re-barrer). El cache
    NO tiene en cuenta el rango de fechas: borra el fichero si cambias --desde/--hasta.
    Tras un barrido real siempre se vuelca a `cache_path` si se proporciona.
    """
    if usar_cache and cache_path and cache_path.exists():
        print(f"  (universo cargado de cache: {cache_path})")
        return json.loads(cache_path.read_text(encoding="utf-8"))

    universo: dict[str, dict] = {}
    for rid in region_ids:
        page = 0
        total = 0
        while True:
            params: dict = {"vpd": VPD, "pageSize": PAGE_SIZE, "page": page, "regiones": rid}
            if fecha_desde:
                params["fechaDesde"] = _a_formato_bdns(fecha_desde)
            if fecha_hasta:
                params["fechaHasta"] = _a_formato_bdns(fecha_hasta)
            try:
                resp = requests.get(
                    f"{BASE_URL}/convocatorias/busqueda", params=params, timeout=60
                )
                resp.raise_for_status()
                datos = _json_utf8(resp)
            except Exception as e:
                print(f"    [ERROR] region {rid} pagina {page}: {e}")
                break

            content = datos.get("content", []) if isinstance(datos, dict) else datos
            total = datos.get("totalElements", len(content)) if isinstance(datos, dict) else len(content)
            if not content:
                break
            for c in content:
                num = c.get("numeroConvocatoria")
                if num:
                    universo[num] = c
            page += 1
            if page * PAGE_SIZE >= total or page >= max_paginas:
                break
            time.sleep(PAUSA)
        print(f"  region {rid}: total={total} -> acumulado unico={len(universo)}")
    lista = list(universo.values())
    if cache_path:
        cache_path.write_text(json.dumps(lista, ensure_ascii=False), encoding="utf-8")
    return lista


def clasificar_categoria(descripcion: str) -> str | None:
    """
    Asigna una categoria interna a partir de la descripcion, o None si no casa ninguna.
    El match es por INICIO de palabra (\\b), no por subcadena: asi "aval" no clasifica
    "carnaval" como vivienda ni "cultura" clasifica "agricultura" como cultura, pero los
    prefijos siguen valiendo ("beca"->"becas", "emprend"->"emprendedor").
    """
    t = _normalizar_ascii(descripcion)
    for categoria, terminos in CLASIFICADOR.items():
        for term in terminos:
            if re.search(r"\b" + re.escape(term), t):
                return categoria
    return None


def _ambito_region(conv: dict) -> str:
    """
    Ambito de una convocatoria que ya viene del barrido territorial de La Rioja.
    ESTADO -> estatal; resto -> larioja. Defensa: si una autonomica menciona otra
    CCAA conocida (quirk de la API), se marca 'desconocido' y va a revision.
    """
    n1 = (conv.get("nivel1") or "").upper().strip()
    if n1 == "ESTADO":
        return "estatal"
    combinado = _normalizar_ascii(f"{conv.get('nivel2','')} {conv.get('nivel3','')}")
    for fragmento, ambito in NIVEL2_A_AMBITO.items():
        if fragmento in combinado and ambito != "larioja":
            return "desconocido"
    return "larioja"


def obtener_candidatos_por_region(
    region_ids: list[int] = REGIONES_LARIOJA,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    max_candidatos: int = 100,
    cache_path: Path | None = None,
    usar_cache: bool = False,
) -> tuple[list[CandidatoFuente], list[tuple], list[tuple], list[tuple], dict]:
    """
    Barrido region-first: enumera todo La Rioja, descarta ruido administrativo,
    clasifica por categoria, colapsa ediciones anuales y enriquece (detalle BDNS)
    hasta `max_candidatos`.

    Devuelve (candidatos, revision, capadas, inter_admin, stats):
      - candidatos:  CandidatoFuente listos para indexar (clasificados, deduplicados, enriquecidos).
      - revision:    [(conv, ambito)] no clasificados, NO descartados -> informe.
      - capadas:     [(conv, ambito, categoria)] clasificados pero fuera del tope --max.
      - inter_admin: [(conv, ambito)] beneficiario = otra administracion -> informe.
      - stats:       conteos para el informe.
    """
    universo = buscar_por_region(
        region_ids, fecha_desde, fecha_hasta, cache_path=cache_path, usar_cache=usar_cache
    )

    descartadas: list[dict] = []
    clasificadas: list[tuple] = []   # (conv, ambito, categoria)
    revision: list[tuple] = []       # (conv, ambito)
    inter_admin: list[tuple] = []    # (conv, ambito)

    for conv in universo:
        desc = conv.get("descripcion", "") or ""
        ambito = _ambito_region(conv)
        if ambito == "desconocido":
            revision.append((conv, ambito))
            continue
        if not _pasa_blacklist_region(desc):
            descartadas.append(conv)
            continue
        if _es_inter_administrativa(desc):
            inter_admin.append((conv, ambito))
            continue
        categoria = clasificar_categoria(desc)
        if categoria:
            clasificadas.append((conv, ambito, categoria))
        else:
            revision.append((conv, ambito))

    # Colapsa ediciones anuales de la misma ayuda (quedarse con la mas reciente).
    clasificadas, colapsadas = _dedup_ediciones(clasificadas)

    # Prioriza las categorias con huecos antes de aplicar el tope.
    orden = {c: i for i, c in enumerate(PRIORIDAD_CATEGORIAS)}
    clasificadas.sort(key=lambda x: orden.get(x[2], 99))
    a_enriquecer = clasificadas[:max_candidatos] if max_candidatos else clasificadas
    capadas = clasificadas[max_candidatos:] if max_candidatos else []

    print(f"\n  Universo={len(universo)} | descartadas={len(descartadas)} | "
          f"inter-admin={len(inter_admin)} | clasificadas unicas={len(clasificadas)} "
          f"(colapsadas {colapsadas}) | sin clasificar={len(revision)}")
    print(f"  Enriqueciendo {len(a_enriquecer)} candidatos (tope --max={max_candidatos})...")

    candidatos: list[CandidatoFuente] = []
    urls_vistas: set[str] = set()
    for i, (conv, ambito, categoria) in enumerate(a_enriquecer, 1):
        print(f"    {i}/{len(a_enriquecer)} [{categoria}/{ambito}] "
              f"{(conv.get('descripcion') or '')[:55]}")
        time.sleep(PAUSA)
        cand = _construir_candidato(conv, ambito, categoria, urls_vistas)
        if cand:
            candidatos.append(cand)

    reparto: dict[str, int] = {}
    for _, _, cat in clasificadas:
        reparto[cat] = reparto.get(cat, 0) + 1

    stats = {
        "universo": len(universo),
        "descartadas": len(descartadas),
        "inter_admin": len(inter_admin),
        "clasificadas": len(clasificadas),
        "ediciones_colapsadas": colapsadas,
        "revision": len(revision),
        "candidatos_generados": len(candidatos),
        "capadas": len(capadas),
        "reparto_categorias": reparto,
    }
    return candidatos, revision, capadas, inter_admin, stats


def escribir_revision(
    revision: list[tuple],
    capadas: list[tuple],
    inter_admin: list[tuple],
    stats: dict,
    ruta: Path,
) -> None:
    """Informe Markdown legible: lo que el barrido NO mete en el JSONL, para revisar a mano."""
    from collections import defaultdict

    L: list[str] = []
    L.append("# Revisión barrido BDNS region-first — La Rioja")
    L.append("")
    L.append(f"Generado: {date.today()}  ·  regiones={REGIONES_LARIOJA}")
    L.append("")
    L.append("## Resumen")
    L.append("")
    L.append(f"- Universo La Rioja (deduplicado): **{stats['universo']}**")
    L.append(f"- Descartadas por blacklist (nominativas/convenios/premios…): **{stats['descartadas']}**")
    L.append(f"- Inter-administrativas (beneficiario = otra administración): **{stats.get('inter_admin', 0)}**")
    L.append(f"- Clasificadas únicas (tras colapsar {stats.get('ediciones_colapsadas', 0)} ediciones anuales): **{stats['clasificadas']}**")
    L.append(f"- Candidatos generados al JSONL (enriquecidos): **{stats['candidatos_generados']}**")
    if stats["capadas"]:
        L.append(f"- Clasificadas fuera del tope --max (no enriquecidas): **{stats['capadas']}**")
    L.append(f"- Sin clasificar (lista de abajo): **{stats['revision']}**")
    L.append("")
    if stats["reparto_categorias"]:
        reparto = ", ".join(
            f"{k}={v}" for k, v in sorted(stats["reparto_categorias"].items(), key=lambda x: -x[1])
        )
        L.append(f"Reparto de clasificadas por categoría: {reparto}")
        L.append("")

    if inter_admin:
        L.append("## Inter-administrativas — beneficiario = otra administración")
        L.append("")
        L.append("El dinero va a un ayuntamiento/EELL, no directamente al ciudadano. A veces")
        L.append("acaba en vecinos vía el municipio: revisa por si alguna merece rescatarse.")
        L.append("")
        for conv, ambito in inter_admin:
            num = conv.get("numeroConvocatoria", "")
            L.append(f"- {(conv.get('descripcion') or '')[:120]}")
            L.append(f"  - {conv.get('nivel1')} · {conv.get('nivel3') or conv.get('nivel2') or ''} · {url_web(num)}")
        L.append("")

    if capadas:
        L.append("## Clasificadas pero fuera del tope --max")
        L.append("")
        L.append("Ya tienen categoría asignada. Para incluirlas, re-ejecuta con `--max` mayor.")
        L.append("")
        for conv, ambito, categoria in capadas:
            num = conv.get("numeroConvocatoria", "")
            L.append(f"- **[{categoria}/{ambito}]** {(conv.get('descripcion') or '')[:120]}")
            L.append(f"  - {conv.get('nivel1')} · {conv.get('nivel3') or conv.get('nivel2') or ''} · {url_web(num)}")
        L.append("")

    L.append("## Sin clasificar — revisar a mano")
    L.append("")
    L.append("No casaron ninguna categoría y no son ruido evidente. Si alguna es una ayuda")
    L.append("real a ciudadanos, promuévela a `data/candidatos.jsonl` con su categoría correcta.")
    L.append("")
    por_nivel: dict[str, list] = defaultdict(list)
    for conv, ambito in revision:
        por_nivel[conv.get("nivel1", "?")].append(conv)
    for nivel, items in sorted(por_nivel.items(), key=lambda x: -len(x[1])):
        L.append(f"### {nivel} ({len(items)})")
        L.append("")
        for conv in items:
            num = conv.get("numeroConvocatoria", "")
            L.append(f"- {(conv.get('descripcion') or '')[:120]}")
            L.append(f"  - {conv.get('nivel3') or conv.get('nivel2') or ''} · {url_web(num)}")
        L.append("")

    ruta.write_text("\n".join(L), encoding="utf-8")


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
                        help="Máximo resultados por búsqueda (modo keyword) o candidatos a "
                             "enriquecer (modo --por-region)")
    parser.add_argument("--por-region", action="store_true",
                        help="Barrido REGION-FIRST de La Rioja: enumera TODO el universo "
                             "riojano por región (no por keyword), clasifica y deja en un "
                             "informe lo que no entra. Cierra el hueco de cobertura.")
    parser.add_argument(
        "--salida",
        type=Path,
        default=Path(__file__).parent.parent.parent.parent / "data" / "candidatos_bdns.jsonl",
        help="Archivo JSONL de salida",
    )
    parser.add_argument(
        "--revision",
        type=Path,
        default=Path(__file__).parent.parent.parent.parent / "data" / "revision_bdns_larioja.md",
        help="Informe Markdown de revisión (solo modo --por-region)",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path(__file__).parent.parent.parent.parent / "data" / "_bdns_universo_larioja.json",
        help="Ruta donde cachear el universo crudo (solo modo --por-region)",
    )
    parser.add_argument("--usar-cache", action="store_true",
                        help="Cargar el universo del cache en vez de pedirlo a la API "
                             "(ojo: el cache ignora --desde/--hasta)")
    args = parser.parse_args()

    if args.por_region:
        print("=" * 60)
        print("  Barrido BDNS REGION-FIRST — La Rioja")
        print("=" * 60)
        print(f"  Periodo:  {args.desde} a {args.hasta}")
        print(f"  Regiones: {REGIONES_LARIOJA} (ES23 + ES230)")
        print(f"  Tope:     --max {args.max} candidatos a enriquecer")
        print()

        candidatos, revision, capadas, inter_admin, stats = obtener_candidatos_por_region(
            region_ids=REGIONES_LARIOJA,
            fecha_desde=args.desde,
            fecha_hasta=args.hasta,
            max_candidatos=args.max,
            cache_path=args.cache,
            usar_cache=args.usar_cache,
        )

        escribir_revision(revision, capadas, inter_admin, stats, args.revision)

        if candidatos:
            escribir_jsonl(candidatos, args.salida)

        print("\n" + "-" * 60)
        print(f"  Universo riojano:      {stats['universo']}")
        print(f"  Descartadas (ruido):   {stats['descartadas']}")
        print(f"  Inter-administrativas: {stats['inter_admin']}")
        print(f"  Clasificadas únicas:   {stats['clasificadas']} (colapsadas {stats['ediciones_colapsadas']})  {stats['reparto_categorias']}")
        print(f"  Candidatos al JSONL:   {stats['candidatos_generados']} -> {args.salida}")
        if stats["capadas"]:
            print(f"  Fuera del tope --max:  {stats['capadas']} (sube --max para incluirlas)")
        print(f"  Sin clasificar:        {stats['revision']} -> informe")
        print(f"  Informe de revisión:   {args.revision}")
        if candidatos:
            print(f"\n  Revisa el informe y, si procede, indexa:")
            print(f"    python src/ingestar_fuentes.py --candidatos {args.salida} --indexar")
        return

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
