"""Пересчёт долей офферов в потоке.

Правила:
- сумма долей активных офферов всегда равна 100;
- закреплённые («запиненные») доли не меняются;
- остаток делится поровну между незакреплёнными офферами;
- если поровну не делится, лишние проценты получают первые офферы по порядку
  (100 на троих — это 34, 33, 33).
"""


class WeightError(ValueError):
    pass


def distribute(pinned: list[int], free_count: int) -> list[int]:
    """Возвращает доли для незакреплённых офферов.

    pinned — доли закреплённых офферов, free_count — число незакреплённых.
    """
    for share in pinned:
        if share < 0 or share > 100:
            raise WeightError("Доля должна быть от 0 до 100.")

    pinned_total = sum(pinned)
    if pinned_total > 100:
        raise WeightError(f"Сумма закреплённых долей — {pinned_total}%, это больше 100%.")

    if free_count == 0:
        return []

    rest = 100 - pinned_total
    base, extra = divmod(rest, free_count)
    return [base + 1 if index < extra else base for index in range(free_count)]


def recalculate(offers) -> None:
    """Пересчитывает доли у списка привязок оффер-поток (объекты StreamOffer).

    Удалённые офферы получают 0. Закреплённые активные не трогаем.
    """
    active = [offer for offer in offers if offer.status == "active"]
    for offer in offers:
        if offer.status != "active":
            offer.share = 0
            offer.pinned = False

    pinned = [offer.share for offer in active if offer.pinned]
    free = [offer for offer in active if not offer.pinned]
    for offer, share in zip(free, distribute(pinned, len(free))):
        offer.share = share
