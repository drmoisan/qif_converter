# qif_converter/gui/merge_tab.py
from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog
from pathlib import Path
from typing import Optional
from qif_converter import qif_to_csv as mod
from qif_converter import match_excel as mex
from qif_converter.gui.helpers import _set_text, _fmt_excel_row, _fmt_txn

class MergeTab(ttk.Frame):
    """Primary function: Excel ↔ QIF merge + manual matching + previews."""
    def __init__(self, master, mb):
        super().__init__(master)
        self.mb = mb
        self._merge_session: Optional[mex.MatchSession] = None
        self._build()

    def _build(self):
        pad = {'padx': 8, 'pady': 6}

        self.m_qif_in = tk.StringVar()
        self.m_xlsx = tk.StringVar()
        self.m_qif_out = tk.StringVar()
        self.m_only_matched = tk.BooleanVar(value=False)
        self.m_preview_var = tk.BooleanVar(value=False)

        files = ttk.LabelFrame(self, text="Files")
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

        controls = ttk.Frame(self)
        controls.pack(anchor="w", padx=12, pady=(0, 6), fill="x")
        ttk.Checkbutton(controls, text="Output Only Matched Items",
                        variable=self.m_only_matched).pack(side="left")
        ttk.Checkbutton(controls, text="Preview Window",
                        variable=self.m_preview_var, command=self._m_toggle_previews).pack(side="left", padx=(12,0))

        actions = ttk.Frame(self)
        actions.pack(fill="x", **pad)
        ttk.Button(actions, text="Load + Auto-Match", command=self._m_load_and_auto).pack(side="left")
        ttk.Button(actions, text="Normalize Categories", command=self._m_normalize_categories).pack(side="left", padx=6)
        ttk.Button(actions, text="Apply Updates & Save", command=self._m_apply_and_save).pack(side="right")

        lists = ttk.Frame(self)
        lists.pack(fill="both", expand=True, **pad)

        # Left: Unmatched QIF
        left = ttk.LabelFrame(lists, text="Unmatched QIF items")
        left.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        left_container = ttk.Frame(left); left_container.pack(fill="both", expand=True)
        self.lbx_unqif = tk.Listbox(left_container, exportselection=False)
        self.lbx_unqif.pack(fill="both", expand=True, padx=4, pady=4)
        self.prev_unqif = tk.Text(left_container, height=8, wrap="word"); self.prev_unqif.pack_forget()

        # Middle: Matched pairs
        mid = ttk.LabelFrame(lists, text="Matched pairs")
        mid.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        mid_container = ttk.Frame(mid); mid_container.pack(fill="both", expand=True)
        self.lbx_pairs = tk.Listbox(mid_container, exportselection=False)
        self.lbx_pairs.pack(fill="both", expand=True, padx=4, pady=4)
        self.prev_pairs = tk.Text(mid_container, height=8, wrap="word"); self.prev_pairs.pack_forget()

        # Right: Unmatched Excel
        right = ttk.LabelFrame(lists, text="Unmatched Excel rows")
        right.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        right_container = ttk.Frame(right); right_container.pack(fill="both", expand=True)
        self.lbx_unx = tk.Listbox(right_container, exportselection=False)
        self.lbx_unx.pack(fill="both", expand=True, padx=4, pady=4)
        self.prev_unx = tk.Text(right_container, height=8, wrap="word"); self.prev_unx.pack_forget()

        self.lbx_unqif.bind("<<ListboxSelect>>", lambda e: self._m_update_preview("unqif"))
        self.lbx_pairs.bind("<<ListboxSelect>>", lambda e: self._m_update_preview("pairs"))
        self.lbx_unx.bind("<<ListboxSelect>>", lambda e: self._m_update_preview("unx"))

        # Footer: Manual match/unmatch + reason
        foot = ttk.Frame(self)
        foot.pack(fill="x", **pad)
        ttk.Button(foot, text="Match Selected →", command=self._m_manual_match).pack(side="left")
        ttk.Button(foot, text="Unmatch Selected", command=self._m_manual_unmatch).pack(side="left", padx=8)
        ttk.Button(foot, text="Why not matched?", command=self._m_why_not).pack(side="left", padx=8)

        infof = ttk.LabelFrame(self, text="Info")
        infof.pack(fill="x", **pad)
        self.txt_info = tk.Text(infof, height=6, wrap="word")
        self.txt_info.pack(fill="x", padx=8, pady=6)

    # ---------- file pickers ----------
    def _m_browse_qif(self):
        p = filedialog.askopenfilename(title="Select input QIF", filetypes=[("QIF files","*.qif"),("All files","*.*")])
        if p:
            self.m_qif_in.set(p)
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

    # ---------- actions ----------
    def _m_load_and_auto(self):
        try:
            qif_in = Path(self.m_qif_in.get().strip())
            xlsx = Path(self.m_xlsx.get().strip())
            if not qif_in.exists():
                self.mb.showerror("Error", "Please choose a valid input QIF."); return
            if not xlsx.exists():
                self.mb.showerror("Error", "Please choose a valid Excel (.xlsx)."); return

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
            self.mb.showerror("Error", str(e))

    def _m_manual_match(self):
        s = self._merge_session
        if not s:
            self.mb.showerror("Error", "No session loaded."); return
        qkey = self._m_selected_unqif_key()
        ei = self._m_selected_unx_idx()
        if qkey is None or ei is None:
            self.mb.showerror("Error", "Select one QIF item and one Excel row to match."); return
        ok, msg = s.manual_match(qkey, ei)
        self._m_info(("Matched." if ok else "Not matched.") + " " + msg)
        self._m_refresh_lists()

    def _m_manual_unmatch(self):
        s = self._merge_session
        if not s:
            return
        sel = self.lbx_pairs.curselection()
        if sel:
            pairs = s.matched_pairs()
            qv, er, _ = pairs[sel[0]]
            s.manual_unmatch(qkey=qv.key)
            self._m_info("Unmatched selected pair.")
            self._m_refresh_lists()
            return

        qkey = self._m_selected_unqif_key()
        if qkey is not None and s.manual_unmatch(qkey=qkey):
            self._m_info("Unmatched QIF item."); self._m_refresh_lists(); return
        ei = self._m_selected_unx_idx()
        if ei is not None and s.manual_unmatch(excel_idx=ei):
            self._m_info("Unmatched Excel row."); self._m_refresh_lists(); return
        self.mb.showinfo("Info", "Nothing selected to unmatch.")

    def _m_apply_and_save(self):
        try:
            s = self._merge_session
            if not s:
                self.mb.showerror("Error", "No session loaded. Click 'Load + Auto-Match' first."); return
            qif_out = Path(self.m_qif_out.get().strip())
            if not qif_out:
                self.mb.showerror("Error", "Please choose an output QIF file."); return
            if qif_out.exists():
                if not self.mb.askyesno("Confirm Overwrite", f"Output QIF already exists:\n\n{qif_out}\n\nOverwrite?"):
                    return
            s.apply_updates()
            txns_to_write = mex.build_matched_only_txns(s) if self.m_only_matched.get() else s.txns
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

    def open_normalize_modal(self):
        """
        Public entry point used by App to open the Normalize Categories modal.
        (Extracted from the old _m_normalize_categories so tests can call through App.)
        """
        try:
            qif_in = Path(self.m_qif_in.get().strip())
            xlsx = Path(self.m_xlsx.get().strip())
            if not qif_in.exists():
                self.mb.showerror("Error", "Please choose a valid input QIF.")
                return
            if not xlsx.exists():
                self.mb.showerror("Error", "Please choose a valid Excel (.xlsx).")
                return

            # Build session
            txns = mod.parse_qif(qif_in)
            qif_cats = mex.extract_qif_categories(txns)
            excel_cats = mex.extract_excel_categories(xlsx)
            sess = mex.CategoryMatchSession(qif_cats, excel_cats)

            # Parent to the toplevel hosting this tab
            parent = self.winfo_toplevel()
            win = tk.Toplevel(parent)
            win.title("Normalize Categories")
            win.geometry("900x520")
            win.transient(parent)
            win.grab_set()

            pad = {'padx': 8, 'pady': 6}

            # Top actions
            top = ttk.Frame(win); top.pack(fill="x", **pad)
            ttk.Button(top, text="Auto-Match",
                       command=lambda: (sess.auto_match(), refresh())).pack(side="left")
            ttk.Button(top, text="Match Selected →",
                       command=lambda: do_match()).pack(side="left", padx=6)
            ttk.Button(top, text="Unmatch Selected",
                       command=lambda: do_unmatch()).pack(side="left", padx=6)

            # Lists
            lists = ttk.Frame(win); lists.pack(fill="both", expand=True, **pad)

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
            bot = ttk.Frame(win); bot.pack(fill="x", **pad)
            out_path_var = tk.StringVar(
                value=str(xlsx.with_name(xlsx.stem + "_normalized.xlsx"))
            )
            ttk.Label(bot, text="Output Excel:").pack(side="left")
            ttk.Entry(bot, textvariable=out_path_var, width=60).pack(side="left", padx=6)
            ttk.Button(bot, text="Browse…", command=lambda: browse_out()).pack(side="left", padx=2)
            ttk.Button(bot, text="Apply & Save", command=lambda: apply_and_save()).pack(side="right")

            info = tk.Text(win, height=4, wrap="word")
            info.pack(fill="x", padx=8, pady=(0, 8))

            # --- helpers (closures) ---
            def refresh():
                lbx_qif.delete(0, "end")
                lbx_excel.delete(0, "end")
                lbx_pairs.delete(0, "end")
                uq, ue = sess.unmatched()
                for c in uq: lbx_qif.insert("end", c)
                for c in ue: lbx_excel.insert("end", c)
                for excel_name, qif_name in sorted(sess.mapping.items(), key=lambda kv: kv[0].lower()):
                    lbx_pairs.insert("end", f"{excel_name}  →  {qif_name}")
                info.delete("1.0", "end")
                info.insert(
                    "end",
                    f"QIF categories: {len(sess.qif_cats)} | "
                    f"Excel categories: {len(sess.excel_cats)} | "
                    f"Matched: {len(sess.mapping)} | "
                    f"Unmatched QIF: {len(uq)} | Unmatched Excel: {len(ue)}"
                )

            def selected(lbx: tk.Listbox):
                sel = lbx.curselection()
                return lbx.get(sel[0]) if sel else None

            def do_match():
                e = selected(lbx_excel); q = selected(lbx_qif)
                if not e or not q:
                    self.mb.showinfo("Info", "Select one Excel category and one QIF category to match.")
                    return
                ok, msg = sess.manual_match(e, q)
                if not ok:
                    self.mb.showerror("Error", msg)
                refresh()

            def do_unmatch():
                sel = lbx_pairs.curselection()
                if sel:
                    label = lbx_pairs.get(sel[0])
                    if "  →  " in label:
                        excel_name = label.split("  →  ", 1)[0]
                        sess.manual_unmatch(excel_name)
                        refresh()
                        return
                e = selected(lbx_excel)
                if e and sess.manual_unmatch(e):
                    refresh()
                    return
                self.mb.showinfo("Info", "Select a matched pair (middle list) or an Excel category to unmatch.")

            def browse_out():
                p = filedialog.asksaveasfilename(
                    title="Select normalized Excel output",
                    defaultextension=".xlsx",
                    filetypes=[("Excel files","*.xlsx"),("All files","*.*")],
                )
                if p:
                    out_path_var.set(p)

            def apply_and_save():
                outp = Path(out_path_var.get().strip())
                if outp.exists():
                    if not self.mb.askyesno("Confirm Overwrite", f"{outp}\n\nOverwrite?"):
                        return
                try:
                    out_file = sess.apply_to_excel(xlsx, xlsx_out=outp)
                    self.mb.showinfo("Done", f"Normalized Excel written:\n{out_file}")
                    win.destroy()
                except Exception as e:
                    self.mb.showerror("Error", str(e))

            # initial population
            refresh()
            return win  # (optional) return the modal window, handy for tests

        except Exception as e:
            self.mb.showerror("Error", str(e))

    # Backward-compatible private name (kept; just forwards)
    def _m_normalize_categories(self):
        return self.open_normalize_modal()


    # ---------- list/preview plumbing ----------
    def _m_refresh_lists(self):
        self.lbx_pairs.delete(0, "end")
        self.lbx_unqif.delete(0, "end")
        self.lbx_unx.delete(0, "end")
        s = self._merge_session
        if not s:
            self.m_pairs = [];
            self.m_unmatched_qif = [];
            self.m_unmatched_excel = [];
            return

        # ---------- Matched pairs ----------
        pairs_preview = []
        for q, er, cost in sorted(s.matched_pairs(), key=lambda t: (t[0].date, t[1].date)):
            label = (f"[d+{cost}] QIF#{q.key.txn_index}{('/S' + str(q.key.split_index)) if q.key.is_split() else ''} "
                     f"{q.date.isoformat()} {q.amount} |→ Excel#{er.idx} {er.date.isoformat()} {er.amount} | {er.item}")
            self.lbx_pairs.insert("end", label)
            qif_dict = {
                "date": getattr(q, "date", None) and q.date.isoformat(),
                "amount": getattr(q, "amount", ""),
                "payee": getattr(q, "payee", ""),
                "category": getattr(q, "category", ""),
                "memo": getattr(q, "memo", ""),
                "transfer_account": getattr(getattr(q, "key", None), "transfer_account", ""),
            }
            excel_dict = {
                "Date": getattr(er, "date", None) and er.date.isoformat(),
                "Amount": getattr(er, "amount", ""),
                "Item": getattr(er, "item", ""),
                "Canonical MECE Category": getattr(er, "category", ""),
                "Categorization Rationale": getattr(er, "rationale", ""),
            }
            pairs_preview.append((excel_dict, qif_dict))

        # ---------- Unmatched QIF ----------
        unqif_preview = []
        for q in sorted(s.unmatched_qif(), key=lambda x: x.date):
            label = (f"QIF#{q.key.txn_index}{('/S' + str(q.key.split_index)) if q.key.is_split() else ''} "
                     f"{q.date.isoformat()} {q.amount} | {q.payee} | {q.memo or q.category}")
            self.lbx_unqif.insert("end", label)
            unqif_preview.append({
                "date": q.date.isoformat(), "amount": q.amount,
                "payee": getattr(q, "payee", ""), "category": getattr(q, "category", ""),
                "memo": getattr(q, "memo", ""),
                "transfer_account": getattr(getattr(q, "key", None), "transfer_account", ""),
                "splits": [{"category": getattr(sp, "category", ""), "memo": getattr(sp, "memo", ""),
                            "amount": getattr(sp, "amount", "")}
                           for sp in getattr(q, "splits", []) or []],
            })

        # ---------- Unmatched Excel ----------
        unx_preview = []
        for er in sorted(s.unmatched_excel(), key=lambda x: x.date):
            label = f"Excel#{er.idx} {er.date.isoformat()} {er.amount} | {er.item} | {er.category}"
            self.lbx_unx.insert("end", label)
            unx_preview.append({
                "Date": er.date.isoformat(), "Amount": er.amount, "Item": getattr(er, "item", ""),
                "Canonical MECE Category": getattr(er, "category", ""),
                "Categorization Rationale": getattr(er, "rationale", ""),
            })

        self.m_pairs = pairs_preview
        self.m_unmatched_qif = unqif_preview
        self.m_unmatched_excel = unx_preview

        if self.m_preview_var.get():
            self._m_update_preview("pairs")
            self._m_update_preview("unqif")
            self._m_update_preview("unx")

    def _m_selected_unqif_key(self) -> Optional[mex.QIFItemKey]:
        s = self._merge_session
        if not s: return None
        sel = self.lbx_unqif.curselection()
        if not sel: return None
        q = s.unmatched_qif()[sel[0]]
        return q.key

    def _m_selected_unx_idx(self) -> Optional[int]:
        s = self._merge_session
        if not s: return None
        sel = self.lbx_unx.curselection()
        if not sel: return None
        er = s.unmatched_excel()[sel[0]]
        return er.idx

    def _m_why_not(self):
        s = self._merge_session
        if not s: return
        sel_q = self._m_selected_unqif_key()
        sel_e = self._m_selected_unx_idx()
        if sel_q is None or sel_e is None:
            self.mb.showinfo("Info", "Pick one unmatched QIF and one unmatched Excel to explain."); return
        q = next(x for x in s.unmatched_qif() if x.key == sel_q)
        er = next(x for x in s.unmatched_excel() if x.idx == sel_e)
        self._m_info(s.nonmatch_reason(q, er))

    def _m_toggle_previews(self):
        show = bool(self.m_preview_var.get())
        for w in (self.prev_unqif, self.prev_pairs, self.prev_unx):
            try:
                if show: w.pack(fill="x", padx=4, pady=(0,4))
                else: w.pack_forget()
            except Exception: pass
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
                tx = self.m_unmatched_qif[idxs[0]] if idxs else {}
                _set_text(self.prev_unqif, _fmt_txn(tx))
            elif which == "unx":
                idxs = self.lbx_unx.curselection()
                row = self.m_unmatched_excel[idxs[0]] if idxs else {}
                _set_text(self.prev_unx, _fmt_excel_row(row))
            elif which == "pairs":
                idxs = self.lbx_pairs.curselection()
                text = ""
                if idxs:
                    excel_row, qif_tx = self.m_pairs[idxs[0]]
                    text = "[Excel]\n" + _fmt_excel_row(excel_row) + "\n\n[QIF]\n" + _fmt_txn(qif_tx)
                _set_text(self.prev_pairs, text)
        except Exception:
            pass
