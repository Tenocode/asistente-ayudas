import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ingesta.pipeline import extraer_candidatos, leer_candidatos
from ingesta.indexar_fuente import indexar_fuente

RUTA_CANDIDATOS = Path(__file__).parent.parent / "data" / "candidatos.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrae texto de fuentes oficiales candidatas e indexa opcionalmente."
    )
    parser.add_argument(
        "--candidatos",
        type=Path,
        default=RUTA_CANDIDATOS,
        help="Ruta al archivo JSONL de candidatos.",
    )
    parser.add_argument(
        "--indexar",
        action="store_true",
        help="Insertar en Postgres tras extraer. Sin este flag solo muestra el texto.",
    )
    args = parser.parse_args()

    if not args.candidatos.exists():
        print(f"No existe el archivo de candidatos: {args.candidatos}")
        print("Crea data/candidatos.jsonl o copia data/candidatos.example.jsonl.")
        return

    candidatos = leer_candidatos(args.candidatos)
    if not candidatos:
        print(f"No hay candidatos en {args.candidatos}")
        return

    print(f"Extrayendo {len(candidatos)} fuente(s)...\n")
    fuentes = extraer_candidatos(candidatos)

    indexadas = ya_existian = errores = 0

    for fuente in fuentes:
        palabras = len(fuente.texto_extraido.split())
        print(f"[OK] {fuente.nombre}")
        print(f"     tipo={fuente.tipo_fuente}  ambito={fuente.ambito}  categoria={fuente.categoria}")
        print(f"     url={fuente.url_oficial}")
        print(f"     texto extraido: {palabras} palabras")

        if args.indexar:
            try:
                resultado = indexar_fuente(fuente)
                if resultado == "ya_existia":
                    print("     [SKIP] Ya estaba en la base de datos.")
                    ya_existian += 1
                else:
                    print("     [INDEXADA]")
                    indexadas += 1
            except Exception as e:
                print(f"     [ERROR] {e}")
                errores += 1
        print()

    if args.indexar:
        print(f"Resumen: {indexadas} indexadas, {ya_existian} ya existian, {errores} errores.")


if __name__ == "__main__":
    main()
