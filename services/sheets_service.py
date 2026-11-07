import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import gspread
from gspread.utils import ValueInputOption  # Importamos el enumerado para el tipado

from app.config import settings
from services.politica_service import POLITICA_VERSION
from services.suscripcion_service import ESTADOS_CON_ACCESO

logger = logging.getLogger(__name__)

_sheets_client: Any = None

# Fase 6.5.1 — Consentimiento (ADR-0011, Ley 8968). En MVP la "tabla usuarios"
# se materializa como una pestaña del mismo Google Sheet (ADR-0002/0009).
CONSENT_TAB_NAME = "Consentimiento"
CONSENT_HEADERS = ["telefono", "estado", "fecha", "version_politica"]

# Fase 6.5.2 — Aislamiento por pestañas (ADR-0009). Cada cliente escribe SOLO en su
# pestaña (título = teléfono), creada perezosamente con estos encabezados.
TRANSACTION_HEADERS = ["fecha", "monto", "categoria", "detalle", "telefono"]


def get_sheets_client() -> Any:
    """
    Inicializa y devuelve el cliente autenticado de gspread.
    Reusa el cliente si ya fue creado para evitar múltiples autenticaciones.
    """
    global _sheets_client
    if _sheets_client is not None:
        return _sheets_client
    try:
        _sheets_client = gspread.service_account(filename=settings.GOOGLE_APPLICATION_CREDENTIALS)  # type: ignore[attr-defined]
        return _sheets_client
    except Exception as e:
        logger.error(f"Error crítico al autenticar con gspread: {e}")
        raise e


def _sync_get_client_worksheet(spreadsheet_id: str, sender_phone: str) -> Any:
    """
    Resuelve la pestaña del cliente por teléfono (título = sender_phone) y la crea con
    encabezados si no existe (ADR-0009, aislamiento por pestañas). Cada cliente escribe
    SOLO en su pestaña dentro del mismo spreadsheet.
    """
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(sender_phone)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=sender_phone, rows=100, cols=10)
        worksheet.append_row(
            TRANSACTION_HEADERS,
            value_input_option=ValueInputOption.user_entered,
        )
    return worksheet


def _sync_append_row(spreadsheet_id: str, row_values: list[Any], sender_phone: str) -> None:
    """
    Operación puramente síncrona que interactúa con la API de Google Sheets.
    Escribe en la pestaña del cliente (aislamiento por pestañas, ADR-0009).
    """
    worksheet = _sync_get_client_worksheet(spreadsheet_id, sender_phone)

    # Se utiliza ValueInputOption.user_entered para cumplir con el tipado de mypy
    worksheet.append_row(row_values, value_input_option=ValueInputOption.user_entered)


def _sync_update_last_row(spreadsheet_id: str, sender_phone: str, row_values: list[Any]) -> None:
    """
    Operación síncrona: localiza la última fila cuyo teléfono coincida con el remitente
    en la pestaña del cliente (ADR-0009) y reescribe sus celdas (monto, categoría,
    detalle y teléfono) conservando la fecha. Lanza LookupError si el usuario no tiene
    transacciones previas.
    """
    worksheet = _sync_get_client_worksheet(spreadsheet_id, sender_phone)

    phone_values = worksheet.col_values(5)
    matches = [i for i, phone in enumerate(phone_values, start=1) if phone == sender_phone]
    if not matches:
        raise LookupError(f"sin transacciones previas para {sender_phone}")

    last_row = matches[-1]
    worksheet.update(
        f"B{last_row}:E{last_row}",
        [row_values],
        value_input_option=ValueInputOption.user_entered,
    )


def _sync_read_last_row(spreadsheet_id: str, sender_phone: str) -> list[Any]:
    """
    Operación síncrona: lee la última fila cuyo teléfono coincida con el remitente
    (columnas A:E) en la pestaña del cliente (ADR-0009) para poder fusionar el delta
    de una corrección con los valores anteriores. Lanza LookupError si el usuario no
    tiene transacciones previas.
    """
    worksheet = _sync_get_client_worksheet(spreadsheet_id, sender_phone)

    phone_values = worksheet.col_values(5)
    matches = [i for i, phone in enumerate(phone_values, start=1) if phone == sender_phone]
    if not matches:
        raise LookupError(f"sin transacciones previas para {sender_phone}")

    last_row = matches[-1]
    return list(worksheet.row_values(last_row))


