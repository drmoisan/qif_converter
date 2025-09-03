from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from quicken_helper.data_model.excel.excel_row import ExcelRow
from quicken_helper.data_model.excel.excel_txn_group import ExcelTxnGroup


def _mk_row(
    idx: int,
    gid: object,
    d: date,
    amt: str,
    item: str = "Item",
    cat: str = "Cat",
    rationale: str = "Why",
) -> ExcelRow:
    """Small helper to create an ExcelRow quickly for tests."""
    return ExcelRow(
        idx=idx,
        txn_id=gid,
        date=d,
        amount=Decimal(amt),
        memo=item,
        category=cat,
        rationale=rationale,
    )


def test_excel_txn_group_basic_fields_and_sum():
    # Arrange
    d = date(2025, 8, 1)
    r1 = _mk_row(0, "G1", d, "-7.00", "A", "Food", "a")
    r2 = _mk_row(1, "G1", d, "-5.00", "B", "Food", "b")
    total = r1.amount + r2.amount

    # Act
    g = ExcelTxnGroup(gid="G1", date=d, total_amount=total, rows=(r1, r2))

    # Assert
    assert g.gid == "G1"
    assert g.date == d
    assert g.total_amount == Decimal("-12.00")
    assert isinstance(g.rows, tuple)
    assert g.rows == (r1, r2)


def test_excel_txn_group_is_immutable_and_hashable():
    # Arrange
    d = date(2025, 8, 2)
    r = _mk_row(0, "Z9", d, "-10.00")
    g = ExcelTxnGroup(gid="Z9", date=d, total_amount=Decimal("-10.00"), rows=(r,))

    # Act / Assert: immutability
    with pytest.raises(FrozenInstanceError):
        setattr(g, "total_amount", Decimal("-11.00"))  # frozen dataclass

    # Act / Assert: hashable & equality semantics
    same = ExcelTxnGroup(gid="Z9", date=d, total_amount=Decimal("-10.00"), rows=(r,))
    different = ExcelTxnGroup(
        gid="Z9", date=d, total_amount=Decimal("-9.99"), rows=(r,)
    )

    s = {g, same}
    assert len(s) == 1  # equal objects hash the same → set dedupes
    assert g == same
    assert g != different


def test_excel_txn_group_accepts_various_gid_types():
    # Arrange
    d = date(2025, 8, 3)
    r_str = _mk_row(0, "S1", d, "-1.00")
    r_int = _mk_row(1, 42, d, "-2.00")
    r_tuple = _mk_row(2, ("bundle", 1), d, "-3.00")

    g1 = ExcelTxnGroup(gid="S1", date=d, total_amount=Decimal("-1.00"), rows=(r_str,))
    g2 = ExcelTxnGroup(gid=42, date=d, total_amount=Decimal("-2.00"), rows=(r_int,))
    g3 = ExcelTxnGroup(
        gid=("bundle", 1), date=d, total_amount=Decimal("-3.00"), rows=(r_tuple,)
    )

    # Assert
    assert g1.gid == "S1"
    assert g2.gid == 42
    assert g3.gid == ("bundle", 1)

    # All should be usable as dict keys (hashable)
    dct = {g1: "a", g2: "b", g3: "c"}
    assert dct[g1] == "a"
    assert dct[g2] == "b"
    assert dct[g3] == "c"


def test_excel_txn_group_allows_empty_rows_but_preserves_fields():
    # Arrange
    d = date(2025, 8, 4)
    # While typical usage provides one or more rows, the dataclass itself
    # doesn’t enforce non-empty rows — this verifies the class stores fields intact.
    g = ExcelTxnGroup(gid="E0", date=d, total_amount=Decimal("0.00"), rows=())

    # Assert
    assert g.gid == "E0"
    assert g.date == d
    assert g.total_amount == Decimal("0.00")
    assert g.rows == ()
    assert isinstance(g.rows, tuple)
