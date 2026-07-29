from typing import Any

from pydantic import BaseModel, Field


class AudioMedia(BaseModel):
    id: str
    mime_type: str | None = None


class Message(BaseModel):
    from_: str = Field(alias="from")
    id: str = ""
    timestamp: str | None = None
    type: str = ""
    audio: AudioMedia | None = None


class Contact(BaseModel):
    profile: dict[str, Any] = {}
    wa_id: str = ""


class Value(BaseModel):
    messaging_product: str = "whatsapp"
    metadata: dict[str, Any] = {}
    contacts: list[Contact] = []
    messages: list[Message] = []


class Change(BaseModel):
    field: str = ""
    value: Value = Value()


class Entry(BaseModel):
    id: str = ""
    changes: list[Change] = []


class WebhookPayload(BaseModel):
    object: str
    entry: list[Entry]
