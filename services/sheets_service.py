import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import gspread
from gspread.utils import ValueInputOption  # Importamos el enumerado para el tipado

from app.config import settings
from services.modelo_service import (
    ESTADOS_ACTIVOS,
    TRANSACTION_HEADERS,
    es_fila_vacia,
    fila_a_movimiento,
    migrar_filas_legacy,
    movimiento_a_fila,
    nuevo_movimiento_id,
    tipo_encabezado,
)
from services.politica_service import POLITICA_VERSION
from services.suscripcion_service import ESTADOS_CON_ACCESO

logger = logging.getLogger(__name__)

_sheets_client: Any = None


class MovimientoAnuladoError(Exception):
    """Se intentó corregir un movimiento anulado (A08: primero se reactiva)."""

    def __init__(self, movimiento: dict[str, Any]) -> None:
        self.movimiento = movimiento
        super().__init__("movimiento anulado")


# Fase 6.5.1 — Consentimiento (ADR-0011, Ley 8968). En MVP la "tabla usuarios"
# se materializa como una pestaña del mismo Google Sheet (ADR-0002/0009).
CONSENT_TAB_NAME = "Consentimiento"
CONSENT_HEADERS = ["telefono", "estado", "fecha", "version_politica"]

# Fase 6.5.2 — Aislamiento por pestañas (ADR-0009). Cada cliente escribe SOLO en su
# pestaña (título = teléfono), creada perezosamente con el encabezado canónico (A02).
# `TRANSACTION_HEADERS` se importa de `services.modelo_service` (13 columnas).
AUDITORIA_TAB_NAME = "Auditoria"
AUDITORIA_HEADERS = [
    "auditoria_id",
    "entidad",
    "entidad_id",
    "accion",
    "antes",
    "despues",
    "actor_id",
    "motivo",
    "fecha",
]


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
    el encabezado canónico si no existe (ADR-0009, aislamiento por pestañas). Cada
    cliente escribe SOLO en su pestaña dentro del mismo spreadsheet.
    """
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(sender_phone)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=sender_phone, rows=100, cols=len(TRANSACTION_HEADERS)
        )
        worksheet.append_row(
            TRANSACTION_HEADERS,
            value_input_option=ValueInputOption.user_entered,
        )
    return worksheet


def _parece_fila_dato(fila: list[Any]) -> bool:
    """Heurística para hojas sin encabezado reconocible: ¿la primera fila es un dato?"""
    if not fila:
        return False
    try:
        int(float(str(fila[1]).replace(",", "")))
    except (IndexError, TypeError, ValueError):
        return False
    return bool(str(fila[0]).strip())


def _movimiento_de_fila(fila: list[Any], tipo: str = "") -> dict[str, Any]:
    """
    Normaliza una fila de una pestaña cuyo encabezado ya conocemos. Evita depender del
    largo de la fila (Sheets recorta celdas vacías del final) y no inventa IDs.
    """
    valores = list(fila)
    if tipo == "canonico":
        valores += [""] * max(0, len(TRANSACTION_HEADERS) - len(valores))
    return fila_a_movimiento(valores)


def _sync_escribir_tab_canonica(worksheet: Any, filas: list[list[Any]]) -> None:
    """
    Reescribe una pestaña con el encabezado canónico y las filas dadas.

    Se escribe primero y se limpia la cola después (no al revés): si la escritura
    falla, la hoja conserva su contenido anterior. La migración nunca debe perder
    filas ni montos aunque la API falle a mitad de camino.
    """
    total_nuevo = len(filas) + 1
    worksheet.update(
        f"A1:M{total_nuevo}",
        [TRANSACTION_HEADERS, *filas],
        value_input_option=ValueInputOption.user_entered,
    )
    existentes = len(worksheet.get_all_values())
    if existentes > total_nuevo:
        worksheet.batch_clear([f"A{total_nuevo + 1}:M{existentes}"])


def _sync_migrar_pestana(
    spreadsheet_id: str, sender_phone: str, worksheet: Any | None = None
) -> dict[str, Any]:
    """
    Migra perezosamente la pestaña histórica de 5 columnas al modelo canónico.

    Devuelve el reporte de conciliación (`filas_antes/despues`, totales y `cuadra`).
    Si `cuadra` es False no escribe nada y lanza ValueError: una migración que no
    concilia es un incidente, no una advertencia.
    """
    worksheet = worksheet or _sync_get_client_worksheet(spreadsheet_id, sender_phone)
    values = worksheet.get_all_values()
    if not values:
        worksheet.update(
            "A1:M1",
            [TRANSACTION_HEADERS],
            value_input_option=ValueInputOption.user_entered,
        )
        return {"migrada": True, "filas_antes": 0, "filas_despues": 0, "cuadra": True}

    tipo = tipo_encabezado(values[0])
    if tipo == "canonico":
        return {"migrada": False, "filas_antes": len(values) - 1, "cuadra": True}
    if tipo == "legacy":
        datos = values[1:]
    elif _parece_fila_dato(values[0]):
        datos = values
    else:
        datos = values[1:]

    filas_canonicas, reporte = migrar_filas_legacy(datos, sender_phone)
    if not reporte["cuadra"]:
        logger.error(
            "migracion: la pestaña de %s NO concilia; no se escribe: %s",
            sender_phone,
            reporte,
        )
        raise ValueError(f"migración sin conciliación para {sender_phone}: {reporte}")

    _sync_escribir_tab_canonica(worksheet, filas_canonicas)
    _sync_registrar_auditoria(
        spreadsheet_id,
        "pestana",
        sender_phone,
        "crear",
        None,
        reporte,
        "sistema",
        "migracion_esquema_canonico",
    )
    logger.info("migracion: pestaña de %s migrada al modelo canónico: %s", sender_phone, reporte)
    return {"migrada": True, **reporte}


def _sync_asegurar_esquema_canonico(worksheet: Any, sender_phone: str) -> dict[str, Any]:
    """Garantiza el encabezado canónico antes de escribir o corregir."""
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    return _sync_migrar_pestana(spreadsheet_id, sender_phone, worksheet=worksheet)


def _sync_append_row(spreadsheet_id: str, movimiento: dict[str, Any], sender_phone: str) -> None:
    """
    Escribe un movimiento canónico en la pestaña del cliente. Si la pestaña todavía
    está en el formato histórico, primero la migra (una sola vez) y luego agrega.
    """
    worksheet = _sync_get_client_worksheet(spreadsheet_id, sender_phone)
    _sync_asegurar_esquema_canonico(worksheet, sender_phone)
    worksheet.append_row(
        movimiento_a_fila(movimiento),
        value_input_option=ValueInputOption.user_entered,
    )


def _sync_leer_movimientos(
    spreadsheet_id: str, sender_phone: str, *, incluir_inactivos: bool = True
) -> list[dict[str, Any]]:
    """
    Lee los movimientos de la pestaña del cliente y los normaliza al contrato canónico.

    No migra ni escribe: es una lectura compatible con pestañas históricas. Cada
    movimiento incluye `_fila` (número de fila en Sheets, 1-based) para las
    operaciones que reescriben en el lugar.
    """
    worksheet = _sync_get_client_worksheet(spreadsheet_id, sender_phone)
    values = worksheet.get_all_values()
    if not values:
        return []

    tipo = tipo_encabezado(values[0])
    if tipo in ("legacy", "canonico"):
        filas = values[1:]
        inicio = 2
    elif _parece_fila_dato(values[0]):
        filas = values
        inicio = 1
    else:
        filas = values[1:]
        inicio = 2

    movimientos: list[dict[str, Any]] = []
    for numero, fila in enumerate(filas, start=inicio):
        if es_fila_vacia(fila):
            continue
        movimiento = _movimiento_de_fila(fila, tipo)
        if not incluir_inactivos and movimiento["estado"] not in ESTADOS_ACTIVOS:
            continue
        movimiento["_fila"] = numero
        movimientos.append(movimiento)
    return movimientos


def _movimiento_desde_transaccion(
    transaction_data: dict[str, Any], sender_phone: str
) -> dict[str, Any]:
    """Construye un movimiento canónico a partir del JSON del parser/LLM."""
    fecha_actual = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    try:
        monto = int(transaction_data.get("monto") or 0)
    except (TypeError, ValueError):
        monto = 0

    tipo = str(transaction_data.get("tipo_movimiento") or "").strip().lower()
    if tipo not in ("ingreso", "gasto", "transferencia", "reembolso", "devolucion"):
        # Compatibilidad: antes, sin tipo explícito, todo positivo era Gasto.
        tipo = "gasto"
    if monto < 0:
        tipo = "gasto"

    return {
        "fecha_movimiento": str(transaction_data.get("fecha_movimiento") or fecha_actual),
        "monto_centimos": abs(monto) * 100,
        "monto": -abs(monto) if tipo == "gasto" else abs(monto),
        "categoria": str(transaction_data.get("categoria") or "Otros"),
        "detalle": str(transaction_data.get("detalle") or ""),
        "telefono": sender_phone,
        "movimiento_id": nuevo_movimiento_id(),
        "tipo_movimiento": tipo,
        "moneda": str(transaction_data.get("moneda") or "CRC"),
        "contexto_tipo": str(transaction_data.get("contexto_tipo") or "personal"),
        "estado": "confirmado",
        "version": 1,
        "fecha_registro": fecha_actual,
        "origen": str(transaction_data.get("origen") or "chat"),
    }


def _merge_delta_con_movimiento(delta: dict[str, Any], anterior: dict[str, Any]) -> dict[str, Any]:
    """
    Fusiona el delta de una corrección con el movimiento anterior.

    Semántica delta (ADR-0012): `None` o monto 0 = "no mencionado" → se conserva.
    Devuelve los campos financieros que cambian; no modifica identidad ni fecha.
    """
    tipo = delta.get("tipo_movimiento")
    if tipo is None:
        tipo = anterior["tipo_movimiento"]
    tipo_norm = str(tipo).strip().lower()

    monto = delta.get("monto")
    if not monto:
        monto_centimos = int(anterior["monto_centimos"])
        monto_abs = monto_centimos // 100
        monto = -monto_abs if anterior["tipo_movimiento"] == "gasto" else monto_abs
    else:
        try:
            monto = int(monto)
        except (TypeError, ValueError):
            monto = 0
        if tipo_norm == "gasto" and monto > 0:
            monto = -monto
        elif tipo_norm == "ingreso" and monto < 0:
            monto = abs(monto)

    if monto < 0:
        tipo_final = "gasto"
    elif monto > 0:
        tipo_final = "ingreso" if tipo_norm != "gasto" else "gasto"
    else:
        tipo_final = anterior["tipo_movimiento"]

    return {
        "monto": monto,
        "monto_centimos": abs(monto) * 100,
        "tipo_movimiento": tipo_final,
        "categoria": delta.get("categoria") or anterior["categoria"],
        "detalle": delta.get("detalle") or anterior["detalle"],
    }


def _sync_corregir_ultimo(
    spreadsheet_id: str, sender_phone: str, transaction_data: dict[str, Any]
) -> dict[str, Any]:
    """
    Corrige el último movimiento activo del cliente (delta, ADR-0012), sin crear una
    fila nueva. Actualiza estado a `corregido`, incrementa `version` y deja el
    antes/después en auditoría. Lanza LookupError si no hay movimientos.
    """
    worksheet = _sync_get_client_worksheet(spreadsheet_id, sender_phone)
    _sync_asegurar_esquema_canonico(worksheet, sender_phone)
    movimientos = _sync_leer_movimientos(spreadsheet_id, sender_phone, incluir_inactivos=True)
    activos = [m for m in movimientos if m["estado"] in ESTADOS_ACTIVOS]
    if not activos:
        if movimientos:
            raise MovimientoAnuladoError(movimientos[-1])
        raise LookupError(f"sin transacciones previas para {sender_phone}")

    anterior = activos[-1]
    antes = {clave: valor for clave, valor in anterior.items() if clave != "_fila"}
    cambios = _merge_delta_con_movimiento(transaction_data, antes)
    nuevo = dict(antes)
    nuevo.update(cambios)
    nuevo["estado"] = "corregido"
    nuevo["version"] = int(antes.get("version") or 1) + 1

    fila = int(anterior["_fila"])
    worksheet.update(
        f"A{fila}:M{fila}",
        [movimiento_a_fila(nuevo)],
        value_input_option=ValueInputOption.user_entered,
    )
    _sync_registrar_auditoria(
        spreadsheet_id,
        "movimiento",
        str(nuevo["movimiento_id"]),
        "corregir",
        antes,
        nuevo,
        sender_phone,
    )
    return {
        "movimiento_id": nuevo["movimiento_id"],
        "movimiento": nuevo,
        "antes": antes,
        "despues": nuevo,
        "fila": fila,
        "monto": cambios["monto"],
        "categoria": nuevo["categoria"],
        "detalle": nuevo["detalle"],
    }


async def append_transaction_to_sheet(
    transaction_data: dict[str, Any], sender_phone: str
) -> dict[str, Any] | None:
    """
    Inserta un movimiento canónico en la pestaña del cliente (ADR-0009). Si la
    pestaña es histórica, la migra antes de escribir. Devuelve el movimiento creado
    (con `movimiento_id`) o None si Sheets falla. La auditoría se registra después
    de la escritura y su fallo no invalida el movimiento ya guardado.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID

    try:
        movimiento = _movimiento_desde_transaccion(transaction_data, sender_phone)
        await asyncio.to_thread(_sync_append_row, spreadsheet_id, movimiento, sender_phone)
        await registrar_auditoria(
            "movimiento",
            str(movimiento["movimiento_id"]),
            "crear",
            None,
            movimiento,
            sender_phone,
        )
        logger.info(f"Fila canónica insertada en Sheets: {movimiento}")
        return movimiento

    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al escribir en Google Sheets: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado en el servicio de Sheets: {e}")
        return None


