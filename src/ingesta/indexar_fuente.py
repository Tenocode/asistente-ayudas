import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.init_db import DSN
from ingesta.trocear import SOLAPAMIENTO, TAMANO_FRAGMENTO, trocear
from ingesta.modelos import FuenteExtraida

MODELO = "paraphrase-multilingual-MiniLM-L12-v2"

_modelo_cache: SentenceTransformer | None = None


def _get_modelo() -> SentenceTransformer:
    global _modelo_cache
    if _modelo_cache is None:
        print(f"  Cargando modelo '{MODELO}'...")
        _modelo_cache = SentenceTransformer(MODELO)
    return _modelo_cache


def indexar_fuente(fuente: FuenteExtraida) -> str:
    """
    Inserta una FuenteExtraida en Postgres con sus fragmentos y embeddings.
    Devuelve 'indexada' o 'ya_existia'. Lanza excepción si falla.
    """
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM fuentes WHERE url_oficial = %s",
                (fuente.url_oficial,),
            )
            if cur.fetchone():
                return "ya_existia"

            cur.execute(
                """
                INSERT INTO fuentes (nombre, ambito, categoria, url_oficial,
                                     tipo_fuente, origen_archivo, texto_extraido)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    fuente.nombre,
                    fuente.ambito,
                    fuente.categoria,
                    fuente.url_oficial,
                    fuente.tipo_fuente,
                    fuente.origen_archivo,
                    fuente.texto_extraido,
                ),
            )
            fuente_id = cur.fetchone()[0]

            textos = trocear(fuente.texto_extraido, TAMANO_FRAGMENTO, SOLAPAMIENTO)
            if not textos:
                conn.commit()
                return "indexada"

            modelo = _get_modelo()
            embeddings = modelo.encode(textos, show_progress_bar=False)

            filas = [
                (fuente_id, i + 1, texto, str(emb.tolist()))
                for i, (texto, emb) in enumerate(zip(textos, embeddings))
            ]
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
    return "indexada"
