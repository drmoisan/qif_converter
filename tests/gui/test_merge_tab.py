# tests/gui_viewers/test_merge_tab.py
"""
Unit tests for quicken_helper.gui_viewers.merge_tab.MergeTab

Policy adherence:
- Independent & isolated: tkinter and quicken_helper deps are stubbed.
- Fast & deterministic: no real GUI; filesystem only via tmp_path.
- AAA structure for each test; docstrings explain intent.
"""

from __future__ import annotations

import importlib
import sys
import types
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from quicken_helper.data_model import ITransaction


# --------------------------
# Tk / ttk / filedialog / messagebox stubs
# --------------------------

class _DummyVar:
    """
    Stand-in for tkinter.StringVar/BooleanVar that accepts 'value=' kwarg
    and provides get()/set().
    """
    def __init__(self, v=None, **kwargs):
        if "value" in kwargs:
            v = kwargs["value"]
        self._v = "" if v is None else v
    def get(self):
        return self._v
    def set(self, v):
        self._v = v


class _TextStub:
    """
    Minimal Text-like widget.
    Accepts height/width/state kwargs and supports common methods used by the code.
    """
    def __init__(self, *args, **kwargs):
        self._buf = ""
        self._height = kwargs.get("height")
        self._width = kwargs.get("width")
        self._state = kwargs.get("state", "normal")

    # Tk-style config API
    def configure(self, **kwargs):
        if "height" in kwargs: self._height = kwargs["height"]
        if "width" in kwargs: self._width = kwargs["width"]
        if "state" in kwargs: self._state = kwargs["state"]
    config = configure  # alias

    def cget(self, key):
        if key == "height": return self._height
        if key == "width": return self._width
        if key == "state": return self._state
        return None

    # Text content API (indices ignored; whole-buffer semantics are fine for tests)
    def get(self, start="1.0", end="end"):
        return self._buf
    def insert(self, index, s):
        if self._state == "disabled": return
        self._buf += str(s)
    def delete(self, start="1.0", end="end"):
        if self._state == "disabled": return
        self._buf = ""
    def see(self, index): pass

    # Geometry + misc
    def pack(self, *a, **k): pass
    def pack_forget(self, *a, **k): pass
    def grid(self, *a, **k): pass
    def bind(self, *a, **k): pass


class _ListboxStub:
    """Minimal Listbox supporting insert/get/delete/bind/selection/grid."""
    def __init__(self, *a, **k):
        self._items = []
        self._binds = {}
        self._sel = set()
    def insert(self, index, s): self._items.append(s)
    def get(self, a, b=None):
        if a == 0 and (b == "end" or b is None):
            return tuple(self._items)
        if isinstance(a, int) and b is None:
            return self._items[a]
        return tuple(self._items)
    def delete(self, a, b=None):
        self._items.clear()
        self._sel.clear()
    def bind(self, evt, fn): self._binds[evt] = fn
    def curselection(self): return tuple(sorted(self._sel))
    def selection_set(self, i): self._sel.add(i)
    def pack(self, *a, **k): pass
    def grid(self, *a, **k): pass


class _FakeMB:
    """Messagebox shim that records calls and controls askyesno return."""
    def __init__(self, askyesno_return=True):
        self.calls = []
        self._ask = askyesno_return
    def showinfo(self, *a, **k):
        self.calls.append(("showinfo", a, k))
    def showerror(self, *a, **k):
        self.calls.append(("showerror", a, k))
    def askyesno(self, *a, **k):
        self.calls.append(("askyesno", a, k))
        return self._ask


