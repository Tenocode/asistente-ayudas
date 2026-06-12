"""
Conector ADER (Agencia de Desarrollo Economico de La Rioja).

Este modulo descubre paginas oficiales de ayudas en www.ader.es y genera
CandidatoFuente en JSONL para que el pipeline comun extraiga/indexe despues.

No indexa directamente y no sustituye a BDNS: ADER actua como fuente oficial
autonomica para empresas, autonomos, comercio, emprendedores e inversion.
"""

import argparse
import json
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ingesta.adaptadores.html import limpiar_html
from ingesta.modelos import CandidatoFuente


BASE_URL = "https://www.ader.es/"
AYUDAS_URL = "https://www.ader.es/ayudas/"
AYUDAS_AREAS_URL = "https://www.ader.es/ayudas/ayudas-por-areas/"
ORGANISMO = "ADER - Agencia de Desarrollo Economico de La Rioja"
TIMEOUT = 30
USER_AGENT = "asistente-ayudas/0.1 (+https://www.ader.es/)"

# ADER es sobre todo tejido productivo. Hasta tener categorias mas finas,
# agrupamos negocio/empresa bajo empleo para que el chat lo recupere.
CATEGORIA_POR_AREA = {
    "autonomos": "empleo",
    "comercio": "empleo",
    "emprendedores": "empleo",
    "financiacion": "empleo",
    "activos": "empleo",
    "i-d": "empleo",
    "innovacion": "empleo",
    "internacionalizacion": "empleo",
    "energia-y-medioambiente": "empleo",
    "vehiculos": "movilidad",
}


@dataclass(frozen=True)
class Enlace:
    url: str
    texto: str
    titulo: str | None = None


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.enlaces: list[Enlace] = []
        self._href_actual: str | None = None
        self._titulo_actual: str | None = None
        self._texto_actual: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() != "a":
            return
        atributos = dict(attrs)
        href = atributos.get("href")
        if not href:
            return
        self._href_actual = normalizar_url(urljoin(self.base_url, href))
        self._titulo_actual = limpiar_espacios(atributos.get("title", ""))
        self._texto_actual = []

    def handle_data(self, data: str) -> None:
        if self._href_actual:
            self._texto_actual.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href_actual:
            return
        texto = limpiar_espacios(" ".join(self._texto_actual))
        self.enlaces.append(Enlace(self._href_actual, texto, self._titulo_actual or None))
        self._href_actual = None
        self._titulo_actual = None
        self._texto_actual = []


def limpiar_espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


