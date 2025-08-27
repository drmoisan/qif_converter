# qif_converter/gui_viewers/csv_profiles.py
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any
import csv

WIN_HEADERS = ["Date","Payee","FI Payee","Amount","Debit/Credit","Category","Account","Tag","Memo","Chknum"]
MAC_HEADERS = ["Date","Description","Original Description","Amount","Transaction Type","Category","Account Name","Labels","Notes"]

def write_csv_quicken_windows(txns: List[Dict[str, Any]], out_path: Path):
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(WIN_HEADERS)
        for t in txns:
            amt = str(t.get("amount","")).strip()
            memo = str(t.get("memo","")).replace("\r","").replace("\n"," ")
            row = [
                t.get("date",""),
                t.get("payee",""),
                "",
                amt,
                "",
                t.get("category",""),
                t.get("account",""),
                "",
                memo,
                t.get("checknum",""),
            ]
            w.writerow(row)

def write_csv_quicken_mac(txns: List[Dict[str, Any]], out_path: Path):
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(MAC_HEADERS)
        for t in txns:
            amt_str = str(t.get("amount","")).strip()
            try:
                val = float(amt_str.replace(",",""))
            except Exception:
                val = 0.0
            txn_type = "credit" if val >= 0 else "debit"
            amt_abs = f"{abs(val):.2f}"
            notes = str(t.get("memo","")).replace("\r","").replace("\n"," ")
            row = [
                t.get("date",""),
                t.get("payee",""),
                t.get("payee",""),
                amt_abs,
                txn_type,
                t.get("category",""),
                t.get("account",""),
                "",
                notes,
            ]
            w.writerow(row)
