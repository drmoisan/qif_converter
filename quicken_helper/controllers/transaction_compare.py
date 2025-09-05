# quicken_helper/controllers/transaction_compare.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Dict, List, Optional

from quicken_helper.data_model.interfaces import ITransaction

# Tunables: mirror your historical auto_match behavior
_AMOUNT_MUST_MATCH: bool = True  # legacy gate: require exact amount
_MAX_POSITIVE: int = 200  # cap for positive score
_W_DATE_PER_DAY: int = 5  # points lost per day of delta (lower is stricter)
_W_PAYEE_MAX: int = 80  # max points contributed by payee match if amounts equal
_W_DATE_BASE: int = 100  # base credit when dates are identical (when amounts equal)


@dataclass(frozen=True)
class MatchScore:
    """Composite score & explainability for a candidate ITransaction pair."""

    score: int  # higher is better
    reasons: List[str]  # human-readable components explaining the score
    features: Dict[str, object]  # raw numbers to aid debugging/thresholding


def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    # basic normalization: strip punctuation-like chars, collapse spaces, lowercase
    out = []
    for ch in s.lower():
        out.append(ch if ch.isalnum() or ch.isspace() else " ")
    return " ".join("".join(out).split())


def _payee_similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(a=_norm(a), b=_norm(b)).ratio()


def _date_delta_days(d1: Optional[date], d2: Optional[date]) -> Optional[int]:
    if d1 is None or d2 is None:
        return None
    return abs((d1 - d2).days)


def compare_txn(a: ITransaction, b: ITransaction) -> MatchScore:
    """
    Compare two ITransaction objects using the legacy auto_match heuristics:

    1) Amount equality is a hard gate (historically the candidate pre-filter).
    2) Among equal-amount candidates, prefer closer dates (lower day delta).
    3) Break ties with normalized payee similarity.

    Returns a MatchScore with a single scalar 'score' suitable for sorting
    (higher is better), plus 'reasons' and raw 'features' for explainability.
    """
    # --- Features ---
    amount_a: Decimal = a.amount
    amount_b: Decimal = b.amount
    amount_diff: Decimal = (amount_a - amount_b).copy_abs()

    date_days: Optional[int] = _date_delta_days(a.date, b.date)
    payee_sim: float = _payee_similarity(
        getattr(a, "payee", ""), getattr(b, "payee", "")
    )

    reasons: List[str] = []
    features: Dict[str, object] = {
        "amount_a": str(amount_a),
        "amount_b": str(amount_b),
        "amount_diff": str(amount_diff),
        "date_a": a.date.isoformat() if getattr(a, "date", None) else None,
        "date_b": b.date.isoformat() if getattr(b, "date", None) else None,
        "date_days": date_days,
        "payee_a": getattr(a, "payee", ""),
        "payee_b": getattr(b, "payee", ""),
        "payee_sim": round(payee_sim, 3),
    }

    # --- Amount gate (legacy behavior) ---
    if _AMOUNT_MUST_MATCH and amount_diff != 0:
        reasons.append(f"Amount differs by {amount_diff}")
        # Negative score to ensure these lose against any equal-amount candidate.
        return MatchScore(score=-1000, reasons=reasons, features=features)

    # --- Score construction for equal-amount candidates ---
    score: int = 0

    # Date proximity: identical date gets full base; each day away costs points.
    if date_days is not None:
        date_points = max(0, _W_DATE_BASE - _W_DATE_PER_DAY * date_days)
        score += date_points
        if date_days == 0:
            reasons.append("Same date (+{})".format(date_points))
        else:
            reasons.append(f"{date_days} day(s) apart (+{date_points})")
    else:
        # No dates → neutral on date; still explain.
        reasons.append("No date on one side (+0)")

    # Payee similarity: up to W_PAYEE_MAX additional points.
    payee_points = int(round(_W_PAYEE_MAX * payee_sim))
    score += payee_points
    reasons.append(f"Payee similarity {payee_sim:.2f} (+{payee_points})")

    # Soft cap to keep scores comparable
    score = min(score, _MAX_POSITIVE)

    return MatchScore(score=score, reasons=reasons, features=features)
