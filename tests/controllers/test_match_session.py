from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import List

import pytest

# System under test
import quicken_helper.controllers.match_session as ms


# ---- Lightweight protocol-shaped stub ---------------------------------------

@dataclass(frozen=True)
class StubTxn:
    """Minimal ITransaction-shaped stub for tests (date, amount, payee only)."""
    date: date
    amount: Decimal
    payee: str = ""


# ---- Helpers -----------------------------------------------------------------

def _mk_bank(*rows: tuple[str, str, str]) -> List[StubTxn]:
    """
    Build bank txns from triples: (YYYY-MM-DD, amount_str, payee).
    """
    out: List[StubTxn] = []
    for d, a, p in rows:
        y, m, dd = map(int, d.split("-"))
        out.append(StubTxn(date=date(y, m, dd), amount=Decimal(a), payee=p))
    return out


def _mk_excel(*rows: tuple[str, str, str]) -> List[StubTxn]:
    """
    Build excel txns from triples: (YYYY-MM-DD, amount_str, payee).
    """
    return _mk_bank(*rows)


# ---- Fixtures ----------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_convert_value(monkeypatch):
    """
    Isolation: stub out convert_value so tests don't depend on concrete implementations
    or the _PROTOCOL_IMPLEMENTATION mapping. It becomes identity.
    """
    monkeypatch.setattr(ms, "convert_value", lambda _t, v: v)


# ---- Tests -------------------------------------------------------------------

def test_constructor_coerces_to_protocol_and_preserves_order():
    """Positive: constructor coerces inputs and preserves element identity/order."""
    bank = _mk_bank(("2025-08-01", "10.00", "A"), ("2025-08-02", "20.00", "B"))
    excel = _mk_excel(("2025-08-01", "10.00", "A*"), ("2025-08-03", "30.00", "C"))

    # Act
    s = ms.MatchSession(bank, excel)

    # Assert
    assert s.bank_txns[0] is bank[0]
    assert s.bank_txns[1] is bank[1]
    assert s.excel_txns[0] is excel[0]
    assert s.excel_txns[1] is excel[1]


def test_auto_match_basic_equal_amount_and_date_tie_break():
    """Positive: auto_match pairs equal-amount txns, preferring closest date then payee similarity."""
    # Arrange: bank has two amounts; excel has same amounts but dates/payees vary
    bank = _mk_bank(
        ("2025-08-01", "10.00", "Acme"),
        ("2025-08-10", "20.00", "Globex"),
    )
    excel = _mk_excel(
        ("2025-08-02", "10.00", "Acme LLC"),   # 1 day apart, good payee sim
        ("2025-08-04", "10.00", "Random"),     # 3 days apart, poor sim
        ("2025-08-12", "20.00", "Globex Inc"), # 2 days apart
    )
    s = ms.MatchSession(bank, excel)

    # Act
    pairs = s.auto_match()

    # Assert: should match (10→first excel 10, 20→its excel 20)
    assert len(pairs) == 2
    assert pairs[0][0] is bank[0] and pairs[0][1] is excel[0]
    assert pairs[1][0] is bank[1] and pairs[1][1] is excel[2]
    # Unmatched lists should be empty
    assert s.unmatched_bank == []
    assert s.unmatched_excel == [excel[1]]


def test_auto_match_respects_threshold_and_rejects_low_scores(monkeypatch):
    """Negative: setting a very high threshold yields no matches."""
    # Arrange: equal amounts but far dates → very low scores
    bank = _mk_bank(("2025-01-01", "50.00", "X"))
    excel = _mk_excel(("2025-03-01", "50.00", "X"))  # 59 days apart
    s = ms.MatchSession(bank, excel)

    # Act
    pairs = s.auto_match(min_score=9999)

    # Assert
    assert pairs == []
    assert s.unmatched_bank == bank
    assert s.unmatched_excel == excel


def test_manual_match_overrides_and_is_one_to_one():
    """Positive: manual_match enforces one-to-one by unhooking conflicting pairs."""
    bank = _mk_bank(
        ("2025-08-01", "10.00", "A"),
        ("2025-08-02", "20.00", "B"),
    )
    excel = _mk_excel(
        ("2025-08-01", "10.00", "A1"),
        ("2025-08-02", "20.00", "B1"),
    )
    s = ms.MatchSession(bank, excel)
    s.auto_match()  # will pair (0->0) and (1->1)

    # Act: force bank[0] to pair with excel[1]
    s.manual_match(bank_index=0, excel_index=1)

    # Assert: bank[1] must be unpaired now
    pairs = s.pairs
    assert pairs == [(bank[0], excel[1])]
    assert s.unmatched_bank == [bank[1]]
    assert s.unmatched_excel == [excel[0]]


def test_manual_unmatch_by_bank_and_excel():
    """Positive: manual_unmatch removes pairs by either side's index."""
    bank = _mk_bank(("2025-08-01", "10.00", "A"))
    excel = _mk_excel(("2025-08-01", "10.00", "A1"))
    s = ms.MatchSession(bank, excel)
    s.auto_match()
    assert s.pairs  # sanity

    # Act / Assert (by bank)
    s.manual_unmatch(bank_index=0)
    assert s.pairs == []
    assert s.unmatched_bank == bank
    assert s.unmatched_excel == excel

    # Re-pair and unmatch by excel index
    s.manual_match(bank_index=0, excel_index=0)
    s.manual_unmatch(excel_index=0)
    assert s.pairs == []
    assert s.unmatched_bank == bank
    assert s.unmatched_excel == excel


def test_nonmatch_reason_reports_when_no_equal_amount_candidates():
    """Negative: nonmatch_reason clearly reports when there are no equal-amount candidates."""
    bank = _mk_bank(("2025-08-01", "10.00", "Acme"))
    excel = _mk_excel(("2025-08-01", "11.00", "Acme"))  # different amount
    s = ms.MatchSession(bank, excel)

    # Act
    msg = s.nonmatch_reason(bank_index=0)

    # Assert
    assert "No equal-amount candidates" in msg
    assert "10.00" in msg  # includes target amount


def test_nonmatch_reason_includes_best_candidate_features():
    """Positive: nonmatch_reason includes score, date delta, and payee similarity with reasons."""
    bank = _mk_bank(("2025-08-10", "25.00", "Globex"))
    # Same amount candidates: one is closer in date, another with worse payee
    excel = _mk_excel(
        ("2025-08-12", "25.00", "Globex Inc"),   # 2 days apart, similar payee
        ("2025-08-20", "25.00", "Different"),    # 10 days apart, poor payee
    )
    s = ms.MatchSession(bank, excel)

    # Act
    msg = s.nonmatch_reason(bank_index=0)

    # Assert
    assert "Best candidate index 0" in msg  # index 0 is the closer-date candidate
    assert "score" in msg
    assert "Date Δ = 2 day(s)" in msg
    assert "Payee sim = " in msg
    # Should also carry human-readable reasons from compare_txn
    assert "day(s) apart" in msg or "Same date" in msg


def test_accessors_pairs_and_unmatched_after_auto_match():
    """Positive: pairs/unmatched_* accessors reflect current session state deterministically."""
    bank = _mk_bank(("2025-08-01", "10.00", "A"), ("2025-08-02", "20.00", "B"))
    excel = _mk_excel(("2025-08-01", "10.00", "A1"))
    s = ms.MatchSession(bank, excel)

    # Act
    s.auto_match()

    # Assert
    assert s.pairs == [(bank[0], excel[0])]
    assert s.unmatched_bank == [bank[1]]
    assert s.unmatched_excel == []