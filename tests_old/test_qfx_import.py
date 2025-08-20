# tests/test_qfx_import.py
from __future__ import annotations
from pathlib import Path
import types

# Import the refactored GUI package entrypoints
from qif_converter import gui as gui


# ---- local lightweight stubs (self-contained) ----
class VarStub:
    def __init__(self, v=""):
        self._v = v
    def get(self): return self._v
    def set(self, v): self._v = v

class BoolVarStub(VarStub):
    pass

class TextStub:
    def __init__(self, text=""):
        self._text = text
    def get(self, a, b): return self._text

class LogStub:
    def __init__(self):
        self.lines = []
    def insert(self, *_):
        # capture last string argument
        if _:
            self.lines.append(str(_[-1]))
    def see(self, *_): pass
    def delete(self, *_): pass

def make_headless_app():
    """
    Create an App-like object without running Tk.__init__.
    We rely on App._run (legacy convert handler), which uses these attrs only.
    """
    app = object.__new__(gui.App)  # bypass __init__

    # Required state vars & widgets used in App._run
    app.in_path = VarStub("")
    app.out_path = VarStub("")
    app.emit_var = VarStub("csv")          # 'csv' or 'qif'
    app.csv_profile = VarStub("default")
    app.explode_var = BoolVarStub(False)
    app.match_var = VarStub("contains")
    app.case_var = BoolVarStub(False)
    app.combine_var = VarStub("any")
    app.date_from = VarStub("")
    app.date_to = VarStub("")
    app.payees_text = TextStub("")
    app.log = LogStub()
    app.update_idletasks = lambda *a, **k: None

    # Messagebox stub that always “agrees” but records calls
    mb = types.SimpleNamespace(
        calls=[],
        showinfo=lambda *a, **k: mb.calls.append(("showinfo", a, k)),
        showerror=lambda *a, **k: mb.calls.append(("showerror", a, k)),
        askyesno=lambda *a, **k: True,  # overwrite OK
    )
    app.mb = mb

    # keep the legacy helpers around (they’re defined on the real class)
    # We don't need to inject _update_output_extension/_parse_payee_filters/logln
    # because App._run calls its own bound methods, but they're present already.

    return app


# ---- helpers ----
def mk_tmp_qfx(tmp_path: Path) -> Path:
    # Content isn’t parsed here because we monkeypatch parse_qfx; file just needs to exist.
    p = tmp_path / "sample.qfx"
    p.write_text("<OFX>dummy</OFX>", encoding="utf-8")
    return p


# ---- tests ----
def test_qfx_to_csv_path(monkeypatch, tmp_path: Path):
    app = make_headless_app()

    in_file = mk_tmp_qfx(tmp_path)
    out_file = tmp_path / "out.csv"

    app.in_path.set(str(in_file))
    app.out_path.set(str(out_file))
    app.emit_var.set("csv")
    app.csv_profile.set("default")
    app.explode_var.set(False)

    called = {"parse_qfx": 0, "write_csv_flat": 0}

    # Ensure the QFX branch is taken and our parsed transactions flow through
    def fake_parse_qfx(path):
        called["parse_qfx"] += 1
        # minimal txn rows as dicts; downstream writers don't inspect deeply here
        return [{"date": "2025-08-01", "payee": "Coffee", "amount": "-3.50"}]

    monkeypatch.setattr("qif_converter.qfx_to_txns.parse_qfx", fake_parse_qfx)

    def fake_write_csv_flat(txns, path):
        called["write_csv_flat"] += 1
        # Write something small so test can verify output file exists if desired
        Path(path).write_text("ok", encoding="utf-8")

    monkeypatch.setattr("qif_converter.qif_to_csv.write_csv_flat", fake_write_csv_flat)

    # Run the legacy convert handler (App._run) which we updated to support QFX
    app._run()

    # Assertions
    assert called["parse_qfx"] == 1, "QFX parser was not invoked"
    assert called["write_csv_flat"] == 1, "CSV writer (default profile) was not invoked"
    assert out_file.exists(), "CSV output not created"
    # Optional: ensure log captured the QFX branch
    assert any("Parsing QFX" in ln for ln in app.log.lines), "Log did not show QFX parsing branch"


def test_qfx_to_qif_path(monkeypatch, tmp_path: Path):
    app = make_headless_app()

    in_file = mk_tmp_qfx(tmp_path)
    out_file = tmp_path / "subset.qif"

    app.in_path.set(str(in_file))
    app.out_path.set(str(out_file))
    app.emit_var.set("qif")  # switch to QIF output

    called = {"parse_qfx": 0, "write_qif": 0}

    def fake_parse_qfx(path):
        called["parse_qfx"] += 1
        return [{"date": "2025-08-02", "payee": "Grocer", "amount": "-45.00"}]

    monkeypatch.setattr("qif_converter.qfx_to_txns.parse_qfx", fake_parse_qfx)

    def fake_write_qif(txns, path):
        called["write_qif"] += 1
        Path(path).write_text("qif", encoding="utf-8")

    monkeypatch.setattr("qif_converter.qif_to_csv.write_qif", fake_write_qif)

    app._run()

    assert called["parse_qfx"] == 1, "QFX parser was not invoked"
    assert called["write_qif"] == 1, "QIF writer was not invoked"
    assert out_file.exists(), "QIF output not created"
    assert any("Parsing QFX" in ln for ln in app.log.lines), "Log did not show QFX parsing branch"
