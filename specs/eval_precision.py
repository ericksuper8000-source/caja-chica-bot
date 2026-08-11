#!/usr/bin/env python3
"""
EVAL DE PRECISION DEL CONJUNTO DORADO - Fase 5.5.2
==================================================
Que hace: califica al bot (Whisper + GPT-4o-mini) contra los 29 audios reales del
conjunto dorado y reporta el % de acierto en monto, categoria y tipo.

Como se ejecuta (Docker-first, dentro del contenedor app del repo original):
    ffmpeg debe estar instalado en el contenedor (una vez por contenedor):
        docker compose exec app sh -c "apt-get update -qq && apt-get install -y -qq ffmpeg"
    Luego:
        docker compose exec -w /code app python specs/eval_precision.py

Entrada:
    - specs/golden_set.json  (la hoja de respuestas del examen)
    - specs/golden_audio/    (los audios reales, formato .m4a)

Salida:
    - Tabla caso por caso con aciertos/fallos
    - % final de acierto en monto (meta: >=95% antes de pilotos)

Casos especiales:
    - esperado = null            (casos 21, 22: sin monto): el bot debe NO crear transaccion.
    - esperado = PEDIR_ACLARACION (caso 27: dos flujos en un audio): el bot debe pedir aclaracion.
    - esperado con "accion"      (casos de correccion 31+: el bot debe detectar 'corregir').
      Estos casos NO cuentan en el % de monto (no hay monto esperado en algunos); se reportan
      por separado como 'comportamiento' pero SI se listan en la tabla para revisar a mano.
"""

import asyncio
import json
import os
import subprocess
import sys
import tempfile

from services.openai_service import parse_financial_text, transcribir_audio_whisper

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GOLDEN_SET_PATH = os.path.join(BASE_DIR, "golden_set.json")
GOLDEN_AUDIO_DIR = os.path.join(BASE_DIR, "golden_audio")


def convertir_a_wav(ruta_audio: str) -> str:
    """Convierte .m4a (codec AAC) a WAV 16 kHz mono que Whisper SI acepta."""
    wav_path = os.path.join(
        tempfile.gettempdir(), os.path.splitext(os.path.basename(ruta_audio))[0] + ".wav"
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            ruta_audio,
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            wav_path,
        ],
        check=True,
        capture_output=True,
    )
    return wav_path


def comparar(obtenido: dict | None, esperado: dict) -> dict[str, str | None]:
    """Compara lo que extrajo el bot contra la respuesta correcta."""
    resultado: dict[str, str | None] = {
        "accion": None,
        "monto": None,
        "categoria": None,
        "tipo": None,
    }
    if not obtenido:
        return resultado
    if "accion" in esperado:
        resultado["accion"] = "OK" if obtenido.get("accion") == esperado["accion"] else "FALLO"
    if "monto" in esperado:
        resultado["monto"] = "OK" if obtenido.get("monto") == esperado["monto"] else "FALLO"
    if "categoria" in esperado:
        resultado["categoria"] = (
            "OK" if obtenido.get("categoria") == esperado["categoria"] else "FALLO"
        )
    if "tipo_movimiento" in esperado:
        resultado["tipo"] = (
            "OK" if obtenido.get("tipo_movimiento") == esperado["tipo_movimiento"] else "FALLO"
        )
    return resultado


async def evaluar_caso(caso: dict) -> dict:
    """Evalua un caso: convierte, transcribe, extrae y compara."""
    audio_name = caso.get("audio")
    ruta_audio = os.path.join(GOLDEN_AUDIO_DIR, audio_name)
    if not os.path.exists(ruta_audio):
        return {"id": caso["id"], "error": f"audio no encontrado: {audio_name}"}

    wav_path = convertir_a_wav(ruta_audio)
    transcripcion = await transcribir_audio_whisper(wav_path)
    if not transcripcion:
        return {
            "id": caso["id"],
            "transcripcion": None,
            "obtenido": None,
            "esperado": caso.get("esperado"),
            "objetivo": caso.get("objetivo", ""),
            "resultado": comparar(None, caso.get("esperado") or {}),
        }

    obtenido = await parse_financial_text(transcripcion)
    return {
        "id": caso["id"],
        "transcripcion": transcripcion,
        "obtenido": obtenido,
        "esperado": caso.get("esperado"),
        "objetivo": caso.get("objetivo", ""),
        "resultado": comparar(obtenido, caso.get("esperado") or {}),
    }


