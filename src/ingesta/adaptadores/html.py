import re
from html import unescape
from html.parser import HTMLParser

import requests

from ingesta.modelos import CandidatoFuente, FuenteExtraida

TIMEOUT = 30


class _TextoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._ignorar = False
        self._partes: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignorar = True
        if tag in {"p", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self._partes.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignorar = False
        if tag in {"p", "li", "tr", "h1", "h2", "h3", "h4"}:
            self._partes.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignorar:
            self._partes.append(data)

    def texto(self) -> str:
        texto = unescape(" ".join(self._partes))
        texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
        texto = re.sub(r"\n\s+", "\n", texto)
        texto = re.sub(r"\n{3,}", "\n\n", texto)
        return texto.strip()


def limpiar_html(html: str) -> str:
    parser = _TextoHTMLParser()
    parser.feed(html)
    return parser.texto()


def extraer_html(candidato: CandidatoFuente) -> FuenteExtraida:
    respuesta = requests.get(candidato.url_oficial, timeout=TIMEOUT)
    respuesta.raise_for_status()
    respuesta.encoding = respuesta.encoding or respuesta.apparent_encoding
    texto = limpiar_html(respuesta.text)

    return FuenteExtraida(
        nombre=candidato.nombre,
        ambito=candidato.ambito,
        categoria=candidato.categoria,
        url_oficial=candidato.url_oficial,
        tipo_fuente="html",
        texto_extraido=texto,
        organismo=candidato.organismo,
        url_tramite=candidato.url_tramite,
        origen_archivo=None,
    )
