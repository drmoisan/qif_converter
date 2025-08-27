# tests/test_qif_loader_parse_qif.py
from __future__ import annotations

from contextlib import contextmanager
from io import StringIO

import pytest

import quicken_helper.controllers.qif_loader as ql


def _mk_open(qif_text: str):
    """Return a contextmanager function that mimics ql._open_for_read."""
    @contextmanager
    def _fake_open(path, binary: bool = False, encoding: str = "utf-8", errors: str = "replace"):
        # We only need text mode; parse_qif reads lines
        yield StringIO(qif_text)
    return _fake_open


def test_parse_qif_simple_bank_txn_fields_and_defaults(monkeypatch):
    # Arrange
    qif_text = (
        "!Type:Bank\n"
        "D2025-01-02\n"
        "T-12.34\n"
        "PCoffee Shop\n"
        "MLatte\n"
        "Mand tip\n"
        "LFood:Coffee\n"
        "N101\n"
        "CX\n"
        "A123 Main St\n"
        "ACity, ST\n"
        "^\n"
    )
    monkeypatch.setattr(ql, "_open_for_read", _mk_open(qif_text))

    # Act
    txns = ql.parse_qif(path=None)  # path ignored by our monkeypatch

    # Assert
    assert len(txns) == 1, "Exactly one transaction should be parsed."
    t = txns[0]
    assert t["type"] == "Bank"
    assert t["date"] == "2025-01-02"
    assert t["amount"] == "-12.34"
    assert t["payee"] == "Coffee Shop"
    # Memo lines are joined with newlines by the parser
    assert t["memo"] == "Latte\nand tip"
    assert t["category"] == "Food:Coffee"
    assert t["checknum"] == "101"
    assert t["cleared"] == "X"
    assert t["address"] == "123 Main St\nCity, ST"
    # Defaults the parser guarantees
    assert t["quantity"] == ""
    assert t["price"] == ""
    assert t["commission"] == ""
    assert t["splits"] == []


def test_parse_qif_account_block_sets_account_for_later_txns(monkeypatch):
    # Arrange
    qif_text = (
        "!Account\n"
        "NChecking\n"
        "^\n"
        "!Type:Bank\n"
        "T-1.00\n"
        "^\n"
    )
    monkeypatch.setattr(ql, "_open_for_read", _mk_open(qif_text))

    # Act
    txns = ql.parse_qif(path=None)

    # Assert
    assert len(txns) == 1
    t = txns[0]
    assert t["account"] == "Checking", "Account list block should set current account for subsequent txns."
    assert t["type"] == "Bank"
    assert t["amount"] == "-1.00"


def test_parse_qif_investment_action_vs_checknum(monkeypatch):
    # Arrange
    qif_text = (
        "!Type:Invst\n"
        "NBuy\n"             # In investment sections, 'N' is an action, not a checknum
        "YACME\n"
        "Q10\n"
        "I12.34\n"
        "O1.00\n"
        "T-124.40\n"
        "^\n"
    )
    monkeypatch.setattr(ql, "_open_for_read", _mk_open(qif_text))

    # Act
    txns = ql.parse_qif(path=None)

    # Assert
    assert len(txns) == 1
    t = txns[0]
    assert t["type"].lower().startswith("invst")
    assert t.get("action") == "Buy", "Investment 'N' should map to 'action'."
    assert "checknum" not in t or t["checknum"] == "", "No checknum expected for investment records when 'N' is action."
    assert t["security"] == "ACME"
    assert t["quantity"] == "10"
    assert t["price"] == "12.34"
    assert t["commission"] == "1.00"
    assert t["amount"] == "-124.40"


def test_parse_qif_handles_splits_and_memo(monkeypatch):
    # Arrange
    qif_text = (
        "!Type:Bank\n"
        "D2025-01-15\n"
        "T-20.00\n"
        "PStore A\n"
        # First split
        "SFood\n"
        "EVeg\n"
        "$-12.00\n"
        # Second split
        "SFood\n"
        "EFruit\n"
        "$-8.00\n"
        # Two memo lines at txn-level
        "MLine1\n"
        "MLine2\n"
        "^\n"
    )
    monkeypatch.setattr(ql, "_open_for_read", _mk_open(qif_text))

    # Act
    txns = ql.parse_qif(path=None)

    # Assert
    assert len(txns) == 1
    t = txns[0]
    assert t["amount"] == "-20.00"
    assert t["memo"] == "Line1\nLine2", "Multiple 'M' lines should join with newline."
    assert len(t["splits"]) == 2
    assert t["splits"][0] == {"category": "Food", "memo": "Veg", "amount": "-12.00"}
    assert t["splits"][1] == {"category": "Food", "memo": "Fruit", "amount": "-8.00"}


