import pytest
from datetime import date
from decimal import Decimal

from qif_converter.match_session import MatchSession
from qif_converter.excel_row import ExcelRow
from qif_converter.excel_txn_group import ExcelTxnGroup
from qif_converter.qif_txn_view import QIFTxnView


def _mk_tx(d: str, amt: str, **extras):
    """Small helper to build a QIF txn dict quickly."""
    base = {"date": d, "amount": amt, "payee": "P", "memo": "", "category": ""}
    base.update(extras)
    return base


def _mk_group(rows, gid=None) -> ExcelTxnGroup:
    """
    Build an ExcelTxnGroup from a non-empty list of ExcelRow by summing amounts
    and using the first row's date. Provides deterministic construction that
    avoids any factory method dependency.
    """
    assert rows, "rows must not be empty"
    group_id = gid if gid is not None else rows[0].txn_id
    total = sum((r.amount for r in rows), Decimal("0"))
    return ExcelTxnGroup(gid=group_id, date=rows[0].date, total_amount=total, rows=tuple(rows))


# ---------------------------------------------------------------------------
# Group-mode (split-aware) tests
# ---------------------------------------------------------------------------

def test_auto_match_groups_matches_by_total_and_date_window():
    # Arrange
    txns = [
        _mk_tx("2025-08-01", "-50.00"),  # will match G1 (sum -30 + -20)
        _mk_tx("2025-08-02", "-20.00"),  # will match G2 (sum -20)
    ]

    rows_g1 = [
        ExcelRow(idx=0, txn_id="G1", date=date(2025, 8, 1), amount=Decimal("-30.00"),
                 item="A1", category="Food:A", rationale="r1"),
        ExcelRow(idx=1, txn_id="G1", date=date(2025, 8, 1), amount=Decimal("-20.00"),
                 item="A2", category="Food:B", rationale="r2"),
    ]
    rows_g2 = [
        ExcelRow(idx=2, txn_id="G2", date=date(2025, 8, 2), amount=Decimal("-20.00"),
                 item="B1", category="Food:C", rationale="r3"),
    ]
    g1 = _mk_group(rows_g1, gid="G1")
    g2 = _mk_group(rows_g2, gid="G2")
    session = MatchSession(txns, excel_groups=[g1, g2])

    # Act
    session.auto_match()
    pairs = session.matched_pairs()

    # Assert
    assert len(pairs) == 2, "Both transactions should auto-match by total and ±3 day window."
    for q, grp, cost in pairs:
        assert isinstance(q, QIFTxnView)
        assert isinstance(grp, ExcelTxnGroup)
        assert q.amount == grp.total_amount, "Transaction must match its group's total amount."
        assert cost in (0, 1, 2, 3), "Date cost should be within ±3 days."


def test_auto_match_groups_prefers_in_window_and_ignores_out_of_window():
    # Arrange
    txns = [
        _mk_tx("2025-08-01", "-42.00"),
    ]
    # One candidate out of window (10 days away)
    g_far = _mk_group([
        ExcelRow(idx=0, txn_id="Z1", date=date(2025, 8, 11), amount=Decimal("-42.00"),
                 item="x", category="C", rationale="far"),
    ], gid="Z1")
    # One candidate inside window (1 day away)
    g_near = _mk_group([
        ExcelRow(idx=1, txn_id="Z2", date=date(2025, 8, 2), amount=Decimal("-42.00"),
                 item="y", category="C", rationale="near"),
    ], gid="Z2")

    session = MatchSession(txns, excel_groups=[g_far, g_near])

    # Act
    session.auto_match()
    pairs = session.matched_pairs()

    # Assert
    assert len(pairs) == 1, "Only the in-window group should be selected."
    q, grp, cost = pairs[0]
    assert grp.gid == "Z2", "The group within ±3 days should be preferred."
    assert cost in (0, 1, 2, 3)