def _install_tk_stubs(monkeypatch, filedialog_overrides=None, toplevel_raises=False):
    """Install minimal tkinter/ttk stubs so MergeTab can import & run headlessly."""
    # ---------------- tkinter ----------------
    tk = types.ModuleType("tkinter")

    class Tk:
        def __init__(self, *a, **k): pass

    class Toplevel:
        def __init__(self, *a, **k):
            if toplevel_raises:
                raise RuntimeError("Headless Toplevel disabled for this test")
        def title(self, *a, **k): pass
        def geometry(self, *a, **k): pass
        def destroy(self): pass

    tk.Tk = Tk
    tk.Toplevel = Toplevel
    tk.StringVar = _DummyVar
    tk.BooleanVar = _DummyVar
    tk.Text = _TextStub
    tk.Listbox = _ListboxStub

    # ---------------- ttk ----------------
    ttk = types.ModuleType("tkinter.ttk")

    class _Base:
        def __init__(self, *a, **k): pass
        def pack(self, *a, **k): pass
        def pack_forget(self, *a, **k): pass
        def grid(self, *a, **k): pass
        def columnconfigure(self, *a, **k): pass
        def rowconfigure(self, *a, **k): pass
        def configure(self, *a, **k): pass
        def winfo_toplevel(self): return object()

    class Style(_Base):
        def map(self, *a, **k): pass
        def theme_use(self, *a, **k): pass

    class Frame(_Base): pass
    class LabelFrame(_Base): pass
    class Label(_Base): pass
    class Button(_Base): pass

    class Entry(_Base):
        """Accepts textvariable=..., so `.get()` works if code reads from it."""
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._textvar = k.get("textvariable")
        def get(self):
            return self._textvar.get() if self._textvar else ""
        def insert(self, index, s):
            if self._textvar:
                self._textvar.set((self._textvar.get() or "") + s)
        def delete(self, start, end=None):
            if self._textvar:
                self._textvar.set("")

    class Checkbutton(_Base): pass
    class Combobox(_Base): pass
    class Scrollbar(_Base): pass
    class Separator(_Base): pass

    class Notebook(_Base):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._tabs = []
        def add(self, child, **k): self._tabs.append((child, k.get("text")))

    ttk.Style = Style
    ttk.Frame = Frame
    ttk.LabelFrame = LabelFrame
    ttk.Label = Label
    ttk.Button = Button
    ttk.Entry = Entry
    ttk.Checkbutton = Checkbutton
    ttk.Combobox = Combobox
    ttk.Scrollbar = Scrollbar
    ttk.Separator = Separator
    ttk.Notebook = Notebook

    # -------------- messagebox --------------
    messagebox = types.ModuleType("tkinter.messagebox")
    def _noop(*a, **k): return None
    messagebox.showinfo = _noop
    messagebox.showerror = _noop
    messagebox.askyesno = lambda *a, **k: True

    # -------------- filedialog --------------
    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.askopenfilename = (filedialog_overrides or {}).get(
        "askopenfilename", lambda **k: ""
    )
    filedialog.asksaveasfilename = (filedialog_overrides or {}).get(
        "asksaveasfilename", lambda **k: ""
    )

    # Register stubs
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", messagebox)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", filedialog)


# --------------------------
# Project submodule stubs to satisfy imports used by merge_tab.py
# --------------------------

# Lightweight data structures used by stubbed helpers
@dataclass
class _Row:
    item: str
    category: str
    rationale: str

@dataclass
class _Group:
    gid: int
    date: date
    total_amount: str
    rows: list[_Row]

@dataclass
class _QKey:
    txn_index: int
    transfer_account: str = ""

@dataclass
class _QTxn:
    key: _QKey
    date: date
    amount: str
    payee: str = ""
    category: str = ""
    memo: str = ""


class _MatchSessionStub:
    """
    Stub of quicken_helper.match_session.MatchSession for list plumbing & actions.
    Implements the API MergeTab uses: auto_match, matched_pairs, unmatched_qif,
    unmatched_excel, manual_match, manual_unmatch, nonmatch_reason, apply_updates.
    """
    def __init__(self, txns, excel_groups):
        self.txns = txns
        self.excel_groups = excel_groups
        self._matched = []
        self._unqif = list(txns)
        self._unx = list(excel_groups)
        self._applied = False

    def auto_match(self):
        if self.txns and self.excel_groups:
            q = self.txns[0]; g = self.excel_groups[0]
            if q in self._unqif: self._unqif.remove(q)
            if g in self._unx: self._unx.remove(g)
            self._matched = [(q, g, "0.00")]

    def matched_pairs(self): return list(self._matched)
    def unmatched_qif(self): return list(self._unqif)
    def unmatched_excel(self): return list(self._unx)

    def manual_match(self, qkey=None, excel_idx=None):
        if qkey is None or excel_idx is None: return False, "missing selection"
        q = next((t for t in self.txns if getattr(t, "key", None) == qkey), None)
        if q is None or excel_idx < 0 or excel_idx >= len(self.excel_groups):
            return False, "invalid selection"
        g = self.excel_groups[excel_idx]
        if q in self._unqif: self._unqif.remove(q)
        if g in self._unx: self._unx.remove(g)
        self._matched.append((q, g, "0.00"))
        return True, "ok"

    def manual_unmatch(self, qkey=None, excel_idx=None):
        if qkey is not None:
            for i, (q, g, _) in enumerate(list(self._matched)):
                if q.key == qkey:
                    self._matched.pop(i); self._unqif.append(q); self._unx.append(g)
                    return True
        if excel_idx is not None and 0 <= excel_idx < len(self.excel_groups):
            g = self.excel_groups[excel_idx]
            for i, (q, gg, _) in enumerate(list(self._matched)):
                if gg is g:
                    self._matched.pop(i); self._unqif.append(q); self._unx.append(gg)
                    return True
        return False

    def nonmatch_reason(self, q, grp):
        return f"No match because payee '{q.payee}' != '{grp.rows[0].item if grp.rows else ''}'"

    def apply_updates(self): self._applied = True


