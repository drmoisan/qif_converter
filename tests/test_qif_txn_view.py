# tests/test_qif_txn_view.py
from datetime import date
from decimal import Decimal

from qif_converter.qif_item_key import QIFItemKey
from qif_converter.qif_txn_view import QIFTxnView


def test_init_and_field_access():
    # Arrange
    key = QIFItemKey(txn_index=7, split_index=None)
    d = date(2025, 8, 10)
    amt = Decimal("-42.00")
    payee = "Cafe"
    memo = "morning coffee"
    category = "Food:Coffee"

    # Act
    view = QIFTxnView(
        key=key,
        date=d,
        amount=amt,
        payee=payee,
        memo=memo,
        category=category,
    )

    # Assert
    assert view.key is key
    assert view.date == d
    assert view.amount == amt
    assert view.payee == payee
    assert view.memo == memo
    assert view.category == category


def test_equality_semantics():
    # Arrange
    key = QIFItemKey(txn_index=1, split_index=None)
    d = date(2025, 1, 2)

    a = QIFTxnView(
        key=key,
        date=d,
        amount=Decimal("-10.00"),
        payee="Store",
        memo="m",
        category="Cat",
    )
    b = QIFTxnView(
        key=QIFItemKey(txn_index=1, split_index=None),
        date=date(2025, 1, 2),
        amount=Decimal("-10.00"),
        payee="Store",
        memo="m",
        category="Cat",
    )
    c = QIFTxnView(
        key=QIFItemKey(txn_index=1, split_index=None),
        date=date(2025, 1, 2),
        amount=Decimal("-9.99"),  # differs
        payee="Store",
        memo="m",
        category="Cat",
    )

    # Assert
    assert a == b
    assert a != c


def test_key_split_flags():
    # Non-split transaction
    k1 = QIFItemKey(txn_index=0, split_index=None)
    v1 = QIFTxnView(
        key=k1,
        date=date(2025, 2, 3),
        amount=Decimal("100.00"),
        payee="Employer",
        memo="Paycheck",
        category="Income",
    )
    assert v1.key.is_split() is False

    # Split transaction
    k2 = QIFItemKey(txn_index=0, split_index=0)
    v2 = QIFTxnView(
        key=k2,
        date=date(2025, 2, 3),
        amount=Decimal("-12.34"),
        payee="Grocer",
        memo="apples",
        category="Food",
    )
    assert v2.key.is_split() is True
