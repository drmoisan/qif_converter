# tests/test_qif_loader_protocol.py
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest

import quicken_helper.controllers.qif_loader as ql
from quicken_helper.data_model.interfaces import EnumClearedStatus


def _mk_rec(**kwargs) -> Dict[str, Any]:
    """
    Helper: produce a minimal transaction dict matching qif_loader.parse_qif output shape.
    Callers override keys via kwargs.
    """
    base = {
        "date": "01/01/2025",
        "amount": "0.00",
        "payee": "",
        "memo": "",
        "category": "",
        "splits": [],
        "cleared": "",
        "checknum": None,
        "address": "",
        "transfer_account": "",
        "action": None,
        # "account": ...  # would be a string name in raw parse, adapter sets to None (IAccount optional)
        # "type": ...     # would be a raw header string, adapter sets to None (IHeader optional)
    }
    base.update(kwargs)
    return base


@pytest.mark.usefixtures()
def test_protocol_return_types_and_defaults(monkeypatch):
    """Ensure load_transactions_protocol returns protocol-shaped objects with correct types and None defaults for account/type."""

    # Arrange
    def fake_parse_qif(_path, encoding="utf-8") -> List[Dict[str, Any]]:
        return [
            _mk_rec(
                date="07/04/2025",
                amount="123.45",
                payee="Acme Co",
                memo="Payment",
                category="Utilities:Internet",
                cleared="",
            )
        ]

    monkeypatch.setattr(ql, "parse_qif", fake_parse_qif)

    # Act
    txns = ql.load_transactions_protocol(Path("dummy.data_model"))

    # Assert
    assert isinstance(txns, list), "Expected a list of transactions"
    assert len(txns) == 1, "Expected exactly one transaction"

    t = txns[0]
    assert isinstance(t.date, date), "date should be a datetime.date"
    assert isinstance(t.amount, Decimal), "amount should be Decimal"
    assert t.amount == Decimal("123.45"), f"Unexpected amount: {t.amount}"
    assert t.payee == "Acme Co"
    assert t.memo == "Payment"
    assert t.category == "Utilities:Internet"
    assert t.tag is None, "Tag should be None when not provided"
    assert t.splits == [], "Splits should be an empty list when not provided"
    assert t.account is None, "account should default to None (Optional[IAccount])"
    assert t.type is None, "type should default to None (Optional[IHeader])"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("7/4'25", date(2025, 7, 4)),
        ("07/04/25", date(2025, 7, 4)),
        ("07/04/2025", date(2025, 7, 4)),
        ("07-04-2025", date(2025, 7, 4)),
    ],
)
def test_date_parsing_qif_formats(monkeypatch, raw, expected):
    """Verify adapter normalizes common QIF date variants into datetime.date."""

    # Arrange
    def fake_parse_qif(_path, encoding="utf-8"):
        return [_mk_rec(date=raw, amount="0.00")]

    monkeypatch.setattr(ql, "parse_qif", fake_parse_qif)

    # Act
    [t] = ql.load_transactions_protocol(Path("dummy.data_model"))

    # Assert
    assert (
        t.date == expected
    ), f"Date parsed incorrectly for input {raw!r}: {t.date} != {expected}"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("1,234.56", Decimal("1234.56")),
        ("(1,234.56)", Decimal("-1234.56")),
        ("0.00", Decimal("0.00")),
        ("(0.01)", Decimal("-0.01")),
    ],
)
def test_amount_parsing_commas_and_parentheses(monkeypatch, raw, expected):
    """Amounts should parse as Decimal, handling commas and parentheses for negatives."""

    # Arrange
    def fake_parse_qif(_path, encoding="utf-8"):
        return [_mk_rec(amount=raw)]

    monkeypatch.setattr(ql, "parse_qif", fake_parse_qif)

    # Act
    [t] = ql.load_transactions_protocol(Path("dummy.data_model"))

    # Assert
    assert isinstance(t.amount, Decimal), "Amount should be Decimal"
    assert (
        t.amount == expected
    ), f"Parsed amount {t.amount} != expected {expected} for input {raw!r}"