def _merge_delta_con_ultima_fila(delta: dict[str, Any], fila_anterior: list[Any]) -> list[Any]:
    """
    Fusiona el delta de una corrección con los valores de la última fila del usuario.

    Semántica de delta (plan-correccion-delta.md, hallazgo 13/08/2026): un campo que el
    LLM devuelve como None significa "el usuario no lo mencionó" → se conserva el valor
    anterior. Un campo con valor se aplica. Desde el 20/08/2026 un monto de 0 también se
    trata como "no mencionado" (el 0 es un monto inválido que la IA no debe inventar) y
    conserva el monto anterior. La fila previa viene como
    [fecha, monto, categoria, detalle, telefono] y se devuelve el row a escribir en B:E.
    """
    prev_monto = int(fila_anterior[1]) if len(fila_anterior) > 1 and fila_anterior[1] else 0
    prev_categoria = fila_anterior[2] if len(fila_anterior) > 2 else "Otros"
    prev_detalle = fila_anterior[3] if len(fila_anterior) > 3 else ""

    tipo = delta.get("tipo_movimiento")
    if tipo is None:
        tipo = "Gasto" if prev_monto < 0 else "Ingreso"

    monto = delta.get("monto")
    if not monto:
        monto = abs(prev_monto)

    if tipo.lower() == "gasto" and monto > 0:
        monto = -monto

    categoria = delta.get("categoria") or prev_categoria
    detalle = delta.get("detalle") or prev_detalle

    return [monto, categoria, detalle]


async def append_transaction_to_sheet(transaction_data: dict[str, Any], sender_phone: str) -> bool:
    """
    Inserta una nueva fila en Google Sheets de manera asíncrona, en la pestaña del
    cliente (ADR-0009, aislamiento por pestañas; título = teléfono).

    La fila guarda también el teléfono del remitente (columna "teléfono"),
    base para localizar la última transacción del usuario en el flujo de
    corrección (5.5.3) y para la identidad por teléfono (6.1).
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID

    try:
        fecha_actual = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        monto = transaction_data.get("monto", 0)
        tipo = transaction_data.get("tipo_movimiento") or "Gasto"

        if tipo.lower() == "gasto" and monto > 0:
            monto = -monto

        row_values = [
            fecha_actual,
            monto,
            transaction_data.get("categoria", "Otros"),
            transaction_data.get("detalle", ""),
            sender_phone,
        ]

        await asyncio.to_thread(_sync_append_row, spreadsheet_id, row_values, sender_phone)

        logger.info(f"Fila insertada con éxito en Sheets de forma asíncrona: {row_values}")
        return True

    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al escribir en Google Sheets: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado en el servicio de Sheets: {e}")
        return False


async def update_last_transaction_to_sheet(
    transaction_data: dict[str, Any], sender_phone: str
) -> list[Any] | None:
    """
    Actualiza la última transacción del remitente con los datos corregidos
    (flujo de corrección 5.5.3, ADR-0010) usando semántica de DELTA: los campos
    que el LLM devuelve como None se conservan de la fila anterior (corrección
    parcial no destruye datos). Operación en la pestaña del cliente (ADR-0009,
    aislamiento por pestañas). Devuelve la fila final aplicada [monto, categoria,
    detalle]; None si el usuario no tiene transacciones previas o hubo error de API.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID

    try:
        fila_anterior = await asyncio.to_thread(_sync_read_last_row, spreadsheet_id, sender_phone)
        row_values = _merge_delta_con_ultima_fila(transaction_data, fila_anterior)
        row_to_write = [*row_values, sender_phone]

        await asyncio.to_thread(_sync_update_last_row, spreadsheet_id, sender_phone, row_to_write)

        logger.info(f"Transacción corregida en Sheets para {sender_phone}: {row_to_write}")
        return row_values

    except LookupError as error:
        logger.info(f"No hay transacción previa del usuario {sender_phone}: {error}")
        return None
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al corregir en Google Sheets: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado en el servicio de Sheets (corregir): {e}")
        return None


