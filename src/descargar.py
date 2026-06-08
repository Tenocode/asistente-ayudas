import re
import unicodedata
from pathlib import Path

import requests

URLS_FILE = Path(__file__).parent.parent / "data" / "urls.txt"
DESTINO = Path(__file__).parent.parent / "data" / "convocatorias"
TIMEOUT = 30


def limpiar_nombre(nombre: str) -> str:
    """Convierte un nombre a slug: sin tildes, minúsculas, guiones."""
    # Descompone caracteres acentuados (é → e + acento) y descarta los acentos
    normalizado = unicodedata.normalize("NFKD", nombre)
    solo_ascii = normalizado.encode("ascii", errors="ignore").decode("ascii")
    # Minúsculas y espacios → guiones
    slug = solo_ascii.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def parsear_lineas(ruta: Path) -> list[dict]:
    """Lee urls.txt y devuelve una lista de dicts con los campos de cada línea."""
    entradas = []
    with ruta.open(encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            # Quita el número de índice inicial si lo hay (p.ej. "1\t")
            partes_tab = linea.split("\t", maxsplit=1)
            cuerpo = partes_tab[-1]  # parte después del tabulador, o la línea entera
            campos = [c.strip() for c in cuerpo.split("|")]
            if len(campos) < 4:
                continue
            entradas.append({
                "nombre": campos[0],
                "ambito": campos[1],
                "categoria": campos[2],
                "url": campos[3],
            })
    return entradas


def descargar_pdf(url: str, destino: Path) -> None:
    """Descarga un PDF en modo streaming y lo guarda en destino."""
    respuesta = requests.get(url, timeout=TIMEOUT, stream=True)
    respuesta.raise_for_status()  # lanza excepción si el servidor devuelve 4xx/5xx
    with destino.open("wb") as f:
        for bloque in respuesta.iter_content(chunk_size=8192):
            f.write(bloque)


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    entradas = parsear_lineas(URLS_FILE)

    exitosos = []
    fallidos = []

    for entrada in entradas:
        nombre = entrada["nombre"]
        url = entrada["url"]
        slug = limpiar_nombre(nombre)
        ruta_pdf = DESTINO / f"{slug}.pdf"

        if ruta_pdf.exists():
            print(f"[SKIP]  {slug}.pdf ya existe")
            exitosos.append(nombre)
            continue

        print(f"[DOWN]  {slug}.pdf ← {url}")
        try:
            descargar_pdf(url, ruta_pdf)
            exitosos.append(nombre)
            print(f"[OK]    {slug}.pdf")
        except requests.exceptions.HTTPError as e:
            fallidos.append((nombre, f"HTTP {e.response.status_code}: {e}"))
            print(f"[FAIL]  {nombre} → HTTP {e.response.status_code}")
        except requests.exceptions.ConnectionError:
            fallidos.append((nombre, "No se pudo conectar al servidor"))
            print(f"[FAIL]  {nombre} → sin conexión")
        except requests.exceptions.Timeout:
            fallidos.append((nombre, f"Timeout tras {TIMEOUT}s"))
            print(f"[FAIL]  {nombre} → timeout")
        except Exception as e:
            fallidos.append((nombre, str(e)))
            print(f"[FAIL]  {nombre} → {e}")
            # Si el archivo quedó a medias, lo borramos
            if ruta_pdf.exists():
                ruta_pdf.unlink()

    print("\n" + "=" * 60)
    print(f"Descargados correctamente : {len(exitosos)}/{len(entradas)}")
    if fallidos:
        print(f"Fallidos ({len(fallidos)}):")
        for nombre, error in fallidos:
            print(f"  - {nombre}: {error}")


if __name__ == "__main__":
    main()