async def update_last_transaction_to_sheet(
    transaction_data: dict[str, Any], sender_phone: str
) -> dict[str, Any] | None:
    """
    Corrige el último movimiento activo del remitente con semántica delta (ADR-0012).
    Devuelve `{movimiento_id, antes, despues, fila, monto, categoria, detalle}` o None
    si no hay movimientos previos / Sheets falla. Lanza MovimientoAnuladoError si
    todos los movimientos existentes están anulados (A08: primero se reactiva).
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID

    try:
        resultado = await asyncio.to_thread(
            _sync_corregir_ultimo, spreadsheet_id, sender_phone, transaction_data
        )
        logger.info(f"Transacción corregida en Sheets para {sender_phone}: {resultado['despues']}")
        return resultado

    except LookupError as error:
        logger.info(f"No hay transacción previa del usuario {sender_phone}: {error}")
        return None
    except MovimientoAnuladoError:
        raise
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al corregir en Google Sheets: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado en el servicio de Sheets (corregir): {e}")
        return None


# ==========================================
# A02/A08 — AUDITORÍA Y ESTADOS DEL MOVIMIENTO
# ==========================================
def _sync_get_auditoria_worksheet(spreadsheet_id: str) -> Any:
    """Devuelve la pestaña `Auditoria`, creándola con encabezados si no existe."""
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(AUDITORIA_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=AUDITORIA_TAB_NAME, rows=1000, cols=len(AUDITORIA_HEADERS)
        )
        worksheet.append_row(
            AUDITORIA_HEADERS,
            value_input_option=ValueInputOption.user_entered,
        )
    return worksheet


def _json_auditoria(valor: dict[str, Any] | None) -> str:
    """Serializa el antes/después sin campos internos y sin reventar por tipos raros."""
    if valor is None:
        return ""
    limpio = {clave: dato for clave, dato in valor.items() if not str(clave).startswith("_")}
    return json.dumps(limpio, ensure_ascii=False, sort_keys=True, default=str)


def _sync_registrar_auditoria(
    spreadsheet_id: str,
    entidad: str,
    entidad_id: str,
    accion: str,
    antes: dict[str, Any] | None,
    despues: dict[str, Any] | None,
    actor_id: str,
    motivo: str = "",
) -> bool:
    """Agrega una fila al registro de auditoría (A02 §2.13 / A08 §5.5)."""
    worksheet = _sync_get_auditoria_worksheet(spreadsheet_id)
    worksheet.append_row(
        [
            nuevo_movimiento_id(),
            entidad,
            entidad_id,
            accion,
            _json_auditoria(antes),
            _json_auditoria(despues),
            actor_id,
            motivo,
            datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
        ],
        value_input_option=ValueInputOption.user_entered,
    )
    return True


async def registrar_auditoria(
    entidad: str,
    entidad_id: str,
    accion: str,
    antes: dict[str, Any] | None,
    despues: dict[str, Any] | None,
    actor_id: str,
    motivo: str = "",
) -> bool:
    """
    Registra una acción en la pestaña `Auditoria`. Nunca levanta: la escritura
    financiera ya ocurrió y un fallo de auditoría no debe convertirla en error.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_registrar_auditoria,
            spreadsheet_id,
            entidad,
            entidad_id,
            accion,
            antes,
            despues,
            actor_id,
            motivo,
        )
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al registrar auditoría: {error}")
        return False
    except Exception as e:
        logger.error(f"Error inesperado al registrar auditoría: {e}")
        return False


