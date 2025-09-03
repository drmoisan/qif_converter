# tests/gui_viewers/test_convert_tab.py
"""
Unit tests for quicken_helper.gui_viewers.convert_tab.ConvertTab

Policy compliance:
- Independence & Isolation: Tk/Ttk, dialogs, filesystem, and external controllers are stubbed/mocked.
- Fast & Deterministic: No external I/O or randomness; all outcomes repeatable.
- Readability: AAA structure; each test includes a docstring describing intent.
- Scenarios: Positive/negative paths for conversion, extension logic, overwrite prompt, parsing & filtering hooks.

These tests DO NOT touch the real filesystem.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
import pytest


# --------------------------
# Minimal tkinter stubs (headless)
# --------------------------

def _install_tk_stubs(monkeypatch):
    """Install minimal tkinter/ttk/font/messagebox/filedialog stubs usable by ConvertTab."""

    # --- tkinter base module ---
    tk = types.ModuleType("tkinter")

    class _VarBase:
        def __init__(self, value=None): self._v = value
        def get(self): return self._v
        def set(self, v): self._v = v
        def trace_add(self, *a, **k): return "token"  # used by emit_var

    class Tk:
        def __init__(self, *a, **k): pass
        def withdraw(self): pass
        def mainloop(self): pass
        def after(self, ms, func=None, *args):  # execute immediately in tests
            if func is not None:
                func(*args)

    class StringVar(_VarBase):
        def __init__(self, value=""): super().__init__(value)

    class BooleanVar(_VarBase):
        def __init__(self, value=False): super().__init__(value)

    class IntVar(_VarBase):
        def __init__(self, value=0): super().__init__(value)

    class Text:
        def __init__(self, *a, **k):
            self.master = a[0] if a else None
            self._buf = ""
        def get(self, s, e): return self._buf
        def insert(self, i, s): self._buf += s
        def delete(self, s, e): self._buf = ""
        def see(self, i): pass
        # geometry & events
        def grid(self, *a, **k): pass
        def pack(self, *a, **k): pass
        def grid_remove(self, *a, **k): pass
        def bind(self, *a, **k): pass

    # Export tkinter symbols
    tk.Tk = Tk
    tk.StringVar = StringVar
    tk.BooleanVar = BooleanVar
    tk.IntVar = IntVar
    tk.Text = Text
    tk.END = "end"
    tk.INSERT = "insert"

    # --- tkinter.ttk submodule ---
    ttk = types.ModuleType("tkinter.ttk")

    class _Widget:
        def __init__(self, *a, **k):
            # emulate Tkinter storing parent on every widget
            self.master = a[0] if a else None
        def pack(self, *a, **k): pass
        def grid(self, *a, **k): pass
        def place(self, *a, **k): pass
        def grid_remove(self, *a, **k): pass
        def columnconfigure(self, *a, **k): pass
        def rowconfigure(self, *a, **k): pass
        def bind(self, *a, **k): pass
        def configure(self, *a, **k): pass
        def destroy(self, *a, **k): pass
        def winfo_ismapped(self): return True
        def update_idletasks(self): pass  # used in ConvertTab.logln()

    class Frame(_Widget): pass
    class LabelFrame(Frame): pass
    class Label(_Widget): pass
    class Button(_Widget): pass
    class Entry(_Widget): pass
    class Checkbutton(_Widget): pass
    class Radiobutton(_Widget): pass

    class Combobox(_Widget):
        def __init__(self, *a, values=None, textvariable=None, **k):
            super().__init__(*a, **k)
            self._values = values or []
            self._tv = textvariable
        def set(self, v):
            if self._tv:
                self._tv.set(v)
        def get(self):
            return self._tv.get() if self._tv else (self._values[0] if self._values else "")
        def current(self, idx):
            if self._values and 0 <= idx < len(self._values):
                self.set(self._values[idx])

    class Notebook(Frame):
        def add(self, *a, **k): pass

    class Style:
        def theme_use(self, *a, **k): pass
        def configure(self, *a, **k): pass
        def map(self, *a, **k): pass

    class Separator(_Widget): pass
    class Progressbar(_Widget): pass

    ttk.Frame = Frame
    ttk.LabelFrame = LabelFrame
    ttk.Label = Label
    ttk.Button = Button
    ttk.Entry = Entry
    ttk.Checkbutton = Checkbutton
    ttk.Radiobutton = Radiobutton
    ttk.Combobox = Combobox
    ttk.Notebook = Notebook
    ttk.Style = Style
    ttk.Separator = Separator
    ttk.Progressbar = Progressbar

    # --- filedialog and messagebox ---
    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.askopenfilename = lambda **k: ""
    filedialog.asksaveasfilename = lambda **k: ""

    messagebox = types.ModuleType("tkinter.messagebox")
    class _FakeMB:
        """Captures info/error prompts and simulates overwrite confirmations."""
        def __init__(self, ask=True):
            self.calls = []
            self._ask = ask
        def showinfo(self, *a, **k):
            self.calls.append(("showinfo", a, k))
        def showerror(self, *a, **k):
            self.calls.append(("showerror", a, k))
        def askyesno(self, *a, **k):
            self.calls.append(("askyesno", a, k))
            return self._ask
    messagebox._FakeMB = _FakeMB

    # --- font ---
    font = types.ModuleType("tkinter.font")
    class _Font:
        def __init__(self, *a, **k): pass
        def cget(self, k): return 10
        def configure(self, **k): pass
    def nametofont(name): return _Font()
    font.Font = _Font
    font.nametofont = nametofont

    # Register stubs
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", filedialog)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", messagebox)
    monkeypatch.setitem(sys.modules, "tkinter.font", font)


# --------------------------
# Fixture: import ConvertTab with tkinter stubbed
# --------------------------

@pytest.fixture
def convert_mod(monkeypatch):
    """Import convert_tab with Tk/Ttk and dialogs stubbed, ensuring a clean module."""
    _install_tk_stubs(monkeypatch)
    # Ensure a fresh import (avoid prior state)
    sys.modules.pop("quicken_helper.gui_viewers.convert_tab", None)
    return importlib.import_module("quicken_helper.gui_viewers.convert_tab")


def _make_tab(convert_mod):
    """Create a ConvertTab with a proper parent chain and a fake messagebox API."""
    tk = sys.modules["tkinter"]
    root = tk.Tk()
    master = convert_mod.ttk.Frame(root)  # parented frame so .master exists
    mb_mod = sys.modules["tkinter.messagebox"]
    mb = mb_mod._FakeMB(ask=True)
    tab = convert_mod.ConvertTab(master, mb, session=None)
    return tab, mb


# --------------------------
# Helpers: no-FS parser/writer & Path.exists
# --------------------------

def _patch_qif_parser(monkeypatch, convert_mod, n_txns=2):
    """Return a fake ledger with transactions regardless of which parser symbol is used."""
    class _Txn:
        def __init__(self, i): self.i = i
        def to_dict(self): return {"id": self.i, "amount": "1.00"}
    class _Ledger:
        def __init__(self, n): self.transactions = [_Txn(i) for i in range(n)]
    # Patch both potential locations
    monkeypatch.setattr(convert_mod, "parse_qif_unified_protocol", lambda p: _Ledger(n_txns), raising=False)
    try:
        loader = importlib.import_module("quicken_helper.controllers.qif_loader")
        monkeypatch.setattr(loader, "parse_qif_unified_protocol", lambda p: _Ledger(n_txns), raising=False)
    except Exception:
        pass


def _patch_csv_writers(monkeypatch, convert_mod, calls):
    """Record CSV writer invocations without writing files."""
    def _recorder(txns, out_path):
        count = len(getattr(txns, "transactions", txns))
        calls.append(("writer_called", count, str(out_path)))
    # Writers imported into convert_tab module namespace
    monkeypatch.setattr(convert_mod, "write_csv_quicken_windows", _recorder, raising=False)
    monkeypatch.setattr(convert_mod, "write_csv_quicken_mac", _recorder, raising=False)
    # Also patch legacy qif_writer functions used for default CSV modes, if ever used
    try:
        from quicken_helper.legacy import qif_writer as mod
        monkeypatch.setattr(mod, "write_csv_exploded", _recorder, raising=False)
        monkeypatch.setattr(mod, "write_csv_flat", _recorder, raising=False)
        monkeypatch.setattr(mod, "write_qif", _recorder, raising=False)
    except Exception:
        pass


def _patch_helpers_passthrough(monkeypatch):
    """Ensure filter helpers don't alter data (deterministic pass-through)."""
    try:
        helpers = importlib.import_module("quicken_helper.gui_viewers.helpers")
        monkeypatch.setattr(helpers, "filter_date_range", lambda txns, df, dt: txns, raising=False)
        monkeypatch.setattr(helpers, "apply_multi_payee_filters", lambda txns, *a, **k: txns, raising=False)
    except Exception:
        pass


