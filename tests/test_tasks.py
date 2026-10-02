import os
import sys
import tempfile
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.duplicado_service import (
    TEXTO_CONFIRMACION_DUPLICADO,
    TEXTO_DUPLICADO_CONFIRMADO,
    TEXTO_DUPLICADO_DESCARTADO,
)
from services.politica_service import POLITICA_VERSION

EXPECTED_DIR = os.path.join(tempfile.gettempdir(), "caja_chica")
EXPECTED_PATH = os.path.join(EXPECTED_DIR, "12345.ogg")


def test_download_audio_task_exito() -> None:
    """Valida el flujo exitoso de la tarea asíncrona simulando las
    respuestas HTTP de Meta utilizando httpx.
    """
    # 1. Limpieza de módulos para forzar recarga
    if "app.config" in sys.modules:
        del sys.modules["app.config"]
    if "workers.tasks" in sys.modules:
        del sys.modules["workers.tasks"]

    # 2. Configuración del entorno
    mock_env = {
        "WHATSAPP_VERIFY_TOKEN": "test_token",
        "WHATSAPP_API_TOKEN": "test_api",
        "WHATSAPP_PHONE_NUMBER_ID": "test_id",
        "OPENAI_API_KEY": "test_openai_key",
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "REDIS_URL": "redis://localhost:6379/0",
        "APPDATA": os.environ.get("APPDATA", "C:\\temp"),
    }

    # 3. Ejecución con patching
    with patch.dict("os.environ", mock_env):
        from workers.tasks import download_audio_task

        with (
            patch("workers.tasks.httpx.Client") as mock_client_class,
            patch("workers.tasks.os.makedirs") as mock_makedirs,
            patch("workers.tasks.open", create=True) as mock_open,
            patch(
                "workers.tasks.transcribir_audio_whisper",
                return_value="transcripcion de prueba",
            ),
            patch(
                "workers.tasks.obtener_consentimiento",
                return_value={"estado": "aceptado", "version_politica": POLITICA_VERSION},
            ),
            patch(
                "workers.tasks.parse_financial_text",
                return_value={
                    "categoria": "comida",
                    "monto": 5000,
                },
            ),
            patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
            patch("workers.tasks.enviar_mensaje_whatsapp", create=True) as mock_whatsapp,
        ):

            mock_client_instance = MagicMock()
            mock_client_class.return_value.__enter__.return_value = mock_client_instance

            mock_response_meta = MagicMock()
            mock_response_meta.json.return_value = {"url": "https://cdn.facebook.com/m/audio.ogg"}

            mock_response_audio = MagicMock()
            mock_response_audio.content = b"fake_ogg_bytes"

            mock_client_instance.get.side_effect = [
                mock_response_meta,
                mock_response_audio,
            ]

            # Ejecución actualizada con sender_phone
            test_sender = "50688888888"
            result_path = download_audio_task("12345", test_sender)

            # Aserciones
            assert result_path == EXPECTED_PATH
            assert mock_client_instance.get.call_count == 2
            expected_headers = {"Authorization": "Bearer test_api"}
            assert all(
                call.kwargs.get("headers") == expected_headers
                for call in mock_client_instance.get.call_args_list
            )
            mock_makedirs.assert_called_once_with(EXPECTED_DIR, exist_ok=True)
            mock_open.assert_called_once_with(EXPECTED_PATH, "wb")

            # Verificamos que el mensaje se envió al número correcto
            mock_whatsapp.assert_called_once()
            call_kwargs = mock_whatsapp.call_args.kwargs
            assert call_kwargs["to_phone"] == test_sender

            # Verificamos que la transacción se guardó con el teléfono del remitente
            mock_sheet.assert_called_once_with({"categoria": "comida", "monto": 5000}, test_sender)


def test_download_audio_task_whisper_falla() -> None:
    """Verifica que si Whisper falla, envía mensaje de error y no intenta parsear."""
    with (
        patch("workers.tasks.transcribir_audio_whisper", return_value=None),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.parse_financial_text") as mock_parser,
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):

        from workers.tasks import download_audio_task

        # Ejecución
        result = download_audio_task("12345", "50688888888")

        # Aserciones
        assert result == EXPECTED_PATH
        mock_whatsapp.assert_called_with(
            to_phone="50688888888",
            mensaje="No entendí el audio. Por favor, intentá de nuevo con más claridad.",
        )
        mock_parser.assert_not_called()


