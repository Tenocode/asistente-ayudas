import psycopg2
import psycopg2.extras
from sentence_transformers import SentenceTransformer

from descargar import limpiar_nombre, parsear_lineas, URLS_FILE
from ingesta.trocear import DIRECTORIO_PDFS, procesar_pdfs
from db.init_db import DSN

MODELO = "paraphrase-multilingual-MiniLM-L12-v2"


def construir_metadatos(ruta_urls) -> dict:
    """Devuelve un dict { slug: {nombre, ambito, categoria, url} } leyendo urls.txt."""
    metadatos = {}
    for entrada in parsear_lineas(ruta_urls):
        slug = limpiar_nombre(entrada["nombre"])
        metadatos[slug] = {
            "nombre": entrada["nombre"],
            "ambito": entrada["ambito"],
            "categoria": entrada["categoria"],
            "url": entrada["url"],
        }
    return metadatos


def meta_para_fragmento(fragmento: dict, metadatos: dict) -> tuple[str, dict]:
    slug = fragmento["origen"].removesuffix(".pdf")
    meta = metadatos.get(slug, {
        "nombre": slug,
        "ambito": "desconocido",
        "categoria": "desconocida",
        "url": None,
    })
    return slug, meta


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
            cur.execute("TRUNCATE TABLE fragmentos, fuentes RESTART IDENTITY CASCADE;")

            fuentes: dict[str, dict] = {}
            for fragmento in fragmentos:
                slug, meta = meta_para_fragmento(fragmento, metadatos)
                if slug not in fuentes:
                    fuentes[slug] = {
                        "meta": meta,
                        "origen_archivo": fragmento["origen"],
                        "textos": [],
                    }
                fuentes[slug]["textos"].append(fragmento["texto"])

            fuente_ids: dict[str, int] = {}
            for slug, fuente in fuentes.items():
                meta = fuente["meta"]
                texto_extraido = "\n\n".join(fuente["textos"])
                cur.execute(
                    """
                    INSERT INTO fuentes (
                        nombre, ambito, categoria, url_oficial,
                        tipo_fuente, origen_archivo, texto_extraido
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        meta["nombre"],
                        meta["ambito"],
                        meta["categoria"],
                        meta["url"],
                        "pdf",
                        fuente["origen_archivo"],
                        texto_extraido,
                    ),
                )
                fuente_ids[slug] = cur.fetchone()[0]

            filas = []
            contadores: dict[str, int] = {}
            for fragmento, embedding in zip(fragmentos, embeddings):
                slug, _ = meta_para_fragmento(fragmento, metadatos)
                contadores[slug] = contadores.get(slug, 0) + 1
                filas.append((
                    fuente_ids[slug],
                    contadores[slug],
                    fragmento["texto"],
                    str(embedding.tolist()),
                ))

            psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO fragmentos (fuente_id, numero_fragmento, texto, embedding)
                VALUES %s
                """,
                filas,
                template="(%s, %s, %s, %s::vector)",
            )

        conn.commit()

    print(
        f"\nListo. {len(fuentes)} fuentes y {len(filas)} fragmentos insertados en Postgres."
    )


if __name__ == "__main__":
    indexar()
