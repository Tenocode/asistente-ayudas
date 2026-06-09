import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

from buscar import buscar_filtrado

casos = [
    ("tengo 23 anos busco empleo", "larioja", "empleo"),
    ("tengo 23 anos quiero sacarme el carnet b", "larioja", "carnet"),
]

for descripcion, comunidad, categoria in casos:
    print(f"\n{'='*60}")
    print(f"QUERY: {descripcion} | {comunidad} | {categoria}")
    print('='*60)
    resultados = buscar_filtrado(descripcion, comunidad=comunidad, categoria=categoria, k=8)
    if not resultados:
        resultados = buscar_filtrado(descripcion, comunidad="todas", categoria=categoria, k=8)
    for i, f in enumerate(resultados, 1):
        print(f"\n[{i}] {f['nombre']} ({f['ambito']}) dist={f['distancia']}")
        print(f['texto'][:500])
        print("---")