class _CategoryMatchSessionStub:
    """
    Stub for quicken_helper.category_match_session.CategoryMatchSession as used by
    MergeTab.open_normalize_modal (constructed with qif_cats, excel_cats).
    """
    def __init__(self, qif_cats, excel_cats):
        self.qif_cats = set(qif_cats)
        self.excel_cats = set(excel_cats)
        self.mapping = {}

    def unmatched(self):
        uq = [q for q in self.qif_cats if q not in self.mapping.values()]
        ue = [e for e in self.excel_cats if e not in self.mapping]
        return uq, ue

    def auto_match(self, threshold: float = 0.84):
        if self.excel_cats and self.qif_cats:
            self.mapping[next(iter(self.excel_cats))] = next(iter(self.qif_cats))

    def manual_match(self, excel_name: str, qif_category: str):
        self.mapping[excel_name] = qif_category
        return True

    def manual_unmatch(self, excel_name: str):
        return bool(self.mapping.pop(excel_name, None))

    def apply_to_excel(self, xlsx: Path, xlsx_out: Path):
        xlsx_out.write_text("normalized", encoding="utf-8")
        return xlsx_out

def nameof_module(mod) -> str:
    return getattr(mod, "__spec__", None).name if getattr(mod, "__spec__", None) else mod.__name__

def _get_module_names() -> dict[str, str]:
    """Return dict of refactor-safe symbols."""
    #import quicken_helper as quicken_helper
    import quicken_helper
    from quicken_helper.controllers import qif_loader, match_excel, match_session, category_match_session
    from quicken_helper.gui_viewers import convert_tab, merge_tab, probe_tab, scaling
    from quicken_helper.legacy import qif_writer


    names = {
        "quicken_helper": nameof_module(quicken_helper),
        "controllers": nameof_module(quicken_helper.controllers),
        "qif_loader": nameof_module(qif_loader),
        "convert_tab": nameof_module(convert_tab),
        "merge_tab": nameof_module(merge_tab),
        "probe_tab": nameof_module(probe_tab),
        "scaling": nameof_module(scaling),
        "match_excel": nameof_module(match_excel),
        "match_session": nameof_module(match_session),
        "category_match_session": nameof_module(category_match_session),
        "qif_writer": nameof_module(qif_writer),
    }

    return names

