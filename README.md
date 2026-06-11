# Asistente Ayudas

Asistente RAG de ayudas y subvenciones públicas en España. El usuario describe su
situación en lenguaje natural y el sistema le dice a qué ayudas puede optar, explicadas
en claro, con importe, plazo y enlace oficial, citando siempre la convocatoria fuente.

- **Nicho de arranque:** ayudas estatales + La Rioja (vivienda, carnet, formación, empleo)
- **Visión a futuro:** toda España, cualquier edad — escalar = cargar más datos, no reprogramar

---

## Estado actual

**Fases 1–4 completas + Fase 5 iniciada (BDNS API).**

| Paso | Estado |
|---|---|
| Descargar PDFs (`src/descargar.py`) | ✅ PDFs en `data/convocatorias/` |
| Trocear texto (`src/ingesta/trocear.py`) | ✅ ~500 palabras, solapamiento 50 |
| Postgres + pgvector en Docker | ✅ Tablas `fuentes` y `fragmentos` (vector dim 384) |
| Indexar PDFs (`src/indexar.py`) | ✅ 68 PDFs indexados (1120 fragmentos) |
| Búsqueda semántica (`src/rag/buscar.py`) | ✅ Coseno con pgvector |
| Respuesta con LLM (`src/rag/chat.py`) | ✅ Ollama + llama3.1:8b citando fuentes |
| Interfaz web (`src/api.py` + `src/static/index.html`) | ✅ FastAPI + chat. Arrancar: `python src/api.py` |
| Widget embebible (`src/static/widget.html` + `src/static/embed.js`) | 🧪 MVP técnico; pendiente de validar |
| Ingesta multi-fuente (`src/ingesta/`) | ✅ Pipeline JSONL + adaptadores PDF/HTML/bdns_api |
| **BDNS API** (`src/ingesta/fuentes/bdns.py`) | ✅ Descubrimiento automatico de convocatorias |
| Pipeline de actualización completo | 🔄 En curso (Fase 5) |

Datos actuales: **77 fuentes** (68 PDF + 9 BDNS API), **1130 fragmentos**.
Categorías: formacion, empleo, movilidad, cultura, vivienda, dependencia, carnet.
Ámbitos: estatal (56), larioja (15), extremadura (2), andalucia (1), castillaleon (1), murcia (1).

---

## Siguiente paso concreto — Fase 5: pipeline de actualización

El descubrimiento automático de convocatorias vía BDNS ya funciona. Lo que falta:

- Marcar convocatorias con plazo vencido como cerradas
- Programar el script BDNS para que se ejecute periódicamente (semanal/mensual)
- Fuentes no cubiertas por BDNS: Gobierno de La Rioja (carnet conducir, emancipación juvenil)
  requieren scraping directo de su portal de subvenciones

Modelo de embeddings: `paraphrase-multilingual-MiniLM-L12-v2` (dim 384, multilingüe).

---

## Nota sobre fuentes no-PDF

El flujo actual basado en PDFs debe seguir funcionando. Es la ruta principal y más estable
del proyecto en este momento.

Como evolución, el sistema debería aceptar también fuentes oficiales que no sean PDF:
páginas web institucionales, sedes electrónicas, boletines HTML y portales de trámites.
La idea no es sustituir el pipeline de PDFs, sino añadir otro pipeline de ingesta con el
mismo objetivo: convertir fuentes oficiales en fragmentos trazables para el RAG.

La regla de calidad se mantiene: no se indexa una ayuda si no tiene fuente oficial, URL
verificable y texto/evidencia suficiente para justificar la respuesta.

Primer paso completado: la base ya separa `fuentes` de `fragmentos`. Cada PDF genera una
fila en `fuentes` con sus metadatos y URL oficial, y sus trozos quedan enlazados desde
`fragmentos.fuente_id`. Esto permite añadir más adelante adaptadores HTML/sede/boletín
sin romper el pipeline actual de PDFs.

Segundo paso completado: se añadió una primera capa de ingesta multi-fuente en
`src/ingesta/`. Esta capa todavía no inserta en Postgres; sirve para probar extracción de
fuentes candidatas antes de indexarlas. Soporta:

- candidatos en JSONL (`data/candidatos.example.jsonl`);
- adaptador PDF por URL;
- adaptador HTML/web por URL;
- comando de prueba `python src/ingestar_fuentes.py --candidatos data/candidatos.example.jsonl`.

El formato de candidato es deliberadamente pequeño: el investigador humano o IA propone
URLs oficiales, y el sistema extrae el texto real desde esas URLs antes de aceptarlas.

---

## Widget embebible

Se añadió un MVP técnico para probar el asistente como widget integrable en otras webs.
No está validado todavía como producto comercial.

