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
