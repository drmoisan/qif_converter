# tests/test_qif_to_csv_unit.py
from __future__ import annotations

from pathlib import Path
import csv
import io
from decimal import Decimal
import pytest

# Unit-under-test
from qif_converter.qif_to_csv import (
    _parse_qif_date,
    _match_one,
    filter_by_payees,
    write_csv_quicken_windows,
    write_csv_quicken_mac,
    write_qif,
)

# ---------- _parse_qif_date ----------

@pytest.mark.parametrize(
    "raw,expect_iso",
    [
        ("12/31'24", "2024-12-31"),
        ("12/31/2024", "2024-12-31"),
        ("2024-12-31", "2024-12-31"),
        ("2024/12/31", "2024-12-31"),
    ],
)
def test__parse_qif_date_formats(raw, expect_iso):
    d = _parse_qif_date(raw)
    assert d.isoformat() == expect_iso


# ---------- _match_one ----------

@pytest.mark.parametrize(
    "mode,query,payee,case,expect",
    [
        ("contains", "latte", "Starbucks Latte", False, True),
        ("contains", "LATTE", "Starbucks Latte", False, True),
        ("contains", "LATTE", "Starbucks Latte", True,  False),

        ("exact",    "Store A", "Store A",       False, True),
        ("exact",    "store a", "Store A",       False, True),
        ("exact",    "store a", "Store A",       True,  False),

        ("starts",   "Star",    "Starbucks",     False, True),
        ("starts",   "star",    "Starbucks",     True,  False),

        ("ends",     "bucks",   "Starbucks",     False, True),
        ("ends",     "BUCKS",   "Starbucks",     True,  False),

        ("glob",     "Store *", "Store A",       False, True),
        ("glob",     "S*e ?",   "Store A",       False, True),

        ("regex",    r"^Cafe\s+\d+$", "Cafe 123", False, True),
        ("regex",    r"[0-9]{3}",     "Cafe ABC", False, False),
    ],
)
def test__match_one_modes(mode, query, payee, case, expect):
    assert _match_one(payee, query, mode=mode, case_sensitive=case) is expect


# ---------- filter_by_payees ----------

def test_filter_by_payees_any_and_all_case():
    txns = [
        {"date": "2025-01-01", "payee": "Starbucks", "amount": "-5.00"},
        {"date": "2025-01-02", "payee": "Whole Foods", "amount": "-20.00"},
        {"date": "2025-01-03", "payee": "Local Cafe", "amount": "-7.50"},
    ]
    # ANY of ["star", "cafe"] case-insensitive → 2 matches
    out_any = filter_by_payees(txns, ["star", "cafe"], mode="contains", case_sensitive=False, combine="any")
    assert [t["payee"] for t in out_any] == ["Starbucks", "Local Cafe"]

    # ALL of ["whole", "foods"] (contains, case-insensitive) → 1 match
    out_all = filter_by_payees(txns, ["whole", "foods"], mode="contains", case_sensitive=False, combine="all")
    assert [t["payee"] for t in out_all] == ["Whole Foods"]

    # Case-sensitive contains: "Star" should match "Starbucks"; "star" should not
    out_cs = filter_by_payees(txns, ["Star"], mode="contains", case_sensitive=True, combine="any")
    assert [t["payee"] for t in out_cs] == ["Starbucks"]

    out_cs_none = filter_by_payees(txns, ["star"], mode="contains", case_sensitive=True, combine="any")
    assert out_cs_none == []


# ---------- write_csv_quicken_windows ----------

def test_write_csv_quicken_windows_headers_and_values(tmp_path: Path):
    txns = [
        {"date": "2025-02-01", "payee": "Store", "memo": "memo1", "amount": "-12.34", "category": "Food"},
    ]
    out = tmp_path / "win.csv"
    write_csv_quicken_windows(txns, out)

    with out.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        # Header should at least include these standard columns
        assert set(["Date", "Payee", "Memo", "Amount", "Category"]).issubset(reader.fieldnames or [])
        rows = list(reader)

    assert len(rows) == 1
    r = rows[0]
    # Windows profile keeps signed Amount as-is
    assert r["Date"] == "2025-02-01"
    assert r["Payee"] == "Store"
    assert r["Memo"] == "memo1"
    assert r["Category"] == "Food"
    assert r["Amount"] in ("-12.34", "-12.340000", str(Decimal("-12.34")))  # tolerate formatting


# ---------- write_csv_quicken_mac ----------

@pytest.mark.parametrize(
    "amount,expect_type,expect_amount",
    [
        ("-12.34", "debit",  "12.34"),
        ("25.00",  "credit", "25.00"),
    ],
)
def test_write_csv_quicken_mac_sign_and_headers(tmp_path: Path, amount, expect_type, expect_amount):
    txns = [
        {"date": "2025-03-15", "payee": "Merchant", "memo": "m", "amount": amount, "category": "Misc"},
    ]
    out = tmp_path / "mac.csv"
    write_csv_quicken_mac(txns, out)

    with out.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        # Expect these profile columns to exist
        required = {"Date", "Description", "Original Description", "Amount", "Transaction Type", "Category", "Account Name", "Account Number", "Labels", "Notes"}
        assert required.issubset(set(reader.fieldnames or []))
        rows = list(reader)

    assert len(rows) == 1
    r = rows[0]
    # Quicken Mac: Amount is absolute; sign encoded in Transaction Type
    assert r["Date"] == "2025-03-15"
    assert r["Description"] == "Merchant"
    assert r["Original Description"] == "Merchant"
    assert r["Category"] == "Misc"
    assert r["Transaction Type"].lower() == expect_type
    # Normalize numeric string (allow csv module to add trailing zeros)
    assert Decimal(r["Amount"]) == Decimal(expect_amount)


# ---------- write_qif ----------

def test_write_qif_basic_bank_record(tmp_path: Path):
    txns = [
        {
            "type": "Bank",
            "date": "2025-04-02",
            "amount": "-42.50",
            "payee": "Books & Co",
            "memo": "paperbacks",
            "category": "Books",
            "address": "123 Main St\nApt 4",
        }
    ]
    out = tmp_path / "out.qif"
    write_qif(txns, out)

    text = out.read_text(encoding="utf-8")
    # Must include a Type header for Bank
    assert "!Type:Bank" in text
    # Required record fields
    assert "D2025-04-02" in text
    assert "$-42.50" in text or "$-42.5" in text
    assert "PBooks & Co" in text
    assert "Mpaperbacks" in text
    assert "LBooks" in text
    # Address lines are prefixed with 'A'
    assert "A123 Main St" in text and "AApt 4" in text
    # Record terminator
    assert "^\n" in text or text.endswith("^")
