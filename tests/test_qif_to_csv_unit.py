# tests/test_qif_to_csv_unit.py
from __future__ import annotations

import builtins
import contextlib
import csv
import io
from pathlib import Path
from typing import Dict

import pytest

from qif_converter.qif_to_csv import (
    write_csv_flat,
    write_csv_exploded,
    write_csv_quicken_windows,
    write_csv_quicken_mac,
    write_qif,
)

# ---------- Shared in-memory “filesystem” fixture ----------

@pytest.fixture
def memfs(monkeypatch):
    """
    Patch builtins.open so writes go to StringIO keyed by path.
    You can then read back the content via memfs.read(path).
    """
    files: Dict[str, io.StringIO] = {}
    real_open = builtins.open

    def fake_open(file, mode="r", encoding=None, newline=None, **kwargs):
        # Normalize whatever object (Path, str, etc.) into a string key
        key = str(file)

        # Intercept text writes/reads
        if "w" in mode:
            buf = io.StringIO()
            files[key] = buf
            # Path.open returns a file object that supports context manager;
            # nullcontext(StringIO) provides that without closing the buffer.
            return contextlib.nullcontext(buf)

        if "r" in mode and key in files:
            # Re-open from an independent reader to emulate file reopen semantics.
            return contextlib.nullcontext(io.StringIO(files[key].getvalue()))

        # Fall back to real open for anything else
        return real_open(file, mode, encoding=encoding, newline=newline, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open, raising=True)

    class MemFS:
        def read(self, path: Path | str) -> str:
            key = str(path)
            if key not in files:
                raise FileNotFoundError(key)
            return files[key].getvalue()

    return MemFS()


def test__open_for_write_uses_builtins_open(monkeypatch, tmp_path):
    # Arrange
    from qif_converter.qif_to_csv import _open_for_write
    called = {"open": False}
    def fake_open(*a, **k):
        called["open"] = True
        class _F:
            def __enter__(self): return self
            def __exit__(self, *e): pass
            def write(self, *_): pass
        return _F()
    monkeypatch.setattr("builtins.open", fake_open)

    # Act
    with _open_for_write(tmp_path / "x.qif"):
        pass

    # Assert
    assert called["open"] is True


# ---------- write_qif (bank) ----------


def test_write_qif_basic_bank_record_in_memory(memfs):
    txns = [
        {
            "account": "Checking",
            "type": "Bank",
            "date": "2025-01-02",
            "amount": "-12.34",
            "payee": "Coffee Shop",
            "memo": "Latte\nand tip",  # multi-line memo exercise
            "category": "Food:Coffee",
            "checknum": "101",
            "cleared": "X",
            "address": "123 Main St\nCity, ST",
            "splits": [
                {"category": "Food:Coffee", "memo": "Latte", "amount": "-10.00"},
                {"category": "Tips", "memo": "Tip", "amount": "-2.34"},
            ],
        }
    ]

    out = Path("MEM://out.qif")
    write_qif(txns, out)

    text = memfs.read(out)
    # Basic structure assertions
    assert "!Account" in text
    assert "NChecking" in text
    assert "TBank" in text  # account type
    assert "!Type:Bank" in text  # transaction block header
    assert "D2025-01-02" in text  # dates are written as strings directly
    assert "T-12.34" in text
    assert "PCoffee Shop" in text
    # Memo lines are “M” prefixed per line
    assert "MLatte" in text and "Mand tip" in text
    # Splits
    assert "SFood:Coffee" in text
    assert "ELatte" in text
    assert "$-10.00" in text
    assert "STips" in text
    assert "ETip" in text
    assert "$-2.34" in text


# ---------- CSV (flat) ----------

def test_write_csv_flat_in_memory(memfs):
    txns = [
        {
            "date": "2025-02-01",
            "amount": "-20.00",
            "payee": "Store A",
            "memo": "Groceries",
            "category": "Food",
            "checknum": "1001",
            "cleared": "X",
            "address": "123 St",
            "splits": [
                {"category": "Food", "memo": "Veg", "amount": "-12.00"},
                {"category": "Food", "memo": "Fruit", "amount": "-8.00"},
            ],
        },
        {
            "date": "2025-02-02",
            "amount": "50.00",
            "payee": "Employer",
            "memo": "Pay",
            "category": "Income",
        },
    ]

    out = Path("MEM://flat.csv")
    write_csv_flat(txns, out)

    content = memfs.read(out)
    reader = csv.DictReader(io.StringIO(content))
    # Ensure columns
    assert reader.fieldnames == [
        "account","type","date","amount","payee","memo","category","transfer_account",
        "checknum","cleared","address","action","security","quantity","price","commission",
        "split_count","split_category","split_memo","split_amount",
    ]

    rows = list(reader)
    assert len(rows) == 2  # one row per transaction

    # First row has split_count=2 and “ | ”-joined split fields
    r0 = rows[0]
    assert r0["split_count"] == "2"
    assert r0["split_category"] == "Food | Food"
    assert r0["split_memo"] == "Veg | Fruit"
    assert r0["split_amount"] == "-12.00 | -8.00"

    # Second row has split_count=0 and blank split fields
    r1 = rows[1]
    assert r1["split_count"] == "0"
    assert r1["split_category"] == ""
    assert r1["split_memo"] == ""
    assert r1["split_amount"] == ""


