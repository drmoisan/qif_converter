# tests/test_qif_loader_parse_qif_unified.py
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from io import StringIO
from typing import Any, Dict, List, Tuple

import quicken_helper.controllers.qif_loader as ql
from quicken_helper.legacy.qif_parsed import ParsedQIF


def _stub_non_txn_sections() -> Tuple[
    List[Dict[str, Any]],  # accounts
    List[Dict[str, Any]],  # categories
    List[Dict[str, Any]],  # memorized
    List[Dict[str, Any]],  # securities
    List[Dict[str, Any]],  # business/class
    List[Dict[str, Any]],  # payees
    Dict[str, List[Dict[str, Any]]],  # other/unknown
]:
    return (
        [{"name": "Checking", "type": "Bank"}],  # accounts
        [{"name": "Food", "expense": True}],  # categories
        [{"name": "Starbucks", "memo": "latte"}],  # memorized
        [{"name": "Vanguard 500", "symbol": "VFIAX"}],  # securities
        [{"name": "Consulting"}],  # class/business
        [{"name": "Coffee Shop"}],  # payees
        {"Foo": [{"raw": ["Xcustom: 1"], "raw_X": ["custom: 1"]}]},  # other
    )

def _mk_open(qif_text: str):
    # Return a callable that returns a context manager when invoked
    def fake_open(*, path, binary=False, **kwargs):
        assert not binary, "This test stub only handles text mode"
        return nullcontext(StringIO(qif_text))
    return fake_open

def test_parse_qif_unified_delegates_and_combines(monkeypatch):
    # Arrange
    txns = [{"date": "2025-01-01", "amount": "-12.34", "payee": "Coffee"}]

    def fake_parse_qif(lines: List[str]):
        # Return the exact list (not a copy) so we can assert identity if desired
        return txns

    def fake_parse_other(path, encoding="utf-8"):
        return _stub_non_txn_sections()

    monkeypatch.setattr(ql, "_open_for_read", _mk_open("dummy text"), raising=True)
    monkeypatch.setattr(ql, "parse_qif", fake_parse_qif)
    monkeypatch.setattr(ql, "_parse_non_txn_sections", fake_parse_other)

    # Act
    parsed = ql.parse_qif_unified(path=None)  # path unused by stubs

    # Assert
    assert isinstance(parsed, ParsedQIF)
    assert (
        parsed.transactions is txns
    ), "Transactions should be exactly those returned by parse_qif."
    accounts, categories, memorized, securities, business_list, payees, other = (
        _stub_non_txn_sections()
    )
    assert parsed.accounts == accounts
    assert parsed.categories == categories
    assert parsed.memorized_payees == memorized
    assert parsed.securities == securities
    assert parsed.business_list == business_list
    assert parsed.payees == payees
    assert parsed.other_sections == other


def test_parse_qif_unified_empty_non_txn_lists(monkeypatch):
    # Arrange
    txns = [{"date": "2025-02-02", "amount": "100.00", "payee": "Deposit"}]

    def fake_parse_qif(lines: List[str]):
        # Return the exact list (not a copy) so we can assert identity if desired
        return txns

    def fake_parse_other(path, encoding="utf-8"):
        return _stub_non_txn_sections()

    monkeypatch.setattr(ql, "_open_for_read", _mk_open("dummy text"), raising=True)
    monkeypatch.setattr(ql, "parse_qif", fake_parse_qif)
    monkeypatch.setattr(
        ql,
        "_parse_non_txn_sections",
        lambda p, encoding="utf-8": ([], [], [], [], [], [], {}),
    )

    # Act
    parsed = ql.parse_qif_unified(path=None)

    # Assert
    assert parsed.transactions == txns
    assert parsed.accounts == []
    assert parsed.categories == []
    assert parsed.memorized_payees == []
    assert parsed.securities == []
    assert parsed.business_list == []
    assert parsed.payees == []
    assert parsed.other_sections == {}


def test_parse_qif_unified_propagates_encoding(monkeypatch):
    # Arrange
    seen = {"pq": None, "po": None}

    def fake_parse_qif(lines: list[str]):
        seen["pq"] = enc
        return [{"date": "2025-03-03", "amount": "1.23"}]

    def fake_parse_other(path, encoding="utf-8"):
        seen["po"] = encoding
        return ([], [], [], [], [], [], {})

    monkeypatch.setattr(ql, "_open_for_read", _mk_open("dummy text"), raising=True)
    monkeypatch.setattr(ql, "parse_qif", fake_parse_qif)
    monkeypatch.setattr(ql, "_parse_non_txn_sections", fake_parse_other)

    # Act
    enc = "latin-1"
    parsed = ql.parse_qif_unified(path=None, encoding=enc)

    # Assert
    assert parsed.transactions == [{"date": "2025-03-03", "amount": "1.23"}]
    assert seen["pq"] == enc, "parse_qif should receive the same encoding"
    assert seen["po"] == enc, "_parse_non_txn_sections should receive the same encoding"


def test_parse_qif_unified_unknown_sections_preserved(monkeypatch):
    # Arrange
    def fake_parse_qif(lines: list[str]):
        return []
    monkeypatch.setattr(ql, "_open_for_read", _mk_open("dummy text"), raising=True)
    monkeypatch.setattr(ql, "parse_qif", fake_parse_qif)
    other = {"WeirdBlock": [{"raw": ["Zsome"], "raw_Z": ["some"]}]}
    monkeypatch.setattr(
        ql,
        "_parse_non_txn_sections",
        lambda p, encoding="utf-8": ([], [], [], [], [], [], other),
    )

    # Act
    parsed = ql.parse_qif_unified(path=None)

    # Assert
    assert parsed.other_sections == other
    assert "WeirdBlock" in parsed.other_sections
    assert isinstance(parsed.other_sections["WeirdBlock"], list)


def test_load_transactions_uses_unified(monkeypatch):
    # Arrange
    desired = [{"date": "2025-04-04", "amount": "-9.99"}]

    # Return a ParsedQIF where transactions == desired
    monkeypatch.setattr(
        ql,
        "parse_qif_unified",
        lambda p, encoding="utf-8": ParsedQIF(
            transactions=desired,
            accounts=[],
            categories=[],
            memorized_payees=[],
            securities=[],
            business_list=[],
            payees=[],
            other_sections={},
        ),
    )

    # Act
    txns = ql.load_transactions(path=None)

    # Assert
    assert (
        txns == desired
    ), "load_transactions should return .transactions from parse_qif_unified"
