# quicken_helper/gui_viewers/merge_tab.py
from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Any, Dict, Optional, List

from quicken_helper.controllers import match_excel as mex
from quicken_helper.controllers.category_match_session import CategoryMatchSession
from quicken_helper.controllers.match_session import MatchSession

# from quicken_helper.qif_loader import load_transactions
from quicken_helper.controllers.qif_loader import load_transactions_protocol
from quicken_helper.data_model import EnumClearedStatus, ITransaction
from quicken_helper.data_model.excel import ExcelTransaction, ExcelTxnGroup, map_group_to_excel_txn
from quicken_helper.gui_viewers.helpers import _fmt_excel_row, _fmt_txn, _set_text
from quicken_helper.gui_viewers.category_popout import open_normalize_modal as open_category_popout
from quicken_helper.controllers.data_session import DataSession

# import qif_item_key
from quicken_helper.legacy import qif_writer as mod
from quicken_helper.legacy.qif_item_key import QIFItemKey

import logging
import logging.config
from quicken_helper.utilities import LOGGING


logging.config.dictConfig(LOGGING)
log = logging.getLogger(__name__)


@dataclass
class _ListColumn:
    frame: ttk.LabelFrame
    listbox: tk.Listbox
    preview: tk.Text


class MergeTab(ttk.Frame):
    """Primary function: Excel ↔ QIF merge + manual matching + previews."""

    def __init__(self, master, mb, session: DataSession | None = None):
        """Initialize UI state, bind actions, and prepare empty `MatchSession`.

        Does not perform any I/O. File selection or drag-drop handlers call
        the loader methods to populate the session.
        """
        super().__init__(master)
        self.mb = mb
        self.session = session
        self._merge_session: Optional[MatchSession] = None

        # Ensure test-visible lists always exist (even if load/refresh bails early)
        self.m_pairs: list = []
        self.m_unmatched_qif: list = []
        self.m_unmatched_excel: list = []

        self._build()

    def _build(self) -> None:
        self._init_state_vars()
        self._build_files_section()
        self._build_controls_section()
        self._build_actions_section()
        self._build_lists_section()  # internally builds the 3 columns via a reusable helper
        self._build_footer_section()
        self._build_info_section()
        self._bind_preview_events()

    def _build_list_column(self, parent: tk.Misc, title: str, export_slug: str,) -> _ListColumn:
        lf = ttk.LabelFrame(parent, text=title)
        lf.pack(side="left", fill="both", expand=True, padx=4, pady=4)

        container = ttk.Frame(lf)
        container.pack(fill="both", expand=True)

        lbx = tk.Listbox(container, exportselection=False)
        lbx.pack(fill="both", expand=True, padx=4, pady=4)

        btns = ttk.Frame(container)
        btns.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(
            btns,
            text="Export…",
            command=lambda: self._export_listbox(lbx, export_slug),
        ).pack(side="left")

        prev = tk.Text(container, height=8, wrap="word")
        prev.pack_forget()

        return _ListColumn(frame=lf, listbox=lbx, preview=prev)

    def _init_state_vars(self) -> None:
        self.m_qif_in = tk.StringVar()
        self.m_xlsx = tk.StringVar()
        self.m_qif_out = tk.StringVar()
        self.m_only_matched = tk.BooleanVar(value=False)
        self.m_preview_var = tk.BooleanVar(value=False)

    def _build_files_section(self) -> None:
        pad = {"padx": 8, "pady": 6}
        files = ttk.LabelFrame(self, text="Files")
        files.pack(fill="x", **pad)

        ttk.Label(files, text="Input QIF:").grid(row=0, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.m_qif_in, width=90).grid(
            row=0, column=1, sticky="we", padx=5
        )
        ttk.Button(files, text="Browse…", command=self._m_browse_qif).grid(
            row=0, column=2
        )

        ttk.Label(files, text="Excel (.xlsx):").grid(row=1, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.m_xlsx, width=90).grid(
            row=1, column=1, sticky="we", padx=5
        )
        ttk.Button(files, text="Browse…", command=self._m_browse_xlsx).grid(
            row=1, column=2
        )

        ttk.Label(files, text="Output QIF:").grid(row=2, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.m_qif_out, width=90).grid(
            row=2, column=1, sticky="we", padx=5
        )
        ttk.Button(files, text="Browse…", command=self._m_browse_out).grid(
            row=2, column=2
        )

        files.columnconfigure(1, weight=1)

    def _build_controls_section(self) -> None:
        controls = ttk.Frame(self)
        controls.pack(anchor="w", padx=12, pady=(0, 6), fill="x")
        ttk.Checkbutton(
            controls, text="Output Only Matched Items", variable=self.m_only_matched
        ).pack(side="left")
        ttk.Checkbutton(
            controls,
            text="Preview Window",
            variable=self.m_preview_var,
            command=self._m_toggle_previews,
        ).pack(side="left", padx=(12, 0))

    def _build_actions_section(self) -> None:
        pad = {"padx": 8, "pady": 6}
        actions = ttk.Frame(self)
        actions.pack(fill="x", **pad)
        ttk.Button(
            actions, text="Load + Auto-Match", command=self._m_load_and_auto
        ).pack(side="left")
        ttk.Button(
            actions, text="Normalize Categories", command=self.open_normalize_modal #normalize_cats_modal
        ).pack(side="left", padx=6)
        ttk.Button(
            actions, text="Apply Updates & Save", command=self._m_apply_and_save
        ).pack(side="right")

    def _build_lists_section(self) -> None:
        pad = {"padx": 8, "pady": 6}
        lists = ttk.Frame(self)
        lists.pack(fill="both", expand=True, **pad)

        # Build columns via reusable helper and attach to self
        left = self._build_list_column(lists, "Unmatched QIF items", "unmatched_qif")
        self.lbx_unqif, self.prev_unqif = left.listbox, left.preview

        mid = self._build_list_column(lists, "Matched pairs", "matched_pairs")
        self.lbx_pairs, self.prev_pairs = mid.listbox, mid.preview

        right = self._build_list_column(
            lists, "Unmatched Excel rows", "unmatched_excel"
        )
        self.lbx_unx, self.prev_unx = right.listbox, right.preview

    def _build_footer_section(self) -> None:
        pad = {"padx": 8, "pady": 6}
        foot = ttk.Frame(self)
        foot.pack(fill="x", **pad)
        ttk.Button(foot, text="Match Selected →", command=self._m_manual_match).pack(
            side="left"
        )
        ttk.Button(foot, text="Unmatch Selected", command=self._m_manual_unmatch).pack(
            side="left", padx=8
        )
        ttk.Button(foot, text="Why not matched?", command=self._m_why_not).pack(
            side="left", padx=8
        )

    def _build_info_section(self) -> None:
        pad = {"padx": 8, "pady": 6}
        infof = ttk.LabelFrame(self, text="Info")
        infof.pack(fill="x", **pad)
        self.txt_info = tk.Text(infof, height=6, wrap="word")
        self.txt_info.pack(fill="x", padx=8, pady=6)

    def _bind_preview_events(self) -> None:
        self.lbx_unqif.bind(
            "<<ListboxSelect>>", lambda e: self._m_update_preview("unqif")
        )
        self.lbx_pairs.bind(
            "<<ListboxSelect>>", lambda e: self._m_update_preview("pairs")
        )
        self.lbx_unx.bind("<<ListboxSelect>>", lambda e: self._m_update_preview("unx"))


    # --------- Protocol→dict adapters (temporary during migration) ---------
    @staticmethod
    def _format_date(d: date) -> str:
        # Legacy merge pipeline expects string dates; standardize as MM/DD/YYYY
        return f"{d.month:02d}/{d.day:02d}/{d.year:04d}"

    @staticmethod
    def _cleared_to_char(val) -> str:
        """
        Map a cleared-like value to a single display char without assuming the value is hashable.
        Accepts:
          - Enum-like (has .name)
          - strings ("yes", "reconciled", "no", "c", "r", etc.)
          - ints (0/1/2) or bools
          - None
        """
        if val is None:
            name = ""
        elif isinstance(val, str):
            name = val
        else:
            # Enum-like or other object: prefer .name; fallback to str()
            name = getattr(val, "name", None)
            if name is None:
                # Some stubs stringify to something useful, e.g. "EnumClearedStatus.NO"
                name = str(val)
        name = (name or "").strip().upper()

        # Common “uncleared/unknown” cases
        if name in {"", "NO", "UNKNOWN", "UNCLEARED", "FALSE", "0"}:
            return " "
        # “cleared”
        if name in {"YES", "CLEARED", "TRUE", "C", "1"}:
            return "c"
        # “reconciled”
        if name in {"RECONCILED", "R", "2"}:
            return "R"

        # Fallback to blank
        return " "

    @classmethod
    def _txn_to_dict(cls, t: ITransaction) -> Dict[str, Any]:
        """Shape a protocol transaction for display (robust to missing optional attrs)."""
        category = getattr(t, "category", "") or ""
        tag = getattr(t, "tag", "") or ""
        if tag:
            category = f"{category}/{tag}" if category else tag
        return {
            "date": cls._format_date(getattr(t, "date", date.today())),
            "amount": str(getattr(t, "amount", "")),
            "payee": getattr(t, "payee", "") or "",
            "memo": getattr(t, "memo", "") or "",
            "category": category,
            "checknum": getattr(t, "action_chk", None),
            "cleared": cls._cleared_to_char(
                getattr(t, "cleared", EnumClearedStatus.UNKNOWN)
            ),
            "splits": [
                {
                    "amount": str(getattr(s, "amount", "")),
                    "category": getattr(s, "category", "") or "",
                    "memo": getattr(s, "memo", "") or "",
                }
                for s in (getattr(t, "splits", None) or [])
            ],
        }

    # ---------- file pickers ----------
    def _m_browse_qif(self):
        p = filedialog.askopenfilename(
            title="Select input QIF",
            filetypes=[("QIF files", "*.qif"), ("All files", "*.*")],
        )
        if p:
            self.m_qif_in.set(p)
            if not self.m_qif_out.get().strip():
                self.m_qif_out.set(
                    str(Path(p).with_name(Path(p).stem + "_updated.qif"))
                )

    def _m_browse_xlsx(self):
        p = filedialog.askopenfilename(
            title="Select Excel workbook",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
        )
        if p:
            self.m_xlsx.set(p)

    def _m_browse_out(self):
        p = filedialog.asksaveasfilename(
            title="Select output QIF",
            defaultextension=".qif",
            filetypes=[("QIF files", "*.qif"), ("All files", "*.*")],
        )
        if p:
            self.m_qif_out.set(p)

    # ---------- actions ----------
    def _m_load_and_auto(self) -> None:
        try:
            qif_in = Path(self.m_qif_in.get().strip())
            xlsx = Path(self.m_xlsx.get().strip())

            if not qif_in.exists():
                self.mb.showerror("Error", "Please choose a valid input QIF.")
                return
            if not xlsx.exists():
                self.mb.showerror("Error", "Please choose a valid Excel (.xlsx).")
                return

            # Bank/Excel side: prefer cached DataSession if available
            if self.session:
                bank_txns = self.session.load_qif(qif_in)
                excel_txns = self.session.load_excel(xlsx)
                rows = self.session.excel_rows or []
            else:
                # Bank side: already ITransaction via loader
                bank_txns = load_transactions_protocol(qif_in)
                # Excel side: rows -> groups -> ITransaction (via adapter)
                rows = mex.load_excel_rows(xlsx)
                groups = mex.group_excel_rows(rows)
                excel_txns = [map_group_to_excel_txn(g) for g in groups]


            # ✅ Protocol-only session: (bank_txns, excel_txns)
            sess = MatchSession(bank_txns, excel_txns)
            sess.auto_match()

            # Publish session and refresh UI
            self._merge_session = sess
            self._m_refresh_lists()
            self._m_info(
                "Loaded "
                f"{len(bank_txns)} QIF transactions and "
                f"{len(excel_txns)} Excel groups (as transactions) "
                f"({len(rows)} split rows).\n"
                f"Matched pairs: {len(sess.pairs)} | "
                f"Unmatched QIF: {len(sess.unmatched_bank)} | "
                f"Unmatched Excel: {len(sess.unmatched_excel)}"
            )
        except Exception as e:
            # Keep the test-visible failure simple
            self._merge_session = None
            self.mb.showerror("Error", f"{e}")

    def _m_manual_match(self):
        s = self._merge_session
        if not s:
            self.mb.showerror("Error", "No session loaded.")
            return
        bi = self._m_selected_unqif_index()
        ei = self._m_selected_unx_index()
        if bi is None or ei is None:
            self.mb.showerror(
                "Error", "Select one QIF item and one Excel item to match."
            )
            return
        s.manual_match(bank_index=bi, excel_index=ei)
        self._m_info("Matched.")
        self._m_refresh_lists()

    def _m_manual_unmatch(self):
        s = self._merge_session
        if not s:
            return

        # If a pair is selected, unmatch by its bank index
        sel = self.lbx_pairs.curselection()
        if sel:
            try:
                bi, ei, _b, _e = self._pairs_sorted[sel[0]]
            except Exception:
                b, e = s.pairs[sel[0]]
                bi = s.bank_txns.index(b)
            s.manual_unmatch(bank_index=bi)
            self._m_info("Unmatched selected pair.")
            self._m_refresh_lists()
            return

        # Otherwise, unmatch by whichever unmatched list has selection
        bi = self._m_selected_unqif_index()
        if bi is not None:
            s.manual_unmatch(bank_index=bi)
            self._m_info("Unmatched QIF item.")
            self._m_refresh_lists()
            return

        ei = self._m_selected_unx_index()
        if ei is not None:
            s.manual_unmatch(excel_index=ei)
            self._m_info("Unmatched Excel item.")
            self._m_refresh_lists()
            return

        self.mb.showinfo("Info", "Nothing selected to unmatch.")

    def _m_apply_and_save(self):
        try:
            s = self._merge_session
            if not s:
                self.mb.showerror(
                    "Error", "No session loaded. Click 'Load + Auto-Match' first."
                )
                return
            qif_out = Path(self.m_qif_out.get().strip())
            if not qif_out:
                self.mb.showerror("Error", "Please choose an output QIF file.")
                return
            if qif_out.exists():
                if not self.mb.askyesno(
                    "Confirm Overwrite",
                    f"Output QIF already exists:\n\n{qif_out}\n\nOverwrite?",
                ):
                    return
            s.apply_updates()
            txns_to_write = (
                mex.build_matched_only_txns(s) if self.m_only_matched.get() else s.txns
            )
            qif_out.parent.mkdir(parents=True, exist_ok=True)
            mod.write_qif(txns_to_write, qif_out)
            self._m_info(f"Updates applied. Wrote updated QIF:\n{qif_out}")
            self.mb.showinfo("Done", f"Updated QIF written:\n{qif_out}")
        except Exception as e:
            self.mb.showerror("Error", str(e))

    def _m_info(self, msg: str):
        try:
            self.txt_info.delete("1.0", "end")
            self.txt_info.insert("end", msg)
        except Exception:
            try:
                self.mb.showinfo("Info", msg)
            except Exception:
                pass

    def _export_listbox(self, lb: tk.Listbox, default_tag: str):
        """Export the current strings shown in a Listbox to a file (txt or csv)."""
        items = lb.get(0, "end")
        if not items:
            self.mb.showinfo("Export", f"No items to export from '{default_tag}'.")
            return

        path = filedialog.asksaveasfilename(
            title=f"Export {default_tag}",
            initialfile=f"{default_tag}.txt",
            defaultextension=".txt",
            filetypes=[
                ("Text files", "*.txt"),
                ("CSV files", "*.csv"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                for row in items:
                    f.write(str(row) + "\n")
            self.mb.showinfo("Export", f"Exported {len(items)} items to:\n{path}")
        except Exception as e:
            self.mb.showerror("Export Error", str(e))

    # ------------------ Normalize Categories modal  --------------------
    # def open_normalize_modal(self):
    #     """
    #     Open the Normalize Categories UI if Tk is available; otherwise, provide a
    #     headless object exposing the same actions so tests don't need Tk/TTK at all.
    #     """
    #     try:
    #         qif_in = Path(self.m_qif_in.get().strip())
    #         xlsx = Path(self.m_xlsx.get().strip())
    #         if not qif_in.exists():
    #             self.mb.showerror("Error", "Please choose a valid input QIF.")
    #             return None
    #         if not xlsx.exists():
    #             self.mb.showerror("Error", "Please choose a valid Excel (.xlsx).")
    #             return None
    #
    #         # Build session
    #         from quicken_helper.controllers.qif_loader import parse_qif_unified_protocol
    #         quicken_file = parse_qif_unified_protocol(qif_in)
    #
    #         transactions = quicken_file.transactions
    #         txns = [t.to_dict() for t in transactions]
    #         # txns = open_and_parse_qif(qif_in)
    #         qif_cats = mex.extract_qif_categories(txns)
    #         excel_cats = mex.extract_excel_categories(xlsx)
    #         sess = CategoryMatchSession(qif_cats, excel_cats)
    #
    #         # Try GUI path first; if it fails (e.g., Tk not installed), fall back to headless.
    #         try:
    #             parent = self.winfo_toplevel()
    #             win = tk.Toplevel(parent)
    #             win.title("Normalize Categories")
    #             win.geometry("900x520")
    #             win.transient(parent)
    #             win.grab_set()
    #
    #             pad = {"padx": 8, "pady": 6}
    #
    #             # Top actions
    #             top = ttk.Frame(win)
    #             top.pack(fill="x", **pad)
    #             ttk.Button(
    #                 top,
    #                 text="Auto-Match",
    #                 command=lambda: (sess.auto_match(), refresh()),
    #             ).pack(side="left")
    #             ttk.Button(
    #                 top, text="Match Selected →", command=lambda: do_match()
    #             ).pack(side="left", padx=6)
    #             ttk.Button(
    #                 top, text="Unmatch Selected", command=lambda: do_unmatch()
    #             ).pack(side="left", padx=6)
    #
    #             # Lists
    #             lists = ttk.Frame(win)
    #             lists.pack(fill="both", expand=True, **pad)
    #
    #             left = ttk.LabelFrame(lists, text="QIF Categories (canonical)")
    #             left.pack(side="left", fill="both", expand=True, padx=4, pady=4)
    #             lbx_qif = tk.Listbox(left, exportselection=False)
    #             lbx_qif.pack(fill="both", expand=True, padx=4, pady=4)
    #
    #             mid = ttk.LabelFrame(lists, text="Matched pairs (Excel → QIF)")
    #             mid.pack(side="left", fill="both", expand=True, padx=4, pady=4)
    #             lbx_pairs = tk.Listbox(mid, exportselection=False)
    #             lbx_pairs.pack(fill="both", expand=True, padx=4, pady=4)
    #
    #             right = ttk.LabelFrame(lists, text="Excel Categories (to normalize)")
    #             right.pack(side="left", fill="both", expand=True, padx=4, pady=4)
    #             lbx_excel = tk.Listbox(right, exportselection=False)
    #             lbx_excel.pack(fill="both", expand=True, padx=4, pady=4)
    #
    #             # Bottom actions
    #             bot = ttk.Frame(win)
    #             bot.pack(fill="x", **pad)
    #             out_path_var = tk.StringVar(
    #                 value=str(xlsx.with_name(xlsx.stem + "_normalized.xlsx"))
    #             )
    #             ttk.Label(bot, text="Output Excel:").pack(side="left")
    #             ttk.Entry(bot, textvariable=out_path_var, width=60).pack(
    #                 side="left", padx=6
    #             )
    #             ttk.Button(bot, text="Browse…", command=lambda: browse_out()).pack(
    #                 side="left", padx=2
    #             )
    #             ttk.Button(
    #                 bot, text="Apply & Save", command=lambda: apply_and_save()
    #             ).pack(side="right")
    #
    #             info = tk.Text(win, height=4, wrap="word")
    #             info.pack(fill="x", padx=8, pady=(0, 8))
    #
    #             # --- helpers (closures) ---
    #             def refresh():
    #                 lbx_qif.delete(0, "end")
    #                 lbx_excel.delete(0, "end")
    #                 lbx_pairs.delete(0, "end")
    #                 uq, ue = sess.unmatched()
    #                 for c in uq:
    #                     lbx_qif.insert("end", c)
    #                 for c in ue:
    #                     lbx_excel.insert("end", c)
    #                 for excel_name, qif_name in sorted(
    #                     sess.mapping.items(), key=lambda kv: kv[0].lower()
    #                 ):
    #                     lbx_pairs.insert("end", f"{excel_name}  →  {qif_name}")
    #                 info.delete("1.0", "end")
    #                 info.insert(
    #                     "end",
    #                     f"QIF categories: {len(sess.qif_cats)} | "
    #                     f"Excel categories: {len(sess.excel_cats)} | "
    #                     f"Matched: {len(sess.mapping)} | "
    #                     f"Unmatched QIF: {len(uq)} | Unmatched Excel: {len(ue)}",
    #                 )
    #
    #             def selected(lbx: tk.Listbox):
    #                 sel = lbx.curselection()
    #                 return lbx.get(sel[0]) if sel else None
    #
    #             def do_match():
    #                 e = selected(lbx_excel)
    #                 q = selected(lbx_qif)
    #                 if not e or not q:
    #                     self.mb.showinfo(
    #                         "Info",
    #                         "Select one Excel category and one QIF category to match.",
    #                     )
    #                     return
    #                 ok, msg = sess.manual_match(e, q)
    #                 if not ok:
    #                     self.mb.showerror("Error", msg)
    #                 refresh()
    #
    #             def do_unmatch():
    #                 sel = lbx_pairs.curselection()
    #                 if sel:
    #                     label = lbx_pairs.get(sel[0])
    #                     if "  →  " in label:
    #                         excel_name = label.split("  →  ", 1)[0]
    #                         sess.manual_unmatch(excel_name)
    #                         refresh()
    #                         return
    #                 # Or unmatch by selecting Excel side
    #                 e = selected(lbx_excel)
    #                 if e and sess.manual_unmatch(e):
    #                     refresh()
    #                     return
    #                 self.mb.showinfo(
    #                     "Info",
    #                     "Select a matched pair (middle list) or an Excel category to unmatch.",
    #                 )
    #
    #             def browse_out():
    #                 p = filedialog.asksaveasfilename(
    #                     title="Select normalized Excel output",
    #                     defaultextension=".xlsx",
    #                     filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
    #                 )
    #                 if p:
    #                     out_path_var.set(p)
    #
    #             def apply_and_save():
    #                 outp = Path(out_path_var.get().strip())
    #                 if outp.exists():
    #                     if not self.mb.askyesno(
    #                         "Confirm Overwrite", f"{outp}\n\nOverwrite?"
    #                     ):
    #                         return
    #                 try:
    #                     out_file = sess.apply_to_excel(xlsx, xlsx_out=outp)
    #                     self.mb.showinfo(
    #                         "Done", f"Normalized Excel written:\n{out_file}"
    #                     )
    #                     win.destroy()
    #                 except Exception as e:
    #                     self.mb.showerror("Error", str(e))
    #
    #             # initial population
    #             refresh()
    #             return win  # return the real modal window
    #
    #         except Exception:
    #             # ===== Headless fallback (no Tk required) =====
    #             class HeadlessNormalize:
    #                 """
    #                 Minimal, dependency-injected stand-in for the modal:
    #                   - exposes same operations for tests
    #                   - never touches Tk/TTK
    #                 """
    #
    #                 def __init__(self, sess: CategoryMatchSession, xlsx_path: Path, mb):
    #                     self.sess = sess
    #                     self.xlsx = xlsx_path
    #                     self.mb = mb
    #                     self.out_path = xlsx_path.with_name(
    #                         xlsx_path.stem + "_normalized.xlsx"
    #                     )
    #
    #                 def auto_match(self, threshold: float = 0.84):
    #                     self.sess.auto_match(threshold)
    #
    #                 def do_match(self, excel_name: str, qif_name: str):
    #                     ok, msg = self.sess.manual_match(excel_name, qif_name)
    #                     return ok, msg
    #
    #                 def do_unmatch(self, excel_name: str):
    #                     return self.sess.manual_unmatch(excel_name)
    #
    #                 def unmatched(self):
    #                     return self.sess.unmatched()
    #
    #                 def pairs(self):
    #                     # Return sorted mapping as label strings similar to UI
    #                     return [
    #                         f"{e}  →  {q}"
    #                         for e, q in sorted(
    #                             self.sess.mapping.items(), key=lambda kv: kv[0].lower()
    #                         )
    #                     ]
    #
    #                 def apply_and_save(self, out_path: Optional[Path] = None):
    #                     outp = Path(out_path) if out_path else self.out_path
    #                     return self.sess.apply_to_excel(self.xlsx, xlsx_out=outp)
    #
    #             return HeadlessNormalize(sess, xlsx, self.mb)
    #
    #     except Exception as e:
    #         self.mb.showerror("Error", str(e))
    #
    #         # Return a no-op object so tests don't explode if they still try to call methods
    #         class _Noop:
    #             pass
    #
    #         return _Noop()

    # Backward-compatible private name (kept; just forwards)

    def open_normalize_modal(self):
        """Open the Normalize Categories popout (delegated to category_popout)."""
        try:
            if not getattr(self, "_merge_session", None):
                self.mb.showerror("Error", "Load data first.")
                return
            xlsx_path = Path(self.m_xlsx.get().strip())
            open_category_popout(self, self._merge_session, xlsx_path, mb=self.mb, show_ui=False)
        except Exception as e:
            # Keep UI resilient
            self.mb.showerror("Error", f"{e}")



    def _m_normalize_categories(self):
        """Toolbar/Actions handler: Normalize Categories."""
        try:
            if not getattr(self, "_merge_session", None):
                self.mb.showerror("Error", "Load data first.")
                return
            xlsx_path = Path(self.m_xlsx.get().strip())
            open_category_popout(self, self._merge_session, xlsx_path, mb=self.mb, show_ui=False)
        except Exception as e:
            self.mb.showerror("Error", f"{e}")



    # def _m_normalize_categories(self):
    #     return self.open_normalize_modal()

    # ---------- list/preview plumbing ----------
    def _m_refresh_lists(self) -> None:
        # Clear listboxes
        self.lbx_pairs.delete(0, "end")
        self.lbx_unqif.delete(0, "end")
        self.lbx_unx.delete(0, "end")

        s = getattr(self, "_merge_session", None)
        # Initialize caches and test-visible mirrors
        self._pairs_sorted = []
        self._unqif_sorted = []
        self._unx_sorted = []
        self.m_pairs = []
        self.m_unmatched_qif = []
        self.m_unmatched_excel = []

        if not s:
            return

        # ----- Matched pairs -----
        try:
            # Stable sort by (bank date, excel date, bank amount) for deterministic UI/tests
            def _pair_key(t):
                b, e = t
                b_d = getattr(b, "date", None)
                e_d = getattr(e, "date", None)
                b_ds = b_d.isoformat() if b_d else ""
                e_ds = e_d.isoformat() if e_d else ""
                return (b_ds, e_ds, str(getattr(b, "amount", "")))

            pairs_sorted = sorted(s.pairs, key=_pair_key)

            for b, e in pairs_sorted:
                # Map back to indices for later manual unmatch ops
                try:
                    bi = s.bank_txns.index(b)
                except ValueError:
                    bi = -1
                try:
                    ei = s.excel_txns.index(e)
                except ValueError:
                    ei = -1

                self._pairs_sorted.append((bi, ei, b, e))
                self.m_pairs.append((b, e))

                label = (
                    f"{getattr(b, 'date', None).isoformat() if getattr(b, 'date', None) else ''} "
                    f"{getattr(b, 'amount', '')} — {getattr(b, 'payee', '')}  "
                    f"↔  Excel[{getattr(e, 'id', '')}] "
                    f"{getattr(e, 'date', None).isoformat() if getattr(e, 'date', None) else ''} "
                    f"{getattr(e, 'amount', '')} | "
                    f"{len(getattr(e, 'splits', []) or [])} split(s)"
                )
                self.lbx_pairs.insert("end", label)
        except Exception as e:
            log.exception("Operation failed: %s", e)
            # Keep UI resilient; leave pairs empty on error
            pass

        # ----- Unmatched QIF (bank side) -----
        try:

            def _bank_key(t):
                d = getattr(t, "date", None)
                ds = d.isoformat() if d else ""
                return (ds, str(getattr(t, "amount", "")), getattr(t, "payee", ""))

            for b in sorted(s.unmatched_bank, key=_bank_key):
                try:
                    bi = s.bank_txns.index(b)
                except ValueError:
                    bi = -1
                self._unqif_sorted.append((bi, b))
                self.m_unmatched_qif.append(b)
                self.lbx_unqif.insert(
                    "end",
                    f"{getattr(b, 'date', None).isoformat() if getattr(b, 'date', None) else ''} "
                    f"{getattr(b, 'amount', '')} — {getattr(b, 'payee', '')}",
                )
        except Exception as e:
            log.exception("Operation failed: %s", e)
            pass

        # ----- Unmatched Excel (excel side) -----
        try:

            def _excel_key(t):
                """Deterministic sort key for Excel-side ITransaction objects."""
                d = getattr(t, "date", None)
                ds = d.isoformat() if d else ""
                # amount may be Decimal; stringify for consistent tuple ordering
                try:
                    amt = str(getattr(t, "amount", ""))
                except Exception:
                    amt = ""
                payee = getattr(t, "payee", "") or ""
                return (ds, amt, payee)

            for e in sorted(s.unmatched_excel, key=_excel_key):
                try:
                    ei = s.excel_txns.index(e)
                except ValueError:
                    ei = -1
                self._unx_sorted.append((ei, e))
                self.m_unmatched_excel.append(e)
                self.lbx_unx.insert(
                    "end",
                    f"Excel[{getattr(e, 'id', '')}] "
                    f"{getattr(e, 'date', None).isoformat() if getattr(e, 'date', None) else ''} "
                    f"{getattr(e, 'amount', '')} | "
                    f"{len(getattr(e, 'splits', []) or [])} split(s)",
                )
        except Exception as e:
            log.exception("Operation failed: %s", e)
            pass

        # ----- Seed previews if the toggle is on -----
        if self.m_preview_var.get():
            try:
                # Unmatched QIF preview
                if self._unqif_sorted:
                    _bi, b = self._unqif_sorted[0]
                    _set_text(
                        self.prev_unqif,
                        _fmt_txn(
                            {
                                "date": getattr(b, "date", None).isoformat()
                                if getattr(b, "date", None)
                                else "",
                                "amount": str(getattr(b, "amount", "")),
                                "payee": getattr(b, "payee", "") or "",
                                "category": getattr(b, "category", "") or "",
                                "memo": getattr(b, "memo", "") or "",
                            }
                        ),
                    )
                # Unmatched Excel preview
                if self._unx_sorted:
                    _ei, e = self._unx_sorted[0]
                    first = (getattr(e, "splits", None) or [None])[0]
                    _set_text(
                        self.prev_unx,
                        _fmt_excel_row(
                            {
                                "TxnID": getattr(e, "id", "") or "",
                                "Date": getattr(e, "date", None).isoformat()
                                if getattr(e, "date", None)
                                else "",
                                "Total Amount": str(getattr(e, "amount", "")),
                                "Split Count": len(getattr(e, "splits", []) or []),
                                "First Item": getattr(first, "memo", "")
                                if first
                                else "",
                                "First Category": getattr(first, "category", "")
                                if first
                                else "",
                                "First Rationale": getattr(e, "memo", "") or "",
                            }
                        ),
                    )
                # First pair preview
                if self._pairs_sorted:
                    _bi, _ei, b, e = self._pairs_sorted[0]
                    excel_view = {
                        "TxnID": getattr(e, "id", "") or "",
                        "Date": getattr(e, "date", None).isoformat()
                        if getattr(e, "date", None)
                        else "",
                        "Total Amount": str(getattr(e, "amount", "")),
                        "Split Count": len(getattr(e, "splits", []) or []),
                        "First Item": getattr(
                            (getattr(e, "splits", None) or [None])[0], "memo", ""
                        )
                        if getattr(e, "splits", None)
                        else "",
                        "First Category": getattr(
                            (getattr(e, "splits", None) or [None])[0], "category", ""
                        )
                        if getattr(e, "splits", None)
                        else "",
                        "First Rationale": getattr(e, "memo", "") or "",
                    }
                    qif_view = {
                        "date": getattr(b, "date", None).isoformat() if getattr(b, "date", None) else "",
                        "amount": str(getattr(b, "amount", "")),
                        "payee": getattr(b, "payee", "") or "",
                        "category": getattr(b, "category", "") or "",
                        "memo": getattr(b, "memo", "") or "",
                    }
                    _set_text(self.prev_pairs, "[Excel]\n" + _fmt_excel_row(excel_view) + "\n\n[QIF]\n" + _fmt_txn(qif_view))
            except Exception:
                # Preview is non-critical; ignore errors to keep UI stable
                pass

    def _m_selected_unqif_index(self) -> Optional[int]:
        if not getattr(self, "_unqif_sorted", None):
            return None
        sel = self.lbx_unqif.curselection()
        if not sel:
            return None
        # stored as (bank_index, txn)
        bi, _ = self._unqif_sorted[sel[0]]
        return bi


    def _m_selected_unx_index(self) -> Optional[int]:
        if not getattr(self, "_unx_sorted", None):
            return None
        sel = self.lbx_unx.curselection()
        if not sel:
            return None
        # stored as (excel_index, txn)
        ei, _ = self._unx_sorted[sel[0]]
        return ei


    def _m_why_not(self):
        s = self._merge_session
        if not s:
            return
        bi = self._m_selected_unqif_index()
        if bi is None:
            self.mb.showinfo("Info", "Pick one unmatched QIF item to explain.")
            return
        self._m_info(s.nonmatch_reason(bank_index=bi))

    def _m_toggle_previews(self):
        show = bool(self.m_preview_var.get())
        for w in (self.prev_unqif, self.prev_pairs, self.prev_unx):
            try:
                if show:
                    w.pack(fill="x", padx=4, pady=(0, 4))
                else:
                    w.pack_forget()
            except Exception:
                pass
        if show:
            self._m_update_preview("unqif")
            self._m_update_preview("pairs")
            self._m_update_preview("unx")

    def _m_update_preview(self, which: str):
        if not self.m_preview_var.get():
            return
        try:
            if which == "unqif":
                idxs = self.lbx_unqif.curselection()
                if not idxs:
                    _set_text(self.prev_unqif, "")
                    return
                _bi, b = self._unqif_sorted[idxs[0]]
                _set_text(
                    self.prev_unqif,
                    _fmt_txn(
                        {
                            "date": b.date.isoformat(),
                            "amount": str(getattr(b, "amount", "")),
                            "payee": getattr(b, "payee", ""),
                            "category": getattr(b, "category", ""),
                            "memo": getattr(b, "memo", ""),
                        }
                    ),
                )

            elif which == "unx":
                idxs = self.lbx_unx.curselection()
                if not idxs:
                    _set_text(self.prev_unx, "")
                    return
                _ei, e = self._unx_sorted[idxs[0]]
                first = (e.splits or [None])[0]
                _set_text(
                    self.prev_unx,
                    _fmt_excel_row(
                        {
                            "TxnID": getattr(e, "id", ""),
                            "Date": e.date.isoformat(),
                            "Total Amount": getattr(e, "amount", ""),
                            "Split Count": len(e.splits or []),
                            "First Item": getattr(first, "memo", "") if first else "",
                            "First Category": getattr(first, "category", "")
                            if first
                            else "",
                            "First Rationale": getattr(e, "memo", ""),
                        }
                    ),
                )

            elif which == "pairs":
                idxs = self.lbx_pairs.curselection()
                if not idxs:
                    _set_text(self.prev_pairs, "")
                    return
                _bi, _ei, b, e = self._pairs_sorted[idxs[0]]
                excel_row = {
                    "TxnID": getattr(e, "id", ""),
                    "Date": e.date.isoformat(),
                    "Total Amount": getattr(e, "amount", ""),
                    "Split Count": len(e.splits or []),
                    "First Item": getattr((e.splits or [None])[0], "memo", "")
                    if e.splits
                    else "",
                    "First Category": getattr((e.splits or [None])[0], "category", "")
                    if e.splits
                    else "",
                    "First Rationale": getattr(e, "memo", ""),
                }
                qif_tx = {
                    "date": b.date.isoformat(),
                    "amount": str(getattr(b, "amount", "")),
                    "payee": getattr(b, "payee", ""),
                    "category": getattr(b, "category", ""),
                    "memo": getattr(b, "memo", ""),
                }
                _set_text(self.prev_pairs, "[Excel]\n" + _fmt_excel_row(excel_row) + "\n\n[QIF]\n" + _fmt_txn(qif_tx))
        except Exception as e:
            try:
                self._m_info(f"Preview error: {e}")
            except Exception:
                pass
