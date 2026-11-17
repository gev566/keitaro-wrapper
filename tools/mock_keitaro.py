"""Заглушка Keitaro для локальной проверки без доступа к настоящему трекеру.

Запуск:  uvicorn tools.mock_keitaro:app --port 9000
В .env:  KEITARO_URL=http://127.0.0.1:9000  и  KEITARO_API_KEY=mock

Повторяет только те методы Admin API, которыми пользуется приложение.
Данные хранятся в памяти и пропадают при перезапуске.
"""

from fastapi import Body, FastAPI, Header, HTTPException

app = FastAPI(title="Mock Keitaro")

OFFERS = [
    {"id": 3717, "name": "Miaflow [BEAUTY-RO-BE_0008]", "state": "active"},
    {"id": 3749, "name": "Miaflow [BEAUTY-RO-BE_0009]", "state": "active"},
    {"id": 11111, "name": "FitoMishki [Weight Loss-CO-DT_0309]", "state": "active"},
    {"id": 11112, "name": "Oxys [BEAUTY-CL-BE_0155]", "state": "active"},
]
DOMAINS = [{"id": 1, "name": "https://in.example.com/", "state": "active"}]
GROUPS = [{"id": 1, "name": "FORTESTS", "type": "campaigns"}]
SOURCES = [{"id": 1, "name": "FORTESTS"}]
CAMPAIGNS: dict[int, dict] = {}
STREAMS: dict[int, dict] = {}
counter = {"id": 1000}


def next_id() -> int:
    counter["id"] += 1
    return counter["id"]


def check(api_key: str | None) -> None:
    if not api_key:
        raise HTTPException(401, "Api-Key header is required")


@app.get("/admin_api/v1/offers")
def offers(api_key: str | None = Header(None)):
    check(api_key)
    return OFFERS


@app.get("/admin_api/v1/domains")
def domains(api_key: str | None = Header(None)):
    check(api_key)
    return DOMAINS


@app.get("/admin_api/v1/groups")
def groups(api_key: str | None = Header(None)):
    check(api_key)
    return GROUPS


@app.get("/admin_api/v1/traffic_sources")
def sources(api_key: str | None = Header(None)):
    check(api_key)
    return SOURCES


@app.get("/admin_api/v1/campaigns")
def campaigns(api_key: str | None = Header(None)):
    check(api_key)
    return list(CAMPAIGNS.values())


@app.post("/admin_api/v1/campaigns")
def create_campaign(payload: dict = Body(...), api_key: str | None = Header(None)):
    check(api_key)
    campaign = {"id": next_id(), **payload}
    CAMPAIGNS[campaign["id"]] = campaign
    return campaign


@app.get("/admin_api/v1/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, api_key: str | None = Header(None)):
    check(api_key)
    if campaign_id not in CAMPAIGNS:
        raise HTTPException(404, "Campaign not found")
    return CAMPAIGNS[campaign_id]


@app.delete("/admin_api/v1/campaigns/{campaign_id}")
def delete_campaign(campaign_id: int, api_key: str | None = Header(None)):
    check(api_key)
    CAMPAIGNS.pop(campaign_id, None)
    return {"success": True}


@app.get("/admin_api/v1/campaigns/{campaign_id}/streams")
def campaign_streams(campaign_id: int, api_key: str | None = Header(None)):
    check(api_key)
    return [stream for stream in STREAMS.values() if stream["campaign_id"] == campaign_id]


@app.post("/admin_api/v1/streams")
def create_stream(payload: dict = Body(...), api_key: str | None = Header(None)):
    check(api_key)
    stream = {"id": next_id(), "offers": [], **payload}
    STREAMS[stream["id"]] = stream
    return stream


@app.put("/admin_api/v1/streams/{stream_id}")
def update_stream(stream_id: int, payload: dict = Body(...), api_key: str | None = Header(None)):
    check(api_key)
    if stream_id not in STREAMS:
        raise HTTPException(404, "Stream not found")
    STREAMS[stream_id].update(payload)
    return STREAMS[stream_id]