def test_download_audio_task_parse_falla() -> None:
    """Verifica que si el parser falla, envía mensaje de error y no guarda en Sheet."""
    with (
        patch("workers.tasks.transcribir_audio_whisper", return_value="texto valido"),
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": POLITICA_VERSION},
        ),
        patch("workers.tasks.parse_financial_text", return_value=None),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):

        from workers.tasks import download_audio_task

        # Ejecución
        result = download_audio_task("12345", "50688888888")

        # Aserciones
        assert result == EXPECTED_PATH
        mock_whatsapp.assert_called_with(
            to_phone="50688888888",
            mensaje=(
                "No encontré datos financieros en tu mensaje. "
                "Intentá de nuevo indicando monto, categoría y si es gasto o ingreso."
            ),
        )
        mock_sheet.assert_not_called()


def test_download_audio_task_monto_cero_pide_monto() -> None:
    """Hallazgo 20/08/2026: un monto 0 (mensaje sin precio) NO se registra; se pide el monto."""
    with (
        patch("workers.tasks.transcribir_audio_whisper", return_value="texto"),
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": POLITICA_VERSION},
        ),
        patch(
            "workers.tasks.parse_financial_text",
            return_value={
                "accion": "registrar",
                "monto": 0,
                "categoria": "Compras",
                "tipo_movimiento": "Gasto",
                "detalle": "3 cajas de pañuelos",
            },
        ),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):

        from workers.tasks import download_audio_task

        result = download_audio_task("12345", "50688888888")

        assert result == EXPECTED_PATH
        mock_sheet.assert_not_called()
        mock_whatsapp.assert_called_with(
            to_phone="50688888888",
            mensaje=(
                "No encontré un monto en tu mensaje. Intentá de nuevo "
                "indicando monto, categoría y si es gasto o ingreso."
            ),
        )


def test_download_audio_task_whisper_no_rompe_flujo_exitoso() -> None:
    """Valida que el flujo exitoso sigue funcionando como antes."""
    with (
        patch("workers.tasks.transcribir_audio_whisper", return_value="texto"),
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": POLITICA_VERSION},
        ),
        patch("workers.tasks.parse_financial_text", return_value={"categoria": "A", "monto": 100}),
        patch("workers.tasks.append_transaction_to_sheet"),
        patch("workers.tasks.enviar_mensaje_whatsapp"),
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):

        from workers.tasks import download_audio_task

        result = download_audio_task("12345", "50688888888")
        assert result == EXPECTED_PATH


def test_download_audio_task_aclaracion_pide_aclaracion() -> None:
    """Verifica que un mensaje con dos flujos pide aclaración y NO guarda ni corrige."""
    with (
        patch("workers.tasks.transcribir_audio_whisper", return_value="texto"),
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": POLITICA_VERSION},
        ),
        patch(
            "workers.tasks.parse_financial_text",
            return_value={"accion": "aclaracion", "monto": None},
        ),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
        patch("workers.tasks.update_last_transaction_to_sheet") as mock_update,
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):

        from workers.tasks import download_audio_task

        result = download_audio_task("12345", "50688888888")

        assert result == EXPECTED_PATH
        mock_sheet.assert_not_called()
        mock_update.assert_not_called()
        mock_whatsapp.assert_called_with(
            to_phone="50688888888",
            mensaje=(
                "Vi dos movimientos en tu mensaje y solo registro uno a la vez. "
                "¿Cuál querés que apunte?"
            ),
        )


def test_download_audio_task_corregir_actualiza() -> None:
    """Verifica que una corrección actualiza la última transacción y NO crea una nueva."""
    data_corregir = {
        "accion": "corregir",
        "monto": 6000,
        "categoria": "Transporte",
        "tipo_movimiento": "Gasto",
        "detalle": "Pasajes",
    }
    with (
        patch("workers.tasks.transcribir_audio_whisper", return_value="texto"),
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": POLITICA_VERSION},
        ),
        patch("workers.tasks.parse_financial_text", return_value=data_corregir),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
        patch(
            "workers.tasks.update_last_transaction_to_sheet",
            return_value=[-6000, "Transporte", "Pasajes"],
        ) as mock_update,
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):

        from workers.tasks import download_audio_task

        result = download_audio_task("12345", "50688888888")

        assert result == EXPECTED_PATH
        mock_sheet.assert_not_called()
        mock_update.assert_called_once_with(data_corregir, "50688888888")
        mock_whatsapp.assert_called_with(
            to_phone="50688888888",
            mensaje="Corregido: Transporte - ₡6000",
        )


