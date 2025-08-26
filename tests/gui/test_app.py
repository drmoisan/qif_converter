# tests/gui/test_app.py
"""
Unit tests for qif_converter.gui.app.App

These tests isolate App from GUI/tooling side-effects by stubbing tkinter/ttk and
qif_converter submodules. They focus on App’s wiring and headless _run logic.
"""

from __future__ import annotations
import importlib
import sys
import types
from pathlib import Path
import builtins
import pytest


# --------------------------
# Helpers: lightweight stubs
# --------------------------

class _DummyVar:
    def __init__(self, v=""):
        self._v = v
    def get(self):
        return self._v
    def set(self, v):
        self._v = v


class _FakeMB:
    """A tiny messagebox API that records calls; askyesno is configurable."""
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


def _make_tk_stubs():
    """Builds stub modules for tkinter, tkinter.ttk, tkinter.messagebox, tkinter.font."""
    tk = types.ModuleType("tkinter")

    class DummyTk:
        def __init__(self, *a, **k):
            pass
        def geometry(self, *a, **k): pass
        def minsize(self, *a, **k): pass
        def option_add(self, *a, **k): pass

    class DummyStringVar(_DummyVar):
        pass

    tk.Tk = DummyTk
    tk.StringVar = DummyStringVar

    ttk = types.ModuleType("tkinter.ttk")
    class Style:
        def __init__(self, *a, **k): pass
        def configure(self, *a, **k): pass
        def map(self, *a, **k): pass
    class Notebook:
        def __init__(self, *a, **k):
            self._tabs = []
        def pack(self, *a, **k): pass
        def add(self, child, **k):
            self._tabs.append((child, k.get("text")))
        def configure(self, **k): pass
    ttk.Style = Style
    ttk.Notebook = Notebook

    messagebox = types.ModuleType("tkinter.messagebox")
    def _noop(*a, **k): return None
    messagebox.showinfo = _noop
    messagebox.showerror = _noop
    messagebox.askyesno = lambda *a, **k: True

    font = types.ModuleType("tkinter.font")
    class _Font:
        def __init__(self, *a, **k):
            self._cfg = {"family": "TkDefaultFont", "size": 10, "weight": "normal"}
        def cget(self, k): return self._cfg.get(k)
        def configure(self, **k): self._cfg.update(k)
    def nametofont(name): return _Font()
    font.Font = _Font
    font.nametofont = nametofont

    return tk, ttk, messagebox, font


def _install_gui_stubs(monkeypatch):
    tk, ttk, messagebox, font = _make_tk_stubs()
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", messagebox)
    monkeypatch.setitem(sys.modules, "tkinter.font", font)


