from pathlib import Path

from pypdf import PdfReader

from ingesta.texto import normalizar_texto

# Tres niveles arriba desde src/ingesta/ → raíz del proyecto
DIRECTORIO_PDFS = Path(__file__).parent.parent.parent / "data" / "convocatorias"
TAMANO_FRAGMENTO = 500
SOLAPAMIENTO = 50


def extraer_texto(ruta_pdf: Path) -> str:
    lector = PdfReader(ruta_pdf)
    paginas = [pagina.extract_text() or "" for pagina in lector.pages]
    # Normaliza símbolos (NFKC, control, U+FFFF/uso-privado→espacio). Algunos PDFs
    # (juventud/vivienda de La Rioja) usan U+FFFF como espacio, lo que pega las
    # palabras y rompe el troceo.
    return normalizar_texto("\n".join(paginas))


def trocear(texto: str, tamano: int, solapamiento: int) -> list[str]:
    palabras = texto.split()
    fragmentos = []
    inicio = 0
    paso = tamano - solapamiento

    while inicio < len(palabras):
        fin = inicio + tamano
        fragmento = " ".join(palabras[inicio:fin])
        fragmentos.append(fragmento)
        if fin >= len(palabras):
            break
        inicio += paso

    return fragmentos


def procesar_pdfs(directorio: Path) -> list[dict]:
    resultado = []
    pdfs = sorted(directorio.glob("*.pdf"))

    if not pdfs:
        print(f"No se encontraron PDFs en {directorio}")
        return resultado

    for ruta_pdf in pdfs:
        try:
            texto = extraer_texto(ruta_pdf)
        except Exception as e:
            print(f"  [SKIP] {ruta_pdf.name}: no es un PDF válido ({e})")
            continue
        fragmentos = trocear(texto, TAMANO_FRAGMENTO, SOLAPAMIENTO)
        for fragmento in fragmentos:
            resultado.append({
                "origen": ruta_pdf.name,
                "texto": fragmento,
            })
        print(f"  {ruta_pdf.name}: {len(fragmentos)} fragmentos")

    return resultado
