# tests/test_match_helpers.py
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import pytest

from quicken_helper.controllers.match_helpers import (_candidate_cost, _flatten_qif_txns)
from quicken_helper.utilities.converters_scalar import _to_decimal, _to_date
from quicken_helper.legacy.qif_item_key import QIFItemKey
from quicken_helper.legacy.qif_txn_view import QIFTxnView

# ----------------------- _to_decimal -----------------------


def test_to_decimal_accepts_decimal_int_float_and_str():
    # Arrange / Act
    d_from_dec = _to_decimal(Decimal("-12.34"))
    d_from_int = _to_decimal(7)
    d_from_float = _to_decimal(1.1)  # should preserve textual value, not binary float
    d_from_str = _to_decimal(" -1,234.56 ")

    # Assert
    assert d_from_dec == Decimal("-12.34")
    assert d_from_int == Decimal("7")
    assert d_from_float == Decimal("1.1")
    assert d_from_str == Decimal("-1234.56")


def test_to_decimal_strips_currency_and_commas_and_space():
    assert _to_decimal(" $ 2,345.00 ") == Decimal("2345.00")


def test_to_decimal_raises_on_empty_plus_minus():
    with pytest.raises(ValueError):
        _to_decimal("")
    with pytest.raises(ValueError):
        _to_decimal("+")
    with pytest.raises(ValueError):
        _to_decimal("-")


# ----------------------- _parse_date -----------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("08/01'25", date(2025, 8, 1)),  # mm/dd'yy
        ("08/01/2025", date(2025, 8, 1)),  # mm/dd/YYYY
        ("2025-08-01", date(2025, 8, 1)),  # ISO
        ("2025/08/01", date(2025, 8, 1)),  # ISO with slashes (fallback)
        ("08/01’25", date(2025, 8, 1)),  # curly apostrophe replaced
    ],
)
def test_parse_date_supported_formats(raw, expected):
    assert _to_date(raw) == expected


def test_parse_date_raises_on_unrecognized():
    with pytest.raises(ValueError):
        _to_date("not a date")


# ----------------------- _candidate_cost -----------------------


def test_candidate_cost_within_and_outside_window():
    d0 = date(2025, 1, 10)
    assert _candidate_cost(d0, d0) == 0
    assert _candidate_cost(d0, d0 + timedelta(days=1)) == 1
    assert _candidate_cost(d0, d0 - timedelta(days=2)) == 2
    assert _candidate_cost(d0, d0 + timedelta(days=3)) == 3
    # Outside ±3 → None
    assert _candidate_cost(d0, d0 + timedelta(days=4)) is None
    assert _candidate_cost(d0, d0 - timedelta(days=5)) is None


# ----------------------- _flatten_qif_txns -----------------------


def _mk_tx(d: str, amount: str, payee="P", memo="", category="", splits=None):
    tx = {
        "date": d,
        "amount": amount,
        "payee": payee,
        "memo": memo,
        "category": category,
    }
    if splits is not None:
        tx["splits"] = splits
    return tx


def test_flatten_qif_txns_handles_non_split_and_split_transactions():
    # Arrange
    txns = [
        _mk_tx("2025-01-02", "-10.00", payee="A", memo="m1", category="Cat1"),
        _mk_tx(
            "2025-01-03",
            "-20.00",
            payee="B",
            memo="m2",
            category="Cat2",
            splits=[
                {"category": "Food", "memo": "coffee", "amount": "-5.00"},
                {"category": "Travel", "memo": "train", "amount": "-15.00"},
            ],
        ),
    ]

    # Act
    views = _flatten_qif_txns(txns)

    # Assert basic shape and order
    assert isinstance(views, list)
    assert all(isinstance(v, QIFTxnView) for v in views)
    # Expect: 1 view from first (no splits) + 2 views from second (two splits) = 3
    assert len(views) == 3

    # First view corresponds to txn 0 (whole transaction)
    v0 = views[0]
    assert v0.key == QIFItemKey(txn_index=0, split_index=None)
    assert v0.payee == "A"
    assert v0.memo == "m1"
    assert v0.category == "Cat1"
    # amount for non-split txn is the txn amount (as Decimal)
    assert v0.amount == Decimal("-10.00")
    assert v0.date.year == 2025 and v0.date.month == 1 and v0.date.day == 2

    # Next two views correspond to splits of txn 1
    v1, v2 = views[1], views[2]
    assert v1.key == QIFItemKey(txn_index=1, split_index=0)
    assert v2.key == QIFItemKey(txn_index=1, split_index=1)

    # Payee comes from parent txn; memo/category from each split
    assert v1.payee == "B"
    assert v1.memo == "coffee"
    assert v1.category == "Food"
    assert v1.amount == Decimal("-5.00")

    assert v2.payee == "B"
    assert v2.memo == "train"
    assert v2.category == "Travel"
    assert v2.amount == Decimal("-15.00")


def test_flatten_qif_txns_handles_missing_optional_fields_gracefully():
    # Arrange: some optional fields not present
    txns = [
        {"date": "2025-02-01", "amount": "-1.00"},
        {
            "date": "2025-02-02",
            "amount": "-2.00",
            "splits": [],
        },  # explicit empty splits
    ]

    # Act
    views = _flatten_qif_txns(txns)

    # Assert: still produce views for both (no splits)
    assert [v.key for v in views] == [
        QIFItemKey(0, None),
        QIFItemKey(1, None),
    ]
    # Default blanks for missing text fields
    assert views[0].payee == ""
    assert views[0].memo == ""
    assert views[0].category == ""
    # Amounts parsed
    assert views[0].amount == Decimal("-1.00")
    assert views[1].amount == Decimal("-2.00")
