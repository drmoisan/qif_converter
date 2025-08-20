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
from pathlib import Path
import csv
import argparse
import re
from typing import List, Dict, Any, Optional, Iterable, TextIO, Union
from collections import defaultdict
import fnmatch

from decimal import Decimal
import io
import os


from qif_converter.utilities.core_util import parse_date_string

QIF_SECTION_PREFIX = "!Type:"
QIF_ACCOUNT_HEADER = "!Account"
TRANSFER_RE = re.compile(r"^\[(.+?)\]$")  # e.g., [Savings]


# ------------------------ Parsing helpers ------------------------

def parse_qif(path: Path, encoding: str = "utf-8") -> List[Dict[str, Any]]:
    """Parse a QIF file into a list of transaction dicts."""
    txns: List[Dict[str, Any]] = []
    current_type: Optional[str] = None
    current_account: Optional[str] = None
    in_account_block = False
    account_props: Dict[str, str] = {}

    def finalize_tx(rec: Dict[str, Any]) -> None:
        if not rec:
            return
        rec.setdefault("account", current_account)
        rec.setdefault("type", current_type)
        if not rec.get("transfer_account"):
            cat = (rec.get("category") or "").strip()
            m = TRANSFER_RE.match(cat)
            rec["transfer_account"] = m.group(1) if m else ""
        addr_lines = rec.pop("_address_lines", None)
        rec["address"] = "\n".join(addr_lines) if addr_lines else ""
        for k in ("amount", "quantity", "price", "commission"):
            rec.setdefault(k, "")
        rec.setdefault("splits", [])
        txns.append(rec)

    with path.open("r", encoding=encoding, errors="replace") as f:
        rec: Dict[str, Any] = {}
        pending_split: Optional[Dict[str, str]] = None
        for raw_line in f:
            line = raw_line.rstrip("\r\n").lstrip()
            if not line:
                continue
            if line.startswith(QIF_SECTION_PREFIX):
                if rec:
                    finalize_tx(rec); rec = {}; pending_split = None
                current_type = line[len(QIF_SECTION_PREFIX):].strip()
                in_account_block = False
                continue
            if line.startswith(QIF_ACCOUNT_HEADER):
                if rec:
                    finalize_tx(rec); rec = {}; pending_split = None
                in_account_block = True
                account_props = {}
                continue
            if line.strip() == "^":
                if in_account_block:
                    current_account = account_props.get("N") or account_props.get("name") or current_account
                    in_account_block = False; account_props = {}
                else:
                    if pending_split is not None:
                        rec.setdefault("splits", []).append(pending_split)
                        pending_split = None
                    finalize_tx(rec); rec = {}
                continue
            if in_account_block:
                code = line[:1]; value = line[1:].rstrip()
                account_props[code] = value
                continue

            code = line[:1]
            value = line[1:].rstrip()
            if code == "D":
                rec["date"] = value
            elif code == "T":
                rec["amount"] = value
            elif code == "P":
                rec["payee"] = value
            elif code == "M":
                prior = rec.get("memo", "")
                rec["memo"] = (prior + "\n" + value).strip() if prior else value
            elif code == "L":
                rec["category"] = value
                m = TRANSFER_RE.match(value.strip())
                rec["transfer_account"] = m.group(1) if m else rec.get("transfer_account", "")
            elif code == "N":
                if current_type and str(current_type).lower().startswith("invst"):
                    rec["action"] = value
                else:
                    rec["checknum"] = value
            elif code == "C":
                rec["cleared"] = value
            elif code == "A":
                value = value.replace("\\n", "\n")
                rec.setdefault("_address_lines", []).append(value)
            elif code == "Y":
                rec["security"] = value
            elif code == "Q":
                rec["quantity"] = value
            elif code == "I":
                rec["price"] = value
            elif code == "O":
                rec["commission"] = value
            elif code == "S":
                if pending_split is not None:
                    rec.setdefault("splits", []).append(pending_split)
                pending_split = {"category": value, "memo": "", "amount": ""}
            elif code == "E":
                if pending_split is None:
                    pending_split = {"category": "", "memo": value, "amount": ""}
                else:
                    pending_split["memo"] = value
            elif code == "$":
                if pending_split is None:
                    pending_split = {"category": "", "memo": "", "amount": value}
                else:
                    pending_split["amount"] = value
            else:
                pass
        if rec:
            finalize_tx(rec)
    return txns


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


