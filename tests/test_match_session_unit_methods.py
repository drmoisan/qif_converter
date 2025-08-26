from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from qif_converter.match_session import MatchSession
from qif_converter.qif_item_key import QIFItemKey
from qif_converter.excel_row import ExcelRow
from qif_converter.excel_txn_group import ExcelTxnGroup


# ------------------------------- small helpers --------------------------------

def _mk_session(txns, *, groups=None, rows=None) -> MatchSession:
    """Build a MatchSession with provided QIF and either groups (preferred) or rows."""
    return MatchSession(txns=txns, excel_groups=groups or [], excel_rows=rows or [])


def _mk_group(gid: str, d: date, total: str | Decimal, rows: tuple[ExcelRow, ...] = ()) -> ExcelTxnGroup:
    """Convenience for ExcelTxnGroup with Decimal coercion."""
    return ExcelTxnGroup(gid=gid, date=d, total_amount=Decimal(str(total)), rows=rows)


def _mk_row(idx: int, gid: str, d: date, amt: str | Decimal, item="i", cat="c", rat="r") -> ExcelRow:
    """Convenience for ExcelRow with Decimal coercion."""
    return ExcelRow(idx=idx, txn_id=gid, date=d, amount=Decimal(str(amt)), item=item, category=cat, rationale=rat)


# ------------------------------ nonmatch_reason --------------------------------

def test_nonmatch_reason_group_amount_differs():
    """nonmatch_reason (group mode): returns amount-mismatch reason when totals differ."""
    qdate = date(2025, 1, 10)
    session = _mk_session([{"date": qdate.isoformat(), "amount": "-10.00"}],
                          groups=[_mk_group("G", qdate, "-9.99")])
    q = session.txn_views[0]
    reason = session.nonmatch_reason(q, session.excel_groups[0])
    assert "Total amount differs" in reason and "QIF -10.00" in reason and "Excel group -9.99" in reason


def test_nonmatch_reason_group_date_outside_window():
    """nonmatch_reason (group mode): returns ±3-days window violation message."""
    qdate = date(2025, 1, 10)
    gdate = qdate + timedelta(days=9)
    session = _mk_session([{"date": qdate.isoformat(), "amount": "-10.00"}],
                          groups=[_mk_group("G", gdate, "-10.00")])
    q = session.txn_views[0]
    reason = session.nonmatch_reason(q, session.excel_groups[0])
    assert "Date outside ±3 days" in reason and qdate.isoformat() in reason and gdate.isoformat() in reason


def test_nonmatch_reason_group_conflicts_and_closer_date():
    """nonmatch_reason (group mode): reports existing conflicts and the 'closer date' hint.

    We verify two branches:
      • If the same QIF key is already matched to a different group → 'QIF txn is already matched.'
      • If date is within window but not equal, it can return 'Auto-match preferred a closer date (day diff = N).'
    """
    qdate = date(2025, 1, 10)
    g1 = _mk_group("G1", qdate, "-10.00")
    g2 = _mk_group("G2", qdate + timedelta(days=1), "-10.00")
    session = _mk_session([{"date": qdate.isoformat(), "amount": "-10.00"}], groups=[g1, g2])
    q = session.txn_views[0]

    # Mark q as already matched to g1; asking about g2 should yield the "already matched" message.
    session.qif_to_excel_group[q.key] = 0
    session.excel_group_to_qif[0] = q.key
    reason1 = session.nonmatch_reason(q, g2)
    assert reason1 == "QIF txn is already matched."

    # Remove conflict; now amounts match and day diff = 1 → closer date message.
    session.qif_to_excel_group.clear()
    session.excel_group_to_qif.clear()
    reason2 = session.nonmatch_reason(q, g2)
    assert reason2.startswith("Auto-match preferred a closer date (day diff = 1)")


def test_nonmatch_reason_group_selected_another_candidate_on_tie():
    """nonmatch_reason (group mode): when amount and date are identical and no conflicts,
    returns 'Auto-match selected another candidate.' (tie / alternate choice)."""
    qdate = date(2025, 1, 10)
    g = _mk_group("G", qdate, "-10.00")
    session = _mk_session([{"date": qdate.isoformat(), "amount": "-10.00"}], groups=[g])
    q = session.txn_views[0]
    assert session.nonmatch_reason(q, g) == "Auto-match selected another candidate."


