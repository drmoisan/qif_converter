# tests/gui_viewers/test_app.py
"""
Unit tests for quicken_helper.gui_viewers.app.App

Policy adherence:
- Independent & isolated: stubs for tkinter and GUI tabs avoid real display/state.
- Fast & deterministic: no real GUI, filesystem only via tmp_path.
- AAA structure: each test is Arrange–Act–Assert.
- Clear intent: every test has a docstring explaining what it verifies.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

# --------------------------
# Tk / ttk / font / messagebox stubs
# --------------------------


class _DummyVar:
    """Simple stand-in for tkinter.StringVar used by App/ConvertTab."""

    def __init__(self, v=""):
        self._v = v

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


class _TextStub:
    """Minimal Text-like widget supporting get/insert/delete/see."""

    def __init__(self):
        self._buf = ""

    def get(self, start, end):
        return self._buf

    def insert(self, index, s):
        self._buf += s

    def delete(self, start, end):
        self._buf = ""

    def see(self, index):
        pass


class _FakeMB:
    """Messagebox shim that records calls and can control askyesno behavior."""

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


def _install_tk_stubs(monkeypatch):
    """Install minimal tkinter/ttk/font/messagebox stubs so App can import & run headlessly."""
    # tkinter root + variables
    tk = types.ModuleType("tkinter")

    class Tk:
        def __init__(self, *a, **k):
            pass

        def geometry(self, *a, **k):
            pass

        def minsize(self, *a, **k):
            pass

        def option_add(self, *a, **k):
            pass

        def title(self, *a, **k):
            pass

        def mainloop(self, *a, **k):
            pass

    tk.Tk = Tk
    tk.StringVar = _DummyVar
    tk.Text = _TextStub

    # ttk bits used by app.py
    ttk = types.ModuleType("tkinter.ttk")

    class Style:
        def __init__(self, *a, **k):
            pass

        def configure(self, *a, **k):
            pass

        def map(self, *a, **k):
            pass

        def theme_use(self, *a, **k):
            pass

    class Notebook:
        def __init__(self, *a, **k):
            self._tabs = []  # record tabs added (widget, text)

        def pack(self, *a, **k):
            pass

        def add(self, child, **k):
            self._tabs.append((child, k.get("text")))

        def configure(self, **k):
            pass

    class Frame:
        def __init__(self, *a, **k):
            pass

    ttk.Style = Style
    ttk.Notebook = Notebook
    ttk.Frame = Frame

    # messagebox (unused directly thanks to dependency-injection, but we stub anyway)
    messagebox = types.ModuleType("tkinter.messagebox")

    def _noop(*a, **k):
        return None

    messagebox.showinfo = _noop
    messagebox.showerror = _noop
    messagebox.askyesno = lambda *a, **k: True

    # filedialog (app imports it but we don't use it in tests)
    filedialog = types.ModuleType("tkinter.filedialog")

    # font
    font = types.ModuleType("tkinter.font")

    class _Font:
        def __init__(self, *a, **k):
            self._cfg = {"family": "TkDefaultFont", "size": 10, "weight": "normal"}

        def cget(self, k):
            return self._cfg.get(k)

        def configure(self, **k):
            self._cfg.update(k)

    def nametofont(name):
        return _Font()

    font.Font = _Font
    font.nametofont = nametofont

    # Register stubs
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", messagebox)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", filedialog)
    monkeypatch.setitem(sys.modules, "tkinter.font", font)


# --------------------------
# GUI submodule stubs (merge_tab / convert_tab / probe_tab)
# --------------------------


def _install_gui_submodule_stubs(monkeypatch):
    """Provide minimal stand-ins for GUI tabs so App wiring works without real UI."""
    # ConvertTab: expose variables and a Text-like log + payees_text
    convert_tab = types.ModuleType("quicken_helper.gui_viewers.convert_tab")

    class ConvertTab:
        def __init__(self, app, mb):
            self.app = app
            self.mb = mb
            self.in_path = _DummyVar("")
            self.out_path = _DummyVar("")
            self.emit_var = _DummyVar("data_model")  # "data_model" or "csv"
            self.csv_profile = _DummyVar("quicken-windows")  # CSV profile
            self.explode_var = _DummyVar(False)
            self.match_var = _DummyVar("contains")
            self.case_var = _DummyVar(False)
            self.combine_var = _DummyVar("any")
            self.date_from = _DummyVar("")
            self.date_to = _DummyVar("")
            self.payees_text = _TextStub()
            self.log = _TextStub()

        # Optional: delegate helpers (App may wrap these)
        def _update_output_extension(self):
            pass

        def _parse_payee_filters(self):
            return []

        def logln(self, msg):
            self.log.insert("end", msg + "\n")

    convert_tab.ConvertTab = ConvertTab
    monkeypatch.setitem(
        sys.modules, "quicken_helper.gui_viewers.convert_tab", convert_tab
    )

    # MergeTab: only the normalize modal is exercised
    merge_tab = types.ModuleType("quicken_helper.gui_viewers.merge_tab")

    class MergeTab:
        def __init__(self, *a, **k):
            # attrs that App might shim out for tests in the future
            self.m_qif_in = _DummyVar("")
            self.m_xlsx = _DummyVar("")
            self.m_qif_out = _DummyVar("")
            self.m_only_matched = _DummyVar(False)
            self.m_preview_var = _DummyVar(False)

        def open_normalize_modal(self):
            return "normalized"

    merge_tab.MergeTab = MergeTab
    monkeypatch.setitem(sys.modules, "quicken_helper.gui_viewers.merge_tab", merge_tab)

    # ProbeTab: empty shell
    probe_tab = types.ModuleType("quicken_helper.gui_viewers.probe_tab")

    class ProbeTab:
        def __init__(self, *a, **k):
            pass

    probe_tab.ProbeTab = ProbeTab
    monkeypatch.setitem(sys.modules, "quicken_helper.gui_viewers.probe_tab", probe_tab)

    # scaling: __init__.py imports these symbols; provide no-op implementations
    scaling = types.ModuleType("quicken_helper.gui_viewers.scaling")
    scaling._safe_float = lambda x, d: (
        d if isinstance(x, str) and not x.strip() else float(x)
    )
    scaling.detect_system_font_scale = lambda root=None: 1.0
    scaling.apply_global_font_scaling = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "quicken_helper.gui_viewers.scaling", scaling)


# --------------------------
# Import fixture
# --------------------------


@pytest.fixture
def app_mod(monkeypatch):
    """
    Import quicken_helper.gui_viewers.app with tkinter and GUI submodules stubbed.
    Returns the imported app module.
    """
    _install_tk_stubs(monkeypatch)
    _install_gui_submodule_stubs(monkeypatch)

    # Ensure a clean import of the target each time
    for key in list(sys.modules):
        if key.endswith(".app") and key.split(".")[-2] == "gui_viewers":
            sys.modules.pop(key, None)

    # Import canonical path
    return importlib.import_module("quicken_helper.gui_viewers.app")


# --------------------------
# Tests (AAA + docstrings)
# --------------------------


def test_app_init_wires_tabs_and_shims(app_mod):
    """App builds Notebook and wires Convert/Merge/Probe tabs; shim vars are exposed on App."""
    # Arrange
    App = app_mod.App
    mb = _FakeMB()

    # Act
    app = App(messagebox_api=mb)

    # Assert
    assert hasattr(app, "nb"), "Notebook should be constructed"
    assert hasattr(app, "convert_tab"), "ConvertTab should be constructed"
    assert hasattr(app, "merge_tab"), "MergeTab should be constructed"
    assert hasattr(app, "probe_tab"), "ProbeTab should be constructed"
    # Shims exist on App, pointing to ConvertTab vars
    assert isinstance(app.in_path, _DummyVar)
    assert isinstance(app.out_path, _DummyVar)
    assert isinstance(app.emit_var, _DummyVar)
    assert isinstance(app.csv_profile, _DummyVar)


def test_update_output_extension_blank_out_uses_in_path(app_mod, tmp_path):
    """When out_path is blank, _update_output_extension suggests in_path with proper extension."""
    # Arrange
    app = app_mod.App(messagebox_api=_FakeMB())
    src = tmp_path / "bank.data_model"
    src.write_text("x", encoding="utf-8")
    app.in_path.set(str(src))
    app.out_path.set("")  # blank
    app.emit_var.set("csv")  # target CSV

    # Act
    app._update_output_extension()

    # Assert
    assert app.out_path.get().endswith(".csv"), "Expected suggested .csv out path"


def test_update_output_extension_switches_extension(app_mod, tmp_path):
    """_update_output_extension switches .data_model↔.csv when emit_var changes."""
    # Arrange
    app = app_mod.App(messagebox_api=_FakeMB())
    out = tmp_path / "out.data_model"
    app.out_path.set(str(out))
    app.emit_var.set("csv")

    # Act
    app._update_output_extension()

    # Assert
    assert app.out_path.get().endswith(
        ".csv"
    ), "Expected .csv after switching emit to csv"

    # Flip back to data_model
    app.emit_var.set("data_model")
    app._update_output_extension()
    assert app.out_path.get().endswith(
        ".data_model"
    ), "Expected .data_model after switching emit to data_model"


def test_parse_payee_filters_parses_lines_and_commas(app_mod):
    """_parse_payee_filters splits on newlines/commas, trims whitespace, and drops empties."""
    # Arrange
    app = app_mod.App(messagebox_api=_FakeMB())
    app.payees_text.insert("end", " Alpha,  Beta \n\nGamma ,\n  ")

    # Act
    got = app._parse_payee_filters()

    # Assert
    assert got == ["Alpha", "Beta", "Gamma"]


def test_run_missing_input_shows_error(app_mod, tmp_path):
    """_run shows error and aborts when input file is missing or empty path."""
    # Arrange
    mb = _FakeMB()
    app = app_mod.App(messagebox_api=mb)
    app.in_path.set("")  # missing
    app.out_path.set(str(tmp_path / "out.data_model"))

    # Act
    app._run()

    # Assert
    assert any(
        c[0] == "showerror" for c in mb.calls
    ), "Expected an error dialog for missing input"


def test_run_missing_output_shows_error(app_mod, tmp_path):
    """_run shows error and aborts when output path is missing."""
    # Arrange
    mb = _FakeMB()
    app = app_mod.App(messagebox_api=mb)
    src = tmp_path / "input.data_model"
    src.write_text("x", encoding="utf-8")
    app.in_path.set(str(src))
    app.out_path.set("")  # missing

    # Act
    app._run()

    # Assert
    assert any(
        c[0] == "showerror" for c in mb.calls
    ), "Expected an error dialog for missing output"


def test_run_decline_overwrite_does_not_write(app_mod, tmp_path):
    """If output exists and user declines overwrite, _run leaves the file unchanged."""
    # Arrange
    mb = _FakeMB(askyesno_return=False)
    app = app_mod.App(messagebox_api=mb)
    src = tmp_path / "input.data_model"
    src.write_text("x", encoding="utf-8")
    out = tmp_path / "out.data_model"
    out.write_text("keep", encoding="utf-8")
    app.in_path.set(str(src))
    app.out_path.set(str(out))
    app.emit_var.set("data_model")

    # Act
    app._run()

    # Assert
    assert (
        out.read_text(encoding="utf-8") == "keep"
    ), "Existing file should remain unchanged"
    assert any(
        c[0] == "askyesno" for c in mb.calls
    ), "Expected overwrite confirmation prompt"


def test_run_writes_qif_and_shows_info(app_mod, tmp_path, monkeypatch):
    """Happy path (emit=data_model): _run calls writer and notifies the user."""
    # Arrange
    mb = _FakeMB(askyesno_return=True)
    app = app_mod.App(messagebox_api=mb)
    src = tmp_path / "input.data_model"
    src.write_text("x", encoding="utf-8")
    out = tmp_path / "out.data_model"
    app.in_path.set(str(src))
    app.out_path.set(str(out))
    app.emit_var.set("data_model")

    # Stub the writer used by app.py (module-level import alias `mod`)
    monkeypatch.setattr(
        app_mod.mod,
        "write_qif",
        lambda txns, p: Path(p).write_text("data_model", encoding="utf-8"),
    )

    # Also stub parsers so we don't depend on real parsing
    qloader = types.ModuleType("quicken_helper.qif_loader")
    qloader.load_transactions = lambda p: [
        {"date": "2024-01-01", "payee": "Alpha", "amount": "1.00"}
    ]
    monkeypatch.setitem(sys.modules, "quicken_helper.qif_loader", qloader)

    # Act
    app._run()

    # Assert
    assert out.exists(), "QIF file should be created"
    assert out.read_text(encoding="utf-8") == "data_model"
    assert any(c[0] == "showinfo" for c in mb.calls), "Expected completion info dialog"


def test_run_writes_csv_windows_profile(app_mod, tmp_path, monkeypatch):
    """CSV branch (quicken-windows): _run writes CSV via utils.write_csv_quicken_windows and notifies."""
    # Arrange
    mb = _FakeMB(askyesno_return=True)
    app = app_mod.App(messagebox_api=mb)
    src = tmp_path / "input.data_model"
    src.write_text("x", encoding="utf-8")
    out = tmp_path / "out.csv"
    app.in_path.set(str(src))
    app.out_path.set(str(out))
    app.emit_var.set("csv")
    app.csv_profile.set("quicken-windows")

    # Stub parser + CSV writer (imported inside _run)
    qloader = types.ModuleType("quicken_helper.qif_loader")
    qloader.load_transactions = lambda p: [
        {"date": "2024-01-01", "payee": "Alpha", "amount": "1.00"}
    ]
    monkeypatch.setitem(sys.modules, "quicken_helper.qif_loader", qloader)

    # Replace utils function that _run imports at call time
    utils_mod = importlib.import_module("quicken_helper.gui_viewers.utils")
    monkeypatch.setattr(
        utils_mod,
        "write_csv_quicken_windows",
        lambda txns, p: Path(p).write_text("windows", encoding="utf-8"),
    )

    # Act
    app._run()

    # Assert
    assert out.exists(), "CSV file should be created"
    assert out.read_text(encoding="utf-8") == "windows"
    assert any(c[0] == "showinfo" for c in mb.calls), "Expected completion info dialog"


def test_m_normalize_categories_delegates_to_merge_tab(app_mod):
    """_m_normalize_categories forwards to MergeTab.open_normalize_modal and returns its result."""
    # Arrange
    app = app_mod.App(messagebox_api=_FakeMB())

    # Act
    result = app._m_normalize_categories()

    # Assert
    assert result == "normalized"