def _buscar_movimiento(
    movimientos: list[dict[str, Any]],
    movimiento_id: str | None,
    *,
    solo_activos: bool,
) -> dict[str, Any] | None:
    """Busca por ID (o toma el último) dentro de la lista, opcionalmente solo activos."""
    candidatos = (
        [m for m in movimientos if m["estado"] in ESTADOS_ACTIVOS] if solo_activos else movimientos
    )
    if movimiento_id is None:
        return candidatos[-1] if candidatos else None
    for movimiento in candidatos:
        if str(movimiento.get("movimiento_id")) == movimiento_id:
            return movimiento
    return None


def _sync_cambiar_estado(
    spreadsheet_id: str,
    sender_phone: str,
    movimiento_id: str | None,
    estado_nuevo: str,
    accion: str,
    motivo: str = "",
    *,
    solo_activos: bool = False,
) -> dict[str, Any] | None:
    """
    Cambia el estado de un movimiento en su misma fila (anulación lógica, A08/D18),
    incrementa `version` y deja rastro en auditoría. Idempotente: si el estado ya es
    el pedido, no reescribe ni audita.
    """
    worksheet = _sync_get_client_worksheet(spreadsheet_id, sender_phone)
    _sync_asegurar_esquema_canonico(worksheet, sender_phone)
    movimientos = _sync_leer_movimientos(spreadsheet_id, sender_phone)
    objetivo = _buscar_movimiento(movimientos, movimiento_id, solo_activos=solo_activos)
    if objetivo is None:
        return None

    antes = {clave: valor for clave, valor in objetivo.items() if clave != "_fila"}
    if antes["estado"] == estado_nuevo:
        return {
            "movimiento_id": antes["movimiento_id"],
            "movimiento": antes,
            "antes": antes,
            "despues": antes,
            "fila": int(objetivo["_fila"]),
            "sin_cambio": True,
        }

    despues = dict(antes)
    despues["estado"] = estado_nuevo
    despues["version"] = int(antes.get("version") or 1) + 1
    fila = int(objetivo["_fila"])
    worksheet.update(
        f"A{fila}:M{fila}",
        [movimiento_a_fila(despues)],
        value_input_option=ValueInputOption.user_entered,
    )
    _sync_registrar_auditoria(
        spreadsheet_id,
        "movimiento",
        str(despues["movimiento_id"]),
        accion,
        antes,
        despues,
        sender_phone,
        motivo,
    )
    return {
        "movimiento_id": despues["movimiento_id"],
        "movimiento": despues,
        "antes": antes,
        "despues": despues,
        "fila": fila,
        "sin_cambio": False,
    }


