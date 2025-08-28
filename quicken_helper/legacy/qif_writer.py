#!/usr/bin/env python3
"""
QIF → CSV converter (enhanced)

Features:
- Robust QIF parser (whitespace-tolerant, supports splits & investments)
- Filtering:
  * by payee (single or multiple), modes: contains/exact/startswith/endswith/regex/glob
  * by date range (--date-from, --date-to)
- Writers:
  * Generic CSV (flat or exploded)
  * Quicken Windows CSV profile
  * Quicken Mac (Mint) CSV profile
  * QIF writer for round-trips
- CLI with combinations of the above
"""
from __future__ import annotations

import csv
import fnmatch
import os
import re
from pathlib import Path
from typing import IO, Any, Dict, Iterable, List, Optional, TextIO, Union

from quicken_helper.data_model import ITransaction
from quicken_helper.utilities.core_util import parse_date_string

# ------------------------ Filtering helpers ------------------------


def _match_one(payee: str, query: str, mode: str, case_sensitive: bool) -> bool:
    if mode == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.search(query, payee, flags) is not None

    if not case_sensitive:
        payee_cmp = payee.lower()
        query_cmp = query.lower()
    else:
        payee_cmp = payee
        query_cmp = query

    if mode == "contains":
        return query_cmp in payee_cmp
    if mode == "exact":
        return payee_cmp == query_cmp
    if mode == "startswith":
        return payee_cmp.startswith(query_cmp)
    if mode == "endswith":
        return payee_cmp.endswith(query_cmp)
    if mode == "glob":
        if case_sensitive:
            return fnmatch.fnmatchcase(payee, query)
        else:
            return fnmatch.fnmatch(payee_cmp, query_cmp)
    raise ValueError(f"Unknown match mode: {mode}")


def filter_by_payee(
    txns: List[Dict[str, Any]], query: str, mode="contains", case_sensitive=False
) -> List[Dict[str, Any]]:
    """Filter transactions by a single payee query."""
    return [
        t for t in txns if _match_one(t.get("payee", ""), query, mode, case_sensitive)
    ]


def filter_by_payees(
    txns: List[Dict[str, Any]],
    queries: Iterable[str],
    mode="contains",
    case_sensitive=False,
    combine: str = "any",
) -> List[Dict[str, Any]]:
    """
    Filter transactions by multiple payee queries.
    combine: 'any' (OR) or 'all' (AND)
    """
    qlist = list(queries)
    out = []
    for t in txns:
        payee = t.get("payee", "")
        matches = [_match_one(payee, q, mode, case_sensitive) for q in qlist]
        ok = any(matches) if combine == "any" else all(matches)
        if ok:
            out.append(t)
    return out


# Date parsing and filtering


def filter_by_date_range(
    txns: List[Dict[str, Any]], date_from: Optional[str], date_to: Optional[str]
) -> List[Dict[str, Any]]:
    """Filter by date range. Dates inclusive. Accepts mm/dd'yy, mm/dd/yyyy, or yyyy-mm-dd strings."""
    df = parse_date_string(date_from) if date_from else None
    dt = parse_date_string(date_to) if date_to else None
    out: List[Dict[str, Any]] = []
    for t in txns:
        ds = t.get("date", "")
        d = parse_date_string(ds)
        if not d:
            continue
        if df and d < df:
            continue
        if dt and d > dt:
            continue
        out.append(t)
    return out


# --------------------- Writer Helpers ---------------------


def _emit_multiline_field(out, tag: str, value: str) -> None:
    """
    Write a multi-line QIF field so that EACH line is prefixed with the tag.
    Example:
      MLine 1
      MLine 2
    """
    if value is None:
        return
    for line in str(value).splitlines():
        out.write(f"{tag}{line}\n")


def _open_for_write(
    path: Path, *, binary: bool = False, newline: Optional[str] = ""
) -> IO:
    """
    Small indirection so tests can monkeypatch in-memory I/O.
    Default behavior simply delegates to Path.open. Tests can replace
    this function to support 'MEM://' or other schemes.
    """
    mode = "wb" if binary else "w"
    kwargs = {} if binary else {"encoding": "utf-8", "newline": newline}
    return open(path, mode, **kwargs)


# ------------------------ Writers ------------------------