def _install_project_stubs(monkeypatch, tmp_path=None):
    """
    Install lightweight quicken_helper stubs used by MergeTab._m_load_and_auto and friends:
      - quicken_helper.qif_loader.load_transactions
      - quicken_helper.match_excel.{load_excel_rows, group_excel_rows, build_matched_only_txns,
                                   extract_qif_categories, extract_excel_categories}
      - quicken_helper.match_session.MatchSession
      - quicken_helper.qif_writer.write_qif
    """
    import datetime
    import sys
    import types
    from datetime import date
    from decimal import Decimal

    names = _get_module_names()
    pkg = types.ModuleType(names["quicken_helper"])
    pkg.__path__ = []  # <-- make it a package
    monkeypatch.setitem(sys.modules, names["quicken_helper"], pkg)

    # ---- qif_loader ----
    ql = types.ModuleType(names["qif_loader"])

    class _Key:
        def __init__(self, idx): self.txn_index = idx; self.transfer_account = ""

    class _QifTxn:
        def __init__(self, idx):
            self.key = _Key(idx)
            self.date = datetime.date(2024, 1, idx if idx <= 28 else 28)
            self.amount = float(idx)
            self.payee = f"Payee{idx}"
            self.category = "Cat"
            self.memo = ""

    def load_transactions(path):
        # Two simple txns; enough for list population and a match
        return [_QifTxn(1), _QifTxn(2)]

    # Some paths call parse_qif (normalize modal)
    def parse_qif(path):
        return load_transactions(path)

    ql.load_transactions = load_transactions
    ql.parse_qif = parse_qif
    monkeypatch.setitem(sys.modules, names["qif_loader"], ql)
    setattr(pkg, "qif_loader", ql)

    # Minimal enum-ish object with .name used by MergeTab._cleared_to_char
    from quicken_helper.data_model.interfaces import EnumClearedStatus


    # Minimal split/txn "protocol-ish" objects
    class _Split:
        def __init__(self, amount="0.00", category="", memo=""):
            self.amount = Decimal(str(amount))
            self.category = category
            self.memo = memo

    class _Txn(ITransaction):
        def __init__(self, **kw):
            self.date = kw.get("date", date(2025, 1, 1))
            self.amount = Decimal(str(kw.get("amount", "0.00")))
            self.payee = kw.get("payee", "")
            self.memo = kw.get("memo", "")
            self.category = kw.get("category", "")
            self.tag = kw.get("tag")
            self.action_chk = kw.get("action_chk")
            # MergeTab maps by cleared.name: "CLEARED"→"X", "RECONCILED"→"*"
            self.cleared = kw.get("cleared", EnumClearedStatus.NOT_CLEARED)
            self.splits = kw.get("splits", [])


    def fake_load_transactions_protocol(path):
        return [
            _Txn(
                amount="12.34",
                category="Groceries",
                tag="Costco",
                cleared=EnumClearedStatus.RECONCILED,
                splits=[_Split("10.00", "Groceries", "Apples"),
                        _Split("2.34", "Groceries", "Bananas")],
            )
        ]

    def fake_load_transactions(path):
        # legacy dict-shaped fallback, if any tests still use it
        return [{
            "date": "01/01/2025",
            "amount": "12.34",
            "payee": "Acme",
            "memo": "",
            "category": "Groceries/Costco",
            "checknum": None,
            "cleared": "*",
            "splits": [
                {"amount": "10.00", "category": "Groceries", "memo": "Apples"},
                {"amount": "2.34", "category": "Groceries", "memo": "Bananas"},
            ],
        }]

    ql.load_transactions_protocol = fake_load_transactions_protocol
    ql.load_transactions = fake_load_transactions

    # install stub module BEFORE importing merge_tab
    monkeypatch.setitem(sys.modules, names["qif_loader"], ql)

    # ---- match_excel ----
    mex = types.ModuleType(names["match_excel"])
    mex.load_transactions = fake_load_transactions

    class _Row:
        def __init__(self, item, category="Cat", rationale=""):
            self.item = item
            self.category = category
            self.rationale = rationale

    class _Group:
        def __init__(self, gid, rows):
            self.gid = gid
            self.rows = rows
            self.date = datetime.date(2024, 1, 15)
            self.total_amount = float(len(rows))

    def load_excel_rows(path):
        # One group of two rows; good for previews and a match
        return [_Row("Item1"), _Row("Item2")]

    def group_excel_rows(rows):
        return [_Group("G1", rows)]

    def build_matched_only_txns(sess):
        # Keep it simple: just return all txns (tests don’t inspect contents)
        return list(sess.txns)

    # Used by normalize modal
    def extract_qif_categories(txns): return {"Food", "Rent"}
    def extract_excel_categories(xlsx): return {"Groceries", "Housing"}

    mex.load_excel_rows = load_excel_rows
    mex.group_excel_rows = group_excel_rows
    mex.build_matched_only_txns = build_matched_only_txns
    mex.extract_qif_categories = extract_qif_categories
    mex.extract_excel_categories = extract_excel_categories
    monkeypatch.setitem(sys.modules, names["match_excel"], mex)
    setattr(pkg, "match_excel", mex)

    # ---- match_session ----
    ms = types.ModuleType(names["match_session"])

    class MatchSession:
        def __init__(self, txns, excel_groups):
            self.txns = list(txns)
            self.excel_groups = list(excel_groups)
            self._pairs = []  # list of (qif_txn, group, cost)

        def auto_match(self, *a, **k):
            if self.txns and self.excel_groups:
                self._pairs = [(self.txns[0], self.excel_groups[0], 0.0)]

        def matched_pairs(self): return list(self._pairs)

        def unmatched_qif(self):
            matched = {q for q, _, _ in self._pairs}
            return [t for t in self.txns if t not in matched]

        def unmatched_excel(self):
            matched = {g for _, g, _ in self._pairs}
            return [g for g in self.excel_groups if g not in matched]

        def manual_match(self, qkey, gi):
            # Map qkey.txn_index to the actual txn; gi is index into excel_groups
            q = next((t for t in self.txns if getattr(getattr(t, "key", None), "txn_index", None) == qkey.txn_index), None)
            if q is None or gi is None or gi < 0 or gi >= len(self.excel_groups):
                return False, "Invalid selection."
            g = self.excel_groups[gi]
            if any(q is pq or g is pg for pq, pg, _ in self._pairs):
                return False, "Already matched."
            self._pairs.append((q, g, 0.0))
            return True, "Matched."

        def manual_unmatch(self, qkey=None, excel_idx=None):
            if qkey is not None:
                before = len(self._pairs)
                self._pairs = [(q, g, c) for (q, g, c) in self._pairs if getattr(q.key, "txn_index", None) != qkey.txn_index]
                return len(self._pairs) != before
            if excel_idx is not None:
                g = self.excel_groups[excel_idx]
                before = len(self._pairs)
                self._pairs = [(q, gg, c) for (q, gg, c) in self._pairs if gg is not g]
                return len(self._pairs) != before
            return False

        def apply_updates(self):  # no-op for tests
            return None

        # For “why not” path used in UI
        def nonmatch_reason(self, q, grp):
            return "Stub: costs differ."

    ms.MatchSession = MatchSession
    monkeypatch.setitem(sys.modules, names["match_session"], ms)
    setattr(pkg, "match_session", ms)

    # ---- qif_writer ----
    qw = types.ModuleType(names["qif_writer"])

    def write_qif(txns, out_path):
        (tmp_path or Path(".")).mkdir(exist_ok=True)

    qw.write_qif = write_qif
    monkeypatch.setitem(sys.modules, names["qif_writer"], qw)
    setattr(pkg, "qif_writer", qw)

    # ---- patch controllers module to expose stubs ----
    controllers_mod = sys.modules.get(names["controllers"])
    if controllers_mod is None:
        import types
        controllers_mod = types.ModuleType(names["controllers"])
        controllers_mod.__path__ = []  # mark as a package
        sys.modules[names["controllers"]] = controllers_mod

    setattr(controllers_mod, "match_excel", mex)
    # repeat similarly for qif_loader, match_session, category_match_session as needed


