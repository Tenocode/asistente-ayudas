import ollama

from buscar import buscar_filtrado

MODELO = "llama3.1:8b"

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

SISTEMA_RESPUESTA = """Eres un asistente especializado en ayudas y subvenciones públicas en España.
Responde SIEMPRE en español, de forma clara y directa.
Usa EXCLUSIVAMENTE la información de los fragmentos que se te proporcionan.
Para cada ayuda relevante menciona: nombre, a quién va dirigida, requisitos principales y cómo solicitarla si aparece.
Cita siempre el nombre de la convocatoria entre paréntesis.
Si no hay información suficiente en los fragmentos, dilo claramente.
Termina con: "⚠️ Información orientativa. Consulta la convocatoria oficial antes de solicitar."
"""


def normalizar(texto: str, tabla: dict) -> str | None:
    texto = texto.lower().strip()
    for clave, valor in tabla.items():
        if clave in texto:
            return valor
    return None


def recoger_perfil() -> dict:
    print("\n--- Cuéntame un poco sobre ti ---\n")

    # Comunidad
    while True:
        comunidad_raw = input("¿En qué comunidad autónoma vives? > ").strip()
        comunidad = normalizar(comunidad_raw, COMUNIDADES)
        if comunidad:
            break
        print("No he reconocido esa comunidad. Prueba con: La Rioja, Murcia, Extremadura, Madrid, todas...")

    # Tipo de ayuda
    while True:
        tipo_raw = input("¿Qué tipo de ayuda buscas? (vivienda, carnet, empleo, formación, movilidad, cultura...) > ").strip()
        categoria = normalizar(tipo_raw, CATEGORIAS)
        if categoria:
            break
        print("No he reconocido ese tipo. Prueba con: vivienda, carnet de conducir, trabajo, becas, extranjero...")

    # Descripción libre
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
    if not resultados:
        return "No he encontrado ayudas relevantes para tu perfil en las convocatorias disponibles."

    fragmentos = []
    for r in resultados:
        fragmentos.append(
            f"[{r['nombre']} | ámbito: {r['ambito']} | categoría: {r['categoria']}]\n{r['texto']}"
        )
    contexto = "\n\n---\n\n".join(fragmentos)

    prompt = f"""El usuario vive en {perfil['comunidad_raw']} y busca: {perfil['descripcion']}

Fragmentos de convocatorias oficiales encontradas:

{contexto}

Responde basándote ÚNICAMENTE en los fragmentos anteriores."""

    respuesta = ollama.chat(
        model=MODELO,
        messages=[
            {"role": "system", "content": SISTEMA_RESPUESTA},
            {"role": "user", "content": prompt},
        ],
    )
    return respuesta.message.content


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
            k=5,
        )

        # Fallback 1: misma categoría en cualquier comunidad
        if not resultados and perfil["categoria"] != "todas":
            print("(Sin resultados en tu comunidad — mostrando ayudas de la misma categoría en otras comunidades...)\n")
            resultados = buscar_filtrado(
                pregunta=perfil["descripcion"],
                comunidad="todas",
                categoria=perfil["categoria"],
                k=5,
            )

        # Fallback 2: misma comunidad sin filtro de categoría
        if not resultados and perfil["comunidad"] != "todas":
            print("(Ampliando a todas las categorías de tu comunidad...)\n")
            resultados = buscar_filtrado(
                pregunta=perfil["descripcion"],
                comunidad=perfil["comunidad"],
                categoria="todas",
                k=5,
            )

        # Fallback 3: búsqueda libre sin filtros
        if not resultados:
            print("(Búsqueda general sin filtros...)\n")
            resultados = buscar_filtrado(
                pregunta=perfil["descripcion"],
                comunidad="todas",
                categoria="todas",
                k=5,
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
