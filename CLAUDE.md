# CLAUDE.md — Contexto del proyecto

> Este archivo lo lees automáticamente al abrir el proyecto. Contiene el plan, el estado
> y la forma de trabajar. Antes de cada paso, dime brevemente qué vamos a hacer y por qué,
> hazme preguntas en vez de asumir, y al terminar cada script explícamelo por encima.
> Vamos paso a paso, sin adelantarnos a fases futuras.

## Qué estamos construyendo

Un asistente RAG de ayudas y subvenciones públicas en España. El usuario describe su
situación en lenguaje natural y el sistema le dice a qué ayudas puede optar, explicadas
en claro, con importe, plazo y enlace oficial, **citando siempre la convocatoria fuente**.

- **Nicho de arranque (este verano):** ayudas estatales + Comunidad de La Rioja.
  Categorías: vivienda/alquiler, carnet de conducir, formación/becas, primer empleo/emprendimiento.
- **Visión a futuro:** toda España, cualquier edad, cualquier comunidad. IMPORTANTE: esto
  NO es entrenar un modelo propio; es el mismo RAG con más documentos y filtros más ricos
  (edad, comunidad, situación). Escalar = cargar más datos, no reprogramar.

## Objetivo personal

El autor está aprendiendo para ser AI engineer. Prioriza que ENTIENDA cada pieza por
encima de la velocidad. Explica conceptos, no solo generes código. El valor de CV está en
saber construir sistemas con IA (RAG, tool use, agentes, pipelines), no en entrenar modelos base.

## Stack

- **Python** + entorno virtual (`venv`).
- **PostgreSQL + pgvector** corriendo en Docker (`docker-compose.yml`).
  Credenciales de desarrollo: usuario/contraseña/db = `ayudas`, host localhost, puerto 5432.
- **Embeddings locales** con `sentence-transformers`, modelo `all-MiniLM-L6-v2` (vectores dim 384).
- **LLM local con Ollama** para generar las respuestas citando fuentes (sin coste, sin API key).
  Modelo: `llama3.2` o similar. Decisión explícita: no usar APIs de pago.

## Estructura del repo

```
asistente-ayudas/
  data/
    convocatorias/      # PDFs de las convocatorias (8 descargados)
    urls.txt            # PDFs directos (formato: nombre | ámbito | categoría | url)
    paginas-pendientes.txt  # convocatorias que son páginas web, no PDF (para más adelante)
  src/
    descargar.py        # descarga los PDFs de urls.txt
    trocear.py          # extrae texto y trocea en fragmentos ~500 palabras con solape
    init_db.py          # crea la tabla `fragmentos` (embedding vector dim 384)
    indexar.py          # (en construcción) trocea + embeddings + inserta en Postgres
  CLAUDE.md
  README.md
```

Tabla `fragmentos`: id, nombre de ayuda, ámbito, categoría, texto del fragmento, embedding (vector 384).

## Plan por fases

1. **Recopilar y entender datos** — HECHO. 8 PDFs descargados, leídos, troceado validado (76 fragmentos).
2. **RAG mínimo** — EN CURSO. Postgres+pgvector listo, tabla creada. Falta: `indexar.py`
   (generar embeddings e insertar) y luego el script de búsqueda + respuesta con Claude citando.
3. **Conversación de perfilado** — pendiente. Claude pregunta lo justo (edad, comunidad,
   situación) vía tool use y filtra/prioriza ayudas.
4. **Interfaz** — pendiente. Web sencilla (chat + lista de ayudas) con backend FastAPI.
5. **Pipeline de actualización** — pendiente. Proceso que trae convocatorias nuevas y reindexa;
   marca plazos abiertos/cerrados. AQUÍ irá la lógica de añadir solo lo nuevo sin reprocesar.
6. **MCP (opcional, nota alta)** — pendiente. Exponer la base de ayudas como servidor MCP.

## Decisiones tomadas (y su porqué)

- **Troceado:** ~500 palabras con ~50 de solapamiento, para no cortar info clave entre fragmentos.
- **Embeddings locales, no Voyage/API:** para aprender y no depender de cuentas/keys externas;
  a esta escala la diferencia de calidad es irrelevante.
- **Reindexar desde cero en desarrollo:** evita duplicados al repetir ejecuciones. La lógica de
  acumular sin reprocesar se deja para la fase 5, cuando reindexar todo sea costoso.
- **Postgres+pgvector en vez de BD vectorial dedicada:** una sola herramienta para datos y vectores,
  y es más transferible/vendible en CV.

## Reglas de trabajo

- Tareas pequeñas y acotadas, una a una. No construir varias fases de golpe.
- Explicar antes de ejecutar; el autor no corre scripts a ciegas.
- Secretos (API keys) NUNCA en el repo: van en `.env`, que está en `.gitignore`.
- `venv/` no se sube al repo; se regenera al clonar.

## Avisos

- Precisión: una ayuda mal citada es peor que nada. El sistema siempre cita la fuente oficial
  y deja claro que es orientativo, no asesoría legal.
- Los enlaces que vengan de agentes de búsqueda pueden estar mal/caducados: validar siempre.
