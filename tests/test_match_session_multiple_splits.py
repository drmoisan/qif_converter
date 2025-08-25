from __future__ import annotations

from datetime import date
from decimal import Decimal

from qif_converter.match_session import MatchSession, TxnLegacyView
from qif_converter.excel_row import ExcelRow
from qif_converter.excel_txn_group import ExcelTxnGroup


def _mk_tx(datestr: str, amt: str, **extras):
    """Minimal QIF txn dict."""
    base = {"date": datestr, "amount": amt, "payee": "P", "memo": "", "category": ""}
    base.update(extras)
    return base


def _mk_group(rows, gid=None) -> ExcelTxnGroup:
    """Build an ExcelTxnGroup from rows; total by sum, date from first row."""
    assert rows, "rows must not be empty"
    total = sum((r.amount for r in rows), Decimal("0"))
    return ExcelTxnGroup(
        gid=(gid if gid is not None else rows[0].txn_id),
        date=rows[0].date,
        total_amount=total,
        rows=tuple(rows),
    )


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
