"""
Tests deterministas del extractor de detalles (sin red ni LLM).

Congela el arreglo del "321.340 euros": una cifra de PRESUPUESTO/CREDITO global no
debe llegar al LLM como importe del ciudadano, ni el boilerplate de firma de PDF.
Y, al reves, una cuantia individual real debe sobrevivir al filtro.

Uso:
    python tests/test_extractor.py   -> PASS/FAIL, exit !=0 si algo falla
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rag.chat import extraer_detalles_clave, _scrub_ruido, normalizar_ascii

fallos: list[str] = []


def ok(nombre: str, cond: bool) -> None:
    if cond:
        print(f"  [PASS] {nombre}")
    else:
        print(f"  [FAIL] {nombre}")
        fallos.append(nombre)


# Caso real: orden de ampliacion de credito de la beca complementaria. Su unica
# cifra en euros es el presupuesto (321.340), NO lo que cobra el estudiante.
TEXTO_PRESUPUESTO = """Beneficiarios
del Gobierno de La Rioja de ampliar el numero de beneficiarios y en prevision de un mayor numero de solicitudes. El incremento asciende a 321.340 euros. Tercero. Existencia de credito adecuado y suficiente.
Requisitos
estudiantes matriculados en un centro o universidad espanola fuera del territorio de la Comunidad Autonoma de La Rioja."""

# Caso con cuantia individual real.
TEXTO_IMPORTE_REAL = """Subvencion a percibir
La cuantia de la ayuda sera de 250 euros mensuales, con un limite maximo de 600 euros al mes.
Beneficiarios
jovenes de 18 a 35 anos empadronados en La Rioja con contrato de alquiler."""

# Caso con boilerplate de firma electronica pegado a un bloque util.
TEXTO_FIRMA = """Beneficiarios
Podran ser beneficiarias las personas fisicas mayores de edad empadronadas en La Rioja.
INFORME DE FIRMA, no sustituye al documento original | C.S.V. : GEN-c96d-b4c8-2394-77ad."""


print("Presupuesto NO debe aparecer como dato")
det = extraer_detalles_clave(TEXTO_PRESUPUESTO)
ok("321.340 fuera de los detalles", "321.340" not in det and "321340" not in det)
ok("se conserva contenido util (beneficiarios)", "beneficiari" in normalizar_ascii(det))
ok("no hay linea 'Importe:' inventada", "importe:" not in normalizar_ascii(det))

print("\nCuantia individual real SOBREVIVE")
det2 = extraer_detalles_clave(TEXTO_IMPORTE_REAL)
ok("250 euros presente", "250 euros" in normalizar_ascii(det2))
ok("limite 600 euros presente", "600 euros" in normalizar_ascii(det2))

print("\nBoilerplate de firma fuera")
det3 = extraer_detalles_clave(TEXTO_FIRMA)
ok("'no sustituye' fuera", "no sustituye" not in normalizar_ascii(det3))
ok("C.S.V. fuera", "c.s.v" not in normalizar_ascii(det3))
ok("beneficiarios reales dentro", "beneficiarias" in normalizar_ascii(det3))

print("\n_scrub_ruido a nivel de frase")
s = _scrub_ruido("La ayuda es de 70 euros por metro cuadrado. El presupuesto total es de 6 millones de euros.")
ok("conserva '70 euros'", "70 euros" in s)
ok("quita el presupuesto global", "millones" not in s)

print()
if fallos:
    print(f"RESULTADO: ROJO — {len(fallos)} test(s) fallan: {fallos}")
    sys.exit(1)
print("RESULTADO: VERDE — el extractor filtra presupuesto/firma y conserva cuantias reales")