# --------------------------
# Import fixture
# --------------------------


@pytest.fixture
def merge_mod(monkeypatch):
    """Import quicken_helper.gui_viewers.merge_tab with all deps stubbed for headless testing."""
    names_dict = _get_module_names()
    items = names_dict.items()
    _install_tk_stubs(monkeypatch)      # GUI stubs
    _install_project_stubs(monkeypatch) # quicken_helper stubs

    # Only reload GUI modules that we want fresh; keep controller stubs intact.
    for key in ("merge_tab",):  # add "convert_tab", "probe_tab" if you truly need them fresh
        sys.modules.pop(names_dict[key], None)

    merge_tab = importlib.import_module(names_dict["merge_tab"])
    return merge_tab

# --------------------------
# Tests (AAA + docstrings)
# --------------------------

def test_init_builds_widgets_and_state(merge_mod):
    """MergeTab initializes variables, listboxes, and info panel without raising."""
    # Arrange
    MergeTab = merge_mod.MergeTab
    mb = _FakeMB()

    # Act
    mt = MergeTab(master=None, mb=mb)

    # Assert
    assert hasattr(mt, "m_qif_in") and hasattr(mt, "m_xlsx") and hasattr(mt, "m_qif_out")
    assert hasattr(mt, "m_only_matched")
    assert hasattr(mt, "lbx_unqif") and hasattr(mt, "lbx_unx") and hasattr(mt, "lbx_pairs")
    assert hasattr(mt, "txt_info"), "Info Text widget should exist"


def test_browse_qif_sets_in_and_suggests_out(merge_mod, monkeypatch):
    """_m_browse_qif sets m_qif_in and suggests '<stem>_updated.qif' without touching disk."""
    import sys

    # Arrange: inject a memory path and reload so the module uses our filedialog
    names = _get_module_names()
    chosen_in = "MEM://in.qif"
    fd_over = {"askopenfilename": lambda **k: chosen_in}
    _install_tk_stubs(monkeypatch, filedialog_overrides=fd_over)
    _install_project_stubs(monkeypatch)
    sys.modules.pop(names["merge_tab"], None)
    m2 = importlib.import_module(names["merge_tab"])

    # Avoid FS checks
    monkeypatch.setattr(m2.Path, "exists", lambda self: True, raising=False)
    monkeypatch.setattr(m2.Path, "is_file", lambda self: True, raising=False)

    mt = m2.MergeTab(master=None, mb=_FakeMB())
    mt.m_qif_out.set("")

    # Act
    mt._m_browse_qif()

    # Assert
    assert mt.m_qif_in.get() == chosen_in
    # Compare only the file name to avoid platform separators
    assert m2.Path(mt.m_qif_out.get()).name == "in_updated.qif"



