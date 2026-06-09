import psycopg2
import psycopg2.extras
from sentence_transformers import SentenceTransformer

from descargar import limpiar_nombre, parsear_lineas, URLS_FILE
from trocear import DIRECTORIO_PDFS, procesar_pdfs
from init_db import DSN

MODELO = "paraphrase-multilingual-MiniLM-L12-v2"


def construir_metadatos(ruta_urls) -> dict:
    """Devuelve un dict { slug: {nombre, ambito, categoria} } leyendo urls.txt."""
    metadatos = {}
    for entrada in parsear_lineas(ruta_urls):
        slug = limpiar_nombre(entrada["nombre"])
        metadatos[slug] = {
            "nombre": entrada["nombre"],
            "ambito": entrada["ambito"],
            "categoria": entrada["categoria"],
        }
    return metadatos


def indexar() -> None:
    print("Troceando PDFs...")
    fragmentos = procesar_pdfs(DIRECTORIO_PDFS)
    print(f"  {len(fragmentos)} fragmentos generados.\n")

    metadatos = construir_metadatos(URLS_FILE)

    print(f"Cargando modelo '{MODELO}' (primera vez descarga ~90 MB)...")
    modelo = SentenceTransformer(MODELO)

    print("Generando embeddings...")
    textos = [f["texto"] for f in fragmentos]
    embeddings = modelo.encode(textos, show_progress_bar=True)

    print("\nInsertando en Postgres...")
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE fragmentos;")

            filas = []
            for fragmento, embedding in zip(fragmentos, embeddings):
                slug = fragmento["origen"].removesuffix(".pdf")
                meta = metadatos.get(slug, {
                    "nombre": slug,
                    "ambito": "desconocido",
                    "categoria": "desconocida",
                })
                filas.append((
                    meta["nombre"],
                    meta["ambito"],
                    meta["categoria"],
                    fragmento["texto"],
                    str(embedding.tolist()),
                ))

            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO fragmentos (nombre, ambito, categoria, texto, embedding)
                VALUES %s
                """,
                filas,
                template="(%s, %s, %s, %s, %s::vector)",
            )

        conn.commit()

    print(f"\nListo. {len(filas)} fragmentos insertados en la tabla `fragmentos`.")


if __name__ == "__main__":
    indexar()