def test_parse_qif_transfer_account_extracted_from_category(monkeypatch):
    # Arrange
    qif_text = (
        "!Type:Bank\n"
        "T-50.00\n"
        "L[Transfer:Emergency Fund]\n"
        "^\n"
    )
    monkeypatch.setattr(ql, "_open_for_read", _mk_open(qif_text))

    # Act
    txns = ql.parse_qif(path=None)

    # Assert
    assert len(txns) == 1
    t = txns[0]
    assert t["category"] == "[Transfer:Emergency Fund]"
    assert t["transfer_account"] == "Emergency Fund", "Transfer account should be parsed from bracketed category."


def test_parse_qif_address_escaped_newlines(monkeypatch):
    # Arrange
    qif_text = (
        "!Type:Bank\n"
        "T-5.00\n"
        "Afirst\\nsecond\n"   # Escaped newline in a single 'A' field
        "^\n"
    )
    monkeypatch.setattr(ql, "_open_for_read", _mk_open(qif_text))

    # Act
    txns = ql.parse_qif(path=None)

    # Assert
    assert len(txns) == 1
    t = txns[0]
    assert t["address"] == "first\nsecond", "Escaped \\n inside 'A' should become a real newline."


def test_parse_qif_finalize_on_eof_without_caret(monkeypatch):
    # Arrange
    # Intentionally omit the final '^' to ensure finalize at EOF works
    qif_text = (
        "!Type:Bank\n"
        "T-1.23\n"
        "PCafe\n"
    )
    monkeypatch.setattr(ql, "_open_for_read", _mk_open(qif_text))

    # Act
    txns = ql.parse_qif(path=None)

    # Assert
    assert len(txns) == 1, "Parser should finalize the last record at EOF even without '^'."
    t = txns[0]
    assert t["payee"] == "Cafe"
    assert t["amount"] == "-1.23"


def test_parse_qif_whitespace_and_unknown_lines_do_not_break(monkeypatch):
    # Arrange
    qif_text = (
        "   !Type:Bank\n"   # leading spaces before the section header
        "\n"
        "ZUnknown Custom Line\n"  # unknown code 'Z' should be ignored for txns
        "T-2.00\n"
        "  PPayee With Space Prefix\n"
        "^\n"
    )
    monkeypatch.setattr(ql, "_open_for_read", _mk_open(qif_text))

    # Act
    txns = ql.parse_qif(path=None)

    # Assert
    assert len(txns) == 1
    t = txns[0]
    assert t["type"] == "Bank"
    assert t["amount"] == "-2.00"
    assert t["payee"] == "Payee With Space Prefix", "Leading whitespace should be stripped from field values."

@pytest.mark.parametrize(
    "cat_line, expected_acct",
    [
        ("L[transfer:Emergency Fund]\n", "Emergency Fund"),     # lowercase + colon
        ("L[Transfer Emergency Fund]\n", "Emergency Fund"),     # no colon
        ("L[ Emergency Fund ]\n", "Emergency Fund"),            # extra spaces
        ("L[Transfer:  Emergency Fund]\n", "Emergency Fund"),   # extra spaces after colon
    ],
)
def test_parse_qif_transfer_variants(monkeypatch, cat_line, expected_acct):
    # Arrange
    qif_text = (
        "!Type:Bank\n"
        "T-50.00\n"
        f"{cat_line}"
        "^\n"
    )
    monkeypatch.setattr(ql, "_open_for_read", _mk_open(qif_text))

    # Act
    txns = ql.parse_qif(path=None)

    # Assert
    assert len(txns) == 1
    t = txns[0]
    # Category stays exactly as read (brackets preserved)
    assert t["category"].startswith("[") and t["category"].endswith("]"), "Literal bracketed category should be preserved."
    # Transfer account is normalized per regex variants
    assert t.get("transfer_account") == expected_acct, f"Expected transfer account '{expected_acct}' parsed from {cat_line.strip()!r}."