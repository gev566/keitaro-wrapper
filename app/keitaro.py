"""Клиент Admin API Keitaro.

Документация: https://admin-api.docs.keitaro.io
Все запросы идут на <адрес трекера>/admin_api/v1 с заголовком Api-Key.
"""

from typing import Any

import httpx


class KeitaroError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class KeitaroClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 20.0):
        if not base_url or not api_key:
            raise KeitaroError("Не заданы KEITARO_URL и KEITARO_API_KEY в файле .env.")
        self._client = httpx.Client(
            base_url=base_url.rstrip("/") + "/admin_api/v1",
            headers={"Api-Key": api_key, "Accept": "application/json"},
            timeout=timeout,
        )

    def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as error:
            raise KeitaroError(f"Keitaro недоступен: {error}") from error

        if response.status_code >= 400:
            raise KeitaroError(_error_text(response), response.status_code)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise KeitaroError("Keitaro вернул ответ не в формате JSON.") from error

    # --- справочники ---

    def get_offers(self) -> list[dict]:
        return self._request("GET", "/offers") or []

    def get_domains(self) -> list[dict]:
        return self._request("GET", "/domains") or []

    def get_groups(self) -> list[dict]:
        return self._request("GET", "/groups", params={"type": "campaigns"}) or []

    def get_traffic_sources(self) -> list[dict]:
        return self._request("GET", "/traffic_sources") or []

    # --- кампании ---

    def get_campaigns(self) -> list[dict]:
        return self._request("GET", "/campaigns") or []

    def get_campaign(self, campaign_id: int) -> dict:
        return self._request("GET", f"/campaigns/{campaign_id}")

    def create_campaign(self, payload: dict) -> dict:
        return self._request("POST", "/campaigns", json=payload)

    def delete_campaign(self, campaign_id: int) -> None:
        self._request("DELETE", f"/campaigns/{campaign_id}")

    # --- потоки ---

    def get_campaign_streams(self, campaign_id: int) -> list[dict]:
        return self._request("GET", f"/campaigns/{campaign_id}/streams") or []

    def create_stream(self, payload: dict) -> dict:
        return self._request("POST", "/streams", json=payload)

    def update_stream(self, stream_id: int, payload: dict) -> dict:
        return self._request("PUT", f"/streams/{stream_id}", json=payload)


def _error_text(response: httpx.Response) -> str:
    """Достаёт понятный текст ошибки из ответа Keitaro."""
    try:
        data = response.json()
    except ValueError:
        return f"Keitaro ответил ошибкой {response.status_code}."
    if isinstance(data, dict):
        for key in ("error", "message", "errors"):
            if data.get(key):
                return f"Keitaro ответил ошибкой {response.status_code}: {data[key]}"
    return f"Keitaro ответил ошибкой {response.status_code}: {data}"