# ==========================================
# FASE 6.5.1 — CONSENTIMIENTO (ADR-0011, Ley 8968)
# ==========================================
def _sync_get_consent_worksheet(spreadsheet_id: str) -> Any:
    """Devuelve la pestaña de consentimientos, creándola con encabezados si no existe."""
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(CONSENT_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=CONSENT_TAB_NAME, rows=100, cols=10)
        worksheet.append_row(
            CONSENT_HEADERS,
            value_input_option=ValueInputOption.user_entered,
        )
    return worksheet


def _sync_read_consent(spreadsheet_id: str, sender_phone: str) -> dict[str, Any] | None:
    """
    Operación síncrona: lee el registro de consentimiento del teléfono (columna A)
    y retorna {'telefono', 'estado', 'fecha', 'version_politica'} o None si no existe.
    """
    worksheet = _sync_get_consent_worksheet(spreadsheet_id)
    phones = worksheet.col_values(1)
    matches = [i for i, phone in enumerate(phones, start=1) if phone == sender_phone]
    if not matches:
        return None

    last_row = matches[-1]
    values = worksheet.row_values(last_row)
    if len(values) < 2 or not values[1]:
        return None
    return {
        "telefono": values[0],
        "estado": values[1],
        "fecha": values[2] if len(values) > 2 else "",
        "version_politica": values[3] if len(values) > 3 else "",
    }


def _sync_write_consent(spreadsheet_id: str, sender_phone: str, estado: str) -> None:
    """Operación síncrona: registra (o actualiza) el estado de consentimiento del teléfono."""
    worksheet = _sync_get_consent_worksheet(spreadsheet_id)

    phones = worksheet.col_values(1)
    matches = [i for i, phone in enumerate(phones, start=1) if phone == sender_phone]
    fecha_actual = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    if matches:
        last_row = matches[-1]
        worksheet.update(
            f"B{last_row}:D{last_row}",
            [[estado, fecha_actual, POLITICA_VERSION]],
            value_input_option=ValueInputOption.user_entered,
        )
    else:
        worksheet.append_row(
            [sender_phone, estado, fecha_actual, POLITICA_VERSION],
            value_input_option=ValueInputOption.user_entered,
        )


async def obtener_consentimiento(sender_phone: str) -> dict[str, Any] | None:
    """
    Consulta el estado de consentimiento del usuario en Google Sheets.
    Retorna el registro completo o None si el usuario nunca respondió la política.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(_sync_read_consent, spreadsheet_id, sender_phone)
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al leer consentimiento: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado al leer consentimiento: {e}")
        return None


async def registrar_consentimiento(sender_phone: str, estado: str) -> bool:
    """
    Registra la respuesta del usuario a la política (estado: 'aceptado' o 'rechazado').
    Retorna True si se persistió correctamente.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        await asyncio.to_thread(_sync_write_consent, spreadsheet_id, sender_phone, estado)
        logger.info(f"Consentimiento {estado} registrado para {sender_phone}.")
        return True
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al registrar consentimiento: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado al registrar consentimiento: {e}")
        return False


# ==========================================
# FASE 6.5.3 — DERECHOS ARCO: EXPORTACIÓN (ADR-0011, Ley 8968)
# ==========================================
def _sync_read_client_rows(spreadsheet_id: str, sender_phone: str) -> list[list[Any]]:
    """
    Operación síncrona: lee TODAS las filas de la pestaña del cliente (ADR-0009) sin
    los encabezados ni filas vacías. Se usa para "exporta mis datos" (Fase 6.5.3).
    """
    worksheet = _sync_get_client_worksheet(spreadsheet_id, sender_phone)
    rows = worksheet.get_all_values()
    if rows and rows[0] == TRANSACTION_HEADERS:
        rows = rows[1:]
    return [r for r in rows if any(r)]


