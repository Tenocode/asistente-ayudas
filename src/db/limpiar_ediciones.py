"""
Limpieza de ediciones anuales obsoletas en `fuentes`.

Problema: la misma ayuda reconvocada cada año queda indexada varias veces (p. ej.
"Becas Santander Movilidad 2025" y "...2026"). Las ediciones de cursos pasados ya
cerradas son ruido: nunca reabriran *asi* (la edicion vigente es la nueva).

Que hace: agrupa fuentes por ambito + nombre normalizado SIN año (la misma clave que
usa el conector BDNS) y, dentro de cada grupo, BORRA las ediciones que cumplen TODAS:
  - tienen un año identificable en el nombre/fecha,
  - su año es ESTRICTAMENTE MENOR que el año mas reciente del grupo,
  - estan `cerrada`.
Asi conserva siempre la edicion mas reciente (aunque este cerrada: suele reabrir) y
nunca toca ayudas abiertas, desconocidas, ni grupos de una sola edicion. Es conservador.

Uso:
    python src/db/limpiar_ediciones.py            # DRY-RUN: solo informa que borraria
    python src/db/limpiar_ediciones.py --aplicar  # borra de verdad (con backup JSON)

El borrado usa ON DELETE CASCADE (se llevan los fragmentos). Antes de borrar vuelca un
backup a data/_ediciones_borradas.json para auditoria. Tras aplicar, ejecutar el gate.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2

from db.init_db import DSN
from ingesta.fuentes.bdns import _anio_de, _clave_dedup

BACKUP = Path(__file__).parent.parent.parent / "data" / "_ediciones_borradas.json"


def _anio_edicion(nombre: str, fecha_fin) -> int:
    """Año de la edicion: el del nombre y, si no hay, el de fecha_fin."""
    anio = _anio_de(nombre)
    if anio:
        return anio
    return fecha_fin.year if fecha_fin else 0


def cargar_fuentes() -> list[dict]:
    with psycopg2.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, nombre, ambito, categoria, url_oficial, tipo_fuente, "
            "fecha_fin, estado FROM fuentes"
        )
        cols = ["id", "nombre", "ambito", "categoria", "url_oficial",
                "tipo_fuente", "fecha_fin", "estado"]
        return [dict(zip(cols, fila)) for fila in cur.fetchall()]


def calcular_obsoletas(fuentes: list[dict]) -> tuple[list[dict], list[tuple]]:
    """Devuelve (a_borrar, grupos_afectados). Grupo afectado = (clave, miembros)."""
    grupos: dict[tuple, list[dict]] = defaultdict(list)
    for f in fuentes:
        f["_anio"] = _anio_edicion(f["nombre"], f["fecha_fin"])
        grupos[(f["ambito"], _clave_dedup(f["nombre"]))].append(f)

    a_borrar: list[dict] = []
    afectados: list[tuple] = []
    for clave, miembros in grupos.items():
        if len(miembros) < 2:
            continue
        anios = [m["_anio"] for m in miembros if m["_anio"] > 0]
        if len(set(anios)) < 2:
            continue  # no hay varias ediciones por año comparables
        max_anio = max(anios)
        obsoletas = [
            m for m in miembros
            if m["_anio"] > 0 and m["_anio"] < max_anio and m["estado"] == "cerrada"
        ]
        if obsoletas:
            afectados.append((clave, miembros))
            a_borrar.extend(obsoletas)
    return a_borrar, afectados


def informe(a_borrar: list[dict], afectados: list[tuple]) -> None:
    print(f"Grupos con ediciones obsoletas: {len(afectados)}")
    print(f"Fuentes a borrar: {len(a_borrar)}\n")
    for clave, miembros in afectados:
        print(f"  Grupo {clave[0]} :: '{clave[1][:50]}'")
        for m in sorted(miembros, key=lambda x: -x["_anio"]):
            marca = "  BORRAR" if m in a_borrar else "conservar"
            print(f"     [{marca}] año={m['_anio']} {m['estado']:11s} #{m['id']} {m['nombre'][:55]}")
        print()


def aplicar(a_borrar: list[dict]) -> None:
    if not a_borrar:
        print("Nada que borrar.")
        return
    BACKUP.write_text(
        json.dumps(
            [{k: (str(v) if k == "fecha_fin" else v) for k, v in f.items() if k != "_anio"}
             for f in a_borrar],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    ids = [f["id"] for f in a_borrar]
    with psycopg2.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM fuentes WHERE id = ANY(%s)", (ids,))
        conn.commit()
    print(f"Borradas {len(ids)} fuentes (fragmentos via CASCADE). Backup: {BACKUP}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Borra ediciones anuales obsoletas de fuentes.")
    parser.add_argument("--aplicar", action="store_true",
                        help="Borra de verdad. Sin este flag solo informa (dry-run).")
    args = parser.parse_args()

    fuentes = cargar_fuentes()
    a_borrar, afectados = calcular_obsoletas(fuentes)
    informe(a_borrar, afectados)

    if args.aplicar:
        aplicar(a_borrar)
    else:
        print("DRY-RUN. Revisa la lista de arriba y, si procede:")
        print("  python src/db/limpiar_ediciones.py --aplicar")


if __name__ == "__main__":
    main()
