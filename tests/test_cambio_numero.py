from unittest.mock import MagicMock, patch

import gspread

from services.numero_service import (
    TEXTO_CAMBIO_NUMERO_CONFIRMADO,
    TEXTO_CAMBIO_NUMERO_INICIO,
    TEXTO_CAMBIO_NUMERO_INVALIDO,
    TEXTO_CAMBIO_NUMERO_SIN_ACCESO,
    clave_cambio_numero,
    crear_codigo_cambio,
    detectar_confirmacion_cambio_numero,
    detectar_inicio_cambio_numero,
    detectar_recuperacion_manual,
    verificar_codigo_cambio,
)
from services.sheets_service import actualizar_telefono_usuario, renombrar_pestana_cliente
from workers.tasks import _procesar_pipeline


def test_detectar_confirmacion_cambio_numero() -> None:
    assert detectar_confirmacion_cambio_numero("cambiar numero 50688888888 123456") == (
        "50688888888",
        "123456",
    )
    assert detectar_confirmacion_cambio_numero("Cambiar número 50688888888 123456") == (
        "50688888888",
        "123456",
    )
    assert detectar_confirmacion_cambio_numero("cambiar mi numero") is None
    assert detectar_confirmacion_cambio_numero("cambiar numero 50688888888") is None


def test_detectar_inicio_cambio_numero() -> None:
    assert detectar_inicio_cambio_numero("cambiar mi número") is True
    assert detectar_inicio_cambio_numero("quiero cambiar de numero") is True
    assert detectar_inicio_cambio_numero("gasté 5000 en café") is False


def test_detectar_recuperacion_manual() -> None:
    assert detectar_recuperacion_manual("no tengo acceso a mi número") is True
    assert detectar_recuperacion_manual("perdí el numero") is True
    assert detectar_recuperacion_manual("hola") is False


async def test_crear_y_verificar_codigo(redis_aislado) -> None:
    codigo = await crear_codigo_cambio("50688888888")
    assert codigo is not None
    assert len(codigo) == 6
    assert codigo.isdigit()
    assert clave_cambio_numero("50688888888") in redis_aislado.store

    assert await verificar_codigo_cambio("50688888888", codigo) is True
    assert clave_cambio_numero("50688888888") not in redis_aislado.store
    assert await verificar_codigo_cambio("50688888888", codigo) is False


async def test_verificar_codigo_incorrecto_conserva_codigo(redis_aislado) -> None:
    codigo = await crear_codigo_cambio("50688888888")
    assert codigo is not None
    incorrecto = "000000" if codigo != "000000" else "111111"
    assert await verificar_codigo_cambio("50688888888", incorrecto) is False
    assert clave_cambio_numero("50688888888") in redis_aislado.store


async def test_verificar_codigo_bloquea_tras_intentos(redis_aislado) -> None:
    codigo = await crear_codigo_cambio("50688888888")
    assert codigo is not None
    incorrecto = "000000" if codigo != "000000" else "111111"
    for _ in range(5):
        await verificar_codigo_cambio("50688888888", incorrecto)
    assert clave_cambio_numero("50688888888") not in redis_aislado.store


async def test_verificar_codigo_sin_solicitud() -> None:
    assert await verificar_codigo_cambio("50688888888", "123456") is False


@patch("services.sheets_service.get_sheets_client")
async def test_actualizar_telefono_usuario(mock_get_sheets_client) -> None:
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()
    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_worksheet.col_values.return_value = ["telefono", "50688888888"]

    assert await actualizar_telefono_usuario("50688888888", "50670000000") is True
    mock_worksheet.update_cell.assert_called_once_with(2, 1, "50670000000")


@patch("services.sheets_service.get_sheets_client")
async def test_actualizar_telefono_usuario_inexistente(mock_get_sheets_client) -> None:
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()
    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_worksheet.col_values.return_value = ["telefono"]

    assert await actualizar_telefono_usuario("50688888888", "50670000000") is False
    mock_worksheet.update_cell.assert_not_called()


@patch("services.sheets_service.get_sheets_client")
async def test_actualizar_telefono_usuario_destino_existe(mock_get_sheets_client) -> None:
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()
    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_worksheet.col_values.return_value = ["telefono", "50688888888", "50670000000"]

    assert await actualizar_telefono_usuario("50688888888", "50670000000") is False