def test_apply_updates_overwrites_splits_from_matched_groups():
    # Arrange
    txns = [
        _mk_tx("2025-07-02", "-20.00",
              splits=[
                  {"category": "Old:Cat", "memo": "old1", "amount": Decimal("-10.00")},
                  {"category": "Old:Cat", "memo": "old2", "amount": Decimal("-10.00")},
              ]),
    ]
    rows = [
        ExcelRow(idx=0, txn_id="B", date=date(2025, 7, 2), amount=Decimal("-10.00"),
                 item="i2a", category="New:C2", rationale="R2a"),
        ExcelRow(idx=1, txn_id="B", date=date(2025, 7, 2), amount=Decimal("-10.00"),
                 item="i2b", category="New:C3", rationale="R2b"),
    ]
    grp = _mk_group(rows, gid="B")
    session = MatchSession(txns, excel_groups=[grp])

    # Act
    session.auto_match()
    session.apply_updates()

    # Assert
    updated = txns[0]
    assert "splits" in updated and len(updated["splits"]) == 2, "Existing splits must be replaced."
    cats = [s["category"] for s in updated["splits"]]
    memos = [s["memo"] for s in updated["splits"]]
    amts = [s["amount"] for s in updated["splits"]]
    assert cats == ["New:C2", "New:C3"]
    assert memos == ["i2a", "i2b"]
    assert amts == [Decimal("-10.00"), Decimal("-10.00")]


def test_unmatched_helpers_return_only_unmatched_items_in_group_mode():
    # Arrange
    txns = [
        _mk_tx("2025-07-01", "-30.00"),   # will match
        _mk_tx("2025-07-02", "-20.00"),   # will be unmatched
    ]
    matched_group = _mk_group([
        ExcelRow(idx=0, txn_id="A", date=date(2025, 7, 1), amount=Decimal("-30.00"),
                 item="i1", category="C1", rationale="R1"),
    ], gid="A")
    # Same total but outside date window → remains unmatched
    unmatched_group = _mk_group([
        ExcelRow(idx=1, txn_id="B", date=date(2025, 8, 1), amount=Decimal("-20.00"),
                 item="i2", category="C2", rationale="R2"),
    ], gid="B")

    session = MatchSession(txns, excel_groups=[matched_group, unmatched_group])

    # Act
    session.auto_match()
    unmatched_q = session.unmatched_qif()
    unmatched_e = session.unmatched_excel()

    # Assert
    assert len(session.matched_pairs()) == 1
    # QIF unmatched should contain the second txn (date 2025-07-02)
    assert len(unmatched_q) == 1 and unmatched_q[0].date.isoformat() == "2025-07-02"
    # Excel unmatched should contain only the second (out-of-window) group
    assert len(unmatched_e) == 1 and isinstance(unmatched_e[0], ExcelTxnGroup)
    assert unmatched_e[0].gid == unmatched_group.gid


# ---------------------------------------------------------------------------
# Legacy row-mode tests (fallback)
# ---------------------------------------------------------------------------

def test_legacy_row_mode_auto_match_by_amount_and_date():
    # Arrange
    txns = [
        _mk_tx("2025-08-01", "-10.00"),
        _mk_tx("2025-08-02", "-20.00"),
    ]
    rows = [
        ExcelRow(idx=0, txn_id="r1", date=date(2025, 8, 1), amount=Decimal("-10.00"),
                 item="x1", category="C1", rationale="R1"),
        ExcelRow(idx=1, txn_id="r2", date=date(2025, 8, 2), amount=Decimal("-20.00"),
                 item="x2", category="C2", rationale="R2"),
    ]
    session = MatchSession(txns, excel_rows=rows)

    # Act
    session.auto_match()
    pairs = session.matched_pairs()

    # Assert
    assert len(pairs) == 2, "Both transactions should match legacy rows by amount and date."
    assert all(isinstance(p[1], ExcelRow) for p in pairs), "Legacy mode should return ExcelRow in pairs."
    assert all(p[2] in (0, 1, 2, 3) for p in pairs), "Date cost should be within ±3 days."
