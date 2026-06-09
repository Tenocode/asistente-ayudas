from pathlib import Path

from pypdf import PdfReader

DIRECTORIO_PDFS = Path(__file__).parent.parent / "data" / "convocatorias"
TAMANO_FRAGMENTO = 500   # palabras
SOLAPAMIENTO = 50        # palabras


def extraer_texto(ruta_pdf: Path) -> str:
    """Devuelve todo el texto de un PDF concatenando todas sus páginas."""
    lector = PdfReader(ruta_pdf)
    paginas = [pagina.extract_text() or "" for pagina in lector.pages]
    texto = "\n".join(paginas)
    return texto.replace("\x00", "")


def trocear(texto: str, tamano: int, solapamiento: int) -> list[str]:
    """
    Parte texto en fragmentos de `tamano` palabras con `solapamiento` palabras
    de contexto compartido entre fragmentos consecutivos.
    """
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
    """
    Lee todos los PDFs del directorio y devuelve una lista de dicts con
    las claves 'origen' (nombre del archivo) y 'texto' (texto del fragmento).
    """
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


def main() -> None:
    print(f"Leyendo PDFs de: {DIRECTORIO_PDFS}\n")
    fragmentos = procesar_pdfs(DIRECTORIO_PDFS)

    print(f"\nTotal de fragmentos generados: {len(fragmentos)}")
    print("\n" + "=" * 60)
    print("FRAGMENTO 1")
    print("=" * 60)
    print(f"Origen : {fragmentos[0]['origen']}")
    print(f"Texto  :\n{fragmentos[0]['texto']}")
    print("\n" + "=" * 60)
    print("FRAGMENTO 2")
    print("=" * 60)
    print(f"Origen : {fragmentos[1]['origen']}")
    print(f"Texto  :\n{fragmentos[1]['texto']}")


if __name__ == "__main__":
    main()
