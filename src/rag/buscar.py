import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from sentence_transformers import SentenceTransformer

from db.init_db import DSN

MODELO = "paraphrase-multilingual-MiniLM-L12-v2"
TOP_K = 5

_modelo_cache: SentenceTransformer | None = None


def _get_modelo() -> SentenceTransformer:
    global _modelo_cache
    if _modelo_cache is None:
        _modelo_cache = SentenceTransformer(MODELO)
    return _modelo_cache


def buscar(pregunta: str, k: int = TOP_K) -> list[dict]:
    modelo = _get_modelo()
    embedding = modelo.encode(pregunta)
    vector_str = str(embedding.tolist())

    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fuentes.nombre, fuentes.ambito, fuentes.categoria,
                       fuentes.url_oficial, fuentes.tipo_fuente,
                       fragmentos.texto,
                       fragmentos.embedding <=> %s::vector AS distancia
                FROM fragmentos
                JOIN fuentes ON fuentes.id = fragmentos.fuente_id
                ORDER BY distancia ASC
                LIMIT %s;
                """,
                (vector_str, k),
            )
            filas = cur.fetchall()

    return [
        {
            "nombre": fila[0],
            "ambito": fila[1],
            "categoria": fila[2],
            "url_oficial": fila[3],
            "tipo_fuente": fila[4],
            "texto": fila[5],
            "distancia": round(fila[6], 4),
        }
        for fila in filas
    ]


def buscar_filtrado(
    pregunta: str,
    comunidad: str | None = None,
    categoria: str | None = None,
    k: int = TOP_K,
) -> list[dict]:
    modelo = _get_modelo()
    embedding = modelo.encode(pregunta)
    vector_str = str(embedding.tolist())

    condiciones = []
    params: list = [vector_str]

    if comunidad and comunidad != "todas":
        condiciones.append("(fuentes.ambito = %s OR fuentes.ambito = 'estatal')")
        params.append(comunidad)
    if categoria and categoria != "todas":
        condiciones.append("fuentes.categoria = %s")
        params.append(categoria)

    where = ("WHERE " + " AND ".join(condiciones)) if condiciones else ""
    params.append(k)

    sql = f"""
        SELECT fuentes.nombre, fuentes.ambito, fuentes.categoria,
               fuentes.url_oficial, fuentes.tipo_fuente,
               fragmentos.texto,
               fragmentos.embedding <=> %s::vector AS distancia
        FROM fragmentos
        JOIN fuentes ON fuentes.id = fragmentos.fuente_id
        {where}
        ORDER BY distancia ASC
        LIMIT %s;
    """

    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            filas = cur.fetchall()

    return [
        {
            "nombre": fila[0],
            "ambito": fila[1],
            "categoria": fila[2],
            "url_oficial": fila[3],
            "tipo_fuente": fila[4],
            "texto": fila[5],
            "distancia": round(fila[6], 4),
        }
        for fila in filas
    ]


def main() -> None:
    pregunta = input("¿Qué ayuda estás buscando? > ").strip()
    if not pregunta:
        print("No has escrito nada.")
        return

    print(f"\nBuscando los {TOP_K} fragmentos más relevantes...\n")
    resultados = buscar(pregunta)

    for i, r in enumerate(resultados, start=1):
        print(f"{'=' * 60}")
        print(f"#{i}  {r['nombre']}")
        print(f"    Ámbito: {r['ambito']} | Categoría: {r['categoria']} | Distancia: {r['distancia']}")
        print(f"    {r['texto'][:300].strip()}...")
        print()


if __name__ == "__main__":
    main()
