from __future__ import annotations

import io
import csv
from pathlib import Path

import pytest

import qif_converter.qif_writer as qw


# ----------------------------- QIF writer tests ------------------------------

def test_write_qif_emits_account_and_type_headers_and_resets_on_account_change():
    """write_qif: emits an !Account block on account changes (with N and T lines)
    and emits !Type:<Type> whenever the transaction type changes. After switching
    accounts, the writer re-emits the !Type header before the next transaction.
    """
    txns = [
        # Account A (Bank)
        {"account": "Checking", "type": "Bank", "date": "01/01/2025", "amount": "-10.00", "payee": "A"},
        {"account": "Checking", "type": "Bank", "date": "01/02/2025", "amount": "-2.00", "payee": "B"},
        # Switch account (forces !Account block and re-emit of !Type)
        {"account": "Savings", "type": "Bank", "date": "01/03/2025", "amount": "1.00", "payee": "C"},
        # Same account, different type -> new !Type header
        {"account": "Savings", "type": "Invst", "date": "01/04/2025", "amount": "0.00", "payee": "D"},
    ]

    buf = io.StringIO()
    qw.write_qif(txns, out=buf)
    out = buf.getvalue()

    # First account header
    assert "!Account\nNChecking\nTBank\n^\n" in out
    # Type header appears before first txn in account
    assert "!Type:Bank" in out

    # After account switches, new account block + re-emitted !Type
    assert "!Account\nNSavings\nTBank\n^\n" in out
    # And then !Type lines for Bank (again) and Invst later
    assert "!Type:Invst" in out

    # Order sanity: the second account header must appear before its subsequent type header
    pos_acct2 = out.index("!Account\nNSavings\nTBank\n^\n")
    pos_type2 = out.index("!Type:Bank", pos_acct2)
    assert pos_acct2 < pos_type2


def test_write_qif_writes_core_fields_memo_address_splits_and_terminator():
    """write_qif: writes D/T/P/M/L core fields; emits one M line *per* memo line
    (not a single M with embedded newline); splits 'address' into multiple A lines;
    writes split entries (S/E/$) in order; and terminates the record with '^'.
    """
    txns = [
        {
            "account": "Checking",
            "type": "Bank",
            "date": "01/02/2025",
            "amount": "-12.34",
            "payee": "ACME",
            "memo": "Line1\nLine2",
            "category": "Food:Groceries",
            "checknum": "123",
            "cleared": "R",
            "address": "Addr1\nAddr2",
            "splits": [
                {"category": "Cat1", "memo": "m1", "amount": "-7.34"},
                {"category": "Cat2", "memo": "m2", "amount": "-5.00"},
            ],
        }
    ]

    buf = io.StringIO()
    qw.write_qif(txns, out=buf)
    out = buf.getvalue()

    # Core lines
    assert "D01/02/2025\n" in out
    assert "T-12.34\n" in out
    assert "PACME\n" in out

    # Memo: one 'M' line PER memo line (not a single 'M' with embedded newline)
    i_m1 = out.index("MLine1\n")
    i_m2 = out.index("MLine2\n")
    assert i_m1 < i_m2

    # Category, checknum, cleared
    assert "LFood:Groceries\n" in out
    assert "N123\n" in out
    assert "CR\n" in out

    # Address split across A lines, in order
    i_a1 = out.index("AAddr1\n")
    i_a2 = out.index("AAddr2\n")
    assert i_a1 < i_a2

    # Splits: ensure S/E/$ triplets appear in order
    s1 = out.index("SCat1\n")
    e1 = out.index("Em1\n", s1)
    d1 = out.index("$-7.34\n", e1)
    s2 = out.index("SCat2\n", d1)
    e2 = out.index("Em2\n", s2)
    d2 = out.index("$-5.00\n", e2)
    assert d2 > d1  # overall sequence maintained

    # Record terminator
    assert out.strip().endswith("^")


def test_write_qif_investment_fields_and_checknum_lines():
    """write_qif: in investment transactions, writes investment fields:
    N<Action> (action), Y<security>, Q<quantity>, I<price>, O<commission>.
    The writer also writes check number with 'N<checknum>' (so two 'N' lines can appear).
    """
    txns = [
        {
            "account": "Brokerage",
            "type": "Invst",
            "date": "01/05/2025",
            "amount": "-123.45",
            "payee": "Broker",
            "checknum": "99",
            "action": "Buy",
            "security": "AAPL",
            "quantity": "10",
            "price": "123.45",
            "commission": "5.00",
        }
    ]

    buf = io.StringIO()
    qw.write_qif(txns, out=buf)
    out = buf.getvalue()

    # Two different N-lines: one for checknum, one for action
    assert "N99\n" in out
    assert "NBuy\n" in out
    assert "YAAPL\n" in out
    assert "Q10\n" in out
    assert "I123.45\n" in out
    assert "O5.00\n" in out


def test_write_qif_writes_to_path_with_utf8_encoding(tmp_path: Path):
    """write_qif: writes to a filesystem path when 'out' is a pathlike; output is
    encoded as specified (default utf-8). This test verifies that content lands on disk.
    """
    txns = [{"date": "01/06/2025", "amount": "1.23", "payee": "Café"}]

    out_path = tmp_path / "out.qif"
    qw.write_qif(txns, out=out_path)  # default encoding 'utf-8'

    text = out_path.read_text(encoding="utf-8")
    assert "PCafé\n" in text
    assert text.strip().endswith("^")


# ----------------------------- CSV writer tests ------------------------------

