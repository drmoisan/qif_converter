# qif_converter/gui/convert_tab.py
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path
from typing import List
from qif_converter import qif_to_csv as mod
from qif_converter.gui.helpers import filter_date_range, apply_multi_payee_filters
from qif_converter.gui.csv_profiles import (
    write_csv_quicken_windows, write_csv_quicken_mac,)
from qif_converter import qfx_to_txns as qfx


class ConvertTab(ttk.Frame):
    """Primary function: Convert QIF → CSV/QIF with filters and profiles."""
    def __init__(self, master, mb):
        super().__init__(master)
        self.mb = mb
        self._build()

    # ---------- UI ----------
    def _build(self):
        pad = {'padx': 8, 'pady': 6}

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

        io_frame = ttk.LabelFrame(self, text="Files")
        io_frame.pack(fill="x", **pad)

        ttk.Label(io_frame, text="Input QIF:").grid(row=0, column=0, sticky="w")
        ttk.Entry(io_frame, textvariable=self.in_path, width=90).grid(row=0, column=1, sticky="we", padx=5)
        ttk.Button(io_frame, text="Browse…", command=self._browse_in).grid(row=0, column=2)

        ttk.Label(io_frame, text="Output File:").grid(row=1, column=0, sticky="w")
        ttk.Entry(io_frame, textvariable=self.out_path, width=90).grid(row=1, column=1, sticky="we", padx=5)
        ttk.Button(io_frame, text="Browse…", command=self._browse_out).grid(row=1, column=2)
        io_frame.columnconfigure(1, weight=1)

        opt = ttk.LabelFrame(self, text="Options")
        opt.pack(fill="x", **pad)
        ttk.Label(opt, text="Emit:").grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(opt, text="CSV", variable=self.emit_var, value="csv").grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(opt, text="QIF", variable=self.emit_var, value="qif").grid(row=0, column=2, sticky="w")
        ttk.Label(opt, text="CSV Profile:").grid(row=0, column=3, sticky="e")
        ttk.Combobox(opt, textvariable=self.csv_profile,
                     values=["default","quicken-windows","quicken-mac"],
                     width=18, state="readonly").grid(row=0, column=4, sticky="w", padx=5)
        ttk.Checkbutton(opt, text="Explode splits (CSV only)", variable=self.explode_var).grid(row=0, column=5, sticky="w")

        flt = ttk.LabelFrame(self, text="Filters")
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

        runf = ttk.Frame(self)
        runf.pack(fill="x", **pad)
        ttk.Button(runf, text="Run Conversion", command=self.run_conversion).pack(side="left")
        ttk.Button(runf, text="Quit", command=self.master.destroy).pack(side="right")

        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(logf, height=12)
        self.log.pack(fill="both", expand=True, padx=5, pady=5)

        def _on_emit_change(*_):
            self._update_output_extension()
        self.emit_var.trace_add("write", _on_emit_change)

    # ---------- actions ----------
    def _browse_in(self):
        path = filedialog.askopenfilename(
            title="Select input file",
            filetypes=[
                ("QIF / QFX files", ("*.qif", "*.qfx", "*.ofx")),
                ("QIF files", "*.qif"),
                ("QFX/OFX files", ("*.qfx", "*.ofx")),
                ("All files", "*.*"),
            ]
        )
        if path:
            self.in_path.set(path)

    def _browse_out(self):
        emit = self.emit_var.get()
        if emit == "qif":
            default_ext = ".qif"; ft = [("QIF files","*.qif"),("All files","*.*")]
        else:
            default_ext = ".csv"; ft = [("CSV files","*.csv"),("All files","*.*")]
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

    def run_conversion(self):
        try:
            in_path = Path(self.in_path.get().strip())
            out_path = Path(self.out_path.get().strip())
            if not in_path or not in_path.exists():
                self.mb.showerror("Error", "Please select a valid input QIF file.")
                return
            if not out_path:
                self.mb.showerror("Error", "Please choose an output file.")
                return
            if Path(out_path).exists():
                if not self.mb.askyesno("Confirm Overwrite",
                                        f"The file already exists:\n\n{out_path}\n\nDo you want to overwrite it?"):
                    return

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
            ext = in_path.suffix.lower()
            if ext in (".qfx", ".ofx"):
                self.logln("Parsing QFX…")
                from qif_converter.qfx_to_txns import parse_qfx
                txns = parse_qfx(in_path)
            else:
                ext = in_path.suffix.lower()
                if ext in (".qfx", ".ofx"):
                    self.logln("Parsing QFX…")
                    from qif_converter.qfx_to_txns import parse_qfx
                    txns = parse_qfx(in_path)
                else:
                    in_ext = in_path.suffix.lower()
                    if in_ext in (".qfx", ".ofx"):
                        self.logln("Parsing QFX/OFX…")
                        txns = qfx.parse_qfx(in_path)
                    else:
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
                self.mb.showinfo("Done", f"Filtered QIF written:\n{out_path}")
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

            self.mb.showinfo("Done", f"CSV written:\n{out_path}")
        except Exception as e:
            self.mb.showerror("Error", str(e))
            self.logln(f"ERROR: {e}")
