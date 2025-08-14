#!/usr/bin/env python3
"""
GUI runner for qif_converter.qif_to_csv

Features:
- Select input QIF and output file
- Output: CSV (flat or exploded) or QIF
- Multiple payee filters, combine ANY/ALL
- Match types: contains, exact, startswith, endswith, glob, regex
- Case-sensitive toggle
- Date range filter (mm/dd'yy, mm/dd/yyyy, yyyy-mm-dd)
- CSV profiles: default, quicken-windows, quicken-mac (handled here if backend lacks profiles)
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import csv
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    from qif_converter import qif_to_csv as mod
except Exception:
    raise

_DATE_FORMATS = ["%m/%d'%y", "%m/%d/%Y", "%Y-%m-%d"]

def parse_date_maybe(s: str) -> Optional[datetime]:
    s = s.strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    s2 = s.replace("’", "'").replace("`", "'")
    if s2 != s:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(s2, fmt)
            except ValueError:
                continue
    return None

def qif_date_to_datetime(qif_date: str) -> Optional[datetime]:
    if not qif_date:
        return None
    return parse_date_maybe(qif_date)

def filter_date_range(txns: List[Dict[str, Any]], start_str: str, end_str: str) -> List[Dict[str, Any]]:
    start = parse_date_maybe(start_str) if start_str else None
    end = parse_date_maybe(end_str) if end_str else None
    if not start and not end:
        return txns
    out = []
    for t in txns:
        d = qif_date_to_datetime(str(t.get("date", "")).strip())
        if d is None:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue
        out.append(t)
    return out

def local_filter_by_payee(txns, query, mode="contains", case_sensitive=False):
    if mode != "regex" and mode != "glob" and not case_sensitive:
        query_cmp = str(query).lower()
    else:
        query_cmp = str(query)
    out = []
    for t in txns:
        payee = t.get("payee", "")
        payee_cmp = payee if (case_sensitive or mode in ("regex","glob")) else payee.lower()
        match = False
        if mode == "contains":
            match = query_cmp in payee_cmp
        elif mode == "exact":
            match = payee_cmp == query_cmp
        elif mode == "startswith":
            match = payee_cmp.startswith(query_cmp)
        elif mode == "endswith":
            match = payee_cmp.endswith(query_cmp)
        elif mode == "glob":
            pattern = "^" + re.escape(query).replace(r"\*", ".*").replace(r"\?", ".") + "$"
            flags = 0 if case_sensitive else re.IGNORECASE
            match = re.search(pattern, payee, flags) is not None
        elif mode == "regex":
            flags = 0 if case_sensitive else re.IGNORECASE
            match = re.search(query, payee, flags) is not None
        if match:
            out.append(t)
    return out

def apply_multi_payee_filters(txns, queries: List[str], mode: str, case_sensitive: bool, combine: str):
    if not queries:
        return txns
    queries = [q.strip() for q in queries if q.strip()]
    if not queries:
        return txns

    def run_filter(tlist, q):
        if hasattr(mod, "filter_by_payee"):
            return [t for t in tlist if t in mod.filter_by_payee(tlist, q, mode=mode, case_sensitive=case_sensitive)]
        else:
            return local_filter_by_payee(tlist, q, mode=mode, case_sensitive=case_sensitive)

    if combine == "any":
        seen = set()
        out = []
        for q in queries:
            subset = run_filter(txns, q)
            for t in subset:
                tid = id(t)
                if tid not in seen:
                    seen.add(tid)
                    out.append(t)
        return out
    else:
        cur = list(txns)
        for q in queries:
            cur = run_filter(cur, q)
        return cur

WIN_HEADERS = ["Date","Payee","FI Payee","Amount","Debit/Credit","Category","Account","Tag","Memo","Chknum"]
MAC_HEADERS = ["Date","Description","Original Description","Amount","Transaction Type","Category","Account Name","Labels","Notes"]

def write_csv_quicken_windows(txns: List[Dict[str, Any]], out_path: Path):
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(WIN_HEADERS)
        for t in txns:
            amt = str(t.get("amount","")).strip()
            memo = str(t.get("memo","")).replace("\\r","").replace("\\n"," ")
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
            notes = str(t.get("memo","")).replace("\\r","").replace("\\n"," ")
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

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QIF → CSV/QIF Converter")
        self.geometry("820x640")
        self.minsize(820, 640)
        self._build_ui()

    def _build_ui(self):
        pad = {'padx': 8, 'pady': 6}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True)

        io_frame = ttk.LabelFrame(frm, text="Files")
        io_frame.pack(fill="x", **pad)

        self.in_path = tk.StringVar()
        self.out_path = tk.StringVar()

        ttk.Label(io_frame, text="Input QIF:").grid(row=0, column=0, sticky="w")
        in_entry = ttk.Entry(io_frame, textvariable=self.in_path, width=80)
        in_entry.grid(row=0, column=1, sticky="we", padx=5)
        ttk.Button(io_frame, text="Browse…", command=self._browse_in).grid(row=0, column=2)

        ttk.Label(io_frame, text="Output File:").grid(row=1, column=0, sticky="w")
        out_entry = ttk.Entry(io_frame, textvariable=self.out_path, width=80)
        out_entry.grid(row=1, column=1, sticky="we", padx=5)
        ttk.Button(io_frame, text="Browse…", command=self._browse_out).grid(row=1, column=2)
        io_frame.columnconfigure(1, weight=1)

        opt = ttk.LabelFrame(frm, text="Options")
        opt.pack(fill="x", **pad)

        self.emit_var = tk.StringVar(value="csv")
        ttk.Label(opt, text="Emit:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(opt, text="CSV", variable=self.emit_var, value="csv").grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(opt, text="QIF", variable=self.emit_var, value="qif").grid(row=0, column=2, sticky="w")

        # Auto-switch output extension when Emit changes
        def _on_emit_change(*_):
            self._update_output_extension()
        self.emit_var.trace_add("write", _on_emit_change)


        self.csv_profile = tk.StringVar(value="default")
        ttk.Label(opt, text="CSV Profile:").grid(row=0, column=3, sticky="e")
        ttk.Combobox(opt, textvariable=self.csv_profile, values=["default","quicken-windows","quicken-mac"], width=18, state="readonly").grid(row=0, column=4, sticky="w", padx=5)
        self.explode_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="Explode splits (CSV only)", variable=self.explode_var).grid(row=0, column=5, sticky="w")

        flt = ttk.LabelFrame(frm, text="Filters")
        flt.pack(fill="x", **pad)

        ttk.Label(flt, text="Payee filters (comma or newline separated):").grid(row=0, column=0, sticky="w")
        self.payees_text = tk.Text(flt, height=4)
        self.payees_text.grid(row=1, column=0, columnspan=6, sticky="we", padx=5, pady=4)
        flt.columnconfigure(5, weight=1)

        ttk.Label(flt, text="Match:").grid(row=2, column=0, sticky="e")
        self.match_var = tk.StringVar(value="contains")
        ttk.Combobox(flt, textvariable=self.match_var, values=["contains","exact","startswith","endswith","glob","regex"], width=16, state="readonly").grid(row=2, column=1, sticky="w")
        self.case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(flt, text="Case sensitive", variable=self.case_var).grid(row=2, column=2, sticky="w")

        ttk.Label(flt, text="Combine:").grid(row=2, column=3, sticky="e")
        self.combine_var = tk.StringVar(value="any")
        ttk.Combobox(flt, textvariable=self.combine_var, values=["any","all"], width=10, state="readonly").grid(row=2, column=4, sticky="w")

        ttk.Label(flt, text="Date from:").grid(row=3, column=0, sticky="e")
        self.date_from = tk.StringVar()
        ttk.Entry(flt, textvariable=self.date_from, width=16).grid(row=3, column=1, sticky="w")
        ttk.Label(flt, text="Date to:").grid(row=3, column=2, sticky="e")
        self.date_to = tk.StringVar()
        ttk.Entry(flt, textvariable=self.date_to, width=16).grid(row=3, column=3, sticky="w")
        ttk.Label(flt, text="(Formats: mm/dd'yy, mm/dd/yyyy, yyyy-mm-dd)").grid(row=3, column=4, columnspan=2, sticky="w")

        runf = ttk.Frame(frm)
        runf.pack(fill="x", **pad)
        ttk.Button(runf, text="Run Conversion", command=self._run).pack(side="left")
        ttk.Button(runf, text="Quit", command=self.destroy).pack(side="right")

        logf = ttk.LabelFrame(frm, text="Log")
        logf.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(logf, height=12)
        self.log.pack(fill="both", expand=True, padx=5, pady=5)

    def _browse_in(self):
        path = filedialog.askopenfilename(title="Select input QIF", filetypes=[("QIF files","*.qif"),("All files","*.*")])
        if path:
            self.in_path.set(path)

    def _browse_out(self):
        emit = self.emit_var.get()
        if emit == "qif":
            default_ext = ".qif"
            ft = [("QIF files","*.qif"),("All files","*.*")]
        else:
            default_ext = ".csv"
            ft = [("CSV files","*.csv"),("All files","*.*")]
        path = filedialog.asksaveasfilename(title="Select output file", defaultextension=default_ext, filetypes=ft)
        if path:
            self.out_path.set(path)

    def logln(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.update_idletasks()

    def _parse_payee_filters(self) -> List[str]:
        raw = self.payees_text.get("1.0", "end").strip()
        if not raw:
            return []
        parts = []
        for chunk in raw.replace(",", "\n").splitlines():
            s = chunk.strip()
            if s:
                parts.append(s)
        return parts

    def _run(self):
        try:
            in_path = Path(self.in_path.get().strip())
            out_path = Path(self.out_path.get().strip())
            if not in_path or not in_path.exists():
                messagebox.showerror("Error", "Please select a valid input QIF file.")
                return
            if not out_path:
                messagebox.showerror("Error", "Please choose an output file.")
                return
            if Path(out_path).exists():
                if not messagebox.askyesno(
                        "Confirm Overwrite",
                        f"The file already exists:\n\n{out_path}\n\nDo you want to overwrite it?"
                ):
                    return  # Cancel run if user says No

            emit = self.emit_var.get()
            csv_profile = self.csv_profile.get()
            explode = self.explode_var.get()
            match_mode = self.match_var.get()
            case_sensitive = self.case_var.get()
            combine = self.combine_var.get()
            payees = self._parse_payee_filters()
            df = self.date_from.get().strip()
            dt = self.date_to.get().strip()

            self.log.delete("1.0", "end")
            self.logln("Parsing QIF…")
            txns = mod.parse_qif(in_path)

            if df or dt:
                self.logln(f"Filtering by date range: from={df or 'MIN'} to={dt or 'MAX'}")
                txns = filter_date_range(txns, df, dt)

            if payees:
                self.logln(f"Applying payee filters: {payees} (mode={match_mode}, case={'yes' if case_sensitive else 'no'}, combine={combine})")
                txns = apply_multi_payee_filters(txns, payees, match_mode, case_sensitive, combine)

            self.logln(f"Transactions after filters: {len(txns)}")

            if emit == "qif":
                self.logln(f"Writing QIF → {out_path}")
                mod.write_qif(txns, out_path)
                messagebox.showinfo("Done", f"Filtered QIF written:\n{out_path}")
                return

            if csv_profile == "quicken-windows":
                self.logln(f"Writing CSV (Quicken Windows profile) → {out_path}")
                write_csv_quicken_windows(txns, out_path)
            elif csv_profile == "quicken-mac":
                self.logln(f"Writing CSV (Quicken Mac/Mint profile) → {out_path}")
                write_csv_quicken_mac(txns, out_path)
            else:
                if explode:
                    self.logln(f"Writing CSV (exploded splits) → {out_path}")
                    mod.write_csv_exploded(txns, out_path)
                else:
                    self.logln(f"Writing CSV (flattened) → {out_path}")
                    mod.write_csv_flat(txns, out_path)

            messagebox.showinfo("Done", f"CSV written:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.logln(f"ERROR: {e}")

    def _update_output_extension(self):
        desired_ext = ".csv" if self.emit_var.get() == "csv" else ".qif"
        cur = self.out_path.get().strip()
        if not cur:
            # If nothing selected yet, suggest based on input file
            in_cur = self.in_path.get().strip()
            if in_cur:
                p_in = Path(in_cur)
                suggested = str(p_in.with_suffix(desired_ext))
                self.out_path.set(suggested)
            return

        p = Path(cur)
        cur_ext = p.suffix.lower()

        # Only auto-adjust if extension is blank or one of the known ones
        if cur_ext in ("", ".csv", ".qif"):
            if cur_ext:
                new_path = str(p.with_suffix(desired_ext))
            else:
                new_path = str(p) + desired_ext
            self.out_path.set(new_path)


if __name__ == "__main__":
    app = App()
    app.mainloop()
