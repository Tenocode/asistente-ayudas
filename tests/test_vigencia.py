"""
Tests deterministas del detector de vigencia (sin red ni base).

Congela el arreglo de la back-reference: una convocatoria cuyo año dominante es
2026 que menciona "hasta el 31 de diciembre de 2022" (cláusula presupuestaria de
un marco anterior) NO debe salir como cerrada en 2022. A la vez, los plazos
reales (pasados o futuros) sí deben extraerse.

Uso:
    python tests/test_vigencia.py   -> PASS/FAIL, exit !=0 si algo falla
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from db.vigencia import (
    _anio_dominante,
    estado_desde_fecha,
    extraer_fecha_fin,
    texto_indica_cerrada,
)
from db.vigencia import _normalizar

fallos: list[str] = []


def ok(nombre: str, cond: bool) -> None:
    if cond:
        print(f"  [PASS] {nombre}")
    else:
        print(f"  [FAIL] {nombre}")
        fallos.append(nombre)


# --- El bug real: plan 2026-2030 con back-reference a 2022 ---
PLAN_2026 = (
    "Plan Estatal de Vivienda 2026-2030. Para el ejercicio 2026 se aprueban las "
    "ayudas. La concesion sera hasta el 31 de diciembre de 2022 siempre que la "
    "concesion se realice con cargo al presupuesto. Vigencia del plan: ejercicios "
    "2026, 2027, 2028, 2029 y 2030. Convocatoria 2026."
)

print("Back-reference (NO debe cerrarse por la fecha vieja)")
ok("plan 2026 con 'hasta el ... 2022' -> sin fecha de cierre",
   extraer_fecha_fin(PLAN_2026) is None)
ok("año dominante del plan es 2026", _anio_dominante(_normalizar(PLAN_2026)) == 2026)

# --- Plazos reales que SI deben extraerse ---
CIERRE_PASADO = (
    "Convocatoria de becas 2025. El plazo de presentacion de solicitudes finaliza "
    "el 30 de septiembre de 2025. Ejercicio 2025. Bases 2025."
)
CIERRE_FUTURO = (
    "Ayudas 2026. La solicitud esta abierto hasta el 1 de septiembre de 2026. "
    "Ejercicio 2026, 2026."
)

print("\nPlazos reales (SI deben extraerse)")
ok("cierre pasado 30/09/2025", extraer_fecha_fin(CIERRE_PASADO) == date(2025, 9, 30))
ok("cierre futuro 01/09/2026", extraer_fecha_fin(CIERRE_FUTURO) == date(2026, 9, 1))

# --- Sin señal de cierre -> no determinable ---
SIN_PLAZO = "La ayuda se concede en un plazo de tres meses desde la notificacion. Ejercicio 2026."
print("\nSin fecha asociada a cierre")
ok("sin clave de cierre -> None", extraer_fecha_fin(SIN_PLAZO) is None)

# --- Año dominante resistente a años-basura (cifras mal leidas) ---
print("\nAño dominante (moda, no maximo)")
ok("ignora un '2088' suelto frente a varios 2026",
   _anio_dominante(_normalizar("ejercicio 2026, 2026, 2026 y un codigo 2088 al pie")) == 2026)
ok("sin años -> None", _anio_dominante("sin fechas aqui") is None)

# --- Señal textual de cerrada y estado por fecha ---
print("\nSeñales de estado")
ok("'fuera de plazo' -> cerrada textual", texto_indica_cerrada("Plazo: Fuera de plazo de solicitud"))
ok("fecha pasada -> cerrada", estado_desde_fecha(date(2020, 1, 1), hoy=date(2026, 6, 15)) == "cerrada")
ok("fecha futura -> abierta", estado_desde_fecha(date(2030, 1, 1), hoy=date(2026, 6, 15)) == "abierta")
ok("sin fecha -> desconocida", estado_desde_fecha(None) == "desconocida")

print()
if fallos:
    print(f"RESULTADO: ROJO — {len(fallos)} test(s) fallan: {fallos}")
    sys.exit(1)
print("RESULTADO: VERDE — vigencia robusta (back-reference descartada, plazos reales intactos)")