def filter_by_payee(txns: List[Dict[str, Any]], query: str, mode="contains", case_sensitive=False) -> List[Dict[str, Any]]:
    """Filter transactions by a single payee query."""
    return [t for t in txns if _match_one(t.get("payee", ""), query, mode, case_sensitive)]


def filter_by_payees(
    txns: List[Dict[str, Any]], queries: Iterable[str], mode="contains", case_sensitive=False, combine: str = "any"
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

def filter_by_date_range(txns: List[Dict[str, Any]], date_from: Optional[str], date_to: Optional[str]) -> List[Dict[str, Any]]:
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


# ------------------------ Writers ------------------------

def write_csv_flat(txns: List[Dict[str, Any]], out_path: Path, newline: str = "") -> None:
    """One row per transaction; splits flattened into pipe-delimited columns."""
    fieldnames = [
        "account","type","date","amount","payee","memo","category","transfer_account",
        "checknum","cleared","address","action","security","quantity","price","commission",
        "split_count","split_categories","split_memos","split_amounts",
    ]
    with out_path.open("w", encoding="utf-8", newline=newline) as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for t in txns:
            splits = t.get("splits", [])
            row = dict(t)
            row["split_count"] = str(len(splits))
            row["split_categories"] = " | ".join(s.get("category", "") for s in splits) if splits else ""
            row["split_memos"] = " | ".join(s.get("memo", "") for s in splits) if splits else ""
            row["split_amounts"] = " | ".join(s.get("amount", "") for s in splits) if splits else ""
            w.writerow({k: row.get(k, "") for k in fieldnames})


def write_csv_exploded(txns: List[Dict[str, Any]], out_path: Path, newline: str = "") -> None:
    """One row per split; non-split transactions produce a single row with empty split_* fields."""
    fieldnames = [
        "account","type","date","amount","payee","memo","category","transfer_account",
        "checknum","cleared","address","action","security","quantity","price","commission",
        "split_category","split_memo","split_amount",
    ]
    with out_path.open("w", encoding="utf-8", newline=newline) as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for t in txns:
            splits = t.get("splits", [])
            base = {k: t.get(k, "") for k in fieldnames if not k.startswith("split_")}
            if splits:
                for s in splits:
                    row = dict(base)
                    row["split_category"] = s.get("category", "")
                    row["split_memo"] = s.get("memo", "")
                    row["split_amount"] = s.get("amount", "")
                    w.writerow(row)
            else:
                w.writerow(base)


def _safe_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except Exception:
        return None


def write_csv_quicken_windows(txns: List[Dict[str, Any]], out_path: Path, newline: str = "") -> None:
    """
    Quicken Windows CSV header order:
    Date, Payee, FI Payee, Amount, Debit/Credit, Category, Account, Tag, Memo, Chknum
    """
    fieldnames = ["Date","Payee","FI Payee","Amount","Debit/Credit","Category","Account","Tag","Memo","Chknum"]
    with out_path.open("w", encoding="utf-8", newline=newline) as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for t in txns:
            amt = t.get("amount","")
            row = {
                "Date": t.get("date",""),
                "Payee": t.get("payee",""),
                "FI Payee": "",
                "Amount": amt,
                "Debit/Credit": "",  # prefer signed Amount
                "Category": t.get("category",""),
                "Account": t.get("account",""),
                "Tag": "",
                "Memo": t.get("memo",""),
                "Chknum": t.get("checknum",""),
            }
            w.writerow(row)


def write_csv_quicken_mac(txns: List[Dict[str, Any]], out_path: Path, newline: str = "") -> None:
    """
    Quicken Mac (Mint) CSV:
    Date, Description, Original Description, Amount, Transaction Type, Category, Account Name, Labels, Notes
    Amount must be positive; direction in Transaction Type: debit/credit
    """
    fieldnames = ["Date","Description","Original Description","Amount","Transaction Type","Category","Account Name","Labels","Notes"]
    with out_path.open("w", encoding="utf-8", newline=newline) as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for t in txns:
            amt_s = t.get("amount","")
            amt = _safe_float(amt_s) or 0.0
            # Determine debit/credit by sign; if 0 or missing, default to debit with amount as given
            txn_type = "credit" if amt > 0 else "debit"
            amt_abs = abs(amt)
            row = {
                "Date": t.get("date",""),
                "Description": t.get("payee",""),
                "Original Description": "",
                "Amount": f"{amt_abs:.2f}" if amt_s != "" else "",
                "Transaction Type": txn_type,
                "Category": t.get("category",""),
                "Account Name": t.get("account",""),
                "Labels": "",
                "Notes": t.get("memo",""),
            }
            w.writerow(row)



# ... keep your existing imports and helpers ...

def write_qif(txns: list[dict], out: Union[str, os.PathLike, TextIO], encoding: str = "utf-8") -> None:
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


def _write_qif_to_stream(txns: list[dict], fp: TextIO) -> None:
    """
    The core writer that emits to a text stream.
    Keep all your existing QIF formatting logic here.
    """
    # Example skeleton; keep your actual field order/formatting rules unchanged.
    fp.write("!Type:Bank\n")
    for r in txns:
        # date line (D), main amount (T), payee (P), memo (M), category (L), address lines (A)
        d = r.get("date", "")
        if d:
            fp.write(f"D{d}\n")
        amt = r.get("amount", "")
        if amt != "":
            fp.write(f"T{amt}\n")  # main txn amount uses 'T'
        payee = r.get("payee", "")
        if payee:
            fp.write(f"P{payee}\n")
        memo = r.get("memo", "")
        if memo:
            fp.write(f"M{memo}\n")
        cat = r.get("category", "")
        if cat:
            fp.write(f"L{cat}\n")
        for a in r.get("address", []) or []:
            fp.write(f"A{a}\n")

        # splits (if you support them): each split line uses $ for amount, S for category, E for memo
        for s in r.get("splits", []) or []:
            sc = s.get("category", "")
            if sc:
                fp.write(f"S{sc}\n")
            sm = s.get("memo", "")
            if sm:
                fp.write(f"E{sm}\n")
            sa = s.get("amount", "")
            if sa != "":
                fp.write(f"${sa}\n")

        fp.write("^\n")



# ------------------------ CLI ------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Convert QIF (Quicken Interchange Format) to CSV or filtered QIF.")
    ap.add_argument("input", type=Path, help="Path to input .qif file")
    ap.add_argument("output", type=Path, help="Path to output file (.csv or .qif)")
    ap.add_argument("--explode-splits", action="store_true",
                    help="Generic CSV only: one row per split (default: flatten splits)")
    ap.add_argument("--encoding", default="utf-8",
                    help="Text encoding of input QIF (default: utf-8). Try cp1252 for old exports.")

    # Payee filtering
    ap.add_argument("--filter-payee", action="append",
                    help="Filter by payee; may be given multiple times for multi-payee filtering")
    ap.add_argument("--combine", choices=["any", "all"], default="any",
                    help="Combine multiple --filter-payee values with OR (any) or AND (all)")
    ap.add_argument("--match", choices=["contains", "exact", "startswith", "endswith", "regex", "glob"],
                    default="contains", help="Payee match mode (default: contains)")
    ap.add_argument("--case-sensitive", action="store_true", help="Make payee match case sensitive")

    # Date range filtering
    ap.add_argument("--date-from", help="Filter: earliest date to include (mm/dd'yy, mm/dd/yyyy, or yyyy-mm-dd)")
    ap.add_argument("--date-to", help="Filter: latest date to include (mm/dd'yy, mm/dd/yyyy, or yyyy-mm-dd)")

    # Output format
    ap.add_argument("--emit", choices=["csv", "qif"], default="csv", help="Output format: csv (default) or qif")
    ap.add_argument("--csv-profile", choices=["generic","quicken-windows","quicken-mac"], default="generic",
                    help="CSV layout profile when --emit csv")

    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input QIF not found: {args.input}")
    if not args.input.is_file():
        raise SystemExit(f"Input path is not a file: {args.input}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    txns = parse_qif(args.input, encoding=args.encoding)

    # Apply filtering
    if args.filter_payee:
        if len(args.filter_payee) == 1:
            txns = filter_by_payee(txns, args.filter_payee[0], mode=args.match, case_sensitive=args.case_sensitive)
        else:
            txns = filter_by_payees(txns, args.filter_payee, mode=args.match,
                                    case_sensitive=args.case_sensitive, combine=args.combine)
    if args.date_from or args.date_to:
        txns = filter_by_date_range(txns, args.date_from, args.date_to)

    # Emit
    if args.emit == "qif":
        write_qif(txns, args.output)
    else:
        profile = args.csv_profile
        if profile == "generic":
            if args.explode_splits:
                write_csv_exploded(txns, args.output)
            else:
                write_csv_flat(txns, args.output)
        elif profile == "quicken-windows":
            write_csv_quicken_windows(txns, args.output)
        elif profile == "quicken-mac":
            write_csv_quicken_mac(txns, args.output)
        else:
            raise SystemExit(f"Unknown CSV profile: {profile}")


if __name__ == "__main__":
    main()
