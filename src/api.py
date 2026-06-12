import html
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from rag.buscar import buscar_filtrado
from rag.chat import CATEGORIAS, COMUNIDADES, generar_respuesta, normalizar

app = FastAPI(title="Asistente Ayudas")

# Sesiones en memoria: session_id -> estado del flujo
sessions: dict[str, dict] = {}

BIENVENIDA = (
    "Hola, soy tu asistente de ayudas públicas.\n\n"
    "Voy a hacerte tres preguntas rápidas para encontrar las ayudas que mejor se ajusten a ti.\n\n"
    "¿En qué comunidad autónoma vives?\n"
    "(ej: La Rioja, Murcia, Extremadura, Madrid, Andalucía...)"
)


class ChatRequest(BaseModel):
    session_id: str | None = None
    mensaje: str


class ChatResponse(BaseModel):
    session_id: str
    respuesta: str


def nueva_sesion(
    comunidad: str | None = None,
    comunidad_raw: str | None = None,
    categoria: str | None = None,
) -> dict:
    sesion = {"estado": "esperando_comunidad"}
    if comunidad:
        sesion["comunidad"] = comunidad
        sesion["comunidad_raw"] = comunidad_raw or comunidad
        sesion["estado"] = "esperando_categoria"
    if comunidad and categoria:
        sesion["categoria"] = categoria
        sesion["estado"] = "esperando_descripcion"
    return sesion


def bienvenida_para_sesion(sesion: dict, entidad: str | None = None) -> str:
    nombre = entidad.strip() if entidad else "tu asistente de ayudas publicas"
    encabezado = f"Hola, soy {nombre}.\n\n"

    if sesion["estado"] == "esperando_categoria":
        return encabezado + (
            "Ya tengo tu comunidad. Dime que tipo de ayuda estas buscando:\n\n"
            "- Vivienda / alquiler\n"
            "- Carnet de conducir\n"
            "- Formacion / becas\n"
            "- Empleo / emprendimiento\n"
            "- Movilidad / extranjero\n"
            "- Cultura\n"
            "- Dependencia / discapacidad"
        )
    if sesion["estado"] == "esperando_descripcion":
        return encabezado + (
            "Ya tengo comunidad y tipo de ayuda. Cuentame tu situacion concreta:\n"
            "(ej: tengo 22 anos y quiero sacarme el carnet B)"
        )
    return encabezado + (
        "Voy a hacerte tres preguntas rapidas para encontrar las ayudas que mejor se ajusten a ti.\n\n"
        "En que comunidad autonoma vives?\n"
        "(ej: La Rioja, Murcia, Extremadura, Madrid, Andalucia...)"
    )