def test_download_audio_task_corregir_sin_previa() -> None:
    """Verifica que si no hay transacción previa, avisa y NO crea una nueva."""
    with (
        patch("workers.tasks.transcribir_audio_whisper", return_value="texto"),
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": POLITICA_VERSION},
        ),
        patch(
            "workers.tasks.parse_financial_text",
            return_value={"accion": "corregir", "monto": 6000, "categoria": "Transporte"},
        ),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
        patch("workers.tasks.append_transaction_to_sheet") as mock_sheet,
        patch("workers.tasks.update_last_transaction_to_sheet", return_value=False) as mock_update,
        patch("workers.tasks.httpx.Client"),
        patch("workers.tasks.os.makedirs"),
        patch("workers.tasks.open", create=True),
    ):

        from workers.tasks import download_audio_task

        result = download_audio_task("12345", "50688888888")

        assert result == EXPECTED_PATH
        mock_sheet.assert_not_called()
        mock_update.assert_called_once()
        mock_whatsapp.assert_called_with(
            to_phone="50688888888",
            mensaje=(
                "No encontré una transacción previa tuya para corregir. "
                "Mandame primero el movimiento."
            ),
        )


# ==========================================
# 8.6.2 — IDEMPOTENCIA ANTI-DOBLE-TAP
# ==========================================
class _FakeRedis:
    """Redis en memoria para probar el dedupe sin depender del servicio real."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)

    async def aclose(self) -> None:
        return None


def _entrada_registro(monto: int, categoria: str, detalle: str) -> dict[str, object]:
    return {
        "accion": "registrar",
        "monto": monto,
        "categoria": categoria,
        "tipo_movimiento": "Gasto",
        "detalle": detalle,
    }


def _contexto_8_6_2(
    redis_falso: _FakeRedis, parse_result: object, transcripcion: str | None = None
):
    """
    Patches del pipeline para las pruebas de 8.6.2. Usa ExitStack para no depender del
    orden de índices. `settings` va mockeado porque `download_audio_task` aborta sin token
    (misma lección de hermeticidad que la trampa J). `transcripcion` solo hace falta para
    el canal de audio, que pasa por Whisper.
    """
    stack = ExitStack()
    mocks = {
        "wa": stack.enter_context(patch("workers.tasks.enviar_mensaje_whatsapp")),
        "sheet": stack.enter_context(patch("workers.tasks.append_transaction_to_sheet")),
        "redis": stack.enter_context(
            patch("workers.tasks._dedupe_redis", new=AsyncMock(return_value=redis_falso))
        ),
        "settings": stack.enter_context(patch("workers.tasks.settings")),
        "consent": stack.enter_context(
            patch(
                "workers.tasks.obtener_consentimiento",
                return_value={"estado": "aceptado", "version_politica": POLITICA_VERSION},
            )
        ),
        "parse": stack.enter_context(
            patch("workers.tasks.parse_financial_text", return_value=parse_result)
        ),
    }
    if transcripcion is not None:
        mocks["whisper"] = stack.enter_context(
            patch("workers.tasks.transcribir_audio_whisper", return_value=transcripcion)
        )
    for target in ("workers.tasks.httpx.Client", "workers.tasks.os.makedirs"):
        stack.enter_context(patch(target))
    stack.enter_context(patch("workers.tasks.open", create=True))
    return stack, mocks


def test_8_6_2_compra_repetida_pregunta_y_no_duplica() -> None:
    """Rompe-si (c): 1 compra repetida por duda = 1 fila + pregunta, no 2 filas."""
    redis_falso = _FakeRedis()
    datos = _entrada_registro(1500, "Alimentación", "sándwich")
    stack, m = _contexto_8_6_2(redis_falso, datos)

    with stack:
        from workers.tasks import procesar_mensaje_texto_task

        procesar_mensaje_texto_task("50688888888", "gasté 1500 en un sándwich")
        procesar_mensaje_texto_task("50688888888", "gasté 1500 en un sándwich")

        assert m["sheet"].call_count == 1
        assert m["wa"].call_args_list[-1].kwargs["mensaje"] == TEXTO_CONFIRMACION_DUPLICADO


def test_8_6_2_tres_compras_distintas_generan_tres_filas() -> None:
    """Rompe-si (b): 3 compras reales separadas = 3 filas (el dedupe no las junta)."""
    redis_falso = _FakeRedis()
    compras = [
        ("gasté 1500 en pan", _entrada_registro(1500, "Alimentación", "pan")),
        ("gasté 2500 en bus", _entrada_registro(2500, "Transporte", "bus")),
        ("gasté 900 en café", _entrada_registro(900, "Alimentación", "cafe")),
    ]
    stack = ExitStack()
    m_redis = stack.enter_context(
        patch("workers.tasks._dedupe_redis", new=AsyncMock(return_value=redis_falso))
    )
    m_wa = stack.enter_context(patch("workers.tasks.enviar_mensaje_whatsapp"))
    m_sheet = stack.enter_context(patch("workers.tasks.append_transaction_to_sheet"))
    stack.enter_context(
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": POLITICA_VERSION},
        )
    )
    m_parse = stack.enter_context(
        patch("workers.tasks.parse_financial_text", side_effect=[c[1] for c in compras])
    )

    with stack:
        from workers.tasks import procesar_mensaje_texto_task

        for texto, _ in compras:
            procesar_mensaje_texto_task("50688888888", texto)

        assert m_parse.call_count == 3
        assert m_sheet.call_count == 3
        assert m_redis is not None and m_wa is not None


def test_8_6_2_reenvio_mismo_media_id_no_guarda() -> None:
    """Reenvío del mismo audio (mismo media_id) = 1 fila + pregunta."""
    redis_falso = _FakeRedis()
    datos = _entrada_registro(1500, "Alimentación", "sándwich")
    stack, m = _contexto_8_6_2(redis_falso, datos, transcripcion="gasté 1500 en un sándwich")

    with stack:
        from workers.tasks import download_audio_task

        download_audio_task("99999", "50688888888")
        download_audio_task("99999", "50688888888")

        assert m["sheet"].call_count == 1
        assert m["wa"].call_args_list[-1].kwargs["mensaje"] == TEXTO_CONFIRMACION_DUPLICADO


def test_8_6_2_confirmar_registra_de_nuevo() -> None:
    """Principio 'preguntar, no adivinar': pregunta, y si confirma, ahora sí guarda."""
    redis_falso = _FakeRedis()
    datos = _entrada_registro(1500, "Alimentación", "sándwich")
    stack, m = _contexto_8_6_2(redis_falso, datos)

    with stack:
        from workers.tasks import procesar_mensaje_texto_task

        procesar_mensaje_texto_task("50688888888", "gasté 1500 en un sándwich")
        procesar_mensaje_texto_task("50688888888", "gasté 1500 en un sándwich")
        assert m["sheet"].call_count == 1

        procesar_mensaje_texto_task("50688888888", "si registralo otra vez")

        assert m["sheet"].call_count == 2
        assert m["wa"].call_args_list[-1].kwargs["mensaje"] == TEXTO_DUPLICADO_CONFIRMADO


def test_8_6_2_confirmar_que_es_el_mismo_no_guarda() -> None:
    """Si responde 'es el mismo', no se duplica (la pendiente se descarta)."""
    redis_falso = _FakeRedis()
    datos = _entrada_registro(1500, "Alimentación", "sándwich")
    stack, m = _contexto_8_6_2(redis_falso, datos)

    with stack:
        from workers.tasks import procesar_mensaje_texto_task

        procesar_mensaje_texto_task("50688888888", "gasté 1500 en un sándwich")
        procesar_mensaje_texto_task("50688888888", "gasté 1500 en un sándwich")
        assert m["sheet"].call_count == 1

        procesar_mensaje_texto_task("50688888888", "es el mismo")

        assert m["sheet"].call_count == 1
        assert m["wa"].call_args_list[-1].kwargs["mensaje"] == TEXTO_DUPLICADO_DESCARTADO


# ==========================================
# 8.6.2 — Variantes naturales de la respuesta (fix 01/10/2026)
# ==========================================


@pytest.mark.parametrize(
    "respuesta",
    ["sí", "si", "va", "dale", "ok", "claro", "sí.", "Va!!", "de nuevo", "son dos", "es otro"],
)
def test_8_6_2_confirmaciones_cortas_registran_otra_fila(respuesta: str) -> None:
    """
    Hallazgo 1 del E2E 01/10/2026: la pregunta pide "sí" y el bot volvía a pedir el monto.
    Con la pendiente activa, un "sí" pelado solo puede significar "sí, otra vez".
    """
    redis_falso = _FakeRedis()
    datos = _entrada_registro(1500, "Alimentación", "sándwich")
    stack, m = _contexto_8_6_2(redis_falso, datos)

    with stack:
        from workers.tasks import procesar_mensaje_texto_task

        procesar_mensaje_texto_task("50688888888", "gasté 1500 en un sándwich")
        procesar_mensaje_texto_task("50688888888", "gasté 1500 en un sándwich")
        assert m["sheet"].call_count == 1

        procesar_mensaje_texto_task("50688888888", respuesta)

        assert m["sheet"].call_count == 2
        assert m["wa"].call_args_list[-1].kwargs["mensaje"] == TEXTO_DUPLICADO_CONFIRMADO


@pytest.mark.parametrize(
    "respuesta",
    [
        "no",
        "nada",
        "es lo mismo",
        "era lo mismo",
        "fue lo mismo",
        "es la misma",
        "dejalo",
        "déjalo",
        "no lo registres",
        "no lo guardes",
        "era uno solo",
        "solo era uno",
        "¿es lo mismo?",
    ],
)
def test_8_6_2_variaciones_de_mismo_no_guardan(respuesta: str) -> None:
    """
    El caso reportado por el dueño: escribió "es lo mismo" y el bot respondió "Vi dos
    movimientos en tu mensaje". La lista vieja solo conocía "es el mismo".
    """
    redis_falso = _FakeRedis()
    datos = _entrada_registro(1500, "Alimentación", "sándwich")
    stack, m = _contexto_8_6_2(redis_falso, datos)

    with stack:
        from workers.tasks import procesar_mensaje_texto_task

        procesar_mensaje_texto_task("50688888888", "gasté 1500 en un sándwich")
        procesar_mensaje_texto_task("50688888888", "gasté 1500 en un sándwich")
        assert m["sheet"].call_count == 1

        procesar_mensaje_texto_task("50688888888", respuesta)

        assert m["sheet"].call_count == 1
        assert m["wa"].call_args_list[-1].kwargs["mensaje"] == TEXTO_DUPLICADO_DESCARTADO


@pytest.mark.parametrize("texto", ["sin monto", "van", "token", "vaca", "mismamente", "notas"])
def test_8_6_2_marcas_cortas_no_colisionan(texto: str) -> None:
    """
    Rompe-si crítico: las marcas cortas se comparan por coincidencia exacta justamente
    para que `si` no matchee `sin monto` y `va` no matchee `van`. Con una pendiente activa
    ese falso positivo registra o descarta una fila.
    """
    from services.duplicado_service import detectar_confirmacion_duplicado

    assert detectar_confirmacion_duplicado(texto) is None


def test_8_6_2_frase_larga_no_confirma() -> None:
    """
    Rompe-si histórico (>6 palabras): una frase de negocio no es respuesta a la pregunta
    del duplicado, así que no puede decidir sobre la fila pendiente: se devuelve al
    parser. Es el comportamiento previo a este fix, no una regresión.

    No se afirma el número de filas porque el mock del parser devuelve siempre una
    transacción válida; lo que importa es que la pendiente NO se resolvió como
    confirmación y el mensaje llegó al parser.
    """
    redis_falso = _FakeRedis()
    datos = _entrada_registro(1500, "Alimentación", "sándwich")
    stack, m = _contexto_8_6_2(redis_falso, datos)

    with stack:
        from workers.tasks import procesar_mensaje_texto_task

        procesar_mensaje_texto_task("50688888888", "gasté 1500 en un sándwich")
        procesar_mensaje_texto_task("50688888888", "gasté 1500 en un sándwich")
        assert m["sheet"].call_count == 1

        procesar_mensaje_texto_task("50688888888", "es lo mismo pero dejame la fila")

        # El parser corre una vez por mensaje: la detección de duplicado se evalúa
        # después de parsear (tasks.py), así que son 3 llamadas para 3 mensajes.
        assert m["parse"].call_count == 3
        assert m["wa"].call_args_list[-1].kwargs["mensaje"] not in (
            TEXTO_DUPLICADO_DESCARTADO,
            TEXTO_DUPLICADO_CONFIRMADO,
        )


def test_8_6_2_sin_pendiente_no_intercepta() -> None:
    """
    Rompe-si del aislamiento: sin pendiente activa esta función ni se llega a llamar
    desde el pipeline. 'sí' debe seguir yendo al parser como mensaje normal.
    """
    redis_falso = _FakeRedis()
    stack, m = _contexto_8_6_2(redis_falso, None)

    with stack:
        from workers.tasks import procesar_mensaje_texto_task

        procesar_mensaje_texto_task("50688888888", "sí")

        assert m["parse"].call_count == 1
        assert m["sheet"].call_count == 0
        assert m["wa"].call_args_list[-1].kwargs["mensaje"] == (
            "No encontré datos financieros en tu mensaje. Intentá de nuevo "
            "indicando monto, categoría y si es gasto o ingreso."
        )