def normalizar_texto(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return texto.encode("ascii", "ignore").decode("ascii")


def quitar_tags(html: str) -> str:
    return limpiar_html(html)


def normalizar_url(url: str) -> str:
    url = url.strip()
    url = url.replace("http://www.ader.es/", "https://www.ader.es/")
    url, _fragmento = urldefrag(url)
    partes = urlparse(url)
    if partes.netloc == "www.ader.es":
        url = urlunparse(partes._replace(query=""))
    return url


def obtener_html(url: str) -> str:
    respuesta = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    respuesta.raise_for_status()
    respuesta.encoding = respuesta.encoding or respuesta.apparent_encoding
    return respuesta.text


def extraer_enlaces(html: str, base_url: str) -> list[Enlace]:
    parser = _LinkParser(base_url)
    parser.feed(html)
    return parser.enlaces


def es_url_ader_ayudas(url: str) -> bool:
    if not url.startswith(AYUDAS_AREAS_URL):
        return False
    ruta = urlparse(url).path.lower()
    if "/ayudas-anteriores/" in ruta:
        return False
    return not ruta.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"))


def area_desde_url(url: str) -> str | None:
    partes = [p for p in urlparse(url).path.strip("/").split("/") if p]
    try:
        indice = partes.index("ayudas-por-areas")
    except ValueError:
        return None
    if indice + 1 >= len(partes):
        return None
    return partes[indice + 1]


def categoria_desde_url(url: str) -> str:
    area = area_desde_url(url) or ""
    return CATEGORIA_POR_AREA.get(area, "empleo")


def extraer_titulo(html: str, fallback_url: str) -> str:
    patrones = [
        r'<header[^>]+id="header-page"[^>]*>.*?<h2[^>]*>(.*?)</h2>',
        r"<title>(.*?)\|",
        r"<h2[^>]*>(.*?)</h2>",
    ]
    for patron in patrones:
        encontrado = re.search(patron, html, flags=re.IGNORECASE | re.DOTALL)
        if encontrado:
            titulo = quitar_tags(encontrado.group(1))
            titulo = limpiar_espacios(titulo)
            if titulo:
                return titulo[:200]

    slug = urlparse(fallback_url).path.rstrip("/").split("/")[-1]
    return slug.replace("-", " ").title()[:200]


def extraer_url_tramite(enlaces: list[Enlace]) -> str | None:
    for enlace in enlaces:
        texto = f"{enlace.texto} {enlace.titulo or ''}".lower()
        if "sede electronica" in texto or "/sede-electronica/" in enlace.url:
            return enlace.url
    return None


def extraer_notas(texto: str, url: str) -> str | None:
    notas: list[str] = []
    area = area_desde_url(url)
    if area:
        notas.append(f"Area ADER: {area}")

    lineas = [limpiar_espacios(linea) for linea in texto.splitlines()]
    for linea in lineas:
        linea_lower = normalizar_texto(linea)
        if (
            "plazo de convocatoria" in linea_lower
            or "plazo de presentacion" in linea_lower
        ):
            notas.append(linea[:250])
            break

    bdns = re.search(r"\bBDNS:\s*([0-9,\s]+)", texto, flags=re.IGNORECASE)
    if bdns:
        notas.append(f"BDNS: {limpiar_espacios(bdns.group(1))}")

    return " | ".join(notas) if notas else None


def es_pagina_detalle_ayuda(texto: str, url: str) -> bool:
    if url.rstrip("/") == AYUDAS_AREAS_URL.rstrip("/"):
        return False

    normalizado = normalizar_texto(texto)
    marcadores = [
        "solicite esta ayuda",
        "beneficiarios",
        "requisitos",
        "subvencion a percibir",
        "plazo de convocatoria",
        "normativa",
    ]
    puntuacion = sum(1 for marcador in marcadores if marcador in normalizado)

    # Las paginas indice suelen tener solo "Lineas disponibles"; las fichas
    # reales combinan tramite, normativa, plazo, beneficiarios o requisitos.
    return puntuacion >= 2


def elegir_nombre(html: str, url: str, nombre_enlace: str | None = None) -> str:
    titulo = extraer_titulo(html, url)
    nombre = limpiar_espacios(nombre_enlace or "")
    if not nombre:
        return titulo

    genericos = {
        "activos",
        "autonomos",
        "comercio",
        "emprendedores",
        "financiacion",
        "i+d",
        "innovacion",
        "internacionalizacion",
    }
    if normalizar_texto(titulo) in genericos or len(nombre) > len(titulo) + 8:
        return nombre[:200]
    return titulo


def construir_candidato(
    url: str,
    html: str,
    nombre_enlace: str | None = None,
) -> CandidatoFuente:
    texto = quitar_tags(html)
    enlaces = extraer_enlaces(html, url)
    return CandidatoFuente(
        nombre=elegir_nombre(html, url, nombre_enlace),
        ambito="larioja",
        categoria=categoria_desde_url(url),
        url_oficial=url,
        tipo_fuente="html",
        organismo=ORGANISMO,
        url_tramite=extraer_url_tramite(enlaces),
        notas=extraer_notas(texto, url),
    )


def area_permitida(url: str, areas: set[str] | None) -> bool:
    if not areas:
        return True
    area = area_desde_url(url)
    return area in areas


def descubrir_candidatos(
    areas: set[str] | None = None,
    max_depth: int = 4,
    max_paginas: int = 80,
    pausa: float = 0.25,
) -> list[CandidatoFuente]:
    visitadas: set[str] = set()
    candidatas_vistas: set[str] = set()
    pendientes: list[tuple[str, int, str | None]] = [(AYUDAS_URL, 0, None)]
    candidatos: list[CandidatoFuente] = []

    while pendientes and len(visitadas) < max_paginas:
        url, depth, nombre_enlace = pendientes.pop(0)
        if url in visitadas:
            continue
        visitadas.add(url)

        html = obtener_html(url)
        texto = quitar_tags(html)
        enlaces = extraer_enlaces(html, url)

        if es_url_ader_ayudas(url) and area_permitida(url, areas):
            if es_pagina_detalle_ayuda(texto, url) and url not in candidatas_vistas:
                candidatos.append(construir_candidato(url, html, nombre_enlace))
                candidatas_vistas.add(url)

        if depth >= max_depth:
            continue

        for enlace in enlaces:
            destino = normalizar_url(enlace.url)
            if not es_url_ader_ayudas(destino):
                continue
            if not area_permitida(destino, areas):
                continue
            if destino not in visitadas and all(destino != p[0] for p in pendientes):
                nombre = enlace.texto or enlace.titulo
                pendientes.append((destino, depth + 1, nombre))

        time.sleep(pausa)

    return candidatos


def escribir_jsonl(candidatos: list[CandidatoFuente], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as f:
        for candidato in candidatos:
            fila = {
                "nombre": candidato.nombre,
                "ambito": candidato.ambito,
                "categoria": candidato.categoria,
                "url_oficial": candidato.url_oficial,
                "tipo_fuente": candidato.tipo_fuente,
                "organismo": candidato.organismo,
                "url_tramite": candidato.url_tramite,
                "notas": candidato.notas,
            }
            f.write(json.dumps(fila, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Descubre ayudas oficiales de ADER y genera candidatos JSONL."
    )
    parser.add_argument(
        "--areas",
        nargs="+",
        default=None,
        help="Limita por areas ADER. Ej: autonomos emprendedores comercio",
    )
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--max-paginas", type=int, default=80)
    parser.add_argument("--pausa", type=float, default=0.25)
    parser.add_argument(
        "--salida",
        type=Path,
        default=Path(__file__).parent.parent.parent.parent / "data" / "candidatos_ader.jsonl",
        help="Archivo JSONL de salida",
    )
    args = parser.parse_args()

    areas = {area.lower().strip("/") for area in args.areas} if args.areas else None

    print("=" * 60)
    print("  Descubrimiento ADER")
    print("=" * 60)
    print(f"  Areas:       {sorted(areas) if areas else 'todas'}")
    print(f"  Max paginas: {args.max_paginas}")
    print()

    candidatos = descubrir_candidatos(
        areas=areas,
        max_depth=args.max_depth,
        max_paginas=args.max_paginas,
        pausa=args.pausa,
    )

    if not candidatos:
        print("No se encontraron ayudas ADER con esos filtros.")
        return

    escribir_jsonl(candidatos, args.salida)
    print(f"Listo. {len(candidatos)} candidatos -> {args.salida}")
    for candidato in candidatos:
        print(f"  - {candidato.nombre} [{candidato.categoria}]")
    print("\nPara probar extraccion:")
    print(f"  python src/ingestar_fuentes.py --candidatos {args.salida}")
    print("\nPara indexarlos:")
    print(f"  python src/ingestar_fuentes.py --candidatos {args.salida} --indexar")


if __name__ == "__main__":
    main()
