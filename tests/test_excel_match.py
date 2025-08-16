# tests/test_excel_match.py
from pathlib import Path
from decimal import Decimal

from qif_converter import qif_to_csv as mod
from qif_converter.match_excel import (
    load_excel, MatchSession, run_excel_qif_merge, ExcelRow, _parse_date, _to_decimal
)

def _write_qif(tmp: Path, text: str) -> Path:
    p = tmp / "in.qif"
    p.write_text(text, encoding="utf-8")
    return p

def _mk_excel_rows():
    # Simulate rows as if loaded from Excel (no pandas here)
    return [
        ExcelRow(idx=0, date=_parse_date("08/10/2025"), amount=_to_decimal("-12.34"),
                 item="Latte", category="Food:Coffee", rationale="Cafe"),
        ExcelRow(idx=1, date=_parse_date("08/11/2025"), amount=_to_decimal("-30.00"),
                 item="Shirt", category="Shopping:Clothes", rationale="Wardrobe"),
        ExcelRow(idx=2, date=_parse_date("08/11/2025"), amount=_to_decimal("-20.00"),
                 item="Socks", category="Shopping:Shoes", rationale="Wardrobe"),
    ]

def test_auto_match_and_apply_updates(tmp_path: Path):
    qif = r"""!Type:Bank
D08/10'25
T-12.34
PCoffee Shop
LUnknown
^
!Type:Bank
D08/11'25
T-50.00
PSome Store
LShopping
SShopping:Clothes
ESomething
$-30.00
SShopping:Shoes
EOther
$-20.00
^
"""
    qif_in = _write_qif(tmp_path, qif)
    txns = mod.parse_qif(qif_in)
    excel_rows = _mk_excel_rows()

    session = MatchSession(txns, excel_rows)
    session.auto_match()

    # Should match 3 items total: one base txn amount -12.34, and two splits -30, -20
    pairs = session.matched_pairs()
    assert len(pairs) == 3
    # Verify unmatched lists empty
    assert session.unmatched_qif() == []
    assert session.unmatched_excel() == []

    # Apply updates and write out
    session.apply_updates()
    qif_out = tmp_path / "out.qif"
    mod.write_qif(txns, qif_out)

    # Re-parse and verify updates
    t0, t1 = mod.parse_qif(qif_out)
    # First txn updated (category from Excel, memo from Item)
    assert t0["category"] == "Food:Coffee"
    assert t0["memo"] == "Latte"

    # Second txn splits updated
    assert len(t1["splits"]) == 2
    s0, s1 = t1["splits"]
    assert s0["category"] == "Shopping:Clothes"
    assert s0["memo"] == "Shirt"
    assert s1["category"] == "Shopping:Shoes"
    assert s1["memo"] == "Socks"

def test_manual_match_and_reason(tmp_path: Path):
    qif = r"""!Type:Bank
D08/15'25
T-10.00
PPlace A
LUnknown
^
"""
    qif_in = _write_qif(tmp_path, qif)
    txns = mod.parse_qif(qif_in)

    excel_rows = [
        ExcelRow(idx=0, date=_parse_date("08/20/2025"), amount=_to_decimal("-10.00"),
                 item="Thing", category="X:Cat", rationale="Too far date"),  # 5 days off
    ]
    sess = MatchSession(txns, excel_rows)
    sess.auto_match()
    # No auto match because ±3 days window exceeded
    assert len(sess.matched_pairs()) == 0
    uq = sess.unmatched_qif()[0]
    reason = sess.nonmatch_reason(uq, excel_rows[0])
    assert "outside ±3 days" in reason

    # Now manually matching will still fail due to rule
    ok, msg = sess.manual_match(uq.key, 0)
    assert not ok
    assert "outside ±3 days" in msg

def test_unmatch_roundtrip(tmp_path: Path):
    qif = r"""!Type:Bank
D08/12'25
T-5.00
PA
LUnknown
^
"""
    qif_in = _write_qif(tmp_path, qif)
    txns = mod.parse_qif(qif_in)
    excel = [ExcelRow(idx=0, date=_parse_date("08/12/2025"), amount=_to_decimal("-5.00"),
                      item="Item", category="New:Cat", rationale="")]
    s = MatchSession(txns, excel)
    s.auto_match()
    assert len(s.matched_pairs()) == 1
    # Unmatch and verify they go back to unmatched lists
    qv, _, _ = s.matched_pairs()[0]
    assert s.manual_unmatch(qkey=qv.key)
    assert len(s.matched_pairs()) == 0
    assert len(s.unmatched_qif()) == 1
    assert len(s.unmatched_excel()) == 1

def test_end_to_end_helper_writes_new_file(tmp_path: Path):
    qif = r"""!Type:Bank
D08/10'25
T-12.34
PCoffee Shop
LUnknown
^
"""
    qif_in = _write_qif(tmp_path, qif)
    # Build a tiny Excel via the API (simulate loaded row)
    xrows = [ExcelRow(idx=0, date=_parse_date("08/10/2025"), amount=_to_decimal("-12.34"),
                      item="Latte", category="Food:Coffee", rationale="")]
    # Monkey-patch the loader to return our rows without needing pandas
    from qif_converter import match_excel as mex
    orig_load = mex.load_excel
    mex.load_excel = lambda _p: xrows
    try:
        out = tmp_path / "updated.qif"
        pairs, uq, ue = mex.run_excel_qif_merge(qif_in, tmp_path / "dummy.xlsx", out)
        assert out.exists()
        assert len(pairs) == 1 and not uq and not ue
        t0 = mod.parse_qif(out)[0]
        assert t0["category"] == "Food:Coffee"
        assert t0["memo"] == "Latte"
    finally:
        mex.load_excel = orig_load
