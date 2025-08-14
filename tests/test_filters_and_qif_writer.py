import csv
import sys
from pathlib import Path
from qif_converter import qif_to_csv as mod


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def read_csv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


SAMPLE_QIF = r"""!Account
NChecking
TBank
^
!Type:Bank
D08/01'25
T-5.25
PStarbucks #123
LFood:Coffee
^
!Type:Bank
D08/02'25
T-6.10
PSTARBUCKS 456
LFood:Coffee
^
!Type:Bank
D08/03'25
T-7.25
PDunkin Donuts
LFood:Coffee
^
!Type:Bank
D08/04'25
T-10.00
PJoe's Cafe
LFood:Coffee
^
"""


def test_filter_contains_case_insensitive(tmp_path: Path):
    qif_path = write(tmp_path, "sample.qif", SAMPLE_QIF)
    txns = mod.parse_qif(qif_path)
    out = mod.filter_by_payee(txns, "starbucks", mode="contains", case_sensitive=False)
    names = [t.get("payee") for t in out]
    assert len(out) == 2
    assert any("Starbucks #123" == n for n in names)
    assert any("STARBUCKS 456" == n for n in names)


def test_filter_exact_case_sensitive(tmp_path: Path):
    qif_path = write(tmp_path, "sample.qif", SAMPLE_QIF)
    txns = mod.parse_qif(qif_path)
    out = mod.filter_by_payee(txns, "STARBUCKS 456", mode="exact", case_sensitive=True)
    assert len(out) == 1
    assert out[0]["payee"] == "STARBUCKS 456"
    out2 = mod.filter_by_payee(txns, "starbucks 456", mode="exact", case_sensitive=True)
    assert len(out2) == 0


def test_filter_startswith_endswith(tmp_path: Path):
    qif_path = write(tmp_path, "sample.qif", SAMPLE_QIF)
    txns = mod.parse_qif(qif_path)
    out = mod.filter_by_payee(txns, "Starbucks", mode="startswith", case_sensitive=True)
    assert len(out) == 1
    out2 = mod.filter_by_payee(txns, "Cafe", mode="endswith", case_sensitive=False)
    assert len(out2) == 1
    assert out2[0]["payee"] == "Joe's Cafe"


def test_filter_regex(tmp_path: Path):
    qif_path = write(tmp_path, "sample.qif", SAMPLE_QIF)
    txns = mod.parse_qif(qif_path)
    out = mod.filter_by_payee(txns, r"(dunkin|joe's\s+cafe)", mode="regex", case_sensitive=False)
    names = [t["payee"] for t in out]
    assert set(names) == {"Dunkin Donuts", "Joe's Cafe"}


def test_cli_filter_to_csv(tmp_path: Path, monkeypatch):
    qif_path = write(tmp_path, "sample.qif", SAMPLE_QIF)
    out_csv = tmp_path / "filtered.csv"
    sys.argv = ["qif_to_csv.py", str(qif_path), str(out_csv), "--filter-payee", "starbucks"]
    mod.main()
    rows = read_csv(out_csv)
    assert len(rows) == 2
    assert set(r["payee"] for r in rows) == {"Starbucks #123", "STARBUCKS 456"}


ROUNDTRIP_QIF = r"""!Account
NBrokerage
TInvst
^
!Type:Invst
D08/05'25
NBuy
YACME Corp
Q10
I25.50
T-255.00
O1.00
^
!Account
NChecking
TBank
^
!Type:Bank
D08/06'25
T-20.00
PUtility Co
LUtilities:Electric
SUtilities:Electric
EBase charge
$-18.00
STaxes
EState tax
$-2.00
A123 Main St
ASuite 456
^
"""


def test_write_qif_roundtrip(tmp_path: Path):
    src = write(tmp_path, "src.qif", ROUNDTRIP_QIF)
    txns = mod.parse_qif(src)
    subset = [t for t in txns if (t.get("type") == "Bank" and "Utility" in t.get("payee", ""))]
    out_qif = tmp_path / "filtered.qif"
    mod.write_qif(subset, out_qif)
    txns2 = mod.parse_qif(out_qif)
    assert len(txns2) == 1
    t = txns2[0]
    assert t["type"] == "Bank"
    assert t["payee"] == "Utility Co"
    assert t["category"] == "Utilities:Electric"
    assert len(t["splits"]) == 2
    assert t["address"] == "123 Main St\nSuite 456"
