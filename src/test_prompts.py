"""
Script de iteración de prompts. Lo ejecuto yo para probar y ajustar sin que
el usuario tenga que copiar y pegar respuestas manualmente.
"""
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))

from buscar import buscar_filtrado
from chat import generar_respuesta

CASOS = [
    {
        "nombre": "formacion madrid",
        "perfil": {
            "comunidad": "madrid",
            "comunidad_raw": "madrid",
            "categoria": "formacion",
            "descripcion": "tengo 23 y estudio en la universidad",
        },
    },
    {
        "nombre": "carnet larioja",
        "perfil": {
            "comunidad": "larioja",
            "comunidad_raw": "la rioja",
            "categoria": "carnet",
            "descripcion": "tengo 23 años y quiero sacarme el carnet b",
        },
    },
    {
        "nombre": "empleo larioja",
        "perfil": {
            "comunidad": "larioja",
            "comunidad_raw": "la rioja",
            "categoria": "empleo",
            "descripcion": "tengo 23 años",
        },
    },
    # Casos adicionales
    {
        "nombre": "vivienda larioja",
        "perfil": {
            "comunidad": "larioja",
            "comunidad_raw": "la rioja",
            "categoria": "vivienda",
            "descripcion": "quiero alquilar un piso, tengo 24 años",
        },
    },
    {
        "nombre": "empleo estatal joven",
        "perfil": {
            "comunidad": "todas",
            "comunidad_raw": "España",
            "categoria": "empleo",
            "descripcion": "soy joven recién graduado buscando primer empleo",
        },
    },
]

SEPARADOR = "=" * 70


def buscar_con_fallback(perfil: dict) -> list[dict]:
    r = buscar_filtrado(perfil["descripcion"], comunidad=perfil["comunidad"], categoria=perfil["categoria"], k=8)
    if not r and perfil["categoria"] != "todas":
        r = buscar_filtrado(perfil["descripcion"], comunidad="todas", categoria=perfil["categoria"], k=8)
    if not r and perfil["comunidad"] != "todas":
        r = buscar_filtrado(perfil["descripcion"], comunidad=perfil["comunidad"], categoria="todas", k=8)
    if not r:
        r = buscar_filtrado(perfil["descripcion"], comunidad="todas", categoria="todas", k=8)
    return r


def evaluar(respuesta: str, caso: dict) -> list[str]:
    problemas = []
    if len(respuesta) < 80:
        problemas.append("AVISO: respuesta muy corta")
    sospechosos = ["imagina", "podría haber", "probablemente", "suele haber", "generalmente", "es posible que existan"]
    for s in sospechosos:
        if s in respuesta.lower():
            problemas.append(f"AVISO: lenguaje especulativo: '{s}'")
    if "Información orientativa" not in respuesta and "No he encontrado" not in respuesta:
        problemas.append("AVISO: falta el disclaimer final")
    return problemas


if __name__ == "__main__":
    resultados_resumen = []

    for i, caso in enumerate(CASOS):
        if i > 0:
            print(f"\n(esperando 15s para que la GPU libere memoria...)")
            time.sleep(15)

        print(f"\n{SEPARADOR}")
        print(f"CASO {i+1}/{len(CASOS)}: {caso['nombre'].upper()}")
        print(SEPARADOR)

        perfil = caso["perfil"]
        resultados = buscar_con_fallback(perfil)
        print(f"Fragmentos recuperados: {len(resultados)}")
        for j, r in enumerate(resultados, 1):
            print(f"  [{j}] {r['nombre']} ({r['ambito']}, {r['categoria']}) dist={r['distancia']}")

        print("\n--- RESPUESTA DEL MODELO ---\n")
        respuesta = generar_respuesta(perfil, resultados)
        print(respuesta)

        problemas = evaluar(respuesta, caso)
        estado = "OK" if not problemas else "REVISAR"
        if problemas:
            print("\n" + "\n".join(problemas))
        else:
            print("\nOK: sin problemas detectados")

        resultados_resumen.append((caso["nombre"], estado))

    print(f"\n{SEPARADOR}")
    print("RESUMEN")
    print(SEPARADOR)
    for nombre, estado in resultados_resumen:
        print(f"  {estado:8s}  {nombre}")
    print(SEPARADOR)
