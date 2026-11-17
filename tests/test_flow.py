def create(client, name="camp", geo="au", offer_id=1):
    response = client.post("/api/campaigns", json={"name": name, "geo": geo, "offer_id": offer_id})
    assert response.status_code == 201, response.text
    return response.json()


def offer_stream(campaign):
    return next(s for s in campaign["streams"] if s["has_offers"])


def shares(stream):
    return {o["offer_id"]: o["share"] for o in stream["offers"]}


def test_create_campaign_makes_two_streams(client, keitaro):
    campaign = create(client)

    assert campaign["name"] == "test_babloyan_camp"  # префикс добавляется сам
    remote = keitaro.campaigns[campaign["keitaro_id"]]
    assert (remote["domain_id"], remote["group_id"], remote["traffic_source_id"]) == (10, 20, 30)

    first, second = sorted(keitaro.get_campaign_streams(remote["id"]), key=lambda s: s["position"])
    assert first["filters"] == [{"name": "country", "mode": "accept", "payload": ["AU"]}]
    assert first["action_payload"] == "https://google.com"
    assert second["offers"] == [{"offer_id": 1, "share": 100, "state": "active"}]

    # поток без офферов показываем только как строку
    plain = next(s for s in campaign["streams"] if not s["has_offers"])
    assert plain["offers"] == []
    assert shares(offer_stream(campaign)) == {1: 100}


def test_prefix_not_duplicated(client):
    assert create(client, name="test_babloyan_x")["name"] == "test_babloyan_x"


def test_bad_geo_and_unknown_offer(client):
    assert client.post("/api/campaigns", json={"name": "a", "geo": "australia", "offer_id": 1}).status_code == 400
    assert client.post("/api/campaigns", json={"name": "a", "geo": "au", "offer_id": 999}).status_code == 404


def test_campaign_removed_if_streams_fail(client, keitaro):
    keitaro.fail_streams = True
    response = client.post("/api/campaigns", json={"name": "a", "geo": "au", "offer_id": 1})
    assert response.status_code == 502
    assert keitaro.campaigns == {}


def test_add_offer_is_draft_until_push(client, keitaro):
    stream = offer_stream(create(client))
    sid, kid = stream["id"], stream["keitaro_id"]

    stream = client.post(f"/api/streams/{sid}/offers", json={"offer_id": 2}).json()
    assert stream["dirty"] is True
    assert shares(stream) == {1: 50, 2: 50}
    assert len(keitaro.streams[kid]["offers"]) == 1  # в Keitaro пока ничего не изменилось

    stream = client.post(f"/api/streams/{sid}/push").json()
    assert stream["dirty"] is False
    assert keitaro.streams[kid]["offers"] == [
        {"offer_id": 1, "share": 50, "state": "active"},
        {"offer_id": 2, "share": 50, "state": "active"},
    ]


def test_cancel_drops_unpublished_offer(client):
    stream = offer_stream(create(client))
    client.post(f"/api/streams/{stream['id']}/offers", json={"offer_id": 2})
    stream = client.post(f"/api/streams/{stream['id']}/cancel").json()
    assert stream["dirty"] is False
    assert shares(stream) == {1: 100}


def test_remove_keeps_offer_in_archive_and_bring_back(client, keitaro):
    stream = offer_stream(create(client))
    sid, kid = stream["id"], stream["keitaro_id"]
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 2})
    stream = client.post(f"/api/streams/{sid}/push").json()
    link = next(o for o in stream["offers"] if o["offer_id"] == 2)

    stream = client.delete(f"/api/stream-offers/{link['id']}").json()
    assert stream["dirty"] is True
    assert shares(stream) == {1: 100, 2: 0}
    removed = next(o for o in stream["offers"] if o["offer_id"] == 2)
    assert removed["status"] == "removed"

    client.post(f"/api/streams/{sid}/push")
    assert [o["offer_id"] for o in keitaro.streams[kid]["offers"]] == [1]

    stream = client.post(f"/api/stream-offers/{link['id']}/restore").json()
    assert stream["dirty"] is True
    assert shares(stream) == {1: 50, 2: 50}


def test_fetch_marks_offers_deleted_in_keitaro_as_removed(client, keitaro):
    campaign = create(client)
    stream = offer_stream(campaign)
    sid, kid = stream["id"], stream["keitaro_id"]
    client.post(f"/api/streams/{sid}/offers", json={"offer_id": 2})
    client.post(f"/api/streams/{sid}/push")

    # кто-то удалил оффер 2 прямо в Keitaro и добавил оффер 3
    keitaro.streams[kid]["offers"] = [
        {"offer_id": 1, "share": 60, "state": "active"},
        {"offer_id": 3, "share": 40, "state": "active"},
    ]
    campaign = client.post(f"/api/campaigns/{campaign['id']}/fetch").json()
    stream = offer_stream(campaign)
    by_id = {o["offer_id"]: o for o in stream["offers"]}
    assert by_id[2]["status"] == "removed" and by_id[2]["share"] == 0
    assert by_id[3]["status"] == "active" and by_id[3]["share"] == 40
    assert by_id[1]["share"] == 60
    assert stream["dirty"] is False


def test_pinned_share_survives_recalculation(client):
    stream = offer_stream(create(client))
    sid = stream["id"]
    for offer_id in (2, 3, 4):
        stream = client.post(f"/api/streams/{sid}/offers", json={"offer_id": offer_id}).json()
    assert shares(stream) == {1: 25, 2: 25, 3: 25, 4: 25}

    first = next(o for o in stream["offers"] if o["offer_id"] == 1)
    stream = client.patch(f"/api/stream-offers/{first['id']}", json={"pinned": True, "share": 25}).json()
    fourth = next(o for o in stream["offers"] if o["offer_id"] == 4)
    stream = client.delete(f"/api/stream-offers/{fourth['id']}").json()

    assert shares(stream) == {1: 25, 2: 38, 3: 37}
    assert stream["total_share"] == 100


def test_push_refuses_when_sum_is_not_100(client):
    stream = offer_stream(create(client))
    only = stream["offers"][0]
    client.patch(f"/api/stream-offers/{only['id']}", json={"pinned": True, "share": 40})
    response = client.post(f"/api/streams/{stream['id']}/push")
    assert response.status_code == 400
    assert "100" in response.json()["detail"]


def test_open_existing_campaign(client, keitaro):
    keitaro.campaigns[500] = {"id": 500, "name": "old one", "alias": "abc", "state": "active"}
    keitaro.streams[501] = {
        "id": 501, "campaign_id": 500, "name": "Flow 2", "position": 2,
        "offers": [{"offer_id": 1, "share": 70, "state": "active"}, {"offer_id": 2, "share": 30, "state": "active"}],
    }
    campaign = client.post("/api/campaigns/open", json={"keitaro_id": 500}).json()
    assert shares(offer_stream(campaign)) == {1: 70, 2: 30}


def test_offer_search(client):
    assert [o["id"] for o in client.get("/api/offers", params={"q": "two"}).json()] == [2]
    assert [o["id"] for o in client.get("/api/offers", params={"q": "3"}).json()] == [3]
