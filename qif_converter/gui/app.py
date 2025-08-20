# qif_converter/gui/app.py
from __future__ import annotations
import os
from types import SimpleNamespace
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont
from typing import List
from .scaling import apply_global_font_scaling

# project modules
from qif_converter import qif_to_csv as mod
from qif_converter.gui.merge_tab import MergeTab
from qif_converter.gui.convert_tab import ConvertTab
from qif_converter.gui.probe_tab import ProbeTab
from qif_converter.gui.utils import (
    filter_date_range, apply_multi_payee_filters,
)
from qif_converter import qfx_to_txns as qfx
from qif_converter.qif_loader import load_transactions

class App(tk.Tk):
    """
    Top-level window that hosts three tabs.
    For test-compatibility, we expose a few legacy attributes and methods.
    """
    def __init__(self, messagebox_api=None):
        super().__init__()
        # NEW: auto font scaling
        try:
            apply_global_font_scaling(self, base_pt=10, minimum_pt=12)
        except Exception:
            pass

        # --- Notebook (tab) styling for better visibility and selected color ---
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")  # clam respects custom colors on Windows/macOS
        except Exception:
            pass

        # Base font → slightly larger & bold for tabs
        try:
            base = tkfont.nametofont("TkDefaultFont")
            tab_font = tkfont.Font(self, family=base.cget("family"),
                                   size=max(12, int(base.cget("size")) + 2),
                                   weight="bold")
        except Exception:
            tab_font = ("Segoe UI", 12, "bold")

        # Define a custom Notebook style so we can target its Tab style precisely
        self.style.configure(
            "Custom.TNotebook",
            background="#d1d5db",  # notebook area behind tabs
            borderwidth=2,
            relief="ridge",
            tabmargins=(12, 6, 12, 0)  # extra air around tabs
        )

        # Tab base (unselected) appearance
        self.style.configure(
            "Custom.TNotebook.Tab",
            font=tab_font,
            padding=(18, 10),
            borderwidth=2,
            relief="raised",
            background="#e5e7eb",  # light gray when not selected
            foreground="black"
        )

        # State-driven colors: selected and hover
        self.style.map(
            "Custom.TNotebook.Tab",
            background=[
                ("selected", "#2563eb"),  # vivid blue when selected
                ("active", "#3b82f6"),  # lighter blue on hover
                ("!selected", "#e5e7eb")
            ],
            foreground=[
                ("selected", "white"),
                ("active", "white"),
                ("!selected", "black")
            ]
        )

        # Apply the custom style to your Notebook
        # If you've already created it earlier, set the style attribute:
        #   self.nb.configure(style="Custom.TNotebook")
        # If you're creating it now, do:
        #   self.nb = ttk.Notebook(self, style="Custom.TNotebook")
        try:
            self.nb.configure(style="Custom.TNotebook")
        except Exception:
            pass

        # Dependency-injected messagebox wrapper; calls module functions at call time
        self.mb = messagebox_api or SimpleNamespace(
            showinfo=lambda *a, **k: messagebox.showinfo(*a, **k),
            showerror=lambda *a, **k: messagebox.showerror(*a, **k),
            askyesno=lambda *a, **k: messagebox.askyesno(*a, **k),
        )
        self.title("QIF Tools")
        self.geometry("980x720")
        self.minsize(920, 640)

        # Dependency-injected messagebox wrapper (fallback inside methods if not present)
        self.mb = messagebox_api or SimpleNamespace(
            showinfo=lambda *a, **k: messagebox.showinfo(*a, **k),
            showerror=lambda *a, **k: messagebox.showerror(*a, **k),
            askyesno=lambda *a, **k: messagebox.askyesno(*a, **k),
        )

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)

        # after: self.nb = ttk.Notebook(self); self.nb.pack(...)
        # Build tabs (inject messagebox wrapper)
        self.convert_tab = ConvertTab(self, self.mb)
        self.merge_tab = MergeTab(self, self.mb)
        self.probe_tab = ProbeTab(self, self.mb)

        # NOTEBOOK ORDER (Merge first, per your preference)
        self.nb.add(self.merge_tab, text="Excel ↔ QIF Merge")
        self.nb.add(self.convert_tab, text="Convert (QIF → CSV/QIF)")
        self.nb.add(self.probe_tab, text="QDX Probe")

        # ----- Convert tab shims (tests expect these on App) -----
        self.in_path = self.convert_tab.in_path
        self.out_path = self.convert_tab.out_path
        self.emit_var = self.convert_tab.emit_var
        self.csv_profile = self.convert_tab.csv_profile
        self.explode_var = self.convert_tab.explode_var
        self.match_var = self.convert_tab.match_var
        self.case_var = self.convert_tab.case_var
        self.combine_var = self.convert_tab.combine_var
        self.date_from = self.convert_tab.date_from
        self.date_to = self.convert_tab.date_to
        self.payees_text = self.convert_tab.payees_text
        self.log = self.convert_tab.log

        def _update_output_extension(self): return self.convert_tab._update_output_extension()

        def _parse_payee_filters(self):     return self.convert_tab._parse_payee_filters()

        def logln(self, msg: str):          return self.convert_tab.logln(msg)

        #def _run(self):                     return self.convert_tab._run()
        # ------------ Temporary Fix. Need to map tests directly to convert_tab._run() ----------
        def _run(self):
            """Headless/test-friendly 'Convert' action handler using the unified loader."""
            mb = self._get_mb()
            try:
                in_path = Path(self.in_path.get().strip())
                out_path = Path(self.out_path.get().strip())

                if not in_path or not in_path.exists():
                    mb.showerror("Error", "Please select a valid input QIF file.")
                    return
                if not out_path:
                    mb.showerror("Error", "Please choose an output file.")
                    return
                if out_path.exists():
                    if not mb.askyesno("Confirm Overwrite", f"The file already exists:\n\n{out_path}\n\nOverwrite?"):
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

                in_ext = in_path.suffix.lower()
                if in_ext in (".qfx", ".ofx"):
                    self.logln("Parsing QFX/OFX…")
                    from qif_converter import qfx_to_txns as qfx
                    txns = qfx.parse_qfx(in_path)
                else:
                    self.logln("Parsing QIF…")
                    from qif_converter import qif_loader as qloader
                    txns = qloader.load_transactions(in_path)

                # Optional filters, same as before
                if df or dt:
                    self.logln(f"Filtering by date range: from={df or 'MIN'} to={dt or 'MAX'}")
                    from qif_converter.gui.utils import filter_date_range
                    txns = filter_date_range(txns, df, dt)

                if payees:
                    self.logln(
                        f"Applying payee filters: {payees} (mode={match_mode}, case={'yes' if case_sensitive else 'no'}, combine={combine})")
                    from qif_converter.gui.utils import apply_multi_payee_filters
                    txns = apply_multi_payee_filters(txns, payees, mode=match_mode, case_sensitive=case_sensitive,
                                                     combine=combine)

                self.logln(f"Transactions after filters: {len(txns)}")
                from qif_converter import qif_to_csv as mod

                if emit == "qif":
                    self.logln(f"Writing QIF → {out_path}")
                    mod.write_qif(txns, out_path)
                    mb.showinfo("Done", f"Filtered QIF written:\n{out_path}")
                    return

                if csv_profile == "quicken-windows":
                    self.logln(f"Writing CSV (Quicken Windows profile) → {out_path}")
                    from qif_converter.gui.utils import write_csv_quicken_windows
                    write_csv_quicken_windows(txns, out_path)
                elif csv_profile == "quicken-mac":
                    self.logln(f"Writing CSV (Quicken Mac/Mint profile) → {out_path}")
                    from qif_converter.gui.utils import write_csv_quicken_mac
                    write_csv_quicken_mac(txns, out_path)
                else:
                    if explode:
                        self.logln(f"Writing CSV (exploded splits) → {out_path}")
                        mod.write_csv_exploded(txns, out_path)
                    else:
                        self.logln(f"Writing CSV (flattened) → {out_path}")
                        mod.write_csv_flat(txns, out_path)

                mb.showinfo("Done", f"CSV written:\n{out_path}")
            except Exception as e:
                mb.showerror("Error", str(e))
                self.logln(f"ERROR: {e}")

        # ----- Merge tab shims (tests poke these on App) -----
        self.m_qif_in = self.merge_tab.m_qif_in
        self.m_xlsx = self.merge_tab.m_xlsx
        self.m_qif_out = self.merge_tab.m_qif_out
        self.m_only_matched = self.merge_tab.m_only_matched
        self.m_preview_var = self.merge_tab.m_preview_var

        def _m_normalize_categories(self):  # backward-compat name used by tests
            return self.merge_tab.open_normalize_modal()

    # ---------- Legacy methods (kept for tests) ----------
    def _update_output_extension(self):
        """Exact behavior kept for tests; operates only on in_path/out_path/emit_var."""
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

    def logln(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        # In tests they stub update_idletasks; if missing, no-op
        getattr(self, "update_idletasks", lambda *a, **k: None)()

    def _get_mb(self):
        # headless tests build App via object.__new__ and do NOT set mb.
        # Fall back to real tkinter.messagebox if self.mb is missing.
        if hasattr(self, "mb") and self.mb:
            return self.mb
        return SimpleNamespace(
            showinfo=lambda *a, **k: messagebox.showinfo(*a, **k),
            showerror=lambda *a, **k: messagebox.showerror(*a, **k),
            askyesno=lambda *a, **k: messagebox.askyesno(*a, **k),
        )

    def _run(self):
        """
        Legacy “Convert” action handler, kept so tests can call it on App.
        Does not require the tabs to exist; it only uses the stubbed attributes that tests set.
        """
        mb = self._get_mb()
        try:
            in_path = Path(self.in_path.get().strip())
            out_path = Path(self.out_path.get().strip())

            if not in_path or not in_path.exists():
                mb.showerror("Error", "Please select a valid input QIF file.")
                return
            if not out_path:
                mb.showerror("Error", "Please choose an output file.")
                return
            if out_path.exists():
                if not mb.askyesno("Confirm Overwrite", f"The file already exists:\n\n{out_path}\n\nOverwrite?"):
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
            # choose parser by extension
            in_ext = in_path.suffix.lower()
            if in_ext in (".qfx", ".ofx"):
                self.logln("Parsing QFX/OFX…")
                txns = qfx.parse_qfx(in_path)
            else:
                self.logln("Parsing QIF…")
                txns = load_transactions(in_path)

            if df or dt:
                self.logln(f"Filtering by date range: from={df or 'MIN'} to={dt or 'MAX'}")
                txns = filter_date_range(txns, df, dt)

            if payees:
                self.logln(f"Applying payee filters: {payees} (mode={match_mode}, case={'yes' if case_sensitive else 'no'}, combine={combine})")
                txns = apply_multi_payee_filters(txns, payees, mode=match_mode, case_sensitive=case_sensitive, combine=combine)

            self.logln(f"Transactions after filters: {len(txns)}")
            if emit == "qif":
                self.logln(f"Writing QIF → {out_path}")
                mod.write_qif(txns, out_path)
                mb.showinfo("Done", f"Filtered QIF written:\n{out_path}")
                return

            if csv_profile == "quicken-windows":
                self.logln(f"Writing CSV (Quicken Windows profile) → {out_path}")
                from qif_converter.gui.utils import write_csv_quicken_windows
                write_csv_quicken_windows(txns, out_path)
            elif csv_profile == "quicken-mac":
                self.logln(f"Writing CSV (Quicken Mac/Mint profile) → {out_path}")
                from qif_converter.gui.utils import write_csv_quicken_mac
                write_csv_quicken_mac(txns, out_path)
            else:
                if explode:
                    self.logln(f"Writing CSV (exploded splits) → {out_path}")
                    mod.write_csv_exploded(txns, out_path)
                else:
                    self.logln(f"Writing CSV (flattened) → {out_path}")
                    mod.write_csv_flat(txns, out_path)

            mb.showinfo("Done", f"CSV written:\n{out_path}")
        except Exception as e:
            mb.showerror("Error", str(e))
            self.logln(f"ERROR: {e}")

    # ------ tiny glue so tests that call category normalize via App still work ------
    def _m_normalize_categories(self):
        """Forward to the Merge tab’s normalize modal."""
        # The modal uses Toplevel(self), so passing self is correct.
        return self.merge_tab.open_normalize_modal()

if __name__ == "__main__":
    app = App()
    app.mainloop()

