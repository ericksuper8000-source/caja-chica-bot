from app.core.utils import extraer_datos_audio


def test_extraer_datos_audio_exitoso():
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "type": "audio",
                                    "audio": {"id": "123"},
                                    "from": "50612345678",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    resultado = extraer_datos_audio(payload)
    assert resultado == {"media_id": "123", "from_phone": "50612345678"}


def test_extraer_datos_audio_invalido():
    payload = {"entry": [{"changes": [{"value": {"messages": [{"type": "text"}]}}]}]}
    resultado = extraer_datos_audio(payload)
    assert resultado is None
