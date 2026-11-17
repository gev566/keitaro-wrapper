"""Таблицы приложения.

В Keitaro хранится то, что реально работает. В нашей базе — копия потоков
и офферов плюс черновик изменений, которые ещё не отправлены в Keitaro.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

STATUS_ACTIVE = "active"
STATUS_REMOVED = "removed"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str] = mapped_column(String(64), default="")
    geo: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    streams: Mapped[list["Stream"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", order_by="Stream.position"
    )


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    keitaro_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    # True — поток с офферами, его можно редактировать. False — показываем только название.
    has_offers: Mapped[bool] = mapped_column(Boolean, default=False)
    # True — есть изменения, которые ещё не отправлены в Keitaro («жёлтый» поток).
    dirty: Mapped[bool] = mapped_column(Boolean, default=False)

    campaign: Mapped[Campaign] = relationship(back_populates="streams")
    offers: Mapped[list["StreamOffer"]] = relationship(
        back_populates="stream", cascade="all, delete-orphan", order_by="StreamOffer.id"
    )


class StreamOffer(Base):
    """Привязка оффера к потоку.

    status, share, pinned — текущее состояние в нашем интерфейсе (черновик).
    pub_* — то, что было при последней синхронизации с Keitaro.
    pub_status = None значит, что оффер добавлен у нас, но в Keitaro его ещё нет.
    """

    __tablename__ = "stream_offers"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id", name="uq_stream_offer"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"))
    offer_id: Mapped[int] = mapped_column(Integer)
    offer_name: Mapped[str] = mapped_column(String(255), default="")

    status: Mapped[str] = mapped_column(String(16), default=STATUS_ACTIVE)
    share: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    pub_status: Mapped[str | None] = mapped_column(String(16), nullable=True, default=None)
    pub_share: Mapped[int] = mapped_column(Integer, default=0)
    pub_pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    stream: Mapped[Stream] = relationship(back_populates="offers")