@app.get("/inicio")
async def inicio(
    session_id: str | None = None,
    entidad: str | None = None,
    comunidad: str | None = None,
    categoria: str | None = None,
):
    sid = session_id or str(uuid.uuid4())
    comunidad_norm = normalizar(comunidad, COMUNIDADES) if comunidad else None
    categoria_norm = normalizar(categoria, CATEGORIAS) if categoria else None
    sessions[sid] = nueva_sesion(
        comunidad=comunidad_norm,
        comunidad_raw=comunidad,
        categoria=categoria_norm,
    )
    return {"session_id": sid, "respuesta": bienvenida_para_sesion(sessions[sid], entidad)}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    sid = req.session_id or str(uuid.uuid4())
    if sid not in sessions:
        sessions[sid] = nueva_sesion()

    sesion = sessions[sid]
    mensaje = req.mensaje.strip()
    estado = sesion["estado"]

    if estado == "esperando_comunidad":
        comunidad = normalizar(mensaje, COMUNIDADES)
        if not comunidad:
            respuesta = (
                "No he reconocido esa comunidad. Prueba con:\n"
                "La Rioja, Murcia, Extremadura, Madrid, Andalucía, Cataluña, Valencia, "
                "País Vasco, Galicia, Aragón, Canarias..."
            )
        else:
            sesion["comunidad"] = comunidad
            sesion["comunidad_raw"] = mensaje
            sesion["estado"] = "esperando_categoria"
            respuesta = (
                f"Perfecto, {mensaje}.\n\n"
                "¿Qué tipo de ayuda estás buscando?\n\n"
                "- Vivienda / alquiler\n"
                "- Carnet de conducir\n"
                "- Formación / becas\n"
                "- Empleo / emprendimiento\n"
                "- Movilidad / extranjero\n"
                "- Cultura\n"
                "- Dependencia / discapacidad"
            )

    elif estado == "esperando_categoria":
        categoria = normalizar(mensaje, CATEGORIAS)
        if not categoria:
            respuesta = (
                "No he reconocido ese tipo. Prueba con:\n"
                "vivienda, alquiler, carnet, formación, becas, trabajo, "
                "emprendimiento, movilidad, cultura, dependencia..."
            )
        else:
            sesion["categoria"] = categoria
            sesion["estado"] = "esperando_descripcion"
            respuesta = (
                "Entendido. Cuéntame un poco más sobre tu situación concreta:\n"
                "(ej: tengo 22 años y quiero sacarme el carnet B)"
            )

    elif estado == "esperando_descripcion":
        descripcion = mensaje or sesion.get("categoria", "")
        sesion["descripcion"] = descripcion
        sesion["estado"] = "fin"

        perfil = {
            "comunidad": sesion["comunidad"],
            "comunidad_raw": sesion["comunidad_raw"],
            "categoria": sesion["categoria"],
            "descripcion": descripcion,
        }

        resultados = buscar_filtrado(
            descripcion, comunidad=perfil["comunidad"], categoria=perfil["categoria"], k=20
        )
        if not resultados and perfil["categoria"] != "todas":
            resultados = buscar_filtrado(
                descripcion, comunidad="todas", categoria=perfil["categoria"], k=20
            )
        if not resultados and perfil["comunidad"] != "todas":
            resultados = buscar_filtrado(
                descripcion, comunidad=perfil["comunidad"], categoria="todas", k=20
            )
        if not resultados:
            resultados = buscar_filtrado(descripcion, comunidad="todas", categoria="todas", k=20)

        respuesta_llm = generar_respuesta(perfil, resultados)
        respuesta = respuesta_llm + "\n\n---\n¿Quieres buscar otro tipo de ayuda? Escribe 'sí' para empezar de nuevo."

    elif estado == "fin":
        if mensaje.lower() in ("si", "sí", "s", "yes"):
            sessions[sid] = nueva_sesion()
            respuesta = "¡Claro! ¿En qué comunidad autónoma vives?"
        else:
            sessions.pop(sid, None)
            respuesta = "¡Hasta luego! Si necesitas más información, vuelve cuando quieras."

    else:
        sessions.pop(sid, None)
        respuesta = "Ha ocurrido un error con la sesión. Recarga la página para empezar."

    return ChatResponse(session_id=sid, respuesta=respuesta)


_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse(str(_static_dir / "index.html"))


@app.get("/widget", response_class=HTMLResponse)
async def widget():
    return FileResponse(str(_static_dir / "widget.html"))


@app.get("/embed.js")
async def embed_js():
    js = (_static_dir / "embed.js").read_text(encoding="utf-8")
    return Response(js, media_type="application/javascript; charset=utf-8")


@app.get("/codigo-widget", response_class=HTMLResponse)
async def codigo_widget(entidad: str = "Ayuntamiento demo", comunidad: str = "larioja"):
    entidad_attr = html.escape(entidad, quote=True)
    comunidad_attr = html.escape(comunidad, quote=True)
    snippet = f"""<div id="asistente-ayudas-widget"></div>
<script
  src="/embed.js"
  data-entidad="{entidad_attr}"
  data-comunidad="{comunidad_attr}"
  data-modo="inline">
</script>"""
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<title>Codigo widget</title>"
        "<body style='font-family:system-ui;max-width:900px;margin:40px auto;padding:0 20px'>"
        "<h1>Codigo para insertar el widget</h1>"
        "<p>Copia este bloque en la web del ayuntamiento o asociacion.</p>"
        f"<pre style='white-space:pre-wrap;background:#f5f5f5;padding:16px;border-radius:8px'>{html.escape(snippet)}</pre>"
        "<h2>Vista previa</h2>"
        f"{snippet}"
        f"<script type='application/json' id='widget-config'>{json.dumps({'entidad': entidad, 'comunidad': comunidad})}</script>"
        "</body>"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
