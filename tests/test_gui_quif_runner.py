import csv
import re
from pathlib import Path
from datetime import datetime

from qif_converter import gui as gui

def mk_tx(date_str, **kw):
    d = {"date": date_str, "amount": "0.00", "payee": "", "category": ""}
    d.update(kw)
    return d


def test_parse_date_maybe_formats():
    d1 = gui.parse_date_maybe("08/12'25")
    d2 = gui.parse_date_maybe("08/12/2025")
    d3 = gui.parse_date_maybe("2025-08-12")
    assert isinstance(d1, datetime) and d1.year in (2025, 1925)
    assert isinstance(d2, datetime) and d2.year == 2025
    assert isinstance(d3, datetime) and d3.year == 2025
    assert gui.parse_date_maybe("not-a-date") is None


def test_filter_date_range_inclusive(tmp_path: Path):
    txns = [
        mk_tx("08/10/2025", payee="A"),
        mk_tx("08/12/2025", payee="B"),
        mk_tx("2025-08-15", payee="C"),
        mk_tx("08/20'25", payee="D"),
    ]
    out = gui.filter_date_range(txns, "08/12/2025", "2025-08-15")
    names = [t["payee"] for t in out]
    assert names == ["B", "C"]


def test_local_filter_by_payee_modes_case():
    txns = [
        mk_tx("08/01/2025", payee="Starbucks #123"),
        mk_tx("08/02/2025", payee="STARBUCKS 456"),
        mk_tx("08/03/2025", payee="Dunkin Donuts"),
        mk_tx("08/04/2025", payee="Joe's Cafe"),
    ]

    out = gui.local_filter_by_payee(txns, "starbucks", mode="contains", case_sensitive=False)
    assert [t["payee"] for t in out] == ["Starbucks #123", "STARBUCKS 456"]

    out = gui.local_filter_by_payee(txns, "STARBUCKS 456", mode="exact", case_sensitive=True)
    assert [t["payee"] for t in out] == ["STARBUCKS 456"]
    out = gui.local_filter_by_payee(txns, "starbucks 456", mode="exact", case_sensitive=True)
    assert out == []

    out = gui.local_filter_by_payee(txns, "Starbucks", mode="startswith", case_sensitive=True)
    assert [t["payee"] for t in out] == ["Starbucks #123"]
    out = gui.local_filter_by_payee(txns, "Cafe", mode="endswith", case_sensitive=False)
    assert [t["payee"] for t in out] == ["Joe's Cafe"]

    out = gui.local_filter_by_payee(txns, "Star*", mode="glob", case_sensitive=False)
    assert [t["payee"] for t in out] == ["Starbucks #123"]
    out = gui.local_filter_by_payee(txns, "*456", mode="glob", case_sensitive=False)
    assert [t["payee"] for t in out] == ["STARBUCKS 456"]

    out = gui.local_filter_by_payee(txns, r"(dunkin|joe's\s+cafe)", mode="regex", case_sensitive=False)
    assert set(t["payee"] for t in out) == {"Dunkin Donuts", "Joe's Cafe"}


def test_apply_multi_payee_filters_any_all():
    txns = [
        mk_tx("08/01/2025", payee="Starbucks #123"),
        mk_tx("08/02/2025", payee="STARBUCKS 456"),
        mk_tx("08/03/2025", payee="Dunkin Donuts"),
        mk_tx("08/04/2025", payee="Joe's Cafe"),
    ]
    out_any = gui.apply_multi_payee_filters(txns, ["starbucks", "dunkin"], mode="contains", case_sensitive=False, combine="any")
    assert set(t["payee"] for t in out_any) == {"Starbucks #123", "STARBUCKS 456", "Dunkin Donuts"}

    out_all = gui.apply_multi_payee_filters(txns, ["Star*", "*123"], mode="glob", case_sensitive=False, combine="all")
    assert [t["payee"] for t in out_all] == ["Starbucks #123"]


def test_csv_profiles_writers(tmp_path: Path):
    txns = [
        mk_tx("08/12/2025", payee="Coffee Shop", amount="-12.34", category="Food:Coffee", account="Checking", memo="morning brew", checknum="1001"),
        mk_tx("08/13/2025", payee="Employer Inc", amount="1500.00", category="Income:Salary", account="Checking", memo="paycheck"),
    ]
    win_csv = tmp_path / "win.csv"
    mac_csv = tmp_path / "mac.csv"

    gui.write_csv_quicken_windows(txns, win_csv)
    gui.write_csv_quicken_mac(txns, mac_csv)

    rows_win = list(csv.reader(win_csv.open("r", encoding="utf-8")))
    assert rows_win[0] == gui.WIN_HEADERS
    assert rows_win[1][0] == "08/12/2025"
    assert rows_win[1][1] == "Coffee Shop"
    assert rows_win[1][3] == "-12.34"
    assert rows_win[1][9] == "1001"
    assert "\n" not in rows_win[1][8]

    rows_mac = list(csv.reader(mac_csv.open("r", encoding="utf-8")))
    assert rows_mac[0] == gui.MAC_HEADERS
    assert rows_mac[1][0] == "08/12/2025"
    assert rows_mac[1][3] == "12.34"
    assert rows_mac[1][4] == "debit"
    assert rows_mac[2][3] == "1500.00"
    assert rows_mac[2][4] == "credit"
