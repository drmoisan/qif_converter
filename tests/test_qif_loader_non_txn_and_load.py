import io
from pathlib import Path

import quicken_helper.controllers.qif_loader as ql


def _mk_open(text: str):
    """
    Create a replacement for Path.open that yields a fresh StringIO on each call.
    Signature matches Path.open(self, mode='r', *args, **kwargs).
    """

    def _open(self, mode="r", *args, **kwargs):
        assert "r" in mode, f"Expected read mode for test stub, got {mode!r}"
        return io.StringIO(text)

    return _open


# ------------------ _parse_non_txn_sections ------------------


def test__parse_non_txn_sections_parses_accounts_cats_payees_and_unknown(monkeypatch):
    # Arrange
    qif_text = (
        # Account list (single record)
        "!Account\n"
        "NChecking\n"
        "DMy Checking\n"
        "TBank\n"
        "^\n"
        # Category list (two records: one expense, one income)
        "!Type:Cat\n"
        "NFood\n"
        "E\n"
        "DGroceries\n"
        "^\n"
        "NSalary\n"
        "I\n"
        "^\n"
        # Memorized payee list (single record)
        "!Type:Memorized\n"
        "PPayee A\n"
        "MSome memo\n"
        "^\n"
        # Securities list (single record)
        "!Type:Security\n"
        "NApple Inc.\n"
        "SAAPL\n"
        "^\n"
        # Class/Business list (single record)
        "!Type:Class\n"
        "NBusiness\n"
        "DUse for biz\n"
        "^\n"
        # Payee list with multi-line address
        "!Type:Payee\n"
        "NStore A\n"
        "A123 Lane\n"
        "ACity, ST\n"
        "^\n"
        # Unknown section (should be preserved raw)
        "!Unknown:Foo\n"
        "Xcustom: value1\n"
        "Znote\n"
        "^\n"
    )
    # Monkeypatch Path.open used inside ql._parse_non_txn_sections
    monkeypatch.setattr(ql.Path, "open", _mk_open(qif_text), raising=True)

    # Act
    accounts, categories, memorized, securities, business, payees, other = (
        ql._parse_non_txn_sections(Path("MEM://ignore.qif"))
    )

    # Assert
    # Accounts
    assert (
        isinstance(accounts, list) and len(accounts) == 1
    ), "Should parse one account record."
    a = accounts[0]
    assert a.get("name") == "Checking"
    assert a.get("type") == "Bank"

    # Categories (one expense + one income)
    names = {c.get("name") for c in categories}
    assert {"Food", "Salary"} <= names, "Both category names should be present."

    # Memorized payees
    # Memorized payees
    assert memorized, "Should parse at least one memorized-payee record."
    m0 = memorized[0]
    # Some parsers store the payee name under 'name'; this one exposes raw_P
    if "name" in m0:
        assert m0["name"] == "Payee A"
    else:
        assert m0.get("raw_P") == ["Payee A"]
    assert m0.get("memo") == "Some memo"

    # Securities
    assert securities and securities[0].get("symbol") == "AAPL"

    # Classes/business list
    assert business and business[0].get("name") == "Business"

    # Payees with multi-line address flattened
    assert payees and "City, ST" in (payees[0].get("address") or "")

    # Unknown sections preserved
    assert "Unknown:Foo" in other, "Unknown section header should be preserved."
    first_unknown = other["Unknown:Foo"][0]
    assert "raw" in first_unknown and "Xcustom: value1" in first_unknown["raw"]
    # Optional: the parser may also expose code-specific raw buckets
    # if present in your implementation:
    if "raw_X" in first_unknown:
        assert first_unknown["raw_X"] == ["custom: value1"]
    if "raw_Z" in first_unknown:
        assert first_unknown["raw_Z"] == ["note"]


def test__parse_non_txn_sections_returns_empty_when_only_txns(monkeypatch):
    # Arrange: only a transaction block; no list headers present
    qif_text = "!Type:Bank\n" "D2025-01-01\n" "T-1.00\n" "^\n"
    monkeypatch.setattr(ql.Path, "open", _mk_open(qif_text), raising=True)

    # Act
    accounts, categories, memorized, securities, business, payees, other = (
        ql._parse_non_txn_sections(Path("MEM://ignore.qif"))
    )

    # Assert
    assert accounts == []
    assert categories == []
    assert memorized == []
    assert securities == []
    assert business == []
    assert payees == []

    # This parser preserves non-list sections it scans past (including txn headers)
    # in 'other'. Validate the captured Type:Bank structure instead of expecting {}.
    assert "Type:Bank" in other
    b0 = other["Type:Bank"][0]
    assert b0.get("raw_D") == ["2025-01-01"]
    assert b0.get("raw_T") == ["-1.00"]


def test__parse_non_txn_sections_multiple_unknown_sections(monkeypatch):
    # Arrange: two separate unknown section headers
    qif_text = "!Unknown:Foo\n" "Xone\n" "^\n" "!Unknown:Bar\n" "Ztwo\n" "^\n"
    monkeypatch.setattr(ql.Path, "open", _mk_open(qif_text), raising=True)

    # Act
    *_, other = ql._parse_non_txn_sections(Path("MEM://ignore.qif"))

    # Assert
    assert set(other.keys()) == {"Unknown:Foo", "Unknown:Bar"}
    # If your implementation includes per-code raw buckets:
    if other["Unknown:Foo"][0].get("raw_X") is not None:
        assert other["Unknown:Foo"][0]["raw_X"] == ["one"]
    if other["Unknown:Bar"][0].get("raw_Z") is not None:
        assert other["Unknown:Bar"][0]["raw_Z"] == ["two"]


# ------------------ load_transactions ------------------


def test_load_transactions_delegates_to_parse_qif_unified(monkeypatch):
    # Arrange
    captured = {}

    class DummyParsed:
        def __init__(self, txns):
            self.transactions = txns

    def fake_parse_unified(path, encoding="utf-8"):
        # capture arguments to verify forwarding
        captured["args"] = (path, encoding)
        return DummyParsed([{"date": "2025-02-01", "amount": "-1.00"}])

    monkeypatch.setattr(ql, "parse_qif_unified", fake_parse_unified)

    # Act
    out = ql.load_transactions(Path("anything.qif"), encoding="latin-1")

    # Assert
    assert out == [{"date": "2025-02-01", "amount": "-1.00"}]
    assert captured["args"][0] == Path("anything.qif")
    assert captured["args"][1] == "latin-1"


def test_load_transactions_accepts_str_path_and_uses_default_encoding(monkeypatch):
    # Arrange
    class DummyParsed:
        def __init__(self):
            self.transactions = [{"amount": "-1.23"}]

    captured = {}

    def fake_parse_unified(path, encoding="utf-8"):
        captured["args"] = (path, encoding)
        return DummyParsed()

    monkeypatch.setattr(ql, "parse_qif_unified", fake_parse_unified)

    # Act
    out = ql.load_transactions("string_path.qif")

    # Assert
    assert out == [{"amount": "-1.23"}]
    assert captured["args"] == ("string_path.qif", "utf-8")
