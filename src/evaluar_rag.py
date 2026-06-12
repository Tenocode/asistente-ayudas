import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import psycopg2

from db.init_db import DSN
from rag.buscar import buscar_filtrado, obtener_textos_fuentes
from rag.chat import (
    clave_conceptual_ayuda,
    extraer_detalles_clave,
    generar_respuesta,
    normalizar_ascii,
    puntuar_resultado,
    seleccionar_top_ayudas,
)


@dataclass(frozen=True)
class CasoEval:
    id: str
    pregunta: str
    comunidad: str
    comunidad_raw: str
    categoria: str
    esperadas: tuple[str, ...] = ()
    notas: str = ""


CASOS: tuple[CasoEval, ...] = (
    CasoEval(
        id="autonomo_larioja",
        pregunta="Soy autonomo en La Rioja, que ayudas puedo pedir?",
        comunidad="larioja",
        comunidad_raw="La Rioja",
        categoria="empleo",
        esperadas=(
            "Consolidación del Trabajo Autónomo Riojano",
            "Inversiones por autónomos y empresas",
            "PPA - Promoción de emprendedores",
        ),
        notas="Caso principal tras indexar ADER. Debe evitar duplicar ficha HTML + PDF.",
    ),
    CasoEval(
        id="pyme_maquinaria",
        pregunta="Tengo una pyme en La Rioja y quiero comprar maquinaria, que ayudas hay?",
        comunidad="larioja",
        comunidad_raw="La Rioja",
        categoria="empleo",
        esperadas=("Inversiones por pymes", "Inversiones por autónomos y empresas"),
    ),
    CasoEval(
        id="comercio_minorista",
        pregunta="Tengo un comercio minorista en La Rioja, hay subvenciones?",
        comunidad="larioja",
        comunidad_raw="La Rioja",
        categoria="empleo",
        esperadas=("COC - Plan para la Competitividad del Comercio Minorista",),
    ),
    CasoEval(
        id="digitalizacion_empresa",
        pregunta="Busco ayudas para digitalizar mi empresa en La Rioja",
        comunidad="larioja",
        comunidad_raw="La Rioja",
        categoria="empleo",
        esperadas=(
            "Digitalización e Industria",
            "Cheque de innovación digitalización",
        ),
    ),
    CasoEval(
        id="emprender_logrono",
        pregunta="Quiero abrir un negocio en Logrono, que ayudas existen?",
        comunidad="larioja",
        comunidad_raw="La Rioja",
        categoria="empleo",
        esperadas=("PPA - Promoción de emprendedores",),
        notas="Logroño aun no tiene conector local; deberia apoyarse en ADER/La Rioja.",
    ),
    CasoEval(
        id="vivienda_joven",
        pregunta="Tengo 24 anos y busco ayuda de alquiler o vivienda en La Rioja",
        comunidad="larioja",
        comunidad_raw="La Rioja",
        categoria="vivienda",
        esperadas=("Ayudas alquiler vivienda joven", "alquiler"),
    ),
    CasoEval(
        id="carnet_conducir",
        pregunta="Soy joven en La Rioja y quiero sacarme el carnet de conducir",
        comunidad="larioja",
        comunidad_raw="La Rioja",
        categoria="carnet",
        esperadas=("carnet", "conducir"),
        notas="Caso para detectar huecos de cobertura IRJ/Gobierno La Rioja.",
    ),
)


def perfil_desde_caso(caso: CasoEval) -> dict:
    return {
        "comunidad": caso.comunidad,
        "comunidad_raw": caso.comunidad_raw,
        "categoria": caso.categoria,
        "descripcion": caso.pregunta,
    }