def write_csv_flat(txns, out_path: Path, newline: str = "") -> None:
    """
    Write a flat CSV - One row per transaction; splits flattened into pipe-delimited columns.
    Uses _open_for_write so tests can redirect to an in-memory stream.
    """
    import csv

    fieldnames = [
        "account",
        "type",
        "date",
        "amount",
        "payee",
        "memo",
        "category",
        "transfer_account",
        "checknum",
        "cleared",
        "address",
        "action",
        "security",
        "quantity",
        "price",
        "commission",
        "split_count",
        "split_category",
        "split_memo",
        "split_amount",
    ]

    with _open_for_write(out_path, binary=False, newline=newline) as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for t in txns:
            splits = t.get("splits", [])
            row = dict(t)
            row["split_count"] = str(len(splits))
            row["split_category"] = (
                " | ".join(s.get("category", "") for s in splits) if splits else ""
            )
            row["split_memo"] = (
                " | ".join(s.get("memo", "") for s in splits) if splits else ""
            )
            row["split_amount"] = (
                " | ".join(s.get("amount", "") for s in splits) if splits else ""
            )
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def write_csv_exploded(txns, out_path: Path, newline: str = "") -> None:
    """
    Write an exploded CSV (one row per split; transactions without splits
    still produce a single row). Uses _open_for_write for testable I/O.
    """
    import csv

    fieldnames = [
        "account",
        "type",
        "date",
        "amount",
        "payee",
        "memo",
        "category",
        "transfer_account",
        "checknum",
        "cleared",
        "address",
        "action",
        "security",
        "quantity",
        "price",
        "commission",
        "split_category",
        "split_memo",
        "split_amount",
    ]

    with _open_for_write(out_path, binary=False, newline=newline) as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for t in txns:
            splits = t.get("splits", [])
            base = {k: t.get(k, "") for k in fieldnames if not k.startswith("split_")}
            if splits:
                for s in splits:
                    row = dict(base)
                    row["split_category"] = s.get("category", "")
                    row["split_memo"] = s.get("memo", "")
                    row["split_amount"] = s.get("amount", "")
                    writer.writerow(row)
            else:
                writer.writerow(base)


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except Exception:
        return None


