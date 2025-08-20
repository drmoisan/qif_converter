# tests/test_qif_loader_new.py
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import List, Dict, Any

import pytest


def _write_qif(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_parse_qif_unified_combines_txns_and_unknown_sections(tmp_path: Path, monkeypatch):
    """
    Arrange: a QIF file with a bank txn plus an unknown section header.
    Act: parse_qif_unified
    Assert: transactions come from base.parse_qif (stubbed), and the unknown
            section is preserved in ParsedQIF. Other lists are present (empty).
    """
    # --- Arrange ---
    qif_text = (
        # One simple bank transaction section
        "!Type:Bank\n"
        "D01/02'25\n"
        "T-12.34\n"
        "PPayee A\n"
        "^\n"
        # An unknown non-transaction section we expect to be preserved
        "!Unknown:Foo\n"
        "Xcustom: value1\n"
        "Znote\n"
        "^\n"
    )
    qif_path = tmp_path / "in.qif"
    _write_qif(qif_path, qif_text)

    # Stub base.parse_qif to isolate file/IO logic from the transaction parser.
    # We only verify that qif_loader delegates and returns what base returns for txns.
    stub_txns: List[Dict[str, Any]] = [
        {"date": "2025-01-02", "amount": "-12.34", "payee": "Payee A"}
    ]

    import qif_converter.qif_loader as ql
    monkeypatch.setattr(ql.base, "parse_qif", lambda p, encoding="utf-8": stub_txns)

    # --- Act ---
    parsed = ql.parse_qif_unified(qif_path)

    # --- Assert ---
    # Transactions are exactly what the stub returned (delegation verified).
    assert parsed.transactions == stub_txns, "Transactions should come from base.parse_qif stub."

    # Non-txn lists exist and default to empty
    assert parsed.accounts == []
    assert parsed.categories == []
    assert parsed.memorized_payees == []
    assert parsed.securities == []
    assert parsed.business_list == []
    assert parsed.payees == []

    # Unknown section preserved
    assert "Unknown:Foo" in parsed.other_sections, "Unknown section header should be preserved."
    # We don't assert exact field mapping—just that at least one item was parsed
    assert len(parsed.other_sections["Unknown:Foo"]) >= 1

def test_load_transactions_uses_parse_qif_unified(tmp_path: Path, monkeypatch):
    """
    Arrange: monkeypatch parse_qif_unified to return a ParsedQIF with known txns.
    Act: load_transactions(path)
    Assert: returns exactly ParsedQIF.transactions
    """
    qif_path = tmp_path / "in.qif"
    _write_qif(qif_path, "!Type:Bank\n^\n")

    # Build a fake ParsedQIF to return from parse_qif_unified
    stub_txns = [{"date": "2025-02-01", "amount": "-1.00"}]

    import qif_converter.qif_loader as ql
    from qif_converter.qif_parsed import ParsedQIF

    def fake_parse(p, encoding="utf-8"):
        return ParsedQIF(
            transactions=list(stub_txns),
            accounts = [],
            categories = [],
            memorized_payees = [],
            securities = [],
            business_list = [],
            payees = [],
            other_sections = {},
            )

    monkeypatch.setattr(ql, "parse_qif_unified", fake_parse)

    # --- Act ---
    txns = ql.load_transactions(qif_path)

    # --- Assert ---
    assert txns == stub_txns, "load_transactions should return ParsedQIF.transactions from parse_qif_unified."

def test_parse_qif_unified_no_other_sections(tmp_path: Path, monkeypatch):
    """
    Arrange: QIF containing only a transaction block, no lists.
    Act: parse_qif_unified
    Assert: All non-txn lists are empty; unknown_sections empty too.
    """
    qif_text = (
        "!Type:Bank\n"
        "D02/03'25\n"
        "T100.00\n"
        "PDeposit\n"
        "^\n"
    )
    qif_path = tmp_path / "only_txn.qif"
    _write_qif(qif_path, qif_text)

    stub_txns = [{"date": "2025-02-03", "amount": "100.00", "payee": "Deposit"}]
    import qif_converter.qif_loader as ql
    monkeypatch.setattr(ql.base, "parse_qif", lambda p, encoding="utf-8": stub_txns)

    parsed = ql.parse_qif_unified(qif_path)

    assert parsed.transactions == stub_txns
    assert parsed.accounts == []
    assert parsed.categories == []
    assert parsed.memorized_payees == []
    assert parsed.securities == []
    assert parsed.business_list == []
    assert parsed.payees == []
    assert parsed.other_sections == {}

def test_parse_qif_unified_handles_multiple_known_headers_minimally(tmp_path: Path, monkeypatch):
    """
    Arrange: A QIF with several known non-transaction headers (in minimal form).
    Act: parse_qif_unified
    Assert: The corresponding ParsedQIF lists are populated (non-empty).
    Note: We keep assertions light to avoid coupling to field-level parsing details.
    """
    qif_text = (
        # Txn
        "!Type:Bank\n"
        "D03/04'25\nT-5.50\nPShop\n^\n"
        # Some likely-known list headers in minimal representation
        "!Account\nNChecking\n^\n"
        "!Type:Cat\nNFood\nE\n^\n"
        "!Type:Memorized\nNStarbucks\n^\n"
        "!Type:Security\nNStockA\n^\n"
        "!Type:Class\nNClass1\n^\n"
        "!Type:Payee\nNPayee A\n^\n"
    )
    qif_path = tmp_path / "lists.qif"
    _write_qif(qif_path, qif_text)

    import qif_converter.qif_loader as ql
    # stub txn parse
    monkeypatch.setattr(ql.base, "parse_qif", lambda p, encoding="utf-8": [{"date": "2025-03-04", "amount": "-5.50"}])

    parsed = ql.parse_qif_unified(qif_path)

    assert len(parsed.transactions) == 1
    # Just verify that each list is recognized as non-empty; we don't assert exact dict shapes
    assert len(parsed.accounts) >= 1
    assert len(parsed.categories) >= 1
    assert len(parsed.memorized) >= 1
    assert len(parsed.securities) >= 1
    assert len(parsed.classes) >= 1
    assert len(parsed.payees) >= 1
