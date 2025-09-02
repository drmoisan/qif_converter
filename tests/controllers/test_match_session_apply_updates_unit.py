from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional

import pytest

# System under test (new, protocol-only API)
from quicken_helper.controllers.match_session import MatchSession


# ---------- Minimal protocol-shaped stub --------------------------------------

@dataclass(frozen=True)
class StubTxn:
    """Minimal ITransaction-shaped stub for protocol-only tests."""
    date: date
    amount: Decimal
    payee: str = ""
    memo: str = ""
    category: str = ""
    splits: Optional[List[dict]] = None


# ---------- Fixtures ----------------------------------------------------------

@pytest.fixture(autouse=True)
def _identity_convert_value(monkeypatch):
    """Isolation: stub convert_value to identity so tests don't depend on adapters."""
    import quicken_helper.controllers.match_session as ms
    monkeypatch.setattr(ms, "convert_value", lambda _t, v: v)


# ---------- Tests -------------------------------------------------------------

def test_matching_does_not_modify_bank_splits():
    """Positive: matching is read-only; existing bank splits remain unchanged after auto_match."""
    bank = [
        StubTxn(
            date=date(2025, 7, 2),
            amount=Decimal("-20.00"),
            splits=[
                {"category": "Old:Cat", "memo": "old1", "amount": Decimal("-10.00")},
                {"category": "Old:Cat", "memo": "old2", "amount": Decimal("-10.00")},
            ],
        )
    ]
    excel = [
        StubTxn(
            date=date(2025, 7, 2),
            amount=Decimal("-20.00"),
            splits=[
                {"category": "New:C2", "memo": "i2a", "amount": Decimal("-10.00")},
                {"category": "New:C3", "memo": "i2b", "amount": Decimal("-10.00")},
            ],
        )
    ]

    s = MatchSession(bank, excel)

    # Act
    pairs = s.auto_match()

    # Assert (paired, but bank object is unchanged)
    assert pairs == [(bank[0], excel[0])]
    assert bank[0].splits and len(bank[0].splits) == 2
    cats = [sp["category"] for sp in bank[0].splits]
    memos = [sp["memo"] for sp in bank[0].splits]
    amts = [sp["amount"] for sp in bank[0].splits]
    assert cats == ["Old:Cat", "Old:Cat"]
    assert memos == ["old1", "old2"]
    assert amts == [Decimal("-10.00"), Decimal("-10.00")]


def test_manual_match_and_accessors_consistency():
    """Positive: manual_match creates a single pair; accessors reflect unmatched sets deterministically."""
    bank = [StubTxn(date=date(2025, 8, 1), amount=Decimal("10.00")),
            StubTxn(date=date(2025, 8, 2), amount=Decimal("20.00"))]
    excel = [StubTxn(date=date(2025, 8, 1), amount=Decimal("10.00"))]

    s = MatchSession(bank, excel)

    # Act
    s.manual_match(bank_index=0, excel_index=0)

    # Assert
    assert s.pairs == [(bank[0], excel[0])]
    assert s.unmatched_bank == [bank[1]]
    assert s.unmatched_excel == []