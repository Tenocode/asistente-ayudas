import json
from pathlib import Path
from typing import Iterable

from ingesta.adaptadores.html import extraer_html
from ingesta.adaptadores.pdf import extraer_pdf
from ingesta.modelos import CandidatoFuente, FuenteExtraida


def leer_candidatos(ruta: Path) -> list[CandidatoFuente]:
    candidatos = []
    with ruta.open(encoding="utf-8") as f:
        for numero_linea, linea in enumerate(f, start=1):
            linea = linea.strip()
            if not linea:
                continue
            try:
                datos = json.loads(linea)
            except json.JSONDecodeError as e:
                raise ValueError(f"{ruta}:{numero_linea}: JSON invalido: {e}") from e

            candidatos.append(CandidatoFuente(**datos))
    return candidatos


def detectar_tipo(candidato: CandidatoFuente) -> str:
    if candidato.tipo_fuente != "auto":
        return candidato.tipo_fuente
    url = candidato.url_oficial.lower().split("?", 1)[0]
    if url.endswith(".pdf"):
        return "pdf"
    return "html"


def extraer_candidato(candidato: CandidatoFuente) -> FuenteExtraida:
    tipo = detectar_tipo(candidato)
    if tipo == "pdf":
        return extraer_pdf(candidato)
    if tipo in {"html", "web", "sede", "boletin"}:
        return extraer_html(candidato)
    if tipo == "bdns_api":
        if not candidato.texto_inline:
            raise ValueError("tipo_fuente='bdns_api' requiere texto_inline")
        return FuenteExtraida(
            nombre=candidato.nombre,
            ambito=candidato.ambito,
            categoria=candidato.categoria,
            url_oficial=candidato.url_oficial,
            tipo_fuente="bdns_api",
            texto_extraido=candidato.texto_inline,
            organismo=candidato.organismo,
            url_tramite=candidato.url_tramite,
            origen_archivo=None,
        )
    raise ValueError(f"Tipo de fuente no soportado: {tipo}")


def extraer_candidatos(candidatos: Iterable[CandidatoFuente]) -> list[FuenteExtraida]:
    fuentes = []
    for candidato in candidatos:
        fuentes.append(extraer_candidato(candidato))
    return fuentes
