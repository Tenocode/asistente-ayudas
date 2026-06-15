from io import BytesIO

import requests
from pypdf import PdfReader

from ingesta.modelos import CandidatoFuente, FuenteExtraida
from ingesta.texto import normalizar_texto

TIMEOUT = 30


def extraer_pdf(candidato: CandidatoFuente) -> FuenteExtraida:
    url = candidato.url_descarga or candidato.url_oficial
    respuesta = requests.get(url, timeout=TIMEOUT)
    respuesta.raise_for_status()

    lector = PdfReader(BytesIO(respuesta.content))
    paginas = [pagina.extract_text() or "" for pagina in lector.pages]
    # Normaliza símbolos (NFKC, control, U+FFFF/uso-privado→espacio) antes de
    # trocear; ver ingesta/texto.py. Sin esto algunos PDFs pegan las palabras.
    texto = normalizar_texto("\n".join(paginas)).strip()

    return FuenteExtraida(
        nombre=candidato.nombre,
        ambito=candidato.ambito,
        categoria=candidato.categoria,
        url_oficial=candidato.url_oficial,
        tipo_fuente="pdf",
        texto_extraido=texto,
        organismo=candidato.organismo,
        url_tramite=candidato.url_tramite,
        origen_archivo=candidato.url_oficial.rsplit("/", 1)[-1],
    )