def buscar_con_fallback(perfil: dict, k: int) -> tuple[list[dict], str]:
    resultados = buscar_filtrado(
        perfil["descripcion"],
        comunidad=perfil["comunidad"],
        categoria=perfil["categoria"],
        k=k,
    )
    if resultados:
        return resultados, "comunidad+categoria"

    if perfil["categoria"] != "todas":
        resultados = buscar_filtrado(
            perfil["descripcion"],
            comunidad="todas",
            categoria=perfil["categoria"],
            k=k,
        )
        if resultados:
            return resultados, "todas+categoria"

    if perfil["comunidad"] != "todas":
        resultados = buscar_filtrado(
            perfil["descripcion"],
            comunidad=perfil["comunidad"],
            categoria="todas",
            k=k,
        )
        if resultados:
            return resultados, "comunidad+todas"

    return buscar_filtrado(
        perfil["descripcion"],
        comunidad="todas",
        categoria="todas",
        k=k,
    ), "todas+todas"


def resumen_db() -> str:
    with psycopg2.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tipo_fuente, count(*) FROM fuentes GROUP BY tipo_fuente ORDER BY tipo_fuente"
            )
            fuentes = cur.fetchall()
            cur.execute("SELECT count(*) FROM fragmentos")
            fragmentos = cur.fetchone()[0]

    return f"fuentes_por_tipo={fuentes}; fragmentos={fragmentos}"


def contiene(texto: str, patron: str) -> bool:
    return normalizar_ascii(patron) in normalizar_ascii(texto)


def checks_basicos(
    caso: CasoEval,
    top_ayudas: list[dict],
    respuesta: str | None,
) -> list[str]:
    texto_top = "\n".join(
        f"{a.get('nombre', '')} {a.get('url_oficial', '')}" for a in top_ayudas
    )
    texto_eval = f"{texto_top}\n{respuesta or ''}"

    checks = []
    if caso.esperadas:
        encontradas = [e for e in caso.esperadas if contiene(texto_eval, e)]
        checks.append(f"esperadas: {len(encontradas)}/{len(caso.esperadas)} -> {encontradas}")

    urls_ok = all(a.get("url_oficial") for a in top_ayudas)
    checks.append(f"urls_oficiales_top: {'ok' if urls_ok else 'faltan'}")

    claves = [clave_conceptual_ayuda(a) for a in top_ayudas]
    checks.append(
        "duplicados_conceptuales_top: "
        + ("no" if len(claves) == len(set(claves)) else "si")
    )

    if respuesta:
        tiene_importe = bool(re.search(r"\b(euros?|%|importe|cuantia|cuantía)\b", respuesta, re.I))
        tiene_plazo = bool(re.search(r"\b(plazo|hasta|solicitudes|20\d{2})\b", respuesta, re.I))
        checks.append(f"respuesta_menciona_importe: {'si' if tiene_importe else 'no'}")
        checks.append(f"respuesta_menciona_plazo: {'si' if tiene_plazo else 'no'}")
        checks.append(
            "aviso_orientativo: "
            + str(respuesta.count("Información orientativa. Consulta la convocatoria oficial antes de solicitar."))
        )

    return checks


def fila_resultado(resultado: dict, pregunta: str) -> str:
    score = puntuar_resultado(resultado, pregunta)
    return (
        f"- `{resultado['distancia']}` score `{score:.4f}` "
        f"`{resultado.get('tipo_fuente')}` frag `{resultado.get('numero_fragmento')}` "
        f"**{resultado['nombre']}**  \n"
        f"  {resultado.get('url_oficial') or 'sin URL'}"
    )


