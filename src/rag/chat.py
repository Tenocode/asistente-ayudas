import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import ollama

from rag.buscar import buscar_filtrado


def limpiar_texto(texto: str) -> str:
    texto = re.sub(r"[^\x20-\x7E\xA0-\xFF\n]", " ", texto)
    texto = re.sub(r" {3,}", "  ", texto)
    return texto.strip()

MODELO = "llama3.1:8b"
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
    "empleo": "empleo", "trabajo": "empleo", "empresa": "empleo", "emprender": "empleo", "autonomo": "empleo", "autónomo": "empleo",
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
    relevantes = [r for r in resultados if r["distancia"] <= DISTANCIA_MAX]

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

    ayudas: dict[str, dict] = {}
    for r in relevantes:
        nombre = r["nombre"]
        if nombre not in ayudas or r["distancia"] < ayudas[nombre]["distancia"]:
            ayudas[nombre] = r

    top_ayudas = dict(list(ayudas.items())[:3])

    PALABRAS_LEY = ["cotizacion", "cotización", "subsidio por desempleo", "fogasa",
                    "estatuto", "reglamento general", "bases mínimas"]

    fragmentos = []
    for i, (nombre, r) in enumerate(top_ayudas.items(), start=1):
        texto_limpio = limpiar_texto(r["texto"])[:600]
        es_ley = any(p in nombre.lower() for p in PALABRAS_LEY)
        etiqueta = "[LEY/REGLAMENTO - no es una ayuda directa]" if es_ley else "[CONVOCATORIA DE AYUDA]"
        url = r.get("url_oficial") or "sin URL oficial registrada"
        fragmentos.append(f"[{i}] {nombre} {etiqueta}\nFuente: {url}\n{texto_limpio}")
    contexto = "\n\n---\n\n".join(fragmentos)

    aviso_foraneo = (
        f"\nNOTA: No hay datos específicos para {perfil['comunidad_raw']} en esta categoría. "
        "Los resultados son de otras comunidades — pueden servir de referencia.\n"
        if hay_resultados_foraneos else ""
    )

    prompt = f"""Ciudadano en {perfil['comunidad_raw']} busca: "{perfil['descripcion']}"
{aviso_foraneo}
Aquí tienes {len(top_ayudas)} convocatoria(s) encontrada(s):

{contexto}

Para cada convocatoria marcada [CONVOCATORIA DE AYUDA], explica: para quién es, qué cubre, importe y plazo si aparecen.
Para las marcadas [LEY/REGLAMENTO], escribe solo "no aplicable".

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
            options={"temperature": 0},
        )
        return prefijo + respuesta.message.content
    except Exception:
        nombres = "\n".join(
            f"- {n} ({r.get('url_oficial') or 'sin URL oficial registrada'})"
            for n, r in top_ayudas.items()
        )
        return (
            prefijo
            + f"He encontrado estas convocatorias que podrían interesarte:\n{nombres}\n\n"
            "Consulta cada convocatoria directamente para obtener los detalles.\n\n"
            "Información orientativa. Consulta la convocatoria oficial antes de solicitar."
        )


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
            k=8,
        )

        if not resultados and perfil["categoria"] != "todas":
            print("(Sin resultados en tu comunidad — mostrando ayudas de la misma categoría en otras comunidades...)\n")
            resultados = buscar_filtrado(
                pregunta=perfil["descripcion"],
                comunidad="todas",
                categoria=perfil["categoria"],
                k=8,
            )

        if not resultados and perfil["comunidad"] != "todas":
            print("(Ampliando a todas las categorías de tu comunidad...)\n")
            resultados = buscar_filtrado(
                pregunta=perfil["descripcion"],
                comunidad=perfil["comunidad"],
                categoria="todas",
                k=8,
            )

        if not resultados:
            print("(Búsqueda general sin filtros...)\n")
            resultados = buscar_filtrado(
                pregunta=perfil["descripcion"],
                comunidad="todas",
                categoria="todas",
                k=8,
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
