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
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from quicken_helper.data_model import (
    ITransaction,
    IQuickenFile,
    EnumClearedStatus,
    QTransaction,
)


# --------------------------
# Tk / ttk / filedialog / messagebox stubs
# --------------------------

class _FileStub(IQuickenFile):
    """Minimal IQuickenFile implementation for MergeTab tests."""

    def __init__(self, path=""):
        self.path = path
        self.transactions = []
        self.accounts = []
        self.headers = []
        self.other_sections = {}

class _TransactionStub(ITransaction):
    """Minimal ITransaction implementation for MergeTab tests."""
    def __init__(self, **kw):
        self.date = kw.get("date", date(1985, 11, 5))
        self.amount = kw.get("amount", Decimal(0))
        self.payee = kw.get("payee", "")
        self.memo = kw.get("memo", "")
        self.category = kw.get("category", "")
        self.tag = kw.get("tag", "")
        self.action_chk = kw.get("action_chk", "")
        self.cleared = kw.get("cleared", EnumClearedStatus.UNKNOWN)
        self.splits = kw.get("splits", [])
        self._dict = kw.get("_dict", {})
    def to_dict(self):
        return self._dict

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
        if "height" in kwargs:
            self._height = kwargs["height"]
        if "width" in kwargs:
            self._width = kwargs["width"]
        if "state" in kwargs:
            self._state = kwargs["state"]

    config = configure  # alias

    def cget(self, key):
        if key == "height":
            return self._height
        if key == "width":
            return self._width
        if key == "state":
            return self._state
        return None

    # Text content API (indices ignored; whole-buffer semantics are fine for tests)
    def get(self, start="1.0", end="end"):
        return self._buf

    def insert(self, index, s):
        if self._state == "disabled":
            return
        self._buf += str(s)

    def delete(self, start="1.0", end="end"):
        if self._state == "disabled":
            return
        self._buf = ""

    def see(self, index):
        pass

    # Geometry + misc
    def pack(self, *a, **k):
        pass

    def pack_forget(self, *a, **k):
        pass

    def grid(self, *a, **k):
        pass

    def bind(self, *a, **k):
        pass


class _ListboxStub:
    """Minimal Listbox supporting insert/get/delete/bind/selection/grid."""

    def __init__(self, *a, **k):
        self._items = []
        self._binds = {}
        self._sel = set()

    def insert(self, index, s):
        self._items.append(s)

    def get(self, a, b=None):
        if a == 0 and (b == "end" or b is None):
            return tuple(self._items)
        if isinstance(a, int) and b is None:
            return self._items[a]
        return tuple(self._items)

    def delete(self, a, b=None):
        self._items.clear()
        self._sel.clear()

    def bind(self, evt, fn):
        self._binds[evt] = fn

    def curselection(self):
        return tuple(sorted(self._sel))

    def selection_set(self, i):
        self._sel.add(i)

    def pack(self, *a, **k):
        pass

    def grid(self, *a, **k):
        pass


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
        def __init__(self, *a, **k):
            pass

    class Toplevel:
        def __init__(self, *a, **k):
            if toplevel_raises:
                raise RuntimeError("Headless Toplevel disabled for this test")

        def title(self, *a, **k):
            pass

        def geometry(self, *a, **k):
            pass

        def destroy(self):
            pass

    tk.Tk = Tk
    tk.Toplevel = Toplevel
    tk.StringVar = _DummyVar
    tk.BooleanVar = _DummyVar
    tk.Text = _TextStub
    tk.Listbox = _ListboxStub

    # ---------------- ttk ----------------
    ttk = types.ModuleType("tkinter.ttk")

    class _Base:
        def __init__(self, *a, **k):
            pass

        def pack(self, *a, **k):
            pass

        def pack_forget(self, *a, **k):
            pass

        def grid(self, *a, **k):
            pass

        def columnconfigure(self, *a, **k):
            pass

        def rowconfigure(self, *a, **k):
            pass

        def configure(self, *a, **k):
            pass

        def winfo_toplevel(self):
            return object()

    class Style(_Base):
        def map(self, *a, **k):
            pass

        def theme_use(self, *a, **k):
            pass

    class Frame(_Base):
        pass

    class LabelFrame(_Base):
        pass

    class Label(_Base):
        pass

    class Button(_Base):
        pass

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

    class Checkbutton(_Base):
        pass

    class Combobox(_Base):
        pass

    class Scrollbar(_Base):
        pass

    class Separator(_Base):
        pass

    class Notebook(_Base):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._tabs = []

        def add(self, child, **k):
            self._tabs.append((child, k.get("text")))

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

    def _noop(*a, **k):
        return None

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
    amount: Decimal  # NEW: every split row must include an amount