@patch("services.sheets_service.get_sheets_client")
async def test_renombrar_pestana_cliente(mock_get_sheets_client) -> None:
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_worksheet = MagicMock()
    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.side_effect = [
        gspread.exceptions.WorksheetNotFound,
        mock_worksheet,
    ]

    assert await renombrar_pestana_cliente("50688888888", "50670000000") is True
    mock_worksheet.update_title.assert_called_once_with("50670000000")


@patch("services.sheets_service.get_sheets_client")
async def test_renombrar_pestana_origen_inexistente(mock_get_sheets_client) -> None:
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.side_effect = [
        gspread.exceptions.WorksheetNotFound,
        gspread.exceptions.WorksheetNotFound,
    ]

    assert await renombrar_pestana_cliente("50688888888", "50670000000") is True


@patch("services.sheets_service.get_sheets_client")
async def test_renombrar_pestana_destino_existe(mock_get_sheets_client) -> None:
    mock_client = MagicMock()
    mock_spreadsheet = MagicMock()
    mock_get_sheets_client.return_value = mock_client
    mock_client.open_by_key.return_value = mock_spreadsheet
    mock_spreadsheet.worksheet.return_value = MagicMock()

    assert await renombrar_pestana_cliente("50688888888", "50670000000") is False


async def test_pipeline_confirma_cambio_numero() -> None:
    with (
        patch("workers.tasks.verificar_codigo_cambio", return_value=True) as mock_verif,
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": "1.0"},
        ),
        patch("workers.tasks.registrar_consentimiento") as mock_registrar,
        patch("workers.tasks.actualizar_telefono_usuario") as mock_usuario,
        patch("workers.tasks.renombrar_pestana_cliente") as mock_pestana,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(
            None, "50670000000", texto_entrante="cambiar numero 50688888888 123456"
        )

    assert result == ""
    mock_verif.assert_called_once_with("50688888888", "123456")
    mock_registrar.assert_called_once_with("50670000000", "aceptado")
    mock_usuario.assert_called_once_with("50688888888", "50670000000")
    mock_pestana.assert_called_once_with("50688888888", "50670000000")
    mock_whatsapp.assert_called_once_with(
        to_phone="50670000000", mensaje=TEXTO_CAMBIO_NUMERO_CONFIRMADO
    )


async def test_pipeline_cambio_codigo_invalido() -> None:
    with (
        patch("workers.tasks.verificar_codigo_cambio", return_value=False),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(
            None, "50670000000", texto_entrante="cambiar numero 50688888888 000000"
        )

    assert result == ""
    mock_whatsapp.assert_called_once_with(
        to_phone="50670000000", mensaje=TEXTO_CAMBIO_NUMERO_INVALIDO
    )


async def test_pipeline_cambio_mismo_numero_invalido() -> None:
    with (
        patch("workers.tasks.verificar_codigo_cambio") as mock_verif,
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(
            None, "50688888888", texto_entrante="cambiar numero 50688888888 123456"
        )

    assert result == ""
    mock_verif.assert_not_called()
    mock_whatsapp.assert_called_once_with(
        to_phone="50688888888", mensaje=TEXTO_CAMBIO_NUMERO_INVALIDO
    )


async def test_pipeline_inicia_cambio_numero() -> None:
    with (
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": "1.0"},
        ),
        patch("workers.tasks.crear_codigo_cambio", return_value="123456"),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(
            None, "50688888888", texto_entrante="quiero cambiar mi número"
        )

    assert result == ""
    mock_whatsapp.assert_called_once_with(
        to_phone="50688888888",
        mensaje=TEXTO_CAMBIO_NUMERO_INICIO.format(telefono="50688888888", codigo="123456"),
    )


async def test_pipeline_recuperacion_manual() -> None:
    with (
        patch(
            "workers.tasks.obtener_consentimiento",
            return_value={"estado": "aceptado", "version_politica": "1.0"},
        ),
        patch("workers.tasks.enviar_mensaje_whatsapp") as mock_whatsapp,
    ):
        result = await _procesar_pipeline(
            None, "50688888888", texto_entrante="no tengo acceso a mi número"
        )

    assert result == ""
    mock_whatsapp.assert_called_once_with(
        to_phone="50688888888", mensaje=TEXTO_CAMBIO_NUMERO_SIN_ACCESO
    )
