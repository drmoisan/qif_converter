from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal
from typing import get_type_hints

import pytest

from quicken_helper.data_model.excel.excel_row import ExcelRow


def test_excel_row_basic_fields_and_equality():
    # Arrange
    r1 = ExcelRow(
        idx=0,
        txn_id="T123",
        date=date(2025, 1, 2),
        amount=Decimal("-12.34"),
        memo="Latte",
        category="Food:Coffee",
        rationale="receipt 42",
    )
    r2 = ExcelRow(
        idx=0,
        txn_id="T123",
        date=date(2025, 1, 2),
        amount=Decimal("-12.34"),
        memo="Latte",
        category="Food:Coffee",
        rationale="receipt 42",
    )
    r3 = ExcelRow(
        idx=1,  # different idx
        txn_id="T123",
        date=date(2025, 1, 2),
        amount=Decimal("-12.34"),
        memo="Latte",
        category="Food:Coffee",
        rationale="receipt 42",
    )

    # Act / Assert
    assert (
        r1 == r2
    ), "Two ExcelRow instances with identical field values should be equal"
    assert r1 != r3, "Differing idx should make rows unequal"
    assert hash(r1) == hash(r2), "Equal frozen dataclasses must have equal hashes"


def test_excel_row_is_immutable_and_hashable():
    # Arrange
    r = ExcelRow(
        idx=7,
        txn_id="G-99",
        date=date(2024, 12, 31),
        amount=Decimal("0"),
        memo="",
        category="",
        rationale="",
    )

    # Act / Assert immutability
    with pytest.raises(FrozenInstanceError):
        # Use setattr to avoid IDE “read-only” warning while still triggering runtime error
        setattr(r, "idx", 9)

    # Act / Assert hashability (usable as dict key / set member)
    d = {r: "ok"}
    s = {r}
    assert d[r] == "ok"
    assert r in s


def test_excel_row_repr_contains_useful_fields():
    # Arrange
    r = ExcelRow(
        idx=3,
        txn_id="ABC",
        date=date(2025, 5, 5),
        amount=Decimal("1.23"),
        memo="Thing",
        category="Misc",
        rationale="why",
    )

    # Act
    rep = repr(r)

    # Assert (don’t pin exact formatting, just check key bits are present)
    assert "ExcelRow" in rep
    assert "txn_id='ABC'" in rep or 'txn_id="ABC"' in rep
    assert "amount=Decimal('1.23')" in rep or 'amount=Decimal("1.23")' in rep


def test_excel_row_type_hints_are_present_and_correct():
    # Arrange / Act
    hints = get_type_hints(ExcelRow)

    # Assert
    # Note: we check the presence and core expected types; get_type_hints resolves forward refs.
    assert hints["idx"] is int
    assert hints["txn_id"] is str
    assert hints["memo"] is str
    assert hints["category"] is str
    assert hints["rationale"] is str

    # Date & Decimal are imported types
    from datetime import date as _date
    from decimal import Decimal as _Decimal

    assert hints["date"] is _date
    assert hints["amount"] is _Decimal


def test_excel_row_inequality_when_any_field_differs():
    # Arrange
    base = dict(
        idx=0,
        txn_id="X",
        date=date(2025, 1, 1),
        amount=Decimal("10"),
        memo="A",
        category="C",
        rationale="R",
    )
    a = ExcelRow(**base)
    b = ExcelRow(**{**base, "txn_id": "Y"})  # change one field

    # Act / Assert
    assert a != b