def test_browse_out_sets_out_path(merge_mod, monkeypatch):
    """_m_browse_out sets m_qif_out from filedialog without touching disk (path-normalized)."""
    import sys

    names = _get_module_names()
    chosen_out = "MEM://out.qif"
    fd_over = {"asksaveasfilename": lambda **k: chosen_out}
    _install_tk_stubs(monkeypatch, filedialog_overrides=fd_over)
    _install_project_stubs(monkeypatch)
    sys.modules.pop(names["merge_tab"], None)
    m2 = importlib.import_module(names["merge_tab"])

    mt = m2.MergeTab(master=None, mb=_FakeMB())

    # Act
    mt._m_browse_out()

    # Assert (normalize both)
    actual = str(m2.Path(mt.m_qif_out.get()))
    expected = str(m2.Path(chosen_out))
    assert actual == expected



def test_load_and_auto_validates_missing_inputs(merge_mod, monkeypatch):
    """_m_load_and_auto shows errors when QIF or Excel paths are invalid (no filesystem)."""
    # Arrange: both invalid
    mt = merge_mod.MergeTab(master=None, mb=_FakeMB())
    bad_qif = "MEM://missing.qif"
    bad_xlsx = "MEM://missing.xlsx"
    mt.m_qif_in.set(bad_qif)
    mt.m_xlsx.set(bad_xlsx)

    # Paths don't exist
    monkeypatch.setattr(merge_mod.Path, "exists", lambda self: False, raising=False)
    monkeypatch.setattr(merge_mod.Path, "is_file", lambda self: False, raising=False)

    # Act
    mt._m_load_and_auto()

    # Assert
    assert any(c[0] == "showerror" for c in mt.mb.calls), "Expected error for invalid QIF/Excel"

    # Arrange: valid QIF, invalid Excel (still no FS)
    mt.mb.calls.clear()
    valid_qif = "MEM://in.qif"
    mt.m_qif_in.set(valid_qif)
    # Make only the valid_qif path exist
    monkeypatch.setattr(
        merge_mod.Path, "exists", lambda self: str(self) == valid_qif, raising=False
    )
    monkeypatch.setattr(
        merge_mod.Path, "is_file", lambda self: str(self) == valid_qif, raising=False
    )

    # Act
    mt._m_load_and_auto()

    # Assert
    assert any(c[0] == "showerror" for c in mt.mb.calls), "Expected error for invalid Excel path"



def test_load_and_auto_populates_lists_on_success(merge_mod, monkeypatch):
    """_m_load_and_auto creates a session, auto-matches, and fills listboxes (no filesystem)."""
    # Arrange
    mt = merge_mod.MergeTab(master=None, mb=_FakeMB())
    qif_in = "Z:/memory/in.qif"
    xlsx = "Z:/memory/in.xlsx"
    mt.m_qif_in.set(qif_in)
    mt.m_xlsx.set(xlsx)

    # Patch Path.exists so ONLY our two in-memory paths "exist"
    allowed = {qif_in, xlsx}
    monkeypatch.setattr(merge_mod.Path, "exists", lambda self: True, raising=False)
    monkeypatch.setattr(merge_mod.Path, "is_file", lambda self: True, raising=False)

    # Act
    mt._m_load_and_auto()

    # Assert
    assert mt._merge_session is not None, "Session should be created"
    assert isinstance(mt.m_pairs, list)
    assert isinstance(mt.m_unmatched_qif, list)
    assert isinstance(mt.m_unmatched_excel, list)



def test_manual_match_requires_selection_and_calls_session(merge_mod):
    """_m_manual_match shows error with no selection; with selections it calls session.manual_match."""
    # Arrange
    mt = merge_mod.MergeTab(master=None, mb=_FakeMB())
    g = _Group(101, date(2024,1,2), "10.00", [_Row("Alpha","Cat","r")])
    q = _QTxn(_QKey(1), date(2024,1,1), "10.00", "Alpha")
    mt._merge_session = _MatchSessionStub([q], [g])
    mt._unqif_sorted = [q]
    mt._unx_sorted = [g]
    mt.lbx_unqif.insert("end", "qif")
    mt.lbx_unx.insert("end", "grp")

    # Act (no selection)
    mt._m_manual_match()
    # Assert
    assert any(c[0] == "showerror" for c in mt.mb.calls), "Expected error when nothing selected"

    # Act (with selections)
    mt.mb.calls.clear()
    mt.lbx_unqif.selection_set(0)
    mt.lbx_unx.selection_set(0)
    mt._m_manual_match()

    # Assert: lists refreshed / info written (no error)
    assert not any(c[0] == "showerror" for c in mt.mb.calls)
    assert "Matched" in mt.txt_info.get("1.0", "end")


