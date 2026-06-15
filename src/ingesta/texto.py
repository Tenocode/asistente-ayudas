"""
Normalización de texto extraído de cualquier fuente (PDF/HTML).

Punto único para limpiar el ruido de símbolos que vimos en el corpus, en vez de
duplicar `.replace(...)` por cada adaptador:

- **NFKC**: unifica ligaduras (ﬁ→fi), anchos completos y variantes de símbolos a
  su forma canónica. Hace el texto más uniforme para troceo, embeddings y matcher
  de cuantías.
- **Caracteres de control (categoría Cc)**: se eliminan (incluye `\x00` y `\r`),
  salvo el salto de línea y el tabulador, que sí estructuran el texto.
- **Uso privado / no asignados / reemplazo (Co, Cn, Cs y U+FFFD)**: se sustituyen
  por un espacio. Algunos PDFs codifican el espacio como U+FFFF (categoría Cn) o
  usan glifos de uso privado como separador; pasarlos a espacio evita que las
  palabras queden pegadas ("cuantia<>de<>250<>euros") y que el troceo cuente un
  bloque pegado como una sola palabra.

Es idempotente: re-aplicarla sobre texto ya limpio no lo cambia.
"""
import unicodedata

# U+FFFD REPLACEMENT CHARACTER es categoría "So" (símbolo), no entra en el filtro
# de categorías de abajo, así que lo tratamos aparte: indica un fallo de
# decodificación, lo pasamos a espacio.
_REEMPLAZO = "�"


def normalizar_texto(texto: str) -> str:
    if not texto:
        return texto

    texto = unicodedata.normalize("NFKC", texto)

    salida: list[str] = []
    for ch in texto:
        if ch in ("\n", "\t"):
            salida.append(ch)
            continue
        if ch == _REEMPLAZO:
            salida.append(" ")
            continue
        categoria = unicodedata.category(ch)
        if categoria == "Cc":  # control -> fuera (incluye \x00, \r)
            continue
        if categoria in ("Co", "Cn", "Cs"):  # uso privado / no asignado / surrogate
            salida.append(" ")
            continue
        salida.append(ch)

    return "".join(salida)
