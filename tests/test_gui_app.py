# tests/test_gui_app.py
from pathlib import Path
import pytest

from qif_converter import gui as gui


# --------- Tiny stubs so we can use App methods without Tk ----------
class VarStub:
    def __init__(self, value=""):
        self._v = value
        self._traces = []

    def get(self):
        return self._v

    def set(self, v):
        self._v = v
        for cb in self._traces:
            cb()

    # emulate tkinter Variable trace_add used in App._build_ui
    def trace_add(self, *_):
        # store callbacks; tests will wire through manually if needed
        pass


class BoolVarStub(VarStub):
    def __init__(self, value=False):
        super().__init__(value)


class TextStub:
    def __init__(self):
        self._buf = ""

    def get(self, start, end):
        return self._buf

    def insert(self, index, text):
        self._buf += text

    def delete(self, start, end):
        self._buf = ""


class LogStub(TextStub):
    def see(self, *_):  # ignored
        pass

    def index(self, *_):
        # Return a changing marker so tests can compare before/after
        return str(len(self._buf))


# --------- A factory that builds a headless App instance ----------
def make_headless_app():
    """Create an App-like object without calling Tk.__init__ or building UI."""
    app = object.__new__(gui.App)  # bypass __init__

    # Stub the attributes App methods expect
    app.in_path = VarStub("")
    app.out_path = VarStub("")
    app.emit_var = VarStub("csv")          # csv or qif
    app.csv_profile = VarStub("default")
    app.explode_var = BoolVarStub(False)
    app.match_var = VarStub("contains")
    app.case_var = BoolVarStub(False)
    app.combine_var = VarStub("any")
    app.date_from = VarStub("")            # <-- needed by _run()
    app.date_to = VarStub("")              # <-- needed by _run()

    app.payees_text = TextStub()
    app.log = LogStub()

    # No-op to avoid calling into Tk
    app.update_idletasks = lambda *a, **k: None  # <-- avoid recursion from logln()

    # Sanity: methods exist on App
    assert hasattr(gui.App, "_update_output_extension")
    assert hasattr(gui.App, "_parse_payee_filters")
    assert hasattr(gui.App, "logln")
    assert hasattr(gui.App, "_run")

    return app


def mk_tmp_qif(tmp_path: Path) -> Path:
    p = tmp_path / "in.qif"
    p.write_text(
        "!Type:Bank\n"
        "D08/01'25\n"
        "T-1.23\n"
        "PTest\n"
        "LFood:Coffee\n"
        "^\n",
        encoding="utf-8",
    )
    return p


def test_auto_extension_switch_and_suggestion_headless(tmp_path: Path):
    app = make_headless_app()
    # Suggest from input when output empty
    in_file = tmp_path / "example.qif"
    in_file.write_text("", encoding="utf-8")
    app.in_path.set(str(in_file))

    app.out_path.set("")
    app.emit_var.set("csv")
    app._update_output_extension()
    assert app.out_path.get().endswith(".csv")
    assert Path(app.out_path.get()).stem == in_file.stem

    # Flip extensions when known
    app.out_path.set(str(tmp_path / "report.csv"))
    app.emit_var.set("qif")
    app._update_output_extension()
    assert app.out_path.get().endswith(".qif")

    app.emit_var.set("csv")
    app._update_output_extension()
    assert app.out_path.get().endswith(".csv")

    # Custom extension stays
    custom = tmp_path / "custom.txt"
    app.out_path.set(str(custom))
    app.emit_var.set("qif")
    app._update_output_extension()
    assert app.out_path.get().endswith(".txt")


def test_parse_payee_filters_and_log_headless():
    app = make_headless_app()
    app.payees_text.insert("end", "Starbucks,  Dunkin\n\nCafe")
    got = app._parse_payee_filters()
    assert got == ["Starbucks", "Dunkin", "Cafe"]

    before = app.log.index("end-1c")
    app.logln("Hello world")
    after = app.log.index("end-1c")
    assert after != before


def test_delayed_overwrite_prompt_csv_headless(tmp_path: Path, monkeypatch):
    app = make_headless_app()
    in_file = mk_tmp_qif(tmp_path)
    out_file = tmp_path / "out.csv"
    out_file.write_text("already", encoding="utf-8")

    app.in_path.set(str(in_file))
    app.out_path.set(str(out_file))
    app.emit_var.set("csv")
    app.csv_profile.set("default")
    app.explode_var.set(False)

    called = {"parse": 0, "flat": 0}

    monkeypatch.setattr(gui.mod, "parse_qif", lambda p: (called.__setitem__("parse", called["parse"] + 1) or []))
    monkeypatch.setattr(gui.mod, "write_csv_flat", lambda tx, p: called.__setitem__("flat", called["flat"] + 1))

    # Use an injected messagebox stub to avoid Tk calls
    from types import SimpleNamespace
    app.mb = SimpleNamespace(
        askyesno=lambda *a, **k: False,  # decline overwrite
        showinfo=lambda *a, **k: None,
        showerror=lambda *a, **k: None,
    )

    app._run()

    assert called["parse"] == 0  # declined overwrite → cancels before parsing
    assert called["flat"] == 0

    # Accept overwrite and run again
    app.mb = SimpleNamespace(
        askyesno=lambda *a, **k: True,
        showinfo=lambda *a, **k: None,
        showerror=lambda *a, **k: None,
    )
    app._run()

    assert called["parse"] == 1
    assert called["flat"] == 1


def test_delayed_overwrite_prompt_qif_headless(tmp_path: Path, monkeypatch):
    app = make_headless_app()
    in_file = mk_tmp_qif(tmp_path)
    out_file = tmp_path / "subset.qif"
    out_file.write_text("exists", encoding="utf-8")

    app.in_path.set(str(in_file))
    app.out_path.set(str(out_file))
    app.emit_var.set("qif")

    called = {"parse": 0, "write_qif": 0}
    monkeypatch.setattr(gui.mod, "parse_qif", lambda p: (called.__setitem__("parse", called["parse"] + 1) or []))
    monkeypatch.setattr(gui.mod, "write_qif", lambda tx, p: called.__setitem__("write_qif", called["write_qif"] + 1))

    from types import SimpleNamespace
    app.mb = SimpleNamespace(
        askyesno=lambda *a, **k: True,  # accept overwrite
        showinfo=lambda *a, **k: None,
        showerror=lambda *a, **k: None,
    )

    app._run()

    assert called["parse"] == 1
    assert called["write_qif"] == 1