def _sync_revertir_movimiento(
    spreadsheet_id: str,
    sender_phone: str,
    movimiento_id: str,
    antes: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Deshace una corrección restaurando los campos financieros previos (D23).

    La identidad (`movimiento_id`), el teléfono y la fecha de registro no se tocan;
    `version` se incrementa para dejar rastro de concurrencia y la auditoría registra
    `deshacer` con el antes/después completo. Solo aplica a movimientos activos: si
    el movimiento fue anulado después de la corrección, la última acción ya no es la
    corrección y no corresponde revertirla.
    """
    worksheet = _sync_get_client_worksheet(spreadsheet_id, sender_phone)
    _sync_asegurar_esquema_canonico(worksheet, sender_phone)
    movimientos = _sync_leer_movimientos(spreadsheet_id, sender_phone)
    objetivo = _buscar_movimiento(movimientos, movimiento_id, solo_activos=False)
    if objetivo is None or objetivo["estado"] not in ESTADOS_ACTIVOS:
        return None

    actual = {clave: valor for clave, valor in objetivo.items() if clave != "_fila"}
    restaurado = dict(actual)
    for campo in (
        "fecha_movimiento",
        "monto_centimos",
        "categoria",
        "detalle",
        "tipo_movimiento",
        "moneda",
        "contexto_tipo",
        "estado",
    ):
        if antes.get(campo) is not None:
            restaurado[campo] = antes[campo]
    restaurado["version"] = int(actual.get("version") or 1) + 1

    fila = int(objetivo["_fila"])
    worksheet.update(
        f"A{fila}:M{fila}",
        [movimiento_a_fila(restaurado)],
        value_input_option=ValueInputOption.user_entered,
    )
    _sync_registrar_auditoria(
        spreadsheet_id,
        "movimiento",
        movimiento_id,
        "deshacer",
        actual,
        restaurado,
        sender_phone,
        "deshacer corrección",
    )
    return {
        "movimiento_id": movimiento_id,
        "movimiento": restaurado,
        "antes": actual,
        "despues": restaurado,
        "fila": fila,
        "sin_cambio": False,
    }


async def anular_movimiento(
    sender_phone: str,
    movimiento_id: str | None = None,
    motivo: str = "",
    *,
    accion: str = "anular",
) -> dict[str, Any] | None:
    """
    Anula lógicamente un movimiento (D18). Sin ID, anula el último activo. Devuelve
    el resultado con antes/después o None si no hay un movimiento que anular.

    `accion` permite distinguir un deshacer de un registro (A08/D23) en la auditoría.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_cambiar_estado,
            spreadsheet_id,
            sender_phone,
            movimiento_id,
            "anulado",
            accion,
            motivo,
            solo_activos=True,
        )
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al anular movimiento: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado al anular movimiento: {e}")
        return None