async def obtener_transacciones_cliente(sender_phone: str) -> list[list[Any]]:
    """
    Lee todas las transacciones del cliente desde su pestaña ("exporta mis datos",
    Fase 6.5.3, derechos ARCO). Retorna la lista de filas (sin encabezados) o [] si
    el cliente no tiene movimientos o hubo un error.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(_sync_read_client_rows, spreadsheet_id, sender_phone)
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al leer datos del cliente: {error}")
        return []
    except Exception as e:
        logger.error(f"Error inesperado al leer datos del cliente: {e}")
        return []


# ==========================================
# FASE 7.2.1 — SUSCRIPCIONES (ADR-0013): CONTROL COMERCIAL
# ==========================================
# Separación legal/comercial (ADR-0013): la pestaña `Suscripciones` la mantiene a mano
# el fundador y el bot SOLO la lee (nunca escribe filas de clientes en el MVP). Las
# columnas siguen el acuerdo de la auditoría 23/09/2026.
SUSCRIPCIONES_TAB_NAME = "Suscripciones"
SUSCRIPCION_HEADERS = [
    "telefono",
    "plan",
    "estado",
    "fecha_inicio",
    "fecha_renovacion",
    "ultimo_pago",
]


def _sync_get_suscripciones_worksheet(spreadsheet_id: str) -> Any:
    """Devuelve la pestaña de suscripciones, creándola con encabezados si no existe."""
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(SUSCRIPCIONES_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=SUSCRIPCIONES_TAB_NAME, rows=100, cols=10)
        worksheet.append_row(
            SUSCRIPCION_HEADERS,
            value_input_option=ValueInputOption.user_entered,
        )
    return worksheet


def _sync_read_suscripcion(spreadsheet_id: str, sender_phone: str) -> dict[str, Any] | None:
    """
    Operación síncrona: lee el registro de suscripción del teléfono (columna A) y
    retorna {'telefono', 'plan', 'estado', 'fecha_inicio', 'fecha_renovacion',
    'ultimo_pago'} o None si no existe o si la fila está incompleta (sin estado).
    """
    worksheet = _sync_get_suscripciones_worksheet(spreadsheet_id)
    phones = worksheet.col_values(1)
    matches = [i for i, phone in enumerate(phones, start=1) if phone == sender_phone]
    if not matches:
        return None

    last_row = matches[-1]
    values = worksheet.row_values(last_row)
    if len(values) < 3 or not values[2]:
        return None
    return {
        "telefono": values[0],
        "plan": values[1] if len(values) > 1 else "",
        "estado": values[2],
        "fecha_inicio": values[3] if len(values) > 3 else "",
        "fecha_renovacion": values[4] if len(values) > 4 else "",
        "ultimo_pago": values[5] if len(values) > 5 else "",
    }


async def obtener_suscripcion(sender_phone: str) -> dict[str, Any] | None:
    """
    Consulta el estado comercial del teléfono en la pestaña `Suscripciones`
    (Fase 7.2.1, ADR-0013). Retorna el registro completo o None si el teléfono no
    tiene suscripción registrada o hubo un error de lectura. El bot solo lee esta
    pestaña: la actualiza a mano el fundador al recibir cada pago.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(_sync_read_suscripcion, spreadsheet_id, sender_phone)
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al leer suscripción: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado al leer suscripción: {e}")
        return None


def _sync_migrar_suscripcion(
    spreadsheet_id: str, telefono_anterior: str, telefono_nuevo: str
) -> str:
    """
    Operación síncrona (deuda #17): muda el control comercial al cambiar de número.
    - Si el número viejo no tiene fila en `Suscripciones`: no se crea nada
      ('sin_suscripcion').
    - Si la ÚLTIMA fila del número nuevo tiene acceso (activo/gratis/de_prueba): no
      se duplica ('nuevo_ya_tiene').
    - Si el número nuevo no tiene fila: se copia la del viejo ('migrada').
    - Si la última fila del número nuevo existe pero NO tiene acceso (p. ej. quedó
      `cancelado` de un cambio anterior), se agrega una fila nueva copiando la del
      viejo ('reactivada'): cambiar de número no debe dejar al usuario sin acceso.
    En todos los casos con fila vieja se marca su estado como `cancelado` para
    revocar el acceso del número anterior (el bot solo lee esta pestaña).
    Retorna: 'migrada', 'reactivada', 'sin_suscripcion' o 'nuevo_ya_tiene'.
    """
    worksheet = _sync_get_suscripciones_worksheet(spreadsheet_id)
    filas = worksheet.get_all_values()
    fila_vieja: list[str] | None = None
    fila_vieja_numero = 0
    fila_nueva: list[str] | None = None
    for numero, row in enumerate(filas, start=1):
        if not row:
            continue
        telefono = str(row[0]).strip()
        if telefono == telefono_anterior:
            fila_vieja = row
            fila_vieja_numero = numero
        elif telefono == telefono_nuevo:
            fila_nueva = row
    if fila_vieja is None:
        return "sin_suscripcion"

    estado_nuevo = ""
    if fila_nueva is not None and len(fila_nueva) > 2:
        estado_nuevo = str(fila_nueva[2]).strip().lower()
    if fila_nueva is not None and estado_nuevo in ESTADOS_CON_ACCESO:
        resultado = "nuevo_ya_tiene"
    else:
        fila_migrada = [telefono_nuevo] + [
            str(fila_vieja[i]) if i < len(fila_vieja) else ""
            for i in range(1, len(SUSCRIPCION_HEADERS))
        ]
        worksheet.append_row(
            fila_migrada,
            value_input_option=ValueInputOption.user_entered,
        )
        resultado = "reactivada" if fila_nueva is not None else "migrada"

    estado_viejo = str(fila_vieja[2]).strip().lower() if len(fila_vieja) > 2 else ""
    if estado_viejo != "cancelado":
        worksheet.update_cell(fila_vieja_numero, 3, "cancelado")
    return resultado


