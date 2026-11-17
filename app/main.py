"""HTTP-слой: JSON API и раздача интерфейса."""

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import services
from .config import Settings, get_settings
from .db import get_db
from .keitaro import KeitaroClient, KeitaroError
from .models import Campaign, Stream, StreamOffer

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Adrobot — обёртка над Keitaro")


def get_keitaro(settings: Settings = Depends(get_settings)) -> KeitaroClient:
    return KeitaroClient(settings.keitaro_url, settings.keitaro_api_key, settings.keitaro_timeout)


@app.exception_handler(services.ServiceError)
def handle_service_error(_, error: services.ServiceError):
    return JSONResponse(status_code=error.status_code, content={"detail": error.message})


@app.exception_handler(KeitaroError)
def handle_keitaro_error(_, error: KeitaroError):
    return JSONResponse(status_code=502, content={"detail": error.message})


# ---------- схемы ----------


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geo: str = Field(min_length=2, max_length=200)
    offer_id: int
    domain_id: int | None = None
    group_id: int | None = None
    source_id: int | None = None


class CampaignOpen(BaseModel):
    keitaro_id: int


class OfferAdd(BaseModel):
    offer_id: int


class PinUpdate(BaseModel):
    pinned: bool
    share: int | None = Field(default=None, ge=0, le=100)


def campaign_out(campaign: Campaign) -> dict:
    return {
        "id": campaign.id,
        "keitaro_id": campaign.keitaro_id,
        "name": campaign.name,
        "alias": campaign.alias,
        "geo": campaign.geo,
        "streams": [stream_out(stream) for stream in campaign.streams],
    }


def stream_out(stream: Stream) -> dict:
    return {
        "id": stream.id,
        "keitaro_id": stream.keitaro_id,
        "name": stream.name,
        "position": stream.position,
        "has_offers": stream.has_offers,
        "dirty": stream.dirty,
        "total_share": sum(offer.share for offer in stream.offers if offer.status == "active"),
        "offers": [
            {
                "id": offer.id,
                "offer_id": offer.offer_id,
                "name": offer.offer_name,
                "status": offer.status,
                "share": offer.share,
                "pinned": offer.pinned,
                "is_new": offer.pub_status is None,
            }
            for offer in stream.offers
        ],
    }


def get_stream(stream_id: int, db: Session) -> Stream:
    stream = db.get(Stream, stream_id)
    if stream is None:
        raise HTTPException(404, "Поток не найден.")
    return stream


def get_stream_offer(link_id: int, db: Session) -> StreamOffer:
    offer = db.get(StreamOffer, link_id)
    if offer is None:
        raise HTTPException(404, "Оффер в потоке не найден.")
    return offer


# ---------- справочники ----------


@app.get("/api/meta")
def meta(keitaro: KeitaroClient = Depends(get_keitaro), settings: Settings = Depends(get_settings)):
    return services.load_meta(keitaro, settings)


@app.get("/api/offers")
def search_offers(q: str = "", limit: int = 20, keitaro: KeitaroClient = Depends(get_keitaro)):
    """Поиск офферов по названию или ID — для автокомплита."""
    query = q.strip().lower()
    found = []
    for offer in keitaro.get_offers():
        if offer.get("state") == "deleted":
            continue
        name = str(offer.get("name", ""))
        if not query or query in name.lower() or query == str(offer["id"]):
            found.append({"id": offer["id"], "name": name})
        if len(found) >= limit:
            break
    return found


@app.get("/api/keitaro/campaigns")
def keitaro_campaigns(q: str = "", limit: int = 50, keitaro: KeitaroClient = Depends(get_keitaro)):
    """Кампании, которые уже есть в Keitaro, — чтобы открыть их в редакторе."""
    query = q.strip().lower()
    found = []
    for campaign in keitaro.get_campaigns():
        if campaign.get("state") == "deleted":
            continue
        name = str(campaign.get("name", ""))
        if not query or query in name.lower() or query == str(campaign["id"]):
            found.append({"keitaro_id": campaign["id"], "name": name, "state": campaign.get("state", "")})
    found.sort(key=lambda item: item["keitaro_id"], reverse=True)
    return found[:limit]


# ---------- кампании ----------


@app.get("/api/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    campaigns = db.scalars(select(Campaign).order_by(Campaign.id.desc())).all()
    return [{"id": c.id, "keitaro_id": c.keitaro_id, "name": c.name, "geo": c.geo} for c in campaigns]


@app.post("/api/campaigns", status_code=201)
def create_campaign(
    body: CampaignCreate,
    db: Session = Depends(get_db),
    keitaro: KeitaroClient = Depends(get_keitaro),
    settings: Settings = Depends(get_settings),
):
    campaign = services.create_campaign(db, keitaro, settings, **body.model_dump())
    return campaign_out(campaign)


@app.post("/api/campaigns/open")
def open_campaign(body: CampaignOpen, db: Session = Depends(get_db), keitaro: KeitaroClient = Depends(get_keitaro)):
    return campaign_out(services.open_campaign(db, keitaro, body.keitaro_id))


@app.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Кампания не найдена.")
    return campaign_out(campaign)


@app.post("/api/campaigns/{campaign_id}/fetch")
def fetch_streams(campaign_id: int, db: Session = Depends(get_db), keitaro: KeitaroClient = Depends(get_keitaro)):
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Кампания не найдена.")
    services.sync_streams(db, keitaro, campaign)
    db.commit()
    return campaign_out(campaign)


# ---------- редактор потока ----------


@app.post("/api/streams/{stream_id}/offers")
def add_offer(
    stream_id: int, body: OfferAdd, db: Session = Depends(get_db), keitaro: KeitaroClient = Depends(get_keitaro)
):
    return stream_out(services.add_offer(db, keitaro, get_stream(stream_id, db), body.offer_id))


@app.delete("/api/stream-offers/{link_id}")
def remove_offer(link_id: int, db: Session = Depends(get_db)):
    return stream_out(services.remove_offer(db, get_stream_offer(link_id, db)))


@app.post("/api/stream-offers/{link_id}/restore")
def restore_offer(link_id: int, db: Session = Depends(get_db)):
    return stream_out(services.restore_offer(db, get_stream_offer(link_id, db)))


@app.patch("/api/stream-offers/{link_id}")
def pin_offer(link_id: int, body: PinUpdate, db: Session = Depends(get_db)):
    return stream_out(services.set_pin(db, get_stream_offer(link_id, db), body.pinned, body.share))


@app.post("/api/streams/{stream_id}/push")
def push_stream(stream_id: int, db: Session = Depends(get_db), keitaro: KeitaroClient = Depends(get_keitaro)):
    return stream_out(services.push_stream(db, keitaro, get_stream(stream_id, db)))


@app.post("/api/streams/{stream_id}/cancel")
def cancel_stream(stream_id: int, db: Session = Depends(get_db)):
    return stream_out(services.cancel_stream(db, get_stream(stream_id, db)))


# ---------- интерфейс ----------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
