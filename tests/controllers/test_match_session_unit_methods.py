from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional

import pytest

# New API location
from quicken_helper.controllers.match_session import MatchSession


# ---------------------------- protocol stubs ----------------------------------

@dataclass(frozen=True)
class StubTxn:
    """Minimal ITransaction-shaped stub (date, amount, payee)."""
    date: date
    amount: Decimal
    payee: str = ""


def _mk_tx(d: str, a: str, p: str = "") -> StubTxn:
    y, m, dd = map(int, d.split("-"))
    return StubTxn(date=date(y, m, dd), amount=Decimal(a), payee=p)


@pytest.fixture(autouse=True)
def _identity_convert_value(monkeypatch):
    """Isolation: treat convert_value as identity (no adapters)."""
    import quicken_helper.controllers.match_session as ms
    monkeypatch.setattr(ms, "convert_value", lambda _t, v: v)


# ------------------------------ nonmatch_reason -------------------------------

def test_nonmatch_reason_reports_no_equal_amount_candidates():
    """Negative: when no Excel txn has equal amount, nonmatch_reason should say so and include the amount."""
    s = MatchSession(
        txns=[_mk_tx("2025-01-10", "-10.00", "A")],
        excel_txns=[_mk_tx("2025-01-10", "-9.99", "A")],
    )
    msg = s.nonmatch_reason(bank_index=0)
    assert "No equal-amount candidates" in msg and "10.00" in msg


def test_nonmatch_reason_prefers_closer_date_and_mentions_features():
    """Positive: among equal-amount candidates, the closer date wins; message includes date delta and payee sim."""
    s = MatchSession(
        txns=[_mk_tx("2025-01-10", "-10.00", "Acme")],
        excel_txns=[
            _mk_tx("2025-01-11", "-10.00", "Acme LLC"),   # 1 day
            _mk_tx("2025-01-20", "-10.00", "Different"),  # 10 days
        ],
    )
    msg = s.nonmatch_reason(bank_index=0)
    assert "Best candidate index 0" in msg
    assert "Date Δ = 1 day(s)" in msg
    assert "Payee sim =" in msg


# -------------------------------- auto_match ----------------------------------

def test_auto_match_greedy_one_to_one_with_threshold():
    """Positive: auto_match yields one-to-one pairs, respects threshold, and leaves unmatched lists consistent."""
    s = MatchSession(
        txns=[_mk_tx("2025-08-01", "10.00", "A"), _mk_tx("2025-08-02", "20.00", "B")],
        excel_txns=[_mk_tx("2025-08-01", "10.00", "A*"), _mk_tx("2025-08-12", "20.00", "B*")],
    )

    pairs = s.auto_match(min_score=0)  # permissive threshold for the test

    assert len(pairs) == 2
    assert s.unmatched_bank == []
    assert s.unmatched_excel == []


# ------------------------------- manual_match ---------------------------------

def test_manual_match_overrides_conflicts_and_is_one_to_one():
    """Positive: manual_match overrides any conflicting existing pairings, keeping the mapping one-to-one."""
    s = MatchSession(
        txns=[_mk_tx("2025-08-01", "10.00"), _mk_tx("2025-08-02", "20.00")],
        excel_txns=[_mk_tx("2025-08-01", "10.00"), _mk_tx("2025-08-02", "20.00")],
    )
    # Prime with an initial mapping
    s.manual_match(0, 0)
    s.manual_match(1, 1)

    # Now force 0 -> 1, which must unhook 1 -> 1
    s.manual_match(0, 1)

    assert s.pairs == [(s.bank_txns[0], s.excel_txns[1])]
    assert s.unmatched_bank == [s.bank_txns[1]]
    assert s.unmatched_excel == [s.excel_txns[0]]


# ------------------------------ manual_unmatch --------------------------------

def test_manual_unmatch_by_bank_and_by_excel_index():
    """Positive: manual_unmatch removes pairs when called by either bank_index or excel_index."""
    s = MatchSession(
        txns=[_mk_tx("2025-08-01", "10.00")],
        excel_txns=[_mk_tx("2025-08-01", "10.00")],
    )
    s.manual_match(0, 0)

    # Remove by bank index
    s.manual_unmatch(bank_index=0)
    assert s.pairs == [] and s.unmatched_bank and s.unmatched_excel

    # Re-pair and remove by excel index
    s.manual_match(0, 0)
    s.manual_unmatch(excel_index=0)
    assert s.pairs == [] and s.unmatched_bank and s.unmatched_excel