@dataclass
class _Group:
    gid: int
    date: date
    total_amount: Decimal  # keep as Decimal to match protocol usage
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
    def __init__(self, bank_txns, excel_txns):
        self.bank_txns = list(bank_txns)
        self.excel_txns = list(excel_txns)
        self.pairs = []

    @property
    def unmatched_bank(self):
        matched_ids = {id(b) for b, _ in self.pairs}
        return [b for b in self.bank_txns if id(b) not in matched_ids]

    @property
    def unmatched_excel(self):
        matched_ids = {id(e) for _, e in self.pairs}
        return [e for e in self.excel_txns if id(e) not in matched_ids]

    def manual_match(self, bank_index=None, excel_index=None):
        if bank_index is None or excel_index is None:
            return False, "missing selection"
        if not (0 <= bank_index < len(self.bank_txns) and 0 <= excel_index < len(self.excel_txns)):
            return False, "invalid selection"
        b, e = self.bank_txns[bank_index], self.excel_txns[excel_index]
        self.pairs = [(bb, ee) for (bb, ee) in self.pairs if bb is not b and ee is not e]
        self.pairs.append((b, e))
        return True, "ok"

    def manual_unmatch(self, bank_index=None, excel_index=None):
        if bank_index is not None and 0 <= bank_index < len(self.bank_txns):
            b = self.bank_txns[bank_index]
            before = len(self.pairs)
            self.pairs = [(bb, ee) for (bb, ee) in self.pairs if bb is not b]
            return len(self.pairs) != before
        if excel_index is not None and 0 <= excel_index < len(self.excel_txns):
            e = self.excel_txns[excel_index]
            before = len(self.pairs)
            self.pairs = [(bb, ee) for (bb, ee) in self.pairs if ee is not e]
            return len(self.pairs) != before
        return False


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
        return True, "ok"

    def manual_unmatch(self, excel_name: str):
        removed = self.mapping.pop(excel_name, None)
        return (removed is not None), ("ok" if removed is not None else "not found")

    def apply_to_excel(self, xlsx: Path, xlsx_out: Path):
        xlsx_out.write_text("normalized", encoding="utf-8")
        return xlsx_out


def nameof_module(mod) -> str:
    return (
        getattr(mod, "__spec__", None).name
        if getattr(mod, "__spec__", None)
        else mod.__name__
    )