async def migrar_suscripcion(telefono_anterior: str, telefono_nuevo: str) -> str | None:
    """
    Muda el control comercial al cambiar de número (deuda #17): copia la fila de
    `Suscripciones` al número nuevo (salvo que su última fila tenga acceso) y revoca
    el acceso del número anterior marcándolo `cancelado`. Retorna 'migrada',
    'reactivada', 'sin_suscripcion' o 'nuevo_ya_tiene'; None si hubo un error (el
    pipeline lo registra y avisa).
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_migrar_suscripcion,
            spreadsheet_id,
            telefono_anterior,
            telefono_nuevo,
        )
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al migrar suscripción: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado al migrar suscripción: {e}")
        return None


# ==========================================
# FASE 6.1 - USUARIOS (ADR-0019): perfil persistente del alta guiada
# ==========================================
# La pestaña `Usuarios` es la persistencia real del onboarding. El estado en Redis
# (services/onboarding_service.py) es solo temporal (TTL 24h); al cerrar el alta se
# escribe/actualiza la fila del teléfono aquí.
USUARIOS_TAB_NAME = "Usuarios"
USUARIOS_HEADERS = [
    "telefono",
    "nombre",
    "tipo_uso",
    "espacio",
    "pais",
    "moneda",
    "zona",
    "categorias",
    "fecha_registro",
]


def _sync_get_usuarios_worksheet(spreadsheet_id: str) -> Any:
    """Devuelve la pestaña de usuarios, creándola con encabezados si no existe."""
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(USUARIOS_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=USUARIOS_TAB_NAME, rows=100, cols=12)
        worksheet.append_row(
            USUARIOS_HEADERS,
            value_input_option=ValueInputOption.user_entered,
        )
    return worksheet


def _sync_upsert_usuario(spreadsheet_id: str, datos: dict[str, Any]) -> bool:
    """Inserta o actualiza la fila del usuario (columna A = teléfono)."""
    worksheet = _sync_get_usuarios_worksheet(spreadsheet_id)
    telefono = str(datos.get("telefono", ""))
    fila = [str(datos.get(columna, "")) for columna in USUARIOS_HEADERS]
    phones = worksheet.col_values(1)
    matches = [i for i, phone in enumerate(phones, start=1) if phone == telefono]
    if matches:
        numero_fila = matches[-1]
        worksheet.update(
            f"A{numero_fila}:I{numero_fila}",
            [fila],
            value_input_option=ValueInputOption.user_entered,
        )
    else:
        worksheet.append_row(fila, value_input_option=ValueInputOption.user_entered)
    return True


async def upsert_usuario(datos: dict[str, Any]) -> bool:
    """
    Guarda el perfil del usuario en la pestaña `Usuarios` (Fase 6.1): crea la fila si
    no existe o la actualiza. Agrega `fecha_registro` si no viene. Nunca levanta
    excepción: devuelve False y deja log si Sheets falla (el flujo del bot continúa).
    """
    telefono = str(datos.get("telefono", ""))
    if not telefono:
        return False
    payload = dict(datos)
    if not payload.get("fecha_registro"):
        payload["fecha_registro"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(_sync_upsert_usuario, spreadsheet_id, payload)
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al guardar usuario: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado al guardar usuario: {e}")
        return False


def _sync_read_usuario(spreadsheet_id: str, sender_phone: str) -> dict[str, Any] | None:
    """Lee la fila del usuario por teléfono y la devuelve como dict o None."""
    worksheet = _sync_get_usuarios_worksheet(spreadsheet_id)
    phones = worksheet.col_values(1)
    matches = [i for i, phone in enumerate(phones, start=1) if phone == sender_phone]
    if not matches:
        return None
    values = list(worksheet.row_values(matches[-1]))
    if len(values) < len(USUARIOS_HEADERS):
        values += [""] * (len(USUARIOS_HEADERS) - len(values))
    return dict(zip(USUARIOS_HEADERS, values, strict=False))


async def obtener_usuario(sender_phone: str) -> dict[str, Any] | None:
    """
    Consulta el perfil del usuario en la pestaña `Usuarios` (Fase 6.1). Devuelve None
    si no existe o si Sheets falla.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(_sync_read_usuario, spreadsheet_id, sender_phone)
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al leer usuario: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado al leer usuario: {e}")
        return None


