# tests/test_qif_loader.py
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
import builtins
import io
import pytest

from qif_converter import qif_loader as loader


def _write_qif(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_parse_qif_unified_parses_lists_and_calls_base(monkeypatch, tmp_path: Path):
    # Arrange: a QIF file that contains several non-transaction lists + unknown section.
    qif_text = """!Account
NChecking
DPrimary checking
^
!Type:Cat
NFood
E
^
!type:category
NSalary
I
^
!Type:Memorized Payee
NStarbucks
A123 Bean St
ASeattle
LFood:Coffee
Musual
^
!TYPE:SECURITY
NAcme Corp
SACME
DTest sec
^
!Type:Class
NOperations
DOverhead
^
!Type:Payee
NJohn Doe
A1 Main St
AAnytown
MGeneric memo
^
!Type:Weird
NZzz
X42
^
"""
    qif_file = tmp_path / "lists_and_unknown.qif"
    _write_qif(qif_file, qif_text)

    # Base parser should be used for transactions; stub it to verify it’s called and to control txns.
    called = {"parse_qif": 0}
    fake_txns = [{"date": "2024-02-01", "amount": "12.34", "payee": "Test"}]

    def fake_parse_qif(path: Path, encoding: str = "utf-8"):
        called["parse_qif"] += 1
        # Ensure it's reading the same file we wrote
        assert Path(path) == qif_file
        return list(fake_txns)

    monkeypatch.setattr(loader.base, "parse_qif", fake_parse_qif)

    # Act
    parsed = loader.parse_qif_unified(qif_file)

    # Assert: transactions come from base parser
    assert called["parse_qif"] == 1
    assert parsed.transactions == fake_txns

    # Accounts
    assert len(parsed.accounts) == 1
    acc = parsed.accounts[0]
    assert acc["name"] == "Checking"
    assert acc["description"] == "Primary checking"
    assert "raw" in acc and isinstance(acc["raw"], list)

    # Categories: flags set to True when present
    # We provided two entries, one with E (expense), one with I (income)
    cat_names = {c["name"] for c in parsed.categories}
    assert cat_names == {"Food", "Salary"}
    food = next(c for c in parsed.categories if c["name"] == "Food")
    salary = next(c for c in parsed.categories if c["name"] == "Salary")
    assert food.get("expense") is True
    assert salary.get("income") is True

    # Memorized: address lines joined, L (category) and M (memo) preserved
    assert len(parsed.memorized_payees) == 1
    mem = parsed.memorized_payees[0]
    assert mem["name"] == "Starbucks"
    assert mem["address"] == "123 Bean St\nSeattle"
    assert mem["category"] == "Food:Coffee"
    assert mem["memo"] == "usual"

    # Securities
    assert len(parsed.securities) == 1
    sec = parsed.securities[0]
    assert sec["name"] == "Acme Corp"
    assert sec["symbol"] == "ACME"
    assert sec["description"] == "Test sec"

    # Business/Class
    assert len(parsed.business_list) == 1
    biz = parsed.business_list[0]
    assert biz["name"] == "Operations"
    assert biz["description"] == "Overhead"

    # Payees
    assert len(parsed.payees) == 1
    payee = parsed.payees[0]
    assert payee["name"] == "John Doe"
    assert payee["address"] == "1 Main St\nAnytown"
    assert payee["memo"] == "Generic memo"

    # Unknown section captured intact in other_sections
    assert "Type:Weird" in parsed.other_sections
    unk = parsed.other_sections["Type:Weird"][0]
    assert unk["raw"][0].startswith("NZzz")
    # Raw X42 stored under raw_X, value ["42"]
    assert unk.get("raw_X") == ["42"]


def test_load_transactions_uses_unified(monkeypatch, tmp_path: Path):
    # Arrange
    qif_file = tmp_path / "only_txns.qif"
    _write_qif(qif_file, "!Type:Bank\n^\n")

    fake = loader.ParsedQIF(
        transactions=[{"date": "2020-01-02", "amount": "10.00"}],
        accounts=[],
        categories=[],
        memorized_payees=[],
        securities=[],
        business_list=[],
        payees=[],
        other_sections={},
    )
    called = {"unified": 0}

    def fake_unified(path, encoding="utf-8"):
        called["unified"] += 1
        assert Path(path) == qif_file
        return fake

    monkeypatch.setattr(loader, "parse_qif_unified", fake_unified)

    # Act
    txns = loader.load_transactions(qif_file)

    # Assert
    assert called["unified"] == 1
    assert txns == fake.transactions


def test_category_flags_and_scalar_fields(tmp_path: Path, monkeypatch):
    # Arrange: Just categories with flags and extra scalar fields
    qif_text = """!Type:Cat
NUtilities
E
TForm 1040/Sched 1
^
!Type:Category
NInterest Income
I
BAnnual
^
"""
    qif_file = tmp_path / "cats.qif"
    _write_qif(qif_file, qif_text)

    # Don’t involve base transaction parsing for this test
    monkeypatch.setattr(loader.base, "parse_qif", lambda *a, **k: [])

    # Act
    parsed = loader.parse_qif_unified(qif_file)

    # Assert: both categories present
    names = [c["name"] for c in parsed.categories]
    assert names == ["Utilities", "Interest Income"]

    util = next(c for c in parsed.categories if c["name"] == "Utilities")
    intr = next(c for c in parsed.categories if c["name"] == "Interest Income")

    # Flags present as booleans
    assert util.get("expense") is True
    assert intr.get("income") is True

    # Scalar fields carried through when present
    assert util.get("tax_line") == "Form 1040/Sched 1"
    assert intr.get("budget") == "Annual"


def test_unknown_sections_are_preserved(tmp_path: Path, monkeypatch):
    qif_text = """!Type:SomethingNew
NZap
QNote
^
"""
    qif_file = tmp_path / "unknown.qif"
    _write_qif(qif_file, qif_text)
    monkeypatch.setattr(loader.base, "parse_qif", lambda *a, **k: [])

    parsed = loader.parse_qif_unified(qif_file)
    assert "Type:SomethingNew" in parsed.other_sections
    item = parsed.other_sections["Type:SomethingNew"][0]
    # known-like codes not mapped should be captured in raw_* buckets
    assert item.get("raw")[0].startswith("NZap")
    assert item.get("raw_Q") == ["Note"]