@pytest.mark.parametrize(
    "cleared_char, expected",
    [
        ("", EnumClearedStatus.NOT_CLEARED),
        (" ", EnumClearedStatus.NOT_CLEARED),
        ("*", EnumClearedStatus.CLEARED),
        ("X", EnumClearedStatus.RECONCILED),
        ("?", EnumClearedStatus.UNKNOWN),
    ],
)
def test_cleared_status_mapping(monkeypatch, cleared_char, expected):
    """Map '', ' ', '*' and 'X' to the correct EnumClearedStatus values."""

    # Arrange
    def fake_parse_qif(_path, encoding="utf-8"):
        return [_mk_rec(cleared=cleared_char)]

    monkeypatch.setattr(ql, "parse_qif", fake_parse_qif)

    # Act
    [t] = ql.load_transactions_protocol(Path("dummy.data_model"))

    # Assert
    assert (
        t.cleared == expected
    ), f"Cleared mapping wrong for {cleared_char!r}: {t.cleared} != {expected}"


def test_category_tag_splitting(monkeypatch):
    """Category with '/', e.g., 'Groceries/Costco', should split into category='Groceries', tag='Costco'."""

    # Arrange
    def fake_parse_qif(_path, encoding="utf-8"):
        return [
            _mk_rec(category="Groceries/Costco"),
            _mk_rec(category="Food:Groceries"),
        ]

    monkeypatch.setattr(ql, "parse_qif", fake_parse_qif)

    # Act
    t1, t2 = ql.load_transactions_protocol(Path("dummy.data_model"))

    # Assert
    assert t1.category == "Groceries", f"Expected 'Groceries', got {t1.category!r}"
    assert t1.tag == "Costco", f"Expected tag 'Costco', got {t1.tag!r}"
    assert (
        t2.category == "Food:Groceries"
    ), f"Unexpected category for second txn: {t2.category!r}"
    assert t2.tag is None, "Tag should be None when '/' is not present in category"


def test_splits_conversion_and_sum(monkeypatch):
    """Split lines should become ISplit-like objects; their amounts should sum to the parent amount."""

    # Arrange
    def fake_parse_qif(_path, encoding="utf-8"):
        return [
            _mk_rec(
                amount="12.34",
                splits=[
                    {"amount": "10.00", "category": "Food:Groceries", "memo": "Apples"},
                    {"amount": "2.34", "category": "Food:Groceries", "memo": "Bananas"},
                ],
            )
        ]

    monkeypatch.setattr(ql, "parse_qif", fake_parse_qif)

    # Act
    [t] = ql.load_transactions_protocol(Path("dummy.data_model"))

    # Assert
    assert isinstance(t.splits, list), "splits should be a list"
    assert len(t.splits) == 2, f"Expected 2 splits, found {len(t.splits)}"
    total = sum(s.amount for s in t.splits)
    assert total == t.amount, f"Split sum {total} must equal txn amount {t.amount}"
    assert t.splits[0].category == "Food:Groceries"
    assert t.splits[0].memo == "Apples"
    assert t.splits[1].memo == "Bananas"


def test_investment_action_passthrough(monkeypatch):
    """Non-protocol extras like 'action' should be preserved on the adapter for investment records."""

    # Arrange
    def fake_parse_qif(_path, encoding="utf-8"):
        return [
            _mk_rec(
                amount="100.00",
                action="Buy",  # e.g., from !Type:Invst
            )
        ]

    monkeypatch.setattr(ql, "parse_qif", fake_parse_qif)

    # Act
    [t] = ql.load_transactions_protocol(Path("dummy.data_model"))

    # Assert
    # Protocol conformance doesn't require .action, but adapter should carry it through.
    assert hasattr(t, "action"), "Adapter should expose 'action' attribute"
    assert t.action == "Buy", f"Expected action 'Buy', got {t.action!r}"