def _sync_actualizar_telefono_usuario(
    spreadsheet_id: str, telefono_anterior: str, telefono_nuevo: str
) -> bool:
    """Mueve la fila del usuario al número nuevo (spec 5.6)."""
    worksheet = _sync_get_usuarios_worksheet(spreadsheet_id)
    phones = worksheet.col_values(1)
    if telefono_nuevo in phones:
        return False
    matches = [i for i, phone in enumerate(phones, start=1) if phone == telefono_anterior]
    if not matches:
        return False
    worksheet.update_cell(matches[-1], 1, telefono_nuevo)
    return True


async def actualizar_telefono_usuario(telefono_anterior: str, telefono_nuevo: str) -> bool:
    """Actualiza el teléfono del perfil en `Usuarios` (Fase 6.1, cambio de número)."""
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_actualizar_telefono_usuario,
            spreadsheet_id,
            telefono_anterior,
            telefono_nuevo,
        )
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al cambiar teléfono: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado al cambiar teléfono: {e}")
        return False


def _sync_renombrar_pestana_cliente(
    spreadsheet_id: str, telefono_anterior: str, telefono_nuevo: str
) -> bool:
    """
    Renombra la pestaña de transacciones del cliente (spec 5.6). Endurecido
    (deuda #17): si la pestaña del número nuevo ya existe pero está vacía (solo
    encabezado), se reemplaza; si ya tiene historial, no se toca nada y se retorna
    False para que el pipeline avise en vez de pisar datos.
    """
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet_nueva = spreadsheet.worksheet(telefono_nuevo)
    except gspread.exceptions.WorksheetNotFound:
        worksheet_nueva = None
    if worksheet_nueva is not None:
        if len(worksheet_nueva.get_all_values()) > 1:
            return False
        spreadsheet.del_worksheet(worksheet_nueva)
    try:
        worksheet = spreadsheet.worksheet(telefono_anterior)
    except gspread.exceptions.WorksheetNotFound:
        return True
    worksheet.update_title(telefono_nuevo)
    return True


async def renombrar_pestana_cliente(telefono_anterior: str, telefono_nuevo: str) -> bool:
    """Renombra la pestaña del cliente para conservar su historial (spec 5.6)."""
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_renombrar_pestana_cliente,
            spreadsheet_id,
            telefono_anterior,
            telefono_nuevo,
        )
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al renombrar pestaña: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado al renombrar pestaña: {e}")
        return False


# ==========================================
# PASO 4 SPRINT — Presupuestos durables (D26: pestaña `Presupuestos`)
# ==========================================
PRESUPUESTOS_TAB_NAME = "Presupuestos"
PRESUPUESTOS_HEADERS = [
    "telefono",
    "categoria",
    "limite",
    "periodo",
    "alerta_80",
    "alerta_100",
    "actualizado",
]


def _sync_get_presupuestos_worksheet(spreadsheet_id: str) -> Any:
    """Devuelve la pestaña de presupuestos, creándola con encabezados si no existe."""
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(PRESUPUESTOS_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=PRESUPUESTOS_TAB_NAME, rows=200, cols=len(PRESUPUESTOS_HEADERS)
        )
        worksheet.append_row(
            PRESUPUESTOS_HEADERS,
            value_input_option=ValueInputOption.user_entered,
        )
    return worksheet


