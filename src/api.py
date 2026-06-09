import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from buscar import buscar_filtrado
from chat import CATEGORIAS, COMUNIDADES, generar_respuesta, normalizar

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


def nueva_sesion() -> dict:
    return {"estado": "esperando_comunidad"}


@app.get("/inicio")
async def inicio(session_id: str | None = None):
    sid = session_id or str(uuid.uuid4())
    sessions[sid] = nueva_sesion()
    return {"session_id": sid, "respuesta": BIENVENIDA}


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
            descripcion, comunidad=perfil["comunidad"], categoria=perfil["categoria"], k=8
        )
        if not resultados and perfil["categoria"] != "todas":
            resultados = buscar_filtrado(
                descripcion, comunidad="todas", categoria=perfil["categoria"], k=8
            )
        if not resultados and perfil["comunidad"] != "todas":
            resultados = buscar_filtrado(
                descripcion, comunidad=perfil["comunidad"], categoria="todas", k=8
            )
        if not resultados:
            resultados = buscar_filtrado(descripcion, comunidad="todas", categoria="todas", k=8)

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
