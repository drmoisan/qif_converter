from __future__ import annotations

import pytest
from datetime import date
from _decimal import Decimal

from qif_converter.match_helpers import TxnLegacyView
from qif_converter.match_session import MatchSession
from qif_converter.excel_row import ExcelRow
from qif_converter.excel_txn_group import ExcelTxnGroup
#from qif_converter.qif_txn_view import QIFTxnView
from qif_converter.match_session import TxnLegacyView


def _mk_tx(datestr: str, amt: str, **extras):
    """Small helper to build a QIF txn dict quickly."""
    base = {"date": datestr, "amount": amt, "payee": "P", "memo": "", "category": ""}
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
    # return ExcelTxnGroup(gid=group_id, date=rows[0].date, total_amount=total, rows=tuple(rows))
    return ExcelTxnGroup(
        gid=(gid if gid is not None else rows[0].txn_id),
        date=rows[0].date,
        total_amount=total,
        rows=tuple(rows),
    )

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
        #assert isinstance(q, QIFTxnView)
        assert isinstance(q, TxnLegacyView)
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


def test_auto_match_group_with_three_splits_matches_total_and_window():
    # Arrange: txn −60.00 should match group G (−20 −20 −20) on 2025-08-10 vs 2025-08-12 (±2 days)
    txns = [_mk_tx("2025-08-10", "-60.00")]
    rows_g = [
        ExcelRow(idx=0, txn_id="G", date=date(2025, 8, 12), amount=Decimal("-20.00"), item="a", category="X", rationale="r"),
        ExcelRow(idx=1, txn_id="G", date=date(2025, 8, 12), amount=Decimal("-20.00"), item="b", category="Y", rationale="r"),
        ExcelRow(idx=2, txn_id="G", date=date(2025, 8, 12), amount=Decimal("-20.00"), item="c", category="Z", rationale="r"),
    ]
    g = _mk_group(rows_g, gid="G")
    session = MatchSession(txns, excel_groups=[g])

    # Act
    session.auto_match()
    pairs = session.matched_pairs()

    # Assert: total must match and date cost within 0..3 days
    assert len(pairs) == 1
    q, grp, cost = pairs[0]
    assert isinstance(q, TxnLegacyView) and grp.gid == "G"
    assert q.amount == grp.total_amount and cost in (0, 1, 2, 3)


def test_auto_match_tie_breaks_equal_cost_by_group_index_deterministically():
    # Arrange: both groups sum to −40 and are ±1 day away; earlier index should win.
    txns = [_mk_tx("2025-08-10", "-40.00")]

    # g0: date 2025-08-11, two splits
    g0_rows = [
        ExcelRow(idx=0, txn_id="A", date=date(2025, 8, 11), amount=Decimal("-15.00"), item="x", category="C", rationale="r"),
        ExcelRow(idx=1, txn_id="A", date=date(2025, 8, 11), amount=Decimal("-25.00"), item="y", category="C", rationale="r"),
    ]
    g0 = _mk_group(g0_rows, gid="A")

    # g1: date 2025-08-09, three splits (same total, same |date diff| = 1)
    g1_rows = [
        ExcelRow(idx=2, txn_id="B", date=date(2025, 8, 9), amount=Decimal("-10.00"), item="u", category="C", rationale="r"),
        ExcelRow(idx=3, txn_id="B", date=date(2025, 8, 9), amount=Decimal("-15.00"), item="v", category="C", rationale="r"),
        ExcelRow(idx=4, txn_id="B", date=date(2025, 8, 9), amount=Decimal("-15.00"), item="w", category="C", rationale="r"),
    ]
    g1 = _mk_group(g1_rows, gid="B")

    # Put g0 first so its group index gi=0 — ties on (cost, ti) should pick lower gi.
    session = MatchSession(txns, excel_groups=[g0, g1])

    # Act
    session.auto_match()
    pairs = session.matched_pairs()

    # Assert: chooses g0 (index 0) on equal date-cost (deterministic tie-break by gi)
    assert len(pairs) == 1
    _, grp, cost = pairs[0]
    assert grp.gid == "A"
    assert cost in (0, 1, 2, 3)


def test_auto_match_multiple_txns_respects_one_to_one_when_many_groups_exist():
    # Arrange: two txns needing −30 each; three candidate groups exist (each −30).
    txns = [
        _mk_tx("2025-08-05", "-30.00"),
        _mk_tx("2025-08-06", "-30.00"),
    ]
    # Three groups, all within window, each with multiple splits
    g_rows = [
        [ExcelRow(idx=0, txn_id="G1", date=date(2025, 8, 5), amount=Decimal("-10.00"), item="a1", category="C", rationale="r"),
         ExcelRow(idx=1, txn_id="G1", date=date(2025, 8, 5), amount=Decimal("-20.00"), item="a2", category="C", rationale="r")],
        [ExcelRow(idx=2, txn_id="G2", date=date(2025, 8, 6), amount=Decimal("-12.00"), item="b1", category="C", rationale="r"),
         ExcelRow(idx=3, txn_id="G2", date=date(2025, 8, 6), amount=Decimal("-18.00"), item="b2", category="C", rationale="r")],
        [ExcelRow(idx=4, txn_id="G3", date=date(2025, 8, 7), amount=Decimal("-15.00"), item="c1", category="C", rationale="r"),
         ExcelRow(idx=5, txn_id="G3", date=date(2025, 8, 7), amount=Decimal("-15.00"), item="c2", category="C", rationale="r")],
    ]
    g1, g2, g3 = (_mk_group(g_rows[0], gid="G1"),
                  _mk_group(g_rows[1], gid="G2"),
                  _mk_group(g_rows[2], gid="G3"))
    session = MatchSession(txns, excel_groups=[g1, g2, g3])

    # Act
    session.auto_match()
    pairs = session.matched_pairs()

    # Assert: exactly two pairs; each Excel group used at most once (one-to-one)
    assert len(pairs) == 2
    used_gids = {grp.gid for _, grp, _ in pairs}
    assert used_gids.issubset({"G1", "G2", "G3"}) and len(used_gids) == 2


def test_auto_match_ignores_multi_split_group_outside_window_even_if_totals_match():
    # Arrange: txn −50.00; two groups total −50.00, but only one is within ±3 days.
    txns = [_mk_tx("2025-08-10", "-50.00")]
    g_far_rows = [
        ExcelRow(idx=0, txn_id="Z1", date=date(2025, 8, 20), amount=Decimal("-20.00"), item="x", category="C", rationale="r"),
        ExcelRow(idx=1, txn_id="Z1", date=date(2025, 8, 20), amount=Decimal("-30.00"), item="y", category="C", rationale="r"),
    ]
    g_near_rows = [
        ExcelRow(idx=2, txn_id="Z2", date=date(2025, 8, 11), amount=Decimal("-25.00"), item="u", category="C", rationale="r"),
        ExcelRow(idx=3, txn_id="Z2", date=date(2025, 8, 11), amount=Decimal("-25.00"), item="v", category="C", rationale="r"),
    ]
    g_far = _mk_group(g_far_rows, gid="Z1")
    g_near = _mk_group(g_near_rows, gid="Z2")
    session = MatchSession(txns, excel_groups=[g_far, g_near])

    # Act
    session.auto_match()
    pairs = session.matched_pairs()

    # Assert: only the in-window group is matched
    assert len(pairs) == 1
    _, grp, cost = pairs[0]
    assert grp.gid == "Z2" and cost in (0, 1, 2, 3)
