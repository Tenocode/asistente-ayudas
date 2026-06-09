# Asistente Ayudas

Asistente RAG de ayudas y subvenciones públicas en España. El usuario describe su
situación en lenguaje natural y el sistema le dice a qué ayudas puede optar, explicadas
en claro, con importe, plazo y enlace oficial, citando siempre la convocatoria fuente.

- **Nicho de arranque:** ayudas estatales + La Rioja (vivienda, carnet, formación, empleo)
- **Visión a futuro:** toda España, cualquier edad — escalar = cargar más datos, no reprogramar

---

## Estado actual

**Fases 1, 2 y 3 completas. Siguiente: Fase 4 — interfaz web.**

| Paso | Estado |
|---|---|
| Descargar PDFs (`src/descargar.py`) | ✅ 8 PDFs en `data/convocatorias/` |
| Trocear texto (`src/trocear.py`) | ✅ 76 fragmentos ~500 palabras, solapamiento 50 |
| Postgres + pgvector en Docker | ✅ Corriendo, tabla `fragmentos` creada (vector dim 384) |
| Indexar: embeddings + insertar (`src/indexar.py`) | ✅ 1113 fragmentos de 66 PDFs insertados en Postgres |
| Búsqueda semántica (`src/buscar.py`) | ✅ Búsqueda coseno con pgvector funcionando |
| Respuesta con LLM (`src/responder.py`) | ✅ Respuestas en español citando fuentes (Ollama + llama3.1:8b) |
| Conversación de perfilado (`src/chat.py`) | ✅ Perfil híbrido: preguntas en Python + LLM para respuesta |
| Interfaz web (FastAPI + chat) | ⬜ Fase 4 |
| Pipeline de actualización | ⬜ Fase 5 |

---

## Siguiente paso concreto — Fase 4: interfaz web

Crear una web con chat donde el usuario use el asistente desde el navegador.
Backend con FastAPI (Python) que expone un endpoint `/chat`. Frontend sencillo con HTML/JS.
El flujo actual de `src/chat.py` se convierte en una API REST.

Datos actuales: 66 PDFs, 1113 fragmentos. Categorías cubiertas: formacion, empleo, vivienda,
carnet, movilidad, cultura, dependencia. Ámbitos: estatal, larioja, extremadura, murcia.

Modelo de embeddings actualizado a `paraphrase-multilingual-MiniLM-L12-v2` — resuelve los
fallos de búsqueda en español (ej. "carnet de coche" → "permiso de conducir").

---

## Estructura del repo

```
asistente-ayudas/
  data/
    convocatorias/      # 8 PDFs de convocatorias descargados
    urls.txt            # formato: nombre | ámbito | categoría | url
  src/
    descargar.py        # descarga los PDFs de urls.txt
    trocear.py          # extrae texto y trocea en fragmentos ~500 palabras con solape
    init_db.py          # crea la tabla `fragmentos` (DROP + CREATE, vector dim 384)
    indexar.py          # trocea + genera embeddings + inserta en Postgres (reindexado completo)
  docker-compose.yml    # Postgres 16 + pgvector
  requirements.txt
  CLAUDE.md             # contexto completo del proyecto para Claude
  README.md
```

---

## Stack

- Python 3.11 + `venv`
- PostgreSQL 16 + pgvector (Docker)
- Embeddings locales: `sentence-transformers` — modelo `paraphrase-multilingual-MiniLM-L12-v2` (dim 384, multilingüe)
- LLM para respuestas: Ollama local, modelo `llama3.1:8b` (sin coste, sin API externa)

---

## Instalación

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

## Arrancar la base de datos

```powershell
docker compose up -d
python src/init_db.py   # crea (o recrea) la tabla fragmentos
```

## Indexar los PDFs

```powershell
python src/indexar.py   # trocea, genera embeddings e inserta en Postgres
```

> La primera ejecución descarga el modelo ~90 MB a caché local. Las siguientes son rápidas.

---

## Decisiones clave

- **Embeddings locales** (no API): para aprender y evitar dependencias externas. A esta escala la calidad es suficiente.
- **Reindexado completo** en desarrollo: `TRUNCATE` + reinserción en cada ejecución, evita duplicados. La lógica de acumular solo lo nuevo va en la Fase 5.
- **Postgres + pgvector** en vez de BD vectorial dedicada: una sola herramienta para datos y vectores, más transferible.
- **Solapamiento de 50 palabras** entre fragmentos: evita cortar información clave justo en el límite.

---

## Aviso

Una ayuda mal citada es peor que nada. El sistema siempre cita la fuente oficial y deja
claro que es orientativo, no asesoría legal.
