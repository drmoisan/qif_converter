from datetime import date
from decimal import Decimal

from qif_converter.match_session import MatchSession
from qif_converter.excel_row import ExcelRow
from qif_converter.excel_txn_group import ExcelTxnGroup


# --- Helpers (Arrange) --------------------------------------------------------
def _mk_tx(datestr, amt, splits=None):
    return {"date": datestr, "amount": amt, "splits": (splits or [])}


def _mk_group(rows, gid="G"):
    # Derive group date and total from the rows
    group_date = rows[0].date if rows else None
    total = sum((r.amount for r in rows), Decimal("0"))
    # Instantiate ExcelTxnGroup directly (no from_rows needed)
    return ExcelTxnGroup(
        gid=gid,
        date=group_date,
        total_amount=total,
        rows=tuple(rows),
    )


class _TestableMatchSession(MatchSession):
    """
    Minimal test-only subclass that exposes a way to directly set the group match
    (bypassing auto_match/manual_match). This keeps the test isolated on
    apply_updates().
    """
    def force_group_link(self, txn_index: int, group_index: int) -> None:
        qkey = self.txn_views[txn_index].key
        # Store the *group object* in qif_to_excel_group so matched_pairs()
        # can use grp.date etc. (some versions store an index; this ensures
        # compatibility with the object-consuming code path).
        self.qif_to_excel_group[qkey] = self.excel_groups[group_index]
        # Keep the reverse map by index → qkey, which other flows expect.
        self.excel_group_to_qif[group_index] = qkey


# --- The independent test (Arrange-Act-Assert) -------------------------------

# def test_apply_updates_overwrites_splits_from_matched_groups_independent():
#     # Arrange
#     txns = [
#         _mk_tx("2025-07-02", "-20.00", splits=[
#             {"category": "Old:Cat", "memo": "old1", "amount": Decimal("-10.00")},
#             {"category": "Old:Cat", "memo": "old2", "amount": Decimal("-10.00")},
#         ]),
#     ]
#     rows = [
#         ExcelRow(idx=0, txn_id="B", date=date(2025, 7, 2), amount=Decimal("-10.00"), item="i2a", category="New:C2", rationale="R2a"),
#         ExcelRow(idx=1, txn_id="B", date=date(2025, 7, 2), amount=Decimal("-10.00"), item="i2b", category="New:C3", rationale="R2b"),
#     ]
#     grp = _mk_group(rows, gid="B")
#     session = _TestableMatchSession(txns, excel_groups=[grp])
#
#     # Act
#     # Force the mapping so we don’t depend on auto/ manual matching.
#     session.force_group_link(txn_index=0, group_index=0)
#     session.apply_updates()
#
#     # Assert
#     updated = txns[0]
#     assert "splits" in updated and len(updated["splits"]) == 2, \
#         "Existing splits must be replaced by Excel group splits."
#     cats = [s["category"] for s in updated["splits"]]
#     memos = [s["memo"] for s in updated["splits"]]
#     amts = [s["amount"] for s in updated["splits"]]
#
#     assert cats == ["New:C2", "New:C3"]
#     assert memos == ["i2a", "i2b"]
#     assert amts == [Decimal("-10.00"), Decimal("-10.00")]
