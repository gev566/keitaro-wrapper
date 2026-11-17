import pytest

from app.weights import WeightError, distribute


def test_equal_split():
    assert distribute([], 4) == [25, 25, 25, 25]


def test_remainder_goes_to_first_offers():
    assert distribute([], 3) == [34, 33, 33]


def test_pinned_share_is_kept():
    # один оффер закреплён на 25 %, остальные 75 % делятся на двоих
    assert distribute([25], 2) == [38, 37]


def test_all_pinned():
    assert distribute([60, 40], 0) == []


def test_pinned_over_100_is_error():
    with pytest.raises(WeightError):
        distribute([70, 40], 1)


def test_sum_is_always_100():
    for pinned in ([], [10], [33, 33]):
        for free in range(1, 8):
            assert sum(pinned) + sum(distribute(pinned, free)) == 100