async def reactivar_movimiento(sender_phone: str, movimiento_id: str) -> dict[str, Any] | None:
    """
    Reactiva un movimiento anulado (lo devuelve a `confirmado`). Se exige el ID:
    reactivar "el último" sin confirmación sería ambiguo y peligroso.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_cambiar_estado,
            spreadsheet_id,
            sender_phone,
            movimiento_id,
            "confirmado",
            "reactivar",
        )
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al reactivar movimiento: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado al reactivar movimiento: {e}")
        return None


async def restaurar_movimiento(
    sender_phone: str, movimiento_id: str, estado: str = "confirmado"
) -> dict[str, Any] | None:
    """
    Restaura un movimiento al estado anterior por "deshacé" (D23). La auditoría
    registra la acción `deshacer`, distinta de una reactivación manual.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_cambiar_estado,
            spreadsheet_id,
            sender_phone,
            movimiento_id,
            estado,
            "deshacer",
        )
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al restaurar movimiento: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado al restaurar movimiento: {e}")
        return None


async def revertir_movimiento(
    sender_phone: str, movimiento_id: str, antes: dict[str, Any]
) -> dict[str, Any] | None:
    """
    Deshace una corrección devolviendo el movimiento al snapshot previo (D23). La
    auditoría queda como `deshacer`, no como una corrección nueva.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_revertir_movimiento,
            spreadsheet_id,
            sender_phone,
            movimiento_id,
            antes,
        )
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al revertir corrección: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado al revertir corrección: {e}")
        return None


def _sync_sin_fila(movimiento: dict[str, Any]) -> dict[str, Any]:
    return {clave: valor for clave, valor in movimiento.items() if clave != "_fila"}


async def obtener_movimientos_cliente(
    sender_phone: str, *, incluir_inactivos: bool = True
) -> list[dict[str, Any]]:
    """
    Lectura canónica de los movimientos del cliente (dicts con estado, tipo, ID y
    montos en céntimos). Compatible con pestañas históricas: las normaliza al vuelo.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        movimientos = await asyncio.to_thread(
            _sync_leer_movimientos,
            spreadsheet_id,
            sender_phone,
            incluir_inactivos=incluir_inactivos,
        )
        return [_sync_sin_fila(movimiento) for movimiento in movimientos]
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al leer movimientos: {error}")
        return []
    except Exception as e:
        logger.error(f"Error inesperado al leer movimientos: {e}")
        return []


