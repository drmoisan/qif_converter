from pathlib import Path
from qif_converter import qif_to_csv as mod
from qif_converter.match_excel import MatchSession, ExcelRow, _parse_date, _to_decimal, build_matched_only_txns

def _write_qif(tmp: Path, text: str) -> Path:
    p = tmp / "in.qif"
    p.write_text(text, encoding="utf-8")
    return p

def test_build_matched_only_txns_splits_and_whole(tmp_path: Path):
    qif = r"""!Type:Bank
D08/11'25
T-50.00
PSome Store
LShopping
SShopping:Clothes
EMemo A
$-30.00
SShopping:Shoes
EMemo B
$-20.00
^
!Type:Bank
D08/12'25
T-12.34
PCoffee
LUnknown
^
"""
    qif_in = _write_qif(tmp_path, qif)
    txns = mod.parse_qif(qif_in)

    # Excel rows: one matches split -30, one matches whole -12.34
    rows = [
        ExcelRow(idx=0, date=_parse_date("08/11/2025"), amount=_to_decimal("-30.00"),
                 item="Shirt", category="Shopping:Clothes", rationale=""),
        ExcelRow(idx=1, date=_parse_date("08/12/2025"), amount=_to_decimal("-12.34"),
                 item="Latte", category="Food:Coffee", rationale=""),
    ]
    s = MatchSession(txns, rows)
    s.auto_match()
    s.apply_updates()

    # Build matched-only view
    only = build_matched_only_txns(s)
    # Expect: first txn appears with only the split -30.00, and second txn included (whole)
    assert len(only) == 2
    t0, t1 = only
    assert len(t0["splits"]) == 1
    assert t0["splits"][0]["amount"] == "-30.00"
    # second is not split and was matched, so present
    assert "splits" not in t1 or not t1["splits"]
    assert t1["amount"] == "-12.34"