def _fila_presupuesto(row: list[str]) -> dict[str, str]:
    """Convierte una fila de la pestaña en dict tolerante a columnas faltantes."""
    return {
        "telefono": row[0] if len(row) > 0 else "",
        "categoria": row[1] if len(row) > 1 else "",
        "limite": row[2] if len(row) > 2 else "",
        "periodo": row[3] if len(row) > 3 else "",
        "alerta_80": row[4] if len(row) > 4 else "",
        "alerta_100": row[5] if len(row) > 5 else "",
    }


def _sync_leer_presupuestos(spreadsheet_id: str) -> list[dict[str, str]]:
    """Lee todas las filas de presupuestos (sin el encabezado)."""
    worksheet = _sync_get_presupuestos_worksheet(spreadsheet_id)
    filas = worksheet.get_all_values()
    return [_fila_presupuesto(row) for row in filas[1:] if row and str(row[0]).strip()]


def _sync_guardar_presupuesto(
    spreadsheet_id: str, telefono: str, categoria: str, limite: int
) -> bool:
    """
    Inserta o actualiza el presupuesto de un teléfono/categoría (una sola fuente:
    la pestaña `Presupuestos`, D26). El periodo V1 es mensual.
    """
    worksheet = _sync_get_presupuestos_worksheet(spreadsheet_id)
    filas = worksheet.get_all_values()
    ahora = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    for numero, row in enumerate(filas[1:], start=2):
        if not row:
            continue
        if (
            str(row[0]).strip() == telefono
            and str(row[1]).strip().lower() == categoria.strip().lower()
        ):
            worksheet.update_cell(numero, 3, limite)
            worksheet.update_cell(numero, 7, ahora)
            return True
    worksheet.append_row(
        [telefono, categoria, limite, "mensual", "", "", ahora],
        value_input_option=ValueInputOption.user_entered,
    )
    return True


def _sync_eliminar_presupuesto(spreadsheet_id: str, telefono: str, categoria: str) -> bool:
    """Borra la fila del presupuesto si existe. Retorna True si la encontró."""
    worksheet = _sync_get_presupuestos_worksheet(spreadsheet_id)
    filas = worksheet.get_all_values()
    for numero, row in enumerate(filas[1:], start=2):
        if not row:
            continue
        if (
            str(row[0]).strip() == telefono
            and str(row[1]).strip().lower() == categoria.strip().lower()
        ):
            worksheet.delete_rows(numero)
            return True
    return False


def _sync_marcar_alerta_presupuesto(
    spreadsheet_id: str, telefono: str, categoria: str, umbral: int, periodo: str
) -> bool:
    """Marca la alerta (80/100) del periodo para no repetirla. True si marcó."""
    worksheet = _sync_get_presupuestos_worksheet(spreadsheet_id)
    filas = worksheet.get_all_values()
    columna = 5 if umbral == 80 else 6
    for numero, row in enumerate(filas[1:], start=2):
        if not row:
            continue
        if (
            str(row[0]).strip() == telefono
            and str(row[1]).strip().lower() == categoria.strip().lower()
        ):
            worksheet.update_cell(numero, columna, periodo)
            return True
    return False


async def obtener_presupuestos_sheet() -> list[dict[str, str]]:
    """Lista de presupuestos persistidos en la pestaña `Presupuestos`."""
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(_sync_leer_presupuestos, spreadsheet_id)
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al leer presupuestos: {error}")
        return []
    except Exception as e:
        logger.error(f"Error inesperado al leer presupuestos: {e}")
        return []


async def guardar_presupuesto_sheet(telefono: str, categoria: str, limite: int) -> bool:
    """Persiste el presupuesto en la pestaña `Presupuestos` (D26)."""
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_guardar_presupuesto, spreadsheet_id, telefono, categoria, limite
        )
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al guardar presupuesto: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado al guardar presupuesto: {e}")
        return False


async def eliminar_presupuesto_sheet(telefono: str, categoria: str) -> bool:
    """Elimina el presupuesto de la pestaña `Presupuestos`."""
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_eliminar_presupuesto, spreadsheet_id, telefono, categoria
        )
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al eliminar presupuesto: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado al eliminar presupuesto: {e}")
        return False


