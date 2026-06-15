import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import ollama

from rag.buscar import buscar_filtrado, obtener_textos_fuentes


def limpiar_texto(texto: str) -> str:
    texto = re.sub(r"[^\x20-\x7E\xA0-\xFF\n]", " ", texto)
    texto = re.sub(r" {3,}", "  ", texto)
    return texto.strip()


def normalizar_ascii(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return texto.encode("ascii", "ignore").decode("ascii")

MODELO = "llama3.2:latest"
DISTANCIA_MAX = 0.82

COMUNIDADES = {
    "la rioja": "larioja", "rioja": "larioja", "larioja": "larioja",
    "murcia": "murcia",
    "extremadura": "extremadura",
    "andalucia": "andalucia", "andalucía": "andalucia",
    "madrid": "madrid",
    "cataluña": "cataluna", "cataluna": "cataluna",
    "valencia": "valencia", "comunidad valenciana": "valencia",
    "pais vasco": "paisvasco", "país vasco": "paisvasco",
    "galicia": "galicia",
    "castilla leon": "castillaleon", "castilla y león": "castillaleon",
    "canarias": "canarias",
    "aragon": "aragon", "aragón": "aragon",
    "todas": "todas", "españa": "todas", "estatal": "todas",
}

CATEGORIAS = {
    "formacion": "formacion", "formación": "formacion", "beca": "formacion", "becas": "formacion", "estudios": "formacion",
    "empleo": "empleo", "trabajo": "empleo", "empresa": "empleo", "empresas": "empleo",
    "negocio": "empleo", "negocios": "empleo", "pyme": "empleo", "pymes": "empleo",
    "comercio": "empleo", "emprender": "empleo", "emprendedor": "empleo",
    "emprendedores": "empleo", "autonomo": "empleo", "autónomo": "empleo",
    "vivienda": "vivienda", "alquiler": "vivienda", "piso": "vivienda",
    "carnet": "carnet", "carné": "carnet", "conducir": "carnet", "coche": "carnet",
    "movilidad": "movilidad", "extranjero": "movilidad", "erasmus": "movilidad",
    "cultura": "cultura",
    "dependencia": "dependencia", "discapacidad": "dependencia",
    "todas": "todas",
}

SISTEMA_RESPUESTA = """Eres un asesor de ayudas públicas en España. Responde en español, en tono amable y directo.
Tu único trabajo es explicar al ciudadano las convocatorias que se te proporcionan. Nada más.
No menciones ayudas que no estén en los textos. No inventes datos."""


def normalizar(texto: str, tabla: dict) -> str | None:
    texto = texto.lower().strip()
    for clave, valor in tabla.items():
        if clave in texto:
            return valor
    return None


def _bloques_texto(texto: str) -> list[str]:
    texto = limpiar_texto(texto)
    partes = re.split(r"\n+", texto)
    bloques = []
    for parte in partes:
        parte = parte.strip(" -\t")
        normalizado = normalizar_ascii(parte)
        es_titulo_util = any(
            clave in normalizado
            for clave in (
                "beneficiari", "requisit", "subvencion", "plazo", "solicite",
                "inversiones subvencionables", "importes minimos", "tipo de ayuda",
                "gastos de constitucion", "costes subvencionables",
            )
        )
        if len(parte) >= 25 or es_titulo_util:
            bloques.append(parte)
    return bloques


ENCABEZADOS_SECCION = {
    "beneficiarios",
    "requisitos",
    "documentacion",
    "subvencion a percibir",
    "inversiones subvencionables",
    "importes minimos y maximos subvencionables",
    "tipo de ayuda",
    "costes subvencionables",
    "plazo",
    "solicite esta ayuda",
}


def es_encabezado_seccion(bloque: str) -> bool:
    return normalizar_ascii(bloque).strip(" :") in ENCABEZADOS_SECCION


def construir_ventana(bloques: list[str], indice: int, max_bloques: int = 4) -> str:
    bloque = bloques[indice]
    if not es_encabezado_seccion(bloque):
        salida = [bloque]
        if indice + 1 < len(bloques) and not es_encabezado_seccion(bloques[indice + 1]):
            salida.append(bloques[indice + 1])
        return " ".join(salida)

    salida = [bloque]
    j = indice + 1
    while j < len(bloques) and len(salida) < max_bloques:
        if es_encabezado_seccion(bloques[j]):
            break
        salida.append(bloques[j])
        j += 1
    return " ".join(salida)


_RE_CIFRA = re.compile(r"\d")
_RE_EUROS = re.compile(r"\d[\d.,]*\s*(?:euros|eur|€)")
_RE_PCT = re.compile(r"\d[\d.,]*\s*%")

# Lineas que hablan del presupuesto/credito global de la convocatoria, no de la
# cuantia que recibe el ciudadano. No deben colarse como "Importe".
# OJO: terminos especificos de presupuesto, no genericos como "asciende a" (que
# tambien usan las cuantias individuales: "la ayuda asciende a 2.700 euros").
_PALABRAS_PRESUPUESTO = (
    "importe total", "presupuest", "aplicacion presupuestaria", "credito disponible",
    "millones de euros", "dotacion", "aprobar el gasto", "cargo a la aplicacion",
    "gasto por importe", "credito total", "incremento asciende", "existencia de credito",
    "credito adecuado", "ampliar el credito", "incremento del credito",
    "incrementa el credito", "modificacion de credito",
)

# Restos de la extraccion de PDF que no son contenido: pies de firma electronica,
# codigos seguros de verificacion, sellos de validez. Si caen en un bloque, el LLM
# puede tomarlos como dato. Fuera.
_PALABRAS_BOILERPLATE = (
    "no sustituye al documento original", "c.s.v", "csv :", "csv:",
    "informe de firma", "verificar la integridad", "codigo seguro de verificacion",
    "direccion de validacion", "run.gob.es",
)


def _es_linea_presupuesto(normalizado: str) -> bool:
    return any(p in normalizado for p in _PALABRAS_PRESUPUESTO)


def _es_ruido(normalizado: str) -> bool:
    """Presupuesto global o boilerplate de firma: nunca debe llegar al LLM como dato."""
    return _es_linea_presupuesto(normalizado) or any(b in normalizado for b in _PALABRAS_BOILERPLATE)


def _scrub_ruido(texto: str) -> str:
    """
    Quita de una ventana las FRASES que son presupuesto global o boilerplate de
    firma, conservando el resto. Asi una cuantia real ("250 euros mensuales") se
    mantiene aunque su parrafo mencione tambien el credito total, y un "incremento
    asciende a 321.340 EUROS" (presupuesto) no se cuela como importe del ciudadano.
    """
    piezas = re.split(r"(?<=[.;])\s+|\n+", texto)
    limpias = [p for p in piezas if p.strip() and not _es_ruido(normalizar_ascii(p))]
    return " ".join(limpias).strip()


def _extraer_importe(bloques: list[str], limite: int = 3, max_chars: int = 650) -> list[str]:
    """
    Selecciona los bloques que contienen la cuantia real para el ciudadano.
    A diferencia de la busqueda generica por palabra clave, aqui exigimos una
    cifra (euros o %), descartamos lineas de presupuesto global (que en los PDF
    de BDNS/BOE suelen aparecer antes que la cuantia individual) y priorizamos
    los bloques mas cercanos a terminos de cuantia. Asi dejamos de capturar el
    indice interno del documento o el credito total en vez del importe.

    Exigimos ademas un score minimo: un bloque que solo contiene una cifra
    incidental (un euro suelto en medio de prosa, sin termino de cuantia ni
    "mensual") no entra. Asi evitamos pasar al LLM bloques que no son importes,
    que es justo lo que hacia que un modelo pequeno se inventara un porcentaje
    para rellenar el hueco. Mejor no dar importe que dar uno falso.
    """
    SCORE_MINIMO = 3
    candidatos: list[tuple[int, int, str]] = []
    for idx, bloque in enumerate(bloques):
        n = normalizar_ascii(bloque)
        if not _RE_CIFRA.search(n):
            continue
        if _es_linea_presupuesto(n):
            continue
        tiene_eur = bool(_RE_EUROS.search(n))
        tiene_pct = bool(_RE_PCT.search(n))
        if not (tiene_eur or tiene_pct):
            continue
        score = (2 if tiene_eur else 0) + (2 if tiene_pct else 0)
        if any(
            k in n
            for k in (
                "cuantia", "subvencion a percibir", "intensidad", "ayuda de",
                "percibir", "importe minimo", "importe maximo", "importes minimos",
                "subvencion de", "minimo", "maximo", "bono", "subvencionara",
                "precio maximo", "hasta el",
            )
        ):
            score += 2
        if "mensual" in n:
            score += 1
        if score < SCORE_MINIMO:
            continue
        candidatos.append((score, idx, bloque))

    if not candidatos:
        return []

    candidatos.sort(key=lambda c: (-c[0], c[1]))
    elegidos: list[str] = []
    vistos: set[str] = set()
    for _, _, bloque in candidatos:
        ventana = limpiar_texto(bloque)
        clave = normalizar_ascii(ventana[:120])
        if clave in vistos:
            continue
        if len(ventana) > max_chars:
            ventana = ventana[:max_chars].rsplit(" ", 1)[0]
        elegidos.append(ventana)
        vistos.add(clave)
        if len(elegidos) >= limite:
            break
    return elegidos


def extraer_detalles_clave(texto_fuente: str, max_chars: int = 1900) -> str:
    """
    Extrae ventanas del texto completo que suelen contener los datos que el
    ciudadano necesita: beneficiarios, requisitos, importe/subvencion y plazo.
    """
    bloques = _bloques_texto(texto_fuente)
    if not bloques:
        return limpiar_texto(texto_fuente)[:max_chars]

    grupos = [
        ("Beneficiarios", ["beneficiari", "destinatari", "personas que pueden"]),
        ("Requisitos", ["requisit", "deberan", "debera"]),
        ("Importe", None),  # se resuelve con _extraer_importe (requiere cifra real)
        ("Cubre", ["inversiones subvencionables", "gastos subvencionables", "seran subvencionables", "programa de inversion", "gastos de constitucion", "costes subvencionables"]),
        ("Plazo", ["plazo", "solicitudes finalizar", "presentacion de solicitudes"]),
        ("Solicitud", ["solicite esta ayuda", "sede electronica", "como solicitar"]),
    ]

    seleccionados: list[str] = []
    vistos: set[str] = set()
    for nombre_grupo, claves in grupos:
        if nombre_grupo == "Importe":
            for ventana in _extraer_importe(bloques):
                ventana = _scrub_ruido(ventana)
                if not ventana:
                    continue
                clave_vista = normalizar_ascii(ventana[:180])
                if clave_vista in vistos:
                    continue
                seleccionados.append(f"Importe: {ventana}")
                vistos.add(clave_vista)
            continue
        max_por_grupo = 300
        encontrado = False
        for clave in claves:
            for i, bloque in enumerate(bloques):
                normalizado = normalizar_ascii(bloque)
                if clave not in normalizado:
                    continue
                if (
                    es_encabezado_seccion(bloque)
                    and i + 1 < len(bloques)
                    and es_encabezado_seccion(bloques[i + 1])
                ):
                    continue
                max_bloques_ventana = 2 if nombre_grupo in {"Plazo", "Solicitud"} else 4
                ventana = construir_ventana(bloques, i, max_bloques=max_bloques_ventana)
                # Quita frases de presupuesto/firma: no son datos del ciudadano y
                # son justo lo que hacia que el LLM citara el credito global como importe.
                ventana = _scrub_ruido(limpiar_texto(ventana))
                if len(ventana) < 15:
                    continue
                clave_vista = normalizar_ascii(ventana[:180])
                if clave_vista in vistos:
                    continue
                if len(ventana) > max_por_grupo:
                    ventana = ventana[:max_por_grupo].rsplit(" ", 1)[0]
                seleccionados.append(f"{nombre_grupo}: {ventana}")
                vistos.add(clave_vista)
                encontrado = True
                break
            if encontrado:
                break

    if not seleccionados:
        return limpiar_texto(texto_fuente)[:max_chars]

    salida: list[str] = []
    usados = 0
    for bloque in seleccionados:
        if usados + len(bloque) > max_chars:
            disponible = max_chars - usados
            if disponible > 250:
                salida.append(bloque[:disponible].rsplit(" ", 1)[0])
            break
        salida.append(bloque)
        usados += len(bloque) + 2

    return "\n".join(salida)


def puntuar_resultado(resultado: dict, descripcion: str) -> float:
    """
    Ajuste ligero sobre la distancia vectorial: si la consulta contiene un
    termino concreto y aparece en nombre/texto, sube esa ayuda en el ranking.
    """
    puntuacion = float(resultado["distancia"])
    consulta = normalizar_ascii(descripcion)
    nombre = normalizar_ascii(resultado.get("nombre", ""))
    texto = normalizar_ascii(resultado.get("texto", "")[:1200])
    contenido = f"{nombre} {texto}"

    terminos = [
        "autonom", "pyme", "pymes", "comercio", "emprend", "maquinaria",
        "digitalizacion", "vehicul", "alquiler", "vivienda", "carnet",
        "conducir", "beca", "formacion", "discapacidad", "dependencia",
    ]
    for termino in terminos:
        if termino in consulta and termino in contenido:
            puntuacion -= 0.08
            if termino in nombre:
                puntuacion -= 0.06

    # Intencion de inversion (comprar maquinaria, invertir, equipamiento): los
    # programas de ADER cuyo nombre es "Inversiones por..." (INP pyme, MIN
    # autonomos/empresas) son la respuesta directa, aunque el embedding los hunda
    # por el boilerplate de cabecera comun a todas las fichas.
    intencion_inversion = any(
        t in consulta for t in ("maquinaria", "invertir", "inversion", "inversiones", "equipamiento")
    )
    if intencion_inversion and "inversion" in nombre:
        puntuacion -= 0.18

    # Desajuste de tamano: si el ciudadano se identifica como pyme o autonomo,
    # una ayuda cuyo nombre es explicitamente para gran empresa encaja peor.
    pide_pequeno = any(t in consulta for t in ("pyme", "autonom"))
    if pide_pequeno and ("gran empresa" in nombre or "grandes empresas" in nombre):
        puntuacion += 0.12

    # Vigencia: una convocatoria con plazo cerrado se degrada de forma MODERADA,
    # nunca se descarta (suele ser anual y reabrir; ademas el parser de fechas
    # puede fallar y no queremos ocultar una ayuda valida por un falso positivo).
    # 'desconocida' no se penaliza: no sabemos la fecha, seria injusto castigarla.
    if resultado.get("estado") == "cerrada":
        puntuacion += 0.10

    if resultado.get("tipo_fuente") == "html":
        puntuacion -= 0.02
    return puntuacion


def clave_conceptual_ayuda(resultado: dict) -> str:
    """
    Agrupa la misma ayuda cuando aparece por varias fuentes oficiales
    (por ejemplo ficha HTML de ADER + PDF de convocatoria en BDNS/ADER).
    """
    nombre = normalizar_ascii(resultado.get("nombre", ""))
    url = normalizar_ascii(resultado.get("url_oficial", ""))
    combinado = f"{nombre} {url}"

    if "consolidacion" in combinado and "trabajo autonom" in combinado:
        return "consolidacion-trabajo-autonomo"
    if "ppa" in combinado or "primeros activos" in combinado:
        return "ppa-primeros-activos"
    if "coc" in combinado or "competitividad del comercio minorista" in combinado:
        return "coc-comercio-minorista"
    if "min-invierte-autonomos" in combinado or "inversiones por autonomos y empresas" in combinado:
        return "min-invierte-autonomos-empresas"

    base = re.sub(r"\b(ayudas?|subvenciones?|convocatoria|la rioja|20\d{2})\b", " ", nombre)
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or (resultado.get("url_oficial") or resultado["nombre"])


def elegir_mejor_resultado(actual: dict, nuevo: dict, descripcion: str) -> dict:
    """
    Si dos resultados representan la misma ayuda, preferimos la ficha HTML
    legible frente al PDF, y despues el mejor score.
    """
    if actual.get("tipo_fuente") != "html" and nuevo.get("tipo_fuente") == "html":
        return nuevo
    if actual.get("tipo_fuente") == "html" and nuevo.get("tipo_fuente") != "html":
        return actual
    if puntuar_resultado(nuevo, descripcion) < puntuar_resultado(actual, descripcion):
        return nuevo
    return actual


def cierre_unico(respuesta: str) -> str:
    cierre = "Información orientativa. Consulta la convocatoria oficial antes de solicitar."
    respuesta = respuesta.replace(f"**{cierre}**", cierre)
    partes = respuesta.split(cierre)
    cuerpo = "".join(partes).strip()
    cuerpo = re.sub(r"\n{3,}", "\n\n", cuerpo)
    return f"{cuerpo}\n\n{cierre}"


def _fecha_es(fecha) -> str:
    """Formatea una fecha (date o str ISO) como DD/MM/YYYY; vacio si no hay."""
    if not fecha:
        return ""
    try:
        return fecha.strftime("%d/%m/%Y")
    except AttributeError:
        partes = str(fecha).split("-")
        return "/".join(reversed(partes)) if len(partes) == 3 else str(fecha)


def avisos_vigencia(ayudas: list[dict]) -> list[str]:
    """
    Aviso DETERMINISTA para convocatorias con plazo cerrado. No depende del LLM:
    se genera leyendo estado/fecha_fin de la BD para garantizar que el ciudadano
    siempre ve la advertencia, diga lo que diga el modelo.
    """
    avisos = []
    for a in ayudas:
        if a.get("estado") == "cerrada":
            fecha = _fecha_es(a.get("fecha_fin"))
            cuando = f"el {fecha}" if fecha else "(fecha no determinada)"
            avisos.append(
                f"- {a['nombre']}: plazo cerrado {cuando}. "
                "Suele ser anual; comprueba si hay una nueva convocatoria abierta."
            )
    return avisos


def aplicar_avisos(contenido: str, top_ayudas: list[dict]) -> str:
    avisos = avisos_vigencia(top_ayudas)
    if not avisos:
        return contenido
    bloque = "Avisos de plazo:\n" + "\n".join(avisos)
    return f"{contenido}\n\n{bloque}"


def resultados_relevantes(resultados: list[dict]) -> list[dict]:
    return [r for r in resultados if r["distancia"] <= DISTANCIA_MAX]


def seleccionar_top_ayudas(
    perfil: dict,
    resultados: list[dict],
    limite: int = 3,
) -> list[dict]:
    relevantes = sorted(
        resultados_relevantes(resultados),
        key=lambda r: puntuar_resultado(r, perfil.get("descripcion", "")),
    )

    ayudas: dict[str, dict] = {}
    descripcion = perfil.get("descripcion", "")
    for r in relevantes:
        clave = clave_conceptual_ayuda(r)
        if clave not in ayudas:
            ayudas[clave] = r
        else:
            ayudas[clave] = elegir_mejor_resultado(ayudas[clave], r, descripcion)

    return list(ayudas.values())[:limite]


def recoger_perfil() -> dict:
    print("\n--- Cuéntame un poco sobre ti ---\n")

    while True:
        comunidad_raw = input("¿En qué comunidad autónoma vives? > ").strip()
        comunidad = normalizar(comunidad_raw, COMUNIDADES)
        if comunidad:
            break
        print("No he reconocido esa comunidad. Prueba con: La Rioja, Murcia, Extremadura, Madrid, todas...")

    while True:
        tipo_raw = input("¿Qué tipo de ayuda buscas? (vivienda, carnet, empleo, formación, movilidad, cultura...) > ").strip()
        categoria = normalizar(tipo_raw, CATEGORIAS)
        if categoria:
            break
        print("No he reconocido ese tipo. Prueba con: vivienda, carnet de conducir, trabajo, becas, extranjero...")

    descripcion = input("Cuéntame más sobre lo que necesitas (puedes ser breve): > ").strip()
    if not descripcion:
        descripcion = tipo_raw

    return {
        "comunidad": comunidad,
        "categoria": categoria,
        "descripcion": descripcion,
        "comunidad_raw": comunidad_raw,
    }


def generar_respuesta(perfil: dict, resultados: list[dict]) -> str:
    relevantes = resultados_relevantes(resultados)

    if not relevantes:
        return (
            "No he encontrado convocatorias de ayudas específicas para tu perfil en los documentos disponibles.\n\n"
            "Te recomiendo consultar directamente el portal de subvenciones de tu comunidad autónoma."
        )

    comunidad_solicitada = perfil.get("comunidad", "todas")
    hay_resultados_foraneos = (
        comunidad_solicitada != "todas"
        and all(
            r["ambito"] != comunidad_solicitada and r["ambito"] != "estatal"
            for r in relevantes
        )
    )

    top_ayudas = seleccionar_top_ayudas(perfil, resultados, limite=3)
    textos_fuentes = obtener_textos_fuentes(
        [r["fuente_id"] for r in top_ayudas if r.get("fuente_id")]
    )

    PALABRAS_LEY = ["cotizacion", "cotización", "subsidio por desempleo", "fogasa",
                    "estatuto", "reglamento general", "bases mínimas"]

    fragmentos = []
    for i, r in enumerate(top_ayudas, start=1):
        nombre = r["nombre"]
        texto_fuente = textos_fuentes.get(r.get("fuente_id")) or r["texto"]
        detalles = extraer_detalles_clave(texto_fuente)
        fragmento_semantico = limpiar_texto(r["texto"])[:260]
        es_ley = any(p in nombre.lower() for p in PALABRAS_LEY)
        etiqueta = "[LEY/REGLAMENTO - no es una ayuda directa]" if es_ley else "[CONVOCATORIA DE AYUDA]"
        if r.get("estado") == "cerrada":
            etiqueta += f" [PLAZO CERRADO el {_fecha_es(r.get('fecha_fin')) or 'fecha no determinada'}]"
        url = r.get("url_oficial") or "sin URL oficial registrada"
        fragmentos.append(
            f"[{i}] {nombre} {etiqueta}\n"
            f"Fuente: {url}\n"
            f"Fragmento semantico encontrado:\n{fragmento_semantico}\n\n"
            f"Datos clave extraidos de la fuente completa:\n{detalles}"
        )
    contexto = "\n\n---\n\n".join(fragmentos)
    hay_leyes = any("[LEY/REGLAMENTO" in fragmento for fragmento in fragmentos)

    aviso_foraneo = (
        f"\nNOTA: No hay datos específicos para {perfil['comunidad_raw']} en esta categoría. "
        "Los resultados son de otras comunidades — pueden servir de referencia.\n"
        if hay_resultados_foraneos else ""
    )

    instruccion_leyes = (
        'Para las marcadas [LEY/REGLAMENTO], escribe solo "no aplicable".'
        if hay_leyes else
        "No añadas apartados de leyes o reglamentos si no aparecen marcados en el contexto."
    )

    hay_cerradas = any(r.get("estado") == "cerrada" for r in top_ayudas)
    instruccion_cerradas = (
        '- Para las marcadas [PLAZO CERRADO el ...], en el campo Plazo escribe '
        '"Cerrado el <fecha>" (no escribas "abierto").\n'
        if hay_cerradas else ""
    )

    prompt = f"""Ciudadano en {perfil['comunidad_raw']} busca: "{perfil['descripcion']}"
{aviso_foraneo}
Aquí tienes {len(top_ayudas)} convocatoria(s) encontrada(s):

{contexto}

Para cada convocatoria marcada [CONVOCATORIA DE AYUDA], explica: para quién es, qué cubre, importe y plazo si aparecen.
Reglas:
- Copia literalmente importes, fechas, porcentajes y rangos de edad cuando aparezcan.
- No reformules "igual o anterior", "igual o posterior", "entre X e Y" ni condiciones parecidas.
- Si un dato no aparece claramente, escribe "No aparece en la fuente proporcionada".
- NUNCA inventes, estimes ni redondees un importe o porcentaje. Si en los datos de una
  convocatoria no hay ninguna cifra de importe, en su campo Importe escribe exactamente
  "No aparece en la fuente proporcionada". Es preferible no dar importe que dar uno falso.
{instruccion_cerradas}- {instruccion_leyes}

Termina con: "Información orientativa. Consulta la convocatoria oficial antes de solicitar."
"""

    prefijo = (
        f"No tengo datos de {perfil['comunidad_raw']} para esta categoría, "
        "pero en otras comunidades existen estas ayudas similares:\n\n"
        if hay_resultados_foraneos else ""
    )

    try:
        respuesta = ollama.chat(
            model=MODELO,
            messages=[
                {"role": "system", "content": SISTEMA_RESPUESTA},
                {"role": "user", "content": prompt},
            ],
            # temperature 0 = deterministico (no inventar cifras).
            # num_predict acota la respuesta y evita generaciones desbocadas
            # (vistas de >10 min en CPU); num_ctx fija la ventana de contexto.
            options={"temperature": 0, "num_predict": 1024, "num_ctx": 4096},
        )
        contenido = aplicar_avisos(respuesta.message.content, top_ayudas)
        return prefijo + cierre_unico(contenido)
    except Exception:
        nombres = "\n".join(
            f"- {r['nombre']} ({r.get('url_oficial') or 'sin URL oficial registrada'})"
            for r in top_ayudas
        )
        cuerpo = (
            prefijo
            + f"He encontrado estas convocatorias que podrían interesarte:\n{nombres}\n\n"
            "Consulta cada convocatoria directamente para obtener los detalles."
        )
        cuerpo = aplicar_avisos(cuerpo, top_ayudas)
        return cuerpo + "\n\nInformación orientativa. Consulta la convocatoria oficial antes de solicitar."


def chat() -> None:
    print("=" * 60)
    print("  Asistente de Ayudas Públicas")
    print("=" * 60)

    while True:
        perfil = recoger_perfil()

        print("\nBuscando ayudas para tu perfil...\n")
        resultados = buscar_filtrado(
            pregunta=perfil["descripcion"],
            comunidad=perfil["comunidad"],
            categoria=perfil["categoria"],
            k=30,
        )

        if not resultados and perfil["categoria"] != "todas":
            print("(Sin resultados en tu comunidad — mostrando ayudas de la misma categoría en otras comunidades...)\n")
            resultados = buscar_filtrado(
                pregunta=perfil["descripcion"],
                comunidad="todas",
                categoria=perfil["categoria"],
                k=30,
            )

        if not resultados and perfil["comunidad"] != "todas":
            print("(Ampliando a todas las categorías de tu comunidad...)\n")
            resultados = buscar_filtrado(
                pregunta=perfil["descripcion"],
                comunidad=perfil["comunidad"],
                categoria="todas",
                k=30,
            )

        if not resultados:
            print("(Búsqueda general sin filtros...)\n")
            resultados = buscar_filtrado(
                pregunta=perfil["descripcion"],
                comunidad="todas",
                categoria="todas",
                k=30,
            )

        print("=" * 60)
        respuesta = generar_respuesta(perfil, resultados)
        print(f"\n{respuesta}\n")
        print("=" * 60)

        continuar = input("\n¿Quieres buscar otro tipo de ayuda? (s/n) > ").strip().lower()
        if continuar != "s":
            print("\n¡Hasta luego!")
            break
        print()


if __name__ == "__main__":
    chat()