def _install_project_stubs(monkeypatch, tmp_path: Path):
    """
    Install stubs for qif_converter package elements that app.py imports.
    These keep tests isolated and deterministic.
    """
    # Top-level package and subpackage
    pkg = types.ModuleType("qif_converter"); pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "qif_converter", pkg)

    gui_pkg = types.ModuleType("qif_converter.gui"); gui_pkg.__path__ = []
    monkeypatch.setitem(sys.modules, "qif_converter.gui", gui_pkg)

    # scaling
    scaling = types.ModuleType("qif_converter.gui.scaling")
    scaling.apply_global_font_scaling = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "qif_converter.gui.scaling", scaling)

    # merge_tab
    merge_tab = types.ModuleType("qif_converter.gui.merge_tab")
    class MergeTab:
        def __init__(self, *a, **k): pass
        def open_normalize_modal(self): return "normalized"
    merge_tab.MergeTab = MergeTab
    monkeypatch.setitem(sys.modules, "qif_converter.gui.merge_tab", merge_tab)

    # probe_tab
    probe_tab = types.ModuleType("qif_converter.gui.probe_tab")
    class ProbeTab:
        def __init__(self, *a, **k): pass
    probe_tab.ProbeTab = ProbeTab
    monkeypatch.setitem(sys.modules, "qif_converter.gui.probe_tab", probe_tab)

    # convert_tab
    convert_tab = types.ModuleType("qif_converter.gui.convert_tab")
    class ConvertTab:
        def __init__(self, app, mb):
            self.in_path = _DummyVar("")
            self.out_path = _DummyVar("")
            self.emit_var = _DummyVar("qif")               # "qif" or "csv"
            self.csv_profile_var = _DummyVar("quicken-windows")  # csv profile
            self.match_var = _DummyVar("contains")
            self.case_var = _DummyVar(False)
            self.combine_var = _DummyVar("any")
            self.date_from = _DummyVar("")                 # ISO-like string or empty
            self.date_to = _DummyVar("")
            self.payees_text = _DummyVar("")
            self.log = []
        def _update_output_extension(self): return "updated-ext"
        def _parse_payee_filters(self): return []
        def logln(self, msg): self.log.append(msg)
    convert_tab.ConvertTab = ConvertTab
    monkeypatch.setitem(sys.modules, "qif_converter.gui.convert_tab", convert_tab)

    # utils used by app.py
    utils = types.ModuleType("qif_converter.gui.utils")
    utils.apply_multi_payee_filters = lambda txns, payees, mode, case_sensitive, combine: txns
    def write_csv_quicken_windows(txns, out_path: Path):
        out_path.write_text("windows", encoding="utf-8")
    def write_csv_quicken_mac(txns, out_path: Path):
        out_path.write_text("mac", encoding="utf-8")
    def filter_date_range(txns, start, end):
        return txns
    utils.write_csv_quicken_windows = write_csv_quicken_windows
    utils.write_csv_quicken_mac = write_csv_quicken_mac
    utils.filter_date_range = filter_date_range
    monkeypatch.setitem(sys.modules, "qif_converter.gui.utils", utils)

    # qif_writer used by app.py
    qif_writer = types.ModuleType("qif_converter.qif_writer")
    def write_qif(txns, out_path: Path):
        out_path.write_text("qif", encoding="utf-8")
    qif_writer.write_qif = write_qif
    monkeypatch.setitem(sys.modules, "qif_converter.qif_writer", qif_writer)

    # qif_loader and/or qfx_to_txns (app.py may import either depending on version)
    qif_loader = types.ModuleType("qif_converter.qif_loader")
    qif_loader.load_transactions = lambda p: [{"date": "2024-01-01", "payee": "Alpha", "amount": "1.00"}]
    monkeypatch.setitem(sys.modules, "qif_converter.qif_loader", qif_loader)

    qfx_to_txns = types.ModuleType("qif_converter.qfx_to_txns")
    qfx_to_txns.load_transactions = lambda p: [{"date": "2024-01-01", "payee": "Alpha", "amount": "1.00"}]
    monkeypatch.setitem(sys.modules, "qif_converter.qfx_to_txns", qfx_to_txns)


@pytest.fixture
def app_mod(monkeypatch, tmp_path):
    """
    Import qif_converter.gui.app with all GUI and project dependencies stubbed,
    returning the imported module object.
    """
    _install_gui_stubs(monkeypatch)
    _install_project_stubs(monkeypatch, tmp_path)

    # Ensure a clean import each time (independence/isolation)
    sys.modules.pop("qif_converter.gui.app", None)
    mod = importlib.import_module("qif_converter.gui.app")
    return mod


# --------------------------
#          TESTS
# --------------------------

def test_app_init_wires_tabs_and_wrappers(app_mod):
    """App initializes with tabs and exposes wrapper methods delegated to ConvertTab."""
    # Arrange
    fake_mb = _FakeMB()
    App = app_mod.App

    # Act
    app = App(messagebox_api=fake_mb)

    # Assert
    # Tabs created
    assert hasattr(app, "convert_tab"), "ConvertTab should be constructed"
    assert hasattr(app, "merge_tab"), "MergeTab should be constructed"
    assert hasattr(app, "probe_tab"), "ProbeTab should be constructed"
    # Wrapper methods are present and functional
    assert app._update_output_extension() == "updated-ext"
    assert app._parse_payee_filters() == []
    app.logln("hello")
    assert "hello" in app.convert_tab.log