async def marcar_alerta_presupuesto_sheet(
    telefono: str, categoria: str, umbral: int, periodo: str
) -> bool:
    """Marca en la pestaña que la alerta del umbral ya se envió en el periodo."""
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_marcar_alerta_presupuesto,
            spreadsheet_id,
            telefono,
            categoria,
            umbral,
            periodo,
        )
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al marcar alerta: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado al marcar alerta: {e}")
        return False


# ==========================================
# PASO 4 SPRINT — Preferencias del cliente (STOP/activar automáticos)
# ==========================================
PREFERENCIAS_TAB_NAME = "Preferencias"
PREFERENCIAS_HEADERS = ["telefono", "resumen_semanal", "actualizado"]


def _sync_get_preferencias_worksheet(spreadsheet_id: str) -> Any:
    """Devuelve la pestaña de preferencias, creándola con encabezados si no existe."""
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(PREFERENCIAS_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=PREFERENCIAS_TAB_NAME, rows=200, cols=len(PREFERENCIAS_HEADERS)
        )
        worksheet.append_row(
            PREFERENCIAS_HEADERS,
            value_input_option=ValueInputOption.user_entered,
        )
    return worksheet


def _sync_leer_preferencia_resumen(spreadsheet_id: str, telefono: str) -> str | None:
    """Lee la preferencia de resumen semanal ('si'/'no') o None si no hay fila."""
    worksheet = _sync_get_preferencias_worksheet(spreadsheet_id)
    phones = worksheet.col_values(1)
    matches = [i for i, phone in enumerate(phones, start=1) if phone == telefono]
    if not matches:
        return None
    values = worksheet.row_values(matches[-1])
    if len(values) < 2 or not values[1]:
        return None
    return str(values[1]).strip().lower()


def _sync_guardar_preferencia_resumen(spreadsheet_id: str, telefono: str, habilitado: bool) -> bool:
    """Inserta o actualiza la preferencia de resumen semanal del teléfono."""
    worksheet = _sync_get_preferencias_worksheet(spreadsheet_id)
    phones = worksheet.col_values(1)
    matches = [i for i, phone in enumerate(phones, start=1) if phone == telefono]
    ahora = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    valor = "si" if habilitado else "no"
    if matches:
        worksheet.update_cell(matches[-1], 2, valor)
        worksheet.update_cell(matches[-1], 3, ahora)
        return True
    worksheet.append_row(
        [telefono, valor, ahora],
        value_input_option=ValueInputOption.user_entered,
    )
    return True


async def leer_preferencia_resumen(telefono: str) -> bool:
    """True si el teléfono recibe el resumen semanal (default: sí, opt-out)."""
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        valor = await asyncio.to_thread(_sync_leer_preferencia_resumen, spreadsheet_id, telefono)
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al leer preferencias: {error}")
        return True
    except Exception as e:
        logger.error(f"Error inesperado al leer preferencias: {e}")
        return True
    return valor != "no"


async def guardar_preferencia_resumen(telefono: str, habilitado: bool) -> bool:
    """Guarda STOP/activar del resumen semanal en `Preferencias`."""
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_guardar_preferencia_resumen, spreadsheet_id, telefono, habilitado
        )
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al guardar preferencias: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado al guardar preferencias: {e}")
        return False


def _sync_leer_telefonos_con_acceso(spreadsheet_id: str) -> list[str]:
    """
    Lista los teléfonos con acceso comercial (última fila de `Suscripciones` en un
    estado con acceso). Se usa para el resumen semanal automático.
    """
    worksheet = _sync_get_suscripciones_worksheet(spreadsheet_id)
    filas = worksheet.get_all_values()
    ultimo_estado: dict[str, str] = {}
    for row in filas[1:]:
        if not row:
            continue
        telefono = str(row[0]).strip()
        if telefono:
            ultimo_estado[telefono] = str(row[2]).strip().lower() if len(row) > 2 else ""
    return [telefono for telefono, estado in ultimo_estado.items() if estado in ESTADOS_CON_ACCESO]


async def obtener_telefonos_con_acceso() -> list[str]:
    """Teléfonos con suscripción vigente (para notificaciones automáticas)."""
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(_sync_leer_telefonos_con_acceso, spreadsheet_id)
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al listar teléfonos: {error}")
        return []
    except Exception as e:
        logger.error(f"Error inesperado al listar teléfonos: {e}")
        return []
