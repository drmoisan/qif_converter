# qif_converter/tests/qif/test_qif_file_emit_transactions.py
from __future__ import annotations

import pytest
from qif_converter.qif import QuickenFile, QifAcct, IQuickenFile, IAccount, ITransaction


class _StubTxn(ITransaction):
    """Minimal txn stub that records how emit_qif() was called and returns a body."""
    def __init__(self, account: QifAcct, body: str):
        self.account = account
        self.body = body
        self.calls: list[tuple[bool, bool]] = []

    # Match the keyword-only call shape used by QifFile.emit_transactions
    def emit_qif(self, with_account: bool = False, with_type: bool = False) -> str:
        self.calls.append((with_account, with_type))
        parts = []
        if with_account:
            parts.append(f"[A:{self.account.name}]")
        if with_type:
            parts.append("[T:TYPE]")
        parts.append(self.body)
        return "\n".join(parts)


class _NoneTxn:
    """Stub that returns None from emit_qif to exercise the fallback-to-empty-string path."""
    def __init__(self, account: QifAcct):
        self.account = account
        self.calls: list[tuple[bool, bool]] = []

    def emit_qif(self, *, with_account: bool = False, with_type: bool = False):
        self.calls.append((with_account, with_type))
        return None


def test_emit_transactions_empty_returns_empty_string():
    # Arrange
    f = QuickenFile()
    f.transactions = []

    # Act
    out = f.emit_transactions()

    # Assert
    assert out == ""


def test_emit_transactions_first_in_account_emits_headers_then_suppresses_for_followups():
    # Arrange
    f = QuickenFile()
    acct = QifAcct(name="Checking", type="Bank", description="")
    t1 = _StubTxn(acct, "TXN1")
    t2 = _StubTxn(acct, "TXN2")
    f.transactions = [t1, t2]

    # Act
    out = f.emit_transactions()

    # Assert
    # First txn for an account -> with_account=True, with_type=True; subsequent -> both False
    assert t1.calls == [(True, True)]
    assert t2.calls == [(False, False)]
    # Joined with a single newline between txn texts
    assert out == "[A:Checking]\n[T:TYPE]\nTXN1\nTXN2"


def test_emit_transactions_reemits_headers_when_account_changes():
    # Arrange
    f = QuickenFile()
    checking = QifAcct(name="Checking", type="Bank", description="")
    savings = QifAcct(name="Savings", type="Bank", description="")
    t1 = _StubTxn(checking, "C1")
    t2 = _StubTxn(checking, "C2")
    t3 = _StubTxn(savings, "S1")  # account change here should trigger headers again
    f.transactions = [t1, t2, t3]

    # Act
    out = f.emit_transactions()

    # Assert
    assert t1.calls == [(True, True)]
    assert t2.calls == [(False, False)]
    assert t3.calls == [(True, True)]  # account changed → headers again
    assert out == "[A:Checking]\n[T:TYPE]\nC1\nC2\n[A:Savings]\n[T:TYPE]\nS1"


def test_emit_transactions_coerces_none_to_empty_string():
    # Arrange
    f = QuickenFile()
    acct = QifAcct(name="Checking", type="Bank", description="")
    t1 = _StubTxn(acct, "TXN1")
    t2 = _NoneTxn(acct)  # returns None → should contribute empty text
    f.transactions = [t1, t2]

    # Act
    out = f.emit_transactions()

    # Assert
    assert t1.calls == [(True, True)]
    assert t2.calls == [(False, False)]
    # The None becomes "", so the join yields a trailing newline after the first body
    assert out == "[A:Checking]\n[T:TYPE]\nTXN1\n"
