import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlparse

import requests
import urllib3

from ingesta.modelos import CandidatoFuente, FuenteExtraida
from ingesta.texto import normalizar_texto

TIMEOUT = 30
USER_AGENT = "asistente-ayudas/0.1 (+lectura de fuentes oficiales)"

# Hosts oficiales cuyo certificado TLS tiene la cadena mal configurada (no envian el
# certificado intermedio), lo que hace fallar la verificacion de `requests` aunque el
# navegador los abra sin problema. Para estas fuentes PUBLICAS y de SOLO LECTURA
# aceptamos TLS sin verificar. Lista cerrada y explicita; no es un comodin global.
HOSTS_TLS_NO_VERIFICABLE = {"www.irj.es", "irj.es"}


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
        # Normaliza símbolos (NFKC, control, U+FFFF/uso-privado→espacio) antes de
        # colapsar espacios; ver ingesta/texto.py.
        texto = normalizar_texto(texto)
        texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
        texto = re.sub(r"\n\s+", "\n", texto)
        texto = re.sub(r"\n{3,}", "\n\n", texto)
        return texto.strip()


def limpiar_html(html: str) -> str:
    parser = _TextoHTMLParser()
    parser.feed(html)
    return parser.texto()


def extraer_html(candidato: CandidatoFuente) -> FuenteExtraida:
    host = urlparse(candidato.url_oficial).netloc.lower()
    verificar = host not in HOSTS_TLS_NO_VERIFICABLE
    if not verificar:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    respuesta = requests.get(
        candidato.url_oficial,
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT},
        verify=verificar,
    )
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