def render_caso(
    caso: CasoEval,
    k: int,
    incluir_llm: bool,
) -> tuple[str, list[str]]:
    perfil = perfil_desde_caso(caso)
    resultados, modo = buscar_con_fallback(perfil, k)
    top_ayudas = seleccionar_top_ayudas(perfil, resultados, limite=3)
    textos_fuentes = obtener_textos_fuentes(
        [a["fuente_id"] for a in top_ayudas if a.get("fuente_id")]
    )
    respuesta = generar_respuesta(perfil, resultados) if incluir_llm else None
    checks = checks_basicos(caso, top_ayudas, respuesta)

    partes = [
        f"## {caso.id}",
        "",
        f"**Pregunta:** {caso.pregunta}",
        f"**Filtro:** comunidad=`{caso.comunidad}` categoria=`{caso.categoria}`",
        f"**Modo busqueda:** `{modo}`",
    ]
    if caso.notas:
        partes.append(f"**Notas:** {caso.notas}")
    partes.extend(["", "### Checks", ""])
    partes.extend(f"- {c}" for c in checks)

    partes.extend(["", "### Top bruto", ""])
    for resultado in resultados[: min(k, 8)]:
        partes.append(fila_resultado(resultado, caso.pregunta))

    partes.extend(["", "### Top final", ""])
    for i, ayuda in enumerate(top_ayudas, start=1):
        detalles = extraer_detalles_clave(
            textos_fuentes.get(ayuda.get("fuente_id"), ayuda.get("texto", ""))
        )
        partes.extend(
            [
                f"{i}. **{ayuda['nombre']}**",
                f"   - tipo: `{ayuda.get('tipo_fuente')}`",
                f"   - distancia: `{ayuda.get('distancia')}`",
                f"   - score: `{puntuar_resultado(ayuda, caso.pregunta):.4f}`",
                f"   - url: {ayuda.get('url_oficial') or 'sin URL'}",
                "   - detalles:",
                "",
                "```text",
                detalles[:1600],
                "```",
                "",
            ]
        )

    partes.extend(["", "### Respuesta LLM", ""])
    if respuesta:
        partes.append(respuesta)
    else:
        partes.append("_Omitida con `--sin-llm`._")

    return "\n".join(partes), checks


def elegir_casos(ids: list[str] | None, max_casos: int | None) -> list[CasoEval]:
    casos = list(CASOS)
    if ids:
        solicitados = set(ids)
        casos = [c for c in casos if c.id in solicitados]
        faltan = solicitados - {c.id for c in casos}
        if faltan:
            raise SystemExit(f"Casos no encontrados: {', '.join(sorted(faltan))}")
    if max_casos:
        casos = casos[:max_casos]
    return casos


def main() -> None:
    ahora = datetime.now().strftime("%Y%m%d_%H%M%S")
    parser = argparse.ArgumentParser(
        description="Ejecuta una bateria reproducible de evaluacion RAG."
    )
    parser.add_argument("--sin-llm", action="store_true", help="Evalua ranking/extractos sin llamar a Ollama.")
    parser.add_argument("--k", type=int, default=20, help="Fragmentos iniciales por busqueda.")
    parser.add_argument("--caso", nargs="+", help="IDs concretos de casos a ejecutar.")
    parser.add_argument("--max-casos", type=int, help="Limita el numero de casos.")
    parser.add_argument(
        "--salida",
        type=Path,
        default=Path(__file__).parent.parent / "data" / "evaluaciones" / f"eval_{ahora}.md",
        help="Ruta del informe Markdown.",
    )
    args = parser.parse_args()

    casos = elegir_casos(args.caso, args.max_casos)
    args.salida.parent.mkdir(parents=True, exist_ok=True)

    incluir_llm = not args.sin_llm
    cabecera = [
        "# Evaluacion RAG",
        "",
        f"- fecha: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- casos: `{len(casos)}`",
        f"- k: `{args.k}`",
        f"- llm: `{'si' if incluir_llm else 'no'}`",
        f"- db: `{resumen_db()}`",
        "",
    ]

    secciones = []
    resumen_terminal = []
    for caso in casos:
        print(f"[eval] {caso.id}...")
        seccion, checks = render_caso(caso, args.k, incluir_llm)
        secciones.append(seccion)
        resumen_terminal.append(f"- {caso.id}: " + " | ".join(checks[:3]))

    informe = "\n".join(cabecera + secciones) + "\n"
    args.salida.write_text(informe, encoding="utf-8")

    print("\nResumen:")
    for linea in resumen_terminal:
        print(linea)
    print(f"\nInforme escrito en: {args.salida}")


if __name__ == "__main__":
    main()
