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
    assert len(out) == 1  # Only "Starbucks #123" when case-sensitive
    out2 = mod.filter_by_payee(txns, "Cafe", mode="endswith", case_sensitive=False)
    assert len(out2) == 1
    assert out2[0]["payee"] == "Joe's Cafe"


def test_filter_regex_and_glob(tmp_path: Path):
    qif_path = write(tmp_path, "sample.qif", SAMPLE_QIF)
    txns = mod.parse_qif(qif_path)
    out = mod.filter_by_payee(txns, r"(dunkin|joe's\s+cafe)", mode="regex", case_sensitive=False)
    names = [t["payee"] for t in out]
    assert set(names) == {"Dunkin Donuts", "Joe's Cafe"}
    # glob star*
    out2 = mod.filter_by_payee(txns, "Star*", mode="glob", case_sensitive=True)
    names2 = [t["payee"] for t in out2]
    assert names2 == ["Starbucks #123"]


def test_filter_multi_any_all(tmp_path: Path):
    qif_path = write(tmp_path, "sample.qif", SAMPLE_QIF)
    txns = mod.parse_qif(qif_path)
    # any: Starbucks or Dunkin (case-insensitive contains)
    out_any = mod.filter_by_payees(txns, ["starbucks", "dunkin"], mode="contains", case_sensitive=False, combine="any")
    assert set(t["payee"] for t in out_any) == {"Starbucks #123", "STARBUCKS 456", "Dunkin Donuts"}
    # all: startswith "Star" AND contains "456" -> matches STARBUCKS 456 only if case-insensitive & combine all with glob/contains
    out_all = mod.filter_by_payees(txns, ["star*", "*456"], mode="glob", case_sensitive=False, combine="all")
    assert set(t["payee"] for t in out_all) == {"STARBUCKS 456"}


def test_cli_filter_to_csv_profiles(tmp_path: Path):
    qif_path = write(tmp_path, "sample.qif", SAMPLE_QIF)
    # Windows profile
    out_csv = tmp_path / "win.csv"
    sys.argv = ["qif_to_csv.py", str(qif_path), str(out_csv), "--filter-payee", "starbucks", "--csv-profile", "quicken-windows"]
    mod.main()
    rows = read_csv(out_csv)
    assert rows[0].keys() == {"Date","Payee","FI Payee","Amount","Debit/Credit","Category","Account","Tag","Memo","Chknum"}
    assert len(rows) == 2
    # Mac profile
    out_csv2 = tmp_path / "mac.csv"
    sys.argv = ["qif_to_csv.py", str(qif_path), str(out_csv2), "--filter-payee", "starbucks", "--csv-profile", "quicken-mac"]
    mod.main()
    rows2 = read_csv(out_csv2)
    assert rows2[0].keys() == {"Date","Description","Original Description","Amount","Transaction Type","Category","Account Name","Labels","Notes"}
    assert len(rows2) == 2


ROUNDTRIP_QIF = r"""!Account
NChecking
TBank
^
!Type:Bank
D08/01'25
T-20.00
PUtility Co
LUtilities:Electric
A123 Main St
ASuite 456
^
!Type:Bank
D08/10'25
T-50.00
PSome Other
LOther
^
"""


def test_date_range_filter(tmp_path: Path):
    src = write(tmp_path, "range.qif", ROUNDTRIP_QIF)
    txns = mod.parse_qif(src)
    # range: include only 08/05'25..08/09'25 -> should exclude both
    filtered = mod.filter_by_date_range(txns, "08/05/2025", "2025-08-09")
    assert filtered == []
    # include 08/01'25..08/05'25 -> includes first only
    filtered2 = mod.filter_by_date_range(txns, "08/01'25", "08/05'25")
    assert len(filtered2) == 1
    assert filtered2[0]["payee"] == "Utility Co"
