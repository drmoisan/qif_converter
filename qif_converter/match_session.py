from __future__ import annotations

from typing import List, Dict, Any, Tuple, Optional

from _decimal import Decimal

from qif_converter.match_helpers import _to_decimal, _candidate_cost, TxnLegacyView #,_flatten_qif_txns
from qif_converter.match_helpers import make_txn_views
from .excel_row import ExcelRow
from .excel_txn_group import ExcelTxnGroup
from .qif_item_key import QIFItemKey
#from .qif_txn_view import QIFTxnView
from .data_model import QTransaction, QSplit


class MatchSession:
    """
    Holds QIF txns + Excel groups (by TxnID), does auto-matching with one-to-one
    constraint at the TRANSACTION level, supports manual match/unmatch, and
    applies updates to QIF (overwriting splits from Excel).
    """

    def __init__(
        self,
        txns: List[Dict[str, Any]],
        excel_rows: List[ExcelRow] | None = None,
        excel_groups: List[ExcelTxnGroup] | None = None,
    ):
        """
        Session can operate in two modes:
          - legacy row-mode (excel_rows) — kept for compatibility if needed
          - group-mode  (excel_groups), where each group represents a single TxnID
            with rows (splits) and a total_amount used for matching.
        Matching is performed at the TRANSACTION level (not split).
        """
        self.txns = txns
        #self.txn_views = _flatten_qif_txns(txns)
        self.txn_views = make_txn_views(txns)

        # Prefer group-mode if provided; fall back to rows (legacy)
        self.excel_rows = excel_rows or []
        self.excel_groups = excel_groups or []

        # Group-mode (TxnID-aggregated) mappings:
        #   key   = QIFItemKey (txn identity)
        #   value = int (index into self.excel_groups)
        self.qif_to_excel_group: Dict[QIFItemKey, int] = {}
        self.excel_group_to_qif: Dict[int, QIFItemKey] = {}

        # Legacy row-mode mappings (kept for back-compat):
        #   key   = QIFItemKey
        #   value = int (row index into self.excel_rows)
        self.qif_to_excel: Dict[QIFItemKey, int] = {}
        self.excel_to_qif: Dict[int, QIFItemKey] = {}

    # --- Auto match

    def auto_match(self) -> None:
        """
        Transaction-level matching (strongly preferred):
          - Compare QIF txn.amount to Excel group.total_amount
          - Date within ±3 days (compare QIF txn.date to group.date)
          - Lowest date delta wins (0 beats 1,2,3)
          - One-to-one on both sides
        Falls back to legacy row-mode if no groups were provided.
        """
        # ---- Group-mode (preferred) ----
        if self.excel_groups:
            candidates: List[Tuple[int, int, int]] = []
            # Index groups by total for quick lookup
            by_total: Dict[Decimal, List[int]] = {}
            for gi, g in enumerate(self.excel_groups):
                by_total.setdefault(g.total_amount, []).append(gi)

            for ti, tv in enumerate(self.txn_views):
                # Normalize tv.amount to Decimal
                try:
                    txn_amt = _to_decimal(tv.amount)
                except Exception:
                    txn_amt = _to_decimal(str(tv.amount))

                for gi in by_total.get(txn_amt, []):
                    g = self.excel_groups[gi]
                    cost = _candidate_cost(tv.date, g.date)
                    if cost is None:
                        continue
                    candidates.append((cost, ti, gi))

            candidates.sort(key=lambda t: (t[0], t[1], t[2]))  # cost, then deterministic

            used_txn: set[int] = set()
            used_grp: set[int] = set()
            for cost, ti, gi in candidates:
                if ti in used_txn or gi in used_grp:
                    continue
                qkey = self.txn_views[ti].key  # <-- QIFItemKey
                self.qif_to_excel_group[qkey] = gi
                self.excel_group_to_qif[gi] = qkey
                used_txn.add(ti)
                used_grp.add(gi)

            print("DEBUG keys types:",
                  {type(k) for k in self.qif_to_excel_group.keys()},
                  {type(v) for v in self.qif_to_excel_group.values()})

            print("DEBUG sample mapping:", list(self.qif_to_excel_group.items())[:3])

            return

        # ---- Legacy row-mode fallback ----
        candidates: List[Tuple[int, int, int]] = []
        by_amount: Dict[Decimal, List[int]] = {}
        for ei, er in enumerate(self.excel_rows):
            by_amount.setdefault(er.amount, []).append(ei)

        for ti, tv in enumerate(self.txn_views):
            try:
                txn_amt = _to_decimal(tv.amount)
            except Exception:
                txn_amt = _to_decimal(str(tv.amount))
            for ei in by_amount.get(txn_amt, []):
                er = self.excel_rows[ei]
                cost = _candidate_cost(tv.date, er.date)
                if cost is None:
                    continue
                candidates.append((cost, ti, ei))

        candidates.sort(key=lambda t: (t[0], t[1], t[2]))

        used_txn: set[int] = set()
        used_row: set[int] = set()
        for cost, ti, ei in candidates:
            if ti in used_txn or ei in used_row:
                continue
            key = self.txn_views[ti].key  # <-- QIFItemKey
            self.qif_to_excel[key] = ei
            self.excel_to_qif[ei] = key
            used_txn.add(ti)
            used_row.add(ei)

    # --- Introspection

    def matched_pairs(self) -> List[Tuple[TxnLegacyView, ExcelTxnGroup | ExcelRow, int]]:
        """
        Return list of matched (QIFTxnView, ExcelTxnGroup|ExcelRow, date_cost).
        Group-mode first, legacy row-mode as fallback.
        """
        out: List[Tuple[TxnLegacyView, ExcelTxnGroup | ExcelRow, int]] = []

        # --- Group mode (ExcelTxnGroup) ---
        if self.excel_groups:
            for q in self.txn_views:
                gi = self.qif_to_excel_group.get(q.key)
                if gi is None:
                    continue
                grp = self.excel_groups[gi]
                cost = _candidate_cost(q.date, grp.date)
                out.append((q, grp, 0 if cost is None else cost))
            return out

        # --- Legacy row mode (ExcelRow) ---
        for q in self.txn_views:
            ei = self.qif_to_excel.get(q.key)
            if ei is None:
                continue
            er = self.excel_rows[ei]
            cost = _candidate_cost(q.date, er.date)
            out.append((q, er, 0 if cost is None else cost))
        return out

    def unmatched_qif(self) -> List[TxnLegacyView]:
        if self.excel_groups:
            matched_keys = set(self.qif_to_excel_group.keys())
            return [tv for tv in self.txn_views if tv.key not in matched_keys]
        # Legacy row-mode
        matched_ti = {k.txn_index for k in self.qif_to_excel.keys()}
        return [tv for ti, tv in enumerate(self.txn_views) if ti not in matched_ti]

    def unmatched_excel(self) -> List[ExcelTxnGroup | ExcelRow]:
        if self.excel_groups:
            return [g for gi, g in enumerate(self.excel_groups) if gi not in self.excel_group_to_qif]
        # Legacy row-mode
        return [er for ei, er in enumerate(self.excel_rows) if ei not in self.excel_to_qif]

    # --- Reasons / manual matching

    def nonmatch_reason(self, q: TxnLegacyView, target) -> str:
        """
        Explain why q (QIF txn) didn't match 'target', which is either:
          - ExcelTxnGroup (group mode), or
          - ExcelRow (legacy row mode)
        """
        # Group mode
        if self.excel_groups is not None and isinstance(target, ExcelTxnGroup):
            grp: ExcelTxnGroup = target
            if q.amount != grp.total_amount:
                return f"Total amount differs (QIF {q.amount} vs Excel group {grp.total_amount})."
            c = _candidate_cost(q.date, grp.date)
            if c is None:
                return f"Date outside ±3 days (QIF {q.date.isoformat()} vs Excel group {grp.date.isoformat()})."

            gi = self._group_index(grp)
            if gi >= 0:
                # Is this QIF txn already matched to a different group?
                gi_for_q = self.qif_to_excel_group.get(q.key)
                if gi_for_q is not None and gi_for_q != gi:
                    return "QIF txn is already matched."
                # Is this Excel group already matched to a different QIF txn?
                q_for_g = self.excel_group_to_qif.get(gi)
                if q_for_g is not None and q_for_g != q.key:
                    return "Excel group is already matched."

            if c > 0:
                return f"Auto-match preferred a closer date (day diff = {c})."
            return "Auto-match selected another candidate."

        # Legacy row mode
        if isinstance(target, ExcelRow):
            er: ExcelRow = target
            if q.amount != er.amount:
                return f"Amount differs (QIF {q.amount} vs Excel {er.amount})."
            c = _candidate_cost(q.date, er.date)
            if c is None:
                return f"Date outside ±3 days (QIF {q.date.isoformat()} vs Excel {er.date.isoformat()})."
            if q.key in self.qif_to_excel and self.qif_to_excel[q.key] != er.idx:
                return "QIF item is already matched."
            if er.idx in self.excel_to_qif and self.excel_to_qif[er.idx] != q.key:
                return "Excel row is already matched."
            if c > 0:
                return f"Auto-match preferred a closer date (day diff = {c})."
            return "Auto-match selected another candidate."

        return "Unsupported target type."

    def manual_match(self, qkey: QIFItemKey, excel_idx: int) -> Tuple[bool, str]:
        """
        Force a match between a QIF txn and an Excel item:
          - In group mode, excel_idx is an index into self.excel_groups
          - In legacy mode, excel_idx is a row index into self.excel_rows
        """
        # Find the QIF view
        try:
            q = next(x for x in self.txn_views if x.key == qkey)
        except StopIteration:
            return False, "QIF item key not found."

        # --- Group mode ---
        if self.excel_groups:
            if excel_idx < 0 or excel_idx >= len(self.excel_groups):
                return False, "Excel group index out of range."
            grp = self.excel_groups[excel_idx]

            # Normalize q.amount to Decimal for comparison
            try:
                q_amt = _to_decimal(q.amount)
            except Exception:
                q_amt = _to_decimal(str(q.amount))

            if q_amt != grp.total_amount:
                return False, f"Total amount differs (QIF {q_amt} vs Excel group {grp.total_amount})."
            if _candidate_cost(q.date, grp.date) is None:
                return False, f"Date outside ±3 days (QIF {q.date.isoformat()} vs Excel group {grp.date.isoformat()})."

            # Unhook existing links
            self._unmatch_qkey_group(qkey)
            self._unmatch_group_index(excel_idx)

            # Link by (QIFItemKey -> group_index)
            self.qif_to_excel_group[qkey] = excel_idx
            self.excel_group_to_qif[excel_idx] = qkey
            return True, "Matched."

        # --- Legacy row mode ---
        if excel_idx < 0 or excel_idx >= len(self.excel_rows):
            return False, "Excel index out of range."
        er = self.excel_rows[excel_idx]

        try:
            q_amt = _to_decimal(q.amount)
        except Exception:
            q_amt = _to_decimal(str(q.amount))

        if q_amt != er.amount:
            return False, f"Amount differs (QIF {q_amt} vs Excel {er.amount})."
        if _candidate_cost(q.date, er.date) is None:
            return False, f"Date outside ±3 days (QIF {q.date.isoformat()} vs Excel {er.date.isoformat()})."

        # Unhook and relink in legacy maps
        self._unmatch_qkey(qkey)
        self._unmatch_excel(excel_idx)

        self.qif_to_excel[qkey] = excel_idx
        self.excel_to_qif[excel_idx] = qkey
        return True, "Matched."

    def manual_unmatch(self, qkey: Optional[QIFItemKey] = None, excel_idx: Optional[int] = None) -> bool:
        """
        Remove an existing match (by either key).
        """
        if qkey is not None:
            return self._unmatch_qkey(qkey)
        if excel_idx is not None:
            return self._unmatch_excel(excel_idx)
        return False

    def _unmatch_qkey_group(self, qkey: QIFItemKey) -> bool:
        gi = self.qif_to_excel_group.pop(qkey, None)
        if gi is None:
            return False
        self.excel_group_to_qif.pop(gi, None)
        return True

    def _unmatch_group_index(self, gi: int) -> bool:
        qkey = self.excel_group_to_qif.pop(gi, None)
        if qkey is None:
            return False
        self.qif_to_excel_group.pop(qkey, None)
        return True

    # ----- THIS IS ONLY FOR ROW MODE. WILL DELETE SOON -----
    def _unmatch_qkey(self, qkey: QIFItemKey) -> bool:
        # Group mode first
        if self.excel_groups is not None:
            grp = self.qif_to_excel_group.pop(qkey, None)
            if grp is None:
                return False
            self.excel_group_to_qif.pop(grp, None)
            return True

        # Legacy
        ei = self.qif_to_excel.pop(qkey, None)
        if ei is None:
            return False
        self.excel_to_qif.pop(ei, None)
        return True

    # ----- THIS IS ONLY FOR ROW MODE. WILL DELETE SOON -----
    def _unmatch_excel(self, excel_idx: int) -> bool:
        # Group mode: excel_idx refers to group index (dict is keyed by int)
        if self.excel_groups is not None:
            qkey = self.excel_group_to_qif.pop(excel_idx, None)
            if qkey is None:
                return False
            self.qif_to_excel_group.pop(qkey, None)
            return True

        # Legacy row mode
        qkey = self.excel_to_qif.pop(excel_idx, None)
        if qkey is None:
            return False
        self.qif_to_excel.pop(qkey, None)
        return True

    def _group_index(self, g: ExcelTxnGroup) -> int:
        # helper to find group index (identity by object; fallback by gid/date/total)
        try:
            return self.excel_groups.index(g)
        except ValueError:
            for i, gg in enumerate(self.excel_groups):
                if gg.gid == g.gid and gg.date == g.date and gg.total_amount == g.total_amount:
                    return i
            return -1

    # --- Applying updates ----------------------------------------------------

    def apply_updates(self) -> None:
        """
        For each matched pair (QIF txn ↔ Excel group), overwrite the txn's splits
        with the group's row details. Transactions are matched at the transaction
        level; split details come exclusively from Excel rows.

        - category  ← Excel row category
        - memo      ← Excel row item
        - amount    ← Excel row amount (Decimal)
        """
        for q_view, grp_or_row, _cost in self.matched_pairs():
            # In group-mode we get an ExcelTxnGroup; in legacy mode it's an ExcelRow.
            # The split-aware behavior only applies to groups. Legacy mode leaves splits untouched.
            if hasattr(grp_or_row, "rows"):  # ExcelTxnGroup
                grp = grp_or_row
                txn = self.txns[q_view.key.txn_index]

                # Build new splits from the group's rows, replacing any existing splits.
                new_splits = []
                for r in grp.rows:
                    new_splits.append({
                        "category": r.category,
                        "memo": r.item,
                        "amount": r.amount,  # already a Decimal
                    })

                self._set_splits_from_group(q_view.key.txn_index, grp)
                #txn["splits"] = new_splits

    def _set_splits_from_group(self, txn_idx: int, group) -> None:
        base = self.txns[txn_idx]

        # Excel rows → new split objects/dicts
        new_splits_model = [
            QSplit(category=r.category or "", memo=r.item or "", amount=r.amount, tag="")
            for r in group.rows
        ]
        new_splits_dicts = [
            {"category": r.category or "", "memo": r.item or "", "amount": r.amount}
            for r in group.rows
        ]

        if isinstance(base, QTransaction):
            # replace model splits
            base.splits = new_splits_model
            # optional: clear top-level category when splits exist
            base.category = ""
        else:
            # legacy dict path
            base["splits"] = new_splits_dicts
            base["category"] = ""