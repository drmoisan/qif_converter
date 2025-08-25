from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from .qif_item_key import QIFItemKey
from .qif_txn_view import QIFTxnView


_DATE_FORMATS = ["%m/%d'%y", "%m/%d/%Y", "%Y-%m-%d"]

def _parse_date(s: str) -> date:
    s = (s or "").strip().replace("’", "'").replace("`", "'")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    # Fallback: allow ISO-like "YYYY/MM/DD"
    try:
        return datetime.strptime(s, "%Y/%m/%d").date()
    except ValueError:
        raise ValueError(f"Unrecognized date: {s!r}")

def _qif_date_to_date(s: str) -> date:
    return _parse_date(s)

def _to_decimal(s: str | float | int | Decimal) -> Decimal:
    if isinstance(s, Decimal):
        return s
    if isinstance(s, (int, float)):
        return Decimal(str(s))
    txt = str(s or "").replace(",", "").replace("$", "").strip()
    if txt in {"", "+", "-"}:
        raise InvalidOperation(f"Empty amount: {s!r}")
    return Decimal(txt)

def _flatten_qif_txns(txns: List[Dict[str, Any]]) -> List[QIFTxnView]:
    """
        Build a stable, transaction-level view of QIF data for matching.

        This helper converts a list of raw QIF transaction dicts into a list of
        ``QIFTxnView`` instances that are used by the matching layer. Each view:

          • corresponds to exactly one *transaction* (never to an individual split)
          • has a deterministic key ``QIFItemKey(txn_index=i, split_index=None)``
          • normalizes the date to ``datetime.date`` using
            :func:`qif_converter.core_util.parse_date_string`
          • normalizes the amount to ``Decimal`` (accepting ``str`` or ``Decimal`` input)

        Why transaction-level only?
            Matching against Excel is intentionally performed at the *transaction* level,
            regardless of whether the QIF transaction contains splits. This allows us to
            (a) find the correct transaction by total amount and date, and (b) later
            overwrite its splits from the Excel side if a match is found.

        Input expectations
            Each ``tx`` in ``txns`` is a dict that may contain (subset is fine):
            ``"date"``, ``"amount"``, ``"payee"``, ``"memo"``, ``"category"``,
            and optionally ``"splits"`` (a list of split dicts). Values may be strings
            or already-normalized types.

        Normalization rules
            • **Date** — Parsed via :func:`parse_date_string`. If the date cannot be
              parsed, the transaction is *skipped* (it would be unusable for date-window
              matching).
            • **Amount** — Parsed to ``Decimal``. If the top-level ``"amount"`` is
              missing or falsy and valid splits are present, the amount is computed as
              the sum of split amounts (fallback).
            • **Strings** — ``payee``, ``memo``, and ``category`` are coerced to
              strings with ``""`` as a default.

        Purity & ordering
            The function does **not** mutate the input list or any of its dicts.
            Output ordering mirrors the input order: the ``i``-th input transaction
            yields a view with ``QIFItemKey.txn_index == i``.

        Returns
            list[QIFTxnView]: One view per valid input transaction. Invalid entries
            (e.g., non-parsable dates) are ignored.

        Raises
            This function is lenient and does not raise for individual record issues.
            Problematic records are simply skipped as described above.

        Examples
            >>> txns = [
            ...   {"date": "2025-08-01", "amount": "-50.00", "payee": "Store A",
            ...    "splits": [{"category": "Food", "amount": "-30.00"},
            ...               {"category": "Household", "amount": "-20.00"}]},
            ...   {"date": "2025/08/02", "amount": "-20", "payee": "Store B"},
            ... ]
            >>> views = _flatten_qif_txns(txns)
            >>> views[0].key.txn_index, views[0].amount, views[0].payee
            (0, Decimal('-50.00'), 'Store A')

        See also
            • :class:`qif_converter.qif_txn_view.QIFTxnView`
            • :class:`qif_converter.qif_item_key.QIFItemKey`
            • :class:`qif_converter.excel_txn_group.ExcelTxnGroup`
            • :func:`qif_converter.core_util.parse_date_string`
        """
    out: List[QIFTxnView] = []
    for ti, t in enumerate(txns):
        # Defensive: skip any record that doesn't look like a transaction
        # (must have a parseable date; amount may be on txn or splits)
        try:
            t_date = _qif_date_to_date(t.get("date", ""))
        except Exception:
            # Not a transaction (e.g., category list line sneaked in) → skip
            continue

        payee = t.get("payee", "")
        memo = t.get("memo", "")
        cat = t.get("category", "")
        splits = t.get("splits") or []
        if splits:
            for si, s in enumerate(splits):
                try:
                    amt = _to_decimal(s.get("amount", "0"))
                except Exception:
                    # If split amount isn't parseable, skip this split
                    continue
                out.append(QIFTxnView(
                    key=QIFItemKey(txn_index=ti, split_index=si),
                    date=t_date,
                    amount=amt,
                    payee=payee,
                    memo=s.get("memo", ""),
                    category=s.get("category", ""),
                ))
        else:
            # No splits → use the txn amount
            try:
                amt = _to_decimal(t.get("amount", "0"))
            except Exception:
                # Can't parse txn amount → skip this txn
                continue
            out.append(QIFTxnView(
                key=QIFItemKey(txn_index=ti, split_index=None),
                date=t_date,
                amount=amt,
                payee=payee,
                memo=memo,
                category=cat,
            ))
    return out

def _candidate_cost(qif_date: date, excel_date: date) -> Optional[int]:
    """Return day-distance cost if within ±3 days, else None (not eligible). Lower is better."""
    delta = abs((qif_date - excel_date).days)
    if delta > 3:
        return None
    return delta  # 0 preferred, then 1,2,3
