import csv
from pathlib import Path
import sys

import qif_converter.qif_loader
from qif_converter import qif_writer as mod


def write_qif(tmp_path: Path, text: str, name: str = "in.qif", encoding="utf-8") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding=encoding)
    return p


def read_csv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_parse_simple_bank(tmp_path: Path):
    qif = r"""!Type:Bank
D08/12'25
T-45.67
PAwesome Store
LShopping:General
^
"""
    p = write_qif(tmp_path, qif)
    txns = qif_converter.qif_loader.parse_qif(p)
    assert len(txns) == 1
    t = txns[0]
    assert t["type"] == "Bank"
    assert t["date"] == "08/12'25"
    assert t["amount"] == "-45.67"
    assert t["payee"] == "Awesome Store"
    assert t["category"] == "Shopping:General"
    assert t["transfer_account"] == ""


def test_account_block_sets_account_name(tmp_path: Path):
    qif = r"""!Account
NChecking
TBank
^
!Type:Bank
D01/01'25
T100.00
PDeposit
LIncome:Salary
^
"""
    p = write_qif(tmp_path, qif)
    txns = qif_converter.qif_loader.parse_qif(p)
    assert len(txns) == 1
    t = txns[0]
    assert t["account"] == "Checking"
    assert t["type"] == "Bank"
    assert t["payee"] == "Deposit"


def test_transfer_account_from_category(tmp_path: Path):
    qif = r"""!Type:Bank
D02/01'25
T-250.00
PTransfer to Savings
L[Savings]
^
"""
    p = write_qif(tmp_path, qif)
    t = qif_converter.qif_loader.parse_qif(p)[0]
    assert t["category"] == "[Savings]"
    assert t["transfer_account"] == "Savings"


def test_splits_parsing_and_flat_writer(tmp_path: Path):
    qif = r"""!Type:Bank
D03/01'25
T-145.32
PUtility Company
LUtilities
SUtilities:Electric
EBase charge
$-120.00
STaxes
EState utility tax
$-25.32
^
"""
    p = write_qif(tmp_path, qif)
    txns = qif_converter.qif_loader.parse_qif(p)
    assert len(txns) == 1
    t = txns[0]
    assert len(t["splits"]) == 2
    out = tmp_path / "out_flat.csv"
    mod.write_csv_flat(txns, out)
    rows = read_csv(out)
    assert len(rows) == 1
    r = rows[0]
    assert r["split_count"] == "2"
    assert r["split_categories"] == "Utilities:Electric | Taxes"
    assert r["split_memos"] == "Base charge | State utility tax"
    assert r["split_amounts"] == "-120.00 | -25.32"


def test_exploded_writer_emits_one_row_per_split(tmp_path: Path):
    qif = r"""!Type:Bank
D03/02'25
T-50.00
PSome Store
LShopping
SShopping:Clothes
EShirt
$-30.00
SShopping:Shoes
ESocks
$-20.00
^
"""
    p = write_qif(tmp_path, qif)
    txns = qif_converter.qif_loader.parse_qif(p)
    out = tmp_path / "out_exploded.csv"
    mod.write_csv_exploded(txns, out)
    rows = read_csv(out)
    assert len(rows) == 2
    cats = [r["split_category"] for r in rows]
    amts = [r["split_amount"] for r in rows]
    assert cats == ["Shopping:Clothes", "Shopping:Shoes"]
    assert amts == ["-30.00", "-20.00"]


def test_investment_action_vs_checknum(tmp_path: Path):
    qif = r"""!Type:Invst
D04/01'25
NBuy
YACME Corp
Q10
I25.5
T-255.00
O1.00
^
"""
    p = write_qif(tmp_path, qif)
    t = qif_converter.qif_loader.parse_qif(p)[0]
    assert t.get("action") == "Buy"
    assert t.get("checknum", "") == ""
    assert t["security"] == "ACME Corp"
    assert t["quantity"] == "10"
    assert t["price"] == "25.5"
    assert t["commission"] == "1.00"


def test_multiline_address_and_memo_accumulate(tmp_path: Path):
    qif = r"""!Type:Bank
D05/01'25
T-10.00
PSome Place
A123 Main St
ASuite 456
MLine1
MLine2
LFood:Coffee
^
"""
    p = write_qif(tmp_path, qif)
    t = qif_converter.qif_loader.parse_qif(p)[0]
    assert t["address"] == "123 Main St\nSuite 456"
    assert t["memo"] == "Line1\nLine2"


def test_unknown_fields_ignored_and_missing_final_caret(tmp_path: Path):
    qif = r"""!Type:Bank
D06/01'25
T-1.00
PTest
LOther
Zignored
"""
    p = write_qif(tmp_path, qif)
    txns = qif_converter.qif_loader.parse_qif(p)
    assert len(txns) == 1
    t = txns[0]
    assert t["payee"] == "Test"
    assert t["amount"] == "-1.00"
    assert "Z" not in t


def test_cli_end_to_end_flat_and_exploded(tmp_path: Path, monkeypatch):
    qif = r"""!Type:Bank
D07/01'25
T-12.34
PCoffee Shop
LFood:Coffee
^
"""
    qif_path = write_qif(tmp_path, qif)
    out_flat = tmp_path / "flat.csv"
    out_exploded = tmp_path / "exploded.csv"

    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    sys.argv = ["qif_to_csv.py", str(qif_path), str(out_flat)]
    mod.main()
    rows = read_csv(out_flat)
    assert len(rows) == 1
    assert rows[0]["payee"] == "Coffee Shop"

    sys.argv = ["qif_to_csv.py", str(qif_path), str(out_exploded), "--explode-splits"]
    mod.main()
    rows2 = read_csv(out_exploded)
    assert len(rows2) == 1
    assert rows2[0]["split_category"] == ""
