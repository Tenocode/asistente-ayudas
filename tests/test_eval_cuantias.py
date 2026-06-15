"""
Tests deterministas del matcher de cuantias del evaluador (sin red ni LLM).

Congela el comportamiento del gate de cuantias robusto: debe casar el mismo
importe escrito de formas distintas (70 euros == 70 €/m²) SIN colar falsos
positivos (70 euros != 1.970, != 70%). Incluye casos negativos a proposito:
un gate que da falsos verdes es peor que no tener gate.

Uso:
    python tests/test_eval_cuantias.py   -> PASS/FAIL, exit !=0 si algo falla
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from evaluar_rag import importe_satisface, _canon_importes

fallos: list[str] = []


def ok(nombre: str, cond: bool) -> None:
    if cond:
        print(f"  [PASS] {nombre}")
    else:
        print(f"  [FAIL] {nombre}")
        fallos.append(nombre)


def satisface(esperado: str, respuesta: str) -> bool:
    return importe_satisface(esperado, _canon_importes(respuesta))


print("Fraseo equivalente (deben CASAR)")
ok("70 euros ~ '70 €/m²'", satisface("70 euros", "el precio sera de 70 €/m²"))
ok("70 euros ~ '70 € por metro'", satisface("70 euros", "70 € por metro cuadrado"))
ok("70 euros ~ '70 euros/m2'", satisface("70 euros", "70 euros/m2"))
ok("2.700 ~ '2.700 euros'", satisface("2.700", "una cuantia fija de 2.700 euros"))
ok("2.700 ~ '2700€'", satisface("2.700", "son 2700€ al ano"))
ok("250 euros ~ '250 euros mensuales'", satisface("250 euros", "ayuda de 250 euros mensuales"))
ok("25% ~ '25 %'", satisface("25%", "el 25 % del gasto"))
ok("1.500.000 euros ~ '1.500.000,00 euros'", satisface("1.500.000 euros", "maximo 1.500.000,00 euros"))

print("\nFalsos positivos (NO deben casar)")
ok("70 euros !~ '1.970'", not satisface("70 euros", "habia 1.970 solicitudes"))
ok("70 euros !~ '70%'", not satisface("70 euros", "intensidad del 70%"))
ok("2.700 !~ '27.000 euros'", not satisface("2.700", "presupuesto de 27.000 euros"))
ok("25% !~ '25 euros'", not satisface("25%", "25 euros por persona"))
ok("250 euros !~ 'sin cifra'", not satisface("250 euros", "No aparece en la fuente proporcionada"))

print("\nGrupos OR (basta una alternativa)")
orx = "70 euros|1.500.000 euros"
ok("OR pasa con el rango", satisface(orx, "entre 20.000 y 1.500.000 euros"))
ok("OR pasa con el precio/m2", satisface(orx, "70 €/m²"))
ok("OR falla si no hay ninguna", not satisface(orx, "intensidad del 35%"))

print("\nUnidad comodin (esperado sin unidad casa cualquier unidad)")
ok("2.700 (sin unidad) ~ '2.700 euros'", satisface("2.700", "2.700 euros"))
ok("2.700 (sin unidad) ~ '2.700' suelto", satisface("2.700", "fija de 2.700 al mes"))

print()
if fallos:
    print(f"RESULTADO: ROJO — {len(fallos)} test(s) fallan: {fallos}")
    sys.exit(1)
print("RESULTADO: VERDE — el matcher de cuantias es robusto y sin falsos verdes")
