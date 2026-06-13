import psycopg2

DSN = "host=localhost port=5432 dbname=ayudas user=ayudas password=ayudas"

SQL_EXTENSION = "CREATE EXTENSION IF NOT EXISTS vector;"

SQL_DROP_FRAGMENTOS = "DROP TABLE IF EXISTS fragmentos;"
SQL_DROP_FUENTES = "DROP TABLE IF EXISTS fuentes;"

SQL_FUENTES = """
CREATE TABLE fuentes (
    id             SERIAL PRIMARY KEY,
    nombre         TEXT NOT NULL,
    ambito         TEXT NOT NULL,
    categoria      TEXT NOT NULL,
    url_oficial    TEXT,
    tipo_fuente    TEXT NOT NULL DEFAULT 'pdf',
    origen_archivo TEXT,
    fecha_revision TIMESTAMPTZ NOT NULL DEFAULT now(),
    fecha_fin      DATE,
    estado         TEXT NOT NULL DEFAULT 'desconocida',
    texto_extraido TEXT NOT NULL DEFAULT ''
);
"""

SQL_FRAGMENTOS = """
CREATE TABLE fragmentos (
    id              SERIAL PRIMARY KEY,
    fuente_id       INTEGER NOT NULL REFERENCES fuentes(id) ON DELETE CASCADE,
    numero_fragmento INTEGER NOT NULL,
    texto           TEXT NOT NULL,
    embedding       vector(384)
);
"""

SQL_INDICES = """
CREATE INDEX idx_fuentes_ambito ON fuentes (ambito);
CREATE INDEX idx_fuentes_categoria ON fuentes (categoria);
CREATE INDEX idx_fragmentos_fuente_id ON fragmentos (fuente_id);
"""


def init_db() -> None:
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL_EXTENSION)
            cur.execute(SQL_DROP_FRAGMENTOS)
            cur.execute(SQL_DROP_FUENTES)
            cur.execute(SQL_FUENTES)
            cur.execute(SQL_FRAGMENTOS)
            cur.execute(SQL_INDICES)
        conn.commit()
    print("Base de datos inicializada correctamente.")


if __name__ == "__main__":
    init_db()
