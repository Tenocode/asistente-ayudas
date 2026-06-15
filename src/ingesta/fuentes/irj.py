"""
Conector IRJ (Instituto Riojano de la Juventud).

Descubre las ayudas a JOVENES que el IRJ publica en su pagina de subvenciones y
genera CandidatoFuente en JSONL para que el pipeline comun extraiga/indexe.

Por que un conector propio y no solo BDNS: las ayudas de juventud del IRJ (carne de
conducir, emancipacion en formacion, ayudas individuales para idiomas/voluntariado/
monitor de tiempo libre, carne joven...) NO estan bien cubiertas por BDNS — el carne
ni siquiera aparece. La ficha oficial del tramite (en larioja.org) trae beneficiarios,
importe y plazo en claro.

Estructura real de la pagina:
  - Las FICHAS oficiales (con beneficiarios/importe/plazo) viven en larioja.org como
    tramites `oficina-electronica/tramite?n=XXXXX` (TLS correcto).
  - Las paginas de CONTENIDO (explicacion en lenguaje ciudadano) viven en irj.es.
    irj.es tiene la cadena TLS rota; el adaptador HTML acepta su TLS sin verificar
    para este host concreto (lista cerrada en adaptadores/html.py).

No indexa directamente: el importador comun valida texto suficiente y deduplica.
"""

import argparse
import json
import sys
import urllib3
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ingesta.fuentes.ader import extraer_enlaces
from ingesta.modelos import CandidatoFuente

SUBVENCIONES_URL = "https://www.irj.es/subvenciones"
ORGANISMO = "IRJ - Instituto Riojano de la Juventud"
USER_AGENT = "asistente-ayudas/0.1 (+lectura de fuentes oficiales)"
TIMEOUT = 30

# Tramites oficiales (larioja.org) que SON ayudas a ciudadanos jovenes -> categoria.
TRAMITES_CIUDADANO = {
    "22127": ("formacion", "Ayudas individuales del IRJ (idiomas, voluntariado, monitor/director)"),
    "24664": ("carnet", "Subvenciones de emancipacion juvenil en formacion (incluye carne de conducir)"),
}
# Tramites que NO son ayudas a ciudadanos (a otras administraciones o a entidades).
TRAMITES_SKIP = {"21227", "01807", "25650", "24487"}

# Paginas de contenido del propio irj.es que describen ayudas a jovenes -> (categoria, nombre).
PAGINAS_IRJ = {
    "ayudas-carne-de-conducir": ("carnet", "Ayudas para el carne de conducir (IRJ)"),
    "carne-joven": ("movilidad", "Carne Joven (IRJ)"),
    "carnes-internacionales": ("movilidad", "Carnes internacionales para jovenes (IRJ)"),
    "voluntariado": ("formacion", "Voluntariado juvenil (IRJ)"),
    "campos-de-voluntariado": ("formacion", "Campos de voluntariado (IRJ)"),
    "monitores-y-directores": ("formacion", "Cursos de monitor y director de tiempo libre (IRJ)"),
    "emancipacion": ("vivienda", "Pacto por la emancipacion juvenil (IRJ)"),
}


def obtener_html(url: str, verify: bool = True) -> str:
    if not verify:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, verify=verify)
    r.raise_for_status()
    r.encoding = r.encoding or r.apparent_encoding
    return r.text


def _num_tramite(url: str) -> str | None:
    """Extrae el numero de tramite de una URL larioja.org/...tramite?n=XXXXX."""
    if "tramite?n=" not in url:
        return None
    return url.split("tramite?n=", 1)[1].split("&", 1)[0].strip()


def _slug_irj(url: str) -> str | None:
    """Slug de una pagina de contenido de irj.es (ultimo segmento del path)."""
    p = urlparse(url)
    if "irj.es" not in p.netloc:
        return None
    return p.path.strip("/").split("/")[-1] or None


def descubrir_candidatos() -> list[CandidatoFuente]:
    """Lee la pagina de subvenciones del IRJ y devuelve las ayudas a jovenes."""
    # irj.es tiene TLS roto: se lee sin verificar SOLO para descubrir enlaces.
    html = obtener_html(SUBVENCIONES_URL, verify=False)
    enlaces = extraer_enlaces(html, SUBVENCIONES_URL)

    candidatos: list[CandidatoFuente] = []
    urls_vistas: set[str] = set()

    for enlace in enlaces:
        url = enlace.url
        if url in urls_vistas:
            continue

        num = _num_tramite(url)
        if num:
            if num in TRAMITES_SKIP or num not in TRAMITES_CIUDADANO:
                continue
            categoria, nombre = TRAMITES_CIUDADANO[num]
            urls_vistas.add(url)
            candidatos.append(CandidatoFuente(
                nombre=nombre, ambito="larioja", categoria=categoria,
                url_oficial=url, tipo_fuente="html", organismo=ORGANISMO,
            ))
            continue

        slug = _slug_irj(url)
        if slug in PAGINAS_IRJ:
            categoria, nombre = PAGINAS_IRJ[slug]
            urls_vistas.add(url)
            candidatos.append(CandidatoFuente(
                nombre=nombre, ambito="larioja", categoria=categoria,
                url_oficial=url, tipo_fuente="html", organismo=ORGANISMO,
            ))

    return candidatos


def escribir_jsonl(candidatos: list[CandidatoFuente], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as f:
        for c in candidatos:
            f.write(json.dumps({
                "nombre": c.nombre, "ambito": c.ambito, "categoria": c.categoria,
                "url_oficial": c.url_oficial, "tipo_fuente": c.tipo_fuente,
                "organismo": c.organismo,
            }, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Descubre ayudas del IRJ y genera candidatos JSONL.")
    parser.add_argument(
        "--salida", type=Path,
        default=Path(__file__).parent.parent.parent.parent / "data" / "candidatos_irj.jsonl",
        help="Archivo JSONL de salida",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Descubrimiento IRJ (Instituto Riojano de la Juventud)")
    print("=" * 60)

    candidatos = descubrir_candidatos()
    if not candidatos:
        print("No se encontraron ayudas del IRJ.")
        return

    escribir_jsonl(candidatos, args.salida)
    print(f"Listo. {len(candidatos)} candidatos -> {args.salida}")
    for c in candidatos:
        print(f"  - [{c.categoria}] {c.nombre}")
    print("\nPara probar extraccion:")
    print(f"  python src/ingestar_fuentes.py --candidatos {args.salida}")
    print("Para indexar:")
    print(f"  python src/ingestar_fuentes.py --candidatos {args.salida} --indexar")


if __name__ == "__main__":
    main()
