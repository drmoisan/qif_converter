# tests/test_excel_match.py
# Tests updated for TxnID-grouped Excel splits and transaction-level matching.
import pytest

#from .. import qif_converter
#import qif_converter
from qif_converter import qif_writer as mod
from qif_converter.match_session import MatchSession
from qif_converter.match_excel import group_excel_rows, load_excel_rows, run_excel_qif_merge
from pathlib import Path
from decimal import Decimal

def _mk_tx(date, amount, payee="P", memo="", category="", splits=None):
    t = {"date": date, "amount": amount, "payee": payee, "memo": memo, "category": category}
    if splits is not None:
        t["splits"] = splits
    return t


def test_auto_match_and_apply_updates(tmp_path: Path):
    # QIF: two transactions
    txns = [
        _mk_tx("2025-08-01", "-50.00", payee="Store A"),
        _mk_tx("2025-08-02", "-20.00", payee="Store B"),
    ]

    # Excel: two TxnID groups, each with splits that sum to txn total
    rows = [
        ["T1","2025-08-01","-30.00","Item A1","Cat:A","Why A1"],
        ["T1","2025-08-01","-20.00","Item A2","Cat:B","Why A2"],
        ["T2","2025-08-02","-20.00","Item B1","Cat:C","Why B1"],
    ]
    xlsx = tmp_path / "in.xlsx"
    import pandas as pd
    pd.DataFrame(rows, columns=[
        "TxnID","Date","Amount","Item","Canonical MECE Category","Categorization Rationale"
    ]).to_excel(xlsx, index=False)

    excel_groups = group_excel_rows(load_excel_rows(xlsx))
    session = MatchSession(txns, excel_groups=excel_groups)
    session.auto_match()
    session.apply_updates()

    # After applying updates, QIF txns should have splits from Excel
    t1, t2 = txns
    assert "splits" in t1 and len(t1["splits"]) == 2
    assert t1["splits"][0]["category"] == "Cat:A"
    assert t1["splits"][0]["memo"] == "Item A1"
    assert t1["splits"][0]["amount"] == Decimal("-30.00")
    assert t1["splits"][1]["category"] == "Cat:B"
    assert t1["splits"][1]["amount"] == Decimal("-20.00")

    assert "splits" in t2 and len(t2["splits"]) == 1
    assert t2["splits"][0]["category"] == "Cat:C"
    assert t2["splits"][0]["amount"] == Decimal("-20.00")


def test_manual_match_and_reason(tmp_path: Path):
    txns = [
        _mk_tx("2025-08-10", "-42.00", payee="Cafe"),
    ]
    rows = [
        ["Z1","2025-08-09","-42.00","Latte","Food:Coffee","receipt"],
    ]
    xlsx = tmp_path / "in.xlsx"
    import pandas as pd
    pd.DataFrame(rows, columns=[
        "TxnID","Date","Amount","Item","Canonical MECE Category","Categorization Rationale"
    ]).to_excel(xlsx, index=False)
    excel_groups = group_excel_rows(load_excel_rows(xlsx))
    session = MatchSession(txns, excel_groups=excel_groups)
    session.auto_match()

    # There should be a match on amount and ±3 days
    pairs = session.matched_pairs()
    assert len(pairs) == 1
    q, grp, cost = pairs[0]
    assert cost in (0,1,2,3)
    # Reason check for an arbitrary non-match (change amount)
    fake_grp = type("G", (), dict(gid="fake", date=grp.date, total_amount=Decimal("-41.00"), rows=()))
    reason = session.nonmatch_reason(q, fake_grp)
    assert "Amount differs" in reason


def test_unmatch_roundtrip(tmp_path: Path):
    txns = [
        _mk_tx("2025-08-01", "-10.00"),
        _mk_tx("2025-08-02", "-20.00"),
    ]
    rows = [
        ["A","2025-08-01","-10.00","i1","C1","R1"],
        ["B","2025-08-02","-20.00","i2","C2","R2"],
    ]
    xlsx = tmp_path / "in.xlsx"
    import pandas as pd
    pd.DataFrame(rows, columns=[
        "TxnID","Date","Amount","Item","Canonical MECE Category","Categorization Rationale"
    ]).to_excel(xlsx, index=False)

    excel_groups = group_excel_rows(load_excel_rows(xlsx))
    session = MatchSession(txns, excel_groups=excel_groups)
    session.auto_match()
    assert len(session.matched_pairs()) == 2

    # Unmatch the first one
    q, grp, _ = session.matched_pairs()[0]
    gi = session.excel_groups.index(grp)
    session.manual_unmatch(qkey=q.key)
    assert len(session.matched_pairs()) == 1

    # Match back manually
    #ok, msg = session.manual_match(qkey=q.key, excel_group_index=gi)
    qkey = q.key
    egi = gi
    ok, msg = session.manual_match(qkey=qkey, excel_idx=egi)
    assert ok
    assert len(session.matched_pairs()) == 2


def test_end_to_end_helper_writes_new_file(tmp_path: Path):
    # QIF source file
    qif_in = tmp_path / "in.qif"
    qif_out = tmp_path / "out.qif"
    txns = [
        _mk_tx("2025-08-01", "-12.00"),
    ]
    mod.write_qif(txns, qif_in)

    # Excel file
    rows = [
        ["G1","2025-08-01","-7.00","A","Food","a"],
        ["G1","2025-08-01","-5.00","B","Food","b"],
    ]
    xlsx = tmp_path / "in.xlsx"
    import pandas as pd
    pd.DataFrame(rows, columns=[
        "TxnID","Date","Amount","Item","Canonical MECE Category","Categorization Rationale"
    ]).to_excel(xlsx, index=False)

    # Merge and write
    pairs, uq, ue = run_excel_qif_merge(qif_in, xlsx, qif_out)
    assert qif_out.exists()
    # Should have one pair, no unmatched
    assert len(pairs) == 1
    assert len(uq) == 0
    assert len(ue) == 0