def _patch_path_exists(monkeypatch, convert_mod, predicate):
    """Make Path.exists return predicate(path_str) everywhere (module-local and global Path)."""
    if hasattr(convert_mod, "Path"):
        monkeypatch.setattr(convert_mod.Path, "exists", lambda self: predicate(str(self)), raising=False)
    monkeypatch.setattr(Path, "exists", lambda self: predicate(str(self)), raising=False)


# --------------------------
# Tests
# --------------------------

def test_update_output_extension_blank_out_uses_in_path(convert_mod):
    """Arrange: blank out_path, valid .qif in_path; Act: _update_output_extension; Assert: out uses stem + .csv."""
    # Arrange
    tab, _ = _make_tab(convert_mod)
    tab.in_path.set(r"C:\fake\input.qif")
    tab.out_path.set("")
    tab.emit_var.set("csv")
    # Act
    tab._update_output_extension()
    # Assert
    out = Path(tab.out_path.get())
    assert out.suffix == ".csv"
    assert out.stem == "input"


def test_update_output_extension_switches_extension(convert_mod):
    """Arrange: out_path with .qif; Act: update for csv emit; Assert: suffix becomes .csv."""
    # Arrange
    tab, _ = _make_tab(convert_mod)
    tab.out_path.set(r"C:\fake\out.qif")
    tab.emit_var.set("csv")
    # Act
    tab._update_output_extension()
    # Assert
    assert Path(tab.out_path.get()).suffix == ".csv"


