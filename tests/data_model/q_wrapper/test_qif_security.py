# Arrange-Act-Assert styled unit tests for QifSecurityTxn

from decimal import Decimal

import pytest

from quicken_helper.data_model import QSecurity


def _mk_security_txn(
    name="Apple Inc.",
    price=Decimal("150.00"),
    quantity=Decimal("10"),
    commission=Decimal("0.00"),
    transfer_amount=Decimal("0.00"),
):
    """
    Helper to build a QifSecurityTxn with sensible defaults. Keeps tests concise
    and deterministic while centralizing object creation.
    """
    return QSecurity(
        name=name,
        price=price,
        quantity=quantity,
        commission=commission,
        transfer_amount=transfer_amount,
    )


def test_creation_and_field_values():
    # Arrange
    name = "Apple Inc."
    price = Decimal("150.00")
    quantity = Decimal("10")
    commission = Decimal("4.95")
    transfer_amount = Decimal("0.00")

    # Act
    s = _mk_security_txn(
        name=name,
        price=price,
        quantity=quantity,
        commission=commission,
        transfer_amount=transfer_amount,
    )

    # Assert
    assert s.name == name
    assert s.price == price
    assert s.quantity == quantity
    assert s.commission == commission
    assert s.transfer_amount == transfer_amount


def test_equality_for_identical_fields_and_inequality_for_different():
    # Arrange
    a = _mk_security_txn(
        name="Apple Inc.",
        price=Decimal("150.00"),
        quantity=Decimal("10"),
        commission=Decimal("0.00"),
        transfer_amount=Decimal("0.00"),
    )
    b = _mk_security_txn(
        name="Apple Inc.",
        price=Decimal("150.00"),
        quantity=Decimal("10"),
        commission=Decimal("0.00"),
        transfer_amount=Decimal("0.00"),
    )
    c = _mk_security_txn(
        name="Other Co",
        price=Decimal("99.00"),
        quantity=Decimal("5"),
        commission=Decimal("1.00"),
        transfer_amount=Decimal("0.00"),
    )

    # Act / Assert
    # Identical field values → should compare equal on dataclasses (if eq=True default)
    assert a == b, "Objects with identical field values should be equal."
    assert a != c, "Objects with different field values should not be equal."


def test_hashability_if_frozen_otherwise_skip():
    # Arrange
    a = _mk_security_txn()
    b = _mk_security_txn()
    c = _mk_security_txn(name="Other Co", price=Decimal("10"), quantity=Decimal("1"))

    # Act / Assert
    # Some dataclasses are frozen (hashable), some are not.
    # We assert hash-based behavior only if hashing is supported.
    try:
        s = {a, b, c}
    except TypeError:
        pytest.skip("QifSecurityTxn is not hashable (dataclass not frozen).")
    else:
        # If hashable: equal objects must collapse to one set member
        assert len(s) == 2, "Equal instances should hash equal and collapse in a set."


def test_repr_contains_key_fields():
    # Arrange
    t = _mk_security_txn(
        name="Apple Inc.", price=Decimal("150.00"), quantity=Decimal("2")
    )

    # Act
    r = repr(t)
    s = str(t)

    # Assert (not strict formatting checks; just presence of key info)
    assert "Apple" in r or "Apple" in s
    assert "150.00" in r or "150.00" in s
    assert "2" in r or "2" in s
