"""
Conector Ayuntamiento de Logroño.

BDNS solo trae de Logroño sus actos administrativos ("Acuerdo de Junta de Gobierno");
las ayudas municipales REALES (Chiquibecas de educacion infantil, libros y material
escolar, ayudas a mayores de 85, Erasmus municipal, servicios sociales...) solo estan
en su portal: logrono.es/becas-y-subvenciones (listado paginado, fichas en logrono.es/-/).

Patron region-first (como el barrido BDNS): enumera TODAS las fichas, descarta el ruido
(actos de ciclo de vida —adjudicacion/concesion/pago—, ayudas a entidades/empresas,
cooperacion internacional, concursos festivos), clasifica por categoria y deja en un
informe lo que no clasifica. No indexa: el importador comun valida y deduplica.
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from ingesta.fuentes.ader import extraer_enlaces
from ingesta.fuentes.bdns import _anio_de, _clave_dedup, _dedup_ediciones, _normalizar_ascii
from ingesta.modelos import CandidatoFuente

LISTADO_URL = "https://logrono.es/becas-y-subvenciones"
ORGANISMO = "Ayuntamiento de Logroño"
USER_AGENT = "asistente-ayudas/0.1 (+lectura de fuentes oficiales)"
TIMEOUT = 30

# Ruido a descartar (titulo normalizado). Sobre todo ACTOS DE CICLO DE VIDA (no son la
# convocatoria abierta), ayudas a ENTIDADES/EMPRESAS, COOPERACION internacional y
# CONCURSOS festivos. Conservador con "subvenciones a obras" (esas SI pueden ser a vecinos).
BLACKLIST_LOGRONO = (
    "adjudicacion", "adjudicatari", "concesion definitiva", "concesion provisional",
    "concesion de subvenciones", "listados definitivos", "listado definitivo", "excluidos",
    "cierre de convocatoria", "pago de", "abono a", "abono de", "adenda", "bases reguladoras",
    "asignacion grupos politicos", "aportacion municipal", "asignacion economica",
    "mantenimiento", "medidas de continuidad", "contrato de gestion", "continuidad del contrato",
    "impreso", "modelo de solicitud", "anexo",
    # beneficiario = entidad/empresa, no ciudadano
    "asociaci", "entidad", "vecinal", "gremial", "zonales", "a empresas", "club", "federaci",
    "utilidad publica", "consejo", "isfl", "fundacion", "a colectivos",
    # cooperacion internacional / emergencias externas
    "gaza", "cruz roja", "marruecos", "cooperacion", "humanitaria", "ucrania", "terremoto",
    # actos varios / festejos
    "concurso", "premio", "carnaval", "criterios de participacion", "musicarte",
)

# Clasificador municipal (terminos en minuscula sin tildes; match por inicio de palabra).
# Orden: nicho especifico primero. Incluye terminos propios de Logroño (chiquibeca).
CLASIFICADOR_LOGRONO = {
    "carnet":      ["carne de conducir", "permiso de conducir", "autoescuela"],
    "vivienda":    ["vivienda", "alquiler", "rehabilitacion", "accesibilidad", "patrimonio",
                    "adecuacion de la accesibilidad", "emancip"],
    "dependencia": ["mayores de 85", "personas mayores", "dependencia", "discapacit",
                    "tercera edad", "autonomia personal"],
    "movilidad":   ["erasmus", "movilidad"],
    "formacion":   ["chiquibeca", "educacion infantil", "primer ciclo", "segundo ciclo",
                    "libros", "material didactico", "material escolar", "beca", "comedor",
                    "estudio", "estudios", "guarderia"],
    "empleo":      ["comercio", "turismo", "iniciativas economicas", "iniciativas empres",
                    "microempresas", "empleo", "emprend", "autonomo", "dinamizacion"],
    "cultura":     ["cultura", "cultural", "musica", "arte"],
}


def obtener_html(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.encoding or r.apparent_encoding
    return r.text


def enumerar_fichas(max_paginas: int = 10) -> dict[str, str]:
    """Devuelve {url_ficha: titulo} recorriendo el listado paginado."""
    fichas: dict[str, str] = {}
    for start in range(1, max_paginas + 1):
        url = f"{LISTADO_URL}?delta=60&start={start}"
        try:
            html = obtener_html(url)
        except Exception as e:
            print(f"  [ERROR] pagina {start}: {e}")
            break
        nuevos = 0
        for e in extraer_enlaces(html, url):
            if "logrono.es/-/" in e.url and e.url not in fichas:
                fichas[e.url] = (e.texto or "").strip()
                nuevos += 1
        print(f"  pagina {start}: +{nuevos} (total {len(fichas)})")
        if nuevos == 0:
            break
    return fichas


def _pasa_blacklist(titulo: str) -> bool:
    t = _normalizar_ascii(titulo)
    return not any(b in t for b in BLACKLIST_LOGRONO)


def clasificar(titulo: str) -> str | None:
    t = _normalizar_ascii(titulo)
    for categoria, terminos in CLASIFICADOR_LOGRONO.items():
        for term in terminos:
            if re.search(r"\b" + re.escape(term), t):
                return categoria
    return None


def descubrir() -> tuple[list[CandidatoFuente], list[tuple], dict]:
    fichas = enumerar_fichas()
    descartadas = antiguas = 0
    items: list[tuple] = []   # (pseudo_conv, ambito, categoria) para dedup
    revision: list[tuple] = []  # (titulo, url)
    ANIO_MIN = 2024  # descarta histórico; nos quedamos con lo vigente/reciente

    for url, titulo in fichas.items():
        if not titulo:
            continue
        anio = _anio_de(titulo)
        if anio and anio < ANIO_MIN:
            antiguas += 1
            continue
        if not _pasa_blacklist(titulo):
            descartadas += 1
            continue
        cat = clasificar(titulo)
        if cat:
            conv = {"descripcion": titulo, "numeroConvocatoria": None, "_url": url}
            items.append((conv, "larioja", cat))
        else:
            revision.append((titulo, url))

    items, colapsadas = _dedup_ediciones(items)
    clasificadas = len(items)

    candidatos = [
        CandidatoFuente(
            nombre=conv["descripcion"][:200], ambito=amb, categoria=cat,
            url_oficial=conv["_url"], tipo_fuente="html", organismo=ORGANISMO,
        )
        for conv, amb, cat in items
    ]
    reparto: dict[str, int] = defaultdict(int)
    for _, _, cat in items:
        reparto[cat] += 1
    stats = {
        "fichas": len(fichas), "antiguas": antiguas, "descartadas": descartadas,
        "clasificadas": clasificadas, "colapsadas": colapsadas,
        "revision": len(revision), "reparto": dict(reparto),
    }
    return candidatos, revision, stats


def escribir_jsonl(candidatos: list[CandidatoFuente], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8") as f:
        for c in candidatos:
            f.write(json.dumps({
                "nombre": c.nombre, "ambito": c.ambito, "categoria": c.categoria,
                "url_oficial": c.url_oficial, "tipo_fuente": c.tipo_fuente,
                "organismo": c.organismo,
            }, ensure_ascii=False) + "\n")


def escribir_revision(revision: list[tuple], stats: dict, ruta: Path) -> None:
    L = ["# Revisión Logroño — fichas no clasificadas", "",
         f"Fichas totales: {stats['fichas']} · descartadas (ruido): {stats['descartadas']} · "
         f"clasificadas: {stats['clasificadas']} (colapsadas {stats['colapsadas']}) · "
         f"sin clasificar: {stats['revision']}", "",
         "Reparto clasificadas: " + ", ".join(f"{k}={v}" for k, v in stats["reparto"].items()), "",
         "## Sin clasificar (revisar por si alguna es ayuda a ciudadanos)", ""]
    for titulo, url in sorted(revision):
        L.append(f"- {titulo[:110]}")
        L.append(f"  - {url}")
    ruta.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Descubre ayudas municipales de Logroño.")
    parser.add_argument("--salida", type=Path,
                        default=Path(__file__).parent.parent.parent.parent / "data" / "candidatos_logrono.jsonl")
    parser.add_argument("--revision", type=Path,
                        default=Path(__file__).parent.parent.parent.parent / "data" / "revision_logrono.md")
    args = parser.parse_args()

    print("=" * 60)
    print("  Descubrimiento Ayuntamiento de Logroño")
    print("=" * 60)
    candidatos, revision, stats = descubrir()
    escribir_jsonl(candidatos, args.salida)
    escribir_revision(revision, stats, args.revision)

    print(f"\n  Fichas: {stats['fichas']} | descartadas: {stats['descartadas']} | "
          f"clasificadas: {stats['clasificadas']} (colapsadas {stats['colapsadas']}) | "
          f"sin clasificar: {stats['revision']}")
    print(f"  Reparto: {stats['reparto']}")
    print(f"  Candidatos -> {args.salida}")
    print(f"  Revisión   -> {args.revision}")
    for c in candidatos:
        print(f"    - [{c.categoria}] {c.nombre[:65]}")


if __name__ == "__main__":
    main()