def _json_o_texto(valor: str) -> Any:
    """Convierte el antes/después de auditoría en dict; si no es JSON, lo deja igual."""
    if not valor:
        return None
    try:
        return json.loads(valor)
    except (TypeError, ValueError):
        return valor


def _sync_leer_historial(spreadsheet_id: str, actor_id: str, limite: int) -> list[dict[str, Any]]:
    """Lee la pestaña de auditoría y devuelve las últimas acciones de un actor."""
    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(AUDITORIA_TAB_NAME)
    except gspread.exceptions.WorksheetNotFound:
        return []

    filas = worksheet.get_all_values()
    historial: list[dict[str, Any]] = []
    for fila in filas[1:]:
        if len(fila) < 7 or str(fila[6]).strip() != actor_id:
            continue
        historial.append(
            {
                "auditoria_id": fila[0],
                "entidad": fila[1],
                "entidad_id": fila[2],
                "accion": fila[3],
                "antes": _json_o_texto(fila[4]),
                "despues": _json_o_texto(fila[5]),
                "actor_id": fila[6],
                "motivo": fila[7] if len(fila) > 7 else "",
                "fecha": fila[8] if len(fila) > 8 else "",
            }
        )
    return historial[-limite:]


async def obtener_historial(sender_phone: str, limite: int = 20) -> list[dict[str, Any]]:
    """
    Historial reciente del propio usuario (A08 §5.5): acciones `crear`, `corregir`,
    `anular`, `reactivar` o `deshacer`, con antes/después. Filtrado por `actor_id`;
    nunca mezcla movimientos de otros teléfonos.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(_sync_leer_historial, spreadsheet_id, sender_phone, limite)
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al leer historial: {error}")
        return []
    except Exception as e:
        logger.error(f"Error inesperado al leer historial: {e}")
        return []


async def migrar_pestana_cliente(sender_phone: str) -> dict[str, Any] | None:
    """
    Migra explícitamente la pestaña de un cliente al modelo canónico. Devuelve el
    reporte de conciliación o None si Sheets falla. Es la misma migración perezosa
    que ejecutan las escrituras, expuesta para operación y pruebas.
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(_sync_migrar_pestana, spreadsheet_id, sender_phone)
    except gspread.exceptions.APIError as error:
        logger.error(f"Error de API de gspread al migrar pestaña: {error}")
        return None
    except Exception as e:
        logger.error(f"Error inesperado al migrar pestaña: {e}")
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
def _sync_read_client_rows(
    spreadsheet_id: str, sender_phone: str, *, incluir_inactivos: bool = False
) -> list[list[Any]]:
    """
    Vista de lectura compatible para reportes, consultas y exportación: filas
    canónicas de 13 columnas con `monto_centimos` positivo. Por defecto excluye
    `anulado` y `pendiente` (A02 §4.4); `incluir_inactivos=True` los conserva para
    la exportación de datos del usuario. No migra ni escribe.
    """
    movimientos = _sync_leer_movimientos(
        spreadsheet_id, sender_phone, incluir_inactivos=incluir_inactivos
    )
    return [movimiento_a_fila(movimiento, generar_id=False) for movimiento in movimientos]