def test_nonmatch_reason_legacy_amount_date_conflicts_and_closer():
    """nonmatch_reason (legacy row mode): amount mismatch, date window fail, row/QIF conflicts, and closer-date hint."""
    qdate = date(2025, 1, 10)
    r_ok = _mk_row(0, "A", qdate + timedelta(days=1), "-10.00")
    r_amt = _mk_row(1, "B", qdate, "-9.99")
    r_far = _mk_row(2, "C", qdate + timedelta(days=9), "-10.00")
    session = _mk_session([{"date": qdate.isoformat(), "amount": "-10.00"}], rows=[r_ok, r_amt, r_far])
    q = session.txn_views[0]

    # amount differs
    assert session.nonmatch_reason(q, r_amt).startswith("Amount differs")

    # date outside window
    assert "Date outside ±3 days" in session.nonmatch_reason(q, r_far)

    # conflicts on legacy maps
    # simulate q mapped to another row (different from r_ok.idx)
    session.qif_to_excel[q.key] = 99
    assert session.nonmatch_reason(q, r_ok) == "QIF item is already matched."
    session.qif_to_excel.clear()

    # row mapped to another qkey
    other_key = QIFItemKey(txn_index=123, split_index=None)
    session.excel_to_qif[r_ok.idx] = other_key
    assert session.nonmatch_reason(q, r_ok) == "Excel row is already matched."
    session.excel_to_qif.clear()

    # closer date hint when diff > 0
    assert session.nonmatch_reason(q, r_ok).startswith("Auto-match preferred a closer date (day diff = 1)")


# -------------------------------- manual_match --------------------------------

def test_manual_match_group_success_and_unhooks_conflicts():
    """manual_match (group mode): succeeds when amount matches and date is in-window,
    unhooks any existing links on both sides, and records the new mapping."""
    qdate = date(2025, 1, 10)
    g1 = _mk_group("G1", qdate, "-10.00")
    g2 = _mk_group("G2", qdate, "-10.00")
    session = _mk_session([{"date": qdate.isoformat(), "amount": "-10.00"}], groups=[g1, g2])
    qkey = session.txn_views[0].key

    # Pre-existing conflicts (wrong links)
    session.qif_to_excel_group[qkey] = 1
    session.excel_group_to_qif[1] = qkey
    other_key = QIFItemKey(99, None)
    session.excel_group_to_qif[0] = other_key
    session.qif_to_excel_group[other_key] = 0

    ok, msg = session.manual_match(qkey, excel_idx=0)
    assert ok and msg == "Matched."
    assert session.qif_to_excel_group == {qkey: 0}
    assert session.excel_group_to_qif == {0: qkey}


def test_manual_match_group_failure_cases():
    """manual_match (group mode): rejects bad indices, amount mismatch, date outside window, unknown QIF key."""
    qdate = date(2025, 1, 10)
    g = _mk_group("G", qdate + timedelta(days=10), "-9.99")
    session = _mk_session([{"date": qdate.isoformat(), "amount": "-10.00"}], groups=[g])
    qkey = session.txn_views[0].key

    # Out of range
    ok, msg = session.manual_match(qkey, excel_idx=1)
    assert not ok and msg == "Excel group index out of range."

    # Amount differs
    ok, msg = session.manual_match(qkey, excel_idx=0)
    assert not ok and msg.startswith("Total amount differs")

    # Date outside ±3
    # Fix amount to match; keep date far
    session.excel_groups[0] = _mk_group("G", g.date, "-10.00")
    ok, msg = session.manual_match(qkey, excel_idx=0)
    assert not ok and msg.startswith("Date outside ±3 days")

    # Unknown QIF key
    bad_key = QIFItemKey(999, None)
    ok, msg = session.manual_match(bad_key, excel_idx=0)
    assert not ok and msg == "QIF item key not found."


def test_manual_match_legacy_success_and_mapping():
    """manual_match (legacy row mode): when there are no groups, excel_idx is a row index;
    succeeds if amount matches and date is in-window, and records qif_to_excel/excel_to_qif."""
    qdate = date(2025, 1, 10)
    r = _mk_row(0, "A", qdate, "-10.00")
    session = _mk_session([{"date": qdate.isoformat(), "amount": "-10.00"}], rows=[r])
    qkey = session.txn_views[0].key

    ok, msg = session.manual_match(qkey, excel_idx=0)
    assert ok and msg == "Matched."
    assert session.qif_to_excel == {qkey: 0}
    assert session.excel_to_qif == {0: qkey}


# ------------------------------- manual_unmatch --------------------------------

def test_manual_unmatch_group_by_qkey_and_by_index():
    """manual_unmatch (group mode): removes existing links when called with qkey or with excel_idx; False when absent."""
    qdate = date(2025, 1, 10)
    g = _mk_group("G", qdate, "-10.00")
    session = _mk_session([{"date": qdate.isoformat(), "amount": "-10.00"}], groups=[g])
    qkey = session.txn_views[0].key

    # Create link
    session.qif_to_excel_group[qkey] = 0
    session.excel_group_to_qif[0] = qkey

    # Remove by qkey
    assert session.manual_unmatch(qkey=qkey) is True
    assert session.qif_to_excel_group == {} and session.excel_group_to_qif == {}

    # Remove by index (absent now) -> False
    assert session.manual_unmatch(excel_idx=0) is False


