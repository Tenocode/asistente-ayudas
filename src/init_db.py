import psycopg2

DSN = "host=localhost port=5432 dbname=ayudas user=ayudas password=ayudas"

SQL_EXTENSION = "CREATE EXTENSION IF NOT EXISTS vector;"

SQL_DROP_TABLA = "DROP TABLE IF EXISTS fragmentos;"

SQL_TABLA = """
CREATE TABLE fragmentos (
    id        SERIAL PRIMARY KEY,
    nombre    TEXT NOT NULL,
    ambito    TEXT NOT NULL,
    categoria TEXT NOT NULL,
    texto     TEXT NOT NULL,
    embedding vector(384)
);
"""


def init_db() -> None:
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_EXTENSION)
            cur.execute(SQL_DROP_TABLA)
            cur.execute(SQL_TABLA)
        conn.commit()
    print("Base de datos inicializada correctamente.")


if __name__ == "__main__":
    init_db()