async def obtener_transacciones_cliente(
    sender_phone: str, *, incluir_inactivos: bool = False
) -> list[list[Any]]:
    """
    Lee las transacciones del cliente desde su pestaña en el contrato de lectura
    canónico (A02). Retorna filas (sin encabezado) o [] si no hay movimientos o
    hubo un error. `incluir_inactivos=True` incluye anulados/pendientes (ARCO).
    """
    spreadsheet_id = settings.GOOGLE_SHEETS_SPREADSHEET_ID
    try:
        return await asyncio.to_thread(
            _sync_read_client_rows,
            spreadsheet_id,
            sender_phone,
            incluir_inactivos=incluir_inactivos,
        )
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


def _normalizar_categoria_sheet(valor: str) -> str:
    """Normaliza categorías para comparar (minúsculas y sin tildes)."""
    texto = str(valor).strip().lower()
    for origen, destino in (
        ("á", "a"),
        ("é", "e"),
        ("í", "i"),
        ("ó", "o"),
        ("ú", "u"),
        ("ü", "u"),
    ):
        texto = texto.replace(origen, destino)
    return texto


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
        if str(row[0]).strip() == telefono and _normalizar_categoria_sheet(
            row[1]
        ) == _normalizar_categoria_sheet(categoria):
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
        if str(row[0]).strip() == telefono and _normalizar_categoria_sheet(
            row[1]
        ) == _normalizar_categoria_sheet(categoria):
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
        if str(row[0]).strip() == telefono and _normalizar_categoria_sheet(
            row[1]
        ) == _normalizar_categoria_sheet(categoria):
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