def test_parse_payee_filters_parses_lines_and_commas(convert_mod):
    """Arrange: mixed commas/newlines + whitespace; Act: _parse_payee_filters; Assert: trimmed non-empty tokens."""
    # Arrange
    tab, _ = _make_tab(convert_mod)
    tab.payees_text.insert("end", " Alpha,  \nBeta\n\n  ,Gamma ,  ")
    # Act
    got = tab._parse_payee_filters()
    # Assert
    assert got == ["Alpha", "Beta", "Gamma"]


def test_run_missing_input_shows_error(convert_mod):
    """Arrange: missing input; Act: run_conversion; Assert: error dialog reported; no writer call needed."""
    # Arrange
    tab, mb = _make_tab(convert_mod)
    tab.in_path.set("")  # missing
    tab.out_path.set(r"C:\fake\out.csv")
    tab.emit_var.set("csv")
    tab.csv_profile.set("quicken-windows")
    # Act
    tab.run_conversion()
    # Assert
    assert any(kind == "showerror" for kind, *_ in mb.calls), "Expected error dialog for missing input"


def test_run_missing_output_shows_error(convert_mod, monkeypatch):
    """Arrange: valid input exists but output missing; Act: run_conversion; Assert: error dialog reported."""
    # Arrange
    tab, mb = _make_tab(convert_mod)
    tab.in_path.set(r"C:\fake\input.qif")
    tab.out_path.set("")  # missing
    tab.emit_var.set("csv")
    tab.csv_profile.set("quicken-windows")
    _patch_path_exists(monkeypatch, convert_mod, predicate=lambda p: p.endswith("input.qif"))
    # Act
    tab.run_conversion()
    # Assert
    assert any(kind == "showerror" for kind, *_ in mb.calls), "Expected error dialog for missing output"


def test_run_decline_overwrite_does_not_write(convert_mod, monkeypatch):
    """Arrange: output 'exists' and user declines; Act: run_conversion; Assert: writer not invoked, confirmation asked."""
    # Arrange
    tab, mb = _make_tab(convert_mod)
    mb._ask = False  # decline overwrite
    tab.in_path.set(r"C:\fake\input.qif")
    tab.out_path.set(r"C:\fake\out.csv")
    tab.emit_var.set("csv")
    tab.csv_profile.set("quicken-windows")
    # both input and output appear to exist
    _patch_path_exists(monkeypatch, convert_mod, predicate=lambda p: p.endswith("input.qif") or p.endswith("out.csv"))
    calls = []
    _patch_qif_parser(monkeypatch, convert_mod)
    _patch_csv_writers(monkeypatch, convert_mod, calls)
    # Act
    tab.run_conversion()
    # Assert
    assert not any(c[0] == "writer_called" for c in calls), "Writer should not be called when overwrite is declined"
    assert any(kind == "askyesno" for kind, *_ in mb.calls), "Expected overwrite confirmation prompt"


def test_run_writes_csv_windows_profile(convert_mod, monkeypatch):
    """Arrange: CSV ('quicken-windows') profile; Act: run_conversion; Assert: writer called & info shown."""
    # Arrange
    tab, mb = _make_tab(convert_mod)
    tab.in_path.set(r"C:\fake\input.qif")
    tab.out_path.set(r"C:\fake\out.csv")
    tab.emit_var.set("csv")
    tab.csv_profile.set("quicken-windows")
    tab.date_from.set("")  # no filters
    tab.date_to.set("")
    # input exists, output does not (no overwrite prompt)
    _patch_path_exists(monkeypatch, convert_mod, predicate=lambda p: p.endswith("input.qif"))
    _patch_helpers_passthrough(monkeypatch)  # ensure filters are deterministic
    _patch_qif_parser(monkeypatch, convert_mod, n_txns=2)
    calls = []
    _patch_csv_writers(monkeypatch, convert_mod, calls)
    # Act
    tab.run_conversion()
    # Assert
    assert any(c[0] == "writer_called" for c in calls), "CSV writer should be invoked"
    assert any(kind == "showinfo" for kind, *_ in mb.calls), "Expected completion info dialog"