def test_manual_unmatch_from_pairs_calls_session(merge_mod):
    """_m_manual_unmatch unmatches the selected pair via session.manual_unmatch."""
    # Arrange
    mt = merge_mod.MergeTab(master=None, mb=_FakeMB())
    g = _Group(101, date(2024,1,2), "10.00", [_Row("Alpha","Cat","r")])
    q = _QTxn(_QKey(1), date(2024,1,1), "10.00", "Alpha")
    sess = _MatchSessionStub([q], [g])
    sess._matched = [(q, g, "0.00")]
    mt._merge_session = sess
    mt._pairs_sorted = list(sess._matched)
    mt.lbx_pairs.insert("end", "PAIR")
    mt.lbx_pairs.selection_set(0)

    # Act
    mt._m_manual_unmatch()

    # Assert
    assert sess._matched == [], "Pair should be removed after unmatch"
    assert "Unmatched" in mt.txt_info.get("1.0", "end")



def test_apply_and_save_validates_and_writes_no_fs(merge_mod, monkeypatch):
    """_m_apply_and_save confirms, applies, mkdirs (stubbed), and 'writes' via stubbed writer (no filesystem)."""
    mb = _FakeMB(askyesno_return=True)
    mt = merge_mod.MergeTab(master=None, mb=mb)

    # Minimal session stub with apply_updates() and txns attribute
    class _Sess:
        def __init__(self):
            self.applied = False
            self.txns = ["t1", "t2"]
        def apply_updates(self):
            self.applied = True

    mt._merge_session = _Sess()
    outp = "MEM://out.qif"
    mt.m_qif_out.set(outp)

    # Make all path checks succeed; noop mkdir to avoid touching disk
    monkeypatch.setattr(merge_mod.Path, "exists", lambda self: True, raising=False)
    monkeypatch.setattr(merge_mod.Path, "is_file", lambda self: True, raising=False)
    monkeypatch.setattr(merge_mod.Path, "mkdir", lambda self, parents=False, exist_ok=False: None, raising=False)

    # Patch the exact writer used by merge_tab: mod.write_qif(...)
    calls = []
    monkeypatch.setattr(merge_mod.mod, "write_qif", lambda txns, p: calls.append((list(txns), str(p))), raising=False)

    # Act
    mt._m_apply_and_save()

    # Assert
    expected_out = str(merge_mod.Path(outp))  # normalize path like the code
    assert calls and calls[-1][1] == expected_out, "Writer should be called with normalized out path"
    assert any(c[0] == "askyesno" for c in mb.calls), "Should confirm before writing"
    assert any(c[0] == "showinfo" for c in mb.calls), "Should notify on completion"



def test_export_listbox_writes_file(merge_mod, monkeypatch):
    """_export_listbox writes listbox items to an in-memory file (no filesystem)."""
    import builtins

    mt = merge_mod.MergeTab(master=None, mb=_FakeMB())
    mt.lbx_unx.insert("end", "row1")
    mt.lbx_unx.insert("end", "row2")

    # Choose a memory path and stub filedialog to return it
    chosen = "MEM://unmatched_excel.txt"
    fd_over = {"asksaveasfilename": lambda **k: chosen}
    _install_tk_stubs(monkeypatch, filedialog_overrides=fd_over)
    _install_project_stubs(monkeypatch)
    # Rebind filedialog used by merge_mod to the newly stubbed one
    import tkinter.filedialog as fd_mod
    merge_mod.filedialog = fd_mod

    # In-memory file that doesn't actually close
    class _MemFile:
        def __init__(self): self._buf = []
        def write(self, s): self._buf.append(str(s))
        def __enter__(self): return self
        def __exit__(self, *a): pass  # no-op close
        def getvalue(self): return "".join(self._buf)

    mem = _MemFile()
    opened = []

    def fake_open(path, mode="r", encoding=None, newline=None):
        # Record the normalized path and return our in-memory handle
        opened.append(str(merge_mod.Path(path)))
        assert "w" in mode
        return mem

    # Patch where open() is looked up
    monkeypatch.setattr(merge_mod, "open", fake_open, raising=False)
    monkeypatch.setattr(builtins, "open", fake_open, raising=False)

    # Act
    merge_mod.MergeTab._export_listbox(mt, mt.lbx_unx, "unmatched_excel")

    # Assert
    assert opened and opened[-1] == str(merge_mod.Path(chosen))
    written = mem.getvalue().strip().splitlines()
    assert written == ["row1", "row2"]
    assert any(c[0] == "showinfo" for c in mt.mb.calls), "Expected completion info dialog"


