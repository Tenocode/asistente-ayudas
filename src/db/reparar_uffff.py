"""
Reparación puntual: limpia el espacio U+FFFF de las fuentes ya indexadas.

Algunos PDFs (juventud/vivienda de La Rioja) y alguna ficha HTML codifican el
espacio como U+FFFF, lo que pega las palabras ("cuantia<>de<>250<>euros") y, de
paso, rompe el troceo (trocear() parte por espacios, así que un bloque pegado
cuenta como UNA sola palabra y los fragmentos salen sobredimensionados).

El código de ingesta ya normaliza U+FFFF en origen (pdf.py, trocear.py, html.py),
así que las ingestas NUEVAS salen limpias. Este script repara lo que YA está en la
base de datos, en sitio y sin red:

  - PDF local  -> re-extrae del fichero en data/convocatorias (ya normaliza).
  - Otra fuente (conector PDF/HTML) -> limpia el texto_extraido ya guardado
    (que es el texto completo del que salen los fragmentos).

Luego re-trocea, re-embebe y reemplaza solo los fragmentos de esa fuente.
No toca el resto del corpus. Es idempotente: re-ejecutarlo no cambia nada si ya
no quedan U+FFFF.
"""
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras
from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).parent.parent))

from db.init_db import DSN
from ingesta.trocear import (
    DIRECTORIO_PDFS,
    SOLAPAMIENTO,
    TAMANO_FRAGMENTO,
    extraer_texto,
    trocear,
)

MODELO = "paraphrase-multilingual-MiniLM-L12-v2"
UFFFF = "￿"


def texto_limpio_de_fuente(origen_archivo: str | None, texto_guardado: str) -> str:
    """Devuelve el texto completo limpio: re-extraído si es PDF local, si no
    limpiando el que ya teníamos almacenado."""
    if origen_archivo:
        ruta = DIRECTORIO_PDFS / origen_archivo
        if ruta.exists():
            return extraer_texto(ruta)  # ya normaliza U+FFFF y \x00
    return texto_guardado.replace("\x00", "").replace(UFFFF, " ")


def reparar() -> None:
    print(f"Cargando modelo '{MODELO}'...")
    modelo = SentenceTransformer(MODELO)

    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, tipo_fuente, origen_archivo, texto_extraido, nombre "
                "FROM fuentes WHERE texto_extraido LIKE %s ORDER BY id",
                (f"%{UFFFF}%",),
            )
            afectadas = cur.fetchall()

            if not afectadas:
                print("No quedan fuentes con U+FFFF. Nada que reparar.")
                return

            print(f"Fuentes a reparar: {len(afectadas)}\n")
            for fuente_id, tipo, origen, texto_guardado, nombre in afectadas:
                texto = texto_limpio_de_fuente(origen, texto_guardado)
                fragmentos = trocear(texto, TAMANO_FRAGMENTO, SOLAPAMIENTO)

                cur.execute(
                    "SELECT count(*) FROM fragmentos WHERE fuente_id = %s", (fuente_id,)
                )
                antes = cur.fetchone()[0]

                embeddings = modelo.encode(fragmentos, show_progress_bar=False)
                cur.execute("DELETE FROM fragmentos WHERE fuente_id = %s", (fuente_id,))
                filas = [
                    (fuente_id, i + 1, frag, str(emb.tolist()))
                    for i, (frag, emb) in enumerate(zip(fragmentos, embeddings))
                ]
                psycopg2.extras.execute_values(
                    cur,
                    "INSERT INTO fragmentos (fuente_id, numero_fragmento, texto, embedding) VALUES %s",
                    filas,
                    template="(%s, %s, %s, %s::vector)",
                )
                cur.execute(
                    "UPDATE fuentes SET texto_extraido = %s WHERE id = %s",
                    (texto, fuente_id),
                )

                fuente_local = bool(origen and (DIRECTORIO_PDFS / origen).exists())
                metodo = "re-extraído" if fuente_local else "texto guardado limpiado"
                print(
                    f"  id={fuente_id} [{tipo}] {metodo}: "
                    f"fragmentos {antes} -> {len(filas)}  | {nombre[:50]}"
                )

        conn.commit()
    print("\nReparación completada.")


if __name__ == "__main__":
    reparar()
