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
| Respuesta con LLM (`src/rag/chat.py`) | ✅ Ollama + llama3.2 (3B) citando fuentes y detalles clave; tope de tokens y blindaje anti-invención |
| Interfaz web (`src/api.py` + `frontend/` React) | ✅ Backend FastAPI + front React/Vite (tarjetas con estado y enlace clicable a la fuente). Front legacy vanilla en `src/static/`. Arrancar: backend `python src/api.py` + `cd frontend && npm run dev` |
| Widget embebible (`src/static/widget.html` + `src/static/embed.js`) | 🧪 MVP técnico; pendiente de validar |
| Ingesta multi-fuente (`src/ingesta/`) | ✅ Pipeline JSONL + adaptadores PDF/HTML/bdns_api |
| **BDNS API** (`src/ingesta/fuentes/bdns.py`) | ✅ Descubrimiento por keyword **y por región** (`--por-region`: barre TODO La Rioja) |
| **ADER** (`src/ingesta/fuentes/ader.py`) | ✅ Descubridor inicial de ayudas de negocio/empresa en La Rioja |
| **IRJ** (`src/ingesta/fuentes/irj.py`) | ✅ Ayudas a jóvenes (carné, emancipación, voluntariado, formación) que BDNS no cubre |
| **Logroño** (`src/ingesta/fuentes/logrono.py`) | ✅ Ayudas municipales (Chiquibecas, libros, mayores 85, comercio) que BDNS no cubre |
| Evaluacion RAG (`src/evaluar_rag.py`) | ✅ Golden set con veredicto PASS/FAIL y código de salida (gate) |
| Vigencia (`src/db/vigencia.py`) | ✅ Marca abierta/cerrada/desconocida; las cerradas bajan en ranking y avisan |
| Pipeline de actualización completo | 🔄 En curso (Fase 5) |

Datos locales comprobados el 2026-06-15 (tras BDNS region-first, limpieza de ediciones
obsoletas y los conectores IRJ y Logroño): **217 fuentes** en Postgres. La Rioja pasa de
47 a **156 fuentes**.

Hallazgo y acción 2026-06-13 (barrido region-first): el universo riojano de BDNS (2025–2026)
es de **1.613 convocatorias**, no las ~190 que veía el método por keyword. Tras descartar ruido
administrativo (867) e inter-administrativas (29), colapsar ediciones anuales y clasificar,
quedan **209 ayudas únicas en categorías diana**. Se indexaron las **84 de categorías con hueco**
(dependencia, vivienda, movilidad, formación) → **78 fuentes nuevas**, con el evaluador como gate
(**5/5 bloqueantes PASS**, sin regresión). El resto (empleo/cultura y lo no clasificado) queda en
`data/revision_bdns_larioja.md` para revisión. Ver punto 5 de la hoja de ruta.

---

## Cobertura actual y hoja de ruta (2026-06-13)

### Qué cubrimos (fuentes por ámbito × categoría)

| Ámbito | Total | Desglose |
|---|---|---|
| estatal | 56 | formación 16 · empleo 12 · movilidad 10 · cultura 9 · dependencia 5 · vivienda 4 · **carnet 0** |
| La Rioja | 125 | formación 46 · empleo 34 · movilidad 22 · vivienda 18 · **dependencia 3** · carnet 1 (IRJ) · cultura 1 |
| otras CCAA | 5 | solo carnet (Murcia, Andalucía, Extremadura×2, Castilla y León) |

Lectura (actualizada 2026-06-13 tras BDNS region-first): La Rioja salta de 47 a **125 fuentes**.
Los huecos del nicho de arranque (*vivienda · carnet · formación · empleo*) quedan **cubiertos**:
formación 5→46, vivienda 5→18, movilidad 1→22, y **dependencia 0→3 (cero roto)**. Empleo y carnet
ya estaban. Pendiente afinar: emprendimiento/ayudas municipales de Logroño (apenas en BDNS) y
profundizar dependencia/cultura (aún finas).

### Hoja de ruta priorizada

1. **Vigencia de convocatorias.**
   - **Paso 1 — HECHO (2026-06-13).** Esquema ampliado con `fecha_fin DATE` y `estado`
     (`abierta`/`cerrada`/`desconocida`). Nuevo módulo `src/db/vigencia.py`: parsea fechas en
     español (incluye fechas "pegadas" de PDFs degradados tipo `1deseptiembrede2025`), marca
     cada fuente y rellena las columnas SIN reindexar (`ALTER ADD COLUMN` + backfill leyendo
     `texto_extraido`). Reparto inicial: 29 abiertas, 17 cerradas, 58 desconocidas. Ejecutar:
     `python src/db/vigencia.py` (o `--informe` para ver el reparto).
   - **Paso 2 — HECHO (2026-06-13).** `buscar` devuelve ahora `estado` y `fecha_fin`. En
     `puntuar_resultado` las `cerrada` reciben una penalización **moderada** (+0,10) que las
     baja en ranking **sin ocultarlas** (un falso positivo del parser solo molesta, nunca
     esconde una ayuda válida); `desconocida` no se penaliza. El aviso de plazo cerrado es
     **determinista** (`avisos_vigencia`/`aplicar_avisos`): se genera leyendo la BD y se añade
     como pie garantizado, no depende de que el LLM lo recuerde; además el contexto marca
     `[PLAZO CERRADO el ...]` para que la línea de Plazo sea coherente. El evaluador muestra
     `top_estados` y comprueba que las cerradas del top lleven aviso. Validado: en
     `autonomo_larioja`, Consolidación (cerró 14-may-2026) baja a 2ª, Inversiones (abierta)
     sube a 1ª, y la respuesta incluye el aviso. Sin regresión en el resto.
2. **Golden set en el evaluador — HECHO (2026-06-13).** Cada `CasoEval` declara las `cuantias`
   que la respuesta DEBE citar (autónomo → `2.700`/`2.100`, comercio → `25%`/`35%`, vivienda →
   `250 euros`, pyme → `70 euros`) y se marca como `bloqueante` (regresión = rojo) u objetivo
   (hueco conocido que se mide pero no bloquea). El evaluador da veredicto **PASS/FAIL** con
   **código de salida** (≠0 si falla un bloqueante), usable como gate. Verificado con LLM:
   4/4 bloqueantes PASS (cuantías + aviso de cerrada incluidos).
