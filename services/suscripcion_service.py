from typing import Any

# Fase 7.2.1 — Gate comercial (ADR-0013): la suscripción es el estado COMERCIAL y va
# separada del consentimiento legal (Ley 8968). El bot solo la lee desde la pestaña
# `Suscripciones`; la actualiza a mano el fundador.
ESTADOS_CON_ACCESO = ("activo", "gratis", "de_prueba")

TEXTO_SUSCRIPCION_VENCIDA = (
    "Tu suscripción venció, así que no puedo registrar más movimientos por ahora. "
    "Tus datos quedan guardados intactos. Para reactivar el servicio, avisale a "
    "quien te activó el bot y en cuanto se confirme el pago vuelvo a funcionar."
)

TEXTO_SUSCRIPCION_SUSPENDIDA = (
    "Tu servicio quedó pausado por el momento, así que no estoy registrando "
    "movimientos. Tus datos quedan guardados intactos. Avisale a quien te activó "
    "el bot para reactivarlo."
)

TEXTO_SUSCRIPCION_NO_ACTIVA = (
    "Tu cuenta todavía no está activa para registrar movimientos. Avisale a quien "
    "te activó el bot para dejarla lista y volvé a intentar."
)


def _normalizar_estado(estado: Any) -> str:
    """Normaliza el estado escrito a mano en la hoja: minúsculas y sin espacios extra."""
    return str(estado or "").strip().lower()


def suscripcion_permite_uso(suscripcion: dict[str, Any] | None) -> bool:
    """
    True si la suscripción del teléfono tiene un estado con acceso (Fase 7.2.1,
    ADR-0013): 'activo', 'gratis' o 'de_prueba'. None (sin registro) y los estados
    'vencido', 'suspendido' o 'cancelado' no permiten procesar. Ante la duda se
    bloquea: revocar el acceso debe ser cambiar un dato, no una feature.
    """
    if suscripcion is None:
        return False
    return _normalizar_estado(suscripcion.get("estado")) in ESTADOS_CON_ACCESO


def mensaje_suscripcion_no_activa(suscripcion: dict[str, Any] | None) -> str:
    """
    Mensaje para un teléfono bloqueado por el gate comercial, según su estado
    (Fase 7.2.1, ADR-0013/7.5): 'vencido' → aviso de vencimiento con cómo reactivar;
    'suspendido' → aviso de pausa; sin registro o cualquier otro estado → aviso de
    cuenta no activa.
    """
    estado = _normalizar_estado(suscripcion.get("estado") if suscripcion else "")
    if estado == "vencido":
        return TEXTO_SUSCRIPCION_VENCIDA
    if estado == "suspendido":
        return TEXTO_SUSCRIPCION_SUSPENDIDA
    return TEXTO_SUSCRIPCION_NO_ACTIVA