def _get_module_names() -> dict[str, str]:
    """Return dict of refactor-safe symbols."""
    # import quicken_helper as quicken_helper
    import quicken_helper
    from quicken_helper.controllers import (
        category_match_session,
        match_excel,
        match_session,
        qif_loader,
    )
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
    Install lightweight quicken_helper stubs used by MergeTab._m_load_and_auto and friends.
    Creates a proper quicken_helper package with .controllers and .legacy subpackages,
    and registers controller/legacy modules in both sys.modules and as parent attributes.
    """
    import datetime
    import sys
    import types
    from datetime import date
    from decimal import Decimal

    names = _get_module_names()

    # ---- root package: quicken_helper (package) ----
    pkg = sys.modules.get(names["quicken_helper"])
    if pkg is None:
        pkg = types.ModuleType(names["quicken_helper"])
        pkg.__path__ = []  # mark as package
        monkeypatch.setitem(sys.modules, names["quicken_helper"], pkg)

    # ---- controllers package ----
    created_controllers = False
    controllers_mod = sys.modules.get(names["controllers"])
    if controllers_mod is None:
        controllers_mod = types.ModuleType(names["controllers"])
        controllers_mod.__path__ = []  # mark as package
        monkeypatch.setitem(sys.modules, names["controllers"], controllers_mod)
        created_controllers = True

    # ---- qif_loader (stub) ----
    ql = types.ModuleType(names["qif_loader"])

    class _Key:
        def __init__(self, idx):
            self.txn_index = idx
            self.transfer_account = ""

    class _QifTxn:
        def __init__(self, idx):
            self.key = _Key(idx)
            self.date = datetime.date(2024, 1, idx if idx <= 28 else 28)
            self.amount = float(idx)
            self.payee = f"Payee{idx}"
            self.category = "Cat"
            self.memo = ""

    def _legacy_load_transactions(path):
        # Two simple dict-like txns (legacy shape)
        return [
            {"key": {"txn_index": 1}, "amount": 1.0},
            {"key": {"txn_index": 2}, "amount": 2.0},
        ]

    # def parse_qif(path):
    #     return _legacy_load_transactions(path)
    #
    # def open_and_parse_qif(path):
    #     return _legacy_load_transactions(path)

    def parse_qif_unified_protocol(path):
        file = _FileStub(path)
        file.transactions.append(_TransactionStub(amount=Decimal(1.0),_dict={"key": {"txn_index": 1}, "amount": 1.0}))
        file.transactions.append(_TransactionStub(amount=Decimal(2.0),_dict={"key": {"txn_index": 2}, "amount": 2.0}))
        return file


    # Minimal enum used by UI
    from quicken_helper.data_model.interfaces import EnumClearedStatus

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
            self.cleared = kw.get("cleared", EnumClearedStatus.NOT_CLEARED)
            self.splits = kw.get("splits", [])
            self.key = _Key(1)

    def load_transactions_protocol(path):
        return [
            _Txn(
                amount="12.34",
                category="Groceries",
                tag="Costco",
                cleared=EnumClearedStatus.RECONCILED,
                splits=[
                    _Split("10.00", "Groceries", "Apples"),
                    _Split("2.34", "Groceries", "Bananas"),
                ],
            )
        ]

    # expose both shapes; MergeTab will use protocol path when available
    ql.load_transactions_protocol = load_transactions_protocol
    ql.load_transactions = _legacy_load_transactions
    # ql.parse_qif = parse_qif
    # ql.open_and_parse_qif = open_and_parse_qif
    ql.parse_qif_unified_protocol = parse_qif_unified_protocol

    monkeypatch.setitem(sys.modules, names["qif_loader"], ql)

    # ---- data_model.excel.excel_transaction (stub) ----
    excel_txn_mod_name = "quicken_helper.data_model.excel.excel_transaction"
    excel_txn_mod = types.ModuleType(excel_txn_mod_name)

    from dataclasses import dataclass as _dc_dataclass, field as _dc_field
    from datetime import date as _date
    from decimal import Decimal as _Decimal

    @_dc_dataclass(frozen=True)
    class _ExcelTxnProto:
        """Protocol-shaped Excel-side ITransaction for tests."""

        id: str
        date: _date
        amount: _Decimal
        payee: str = ""
        memo: str = ""
        category: str = ""
        splits: list = _dc_field(default_factory=list)

    excel_txn_mod._ExcelTxnProto = _ExcelTxnProto

    def map_group_to_excel_txn(group):
        """Adapt a group with validated rows (each having .amount, .category) to a protocol txn."""
        rows = tuple(getattr(group, "rows", ()) or ())
        first = rows[0] if rows else None
        payee = getattr(first, "item", "") if first else ""
        memo = getattr(first, "rationale", "") if first else ""

        # Build split views; rows are guaranteed to have amount/category by ingestion validation
        splits = [
            type(
                "S",
                (),
                {
                    "category": getattr(r, "category", "") or "",
                    "memo": getattr(r, "item", "") or "",
                    "amount": (
                        r.amount
                        if isinstance(r.amount, _Decimal)
                        else _Decimal(str(r.amount))
                    ),
                },
            )
            for r in rows
        ]

        total = (
            group.total_amount
            if isinstance(group.total_amount, _Decimal)
            else _Decimal(str(group.total_amount))
        )
        return excel_txn_mod._ExcelTxnProto(
            id=str(group.gid),
            date=group.date,
            amount=total,
            payee=payee,
            memo=memo,
            splits=splits,
        )

    excel_txn_mod.map_group_to_excel_txn = map_group_to_excel_txn

    # Ensure parent packages exist and register the stub
    pkg_dm = sys.modules.setdefault(
        "quicken_helper.data_model", types.ModuleType("quicken_helper.data_model")
    )
    pkg_dm.__path__ = getattr(pkg_dm, "__path__", [])
    pkg_dm_excel = sys.modules.setdefault(
        "quicken_helper.data_model.excel",
        types.ModuleType("quicken_helper.data_model.excel"),
    )
    pkg_dm_excel.__path__ = getattr(pkg_dm_excel, "__path__", [])
    monkeypatch.setitem(sys.modules, excel_txn_mod_name, excel_txn_mod)

    # ---- controllers.match_excel (validated ingestion) ----
    mex = types.ModuleType(names["match_excel"])

    from dataclasses import dataclass as _dc, field as _dc_field
    from decimal import Decimal
    from datetime import date as _date

    @_dc(frozen=True)
    class _Row2:
        item: str
        category: str
        rationale: str
        amount: Decimal  # NEW: rows always carry an amount

    @_dc(frozen=True)
    class _Group2:
        gid: str
        date: _date
        total_amount: Decimal
        rows: tuple[_Row2, ...]

    def _validate_rows(rows):
        """Raise early if any row is missing required fields."""
        for i, r in enumerate(rows or []):
            if not hasattr(r, "amount") or getattr(r, "amount", None) is None:
                raise ValueError(f"Excel row #{i} missing required 'amount'")
            if not hasattr(r, "category") or not getattr(r, "category", ""):
                raise ValueError(f"Excel row #{i} missing required 'category'")

    def load_excel_rows(path):
        # Two valid rows with amounts for happy-path UI tests
        rows = [
            _Row2("Item1", "Cat", "r1", Decimal("5.00")),
            _Row2("Item2", "Cat", "r2", Decimal("7.34")),
        ]
        _validate_rows(rows)
        return rows

    def group_excel_rows(rows):
        _validate_rows(rows)
        total = sum((r.amount for r in rows or []), Decimal("0"))
        return [_Group2(gid="G1", date=_date(2024, 1, 15), total_amount=total, rows=tuple(rows or []))]

    def build_matched_only_txns(sess):
        return list(getattr(sess, "txns", []))

    def extract_qif_categories(txns):
        return {"Food", "Rent"}

    def extract_excel_categories(xlsx):
        return {"Groceries", "Housing"}

    mex.load_excel_rows = load_excel_rows
    mex.group_excel_rows = group_excel_rows
    mex.build_matched_only_txns = build_matched_only_txns
    mex.extract_qif_categories = extract_qif_categories
    mex.extract_excel_categories = extract_excel_categories
    monkeypatch.setitem(sys.modules, names["match_excel"], mex)

    # ---- match_session (stub) ----
    ms = types.ModuleType(names["match_session"])

    from dataclasses import dataclass, field
    from datetime import date as _date
    from decimal import Decimal as _Decimal
    from typing import Iterable, List, Tuple

    @dataclass(frozen=True)
    class _ExcelTxnStub:
        """Minimal ITransaction-shaped stub for Excel side."""

        id: str
        date: _date
        amount: _Decimal
        payee: str = ""
        memo: str = ""
        category: str = ""
        splits: List[object] = field(default_factory=list)

    class MatchSession:
        """
        Protocol-only API used by MergeTab:
          • __init__(bank_txns, excel_txns)
          • pairs: List[(bank_txn, excel_txn)]
          • unmatched_bank / unmatched_excel: Lists
          • manual_match(bank_index, excel_index)
          • manual_unmatch(bank_index=None, excel_index=None)
          • auto_match()
        """

        def __init__(self, bank_txns: Iterable[object], excel_txns: Iterable[object]):
            self.bank_txns = list(bank_txns)
            self.excel_txns = list(excel_txns)
            self.pairs: List[Tuple[object, object]] = []

        def auto_match(self, *_a, **_k):
            if self.bank_txns and self.excel_txns:
                self.pairs = [(self.bank_txns[0], self.excel_txns[0])]

        @property
        def unmatched_bank(self) -> List[object]:
            # Identity-based (no hashing of txn objects)
            matched_ids = {id(b) for b, _ in self.pairs}
            return [b for b in self.bank_txns if id(b) not in matched_ids]

        @property
        def unmatched_excel(self) -> List[object]:
            # Identity-based (no hashing of txn objects)
            matched_ids = {id(e) for _, e in self.pairs}
            return [e for e in self.excel_txns if id(e) not in matched_ids]

        def manual_match(
            self, bank_index: int | None = None, excel_index: int | None = None
        ):
            if bank_index is None or excel_index is None:
                return False, "missing selection"
            if not (
                0 <= bank_index < len(self.bank_txns)
                and 0 <= excel_index < len(self.excel_txns)
            ):
                return False, "invalid selection"
            b, e = self.bank_txns[bank_index], self.excel_txns[excel_index]
            # keep 1↔1
            self.pairs = [
                (bb, ee) for (bb, ee) in self.pairs if bb is not b and ee is not e
            ]
            self.pairs.append((b, e))
            return True, "ok"

        def manual_unmatch(self, bank_index: int | None = None, excel_index: int | None = None):
            if bank_index is not None and 0 <= bank_index < len(self.bank_txns):
                b = self.bank_txns[bank_index]
                before = len(self.pairs)
                self.pairs = [(bb, ee) for (bb, ee) in self.pairs if bb is not b]
                return len(self.pairs) != before
            if excel_index is not None and 0 <= excel_index < len(self.excel_txns):
                e = self.excel_txns[excel_index]
                before = len(self.pairs)
                self.pairs = [(bb, ee) for (bb, ee) in self.pairs if ee is not e]
                return len(self.pairs) != before
            return False

    ms.MatchSession = MatchSession
    monkeypatch.setitem(sys.modules, names["match_session"], ms)


    # ---- category_match_session (stub) ----
    cms = types.ModuleType(names["category_match_session"])
    cms.CategoryMatchSession = _CategoryMatchSessionStub
    monkeypatch.setitem(sys.modules, names["category_match_session"], cms)

    # ---- legacy.qif_writer (stub) ----
    legacy_pkg_name = names["qif_writer"].rsplit(".", 1)[
        0
    ]  # e.g., "quicken_helper.legacy"
    legacy_mod = sys.modules.get(legacy_pkg_name)
    if legacy_mod is None:
        legacy_mod = types.ModuleType(legacy_pkg_name)
        legacy_mod.__path__ = []
        monkeypatch.setitem(sys.modules, legacy_pkg_name, legacy_mod)

    qw = types.ModuleType(names["qif_writer"])

    def write_qif(txns, out_path):
        (tmp_path or Path(".")).mkdir(exist_ok=True)
        return None

    qw.write_qif = write_qif
    monkeypatch.setitem(sys.modules, names["qif_writer"], qw)

    # ----belt and suspenders: tag stubs for cleanup ----
    for _m in (ql, qw, mex, ms, cms):
        setattr(_m, "_is_merge_tab_test_stub", True)
    if created_controllers:
        setattr(controllers_mod, "_is_merge_tab_test_stub", True)

    # ---- bind subpackages on parent packages ----
    # Bind controllers submodules as attributes
    monkeypatch.setattr(controllers_mod, "qif_loader", ql)
    monkeypatch.setattr(controllers_mod, "match_excel", mex)
    monkeypatch.setattr(controllers_mod, "match_session", ms)
    monkeypatch.setattr(controllers_mod, "category_match_session", cms)
    # Attach controllers to root package
    monkeypatch.setattr(pkg, "controllers", controllers_mod)
    # Bind legacy.qif_writer and attach legacy on root package
    monkeypatch.setattr(legacy_mod, "qif_writer", qw)
    monkeypatch.setattr(pkg, "legacy", legacy_mod)


# --------------------------
# Import fixture
# --------------------------


@pytest.fixture
def merge_mod(monkeypatch):
    """Import quicken_helper.gui_viewers.merge_tab with all deps stubbed for headless testing."""
    names_dict = _get_module_names()
    _install_tk_stubs(monkeypatch)  # GUI stubs
    _install_project_stubs(monkeypatch)  # quicken_helper stubs

    # Only reload GUI modules that we want fresh; keep controller stubs intact.
    for key in (
        "merge_tab",
    ):  # add "convert_tab", "probe_tab" if you truly need them fresh
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
    assert (
        hasattr(mt, "m_qif_in") and hasattr(mt, "m_xlsx") and hasattr(mt, "m_qif_out")
    )
    assert hasattr(mt, "m_only_matched")
    assert (
        hasattr(mt, "lbx_unqif") and hasattr(mt, "lbx_unx") and hasattr(mt, "lbx_pairs")
    )
    assert hasattr(mt, "txt_info"), "Info Text widget should exist"


def test_browse_qif_sets_in_and_suggests_out(merge_mod, monkeypatch):
    """_m_browse_qif sets m_qif_in and suggests '<stem>_updated.data_model' without touching disk."""
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
    chosen_out = "MEM://out.data_model"
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
    bad_qif = "MEM://missing.data_model"
    bad_xlsx = "MEM://missing.xlsx"
    mt.m_qif_in.set(bad_qif)
    mt.m_xlsx.set(bad_xlsx)

    # Paths don't exist
    monkeypatch.setattr(merge_mod.Path, "exists", lambda self: False, raising=False)
    monkeypatch.setattr(merge_mod.Path, "is_file", lambda self: False, raising=False)

    # Act
    mt._m_load()

    # Assert
    assert any(
        c[0] == "showerror" for c in mt.mb.calls
    ), "Expected error for invalid QIF/Excel"

    # Arrange: valid QIF, invalid Excel (still no FS)
    mt.mb.calls.clear()
    valid_qif = "MEM://in.data_model"
    mt.m_qif_in.set(valid_qif)
    # Make only the valid_qif path exist
    monkeypatch.setattr(
        merge_mod.Path, "exists", lambda self: str(self) == valid_qif, raising=False
    )
    monkeypatch.setattr(
        merge_mod.Path, "is_file", lambda self: str(self) == valid_qif, raising=False
    )

    # Act
    mt._m_load()

    # Assert
    assert any(
        c[0] == "showerror" for c in mt.mb.calls
    ), "Expected error for invalid Excel path"


def test_load_and_auto_populates_lists_on_success(merge_mod, monkeypatch):
    """_m_load_and_auto creates a session, auto-matches, and fills listboxes (no filesystem)."""
    # Arrange
    mt = merge_mod.MergeTab(master=None, mb=_FakeMB())
    qif_in = "Z:/memory/in.data_model"
    xlsx = "Z:/memory/in.xlsx"
    mt.m_qif_in.set(qif_in)
    mt.m_xlsx.set(xlsx)

    # Patch Path.exists so ONLY our two in-memory paths "exist"
    monkeypatch.setattr(merge_mod.Path, "exists", lambda self: True, raising=False)
    monkeypatch.setattr(merge_mod.Path, "is_file", lambda self: True, raising=False)

    # Act
    mt._m_load()
    mt._m_auto_match()

    # Assert
    assert mt._merge_session is not None, "Session should be created"
    assert isinstance(mt.m_pairs, list)
    assert isinstance(mt.m_unmatched_qif, list)
    assert isinstance(mt.m_unmatched_excel, list)


def test_manual_match_requires_selection_and_calls_session(merge_mod):
    """_m_manual_match shows error with no selection; with selections it calls session.manual_match."""
    # Arrange
    mt = merge_mod.MergeTab(master=None, mb=_FakeMB())

    # bank txn (QIF) and excel txn (protocol-shaped)
    q = _QTxn(_QKey(1), date(2024, 1, 1), "10.00", "Alpha")

    @dataclass(frozen=True)
    class _ExcelTxn:
        id: str
        date: date
        amount: Decimal
        payee: str = ""
        memo: str = ""
        category: str = ""
        splits: list = field(default_factory=list)

    e = _ExcelTxn("G101", date(2024, 1, 2), Decimal("10.00"), payee="Alpha")

    # protocol-shaped session stub
    mt._merge_session = _MatchSessionStub([q], [e])

    # UI caches now carry (index, txn) tuples
    mt._unqif_sorted = [(0, q)]
    mt._unx_sorted = [(0, e)]

    # seed listboxes
    mt.lbx_unqif.insert("end", "data_model")
    mt.lbx_unx.insert("end", "grp")

    # Act (no selection)
    mt._m_manual_match()
    # Assert
    assert any(c[0] == "showerror" for c in mt.mb.calls), (
        "Expected error when nothing selected"
    )

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

    q = _QTxn(_QKey(1), date(2024, 1, 1), "10.00", "Alpha")

    @dataclass(frozen=True)
    class _ExcelTxn:
        id: str
        date: date
        amount: Decimal
        payee: str = ""
        memo: str = ""
        category: str = ""
        splits: list = field(default_factory=list)

    e = _ExcelTxn("G101", date(2024, 1, 2), Decimal("10.00"), payee="Alpha")

    sess = _MatchSessionStub([q], [e])
    # one matched pair, protocol shape
    sess.pairs = [(q, e)]
    mt._merge_session = sess

    # UI pairs cache uses (bank_index, excel_index, bank_txn, excel_txn)
    mt._pairs_sorted = [(0, 0, q, e)]

    mt.lbx_pairs.insert("end", "PAIR")
    mt.lbx_pairs.selection_set(0)


    # Act
    mt._m_manual_unmatch()

    # Assert
    assert sess.pairs == [], "Pair should be removed after unmatch"
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
    outp = "MEM://out.data_model"
    mt.m_qif_out.set(outp)

    # Make all path checks succeed; noop mkdir to avoid touching disk
    monkeypatch.setattr(merge_mod.Path, "exists", lambda self: True, raising=False)
    monkeypatch.setattr(merge_mod.Path, "is_file", lambda self: True, raising=False)
    monkeypatch.setattr(
        merge_mod.Path,
        "mkdir",
        lambda self, parents=False, exist_ok=False: None,
        raising=False,
    )

    # Patch the exact writer used by merge_tab: mod.write_qif(...)
    calls = []
    monkeypatch.setattr(
        merge_mod.mod,
        "write_qif",
        lambda txns, p: calls.append((list(txns), str(p))),
        raising=False,
    )

    # Act
    mt._m_apply_and_save()

    # Assert
    expected_out = str(merge_mod.Path(outp))  # normalize path like the code
    assert (
        calls and calls[-1][1] == expected_out
    ), "Writer should be called with normalized out path"
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
        def __init__(self):
            self._buf = []

        def write(self, s):
            self._buf.append(str(s))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass  # no-op close

        def getvalue(self):
            return "".join(self._buf)

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
    assert any(
        c[0] == "showinfo" for c in mt.mb.calls
    ), "Expected completion info dialog"


def test_open_normalize_modal_headless_object_behaves(merge_mod, monkeypatch):
    """Headless normalize modal exposes actions that work (no filesystem; names from session)."""
    # IMPORTANT: get real module names first (from the actual package), THEN install stubs
    names = _get_module_names()

    # Arrange: force headless, stub deps, reload
    _install_tk_stubs(monkeypatch, toplevel_raises=True)
    _install_project_stubs(monkeypatch)

    sys.modules.pop(names["merge_tab"], None)
    m2 = importlib.import_module(names["merge_tab"])

    mt = m2.MergeTab(master=None, mb=_FakeMB())
    mt.m_qif_in.set("MEM://in.data_model")
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

    monkeypatch.setattr(
        cms.CategoryMatchSession, "apply_to_excel", fake_apply, raising=False
    )

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


@pytest.fixture(autouse=True)
def _purge_stubs_after_each_test(monkeypatch):
    yield
    # remove only modules we created (tag them when you create them)
    for name, mod in list(sys.modules.items()):
        if getattr(mod, "_is_merge_tab_test_stub", False):
            sys.modules.pop(name, None)
        importlib.invalidate_caches()


@pytest.fixture(autouse=True, scope="module")
def _cleanup_module():
    yield
    # cleanup here (e.g., purge tagged sys.modules entries)
    for name, mod in list(sys.modules.items()):
        if getattr(mod, "_is_merge_tab_test_stub", False):
            sys.modules.pop(name, None)
    importlib.invalidate_caches()

# --- Migration guard: skip normalize-related tests moved to test_category_popout.py ---
def _skip_legacy_normalize_tests():
    import pytest as _pytest

    # Tailored selectors: name/docstring, case-insensitive
    KEYWORDS = (
        "normalize",                  # broad: catches test_normalize_* variants
        "open_normalize_modal",       # specific old entrypoint
        "_m_normalize_categories",    # specific old handler
        "normalize categories",       # docstring phrase
        "category_popout",            # new home reference
    )

    g = globals()
    for name, obj in list(g.items()):
        if not (name.startswith("test_") and callable(obj)):
            continue
        text = (name + " " + (getattr(obj, "__doc__", "") or "")).lower()
        if any(k in text for k in KEYWORDS):
            g[name] = _pytest.mark.skip(
                "Moved to tests/gui_viewers/test_category_popout.py"
            )(obj)

_skip_legacy_normalize_tests()
del _skip_legacy_normalize_tests
