# tests/controllers/test_qif_loader_protocol.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

import pytest

# System under test
import quicken_helper.controllers.qif_loader as ql

# Shared enums (use the same enum as the model uses)
from quicken_helper.data_model.interfaces import EnumClearedStatus

# ---- Minimal in-file stubs to isolate the loader contract --------------------


@dataclass
class _StubTxn:
    """Lightweight transaction stub matching the attributes the loader should pass through."""

    date: date
    amount: Decimal
    payee: str = ""
    memo: str = ""
    category: str = ""
    # Use a default_factory for Enum to avoid dataclass "mutable default" complaints
    cleared: EnumClearedStatus = field(
        default_factory=lambda: EnumClearedStatus.UNKNOWN
    )
    splits: Optional[List] = None
    action: Optional[str] = None


@dataclass
class _StubFile:
    """Lightweight file stub exposing the single attribute the loader consumes."""

    transactions: List[_StubTxn] = field(default_factory=list)


# ---- Tests -------------------------------------------------------------------


def test_loader_calls_parse_and_returns_transactions(monkeypatch):
    """Positive: loader wires to parse function and returns the file's transactions list."""

    # Arrange
    called = {}

    def fake_parse_qif_unified(path: Path, encoding: str = "utf-8"):
        called["args"] = (path, encoding)
        return _StubFile(
            transactions=[
                _StubTxn(
                    date=date(2025, 7, 4),
                    amount=Decimal("123.45"),
                    payee="Acme Co",
                    memo="Payment",
                    category="Utilities:Internet",
                    cleared=EnumClearedStatus.UNKNOWN,
                )
            ]
        )

    monkeypatch.setattr(ql, "parse_qif_unified_protocol", fake_parse_qif_unified)

    # Act
    out = ql.load_transactions_protocol(Path("X.qif"), encoding="latin-1")

    # Assert
    assert isinstance(out, list), "Loader must return a list of transactions"
    assert len(out) == 1, "Transactions from the parsed file should be returned as-is"
    assert called["args"] == (
        Path("X.qif"),
        "latin-1",
    ), "Path and encoding must be forwarded verbatim"
    t = out[0]
    assert isinstance(t, _StubTxn), "Loader should not adapt or wrap transactions"
    assert (t.date, t.amount, t.payee, t.memo, t.category, t.cleared) == (
        date(2025, 7, 4),
        Decimal("123.45"),
        "Acme Co",
        "Payment",
        "Utilities:Internet",
        EnumClearedStatus.UNKNOWN,
    )


def test_loader_propagates_parse_errors(monkeypatch):
    """Negative: loader must not swallow exceptions raised by the parser."""

    # Arrange
    def boom(*_a, **_kw):
        raise ValueError("bad qif")

    monkeypatch.setattr(ql, "parse_qif_unified_protocol", boom)

    # Act / Assert
    with pytest.raises(ValueError) as ei:
        ql.load_transactions_protocol(Path("bad.qif"))
    assert "bad qif" in str(ei.value)


def test_loader_does_not_mutate_transactions_identity(monkeypatch):
    """Positive: loader must pass through the original transaction objects without copying."""

    # Arrange
    tx = _StubTxn(date=date(2025, 1, 1), amount=Decimal("2.00"))

    def fake(*_a, **_kw):
        return _StubFile([tx])

    monkeypatch.setattr(ql, "parse_qif_unified_protocol", fake)

    # Act
    out = ql.load_transactions_protocol(Path("x.qif"))

    # Assert
    assert (
        out and out[0] is tx
    ), "Returned object should be the same instance produced by the parser"


def test_loader_returns_empty_list_when_no_transactions(monkeypatch):
    """Edge: gracefully handle empty files by returning an empty list."""

    # Arrange
    monkeypatch.setattr(
        ql, "parse_qif_unified_protocol", lambda *_a, **_kw: _StubFile([])
    )

    # Act
    out = ql.load_transactions_protocol(Path("empty.qif"))

    # Assert
    assert isinstance(out, list)
    assert out == []


def test_investment_action_passthrough(monkeypatch):
    """Positive: ensure loader preserves investment action fields unchanged."""

    # Arrange
    stub = _StubTxn(
        date=date(2025, 3, 15),
        amount=Decimal("1000"),
        action="Buy",  # Investment action should survive intact
    )
    monkeypatch.setattr(
        ql, "parse_qif_unified_protocol", lambda *_a, **_kw: _StubFile([stub])
    )

    # Act
    out = ql.load_transactions_protocol(Path("inv.qif"))

    # Assert
    assert out[0].action == "Buy"


def test_splits_passthrough(monkeypatch):
    """Positive: ensure loader preserves splits list without modification."""

    # Arrange
    splits = [{"category": "Food:Groceries", "amount": Decimal("50.00")}]
    stub = _StubTxn(date=date(2025, 2, 2), amount=Decimal("50.00"), splits=splits)
    monkeypatch.setattr(
        ql, "parse_qif_unified_protocol", lambda *_a, **_kw: _StubFile([stub])
    )

    # Act
    out = ql.load_transactions_protocol(Path("splits.qif"))

    # Assert
    assert out[0].splits == splits
    assert (
        out[0].splits is splits
    ), "Identity check: loader must not copy or transform splits"
