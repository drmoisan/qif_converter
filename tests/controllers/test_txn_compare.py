from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

import pytest

from quicken_helper.controllers.transaction_compare import compare_txn


@dataclass(frozen=True)
class StubTxn:
    """Minimal ITransaction-shaped stub (only attributes used by compare_txn)."""
    date: Optional[date]
    amount: Decimal
    payee: str = ""


def _t(d: Optional[str], a: str, p: str) -> StubTxn:
    """Helper to build a StubTxn from strings."""
    dt = None if d is None else date.fromisoformat(d)
    return StubTxn(date=dt, amount=Decimal(a), payee=p)


def test_amount_mismatch_is_hard_gate():
    """Negative: amount mismatch should trigger the hard gate and a negative score with a clear reason."""
    a = _t("2025-08-01", "10.00", "Acme")
    b = _t("2025-08-02", "11.00", "Acme")

    ms = compare_txn(a, b)

    assert ms.score < 0, "Amount mismatch must yield a losing/negative score"
    joined = "; ".join(ms.reasons)
    assert "Amount differs by" in joined
    assert ms.features["amount_a"] == "10.00"
    assert ms.features["amount_b"] == "11.00"


def test_date_proximity_scoring_is_monotonic_with_equal_amounts():
    """Positive: with equal amounts and same payee, closer dates must score higher (0d > 5d > 10d)."""
    base = _t("2025-08-01", "25.00", "Acme")
    same_day = _t("2025-08-01", "25.00", "Acme")
    plus_5 = _t("2025-08-06", "25.00", "Acme")   # 5 days
    plus_10 = _t("2025-08-11", "25.00", "Acme")  # 10 days

    s0 = compare_txn(base, same_day)
    s5 = compare_txn(base, plus_5)
    s10 = compare_txn(base, plus_10)

    assert s0.score > s5.score > s10.score >= 0
    assert any("Same date" in r for r in s0.reasons), "Same-date case should explain the bonus"
    assert s5.features["date_days"] == 5
    assert s10.features["date_days"] == 10


def test_payee_similarity_breaks_ties_when_dates_equal():
    """Positive: with equal amounts and same date, higher payee similarity should yield higher score."""
    a = _t("2025-08-01", "50.00", "Acme")
    b_close = _t("2025-08-01", "50.00", "Acme LLC")   # similar
    b_far = _t("2025-08-01", "50.00", "Different Co") # dissimilar

    ms_close = compare_txn(a, b_close)
    ms_far = compare_txn(a, b_far)

    assert ms_close.score > ms_far.score
    assert 0.0 <= ms_close.features["payee_sim"] <= 1.0
    assert 0.0 <= ms_far.features["payee_sim"] <= 1.0
    # Should mention payee similarity in reasons
    assert any("Payee similarity" in r for r in ms_close.reasons)
    assert any("Payee similarity" in r for r in ms_far.reasons)


def test_missing_dates_are_neutral_on_date_component():
    """Edge: if one side lacks a date, score is based on payee similarity only; reason clarifies neutrality."""
    a = _t("2025-08-01", "10.00", "Acme")
    b = _t(None, "10.00", "Acme")  # no date on one side

    ms = compare_txn(a, b)

    assert ms.features["date_days"] is None
    assert any("No date on one side (+0)" in r for r in ms.reasons)
    assert ms.score >= 0, "With equal amounts and identical payee, score should be non-negative"


def test_features_dictionary_contains_expected_keys_and_types():
    """Positive: features should include normalized amounts, dates, payees, deltas, and similarity."""
    a = _t("2025-08-10", "100.00", "Globex")
    b = _t("2025-08-12", "100.00", "Globex Inc")

    ms = compare_txn(a, b)
    f = ms.features

    # Presence checks
    for key in ("amount_a", "amount_b", "amount_diff", "date_a", "date_b", "date_days", "payee_a", "payee_b", "payee_sim"):
        assert key in f, f"features should contain '{key}'"

    # Type/format sanity
    assert isinstance(f["amount_a"], str) and isinstance(f["amount_b"], str)
    assert isinstance(f["amount_diff"], str)
    # date_a/date_b are ISO strings
    assert isinstance(f["date_a"], str) and f["date_a"].startswith("2025-08-")
    assert isinstance(f["date_b"], str) and f["date_b"].startswith("2025-08-")
    assert isinstance(f["date_days"], int)
    assert isinstance(f["payee_a"], str) and isinstance(f["payee_b"], str)
    assert isinstance(f["payee_sim"], float)