3. **Carnet La Rioja — HECHO (2026-06-13).** Verificado que BDNS NO tiene carnet de La Rioja
   (ni autonómica ni local). La Rioja sí da la ayuda vía **IRJ** (dentro de "emancipación
   juvenil en materia de formación"). Se indexó la ficha oficial del trámite
   (`web.larioja.org/oficina-electronica/tramite?n=24664`) como `categoria=carnet`,
   `ambito=larioja` (beneficiarios 18-35 empadronados, qué cubre, periodo). La página dice
   "Fuera de plazo de solicitud" → se añadió esa señal textual al detector de vigencia
   (`vigencia.py`) para marcarla `cerrada` aunque no haya fecha parseable. Ahora
   `carnet_conducir` devuelve la fuente riojana (antes caía a Extremadura) y es caso
   **bloqueante** en el golden set. La ficha no publica importe por persona (está en el BOR),
   así que la respuesta lo dice honestamente en vez de inventarlo.
4. **Barrido BDNS de La Rioja — HECHO (2026-06-13).** Hallazgo: el barrido **autonómico** ya
   estaba saturado (vivienda/formación que devolvía ya estaban indexadas; dependencia = 0 en
   BDNS). El filón estaba en lo **LOCAL**: `inferir_ambito` no reconocía Logroño ni los
   municipios riojanos, así que sus ayudas caían como "desconocido". Se añadió `MUNICIPIOS_LARIOJA`
   (capital + principales) al conector. El re-barrido encontró 11 candidatos locales, pero la
   mayoría eran **convenios/adendas administrativos** (no ayudas a ciudadanos) → se añadieron a
   la BLACKLIST del conector. Se indexaron solo las 3 genuinas: Concurso Emprendedores de Alfaro,
   CS Emprendimiento (cooperativas) y Bases de contratación de menores de 30 / Garantía Juvenil.
   Conclusión ~~la veta de BDNS para La Rioja está prácticamente agotada~~ **CORREGIDA en el
   punto 5**: esa conclusión era un **artefacto del método por keyword**, no del dato. El
   barrido por región (punto 5) demostró que el universo riojano de BDNS es mucho mayor.
5. **Barrido BDNS region-first de La Rioja — HECHO (2026-06-13).** Corrige el punto 4. El
   método por keyword solo veía convocatorias cuya *descripción* casaba un término, dejando
   fuera el grueso del universo riojano. La API BDNS **sí filtra por región** con el parámetro
   `regiones` (plural): La Rioja son los ids **19 (ES23)** y **20 (ES230)**, que no se solapan,
   así que hay que unir ambos y deduplicar. Nuevo modo `--por-region` en `bdns.py` que:
   (1) enumera TODO el universo riojano (**1.613** convocatorias 2025–2026, deduplicadas);
   (2) descarta ruido administrativo con una **blacklist ampliada** (nominativas, convenios,
   premios, patrocinios, procesos selectivos…) → **867** fuera; (3) las keywords pasan de filtro
   a **clasificador** por inicio de palabra (`\b`, para que "aval" no clasifique "carn**aval**"
   ni "cultura" clasifique "agri**cultura**") → **275** clasificadas {dependencia 7, vivienda 28,
   movilidad 27, formación 49, empleo 107, cultura 57}; (4) lo no clasificado (**471**) **no se
   tira**: va a un informe de revisión (`data/revision_bdns_larioja.md`). Hallazgo clave:
   **rompe el cero de dependencia** (ayudas a contratación de cuidadores/empleados de hogar,
   descuentos de transporte para mayores de 65) y aflora vivienda/formación/movilidad que el
   keyword no veía (bono infantil, libros de texto, comedor, becas de permanencia UR,
   rehabilitación de edificios, bicicletas, carné de transporte de estudiantes). Salida:
   `data/candidatos_bdns.jsonl` (enriquecidos, ordenados por prioridad de hueco).
   - **Profundización + indexado — HECHO (noche 2026-06-13).** Sobre el barrido base se añadió:
     (a) **caché del universo** (`--cache`/`--usar-cache`) para iterar la clasificación sin
     re-barrer la API; (b) **filtro inter-administrativo**: ayudas cuyo beneficiario es otra
     administración (a municipios/EELL) se apartan a su propio cubo del informe (29), no
     ensucian candidatos; (c) **dedup de ediciones anuales**: la misma ayuda reconvocada cada
     año (nombre igual salvo el año) se colapsa quedándose con la más reciente (63 colapsadas);
     (d) **tests deterministas** del conector en `tests/test_bdns.py` (clasificador, blacklist,
     inter-admin, ámbito, dedup) — congelan regresiones como "carnaval→vivienda"; (e) revisión
     del bucket *sin clasificar*: era casi todo agrario/medioambiente/entidades (fuera de nicho,
     correcto que quede en revisión); se añadieron al clasificador `transporte escolar` y el
     stem `discapacit` (antes "discapacidad" no casaba "discapacit**ados**"). Resultado del
     barrido limpio: universo 1.613 → 867 descartadas + 29 inter-admin + **209 clasificadas
     únicas** (tras colapsar 63) + 445 sin clasificar. **Se indexaron las 84 de categorías con
     hueco** (dependencia/vivienda/movilidad/formación) con `--min-palabras 120` → **78 fuentes
     nuevas** (3 ya existían, 3 con texto insuficiente). Se corrió `vigencia.py` y el evaluador
     como **gate**: **5/5 bloqueantes PASS**, sin regresión (rollback por `url_oficial` preparado
     por si fallaba). Nuevo caso `dependencia_larioja` en el golden set (objetivo) que congela el
     cero roto. Empleo (79) y cultura (46) NO se indexaron (empleo ya lo cubre ADER; cultura es
     ruidosa); quedan en el informe por si se quieren rescatar.
6. **Calidad de extracción de texto (palabras pegadas) — PARCIAL (2026-06-15).**
   - **Hallazgo:** el síntoma "palabras pegadas" (`cuantía<>de<>250<>euros`, fechas tipo
     `1deseptiembrede2025`) NO era cosa de `pypdf`. Se probó **PyMuPDF (fitz)** como alternativa y
     se descartó: A/B sobre el corpus real da empate o ligeramente peor (control chars, tokens-basura)
     y texto **idéntico** en la única cuantía del golden set respaldada por PDF ("250 euros" del
     alquiler joven). El € que "se perdía" era cómo lo pintaba la consola de Windows, no la extracción.
     PyMuPDF solo gana en PDFs difíciles (escaneados/columnas), que apenas tenemos. **Veredicto:
     seguir con `pypdf`; no reabrir esto salvo que entren PDFs escaneados.**
   - **Causa real = U+FFFF.** 5 PDFs de juventud/vivienda de La Rioja (el nicho) y alguna ficha
     codifican el **espacio como U+FFFF** (carácter de reemplazo). Eso pega las palabras y, peor,
     **rompe el troceo**: `trocear()` parte por espacios, así que un bloque pegado contaba como UNA
     palabra y los fragmentos salían sobredimensionados (el alquiler joven tenía 16 fragmentos en vez
     de 34). Lo sufren pypdf y fitz por igual.
   - **Arreglo:** normalizar `U+FFFF → espacio` en origen (`pdf.py`, `trocear.py`, `html.py`, donde
     ya se limpiaba `\x00`) para que las ingestas nuevas salgan limpias, + reparación en sitio del
     corpus ya indexado con `src/db/reparar_uffff.py` (re-extrae/limpia, re-trocea, re-embebe solo las
     fuentes afectadas; sin red, sin TRUNCATE, idempotente). Resultado: 9 fuentes reparadas, 0 U+FFFF
     en BD, fragmentos bien dimensionados. Gate **5/5 bloqueantes PASS antes y después** (era mejora de
     calidad/robustez, no un gate rojo: la 2ª copia limpia de "250 euros" ya lo salvaba).
   - **Blindaje genérico (2026-06-15).** Se centralizó la limpieza en `src/ingesta/texto.py`
     (`normalizar_texto`, usada por `pdf.py`, `trocear.py` y `html.py`): **NFKC** (ligaduras
     ﬁ→fi, anchos completos, variantes de símbolos) + eliminación de caracteres de control (Cc)
     + sustitución por espacio de uso privado / no asignados / U+FFFF / U+FFFD (Co/Cn/Cs). Así no
     dependemos de listar glifo a glifo. Verificado que NFKC no rompe el matcher de cuantías
     (`70 €/m²`→`70 €/m2` sigue casando "70 euros") y gate **5/5 PASS**. Aplica a ingestas nuevas;
     el corpus ya cargado solo se reprocesaría con un reindexado (bajo valor: ya sin U+FFFF).
   - **Pendiente:** limpiar boilerplate de ADER y revisar el parche de `k=30`. OCR de respaldo
     (pytesseract) queda para cuando entren PDFs escaneados/cmap roto en el cuerpo (hoy la basura
     de fuente rota está solo en márgenes, no afecta a las respuestas).
7. **Filtro por edad/perfil** (Fase 3): muchas ayudas son ≤35 años; hoy no filtramos por edad.
8. **Emprendimiento/ayudas municipales de Logroño**: el barrido region-first (punto 5) **sí**
   encontró dependencia autonómica de La Rioja en BDNS (cuidadores, transporte de mayores),
   corrigiendo el supuesto anterior de que BDNS no la tenía. Lo que sigue flojo es el
   emprendimiento y las ayudas municipales de Logroño, que apenas registran en BDNS y
   probablemente requieran scraping directo del Ayuntamiento (como se hizo con el IRJ).

Diagnóstico de fondo: la latencia es del MODELO (fija) y el retrieval (lo que crece con la BD)
es barato e indexable. Por tanto **el cuello de botella para ser "vendible" son los DATOS**
(cobertura + frescura + vigencia), no la infraestructura.

### Disciplina de pruebas (testing continuo)

`src/evaluar_rag.py` es el "CI" del proyecto y ahora da **veredicto PASS/FAIL** con código de
salida (≠0 si falla un caso bloqueante), no solo un informe. Regla: **ningún cambio se da por
bueno sin la batería verde**.

- `python src/evaluar_rag.py --sin-llm` → rápido (sin Ollama). Verifica ranking, cobertura,
  URLs y vigencia. Ejecutar tras **cada** cambio.
- `python src/evaluar_rag.py` → además verifica las `cuantias` del golden set en la respuesta
  del LLM y el aviso de plazo cerrado. Ejecutar antes de cada commit.
- `python tests/test_bdns.py` → tests deterministas del conector BDNS (clasificador, blacklist,
  inter-admin, ámbito, dedup de ediciones). Sin red ni base. Veredicto VERDE/ROJO con código de
  salida. Ejecutar tras tocar `bdns.py`. Congela regresiones tipo "carnaval→vivienda".
- `python tests/test_eval_cuantias.py` → tests del **matcher de cuantías** del gate. Sin red ni LLM.
- `python tests/test_extractor.py` → tests del **extractor de detalles** (presupuesto/firma no se
  cuelan como dato; la cuantía individual real sobrevive). Sin red ni LLM.
- `python tests/test_vigencia.py` → tests del **detector de vigencia**: descarta back-references de
  fechas (un plan 2026-2030 no cierra en 2022) y conserva los plazos reales. Sin red ni base.

Cada caso es **bloqueante** (su fallo = regresión = batería en rojo) u **objetivo** (hueco
conocido: se mide pero no bloquea). Al cerrar una mejora, **añadir/actualizar el caso** con sus
cuantías esperadas para congelarlo. Así una cifra que hoy funciona no se puede perder en
silencio mañana. Workflow ligero (gate + golden set); CI/CD pesado todavía es prematuro.

**Matcher de cuantías robusto (2026-06-13).** El gate ya no compara importes por substring
literal (era frágil: `"70 euros"` no casaba `"70 €/m²"` y un cambio menor de fraseo del 3B
ponía la batería en rojo sin haber regresión real). Ahora `evaluar_rag.py` canonicaliza cada
importe a *(cifra, unidad)* y compara por **token exacto + clase de unidad** (`€`/`%`/ninguna):
`"70 euros"` casa `"70 €/m²"` pero **no** `"1.970"` ni `"70%"`. Cada cuantía esperada admite
alternativas con `|` (p. ej. `pyme_maquinaria` acepta el precio/m² **o** el rango de inversión,
ambos válidos). Diseñado para **no introducir falsos verdes**: ver casos negativos en los tests.

**Fix del "importe = presupuesto global" (2026-06-15).** Síntoma real: para una beca cuyo PDF
indexado era la *orden de ampliación de crédito* (sin cuantía por persona), el chat citaba como
importe el **crédito global** ("321.340 euros") que se colaba por el bloque de Beneficiarios.
Arreglo determinista en `chat.py` (`_scrub_ruido`): antes de mandar los detalles al LLM se quitan
las **frases de presupuesto/crédito/incremento** y el **boilerplate de firma electrónica** (CSV,
"no sustituye al documento original"). Si la fuente no tiene cuantía individual, el campo Importe
queda en "No aparece" en vez de inventar. Congelado en `tests/test_extractor.py`. Este fix solo
fue seguro de hacer **después** de robustecer el gate de cuantías (si no, la variación de fraseo
del 3B daba falsos rojos).

**Fix de back-reference en vigencia (2026-06-15).** Síntoma: "Plan Estatal Vivienda 2026-2030"
salía como *cerrada el 31/12/2022*. El detector (`src/db/vigencia.py`) tomaba como cierre cualquier
"hasta el <fecha>", y el texto del plan (un Real Decreto de ~400 KB) incluye "hasta el 31 de
diciembre de 2022 siempre que la concesión se realice con cargo a..." — una cláusula presupuestaria
del marco anterior, no el plazo de solicitud. Arreglo: se descartan las fechas de cierre anteriores
al **año dominante** del documento (la moda de los años que menciona; un RD de 2026 repite "2026").
Se usa la moda, no el máximo, porque el máximo se contamina con cifras mal leídas como años (2064,
2088…). Efecto medido sobre el corpus: **solo 1 fuente cambia** (el plan pasa a `desconocida`), las
45 cerradas legítimas se conservan; gate 5/5 PASS. Congelado en `tests/test_vigencia.py`.

**Limpieza de ediciones obsoletas (2026-06-15).** La misma ayuda reconvocada cada año quedaba
indexada varias veces (p. ej. "Becas Santander Movilidad 2025" y "...2026"). El dedup del barrido
se saltaba algunos pares por una palabra vacía ("Convocatoria **las** «Becas...»" vs "Convocatoria
«Becas...»"); se endureció `_clave_dedup` (quita artículos y "convocatoria") con test en
`tests/test_bdns.py`. Para limpiar lo ya indexado: `src/db/limpiar_ediciones.py` agrupa por
ambito+nombre-sin-año y borra **solo** las ediciones de años anteriores que estén `cerrada`
cuando existe una edición más reciente del mismo grupo (conserva la más reciente aunque esté
cerrada; nunca toca abiertas, desconocidas ni grupos de una sola edición). Dry-run por defecto;
`--aplicar` borra (con backup JSON) — validar con el gate después.

---

## Siguiente paso concreto — Fase 5: pipeline de actualización

El descubrimiento automático de convocatorias vía BDNS ya funciona, ahora por **keyword y por
región** (cobertura completa de La Rioja, ver punto 5). Hecho ya: barrido region-first, vigencia
(marca cerradas), tests del conector, e indexado de las categorías con hueco. Lo que falta:

- **Programar** el barrido BDNS para que se ejecute periódicamente (semanal/mensual) y reindexe
  solo lo nuevo (incremental, sin TRUNCATE) — pieza central de la Fase 5.
- **Indexar empleo/cultura** del barrido region-first si se decide (hoy solo se metieron las de
  hueco: dependencia/vivienda/movilidad/formación). Empleo ya lo cubre ADER en gran parte.
- Consolidar conectores por fuente oficial: ADER, IRJ, Gobierno de La Rioja, Logroño.
- Fuentes no cubiertas por BDNS: emprendimiento y ayudas municipales de **Logroño** (apenas
  registran en BDNS) requieren scraping directo de su portal.
- En el chat, las consultas de negocio se agrupan provisionalmente bajo la categoría `empleo`.

Modelo de embeddings: `paraphrase-multilingual-MiniLM-L12-v2` (dim 384, multilingüe).

---

## Mapa de fuentes para cubrir La Rioja

Objetivo: cubrir La Rioja completa antes de escalar comunidad por comunidad. El orden de
prioridad de fuentes debe ser:

1. **BDNS / SNPSAP** — ✅ **conector** (`bdns.py`, keyword + `--por-region`). Fuente transversal;
   universo riojano entero enumerado, nicho indexado.
   - API/docs: `https://www.infosubvenciones.es/bdnstrans/doc/swagger`
2. **Gobierno de La Rioja / Oficina electrónica** — 🟡 **parcial**: ~8 fichas sueltas indexadas a
   mano; falta conector sistemático (mejor texto que el PDF de BDNS).
   - `https://web.larioja.org/oficina-electronica/`
3. **Boletín Oficial de La Rioja (BOR)** — 🟢 indirecto vía BDNS; prioridad baja.
   - `https://web.larioja.org/bor`
4. **Instituto Riojano de la Juventud (IRJ)** — ✅ **conector** (`irj.py`, 2026-06-15): carné,
   emancipación, voluntariado, monitor/director, ayudas individuales. Lo que BDNS no cubre.
   - `https://www.irj.es/subvenciones`
5. **ADER** — ✅ **conector** (`ader.py`): empresas, autónomos, comercio, inversión.
   - `https://www.ader.es/ayudas/`
6. **Ayuntamiento de Logroño** — ✅ **conector** (`logrono.py`, 2026-06-15): Chiquibecas (educación
   infantil), libros y material escolar, ayudas a mayores de 85, Erasmus municipal, comercio,
   nuevas iniciativas económicas. BDNS solo tenía sus actos administrativos.
   - `https://logrono.es/becas-y-subvenciones`

Estado de cobertura (2026-06-15): la fuente transversal (BDNS) y los conectores de nicho (ADER,
IRJ, Logroño) están. La Rioja queda razonablemente cubierta a nivel de **fuentes**. Mejora
pendiente de calidad: un conector sistemático del portal del Gobierno de La Rioja (oficina
electrónica) para enriquecer el texto de las autonómicas que en BDNS llegan como PDF degradado.

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

### ¿Hay que tener todos los PDFs descargados?

No necesariamente. Para que el RAG responda, basta con guardar en Postgres:

- `url_oficial`;
- `tipo_fuente`;
- `texto_extraido`;
- `fragmentos`;
- `embedding`.

Los PDFs locales son útiles como caché y auditoría, pero no son obligatorios si el sistema
puede volver a descargar la fuente oficial. A futuro conviene añadir una caché controlada
(`data/cache/fuentes/`) con hash del archivo, fecha de descarga y URL, para poder reindexar
sin depender siempre de la red.

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

Tercer paso completado: se añadio `src/ingesta/fuentes/ader.py` como primer conector
especifico por fuente oficial. ADER no indexa directamente; descubre paginas oficiales de
ayudas para empresas, autonomos, comercio y emprendedores, genera `data/candidatos_ader.jsonl`,
y despues el importador comun decide si la pagina tiene texto suficiente para entrar al RAG.
Esta separacion es importante: cada fuente sabe descubrir sus URLs, pero la validacion,
extraccion, deduplicacion e indexado siguen centralizados.

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
    evaluaciones/         # informes locales de evaluar_rag.py (ignorado por git)
    urls.txt              # formato: nombre | ámbito | categoría | url
    candidatos.example.jsonl # ejemplo versionado de candidato manual
    candidatos.jsonl      # cola local de fuentes candidatas (ignorado por git)
    candidatos_bdns.jsonl # salida local del conector BDNS (ignorado por git)
    revision_bdns_larioja.md # informe del barrido --por-region (ignorado por git)
    _bdns_universo_larioja.json # cache del universo crudo BDNS (ignorado por git)
    candidatos_ader.jsonl # salida local del conector ADER (ignorado por git)
  src/
    db/
      init_db.py          # crea tablas `fuentes` + `fragmentos` (DROP + CREATE)
      vigencia.py         # marca fecha_fin/estado (abierta/cerrada/desconocida) leyendo el texto
      limpiar_ediciones.py # borra ediciones anuales obsoletas (dry-run / --aplicar)
      reparar_uffff.py    # limpia el espacio U+FFFF de fuentes ya indexadas (re-trocea+re-embebe, sin red)
    ingesta/
      trocear.py          # extrae texto de PDFs y trocea en fragmentos ~500 palabras
      texto.py            # normaliza símbolos (NFKC + control/uso-privado/U+FFFF→espacio) para PDF y HTML
      modelos.py          # tipos de datos: CandidatoFuente, FuenteExtraida
      pipeline.py         # lectura JSONL, detección de tipo y extracción
      indexar_fuente.py   # inserta una FuenteExtraida en Postgres (con dedup)
      adaptadores/
        pdf.py            # extractor PDF por URL
        html.py           # extractor HTML/web por URL (TLS sin verificar solo para hosts con cert roto: irj.es)
      fuentes/
        bdns.py           # conector BDNS: keyword o --por-region (barre todo La Rioja) -> candidatos_bdns.jsonl
        ader.py           # conector ADER: descubre paginas oficiales de ayudas ADER
        irj.py            # conector IRJ: ayudas a jovenes (carne, emancipacion, voluntariado, formacion)
        logrono.py        # conector Ayto Logrono: enumera+blacklist+clasifica ayudas municipales
    rag/
      buscar.py           # búsqueda semántica con pgvector + JOIN a fuentes
      chat.py             # perfilado de usuario + generación de respuesta LLM
    static/
      index.html          # interfaz web principal
      widget.html         # interfaz del widget embebible
      embed.js            # script de inserción del widget
    api.py                # servidor FastAPI + web + widget
    descargar.py          # CLI: descarga PDFs desde urls.txt
    evaluar_rag.py        # CLI: bateria de evaluacion RAG reproducible
    indexar.py            # CLI: trocea + embeddings + inserta todos los PDFs
    ingestar_fuentes.py   # CLI: extrae e indexa candidatos de candidatos.jsonl
  tests/
    test_bdns.py          # tests deterministas del conector BDNS (sin red/base)
    test_eval_cuantias.py # tests del matcher de cuantias del gate (sin red/LLM)
  frontend/               # front React/Vite (tarjetas + enlaces clicables)
    src/
      App.jsx             # estado del chat (mensajes, sesion, envio)
      api.js              # llamadas a /inicio y /chat
      components/
        Message.jsx       # burbuja: Markdown del bot + tarjetas
        AyudaCard.jsx     # tarjeta de ayuda con estado + boton a la fuente oficial
      styles.css          # estilos (tarjetas limpias)
    vite.config.js        # proxy /inicio y /chat -> :8000
    package.json
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
- LLM para respuestas: Ollama local, modelo `llama3.2:latest` (3B) por defecto — ~5,8× más
  rápido que `llama3.1:8b` en CPU y con la misma precisión en cuantías para esta tarea de
  extracción. Sin coste, sin API externa. (`llama3.1:8b` sigue disponible si se prioriza calidad.)

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

Hay dos frentes sobre el mismo backend FastAPI:

**Backend (siempre):**
```powershell
python src/api.py            # FastAPI en http://localhost:8000
```

**Front React/Vite (recomendado, el bonito con tarjetas y enlaces clicables):**
```powershell
cd frontend
npm install                 # solo la primera vez
npm run dev                 # Vite en http://localhost:5173
```
Abre **http://localhost:5173**. Vite hace de proxy de `/inicio` y `/chat` al backend
(`:8000`), así que necesitas los **dos procesos** arrancados a la vez (backend + `npm run dev`).
El front renderiza Markdown y pinta cada ayuda como tarjeta con su estado (abierta/cerrada)
y un botón a la convocatoria oficial (PDF o web). El `/chat` devuelve ahora también
`ayudas[]` (nombre, url_oficial, estado, fecha_fin, tipo_fuente) además del texto.

**Front legacy (vanilla, sin tarjetas):** sigue servido por FastAPI en
http://localhost:8000 (`src/static/index.html`). Útil como fallback o para el widget.

## Evaluar el RAG sin probar a mano

Se añadio `src/evaluar_rag.py` para automatizar el ciclo de evaluacion:
pregunta real -> recuperacion semantica -> re-ranking/deduplicado -> extractos clave -> respuesta
LLM opcional -> informe Markdown.

Uso rapido para revisar ranking, fuentes y extractos sin esperar a Ollama:

```powershell
python src/evaluar_rag.py --sin-llm
```

Uso completo, generando tambien respuestas con `llama3.1:8b`:

```powershell
python src/evaluar_rag.py
```

Iteracion sobre un caso concreto:

```powershell
python src/evaluar_rag.py --caso autonomo_larioja
python src/evaluar_rag.py --caso autonomo_larioja --sin-llm
```

Los informes se guardan en `data/evaluaciones/eval_YYYYMMDD_HHMMSS.md` y estan ignorados
por git. Casos iniciales incluidos:

- `autonomo_larioja`
- `pyme_maquinaria`
- `comercio_minorista`
- `digitalizacion_empresa`
- `emprender_logrono`
- `vivienda_joven`
- `carnet_conducir`

Instruccion para continuar en Claude Code: antes de tocar ranking, prompt o extractores, ejecutar
`python src/evaluar_rag.py --sin-llm`; despues de cada ajuste, repetir el mismo comando y comparar
el ultimo informe. Ejecutar el modo completo con LLM solo en los casos que ya tengan buen ranking.

Baseline local del 2026-06-12 con `python src/evaluar_rag.py --sin-llm` (k por defecto = 30):

- `autonomo_larioja`: 3/3 esperadas, correcto.
- `comercio_minorista`: 1/1 esperadas, correcto.
- `vivienda_joven`: 2/2 esperadas, correcto.
- `pyme_maquinaria`: 2/2 esperadas, correcto (antes 0/2; ver mejora de ranking abajo).
- `digitalizacion_empresa`: 1/2 esperadas; falta subir mejor `Digitalizacion e Industria`.
- `carnet_conducir`: 1/2 esperadas; caso de cobertura incompleta para IRJ/Gobierno La Rioja.
- `emprender_logrono`: 0/1 esperadas; falta conector local Logroño o ajustar fallback a ADER.

Mejora de ranking `pyme_maquinaria` (2026-06-12, sin reindexar la base):

- Diagnóstico: las dos ayudas correctas (`Inversiones por pymes` = INP, `Inversiones por
  autónomos y empresas` = MIN) existen como fichas HTML de ADER, pero el embedding las hundía
  a las posiciones 17 y 27 por distancia. La cabecera de navegación común a todas las fichas
  ADER ensucia el primer fragmento semántico, así que ayudas industriales genéricas
  (`Gran empresa industrial`, que además es para *grandes* empresas, no pymes) las superaban.
- Cambios en `src/rag/chat.py` (`puntuar_resultado`), conceptuales y gateados para no tocar
  los casos buenos:
  1. **Intención de inversión**: si la consulta menciona maquinaria/invertir/inversión/equipamiento,
     se prioriza la ayuda cuyo nombre es un programa de inversión (`Inversiones por...`).
  2. **Desajuste de tamaño**: si el ciudadano se identifica como pyme/autónomo, se penaliza
     la ayuda cuyo nombre es explícitamente para *gran empresa*.
- Cambio de recuperación: `k` por defecto de 20 → 30 en `evaluar_rag.py` y en `chat.py`. Con
  k=20 la ficha `Inversiones por pymes` (posición 27 por distancia) ni se recuperaba; el
  re-ranking solo reordena lo ya recuperado. Filosofía: recuperar más ancho, re-rankear preciso.
- Verificación: `python src/evaluar_rag.py --sin-llm` deja `pyme_maquinaria` en 2/2 sin romper
  `autonomo_larioja` (3/3), `comercio_minorista` (1/1) ni `vivienda_joven` (2/2).

### Iteración de precisión en cuantías y latencia (2026-06-12, sin reindexar)

Batería de 13 frases coloquiales con LLM (`llama3.1:8b`) auditando dónde se pierden los
importes: fuente real → extracto enviado al LLM → respuesta final. Hallazgos y arreglos:

- **Bug del extractor de importes en PDFs** (`extraer_detalles_clave` en `src/rag/chat.py`).
  El extractor estaba afinado para la estructura limpia de las fichas HTML de ADER. En PDFs
  de BDNS/BOE hacía match con el **índice interno** del documento (líneas tipo "...cuantía de
  la ayuda, plazo de concesión...", sin ninguna cifra) o con el **presupuesto/crédito total**
  ("importe total de seis millones de euros"), en lugar de la cuantía al ciudadano. Resultado:
  el Bono Alquiler Joven 2026 llegaba al LLM con **cero importes** pese a que el PDF dice
  "ayuda de 250 euros mensuales".
  - Arreglo: nuevo `_extraer_importe()` que para la sección Importe **exige una cifra real**
    (euros o %), **descarta líneas de presupuesto global** y prioriza por cercanía a términos
    de cuantía, devolviendo los 2 mejores bloques. Ahora el Bono Alquiler extrae
    "250 euros mensuales"; ADER (2.700 €, 20.000–1.500.000 €, 25%/35%) y carnet Extremadura
    (400/1.300/1.500 €) se mantienen.
- **Generaciones desbocadas del LLM**: dos frases tardaron 711 s y 1.112 s (>18 min) y
  acababan en respuesta vacía de fallback. Se añadió `num_predict=1024` y `num_ctx=4096` a
  las opciones de Ollama: acota la respuesta, evita runaways y baja latencia. Tras el cambio,
  esas mismas frases responden en ~100 s con sus importes.
- **Latencia (cuello de botella = generación LLM en CPU, no el retrieval)**:
  - retrieval: media 0,48 s (rápido).
  - `llama3.1:8b`: ~60–135 s por respuesta.
  - `llama3.2:latest` (3B): **~23 s** en la misma frase (~5,8× más rápido) y sigue citando
    "2.700 euros" correctamente. Candidato a modelo por defecto si se prioriza UX; pendiente
    de validar calidad en más casos antes de cambiarlo.
- **Pérdida de datos ANTES del embedding (calidad de PDF)**: algunos PDFs (emancipación
  juvenil, Becas Culturex) salen de `pypdf` con **palabras pegadas** o **sin símbolo de
  moneda**, o solo contienen el presupuesto global. Ahí no hay cuantía individual que extraer;
  el arreglo real es mejorar la extracción de texto (OCR/espaciado) y reindexar — tarea aparte.

### Adopción de llama3.2 (3B) + blindaje anti-invención (2026-06-12)

Tras validar latencia, se cambió el modelo por defecto a `llama3.2:latest`. Latencia/respuesta
en CPU bajó de ~60–135 s (8B) a ~6–18 s (3B). **Por qué es seguro escalar:** la latencia es
del MODELO, no de la base. El retrieval (lo único que crece con la BD) es ~0,5 s y se mantiene
con un índice HNSW cuando haya decenas de miles de fragmentos; el LLM solo ve las top-3 ayudas,
nunca la BD entera, así que su tiempo es constante aunque la BD crezca.

El 3B es más propenso a **inventar cifras** cuando el contexto de Importe llega vacío o con
ruido. Se detectó y corrigió:

- `_extraer_importe` (en `src/rag/chat.py`) exige ahora un **score mínimo** (cifra real +
  término de cuantía), descarta presupuesto global y emite hasta **3** tramos. Se corrigió una
  clave que no casaba (`"intensidad de ayuda"` no encontraba `"intensidad de la ayuda"`), que
  dejaba sin importe al `Cheque de innovación digitalización` y provocaba que el 3B inventara
  un `75%`.
- El prompt prohíbe explícitamente inventar/estimar importes: si no hay cifra textual, el campo
  Importe debe decir "No aparece en la fuente proporcionada".
- Resultado validado (6 frases con `llama3.2`): cuantías correctas y **literales** en Bono
  Alquiler (250 €, límite 600 €), Consolidación Autónomo (2.700/2.700/2.100 €), Inversiones
  pyme (70 €/m²), Comercio COC (25%/35%), Cheque digitalización (50%/70%) y carnet Extremadura
  (400/1.300/1.500 €). En las fuentes sin cuantía individual, el modelo **se abstiene** en vez
  de inventar (era el fallo crítico: antes inventaba un `85%` inexistente).

- Verificación end-to-end: ver `data/evaluaciones/` (informes ignorados por git). La batería
  de ranking `--sin-llm` sigue sin regresiones.

## Descubrir y añadir convocatorias desde la BDNS

La BDNS (Base de Datos Nacional de Subvenciones) tiene más de 600.000 convocatorias
accesibles por API pública. Este comando las busca, filtra por ámbito y categoría,
y genera un archivo JSONL listo para indexar:

```powershell
# Busca convocatorias estatal + La Rioja desde 2025, todas las categorías
python src/ingesta/fuentes/bdns.py --desde 2025-01-01 --ambito estatal larioja

# Sólo vivienda y carnet de La Rioja
python src/ingesta/fuentes/bdns.py --desde 2025-01-01 --ambito larioja --categorias vivienda carnet

# Barrido más útil para negocio/emprendimiento en La Rioja
python src/ingesta/fuentes/bdns.py --desde 2025-01-01 --ambito larioja --categorias empleo --max 100
```

Luego indexa los resultados (la deduplicación es automática):

```powershell
python src/ingestar_fuentes.py --candidatos data/candidatos_bdns.jsonl --indexar
```

El importador valida calidad mínima antes de indexar: procesa candidato a candidato, no aborta
toda la tanda si una fuente falla, y salta documentos con texto extraído insuficiente. Por defecto
exige 80 palabras; se puede ajustar:

```powershell
python src/ingestar_fuentes.py --candidatos data/candidatos_bdns.jsonl --indexar --min-palabras 120
```

Nota operativa: para barridos autonómicos, `--max 5` suele ser demasiado bajo. En pruebas,
La Rioja no aparecía en empleo/empresa con `--max 5`, pero sí aparecieron ayudas ADER y
emprendimiento con `--max 100`.

### Barrido REGION-FIRST de La Rioja (recomendado para cobertura completa)

El modo por keyword de arriba solo encuentra convocatorias cuya **descripción** contiene un
término buscado, así que se deja fuera el grueso de La Rioja. El modo `--por-region` le da la
vuelta: barre **todo** el universo riojano filtrando por región en la API (`regiones=[19,20]`,
ES23 + ES230) y reparte cada convocatoria en cubos: **descartada** (ruido administrativo:
nominativas, convenios, premios, procesos selectivos…), **inter-administrativa** (beneficiario =
otra administración, a municipios/EELL), **clasificada** (casa una categoría diana; se colapsan
ediciones anuales quedándose con la más reciente) o **sin clasificar** (al informe, no se tira).
Es la forma de "no dejarnos nada".

```powershell
# Barrido completo de La Rioja desde 2025 (genera JSONL + informe, NO indexa)
python src/ingesta/fuentes/bdns.py --por-region --desde 2025-01-01 --max 300

# Iterar la clasificación sin re-barrer la API (usa el universo cacheado):
python src/ingesta/fuentes/bdns.py --por-region --desde 2025-01-01 --usar-cache --max 300
```

`--max` limita cuántas clasificadas se **enriquecen** (piden detalle a la API); con prioridad de
hueco (dependencia, vivienda, movilidad, formación primero). `--cache` fija dónde se guarda el
universo crudo y `--usar-cache` lo recarga del disco (ojo: el cache ignora `--desde`/`--hasta`,
bórralo si cambias el rango). Produce dos ficheros (ignorados por git, se regeneran):

- `data/candidatos_bdns.jsonl`: ayudas clasificadas, deduplicadas y enriquecidas (importe/plazo/PDF).
- `data/revision_bdns_larioja.md`: informe legible con lo que NO entró en el JSONL — inter-administrativas,
  clasificadas fuera del tope `--max` y las **sin clasificar** (mayoría agrario/medioambiente/entidades,
  fuera del nicho), por si alguna merece rescatarse a mano a `data/candidatos.jsonl`.

Flujo recomendado: barrido → **revisar** el JSONL y el informe → indexar lo bueno. Para indexar solo
las categorías con hueco (lo que se hizo el 2026-06-13), filtra el JSONL a `dependencia/vivienda/
movilidad/formacion` antes de indexar y usa un bar de calidad estricto:

```powershell
python src/ingestar_fuentes.py --candidatos data/candidatos_bdns.jsonl --indexar --min-palabras 120
```

## Descubrir ayudas desde ADER

ADER es fuente oficial para ayudas de empresas, autonomos, comercio, emprendedores,
innovacion, financiacion e inversion en La Rioja. El conector ADER rastrea paginas oficiales
de `www.ader.es/ayudas/ayudas-por-areas/` y genera candidatos HTML:

```powershell
# Todas las areas ADER detectadas
python src/ingesta/fuentes/ader.py

# Solo areas concretas de negocio
python src/ingesta/fuentes/ader.py --areas autonomos emprendedores comercio
```

Primero conviene probar extraccion sin indexar:

```powershell
python src/ingestar_fuentes.py --candidatos data/candidatos_ader.jsonl
```

Y, si el texto extraido es correcto, indexar:

```powershell
python src/ingestar_fuentes.py --candidatos data/candidatos_ader.jsonl --indexar
```

Decision actual: ADER se guarda como `tipo_fuente="html"` porque sus fichas oficiales ya
incluyen plazo, normativa, beneficiarios, requisitos, tramite y enlaces a PDF/BDNS cuando
existen. Los PDFs enlazados pueden anadirse despues como enriquecimiento, pero no bloquean
la ingesta inicial. Cuando una ficha ADER usa un titulo generico, el conector conserva el
nombre mas concreto del enlace oficial que llevo hasta esa ficha. Tambien normaliza URLs
de ADER eliminando parametros de seguimiento para evitar duplicados de la misma ayuda, y
normaliza texto para detectar marcadores aunque la web use tildes o variantes.

Validacion local del 2026-06-12: el barrido completo de ADER genero 28 candidatos unicos en
`data/candidatos_ader.jsonl`; `ingestar_fuentes.py --min-palabras 80` acepto los 28, con
0 saltadas y 0 errores. Todavia no se han indexado en Postgres para no modificar la base
sin una decision explicita.

Tras indexar ADER, una prueba de chat encontro ayudas correctas pero respondio flojo en
plazo/importe porque solo se enviaban 600 caracteres del fragmento semantico al LLM. Se ajusto
`src/rag/buscar.py` para devolver `fuente_id` y recuperar `texto_extraido`, y `src/rag/chat.py`
para enriquecer cada ayuda con extractos clave del texto completo: beneficiarios, requisitos,
importe/subvencion, plazo y solicitud. Esos extractos se balancean por seccion para que una
seccion larga no tape datos de importe o plazo, y se evita tomar como contenido el indice interno
de las fichas ADER cuando solo enumera encabezados. Si un bloque ya usado coincide con otra seccion,
el extractor sigue buscando para no perder la seccion real de importes o plazos. En cada seccion
se priorizan encabezados fuertes antes que palabras sueltas como `euros`. Tambien se anadio
un re-ranking ligero para que consultas
con terminos concretos como `autonomo`, `pyme`, `comercio` o `emprendimiento` suban ayudas cuyo
nombre o texto contiene esos terminos.

Validacion posterior: con la consulta `Soy autonomo en La Rioja, que ayudas puedo pedir?`, el
ranking sube `Consolidacion del Trabajo Autonomo Riojano` al primer puesto y el LLM ya responde
con cuantias `2.700 euros` / `2.100 euros` y plazo `14 de mayo de 2026`.

Segunda validacion web: la respuesta ya daba bien la primera ayuda, pero repetia la misma ayuda
desde BDNS/PDF y metia `Incentivos regionales` antes de una ayuda mas directa para autonomos.
Se aumento la recuperacion inicial de `k=8` a `k=20` antes del re-ranking, se anadio deduplicado
conceptual entre ficha HTML y PDF oficial, y ante duplicados se prefiere la ficha HTML porque suele
ser mas clara para responder a ciudadanos.

Tercer ajuste: el extractor de detalles ahora incluye tambien una seccion `Cubre` para capturar
encabezados ADER como `Inversiones subvencionables`, `Gastos subvencionables`, `Gastos de
constitucion` o `Costes subvencionables`. El prompt del LLM tambien exige copiar literalmente
importes, fechas, porcentajes y rangos de edad para evitar reformular condiciones sensibles.
Ademas, `Importe` se extrae antes que `Cubre` para que porcentajes como `35%` no queden
clasificados como descripcion, y la respuesta final se normaliza para dejar el aviso legal
orientativo una sola vez.
Se mantiene el contexto por ayuda acotado para no disparar la latencia de Ollama local.
La seccion `Importe` recibe mas margen de caracteres que el resto porque truncar cuantias
provoca respuestas incompletas o numeros inventados.

## Descubrir ayudas desde IRJ (Instituto Riojano de la Juventud)

BDNS NO cubre bien las ayudas de juventud del IRJ (el carné de conducir ni aparece). El IRJ
publica su catálogo en `irj.es/subvenciones`, que enlaza a las fichas oficiales del trámite en
`larioja.org` (con beneficiarios/importe/plazo) y a páginas de contenido en `irj.es`. El conector
descubre las ayudas **a jóvenes** (carné, emancipación, voluntariado, monitor/director de tiempo
libre, carné joven, ayudas individuales) y descarta lo que va a ayuntamientos/asociaciones/consejos.

```powershell
python src/ingesta/fuentes/irj.py
python src/ingestar_fuentes.py --candidatos data/candidatos_irj.jsonl            # probar extraccion
python src/ingestar_fuentes.py --candidatos data/candidatos_irj.jsonl --indexar  # indexar
```

Nota técnica: `irj.es` tiene la **cadena TLS mal configurada** (no envía el certificado
intermedio), así que `requests` la rechaza. El adaptador HTML acepta TLS **sin verificar solo
para ese host** (lista cerrada `HOSTS_TLS_NO_VERIFICABLE` en `adaptadores/html.py`); el resto de
fuentes sigue con verificación normal. Las fichas oficiales del trámite viven en `larioja.org`,
que sí tiene TLS correcto. Validación local 2026-06-15: 9 candidatos, 0 errores; indexadas 8
(el carné `n=24664` ya estaba). Gate completo 5/5 PASS.

## Descubrir ayudas desde el Ayuntamiento de Logroño

BDNS solo trae de Logroño sus actos administrativos ("Acuerdo de Junta de Gobierno"); las ayudas
municipales reales (Chiquibecas de educación infantil, libros/material escolar, ayudas a mayores
de 85, Erasmus municipal, comercio…) solo están en `logrono.es/becas-y-subvenciones`. El conector
sigue el patrón region-first: enumera todas las fichas (listado paginado), descarta el ruido
(actos de ciclo de vida —adjudicación/concesión/pago—, ayudas a entidades/empresas, cooperación
internacional, concursos), filtra por **recencia** (≥2024), clasifica por categoría y deja el
resto en `data/revision_logrono.md`.

```powershell
python src/ingesta/fuentes/logrono.py
python src/ingestar_fuentes.py --candidatos data/candidatos_logrono.jsonl --indexar --min-palabras 120
```

Validación local 2026-06-15: 269 fichas → 76 descartadas (ruido) + histórico (<2024) → **25
clasificadas** indexadas, 0 errores. Gate completo 5/5 PASS. Limitación conocida: la misma ayuda
aparece a veces en varios años/fraseos que el dedup no colapsa del todo (revisar antes de escalar).

## Ingesta manual multi-fuente

Para añadir candidatos propios (PDFs por URL o páginas web), crea `data/candidatos.jsonl`:

```json
{"nombre":"Nombre de la ayuda","ambito":"larioja","categoria":"vivienda","url_oficial":"https://...","tipo_fuente":"auto","organismo":"Gobierno de La Rioja"}
```

`data/candidatos.jsonl`, `data/candidatos_*.jsonl` y `data/test_*.jsonl` son archivos
locales de trabajo y estan ignorados por git. El archivo versionado es
`data/candidatos.example.jsonl`.

```powershell
python src/ingestar_fuentes.py --candidatos data/candidatos.jsonl --indexar
```

Si sólo quieres comprobar extracción sin tocar Postgres:

```powershell
python src/ingestar_fuentes.py --candidatos data/candidatos.jsonl
```

---

## Decisiones clave

- **Embeddings locales** (no API): para aprender y evitar dependencias externas. A esta escala la calidad es suficiente.
- **Reindexado completo** en desarrollo: `TRUNCATE` + reinserción en cada ejecución, evita duplicados. La lógica de acumular solo lo nuevo va en la Fase 5.
- **Postgres + pgvector** en vez de BD vectorial dedicada: una sola herramienta para datos y vectores, más transferible.
- **Solapamiento de 50 palabras** entre fragmentos: evita cortar información clave justo en el límite.
- **Separación fuente/fragmento:** `fuentes` guarda el documento o página oficial; `fragmentos` guarda los trozos vectorizados. Así el RAG puede crecer a varios tipos de ingesta.
- **Candidatos antes que verdad:** una investigación externa solo propone URLs candidatas; el sistema debe descargar la fuente oficial y extraer texto real antes de indexar.
- **Validación mínima de extracción:** no se indexan fuentes que devuelven texto vacío o demasiado corto; esos casos necesitan OCR, otro documento o revisión manual.
- **Cobertura por términos:** BDNS no trae nuestras categorías internas; se buscan palabras clave por categoría. Para La Rioja, `empleo` cubre también negocio, autónomos, empresa, comercio, pymes y emprendimiento.
- **Fuentes no-PDF como extensión, no sustitución:** primero se mantiene el pipeline de PDFs y después se añade ingesta desde HTML/sedes/boletines con validación.

---

## Aviso

Una ayuda mal citada es peor que nada. El sistema siempre cita la fuente oficial y deja
claro que es orientativo, no asesoría legal.
