from __future__ import annotations

import sys
from datetime import datetime
from types import ModuleType

import quicken_helper.legacy.qfx_to_txns as qfx

# ------------------------------- _to_date -------------------------------------

def test__to_date_parses_plain_time_and_tz():
    """_to_date: parses OFX/QFX date formats like YYYYMMDD, YYYYMMDDThhmmss,
    and strips timezone brackets, returning 'mm/dd/YYYY' or '' if invalid."""
    assert qfx._to_date("20250115") == "01/15/2025"
    assert qfx._to_date("20250115T120000") == "01/15/2025"
    assert qfx._to_date("20250115[0:GMT]") == "01/15/2025"


def test__to_date_returns_empty_on_invalid():
    """_to_date: invalid/partial inputs return empty string (defensive)."""
    assert qfx._to_date("") == ""
    assert qfx._to_date("2025") == ""             # too short
    assert qfx._to_date("20251340") == ""         # impossible month/day


# --------------------------------- _tx ----------------------------------------

def test__tx_formats_amount_and_schema_defaults():
    """_tx: returns a dict in the expected schema with 2-decimal amount,
    empty strings for optional text fields, and an empty splits list."""
    t = qfx._tx(-12.3, payee=" ACME ", memo=" Memo ", date="01/02/2025", checknum=" 99 ")
    assert t == {
        "date": "01/02/2025",
        "payee": " ACME ",            # _tx does not strip; caller is responsible
        "amount": "-12.30",
        "category": "",
        "memo": " Memo ",
        "account": "",
        "checknum": " 99 ",
        "splits": [],
    }


# ------------------------------- parse_qfx ------------------------------------

def test_parse_qfx_uses_ofxparse_when_available(monkeypatch, tmp_path):
    """parse_qfx: when 'ofxparse' is importable, it uses OfxParser.parse(...)
    and maps transactions -> dicts via _tx. We install a fake ofxparse module
    that returns a minimal object graph with accounts/statement/transactions."""
    # Prepare a fake 'ofxparse' module
    class FakeTxn:
        def __init__(self, amount, payee, memo, date, checknum=""):
            self.amount = amount
            self.payee = payee
            self.memo = memo
            self.date = date
            self.checknum = checknum

    class FakeStatement:
        def __init__(self, transactions):
            self.transactions = transactions

    class FakeAccount:
        def __init__(self, txns):
            self.statement = FakeStatement(txns)

    class FakeOfx:
        def __init__(self, accounts):
            self.accounts = accounts

    class FakeParser:
        @staticmethod
        def parse(f):  # file-like; content not needed
            txns = [
                FakeTxn(amount=12.34, payee="Alpha", memo="A", date=datetime(2025, 1, 15), checknum="101"),
                FakeTxn(amount=-56.78, payee="", memo="Beta Memo", date=datetime(2025, 1, 16)),
            ]
            return FakeOfx([FakeAccount(txns)])

    fake_mod = ModuleType("ofxparse")
    fake_mod.OfxParser = FakeParser
    monkeypatch.setitem(sys.modules, "ofxparse", fake_mod)

    # Write any file contents (parser ignores)
    p = tmp_path / "sample.qfx"
    p.write_text("dummy", encoding="utf-8")

    out = qfx.parse_qfx(p)
    assert len(out) == 2
    # Txn 0
    assert out[0]["amount"] == "12.34"
    assert out[0]["payee"] == "Alpha"       # payee preferred over memo
    assert out[0]["memo"] == "A"
    assert out[0]["date"] == "01/15/2025"   # from datetime -> YYYYMMDD -> _to_date
    assert out[0]["checknum"] == "101"
    assert out[0]["splits"] == []
    # Txn 1
    assert out[1]["amount"] == "-56.78"
    assert out[1]["payee"] == "Beta Memo"   # payee fallback to memo when payee is empty
    assert out[1]["memo"] == "Beta Memo"
    assert out[1]["date"] == "01/16/2025"
    assert out[1]["checknum"] == ""


def test_parse_qfx_fallback_scans_stmttrn_blocks(monkeypatch, tmp_path):
    """parse_qfx (fallback): when ofxparse fails, scans <STMTTRN>...</STMTTRN>
    blocks and extracts TRNAMT/NAME/MEMO/DTPOSTED/CHECKNUM into _tx schema.
    Values like '1,234.56' are normalized, and dates are converted via _to_date."""
    # Force the function into the fallback path by providing an ofxparse with a failing parse
    class FailingParser:
        @staticmethod
        def parse(f):
            raise RuntimeError("boom")

    failing_mod = ModuleType("ofxparse")
    failing_mod.OfxParser = FailingParser
    monkeypatch.setitem(sys.modules, "ofxparse", failing_mod)

    # Craft minimal QFX/OFX text with two STMTTRN blocks (uppercase tags)
    qfx_text = """\
<OFX>
  <BANKMSGSRSV1>
    <STMTTRN>
      <TRNAMT>-20.00
      <NAME>ACME INC
      <MEMO>Payment
      <DTPOSTED>20250115[0:GMT]
      <CHECKNUM>123
    </STMTTRN>
    <STMTTRN>
      <TRNAMT>1,234.56
      <MEMO>Memo only
      <DTPOSTED>20250116T120000
    </STMTTRN>
  </BANKMSGSRSV1>
</OFX>
"""
    p = tmp_path / "fallback.qfx"
    p.write_text(qfx_text, encoding="utf-8")

    out = qfx.parse_qfx(p)
    assert len(out) == 2

    # First block
    t0 = out[0]
    assert t0["amount"] == "-20.00"
    assert t0["payee"] == "ACME INC"         # name used when present
    assert t0["memo"] == "Payment"
    assert t0["date"] == "01/15/2025"        # _to_date applied
    assert t0["checknum"] == "123"

    # Second block (no NAME)
    t1 = out[1]
    assert t1["amount"] == "1234.56"         # comma removed before float->format
    assert t1["payee"] == "Memo only"        # payee falls back to memo
    assert t1["memo"] == "Memo only"
    assert t1["date"] == "01/16/2025"
    assert t1["checknum"] == ""              # missing → empty