Prueba local:

```text
http://localhost:8000/codigo-widget?entidad=Ayuntamiento%20demo&comunidad=larioja
```

Ejemplo de inserción futura:

```html
<div id="asistente-ayudas-widget"></div>
<script
  src="https://tu-dominio.com/embed.js"
  data-entidad="Entidad demo"
  data-comunidad="larioja"
  data-modo="inline">
</script>
```

---

## Estructura del repo

```
asistente-ayudas/
  data/
    convocatorias/        # PDFs de convocatorias descargados
    urls.txt              # formato: nombre | ámbito | categoría | url
    candidatos.jsonl      # fuentes candidatas manuales (PDF/HTML por URL)
    candidatos_bdns.jsonl # salida del conector BDNS (generado, no se sube al repo)
  src/
    db/
      init_db.py          # crea tablas `fuentes` + `fragmentos` (DROP + CREATE)
    ingesta/
      trocear.py          # extrae texto de PDFs y trocea en fragmentos ~500 palabras
      modelos.py          # tipos de datos: CandidatoFuente, FuenteExtraida
      pipeline.py         # lectura JSONL, detección de tipo y extracción
      indexar_fuente.py   # inserta una FuenteExtraida en Postgres (con dedup)
      adaptadores/
        pdf.py            # extractor PDF por URL
        html.py           # extractor HTML/web por URL
      fuentes/
        bdns.py           # conector BDNS: busca, filtra y genera candidatos_bdns.jsonl
    rag/
      buscar.py           # búsqueda semántica con pgvector + JOIN a fuentes
      chat.py             # perfilado de usuario + generación de respuesta LLM
    static/
      index.html          # interfaz web principal
      widget.html         # interfaz del widget embebible
      embed.js            # script de inserción del widget
    api.py                # servidor FastAPI + web + widget
    descargar.py          # CLI: descarga PDFs desde urls.txt
    indexar.py            # CLI: trocea + embeddings + inserta todos los PDFs
    ingestar_fuentes.py   # CLI: extrae e indexa candidatos de candidatos.jsonl
  docker-compose.yml      # Postgres 16 + pgvector
  requirements.txt
  CLAUDE.md
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

## Arrancar la web

```powershell
python src/api.py
```

## Descubrir y añadir convocatorias desde la BDNS

La BDNS (Base de Datos Nacional de Subvenciones) tiene más de 600.000 convocatorias
accesibles por API pública. Este comando las busca, filtra por ámbito y categoría,
y genera un archivo JSONL listo para indexar:

```powershell
# Busca convocatorias estatal + La Rioja desde 2025, todas las categorías
python src/ingesta/fuentes/bdns.py --desde 2025-01-01 --ambito estatal larioja

# Sólo vivienda y carnet de La Rioja
python src/ingesta/fuentes/bdns.py --desde 2025-01-01 --ambito larioja --categorias vivienda carnet
```

Luego indexa los resultados (la deduplicación es automática):

```powershell
python src/ingestar_fuentes.py --candidatos data/candidatos_bdns.jsonl --indexar
```

## Ingesta manual multi-fuente

Para añadir candidatos propios (PDFs por URL o páginas web), crea `data/candidatos.jsonl`:

```json
{"nombre":"Nombre de la ayuda","ambito":"larioja","categoria":"vivienda","url_oficial":"https://...","tipo_fuente":"auto","organismo":"Gobierno de La Rioja"}
```

```powershell
python src/ingestar_fuentes.py --candidatos data/candidatos.jsonl --indexar
```

---

## Decisiones clave

- **Embeddings locales** (no API): para aprender y evitar dependencias externas. A esta escala la calidad es suficiente.
- **Reindexado completo** en desarrollo: `TRUNCATE` + reinserción en cada ejecución, evita duplicados. La lógica de acumular solo lo nuevo va en la Fase 5.
- **Postgres + pgvector** en vez de BD vectorial dedicada: una sola herramienta para datos y vectores, más transferible.
- **Solapamiento de 50 palabras** entre fragmentos: evita cortar información clave justo en el límite.
- **Separación fuente/fragmento:** `fuentes` guarda el documento o página oficial; `fragmentos` guarda los trozos vectorizados. Así el RAG puede crecer a varios tipos de ingesta.
- **Candidatos antes que verdad:** una investigación externa solo propone URLs candidatas; el sistema debe descargar la fuente oficial y extraer texto real antes de indexar.
- **Fuentes no-PDF como extensión, no sustitución:** primero se mantiene el pipeline de PDFs y después se añade ingesta desde HTML/sedes/boletines con validación.

---

## Aviso

Una ayuda mal citada es peor que nada. El sistema siempre cita la fuente oficial y deja
claro que es orientativo, no asesoría legal.
