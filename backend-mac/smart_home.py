"""Domótica (Fase 2). Esqueleto listo para conectar Home Assistant."""
from __future__ import annotations


class SmartHomeController:
    """
    Punto único de entrada a la casa inteligente.

    Fase 2: implementar contra la API REST/WebSocket de Home Assistant
    (base_url tipo http://homeassistant.local:8123 + token de larga duración)
    y registrar en server.py las herramientas que llamen a estos métodos.
    Las que abran cerraduras o puertas deben declararse `critical=True`.
    """

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = base_url
        self.token = token

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    async def list_entities(self, domain: str | None = None) -> list[dict]:
        raise NotImplementedError("Fase 2: GET /api/states")

    async def get_state(self, entity_id: str) -> dict:
        raise NotImplementedError("Fase 2: GET /api/states/<entity_id>")

    async def call_service(self, domain: str, service: str, entity_id: str, **data) -> dict:
        raise NotImplementedError("Fase 2: POST /api/services/<domain>/<service>")
