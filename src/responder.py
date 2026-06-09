import ollama

from buscar import buscar

MODELO = "llama3.1:8b"
TOP_K = 5

SISTEMA = """Eres un asistente especializado en ayudas y subvenciones públicas en España.
Responde SIEMPRE en español, de forma clara y directa.

REGLAS ABSOLUTAS:
1. Usa EXCLUSIVAMENTE la información de los fragmentos oficiales que se te proporcionan.
2. NUNCA uses tu conocimiento propio ni inventes datos.
3. Si encuentras información relevante, extrae y menciona datos concretos: importes, plazos, requisitos de edad, comunidad autónoma, cómo solicitarla.
4. Cita siempre el nombre de la convocatoria entre paréntesis al mencionar cada ayuda.
5. Si los fragmentos no contienen información suficiente, responde: "No tengo información suficiente en las convocatorias disponibles."
6. Termina con una línea: "⚠️ Información orientativa. Consulta siempre la convocatoria oficial antes de solicitar."
"""


def construir_contexto(resultados: list[dict]) -> str:
    fragmentos = []
    for i, r in enumerate(resultados, start=1):
        fragmentos.append(
            f"[{i}] {r['nombre']} (ámbito: {r['ambito']}, categoría: {r['categoria']})\n{r['texto']}"
        )
    return "\n\n---\n\n".join(fragmentos)


def responder(pregunta: str) -> str:
    resultados = buscar(pregunta, k=TOP_K)

    if not resultados:
        return "No he encontrado convocatorias relevantes para tu consulta."

    contexto = construir_contexto(resultados)

    prompt = f"""A continuación tienes fragmentos REALES de convocatorias oficiales españolas.
Debes responder la pregunta usando SOLO estos fragmentos. No añadas nada más.

FRAGMENTOS OFICIALES:
{contexto}

PREGUNTA: {pregunta}

RESPUESTA (basada exclusivamente en los fragmentos anteriores):"""

    respuesta = ollama.chat(
        model=MODELO,
        messages=[
            {"role": "system", "content": SISTEMA},
            {"role": "user", "content": prompt},
        ],
    )

    return respuesta.message.content


def main() -> None:
    pregunta = input("¿En qué te puedo ayudar? > ").strip()
    if not pregunta:
        print("No has escrito nada.")
        return

    print("\nBuscando y generando respuesta...\n")
    print("=" * 60)
    print(responder(pregunta))
    print("=" * 60)


if __name__ == "__main__":
    main()
