#!/usr/bin/env python3
"""
GUI runner for qif_converter:
Tab 1: QIF → CSV/QIF converter (filters, profiles, etc.)
Tab 2: Excel ↔ QIF merge (auto-match + manual matches + apply updates)

Requirements for Excel tab:
  pip install pandas openpyxl
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import csv
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

# --- project imports ---
from qif_converter import qif_to_csv as mod
from qif_converter import match_excel as mex
from qif_converter import qdx_probe  # NEW: library API for probe



# =========================
# Shared helpers
# =========================

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

def filter_date_range(txns: List[Dict[str, Any]], start_str: str, end_str: str) -> List[Dict[str, Any]]:
    def _d(s):
        d = parse_date_maybe(s)
        return d.date() if d else None

    start = _d(start_str) if start_str else None
    end = _d(end_str) if end_str else None
    if not start and not end:
        return txns
    out = []
    for t in txns:
        d = parse_date_maybe(str(t.get("date", "")).strip())
        if not d:
            continue
        if start and d.date() < start:
            continue
        if end and d.date() > end:
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
            # smart-case: uppercase in pattern implies case-sensitive when case_sensitive is False
            pattern = "^" + re.escape(query).replace(r"\*", ".*").replace(r"\?", ".") + "$"
            smart_case = case_sensitive or any(ch.isalpha() and ch.isupper() for ch in query)
            flags = 0 if smart_case else re.IGNORECASE
            match = re.search(pattern, payee, flags) is not None
        elif mode == "regex":
            flags = 0 if case_sensitive else re.IGNORECASE
            match = re.search(query, payee, flags) is not None
        if match:
            out.append(t)
    return out

def apply_multi_payee_filters(
    txns: List[Dict[str, Any]],
    queries: List[str],
    mode: str = "contains",
    case_sensitive: bool = False,
    combine: str = "any",
) -> List[Dict[str, Any]]:
    """
    Apply one or more payee filters across transactions.
    - combine="any": union of all matches
    - combine="all": intersection in sequence
    Uses mod.filter_by_payee if present; falls back to local_filter_by_payee.
    """
    queries = [q.strip() for q in (queries or []) if q and q.strip()]
    if not queries:
        return txns

    def run_filter(tlist, q):
        if hasattr(mod, "filter_by_payee"):
            return [t for t in tlist if t in mod.filter_by_payee(
                tlist, q, mode=mode, case_sensitive=case_sensitive
            )]
        return local_filter_by_payee(tlist, q, mode=mode, case_sensitive=case_sensitive)

    if combine == "any":
        seen, out = set(), []
        for q in queries:
            subset = run_filter(txns, q)
            for t in subset:
                tid = id(t)
                if tid not in seen:
                    seen.add(tid)
                    out.append(t)
        return out
    else:  # "all"
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


# =========================
# GUI
# =========================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("QIF Tools")
        self.geometry("980x720")
        self.minsize(920, 640)

        self._build_tabs()

    # ---------- Tabs ----------
    def _build_tabs(self):
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        self.tab_convert = ttk.Frame(self.nb)
        self.tab_merge = ttk.Frame(self.nb)
        self.tab_probe = ttk.Frame(self.nb)

        self.nb.add(self.tab_convert, text="Convert (QIF → CSV/QIF)")
        self.nb.add(self.tab_merge, text="Excel ↔ QIF Merge")
        self.nb.add(self.tab_probe, text="QDX Probe")

        self._build_convert_tab(self.tab_convert)
        self._build_merge_tab(self.tab_merge)
        self._build_probe_tab(self.tab_probe)

    # ---------- Convert tab (your existing features) ----------
    def _build_convert_tab(self, root):
        pad = {'padx': 8, 'pady': 6}

        # state vars
        self.in_path = tk.StringVar()
        self.out_path = tk.StringVar()
        self.emit_var = tk.StringVar(value="csv")
        self.csv_profile = tk.StringVar(value="default")
        self.explode_var = tk.BooleanVar(value=False)
        self.match_var = tk.StringVar(value="contains")
        self.case_var = tk.BooleanVar(value=False)
        self.combine_var = tk.StringVar(value="any")
        self.date_from = tk.StringVar()
        self.date_to = tk.StringVar()

        # Files
        io_frame = ttk.LabelFrame(root, text="Files")
        io_frame.pack(fill="x", **pad)

        ttk.Label(io_frame, text="Input QIF:").grid(row=0, column=0, sticky="w")
        ttk.Entry(io_frame, textvariable=self.in_path, width=90).grid(row=0, column=1, sticky="we", padx=5)
        ttk.Button(io_frame, text="Browse…", command=self._browse_in).grid(row=0, column=2)

        ttk.Label(io_frame, text="Output File:").grid(row=1, column=0, sticky="w")
        ttk.Entry(io_frame, textvariable=self.out_path, width=90).grid(row=1, column=1, sticky="we", padx=5)
        ttk.Button(io_frame, text="Browse…", command=self._browse_out).grid(row=1, column=2)

        io_frame.columnconfigure(1, weight=1)

        # Options
        opt = ttk.LabelFrame(root, text="Options")
        opt.pack(fill="x", **pad)

        ttk.Label(opt, text="Emit:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(opt, text="CSV", variable=self.emit_var, value="csv").grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(opt, text="QIF", variable=self.emit_var, value="qif").grid(row=0, column=2, sticky="w")

        ttk.Label(opt, text="CSV Profile:").grid(row=0, column=3, sticky="e")
        ttk.Combobox(opt, textvariable=self.csv_profile, values=["default","quicken-windows","quicken-mac"],
                     width=18, state="readonly").grid(row=0, column=4, sticky="w", padx=5)
        ttk.Checkbutton(opt, text="Explode splits (CSV only)", variable=self.explode_var).grid(row=0, column=5, sticky="w")

        # Filters
        flt = ttk.LabelFrame(root, text="Filters")
        flt.pack(fill="x", **pad)

        ttk.Label(flt, text="Payee filters (comma or newline separated):").grid(row=0, column=0, sticky="w")
        self.payees_text = tk.Text(flt, height=4)
        self.payees_text.grid(row=1, column=0, columnspan=6, sticky="we", padx=5, pady=4)
        flt.columnconfigure(5, weight=1)

        ttk.Label(flt, text="Match:").grid(row=2, column=0, sticky="e")
        ttk.Combobox(flt, textvariable=self.match_var,
                     values=["contains","exact","startswith","endswith","glob","regex"],
                     width=16, state="readonly").grid(row=2, column=1, sticky="w")
        ttk.Checkbutton(flt, text="Case sensitive", variable=self.case_var).grid(row=2, column=2, sticky="w")

        ttk.Label(flt, text="Combine:").grid(row=2, column=3, sticky="e")
        ttk.Combobox(flt, textvariable=self.combine_var, values=["any","all"],
                     width=10, state="readonly").grid(row=2, column=4, sticky="w")

        ttk.Label(flt, text="Date from:").grid(row=3, column=0, sticky="e")
        ttk.Entry(flt, textvariable=self.date_from, width=16).grid(row=3, column=1, sticky="w")
        ttk.Label(flt, text="Date to:").grid(row=3, column=2, sticky="e")
        ttk.Entry(flt, textvariable=self.date_to, width=16).grid(row=3, column=3, sticky="w")
        ttk.Label(flt, text="(Formats: mm/dd'yy, mm/dd/yyyy, yyyy-mm-dd)").grid(row=3, column=4, columnspan=2, sticky="w")

        # Run/Log
        runf = ttk.Frame(root)
        runf.pack(fill="x", **pad)
        ttk.Button(runf, text="Run Conversion", command=self._run).pack(side="left")
        ttk.Button(runf, text="Quit", command=self.destroy).pack(side="right")

        logf = ttk.LabelFrame(root, text="Log")
        logf.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(logf, height=12)
        self.log.pack(fill="both", expand=True, padx=5, pady=5)

        # Auto-change extension when Emit changes
        def _on_emit_change(*_):
            self._update_output_extension()
        self.emit_var.trace_add("write", _on_emit_change)

    # ---------- Merge tab (Excel ↔ QIF) ----------
    def _build_merge_tab(self, root):
        pad = {'padx': 8, 'pady': 6}

        # state
        self.m_qif_in = tk.StringVar()
        self.m_xlsx = tk.StringVar()
        self.m_qif_out = tk.StringVar()

        # session holder
        self._merge_session: Optional[mex.MatchSession] = None

        files = ttk.LabelFrame(root, text="Files")
        files.pack(fill="x", **pad)

        ttk.Label(files, text="Input QIF:").grid(row=0, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.m_qif_in, width=90).grid(row=0, column=1, sticky="we", padx=5)
        ttk.Button(files, text="Browse…", command=self._m_browse_qif).grid(row=0, column=2)

        ttk.Label(files, text="Excel (.xlsx):").grid(row=1, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.m_xlsx, width=90).grid(row=1, column=1, sticky="we", padx=5)
        ttk.Button(files, text="Browse…", command=self._m_browse_xlsx).grid(row=1, column=2)

        ttk.Label(files, text="Output QIF:").grid(row=2, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.m_qif_out, width=90).grid(row=2, column=1, sticky="we", padx=5)
        ttk.Button(files, text="Browse…", command=self._m_browse_out).grid(row=2, column=2)

        files.columnconfigure(1, weight=1)

        # Checkbox: output only matched items
        self.m_only_matched = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            root,
            text="Output Only Matched Items",
            variable=self.m_only_matched
        ).pack(anchor="w", padx=12, pady=(0, 6))

        # Actions
        actions = ttk.Frame(root)
        actions.pack(fill="x", **pad)
        ttk.Button(actions, text="Load + Auto-Match", command=self._m_load_and_auto).pack(side="left")
        ttk.Button(actions, text="Apply Updates & Save", command=self._m_apply_and_save).pack(side="right")
        ttk.Button(actions, text="Normalize Categories", command=self._m_normalize_categories).pack(side="left", padx=6)

        # Lists: matched / unmatched
        lists = ttk.Frame(root)
        lists.pack(fill="both", expand=True, **pad)

        # Left: Unmatched QIF
        left = ttk.LabelFrame(lists, text="Unmatched QIF items")
        left.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.lbx_unqif = tk.Listbox(left, exportselection=False)
        self.lbx_unqif.pack(fill="both", expand=True, padx=4, pady=4)

        # Middle: Matched pairs
        mid = ttk.LabelFrame(lists, text="Matched pairs")
        mid.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.lbx_pairs = tk.Listbox(mid, exportselection=False)
        self.lbx_pairs.pack(fill="both", expand=True, padx=4, pady=4)

        # Right: Unmatched Excel
        right = ttk.LabelFrame(lists, text="Unmatched Excel rows")
        right.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.lbx_unx = tk.Listbox(right, exportselection=False)
        self.lbx_unx.pack(fill="both", expand=True, padx=4, pady=4)

        # Footer: Manual match/unmatch + reason
        foot = ttk.Frame(root)
        foot.pack(fill="x", **pad)
        ttk.Button(foot, text="Match Selected →", command=self._m_manual_match).pack(side="left")
        ttk.Button(foot, text="Unmatch Selected", command=self._m_manual_unmatch).pack(side="left", padx=8)
        ttk.Button(foot, text="Why not matched?", command=self._m_why_not).pack(side="left", padx=8)

        self.txt_info = tk.Text(root, height=6)
        self.txt_info.pack(fill="x", padx=8, pady=6)


    # --------------- QDX Probe tab  --------------
    def _build_probe_tab(self, root):
        pad = {'padx': 8, 'pady': 6}

        self.p_qdx = tk.StringVar()
        self.p_qif = tk.StringVar()
        self.p_out = tk.StringVar()

        files = ttk.LabelFrame(root, text="Files")
        files.pack(fill="x", **pad)

        ttk.Label(files, text="QDX file:").grid(row=0, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.p_qdx, width=90).grid(row=0, column=1, sticky="we", padx=5)
        ttk.Button(files, text="Browse…", command=self._p_browse_qdx).grid(row=0, column=2)

        ttk.Label(files, text="(Optional) QIF:").grid(row=1, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.p_qif, width=90).grid(row=1, column=1, sticky="we", padx=5)
        ttk.Button(files, text="Browse…", command=self._p_browse_qif).grid(row=1, column=2)

        ttk.Label(files, text="Output (dir or .txt):").grid(row=2, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.p_out, width=90).grid(row=2, column=1, sticky="we", padx=5)
        ttk.Button(files, text="Browse…", command=self._p_browse_out).grid(row=2, column=2)

        files.columnconfigure(1, weight=1)

        actions = ttk.Frame(root)
        actions.pack(fill="x", **pad)
        ttk.Button(actions, text="Run Probe", command=self._p_run_probe).pack(side="left")

        # Results
        res = ttk.Frame(root)
        res.pack(fill="both", expand=True, **pad)

        left = ttk.LabelFrame(res, text="Report")
        left.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.p_report = tk.Text(left, wrap="word")
        self.p_report.pack(fill="both", expand=True, padx=4, pady=4)

        right = ttk.LabelFrame(res, text="Artifacts (decompressed blobs)")
        right.pack(side="left", fill="both", expand=True, padx=4, pady=4)

        # Listbox + buttons
        right_top = ttk.Frame(right)
        right_top.pack(fill="x", padx=4, pady=(4, 2))

        self.p_artifacts = tk.Listbox(right, exportselection=False)
        self.p_artifacts.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        btns = ttk.Frame(right)
        btns.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(btns, text="Preview", command=self._p_preview_artifact).pack(side="left")
        ttk.Button(btns, text="Open Containing Folder", command=self._p_open_artifact_folder).pack(side="left", padx=6)

        # Preview panel
        prev = ttk.LabelFrame(right, text="Artifact Preview")
        prev.pack(fill="both", expand=False, padx=4, pady=(0, 4))
        self.p_preview = tk.Text(prev, height=12, wrap="word")
        self.p_preview.pack(fill="both", expand=True, padx=4, pady=4)

        # Double-click to preview
        self.p_artifacts.bind("<Double-Button-1>", lambda e: self._p_preview_artifact())

    # =========================
    # Convert tab actions
    # =========================

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
        # in tests we stub update_idletasks()
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

    def _update_output_extension(self):
        desired_ext = ".csv" if self.emit_var.get() == "csv" else ".qif"
        cur = self.out_path.get().strip()
        if not cur:
            in_cur = self.in_path.get().strip()
            if in_cur:
                p_in = Path(in_cur)
                suggested = str(p_in.with_suffix(desired_ext))
                self.out_path.set(suggested)
            return
        p = Path(cur)
        cur_ext = p.suffix.lower()
        if cur_ext in ("", ".csv", ".qif"):
            new_path = str(p.with_suffix(desired_ext)) if cur_ext else str(p) + desired_ext
            self.out_path.set(new_path)

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
                self.logln(
                    f"Applying payee filters: {payees} "
                    f"(mode={match_mode}, case={'yes' if case_sensitive else 'no'}, combine={combine})"
                )
                txns = apply_multi_payee_filters(
                    txns, payees, mode=match_mode, case_sensitive=case_sensitive, combine=combine
                )

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

    # =========================
    # Merge tab actions
    # =========================

    def _m_browse_qif(self):
        p = filedialog.askopenfilename(title="Select input QIF", filetypes=[("QIF files","*.qif"),("All files","*.*")])
        if p:
            self.m_qif_in.set(p)
            # suggest output if blank
            if not self.m_qif_out.get().strip():
                self.m_qif_out.set(str(Path(p).with_name(Path(p).stem + "_updated.qif")))

    def _m_browse_xlsx(self):
        p = filedialog.askopenfilename(title="Select Excel workbook", filetypes=[("Excel files","*.xlsx"),("All files","*.*")])
        if p:
            self.m_xlsx.set(p)

    def _m_browse_out(self):
        p = filedialog.asksaveasfilename(title="Select output QIF", defaultextension=".qif",
                                         filetypes=[("QIF files","*.qif"),("All files","*.*")])
        if p:
            self.m_qif_out.set(p)

    def _m_load_and_auto(self):
        try:
            qif_in = Path(self.m_qif_in.get().strip())
            xlsx = Path(self.m_xlsx.get().strip())
            if not qif_in.exists():
                messagebox.showerror("Error", "Please choose a valid input QIF.")
                return
            if not xlsx.exists():
                messagebox.showerror("Error", "Please choose a valid Excel (.xlsx).")
                return

            txns = mod.parse_qif(qif_in)
            rows = mex.load_excel(xlsx)
            sess = mex.MatchSession(txns, rows)
            sess.auto_match()
            self._merge_session = sess
            self._m_refresh_lists()
            self._m_info(f"Loaded {len(txns)} QIF items (txn/splits) and {len(rows)} Excel rows.\n"
                         f"Matched pairs: {len(sess.matched_pairs())} | "
                         f"Unmatched QIF: {len(sess.unmatched_qif())} | "
                         f"Unmatched Excel: {len(sess.unmatched_excel())}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _m_refresh_lists(self):
        self.lbx_pairs.delete(0, "end")
        self.lbx_unqif.delete(0, "end")
        self.lbx_unx.delete(0, "end")
        s = self._merge_session
        if not s:
            return

        # Pairs
        for q, er, cost in s.matched_pairs():
            label = f"[d+{cost}] QIF#{q.key.txn_index}{('/S'+str(q.key.split_index)) if q.key.is_split() else ''} "\
                    f"{q.date.isoformat()} {q.amount} |→ Excel#{er.idx} {er.date.isoformat()} {er.amount} | {er.item}"
            self.lbx_pairs.insert("end", label)
        # Unmatched QIF
        for q in s.unmatched_qif():
            label = f"QIF#{q.key.txn_index}{('/S'+str(q.key.split_index)) if q.key.is_split() else ''} "\
                    f"{q.date.isoformat()} {q.amount} | {q.payee} | {q.memo or q.category}"
            self.lbx_unqif.insert("end", label)
        # Unmatched Excel
        for er in s.unmatched_excel():
            label = f"Excel#{er.idx} {er.date.isoformat()} {er.amount} | {er.item} | {er.category}"
            self.lbx_unx.insert("end", label)

    def _m_selected_unqif_key(self) -> Optional[mex.QIFItemKey]:
        s = self._merge_session
        if not s:
            return None
        sel = self.lbx_unqif.curselection()
        if not sel:
            return None
        q = s.unmatched_qif()[sel[0]]
        return q.key

    def _m_selected_unx_idx(self) -> Optional[int]:
        s = self._merge_session
        if not s:
            return None
        sel = self.lbx_unx.curselection()
        if not sel:
            return None
        er = s.unmatched_excel()[sel[0]]
        return er.idx

    def _m_manual_match(self):
        s = self._merge_session
        if not s:
            messagebox.showerror("Error", "No session loaded.")
            return
        qkey = self._m_selected_unqif_key()
        ei = self._m_selected_unx_idx()
        if qkey is None or ei is None:
            messagebox.showerror("Error", "Select one QIF item and one Excel row to match.")
            return
        ok, msg = s.manual_match(qkey, ei)
        self._m_info(("Matched." if ok else "Not matched.") + " " + msg)
        self._m_refresh_lists()

    def _m_manual_unmatch(self):
        s = self._merge_session
        if not s:
            return
        # Unmatch from selected pair if any; else unmatch from either list if selected
        sel = self.lbx_pairs.curselection()
        if sel:
            # parse back the indices from label (safer: find by order)
            # We unmatch by Excel index shown in order
            pairs = s.matched_pairs()
            qv, er, _ = pairs[sel[0]]
            s.manual_unmatch(qkey=qv.key)
            self._m_info("Unmatched selected pair.")
            self._m_refresh_lists()
            return

        qkey = self._m_selected_unqif_key()
        if qkey is not None and s.manual_unmatch(qkey=qkey):
            self._m_info("Unmatched QIF item.")
            self._m_refresh_lists()
            return
        ei = self._m_selected_unx_idx()
        if ei is not None and s.manual_unmatch(excel_idx=ei):
            self._m_info("Unmatched Excel row.")
            self._m_refresh_lists()
            return

        messagebox.showinfo("Info", "Nothing selected to unmatch.")

    def _m_why_not(self):
        s = self._merge_session
        if not s:
            return
        sel_q = self._m_selected_unqif_key()
        sel_e = self._m_selected_unx_idx()
        if sel_q is None or sel_e is None:
            messagebox.showinfo("Info", "Pick one unmatched QIF and one unmatched Excel to explain.")
            return
        q = next(x for x in s.unmatched_qif() if x.key == sel_q)
        er = next(x for x in s.unmatched_excel() if x.idx == sel_e)
        self._m_info(s.nonmatch_reason(q, er))

    def _m_apply_and_save(self):
        try:
            s = self._merge_session
            if not s:
                messagebox.showerror("Error", "No session loaded. Click 'Load + Auto-Match' first.")
                return
            qif_out = Path(self.m_qif_out.get().strip())
            if not qif_out:
                messagebox.showerror("Error", "Please choose an output QIF file.")
                return
            if qif_out.exists():
                if not messagebox.askyesno("Confirm Overwrite",
                                           f"Output QIF already exists:\n\n{qif_out}\n\nOverwrite?"):
                    return
            s.apply_updates()

            # Respect "Output Only Matched Items"
            if self.m_only_matched.get():
                txns_to_write = mex.build_matched_only_txns(s)
            else:
                txns_to_write = s.txns

            qif_out.parent.mkdir(parents=True, exist_ok=True)
            mod.write_qif(txns_to_write, qif_out)

            self._m_info(f"Updates applied. Wrote updated QIF:\n{qif_out}")
            messagebox.showinfo("Done", f"Updated QIF written:\n{qif_out}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _m_info(self, msg: str):
        self.txt_info.delete("1.0", "end")
        self.txt_info.insert("end", msg)

    def _m_normalize_categories(self):
        """Open a modal to normalize Excel categories to QIF categories."""
        try:
            qif_in = Path(self.m_qif_in.get().strip())
            xlsx = Path(self.m_xlsx.get().strip())
            if not qif_in.exists():
                messagebox.showerror("Error", "Please choose a valid input QIF.")
                return
            if not xlsx.exists():
                messagebox.showerror("Error", "Please choose a valid Excel (.xlsx).")
                return

            # Build session
            txns = mod.parse_qif(qif_in)
            qif_cats = mex.extract_qif_categories(txns)
            excel_cats = mex.extract_excel_categories(xlsx)
            sess = mex.CategoryMatchSession(qif_cats, excel_cats)

            # Modal window
            win = tk.Toplevel(self)
            win.title("Normalize Categories")
            win.geometry("900x520")
            win.transient(self)
            win.grab_set()

            pad = {'padx': 8, 'pady': 6}

            # Top buttons
            top = ttk.Frame(win)
            top.pack(fill="x", **pad)
            ttk.Button(top, text="Auto-Match", command=lambda: (sess.auto_match(), refresh())).pack(side="left")
            ttk.Button(top, text="Match Selected →", command=lambda: do_match()).pack(side="left", padx=6)
            ttk.Button(top, text="Unmatch Selected", command=lambda: do_unmatch()).pack(side="left", padx=6)

            # Lists
            lists = ttk.Frame(win)
            lists.pack(fill="both", expand=True, **pad)

            left = ttk.LabelFrame(lists, text="QIF Categories (canonical)")
            left.pack(side="left", fill="both", expand=True, padx=4, pady=4)
            lbx_qif = tk.Listbox(left, exportselection=False)
            lbx_qif.pack(fill="both", expand=True, padx=4, pady=4)

            mid = ttk.LabelFrame(lists, text="Matched pairs (Excel → QIF)")
            mid.pack(side="left", fill="both", expand=True, padx=4, pady=4)
            lbx_pairs = tk.Listbox(mid, exportselection=False)
            lbx_pairs.pack(fill="both", expand=True, padx=4, pady=4)

            right = ttk.LabelFrame(lists, text="Excel Categories (to normalize)")
            right.pack(side="left", fill="both", expand=True, padx=4, pady=4)
            lbx_excel = tk.Listbox(right, exportselection=False)
            lbx_excel.pack(fill="both", expand=True, padx=4, pady=4)

            # Bottom actions
            bot = ttk.Frame(win)
            bot.pack(fill="x", **pad)

            out_path_var = tk.StringVar(value=str(xlsx.with_name(xlsx.stem + "_normalized.xlsx")))
            ttk.Label(bot, text="Output Excel:").pack(side="left")
            ttk.Entry(bot, textvariable=out_path_var, width=60).pack(side="left", padx=6)
            ttk.Button(bot, text="Browse…", command=lambda: browse_out()).pack(side="left", padx=2)

            ttk.Button(bot, text="Apply & Save", command=lambda: apply_and_save()).pack(side="right")

            info = tk.Text(win, height=4, wrap="word")
            info.pack(fill="x", padx=8, pady=(0, 8))

            # Helpers for UI
            def refresh():
                lbx_qif.delete(0, "end")
                lbx_excel.delete(0, "end")
                lbx_pairs.delete(0, "end")
                uq, ue = sess.unmatched()
                for c in uq:
                    lbx_qif.insert("end", c)
                for c in ue:
                    lbx_excel.insert("end", c)
                for excel_name, qif_name in sorted(sess.mapping.items(), key=lambda kv: kv[0].lower()):
                    lbx_pairs.insert("end", f"{excel_name}  →  {qif_name}")

                info.delete("1.0", "end")
                info.insert("end", f"QIF categories: {len(sess.qif_cats)} | "
                                   f"Excel categories: {len(sess.excel_cats)} | "
                                   f"Matched: {len(sess.mapping)} | "
                                   f"Unmatched QIF: {len(uq)} | Unmatched Excel: {len(ue)}")

            def selected(lbx: tk.Listbox) -> Optional[str]:
                sel = lbx.curselection()
                if not sel:
                    return None
                return lbx.get(sel[0])

            def do_match():
                e = selected(lbx_excel)
                q = selected(lbx_qif)
                if not e or not q:
                    messagebox.showinfo("Info", "Select one Excel category and one QIF category to match.")
                    return
                ok, msg = sess.manual_match(e, q)
                if not ok:
                    messagebox.showerror("Error", msg)
                refresh()

            def do_unmatch():
                # unmatch by selecting a pair or an Excel category
                sel = lbx_pairs.curselection()
                if sel:
                    label = lbx_pairs.get(sel[0])
                    # label format: "Excel → QIF"
                    if "  →  " in label:
                        excel_name = label.split("  →  ", 1)[0]
                        sess.manual_unmatch(excel_name)
                        refresh()
                        return
                e = selected(lbx_excel)
                if e and sess.manual_unmatch(e):
                    refresh()
                    return
                messagebox.showinfo("Info", "Select a matched pair (middle list) or an Excel category to unmatch.")

            def browse_out():
                p = filedialog.asksaveasfilename(
                    title="Select normalized Excel output",
                    defaultextension=".xlsx",
                    filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")]
                )
                if p:
                    out_path_var.set(p)

            def apply_and_save():
                outp = Path(out_path_var.get().strip())
                if outp.exists():
                    if not messagebox.askyesno("Confirm Overwrite", f"{outp}\n\nOverwrite?"):
                        return
                try:
                    out_file = sess.apply_to_excel(xlsx, xlsx_out=outp)
                    messagebox.showinfo("Done", f"Normalized Excel written:\n{out_file}")
                    win.destroy()
                except Exception as e:
                    messagebox.showerror("Error", str(e))

            # initial population
            refresh()

        except Exception as e:
            messagebox.showerror("Error", str(e))

    # =========================
    # QDX Probe tab actions
    # =========================

    def _p_browse_qdx(self):
        p = filedialog.askopenfilename(title="Select QDX file",
                                       filetypes=[("QDX files", "*.qdx"), ("All files", "*.*")])
        if p: self.p_qdx.set(p)

    def _p_browse_qif(self):
        p = filedialog.askopenfilename(title="Select QIF (optional)",
                                       filetypes=[("QIF files", "*.qif"), ("All files", "*.*")])
        if p: self.p_qif.set(p)

    def _p_browse_out(self):
        # Let user choose either a directory or a .txt file; we’ll default to a directory
        p = filedialog.asksaveasfilename(title="Select output report (.txt) or choose a folder in the dialog",
                                         defaultextension=".txt",
                                         filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if p: self.p_out.set(p)

    def _p_run_probe(self):
        try:
            qdx = Path(self.p_qdx.get().strip())
            if not qdx.exists():
                messagebox.showerror("Error", "Please pick a valid QDX file.")
                return
            qif = Path(self.p_qif.get().strip()) if self.p_qif.get().strip() else None
            out = Path(self.p_out.get().strip()) if self.p_out.get().strip() else None

            report, artifacts = qdx_probe.run_probe(qdx, qif, out)

            # Show report
            self.p_report.delete("1.0", "end")
            self.p_report.insert("end", report)

            # List artifacts
            self.p_artifacts.delete(0, "end")
            for a in artifacts:
                self.p_artifacts.insert("end", str(a))

            messagebox.showinfo("QDX Probe", "Probe completed.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _p_selected_artifact(self) -> Optional[Path]:
        sel = self.p_artifacts.curselection()
        if not sel:
            return None
        try:
            return Path(self.p_artifacts.get(sel[0]))
        except Exception:
            return None

    def _p_open_artifact_folder(self):
        p = self._p_selected_artifact()
        if not p:
            messagebox.showinfo("Info", "Select an artifact first.")
            return
        folder = p.parent
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder:\n{e}")

    def _p_preview_artifact(self):
        p = self._p_selected_artifact()
        if not p or not p.exists():
            messagebox.showinfo("Info", "Select an existing artifact to preview.")
            return
        try:
            data = p.read_bytes()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read artifact:\n{e}")
            return

        # Try text decodes in order; fall back to hex if looks binary
        text = self._decode_best_effort(data)
        if text is None:
            # Hex fallback (first 4096 bytes)
            chunk = data[:4096]
            hexed = chunk.hex()
            grouped = " ".join(hexed[i:i+2] for i in range(0, len(hexed), 2))
            text = f"[binary data] showing first {len(chunk)} bytes as hex:\n\n{grouped}"

        self.p_preview.delete("1.0", "end")
        self.p_preview.insert("end", text)

    # --- tiny helpers for preview ---
    def _decode_best_effort(self, data: bytes) -> Optional[str]:
        """
        Try UTF-8 → UTF-16LE → UTF-16BE → Latin-1.
        Return None if it looks binary (lots of NULs / few printable chars).
        """
        if self._looks_binary(data):
            return None
        for enc in ("utf-8", "utf-16le", "utf-16be", "latin-1"):
            try:
                s = data.decode(enc)
                # Filter out excessive control characters; if too many, treat as binary
                if self._too_many_controls(s):
                    continue
                return s
            except Exception:
                continue
        return None

    def _looks_binary(self, data: bytes) -> bool:
        if not data:
            return False
        sample = data[:4096]
        nul_fraction = sample.count(0) / len(sample)
        # crude heuristics: lots of NULs or very high entropy-looking chunk
        if nul_fraction > 0.10:
            return True
        # check printable ratio
        printable = sum(1 for b in sample if 32 <= b <= 126 or b in (9, 10, 13))
        return printable / len(sample) < 0.5

    def _too_many_controls(self, s: str) -> bool:
        if not s:
            return False
        sample = s[:4096]
        controls = sum(1 for ch in sample if ord(ch) < 32 and ch not in ("\n", "\r", "\t"))
        return controls / max(1, len(sample)) > 0.10



if __name__ == "__main__":
    app = App()
    app.mainloop()
