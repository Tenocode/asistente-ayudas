"""
Vigencia de convocatorias: extrae la fecha de fin de plazo del texto oficial y
marca cada fuente como abierta / cerrada / desconocida.

No toca embeddings ni fragmentos. Solo:
  1. anade columnas fecha_fin y estado a `fuentes` (idempotente, no destructivo);
  2. rellena esas columnas parseando el texto_extraido que ya tenemos.

Uso:
    python src/db/vigencia.py            # migra + rellena + informe
    python src/db/vigencia.py --informe  # solo muestra el reparto actual
"""
import argparse
import re
import sys
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2

from db.init_db import DSN

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

# "11 de diciembre de 2026"
_RE_FECHA_LARGA = re.compile(r"(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})")
# "1deseptiembrede2025" (PDFs degradados que pierden los espacios al extraer)
_RE_FECHA_PEGADA = re.compile(r"(\d{1,2})de([a-z]+)de(\d{4})")
# "30/09/2026" o "30-09-2026"
_RE_FECHA_NUM = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})")
# Años plausibles (2010-2039) para estimar el horizonte temporal del documento.
_RE_ANIO = re.compile(r"\b(20[1-3]\d)\b")

# Senales de que la fecha que sigue es el CIERRE del plazo.
_CLAVES_CIERRE = (
    "fin de plazo", "finalizara", "finaliza el", "abierto hasta", "hasta el",
    "presentacion de solicitudes", "plazo de presentacion", "plazo de solicitud",
    "plazo de convocatoria",
)


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return texto.encode("ascii", "ignore").decode("ascii")


def _fecha_valida(d: int, m: int, y: int) -> date | None:
    if not (1 <= m <= 12 and 1 <= d <= 31 and 2000 <= y <= 2100):
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _primera_fecha(fragmento: str) -> date | None:
    for patron in (_RE_FECHA_LARGA, _RE_FECHA_PEGADA):
        m = patron.search(fragmento)
        if m:
            mes = MESES.get(m.group(2))
            if mes:
                f = _fecha_valida(int(m.group(1)), mes, int(m.group(3)))
                if f:
                    return f
    m = _RE_FECHA_NUM.search(fragmento)
    if m:
        return _fecha_valida(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _anio_dominante(texto_normalizado: str) -> int | None:
    """Año que más veces aparece en el documento: aproxima su horizonte temporal.
    Una convocatoria de 2026 repite "2026" muchas veces. Usamos la MODA (no el
    máximo) porque el máximo se contamina con cifras mal leídas como años
    (presupuestos, códigos) que dan 2064, 2088, etc."""
    anios = [int(y) for y in _RE_ANIO.findall(texto_normalizado)]
    if not anios:
        return None
    return Counter(anios).most_common(1)[0][0]


def extraer_fecha_fin(texto: str) -> date | None:
    """
    Devuelve la fecha de cierre de plazo mas tardia que aparece cerca de una
    senal de cierre ("hasta el", "fin de plazo", "finalizara el"...). Si no hay
    ninguna fecha asociada a un cierre, devuelve None (plazo no determinable:
    p.ej. "tres meses desde la notificacion").
    """
    if not texto:
        return None
    n = _normalizar(texto)

    candidatas: list[date] = []
    for clave in _CLAVES_CIERRE:
        inicio = 0
        while True:
            p = n.find(clave, inicio)
            if p < 0:
                break
            # ventana tras la senal de cierre donde esperamos la fecha
            ventana = n[p:p + 80]
            f = _primera_fecha(ventana)
            if f:
                candidatas.append(f)
            inicio = p + len(clave)

    if not candidatas:
        return None

    # Descarta back-references: una fecha de cierre anterior al horizonte propio
    # del documento (su año dominante) no es su plazo, sino una cita a un marco
    # anterior. Ej.: el "Plan Estatal Vivienda 2026-2030" menciona "hasta el 31
    # de diciembre de 2022" (clausula presupuestaria del plan previo); sin esto
    # el plan salia como "cerrado en 2022", que es absurdo.
    dom = _anio_dominante(n)
    if dom is not None:
        candidatas = [f for f in candidatas if f.year >= dom]
    if not candidatas:
        return None

    # el cierre real es la fecha limite mas tardia entre las asociadas a cierre
    return max(candidatas)


# Señales textuales de que el plazo ya esta cerrado, aunque no haya fecha
# parseable (p.ej. las fichas de tramite del Gobierno de La Rioja lo dicen
# explicitamente: "Plazo: Fuera de plazo de solicitud").
_SENALES_CERRADA = ("fuera de plazo",)


def texto_indica_cerrada(texto: str) -> bool:
    n = _normalizar(texto or "")
    return any(s in n for s in _SENALES_CERRADA)


def estado_desde_fecha(fecha_fin: date | None, hoy: date | None = None) -> str:
    if fecha_fin is None:
        return "desconocida"
    hoy = hoy or date.today()
    return "cerrada" if fecha_fin < hoy else "abierta"


def migrar() -> None:
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE fuentes ADD COLUMN IF NOT EXISTS fecha_fin DATE")
            cur.execute(
                "ALTER TABLE fuentes ADD COLUMN IF NOT EXISTS estado TEXT NOT NULL DEFAULT 'desconocida'"
            )
        conn.commit()
    print("Migracion: columnas fecha_fin y estado aseguradas.")


def backfill() -> dict:
    hoy = date.today()
    reparto = {"abierta": 0, "cerrada": 0, "desconocida": 0}
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, texto_extraido FROM fuentes")
            filas = cur.fetchall()
            for fuente_id, texto in filas:
                fecha_fin = extraer_fecha_fin(texto or "")
                if texto_indica_cerrada(texto):
                    estado = "cerrada"
                    # La senal textual es autoritativa; si la fecha parseada no es
                    # pasada, contradice el "fuera de plazo" y es mejor no mostrarla.
                    if fecha_fin is not None and fecha_fin >= hoy:
                        fecha_fin = None
                else:
                    estado = estado_desde_fecha(fecha_fin, hoy)
                reparto[estado] += 1
                cur.execute(
                    "UPDATE fuentes SET fecha_fin = %s, estado = %s WHERE id = %s",
                    (fecha_fin, estado, fuente_id),
                )
        conn.commit()
    return reparto


def informe() -> None:
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT estado, count(*) FROM fuentes GROUP BY estado ORDER BY 2 DESC")
            print("Reparto por estado:")
            for estado, n in cur.fetchall():
                print(f"  {estado:12s} {n}")
            cur.execute(
                "SELECT nombre, fecha_fin, estado FROM fuentes "
                "WHERE estado='cerrada' ORDER BY fecha_fin DESC LIMIT 12"
            )
            cerradas = cur.fetchall()
            if cerradas:
                print("\nEjemplos de cerradas (no deberian devolverse como vigentes):")
                for nombre, fecha, _ in cerradas:
                    print(f"  [{fecha}] {nombre[:60]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Marca vigencia de convocatorias.")
    parser.add_argument("--informe", action="store_true", help="Solo muestra el reparto actual.")
    args = parser.parse_args()

    if args.informe:
        informe()
        return

    migrar()
    reparto = backfill()
    print(f"Backfill: {reparto}")
    print()
    informe()


if __name__ == "__main__":
    main()