def test_manual_unmatch_legacy_paths_via_internal_helpers():
    """manual_unmatch/_unmatch_qkey/_unmatch_excel: exercise legacy branches by setting
    session.excel_groups to None, then unlinking legacy maps."""
    qdate = date(2025, 1, 10)
    r = _mk_row(0, "A", qdate, "-10.00")
    session = _mk_session([{"date": qdate.isoformat(), "amount": "-10.00"}], rows=[r])

    # Manually force legacy-mode behavior inside helpers
    session.excel_groups = None

    qkey = session.txn_views[0].key
    session.qif_to_excel[qkey] = 0
    session.excel_to_qif[0] = qkey

    # By qkey:
    assert session.manual_unmatch(qkey=qkey) is True
    assert session.qif_to_excel == {} and session.excel_to_qif == {}

    # Recreate link and remove by excel index (legacy path in _unmatch_excel)
    session.qif_to_excel[qkey] = 0
    session.excel_to_qif[0] = qkey
    assert session.manual_unmatch(excel_idx=0) is True
    assert session.qif_to_excel == {} and session.excel_to_qif == {}


# -------------------------- internal unmatch helpers ---------------------------

def test__unmatch_qkey_group_and__unmatch_group_index_symmetry():
    """_unmatch_qkey_group/_unmatch_group_index: both remove the bi-directional link;
    return False if nothing to remove."""
    qdate = date(2025, 1, 10)
    g = _mk_group("G", qdate, "-10.00")
    session = _mk_session([{"date": qdate.isoformat(), "amount": "-10.00"}], groups=[g])
    qkey = session.txn_views[0].key

    # Nothing yet
    assert session._unmatch_qkey_group(qkey) is False
    assert session._unmatch_group_index(0) is False

    # Link and remove from both directions
    session.qif_to_excel_group[qkey] = 0
    session.excel_group_to_qif[0] = qkey
    assert session._unmatch_qkey_group(qkey) is True
    assert session.qif_to_excel_group == {} and session.excel_group_to_qif == {}

    # Recreate and remove by index
    session.qif_to_excel_group[qkey] = 0
    session.excel_group_to_qif[0] = qkey
    assert session._unmatch_group_index(0) is True
    assert session.qif_to_excel_group == {} and session.excel_group_to_qif == {}


def test__unmatch_qkey_and__unmatch_excel_legacy_and_group_modes():
    """_unmatch_qkey/_unmatch_excel: verify they unlink in the correct maps in both group-mode
    (excel_groups is not None) and legacy-mode (excel_groups is None)."""
    qdate = date(2025, 1, 10)
    session = _mk_session([{"date": qdate.isoformat(), "amount": "-10.00"}])

    qkey = session.txn_views[0].key

    # Group-path: excel_groups defaults to [], which is "not None" for helpers
    session.qif_to_excel_group[qkey] = 5
    session.excel_group_to_qif[5] = qkey
    assert session._unmatch_qkey(qkey) is True
    assert session.qif_to_excel_group == {} and session.excel_group_to_qif == {}

    session.qif_to_excel_group[qkey] = 6
    session.excel_group_to_qif[6] = qkey
    assert session._unmatch_excel(6) is True
    assert session.qif_to_excel_group == {} and session.excel_group_to_qif == {}

    # Legacy-path: set excel_groups to None, then unlink via legacy maps
    session.excel_groups = None
    session.qif_to_excel[qkey] = 7
    session.excel_to_qif[7] = qkey
    assert session._unmatch_qkey(qkey) is True
    assert session.qif_to_excel == {} and session.excel_to_qif == {}

    session.qif_to_excel[qkey] = 8
    session.excel_to_qif[8] = qkey
    assert session._unmatch_excel(8) is True
    assert session.qif_to_excel == {} and session.excel_to_qif == {}


# -------------------------------- _group_index ---------------------------------

def test__group_index_identity_and_fallback_and_not_found():
    """_group_index: returns index by identity when the instance is in the list; if a
    different instance with the same (gid, date, total_amount) is provided, returns the
    matching index; returns -1 when no match is found."""
    d = date(2025, 1, 10)
    g0 = _mk_group("G", d, "-10.00")
    session = _mk_session([{"date": d.isoformat(), "amount": "-10.00"}], groups=[g0])

    # Identity
    assert session._group_index(g0) == 0

    # Fallback matching by fields
    g_equiv = _mk_group("G", d, "-10.00")
    assert session._group_index(g_equiv) == 0

    # Not found
    g_other = _mk_group("H", d, "-10.00")
    assert session._group_index(g_other) == -1