# ---------- CSV (exploded) ----------

def test_write_csv_exploded_in_memory(memfs):
    txns = [
        {
            "date": "2025-03-01",
            "amount": "-20.00",
            "payee": "Store B",
            "memo": "Groceries",
            "category": "Food",
            "splits": [
                {"category": "Food", "memo": "Bread", "amount": "-5.00"},
                {"category": "Food", "memo": "Milk", "amount": "-3.00"},
                {"category": "Food", "memo": "Eggs", "amount": "-12.00"},
            ],
        },
        {
            "date": "2025-03-02",
            "amount": "10.00",
            "payee": "Refund",
            "memo": "Return",
            "category": "Misc",
        },
    ]

    out = Path("MEM://exploded.csv")
    write_csv_exploded(txns, out)

    content = memfs.read(out)
    reader = csv.DictReader(io.StringIO(content))
    assert reader.fieldnames == [
        "account","type","date","amount","payee","memo","category","transfer_account",
        "checknum","cleared","address","action","security","quantity","price","commission",
        "split_category","split_memo","split_amount",
    ]

    rows = list(reader)
    # 3 split rows from first txn + 1 non-split row from second txn
    assert len(rows) == 4

    # Verify one split row looks correct
    r = rows[0]
    assert r["payee"] == "Store B"
    assert r["split_category"] == "Food"
    assert r["split_memo"] in {"Bread", "Milk", "Eggs"}
    assert r["split_amount"] in {"-5.00", "-3.00", "-12.00"}


# ---------- CSV (Quicken Windows) ----------

def test_write_csv_quicken_windows_in_memory(memfs):
    txns = [
        {"date": "2025-04-01", "amount": "-1.23", "payee": "P1", "memo": "M1", "category": "C1", "checknum": "11"},
        {"date": "2025-04-02", "amount": "2.50", "payee": "P2", "memo": "M2", "category": "C2", "checknum": "12"},
    ]

    out = Path("MEM://qw.csv")
    write_csv_quicken_windows(txns, out)

    content = memfs.read(out)
    reader = csv.DictReader(io.StringIO(content))

    # Exact header expected by our writer
    assert reader.fieldnames == [
        "Date",
        "Payee",
        "FI Payee",
        "Amount",
        "Debit/Credit",
        "Category",
        "Account",
        "Tag",
        "Memo",
        "Chknum",
    ]

    rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["Date"] == "2025-04-01"
    assert rows[0]["Payee"] == "P1"
    assert rows[0]["Amount"] == "-1.23"
    assert rows[0]["Category"] == "C1"
    assert rows[0]["FI Payee"] == ""  # we map these to empty per writer
    assert rows[0]["Debit/Credit"] == ""


# ---------- CSV (Quicken Mac / Mint) ----------

def test_write_csv_quicken_mac_in_memory(memfs):
    txns = [
        {"date": "2025-05-01", "amount": "-12.00", "payee": "Cafe", "memo": "Latte", "category": "Food:Coffee"},
        {"date": "2025-05-02", "amount": "100.00", "payee": "Employer", "memo": "Pay", "category": "Income:Salary"},
    ]

    out = Path("MEM://qm.csv")
    write_csv_quicken_mac(txns, out)

    content = memfs.read(out)
    reader = csv.DictReader(io.StringIO(content))

    # Exact header expected by our writer
    assert reader.fieldnames == [
        "Date",
        "Description",
        "Original Description",
        "Amount",
        "Transaction Type",
        "Category",
        "Account Name",
        "Labels",
        "Notes",
    ]

    rows = list(reader)
    assert len(rows) == 2
    r0 = rows[0]
    assert r0["Date"] == "2025-05-01"
    assert r0["Description"] == "Cafe"
    assert r0["Original Description"] == ""
    assert r0["Amount"] == "12.00"
    assert r0["Category"] == "Food:Coffee"
    # We don’t over-assert Transaction Type value — only that the column exists.
