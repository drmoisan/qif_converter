# tests/test_excel_only_matched.py
from qif_converter.match_excel import (
    MatchSession,
    build_matched_only_txns,
    load_excel_rows,
    group_excel_rows,
)
from decimal import Decimal
from pathlib import Path
import pandas as pd


def _mk_tx(date, amount, splits=None):
    t = {"date": date, "amount": amount}
    if splits is not None:
        t["splits"] = splits
    return t


def test_build_matched_only_txns_splits_and_whole(tmp_path: Path):
    # QIF has three txns; we’ll match only two by total amount
    txns = [
        _mk_tx("2025-07-01", "-30.00"),
        _mk_tx("2025-07-02", "-20.00", splits=[
            {"category": "Old:Cat", "memo": "old1", "amount": Decimal("-10.00")},
            {"category": "Old:Cat", "memo": "old2", "amount": Decimal("-10.00")},
        ]),
        _mk_tx("2025-07-03", "-99.00"),
    ]

    rows = [
        ["A","2025-07-01","-30.00","i1","C1","R1"],
        ["B","2025-07-02","-10.00","i2a","C2","R2a"],
        ["B","2025-07-02","-10.00","i2b","C3","R2b"],
    ]
    xlsx = tmp_path / "in.xlsx"
    pd.DataFrame(rows, columns=[
        "TxnID","Date","Amount","Item","Canonical MECE Category","Categorization Rationale"
    ]).to_excel(xlsx, index=False)

    excel_groups = group_excel_rows(load_excel_rows(xlsx))
    session = MatchSession(txns, excel_groups=excel_groups)
    session.auto_match()
    session.apply_updates()

    matched_only = build_matched_only_txns(session)
    # Expect only first two txns (3rd unmatched)
    assert len(matched_only) == 2

    # Splits for second txn should be overwritten from Excel (C2/C3)
    t2 = matched_only[1]
    cats = [s["category"] for s in t2["splits"]]
    memos = [s["memo"] for s in t2["splits"]]
    amts = [s["amount"] for s in t2["splits"]]
    assert cats == ["C2", "C3"]
    assert memos == ["i2a", "i2b"]
    assert amts == [Decimal("-10.00"), Decimal("-10.00")]
