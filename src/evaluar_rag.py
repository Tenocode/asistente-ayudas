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
    # Nombres de ayudas que deben aparecer en el top / respuesta.
    esperadas: tuple[str, ...] = ()
    # Cifras (importes, %) que la respuesta del LLM DEBE citar literalmente.
    # Solo se verifican en modo con LLM (sin --sin-llm). Es el "golden set":
    # congela las cuantias que ya validamos para que no se pierdan en silencio.
    cuantias: tuple[str, ...] = ()
    # bloqueante=True => si falla, la bateria sale en rojo (regresion real).
    # bloqueante=False => caso objetivo / hueco conocido: se mide pero no tumba.
    bloqueante: bool = True
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
        cuantias=("2.700", "2.100"),
        bloqueante=True,
        notas="Caso principal tras indexar ADER. Debe evitar duplicar ficha HTML + PDF.",
    ),
    CasoEval(
        id="pyme_maquinaria",
        pregunta="Tengo una pyme en La Rioja y quiero comprar maquinaria, que ayudas hay?",
        comunidad="larioja",
        comunidad_raw="La Rioja",
        categoria="empleo",
        esperadas=("Inversiones por pymes", "Inversiones por autónomos y empresas"),
        cuantias=("70 euros",),
        bloqueante=True,
    ),
    CasoEval(
        id="comercio_minorista",
        pregunta="Tengo un comercio minorista en La Rioja, hay subvenciones?",
        comunidad="larioja",
        comunidad_raw="La Rioja",
        categoria="empleo",
        esperadas=("COC - Plan para la Competitividad del Comercio Minorista",),
        cuantias=("25%", "35%"),
        bloqueante=True,
    ),
    CasoEval(
        id="vivienda_joven",
        pregunta="Tengo 24 anos y busco ayuda de alquiler o vivienda en La Rioja",
        comunidad="larioja",
        comunidad_raw="La Rioja",
        categoria="vivienda",
        esperadas=("Ayudas alquiler vivienda joven", "alquiler"),
        cuantias=("250 euros",),
        bloqueante=True,
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
        cuantias=("50%",),
        bloqueante=False,
        notas="Objetivo: falta subir 'Digitalizacion e Industria' al top.",
    ),
    CasoEval(
        id="emprender_logrono",
        pregunta="Quiero abrir un negocio en Logrono, que ayudas existen?",
        comunidad="larioja",
        comunidad_raw="La Rioja",
        categoria="empleo",
        esperadas=("PPA - Promoción de emprendedores",),
        bloqueante=False,
        notas="Objetivo: Logroño aun no tiene conector local; deberia apoyarse en ADER/La Rioja.",
    ),
    CasoEval(
        id="carnet_conducir",
        pregunta="Soy joven en La Rioja y quiero sacarme el carnet de conducir",
        comunidad="larioja",
        comunidad_raw="La Rioja",
        categoria="carnet",
        esperadas=("conducir", "La Rioja"),
        # La ficha oficial del IRJ no publica importe por persona (esta en las
        # bases del BOR); no exigimos cuantia para no forzar una invencion.
        cuantias=(),
        bloqueante=True,
        notas="Hueco cubierto con la ficha oficial del IRJ (cerrada; suele ser anual). "
        "Antes caia a Extremadura por falta de fuente riojana.",
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


def analizar_caso(
    caso: CasoEval,
    top_ayudas: list[dict],
    respuesta: str | None,
) -> tuple[bool, list[str], list[str]]:
    """
    Comprueba el caso contra su golden set y devuelve (paso, fallos, lineas).
    - paso: True si no hay fallos verificables.
    - fallos: lista de etiquetas de los checks que fallaron.
    - lineas: detalle legible para el informe.
    Los checks que requieren la respuesta del LLM (cuantias, aviso de cerrada)
    se marcan como "pendiente con LLM" en modo --sin-llm y NO cuentan como fallo.
    """
    texto_top = "\n".join(
        f"{a.get('nombre', '')} {a.get('url_oficial', '')}" for a in top_ayudas
    )
    texto_eval = f"{texto_top}\n{respuesta or ''}"
    resp_low = (respuesta or "").lower()

    fallos: list[str] = []
    lineas: list[str] = []

    # 1. Nombres de ayudas esperados (ranking/cobertura).
    if caso.esperadas:
        faltan = [e for e in caso.esperadas if not contiene(texto_eval, e)]
        lineas.append(
            f"nombres: {len(caso.esperadas) - len(faltan)}/{len(caso.esperadas)}"
            + (f" FALTAN {faltan}" if faltan else "")
        )
        if faltan:
            fallos.append("nombres")

    # 2. Cuantias obligatorias (golden set). Solo con LLM.
    if caso.cuantias:
        if respuesta is not None:
            faltan = [c for c in caso.cuantias if normalizar_ascii(c) not in normalizar_ascii(resp_low)]
            lineas.append(
                f"cuantias: {len(caso.cuantias) - len(faltan)}/{len(caso.cuantias)}"
                + (f" FALTAN {faltan}" if faltan else "")
            )
            if faltan:
                fallos.append("cuantias")
        else:
            lineas.append(f"cuantias: pendiente con LLM -> {list(caso.cuantias)}")

    # 3. Seguridad de vigencia: una cerrada en el top DEBE llevar aviso.
    cerradas = [a for a in top_ayudas if a.get("estado") == "cerrada"]
    if cerradas:
        if respuesta is not None:
            ok = "plazo cerrado" in resp_low
            lineas.append(f"aviso_cerradas: {'ok' if ok else 'FALTA'} ({len(cerradas)} en top)")
            if not ok:
                fallos.append("aviso_cerradas")
        else:
            lineas.append(f"aviso_cerradas: pendiente con LLM ({len(cerradas)} en top; pie determinista)")

    # 4. URLs oficiales presentes (sin URL no podemos citar la fuente).
    urls_ok = all(a.get("url_oficial") for a in top_ayudas)
    lineas.append(f"urls_oficiales_top: {'ok' if urls_ok else 'FALTAN'}")
    if not urls_ok:
        fallos.append("urls")

    # 5. Informativos (no bloquean).
    claves = [clave_conceptual_ayuda(a) for a in top_ayudas]
    lineas.append("duplicados_conceptuales_top: " + ("no" if len(claves) == len(set(claves)) else "si"))
    lineas.append(f"top_estados: {[a.get('estado') for a in top_ayudas]}")

    return (len(fallos) == 0), fallos, lineas


def fila_resultado(resultado: dict, pregunta: str) -> str:
    score = puntuar_resultado(resultado, pregunta)
    return (
        f"- `{resultado['distancia']}` score `{score:.4f}` "
        f"`{resultado.get('tipo_fuente')}` `{resultado.get('estado')}` "
        f"frag `{resultado.get('numero_fragmento')}` "
        f"**{resultado['nombre']}**  \n"
        f"  {resultado.get('url_oficial') or 'sin URL'}"
    )


def render_caso(
    caso: CasoEval,
    k: int,
    incluir_llm: bool,
) -> tuple[str, bool, list[str]]:
    perfil = perfil_desde_caso(caso)
    resultados, modo = buscar_con_fallback(perfil, k)
    top_ayudas = seleccionar_top_ayudas(perfil, resultados, limite=3)
    textos_fuentes = obtener_textos_fuentes(
        [a["fuente_id"] for a in top_ayudas if a.get("fuente_id")]
    )
    respuesta = generar_respuesta(perfil, resultados) if incluir_llm else None
    paso, fallos, lineas = analizar_caso(caso, top_ayudas, respuesta)

    tipo = "bloqueante" if caso.bloqueante else "objetivo"
    if paso:
        veredicto = "PASS"
    else:
        veredicto = "FAIL" if caso.bloqueante else "FAIL (objetivo, no bloquea)"

    partes = [
        f"## {caso.id} - {veredicto}",
        "",
        f"**Pregunta:** {caso.pregunta}",
        f"**Filtro:** comunidad=`{caso.comunidad}` categoria=`{caso.categoria}` ({tipo})",
        f"**Modo busqueda:** `{modo}`",
    ]
    if caso.notas:
        partes.append(f"**Notas:** {caso.notas}")
    partes.extend(["", "### Checks", ""])
    partes.extend(f"- {c}" for c in lineas)

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

    return "\n".join(partes), paso, fallos


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
    parser.add_argument("--k", type=int, default=30, help="Fragmentos iniciales por busqueda.")
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
    resultados_casos = []  # (caso, paso, fallos)
    for caso in casos:
        print(f"[eval] {caso.id}...")
        seccion, paso, fallos = render_caso(caso, args.k, incluir_llm)
        secciones.append(seccion)
        resultados_casos.append((caso, paso, fallos))

    informe = "\n".join(cabecera + secciones) + "\n"
    args.salida.write_text(informe, encoding="utf-8")

    # Veredicto: solo los casos bloqueantes que fallan tumban la bateria.
    bloqueantes = [(c, p, f) for c, p, f in resultados_casos if c.bloqueante]
    objetivos = [(c, p, f) for c, p, f in resultados_casos if not c.bloqueante]
    fallos_bloqueantes = [c.id for c, p, _ in bloqueantes if not p]

    print("\n=== Resumen ===")
    print("Bloqueantes (regresion si fallan):")
    for c, p, f in bloqueantes:
        marca = "PASS" if p else "FAIL"
        extra = "" if p else f" -> {f}"
        print(f"  [{marca}] {c.id}{extra}")
    if objetivos:
        print("Objetivos (huecos conocidos, no bloquean):")
        for c, p, f in objetivos:
            marca = "PASS" if p else "pendiente"
            extra = "" if p else f" -> {f}"
            print(f"  [{marca}] {c.id}{extra}")

    print(f"\nInforme escrito en: {args.salida}")

    if fallos_bloqueantes:
        print(f"\nRESULTADO: ROJO — fallan {len(fallos_bloqueantes)} bloqueantes: {fallos_bloqueantes}")
        raise SystemExit(1)
    pendientes = sum(1 for c, p, _ in objetivos if not p)
    print(
        f"\nRESULTADO: VERDE — {len(bloqueantes)}/{len(bloqueantes)} bloqueantes PASS"
        + (f" · {pendientes} objetivos pendientes" if pendientes else "")
    )


if __name__ == "__main__":
    main()
