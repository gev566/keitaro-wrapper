"""Тесты работают без настоящего Keitaro: вместо него — FakeKeitaro в памяти."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings
from app.db import Base, get_db
from app.keitaro import KeitaroError
from app.main import app, get_keitaro


class FakeKeitaro:
    def __init__(self):
        self.offers = {
            1: {"id": 1, "name": "Offer one", "state": "active"},
            2: {"id": 2, "name": "Offer two", "state": "active"},
            3: {"id": 3, "name": "Offer three", "state": "active"},
            4: {"id": 4, "name": "Offer four", "state": "active"},
        }
        self.domains = [{"id": 10, "name": "https://in.example.com/", "state": "active"}]
        self.groups = [{"id": 20, "name": "FORTESTS", "type": "campaigns"}]
        self.sources = [{"id": 30, "name": "FORTESTS"}]
        self.campaigns: dict[int, dict] = {}
        self.streams: dict[int, dict] = {}
        self.fail_streams = False
        self._next_id = 100

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    def get_offers(self):
        return list(self.offers.values())

    def get_domains(self):
        return self.domains

    def get_groups(self):
        return self.groups

    def get_traffic_sources(self):
        return self.sources

    def get_campaigns(self):
        return list(self.campaigns.values())

    def get_campaign(self, campaign_id):
        if campaign_id not in self.campaigns:
            raise KeitaroError("not found", 404)
        return self.campaigns[campaign_id]

    def create_campaign(self, payload):
        campaign = {"id": self._id(), **payload}
        self.campaigns[campaign["id"]] = campaign
        return campaign

    def delete_campaign(self, campaign_id):
        self.campaigns.pop(campaign_id, None)

    def get_campaign_streams(self, campaign_id):
        return [s for s in self.streams.values() if s["campaign_id"] == campaign_id]

    def create_stream(self, payload):
        if self.fail_streams:
            raise KeitaroError("boom", 500)
        stream = {"id": self._id(), "offers": [], **payload}
        self.streams[stream["id"]] = stream
        return stream

    def update_stream(self, stream_id, payload):
        self.streams[stream_id].update(payload)
        return self.streams[stream_id]


@pytest.fixture
def keitaro():
    return FakeKeitaro()


@pytest.fixture
def client(keitaro):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with Session() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_keitaro] = lambda: keitaro
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, campaign_prefix="test_babloyan_", keitaro_url="x", keitaro_api_key="x"
    )
    yield TestClient(app)
    app.dependency_overrides.clear()