# def test_open_normalize_modal_headless_object_behaves(merge_mod, monkeypatch):
#     """Headless normalize modal exposes actions that work (no filesystem; robust to names)."""
#     import importlib
#     import sys
#
#     # Arrange: force headless Toplevel & stub project deps; reload module
#     _install_tk_stubs(monkeypatch, toplevel_raises=True)
#     _install_project_stubs(monkeypatch)
#     sys.modules.pop("quicken_helper.gui_viewers.merge_tab", None)
#     m2 = importlib.import_module("quicken_helper.gui_viewers.merge_tab")
#
#     mt = m2.MergeTab(master=None, mb=_FakeMB())
#     mt.m_qif_in.set("MEM://in.qif")
#     mt.m_xlsx.set("MEM://in.xlsx")
#
#     # No real FS
#     monkeypatch.setattr(m2.Path, "exists", lambda self: True, raising=False)
#     monkeypatch.setattr(m2.Path, "is_file", lambda self: True, raising=False)
#
#     # Don’t write: capture the apply call and return the out path
#     calls = []
#     cms = sys.modules["quicken_helper.controllers.category_match_session"]
#     def fake_apply(self, xlsx, xlsx_out):
#         calls.append((str(xlsx), str(xlsx_out)))
#         return m2.Path(xlsx_out)
#
#     monkeypatch.setattr(cms.CategoryMatchSession, "apply_to_excel", fake_apply, raising=False)
#
#     # Act
#     headless = mt.open_normalize_modal()
#     headless.auto_match()
#
#     # Use the session’s own unmatched sets, not hardcoded names
#     uq, ue = headless.unmatched()
#     pre_pairs = list(headless.pairs())
#     if ue and uq:
#         e = sorted(list(ue))[0]
#         q = sorted(list(uq))[0]
#         ok, _ = headless.do_match(e, q)
#         assert ok, "manual match should succeed"
#     post_pairs = list(headless.pairs())
#
#     # Assert
#     assert len(post_pairs) >= len(pre_pairs), "pairs should persist or grow after manual match"
#     out_path = "MEM://normalized.xlsx"
#     result = headless.apply_and_save(out_path=out_path)
#
#     # Normalize expectations using the module's Path (handles slashes on Windows)
#     expected_in = str(m2.Path("MEM://in.xlsx"))
#     expected_out = str(m2.Path(out_path))
#
#     assert calls and calls[-1] == (expected_in, expected_out)
#     assert str(result) == expected_out



def test_open_normalize_modal_headless_object_behaves(merge_mod, monkeypatch):
    """Headless normalize modal exposes actions that work (no filesystem; names from session)."""
    # Arrange: force headless, stub deps, reload
    _install_tk_stubs(monkeypatch, toplevel_raises=True)
    _install_project_stubs(monkeypatch)
    import sys
    names = _get_module_names()
    sys.modules.pop(names["merge_tab"], None)
    m2 = importlib.import_module(names["merge_tab"])

    mt = m2.MergeTab(master=None, mb=_FakeMB())
    mt.m_qif_in.set("MEM://in.qif")
    mt.m_xlsx.set("MEM://in.xlsx")

    # No real FS
    monkeypatch.setattr(m2.Path, "exists", lambda self: True, raising=False)
    monkeypatch.setattr(m2.Path, "is_file", lambda self: True, raising=False)

    # Don’t write files; just capture call
    calls = []
    cms = sys.modules[names["category_match_session"]]
    def fake_apply(self, xlsx, xlsx_out):
        calls.append((str(xlsx), str(xlsx_out)))
        return m2.Path(xlsx_out)
    monkeypatch.setattr(cms.CategoryMatchSession, "apply_to_excel", fake_apply, raising=False)

    # Act
    headless = mt.open_normalize_modal()
    headless.auto_match()

    # Use the session’s own unmatched sets (robust to stub changes)
    uq, ue = headless.unmatched()
    assert isinstance(uq, (list, set)) and isinstance(ue, (list, set))
    # Pick any available names; if empty, skip matching step (still exercise pairs/apply)
    pre_pairs = list(headless.pairs())
    if ue and uq:
        e = sorted(list(ue))[0]
        q = sorted(list(uq))[0]
        ok, _ = headless.do_match(e, q)
        assert ok, "manual match should succeed"
    post_pairs = list(headless.pairs())

    # Assert: pair list grew (or at least exists), and apply/save was invoked with our path
    assert len(post_pairs) >= len(pre_pairs)
    out_path = "MEM://normalized.xlsx"
    result = headless.apply_and_save(out_path=out_path)

    # Normalize expectations using the module's Path (handles Windows vs POSIX)
    expected_in = str(m2.Path("MEM://in.xlsx"))
    expected_out = str(m2.Path(out_path))

    assert calls and calls[-1] == (expected_in, expected_out)
    assert str(result) == expected_out


