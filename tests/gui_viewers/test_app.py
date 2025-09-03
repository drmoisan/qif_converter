# tests/gui_viewers/test_app.py
"""
Lean App smoke test after removing shims from app.py.

We keep minimal tkinter + GUI tab stubs so quicken_helper.gui_viewers.app
can import & build without a real display. This file intentionally does NOT
test Convert/Merge/Probe functionality; those now have dedicated tests.
"""

from __future__ import annotations

import importlib
import sys
import types
import pytest


# --------------------------
# Minimal tkinter stubs
# --------------------------

def _install_tk_stubs(monkeypatch):
    """Install minimal tkinter/ttk/font/messagebox stubs so App can import & run headlessly."""

    tk = types.ModuleType("tkinter")

    class Tk:
        def __init__(self, *a, **k): pass
        def geometry(self, *a, **k): pass
        def minsize(self, *a, **k): pass
        def option_add(self, *a, **k): pass
        def title(self, *a, **k): pass
        def mainloop(self, *a, **k): pass

    class StringVar:
        def __init__(self, value=""): self._v = value
        def get(self): return self._v
        def set(self, v): self._v = v

    class BooleanVar:
        def __init__(self, value=False): self._v = value
        def get(self): return self._v
        def set(self, v): self._v = v

    class Text:
        def __init__(self, *a, **k): self._buf = ""
        def get(self, s, e): return self._buf
        def insert(self, i, s): self._buf += s
        def delete(self, s, e): self._buf = ""
        def see(self, i): pass

    tk.Tk = Tk
    tk.StringVar = StringVar
    tk.BooleanVar = BooleanVar
    tk.Text = Text

    ttk = types.ModuleType("tkinter.ttk")

    class Frame:
        def __init__(self, *a, **k): pass
        def pack(self, *a, **k): pass
        def grid(self, *a, **k): pass

    class LabelFrame(Frame): pass

    class Button:
        def __init__(self, *a, **k): pass
        def grid(self, *a, **k): pass

    class Entry:
        def __init__(self, *a, **k): pass
        def grid(self, *a, **k): pass

    class Notebook(Frame):
        def __init__(self, *a, **k): pass
        def add(self, *a, **k): pass
        def pack(self, *a, **k): pass

    class Style:
        def __init__(self, *a, **k): pass
        def theme_use(self, *a, **k): pass
        def configure(self, *a, **k): pass
        def map(self, *a, **k): pass

    ttk.Frame = Frame
    ttk.LabelFrame = LabelFrame
    ttk.Button = Button
    ttk.Entry = Entry
    ttk.Notebook = Notebook
    ttk.Style = Style

    filedialog = types.ModuleType("tkinter.filedialog")
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

    # Register stubs
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.ttk", ttk)
    monkeypatch.setitem(sys.modules, "tkinter.messagebox", messagebox)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", filedialog)
    monkeypatch.setitem(sys.modules, "tkinter.font", font)


# --------------------------
# GUI submodule stubs (ConvertTab / MergeTab / ProbeTab)
# --------------------------

def _install_gui_submodule_stubs(monkeypatch):
    """Provide minimal stand-ins for GUI tabs so App wiring works without real UI."""

    # ConvertTab (accepts the new optional session param)
    convert_tab = types.ModuleType("quicken_helper.gui_viewers.convert_tab")

    class ConvertTab:
        def __init__(self, app, mb, session=None):
            self.app = app
            self.mb = mb
            self.session = session

    convert_tab.ConvertTab = ConvertTab
    monkeypatch.setitem(sys.modules, "quicken_helper.gui_viewers.convert_tab", convert_tab)

    # MergeTab
    merge_tab = types.ModuleType("quicken_helper.gui_viewers.merge_tab")

    class MergeTab:
        def __init__(self, *a, **k): pass

    merge_tab.MergeTab = MergeTab
    monkeypatch.setitem(sys.modules, "quicken_helper.gui_viewers.merge_tab", merge_tab)

    # ProbeTab
    probe_tab = types.ModuleType("quicken_helper.gui_viewers.probe_tab")

    class ProbeTab:
        def __init__(self, *a, **k): pass

    probe_tab.ProbeTab = ProbeTab
    monkeypatch.setitem(sys.modules, "quicken_helper.gui_viewers.probe_tab", probe_tab)


# --------------------------
# Fixture: import App with stubs
# --------------------------

@pytest.fixture
def app_mod(monkeypatch):
    """Import quicken_helper.gui_viewers.app with tkinter & GUI submodules stubbed."""
    _install_tk_stubs(monkeypatch)
    _install_gui_submodule_stubs(monkeypatch)

    # Clean import
    for key in list(sys.modules):
        if key.endswith(".app") and key.split(".")[-2] == "gui_viewers":
            sys.modules.pop(key, None)

    return importlib.import_module("quicken_helper.gui_viewers.app")


# --------------------------
# Tests
# --------------------------

def test_app_init_builds_tabs(app_mod):
    """App builds the Notebook and instantiates Convert/Merge/Probe tabs (no shim checks)."""
    App = app_mod.App
    app = App(messagebox_api=None)
    assert hasattr(app, "nb"), "Notebook should be constructed"
    assert hasattr(app, "convert_tab"), "ConvertTab should be constructed"
    assert hasattr(app, "merge_tab"), "MergeTab should be constructed"
    assert hasattr(app, "probe_tab"), "ProbeTab should be constructed"