def formatear_mensaje(transcripcion: str | None) -> str:
    if not transcripcion:
        return "  (sin transcripcion)"
    return f"  [{transcripcion.strip()}]"


def imprimir_resumen(resultados: list[dict]) -> None:
    """Imprime la tabla y el % de acierto en monto."""
    print("\n" + "=" * 78)
    print("RESULTADOS - CASO POR CASO")
    print("=" * 78)
    print(f"{'Caso':<5} {'Transcripcion / resultado':<70}")

    conteo_monto = {"total": 0, "ok": 0}
    conteo_cat = {"total": 0, "ok": 0}
    conteo_tipo = {"total": 0, "ok": 0}

    for r in resultados:
        caso_id = r["id"]
        if "error" in r:
            print(f"{caso_id:<5} ERROR: {r['error']}")
            continue

        res = r["resultado"]
        esperado = r["esperado"]
        print(f"{caso_id:<5} {formatear_mensaje(r.get('transcripcion'))}")

        if esperado is None:
            obtenido = r.get("obtenido")
            crea = (
                bool(obtenido)
                and obtenido.get("accion", "registrar") == "registrar"
                and obtenido.get("monto") is not None
            )
            ok_comportamiento = "SIN_CREAR" if not crea else "CREO_TRANSACCION"
            print(f"       Comportamiento esperado: {r.get('objetivo', '')}")
            print(f"       Bot: {ok_comportamiento} - REVISION MANUAL")
            continue

        if esperado == "PEDIR_ACLARACION":
            obtenido = r.get("obtenido")
            pide = obtenido is None or obtenido.get("accion") == "aclaracion"
            ok = "PIDE_ACLARACION" if pide else "CREO_TRANSACCION"
            print(f"       Esperado: pedir aclaracion | Bot: {ok} - REVISION MANUAL")
            continue

        if "accion" in esperado and res.get("accion") is not None:
            print(
                f"       accion:    {res['accion']:<6} esperado={esperado['accion']!r} "
                f"bot={r['obtenido'].get('accion') if r['obtenido'] else None!r}"
            )

        for campo, llave in (
            ("monto", "monto"),
            ("categoria", "categoria"),
            ("tipo", "tipo_movimiento"),
        ):
            if res.get(campo) is None:
                continue
            conteo = {
                "monto": conteo_monto,
                "categoria": conteo_cat,
                "tipo": conteo_tipo,
            }[campo]
            conteo["total"] += 1
            if res[campo] == "OK":
                conteo["ok"] += 1
            print(
                f"       {campo:<10} {res[campo]:<6} esperado={esperado[llave]!r} "
                f"bot={r['obtenido'].get(llave) if r['obtenido'] else None!r}"
            )

    print("\n" + "=" * 78)
    print("PUNTAJE")
    print("=" * 78)

    def pct(c: dict) -> str:
        if not c["total"]:
            return "n/a"
        return f"{c['ok']}/{c['total']} = {100.0 * c['ok'] / c['total']:.1f}%"

    print(f"  Monto:     {pct(conteo_monto)}   (meta: >=95%)")
    print(f"  Categoria: {pct(conteo_cat)}")
    print(f"  Tipo:      {pct(conteo_tipo)}")

    meta_monto = conteo_monto["total"] and 100.0 * conteo_monto["ok"] / conteo_monto["total"] >= 95
    print(f"\n  {'META ALCANZADA en monto' if meta_monto else 'META NO alcanzada en monto'}")
    print("=" * 78)


async def main() -> None:
    if not os.path.exists(GOLDEN_SET_PATH):
        print(f"ERROR: no existe {GOLDEN_SET_PATH}")
        sys.exit(1)

    with open(GOLDEN_SET_PATH, encoding="utf-8") as f:
        data = json.load(f)

    casos = [c for c in data["casos"] if c.get("audio")]
    print(f"Evaluando {len(casos)} audios del conjunto dorado...")

    resultados = []
    for caso in casos:
        resultados.append(await evaluar_caso(caso))

    imprimir_resumen(resultados)


if __name__ == "__main__":
    asyncio.run(main())
