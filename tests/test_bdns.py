"""
Tests deterministas del conector BDNS (sin red).

Cubren la lógica pura del barrido region-first: clasificador por categoría,
blacklist de ruido administrativo, filtro inter-administrativo, inferencia de
ámbito y dedup de ediciones anuales. Son rápidos y no tocan la API ni la base.

Uso:
    python tests/test_bdns.py        -> imprime PASS/FAIL y sale !=0 si algo falla

Filosofía igual que evaluar_rag.py: gate ligero, congela el comportamiento para
que un bug ya corregido (p. ej. "carnaval" -> vivienda) no pueda volver en silencio.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ingesta.fuentes import bdns

fallos: list[str] = []


def check(nombre: str, obtenido, esperado) -> None:
    if obtenido == esperado:
        print(f"  [PASS] {nombre}")
    else:
        print(f"  [FAIL] {nombre}: obtenido={obtenido!r} esperado={esperado!r}")
        fallos.append(nombre)


def check_true(nombre: str, cond: bool) -> None:
    check(nombre, bool(cond), True)


# --- clasificar_categoria ---------------------------------------------------
print("clasificar_categoria")
# Regresiones del match por subcadena (deben NO clasificar mal):
check("carnaval no es vivienda", bdns.clasificar_categoria("CONCURSO DE CARNAVAL 2026"), None)
# Lo agrario está fuera de nicho: no debe clasificar (queda en revisión), y nunca como cultura.
check("agricultura/remolacha no clasifica",
      bdns.clasificar_categoria("Consejería de Agricultura: ayuda a la remolacha"), None)
check_true("agricultura nunca cultura",
           bdns.clasificar_categoria("Resolución de Agricultura sobre viñedo") != "cultura")
# Clasificaciones correctas:
check("bono alquiler -> vivienda", bdns.clasificar_categoria("BONO ALQUILER JOVEN 2026"), "vivienda")
check("rehabilitacion -> vivienda",
      bdns.clasificar_categoria("Subvenciones en materia de rehabilitación de edificios"), "vivienda")
check("garantia juvenil -> empleo",
      bdns.clasificar_categoria("Contratación de menores de 30 y beneficiarias SNGJ 2026"), "empleo")
check("libros de texto -> formacion",
      bdns.clasificar_categoria("Ayudas a la adquisición de libros de texto, curso 2025/2026"), "formacion")
check("transporte escolar -> formacion",
      bdns.clasificar_categoria("Ayudas individualizadas de transporte escolar, curso 2025/2026"), "formacion")
check("becas (plural) -> formacion",
      bdns.clasificar_categoria("BECAS DE FORMACIÓN EN ARCHIVOS Y BIBLIOTECA"), "formacion")
check("carne de transporte estudiantes -> movilidad",
      bdns.clasificar_categoria("Subv. por descuentos carné de transporte estudiantes"), "movilidad")
check("bicicletas -> movilidad",
      bdns.clasificar_categoria("Subv. adquisición de bicicletas y ciclos de pedales"), "movilidad")
check("discapacitados (sufijo) -> dependencia",
      bdns.clasificar_categoria("Ayudas para deportistas riojanos discapacitados"), "dependencia")
# Forma real en BDNS: "CONTRAT." abreviado no casa "contratacion" (empleo) -> cae en dependencia por "cuidador".
check("cuidadores (forma real abreviada) -> dependencia",
      bdns.clasificar_categoria("CONV. AYUDAS CONTRAT. CUIDADORES Y EMPLEADOS HOGAR Y REDUCCIÓN JORNADA 2026"), "dependencia")
check("sin termino -> None",
      bdns.clasificar_categoria("Ayuda a la remolacha azucarera"), None)

# --- blacklist de ruido administrativo --------------------------------------
print("_pasa_blacklist_region")
check_true("convenio bloqueado", not bdns._pasa_blacklist_region("Convenio con el Ayuntamiento de Lardero"))
check_true("nominativa bloqueada", not bdns._pasa_blacklist_region("Subvención nominativa a favor de la Fundación X"))
check_true("premio bloqueado", not bdns._pasa_blacklist_region("Premios extraordinarios de Educación"))
check_true("proceso selectivo bloqueado", not bdns._pasa_blacklist_region("Convocatoria del proceso selectivo para la contratación"))
check_true("ayuda real pasa", bdns._pasa_blacklist_region("BONO ALQUILER JOVEN 2026"))

# --- filtro inter-administrativo --------------------------------------------
print("_es_inter_administrativa")
check_true("a municipios -> inter-admin", bdns._es_inter_administrativa("Subvenciones a municipios y EELL para accesibilidad"))
check_true("entidades locales -> inter-admin", bdns._es_inter_administrativa("Ayudas a entidades locales"))
check_true("ayuda a ciudadano no es inter-admin", not bdns._es_inter_administrativa("Ayudas comedor no transportados"))

# --- inferencia de ámbito ---------------------------------------------------
print("_ambito_region")
check("ESTADO -> estatal", bdns._ambito_region({"nivel1": "ESTADO", "nivel2": "", "nivel3": ""}), "estatal")
check("AUTONOMICA La Rioja -> larioja",
      bdns._ambito_region({"nivel1": "AUTONOMICA", "nivel2": "LA RIOJA", "nivel3": "CONSEJERÍA X"}), "larioja")
check("LOCAL Logroño -> larioja",
      bdns._ambito_region({"nivel1": "LOCAL", "nivel2": "LOGROÑO", "nivel3": "AYUNTAMIENTO DE LOGROÑO"}), "larioja")
check("AUTONOMICA Asturias -> desconocido (defensa)",
      bdns._ambito_region({"nivel1": "AUTONOMICA", "nivel2": "PRINCIPADO DE ASTURIAS", "nivel3": ""}), "desconocido")

# --- dedup de ediciones anuales ---------------------------------------------
print("_anio_de / _clave_dedup / _dedup_ediciones")
check("anio_de 2026", bdns._anio_de("BONO ALQUILER JOVEN 2026"), 2026)
check("anio_de sin año", bdns._anio_de("Ayuda a la remolacha"), 0)
check_true("clave_dedup ignora año",
           bdns._clave_dedup("BONO ALQUILER JOVEN 2025") == bdns._clave_dedup("Bono Alquiler Joven 2026"))
check_true("clave_dedup distingue ayudas distintas",
           bdns._clave_dedup("Bono Alquiler Joven") != bdns._clave_dedup("Bono Infantil"))

ediciones = [
    ({"descripcion": "BONO ALQUILER JOVEN 2025", "numeroConvocatoria": "100"}, "larioja", "vivienda"),
    ({"descripcion": "Bono Alquiler Joven 2026", "numeroConvocatoria": "200"}, "larioja", "vivienda"),
    ({"descripcion": "Ayuda comedor no transportados 2026", "numeroConvocatoria": "300"}, "larioja", "formacion"),
]
unicas, colapsadas = bdns._dedup_ediciones(ediciones)
check("dedup colapsa 1", colapsadas, 1)
check("dedup deja 2 unicas", len(unicas), 2)
# se queda con la edición 2026 (año más alto)
bono = [it for it in unicas if "alquiler" in it[0]["descripcion"].lower()][0]
check("dedup conserva la mas reciente", bono[0]["descripcion"], "Bono Alquiler Joven 2026")

# --- resultado --------------------------------------------------------------
print()
if fallos:
    print(f"RESULTADO: ROJO — {len(fallos)} test(s) fallan: {fallos}")
    sys.exit(1)
print("RESULTADO: VERDE — todos los tests del conector BDNS pasan")