def write_csv_quicken_windows(
    txns: List[Dict[str, Any]], out_path: Path, newline: str = ""
) -> None:
    """
    Quicken Windows CSV header order:
    Date, Payee, FI Payee, Amount, Debit/Credit, Category, Account, Tag, Memo, Chknum
    """
    fieldnames = [
        "Date",
        "Payee",
        "FI Payee",
        "Amount",
        "Debit/Credit",
        "Category",
        "Account",
        "Tag",
        "Memo",
        "Chknum",
    ]
    with _open_for_write(out_path, binary=False, newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\r\n")  # Windows

        w.writeheader()
        for t in txns:
            amt = t.get("amount", "")
            row = {
                "Date": t.get("date", ""),
                "Payee": t.get("payee", ""),
                "FI Payee": "",
                "Amount": amt,
                "Debit/Credit": "",  # prefer signed Amount
                "Category": t.get("category", ""),
                "Account": t.get("account", ""),
                "Tag": "",
                "Memo": t.get("memo", ""),
                "Chknum": t.get("checknum", ""),
            }
            w.writerow(row)


def write_csv_quicken_mac(
    txns: List[Dict[str, Any]], out_path: Path, newline: str = ""
) -> None:
    """
    Quicken Mac (Mint) CSV:
    Date, Description, Original Description, Amount, Transaction Type, Category, Account Name, Labels, Notes
    Amount must be positive; direction in Transaction Type: debit/credit
    """
    fieldnames = [
        "Date",
        "Description",
        "Original Description",
        "Amount",
        "Transaction Type",
        "Category",
        "Account Name",
        "Labels",
        "Notes",
    ]
    with _open_for_write(out_path, binary=False, newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        for t in txns:
            amt_s = t.get("amount", "")
            amt = _safe_float(amt_s) or 0.0
            # Determine debit/credit by sign; if 0 or missing, default to debit with amount as given
            txn_type = "credit" if amt > 0 else "debit"
            amt_abs = abs(amt)
            row = {
                "Date": t.get("date", ""),
                "Description": t.get("payee", ""),
                "Original Description": "",
                "Amount": f"{amt_abs:.2f}" if amt_s != "" else "",
                "Transaction Type": txn_type,
                "Category": t.get("category", ""),
                "Account Name": t.get("account", ""),
                "Labels": "",
                "Notes": t.get("memo", ""),
            }
            w.writerow(row)


# ... keep your existing imports and helpers ...


def write_qif(
    txns, out: Union[str, os.PathLike, TextIO], encoding: str = "utf-8"
) -> None:
    """
    Write QIF to either:
      - a filesystem path (str/PathLike), or
      - a text stream with .write() (e.g., io.StringIO)
    """
    # If it's already a file-like object, write to it directly
    if hasattr(out, "write") and callable(getattr(out, "write")):
        _write_qif_to_stream(txns, out)  # type: ignore[arg-type]
        return

    # Otherwise treat as a path
    with open(out, "w", encoding=encoding, newline="") as fp:
        _write_qif_to_stream(txns, fp)


# def write_qif(txns, out: Union[str, os.PathLike, TextIO], encoding: str = "utf-8"):
#     # detect model and use proper emitter if desired
#     if txns and isinstance(txns[0], QifTxnLike):
#         # build a QifFile and emit using model’s emitters
#         _iter_as_legacy(txns)  # convert to legacy dicts for now
#     else:
#         # current legacy dict writing path
#         _iter_as_legacy(txns)


def _write_qif_to_stream(txns: list[dict], fp: TextIO) -> None:
    """
    Core QIF writer that emits to a text stream.

    Behavior:
      - Emits an !Account block whenever the transaction's 'account' changes.
        Includes:
          * N<account name>
          * T<account type> (e.g., TBank) derived from txn["type"] or default 'Bank'
      - Emits the proper !Type:<TypeName> header when the transaction 'type' changes.
      - Writes address lines correctly by splitting a single string on newlines,
        or iterating a pre-split sequence of lines.
      - Preserves existing behavior for memo: a single 'M' line may contain embedded
        newlines if the memo is multi-line.
    """
    current_account: str | None = None
    current_type: str | None = None

    for r in txns:
        if isinstance(r, ITransaction):
            # Convert model to dict if initially
            # Will eventually replace with emitter methods on the model
            r = r.to_dict()
        # Derive txn_type early since we may need it for the !Account block.
        legacy_write(current_account, current_type, fp, r)


def legacy_write(current_account, current_type, fp, r):
    txn_type = (r.get("type") or "Bank").strip()
    # 1) Account block (when account changes and account is non-empty)
    acct = (r.get("account") or "").strip()
    if acct and acct != current_account:
        fp.write("!Account\n")
        fp.write(f"N{acct}\n")
        # Include account type in the account list block (what the test expects)
        fp.write(f"T{txn_type}\n")
        fp.write("^\n")
        current_account = acct
        # Reset the current_type so we re-emit the !Type header after switching accounts
        current_type = None
    # 2) Type header (when type changes; default to Bank)
    if txn_type != current_type:
        fp.write(f"!Type:{txn_type}\n")
        current_type = txn_type
    # 3) Transaction body
    d = r.get("date", "")
    if d:
        fp.write(f"D{d}\n")
    amt = r.get("amount", "")
    if amt != "":
        fp.write(f"T{amt}\n")
    payee = r.get("payee", "")
    if payee:
        fp.write(f"P{payee}\n")
    memo = r.get("memo", "")
    if memo:
        _emit_multiline_field(fp, "M", memo)
    cat = r.get("category", "")
    if cat:
        fp.write(f"L{cat}\n")
    # Optional scalar fields
    checknum = r.get("checknum", "")
    if checknum:
        fp.write(f"N{checknum}\n")
    cleared = r.get("cleared", "")
    if cleared:
        fp.write(f"C{cleared}\n")
    # Address can be a single string (splitlines) or a sequence of lines
    addr = r.get("address", "")
    if isinstance(addr, str):
        addr_lines = [line for line in addr.splitlines() if line != ""]
    elif addr:
        try:
            addr_lines = list(addr)
        except TypeError:
            addr_lines = []
    else:
        addr_lines = []
    for line in addr_lines:
        fp.write(f"A{line}\n")
    # Investment fields (pass-through if present)
    action = r.get("action", "")
    if action:
        fp.write(f"N{action}\n")
    security = r.get("security", "")
    if security:
        fp.write(f"Y{security}\n")
    quantity = r.get("quantity", "")
    if quantity != "":
        fp.write(f"Q{quantity}\n")
    price = r.get("price", "")
    if price != "":
        fp.write(f"I{price}\n")
    commission = r.get("commission", "")
    if commission != "":
        fp.write(f"O{commission}\n")
    # 4) Splits
    for s in r.get("splits") or []:
        sc = s.get("category", "")
        if sc:
            fp.write(f"S{sc}\n")
        sm = s.get("memo", "")
        if sm:
            fp.write(f"E{sm}\n")
        sa = s.get("amount", "")
        if sa != "":
            fp.write(f"${sa}\n")
    # 5) Record terminator
    fp.write("^\n")