def _capture_csv(monkeypatch, call_fn, txns, *, newline=""):
    """Helper: monkeypatch qw._open_for_write to return an in-memory file-like object
    that captures its contents on close so we can read it after the writer exits."""
    captured = {}

    def fake_open(path, *, binary=False, newline=""):
        import io

        class CapturingStringIO(io.StringIO):
            def close(self):
                # Save contents before closing so tests can read them safely.
                captured["text"] = self.getvalue()
                super().close()

        return CapturingStringIO()

    # Redirect qif_writer's opener to our capturing in-memory stream
    monkeypatch.setattr(qw, "_open_for_write", fake_open, raising=True)

    # Invoke the writer (it will 'with _open_for_write(...) as f:' and then close f)
    call_fn(txns, Path("dummy.csv"), newline=newline)

    # Return the text captured at close time (safe even though the stream is closed)
    return captured["text"]


def test_write_csv_flat_includes_split_aggregates_and_headers(monkeypatch):
    """write_csv_flat: produces one row per transaction with split aggregates:
    split_count, split_category|split_memo|split_amount joined via ' | '. Unknown
    fields are ignored via extrasaction='ignore'. Header order matches the writer.
    """
    txns = [
        {
            "account": "Checking",
            "type": "Bank",
            "date": "01/01/2025",
            "amount": "-10.00",
            "payee": "A",
            "memo": "M",
            "category": "Cat",
            "checknum": "1",
            "cleared": "R",
            "address": "Addr",
            "splits": [
                {"category": "S1", "memo": "m1", "amount": "-7.00"},
                {"category": "S2", "memo": "m2", "amount": "-3.00"},
            ],
            "unknown": "ignored",
        }
    ]

    csv_text = _capture_csv(monkeypatch, qw.write_csv_flat, txns)
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    assert len(rows) == 1
    r = rows[0]
    assert r["account"] == "Checking"
    assert r["type"] == "Bank"
    assert r["split_count"] == "2"
    assert r["split_category"] == "S1 | S2"
    assert r["split_memo"] == "m1 | m2"
    assert r["split_amount"] == "-7.00 | -3.00"


def test_write_csv_exploded_emits_one_row_per_split_and_single_row_when_no_splits(monkeypatch):
    """write_csv_exploded: emits one row per split when present, otherwise one row per
    transaction. Split fields appear in split_category/split_memo/split_amount columns.
    """
    txns = [
        {
            "account": "Checking", "type": "Bank", "date": "01/01/2025", "amount": "-10.00",
            "payee": "A", "category": "Cat",
            "splits": [{"category": "S1", "memo": "m1", "amount": "-7.00"},
                       {"category": "S2", "memo": "m2", "amount": "-3.00"}],
        },
        {
            "account": "Checking", "type": "Bank", "date": "01/02/2025", "amount": "-5.00",
            "payee": "B", "category": "Cat2",
            # no splits -> one row
        },
    ]

    csv_text = _capture_csv(monkeypatch, qw.write_csv_exploded, txns)
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    # First txn -> 2 split rows; second txn -> 1 row => total 3 rows
    assert len(rows) == 3
    # Rows for first txn have split fields populated
    s_rows = [r for r in rows if r["date"] == "01/01/2025"]
    assert {r["split_category"] for r in s_rows} == {"S1", "S2"}
    # Row for second txn has empty split fields
    r2 = [r for r in rows if r["date"] == "01/02/2025"][0]
    assert r2["split_category"] == "" and r2["split_memo"] == "" and r2["split_amount"] == ""


def test_write_csv_quicken_windows_uses_signed_amount_and_empty_debit_credit(monkeypatch):
    """write_csv_quicken_windows: writes the Quicken Windows header order; leaves the
    'Debit/Credit' column empty and keeps 'Amount' signed exactly as provided.
    """
    txns = [
        {"date": "01/10/2025", "payee": "Alpha", "amount": "-12.34", "category": "CatA", "account": "Acc"},
        {"date": "01/11/2025", "payee": "Beta",  "amount": "56.78",  "category": "CatB", "account": "Acc"},
    ]

    csv_text = _capture_csv(monkeypatch, qw.write_csv_quicken_windows, txns)
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    assert [r["Amount"] for r in rows] == ["-12.34", "56.78"]
    assert [r["Debit/Credit"] for r in rows] == ["", ""]
    assert rows[0]["Payee"] == "Alpha" and rows[1]["Payee"] == "Beta"


def test_write_csv_quicken_mac_sets_type_by_sign_and_amount_is_abs(monkeypatch):
    """write_csv_quicken_mac: outputs 'Transaction Type' = 'credit' for positive amounts
    and 'debit' for zero/negative; 'Amount' is the absolute value. If the amount field is
    missing/empty, the amount cell is empty but the type defaults to 'debit'.
    """
    txns = [
        {"date": "01/12/2025", "payee": "Pos", "amount": "12.34", "category": "C", "account": "A"},
        {"date": "01/13/2025", "payee": "Neg", "amount": "-2.50", "category": "C", "account": "A"},
        {"date": "01/14/2025", "payee": "Missing", "amount": "", "category": "C", "account": "A"},
    ]

    csv_text = _capture_csv(monkeypatch, qw.write_csv_quicken_mac, txns)
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    # Abs amounts
    assert [r["Amount"] for r in rows] == ["12.34", "2.50", ""]
    # Type by sign (missing => debit)
    assert [r["Transaction Type"] for r in rows] == ["credit", "debit", "debit"]
    # Pass-through fields
    assert rows[0]["Description"] == "Pos" and rows[1]["Description"] == "Neg"
