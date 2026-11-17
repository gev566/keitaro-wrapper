"""Бизнес-логика: создание кампании и редактор офферов в потоке."""

import re
import secrets
import string

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .keitaro import KeitaroClient, KeitaroError
from .models import STATUS_ACTIVE, STATUS_REMOVED, Campaign, Stream, StreamOffer
from .weights import WeightError, recalculate


class ServiceError(Exception):
    """Ошибка, которую нужно показать пользователю."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ---------- создание кампании ----------


def parse_geo(raw: str) -> list[str]:
    """«mx, au» -> ["MX", "AU"]. Принимаем двухбуквенные коды стран."""
    codes = [part.strip().upper() for part in re.split(r"[,\s;]+", raw) if part.strip()]
    if not codes:
        raise ServiceError("Укажите код страны, например AU.")
    for code in codes:
        if not re.fullmatch(r"[A-Z]{2}", code):
            raise ServiceError(f"«{code}» не похоже на код страны. Нужны две латинские буквы, например AU.")
    return list(dict.fromkeys(codes))  # убираем повторы, сохраняя порядок


def with_prefix(name: str, prefix: str) -> str:
    name = name.strip()
    if not name:
        raise ServiceError("Укажите название кампании.")
    if prefix and not name.lower().startswith(prefix.lower()):
        name = prefix + name
    return name


def make_alias(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def find_by_name(items: list[dict], name: str) -> dict | None:
    for item in items:
        if str(item.get("name", "")).strip().lower() == name.strip().lower():
            return item
    return None


def load_meta(keitaro: KeitaroClient, settings: Settings) -> dict:
    """Справочники для формы и значения по умолчанию."""
    domains = [d for d in keitaro.get_domains() if d.get("state", "active") == "active"]
    groups = keitaro.get_groups()
    sources = keitaro.get_traffic_sources()

    domain = find_by_name(domains, settings.default_domain_name) if settings.default_domain_name else None
    domain = domain or (domains[0] if domains else None)
    group = find_by_name(groups, settings.default_group_name)
    source = find_by_name(sources, settings.default_source_name)

    def short(items):
        return [{"id": item["id"], "name": item.get("name", "")} for item in items]

    return {
        "domains": short(domains),
        "groups": short(groups),
        "sources": short(sources),
        "defaults": {
            "domain_id": domain["id"] if domain else None,
            "group_id": group["id"] if group else None,
            "source_id": source["id"] if source else None,
        },
        "prefix": settings.campaign_prefix,
        "redirect_url": settings.geo_redirect_url,
    }


def create_campaign(
    db: Session,
    keitaro: KeitaroClient,
    settings: Settings,
    *,
    name: str,
    geo: str,
    offer_id: int,
    domain_id: int | None = None,
    group_id: int | None = None,
    source_id: int | None = None,
) -> Campaign:
    name = with_prefix(name, settings.campaign_prefix)
    countries = parse_geo(geo)

    offers = {offer["id"]: offer for offer in keitaro.get_offers()}
    if offer_id not in offers:
        raise ServiceError(f"Оффер с ID {offer_id} не найден в Keitaro.", 404)

    # Домен, группа и источник обязательны по ТЗ. Если их не выбрали в форме,
    # берём значения по умолчанию из настроек.
    if domain_id is None or group_id is None or source_id is None:
        defaults = load_meta(keitaro, settings)["defaults"]
        domain_id = domain_id if domain_id is not None else defaults["domain_id"]
        group_id = group_id if group_id is not None else defaults["group_id"]
        source_id = source_id if source_id is not None else defaults["source_id"]
    missing = [
        title
        for title, value in (("домен", domain_id), ("группу", group_id), ("источник", source_id))
        if value is None
    ]
    if missing:
        raise ServiceError("Не удалось определить " + ", ".join(missing) + " для кампании. Выберите их в форме.")

    created = keitaro.create_campaign(
        {
            "name": name,
            "alias": make_alias(),
            "type": "position",  # потоки проверяются по порядку: сначала первый, потом второй
            "state": "active",
            "domain_id": domain_id,
            "group_id": group_id,
            "traffic_source_id": source_id,
        }
    )
    keitaro_campaign_id = created["id"]

    try:
        # Поток 1: посетители из выбранных стран уходят на Google.
        keitaro.create_stream(
            {
                "campaign_id": keitaro_campaign_id,
                "type": "regular",
                "name": "Flow 1",
                "position": 1,
                "state": "active",
                "schema": "redirect",
                "action_type": "http",
                "action_payload": settings.geo_redirect_url,
                "collect_clicks": True,
                "filter_or": False,
                "filters": [{"name": "country", "mode": "accept", "payload": countries}],
            }
        )
        # Поток 2: все остальные уходят на выбранный оффер.
        keitaro.create_stream(
            {
                "campaign_id": keitaro_campaign_id,
                "type": "regular",
                "name": "Flow 2",
                "position": 2,
                "state": "active",
                "schema": "landings",
                "action_type": "http",
                "collect_clicks": True,
                "filter_or": False,
                "filters": [],
                "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
            }
        )
    except KeitaroError as error:
        # Кампания без потоков бесполезна — убираем её, чтобы не оставлять мусор.
        try:
            keitaro.delete_campaign(keitaro_campaign_id)
        except KeitaroError:
            pass
        raise ServiceError(f"Кампания не создана: не удалось создать потоки. {error.message}", 502) from error

    campaign = Campaign(
        keitaro_id=keitaro_campaign_id,
        name=created.get("name", name),
        alias=created.get("alias", ""),
        geo=",".join(countries),
    )
    db.add(campaign)
    db.flush()
    sync_streams(db, keitaro, campaign, offer_names={k: v.get("name", "") for k, v in offers.items()})
    db.commit()
    return campaign


def open_campaign(db: Session, keitaro: KeitaroClient, keitaro_id: int) -> Campaign:
    """Открывает в редакторе кампанию, которая уже есть в Keitaro."""
    campaign = db.scalar(select(Campaign).where(Campaign.keitaro_id == keitaro_id))
    if campaign is None:
        remote = keitaro.get_campaign(keitaro_id)
        campaign = Campaign(keitaro_id=keitaro_id, name=remote.get("name", ""), alias=remote.get("alias", ""))
        db.add(campaign)
        db.flush()
    sync_streams(db, keitaro, campaign)
    db.commit()
    return campaign


# ---------- синхронизация с Keitaro ----------


def sync_streams(
    db: Session, keitaro: KeitaroClient, campaign: Campaign, offer_names: dict[int, str] | None = None
) -> None:
    """«Fetch streams»: забирает потоки и офферы из Keitaro.

    - потоки без офферов сохраняем только как строку с названием;
    - оффер, которого у нас не было, добавляется как активный;
    - оффер, который у нас был, а из Keitaro пропал, не удаляется, а получает статус removed;
    - неопубликованный черновик при этом сбрасывается: источник правды — Keitaro.
    """
    remote_streams = keitaro.get_campaign_streams(campaign.keitaro_id)
    if offer_names is None:
        offer_names = {offer["id"]: offer.get("name", "") for offer in keitaro.get_offers()}

    local_by_kid = {stream.keitaro_id: stream for stream in campaign.streams}
    seen: set[int] = set()

    for remote in remote_streams:
        if remote.get("state") == "deleted":
            continue
        kid = remote["id"]
        seen.add(kid)
        stream = local_by_kid.get(kid)
        if stream is None:
            stream = Stream(campaign=campaign, keitaro_id=kid)
            db.add(stream)

        stream.name = remote.get("name") or f"Stream {kid}"
        stream.position = remote.get("position") or 0

        remote_offers = {
            item["offer_id"]: item
            for item in (remote.get("offers") or [])
            if item.get("state", "active") != "deleted"
        }
        stream.has_offers = bool(remote_offers) or bool(stream.offers)
        if not stream.has_offers:
            stream.dirty = False
            continue

        cancel_draft(db, stream)  # сбрасываем черновик перед синхронизацией

        local_offers = {offer.offer_id: offer for offer in stream.offers}
        for offer_id, item in remote_offers.items():
            offer = local_offers.get(offer_id)
            if offer is None:
                offer = StreamOffer(stream=stream, offer_id=offer_id)
                db.add(offer)
            offer.offer_name = offer_names.get(offer_id) or offer.offer_name or f"Offer {offer_id}"
            offer.status = STATUS_ACTIVE
            offer.share = int(item.get("share") or 0)
            _mark_published(offer)

        for offer_id, offer in local_offers.items():
            if offer_id not in remote_offers:
                offer.status = STATUS_REMOVED
                offer.share = 0
                offer.pinned = False
                _mark_published(offer)

        stream.dirty = False

    for kid, stream in local_by_kid.items():
        if kid not in seen:
            db.delete(stream)

    db.flush()
    db.refresh(campaign)


def _mark_published(offer: StreamOffer) -> None:
    offer.pub_status = offer.status
    offer.pub_share = offer.share
    offer.pub_pinned = offer.pinned


def _is_dirty(stream: Stream) -> bool:
    return any(
        offer.pub_status is None
        or offer.status != offer.pub_status
        or offer.share != offer.pub_share
        or offer.pinned != offer.pub_pinned
        for offer in stream.offers
    )


def _recalculate(stream: Stream) -> None:
    try:
        recalculate(stream.offers)
    except WeightError as error:
        raise ServiceError(str(error)) from error
    stream.dirty = _is_dirty(stream)


# ---------- редактор потока ----------


def add_offer(db: Session, keitaro: KeitaroClient, stream: Stream, offer_id: int) -> Stream:
    existing = next((offer for offer in stream.offers if offer.offer_id == offer_id), None)
    if existing is not None:
        if existing.status == STATUS_ACTIVE:
            raise ServiceError("Этот оффер уже есть в потоке.", 409)
        existing.status = STATUS_ACTIVE  # оффер был удалён — возвращаем его
    else:
        remote = next((offer for offer in keitaro.get_offers() if offer["id"] == offer_id), None)
        if remote is None:
            raise ServiceError(f"Оффер с ID {offer_id} не найден в Keitaro.", 404)
        stream.offers.append(
            StreamOffer(offer_id=offer_id, offer_name=remote.get("name", ""), status=STATUS_ACTIVE, pub_status=None)
        )
    stream.has_offers = True
    _recalculate(stream)
    db.commit()
    return stream


def remove_offer(db: Session, offer: StreamOffer) -> Stream:
    stream = offer.stream
    if offer.status == STATUS_REMOVED:
        raise ServiceError("Оффер уже удалён из потока.", 409)
    if offer.pub_status is None:
        # Оффер добавили и не успели опубликовать — просто убираем привязку.
        stream.offers.remove(offer)
    else:
        offer.status = STATUS_REMOVED
    _recalculate(stream)
    db.commit()
    return stream


def restore_offer(db: Session, offer: StreamOffer) -> Stream:
    if offer.status == STATUS_ACTIVE:
        raise ServiceError("Оффер и так активен.", 409)
    offer.status = STATUS_ACTIVE
    _recalculate(offer.stream)
    db.commit()
    return offer.stream


def set_pin(db: Session, offer: StreamOffer, pinned: bool, share: int | None) -> Stream:
    if offer.status != STATUS_ACTIVE:
        raise ServiceError("Нельзя закрепить долю удалённого оффера.", 409)
    if pinned and share is not None:
        if not 0 <= share <= 100:
            raise ServiceError("Доля должна быть от 0 до 100.")
        offer.share = share
    offer.pinned = pinned
    _recalculate(offer.stream)
    db.commit()
    return offer.stream


def push_stream(db: Session, keitaro: KeitaroClient, stream: Stream) -> Stream:
    """«Push to KT»: отправляет черновик в Keitaro."""
    active = [offer for offer in stream.offers if offer.status == STATUS_ACTIVE]
    if not active:
        raise ServiceError("В потоке должен остаться хотя бы один оффер.")
    total = sum(offer.share for offer in active)
    if total != 100:
        raise ServiceError(f"Сумма долей — {total}%, а должна быть 100%. Поправьте закреплённые доли.")

    try:
        keitaro.update_stream(
            stream.keitaro_id,
            {"offers": [{"offer_id": offer.offer_id, "share": offer.share, "state": "active"} for offer in active]},
        )
    except KeitaroError as error:
        raise ServiceError(f"Не удалось отправить изменения. {error.message}", 502) from error

    for offer in stream.offers:
        _mark_published(offer)
    stream.dirty = False
    db.commit()
    return stream


def cancel_draft(db: Session, stream: Stream) -> None:
    """Возвращает поток к состоянию последней синхронизации. Без commit."""
    for offer in list(stream.offers):
        if offer.pub_status is None:
            stream.offers.remove(offer)
        else:
            offer.status = offer.pub_status
            offer.share = offer.pub_share
            offer.pinned = offer.pub_pinned
    stream.dirty = False


def cancel_stream(db: Session, stream: Stream) -> Stream:
    """«Cancel»: отменяет неопубликованные изменения."""
    cancel_draft(db, stream)
    db.commit()
    return stream