def test_run_missing_input_shows_error(app_mod, tmp_path):
    """When input is missing/invalid, _run shows an error and aborts without writing output."""
    # Arrange
    fake_mb = _FakeMB()
    app = app_mod.App(messagebox_api=fake_mb)
    app.in_path.set("")  # missing
    out_path = tmp_path / "out.qif"
    app.out_path.set(str(out_path))

    # Act
    app._run()

    # Assert
    assert not out_path.exists(), "No output should be produced on invalid input"
    assert any(c[0] == "showerror" for c in fake_mb.calls), "Expected an error dialog"


def test_run_missing_output_shows_error(app_mod, tmp_path):
    """When output is missing, _run shows an error and aborts."""
    # Arrange
    fake_mb = _FakeMB()
    app = app_mod.App(messagebox_api=fake_mb)
    in_path = tmp_path / "input.qif"
    in_path.write_text("dummy", encoding="utf-8")
    app.in_path.set(str(in_path))
    app.out_path.set("")  # missing

    # Act
    app._run()

    # Assert
    assert any(c[0] == "showerror" for c in fake_mb.calls), "Expected an error dialog"


def test_run_decline_overwrite_does_not_write(app_mod, tmp_path):
    """If output exists and user declines overwrite, _run aborts without changing the file."""
    # Arrange
    fake_mb = _FakeMB(askyesno_return=False)
    app = app_mod.App(messagebox_api=fake_mb)
    in_path = tmp_path / "input.qif"
    in_path.write_text("dummy", encoding="utf-8")
    out_path = tmp_path / "out.qif"
    out_path.write_text("keepme", encoding="utf-8")

    app.in_path.set(str(in_path))
    app.out_path.set(str(out_path))

    # Act
    app._run()

    # Assert
    assert out_path.read_text(encoding="utf-8") == "keepme", "Existing file should be unchanged"
    assert any(c[0] == "askyesno" for c in fake_mb.calls), "Expected overwrite confirmation prompt"


def test_run_writes_qif_and_shows_info(app_mod, tmp_path):
    """Happy path (emit=qif): _run writes QIF output and notifies the user."""
    # Arrange
    fake_mb = _FakeMB(askyesno_return=True)
    app = app_mod.App(messagebox_api=fake_mb)
    in_path = tmp_path / "input.qif"
    in_path.write_text("dummy", encoding="utf-8")
    out_path = tmp_path / "out.qif"

    app.in_path.set(str(in_path))
    app.out_path.set(str(out_path))
    app.emit_var.set("qif")  # ensure QIF branch

    # Act
    app._run()

    # Assert
    assert out_path.exists(), "QIF file should be created"
    assert out_path.read_text(encoding="utf-8") == "qif", "Stub writer should produce 'qif'"
    assert any(c[0] == "showinfo" for c in fake_mb.calls), "Expected completion info dialog"


def test_run_writes_csv_windows_profile(app_mod, tmp_path):
    """CSV branch (quicken-windows): _run writes CSV via windows profile."""
    # Arrange
    fake_mb = _FakeMB(askyesno_return=True)
    app = app_mod.App(messagebox_api=fake_mb)
    in_path = tmp_path / "input.qif"
    in_path.write_text("dummy", encoding="utf-8")
    out_path = tmp_path / "out.csv"

    app.in_path.set(str(in_path))
    app.out_path.set(str(out_path))
    app.emit_var.set("csv")
    app.csv_profile_var.set("quicken-windows")

    # Act
    app._run()

    # Assert
    assert out_path.exists(), "CSV file should be created"
    assert out_path.read_text(encoding="utf-8") == "windows", "Windows CSV stub should write 'windows'"
    assert any(c[0] == "showinfo" for c in fake_mb.calls), "Expected completion info dialog"


def test_normalize_categories_forwards_to_merge_tab(app_mod):
    """_m_normalize_categories delegates to MergeTab.open_normalize_modal and returns its result."""
    # Arrange
    app = app_mod.App(messagebox_api=_FakeMB())

    # Act
    result = app._m_normalize_categories()

    # Assert
    assert result == "normalized"
