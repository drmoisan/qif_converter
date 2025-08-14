#!/usr/bin/env python3
"""
QIF → CSV converter (with filtering and QIF writer)
- Tolerant of leading spaces and mixed newlines
- Extracts transfers from L[...] into transfer_account
- Joins multi-line address (A) with real newlines
- Handles splits (S/E/$) and investment fields (N/Y/Q/I/O)
- Filtering by payee (contains/exact/startswith/endswith/regex)
- Can emit CSV (flat or exploded) or filtered QIF
"""
from pathlib import Path
import csv
import argparse
import re
from typing import List, Dict, Any, Optional
from collections import defaultdict

QIF_SECTION_PREFIX = "!Type:"
QIF_ACCOUNT_HEADER = "!Account"
TRANSFER_RE = re.compile(r"^\[(.+?)\]$")  # e.g., [Savings]


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


def filter_by_payee(txns, query, mode="contains", case_sensitive=False):
    """Return a filtered list of transactions whose payee matches `query`."""
    if mode != "regex" and not case_sensitive:
        query_cmp = str(query).lower()
    else:
        query_cmp = str(query)
    out = []
    for t in txns:
        payee = t.get("payee", "")
        payee_cmp = payee if (case_sensitive or mode == "regex") else payee.lower()
        match = False
        if mode == "contains":
            match = query_cmp in payee_cmp
        elif mode == "exact":
            match = payee_cmp == query_cmp
        elif mode == "startswith":
            match = payee_cmp.startswith(query_cmp)
        elif mode == "endswith":
            match = payee_cmp.endswith(query_cmp)
        elif mode == "regex":
            flags = 0 if case_sensitive else re.IGNORECASE
            match = re.search(query, payee, flags) is not None
        if match:
            out.append(t)
    return out


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


def write_qif(txns: List[Dict[str, Any]], out_path: Path) -> None:
    """Write a QIF file from parsed transactions, grouped by (account, type)."""
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        groups = defaultdict(list)
        for t in txns:
            groups[(t.get("account", ""), t.get("type", ""))].append(t)

        for (account, typ), recs in groups.items():
            if account:
                f.write("!Account\n")
                f.write(f"N{account}\n")
                if typ:
                    f.write(f"T{typ}\n")
                f.write("^\n")
            if typ:
                f.write(f"!Type:{typ}\n")
            for r in recs:
                if r.get("date"):
                    f.write(f"D{r['date']}\n")
                if r.get("amount"):
                    f.write(f"T{r['amount']}\n")
                if r.get("payee"):
                    f.write(f"P{r['payee']}\n")
                if r.get("memo"):
                    for line in str(r['memo']).split("\n"):
                        f.write(f"M{line}\n")
                if r.get("category"):
                    f.write(f"L{r['category']}\n")
                if r.get("checknum"):
                    f.write(f"N{r['checknum']}\n")
                if r.get("cleared"):
                    f.write(f"C{r['cleared']}\n")
                if r.get("address"):
                    for line in str(r['address']).split("\n"):
                        f.write(f"A{line}\n")
                for s in r.get("splits", []):
                    f.write(f"S{s.get('category','')}\n")
                    if s.get("memo"):
                        f.write(f"E{s['memo']}\n")
                    if s.get("amount"):
                        f.write(f"${s['amount']}\n")
                if r.get("action"):
                    f.write(f"N{r['action']}\n")
                if r.get("security"):
                    f.write(f"Y{r['security']}\n")
                if r.get("quantity"):
                    f.write(f"Q{r['quantity']}\n")
                if r.get("price"):
                    f.write(f"I{r['price']}\n")
                if r.get("commission"):
                    f.write(f"O{r['commission']}\n")
                f.write("^\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert QIF (Quicken Interchange Format) to CSV or filtered QIF.")
    ap.add_argument("input", type=Path, help="Path to input .qif file")
    ap.add_argument("output", type=Path, help="Path to output file (.csv or .qif)")
    ap.add_argument("--explode-splits", action="store_true",
                    help="CSV only: one row per split (default: flatten splits across columns)")
    ap.add_argument("--encoding", default="utf-8",
                    help="Text encoding of input QIF (default: utf-8). Try cp1252 for old exports.")
    ap.add_argument("--filter-payee", help="Filter transactions by payee name")
    ap.add_argument("--match", choices=["contains", "exact", "startswith", "endswith", "regex"],
                    default="contains", help="Payee match mode (default: contains)")
    ap.add_argument("--case-sensitive", action="store_true", help="Make payee match case sensitive")
    ap.add_argument("--emit", choices=["csv", "qif"], default="csv", help="Output format: csv (default) or qif")
    args = ap.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input QIF not found: {args.input}")
    if not args.input.is_file():
        raise SystemExit(f"Input path is not a file: {args.input}")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    txns = parse_qif(args.input, encoding=args.encoding)
    if args.filter_payee:
        txns = filter_by_payee(txns, args.filter_payee, mode=args.match, case_sensitive=args.case_sensitive)

    if args.emit == "qif":
        write_qif(txns, args.output)
    else:
        if args.explode_splits:
            write_csv_exploded(txns, args.output)
        else:
            write_csv_flat(txns, args.output)


if __name__ == "__main__":
    main()
