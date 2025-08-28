# tests/data_model/qif_parsers_emitters/test_emitter_integration_min.py
import importlib
import sys
from collections.abc import Iterable
from typing import TYPE_CHECKING

# Adjust these to your actual package paths once, then forget about it.
MODEL_MOD   = "quicken_helper.data_model.q_wrapper.q_file"
EMITTER_MOD = "quicken_helper.data_model.qif_parsers_emitters.qif_file_parser_emitter"

if TYPE_CHECKING:
    # Import types for annotations only (no runtime dependency).
    from quicken_helper.data_model.interfaces import IQuickenFile  # or where your protocol lives

def _fresh_import(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)

def test_model_import_does_not_pull_emitter():
    """
    Import the model only; ensure the emitter module is not imported as a side effect.
    This guards against circular deps (model -> emitter).
    """
    sys.modules.pop(EMITTER_MOD, None)
    model = _fresh_import(MODEL_MOD)
    assert EMITTER_MOD not in sys.modules, "Model import should not import the emitter"
    assert hasattr(model, "QuickenFile")

def test_parse_sets_backref_using_fake_emitter():
    """
    A minimal fake emitter implementing the protocol sets file.emitter = self
    and returns an iterable of files. Verifies the back-reference.
    """
    model = _fresh_import(MODEL_MOD)
    QF = model.QuickenFile

    class FakeEmitter:
        file_format = "QIF"

        def parse(self, unparsed_string: str) -> Iterable["IQuickenFile"]:
            f = QF()
            f.emitter = self  # back-reference
            return [f]

        def emit(self, obj: "Iterable[IQuickenFile] | IQuickenFile") -> str:
            # delegate to the model’s own emission API
            if hasattr(obj, "emit_qif"):
                return obj.emit_qif()                  # single file
            return "\n".join(x.emit_qif() for x in obj) # many files

    E = FakeEmitter()
    files = list(E.parse("dummy"))
    assert files and files[0].emitter is E


def test_emit_delegates_to_model(monkeypatch):
    """Emission should delegate to the model’s own method (no emitter->model cycle needed)."""
    model = _fresh_import(MODEL_MOD)
    f = model.QuickenFile()

    # Ensure we can recognize the emission clearly
    monkeypatch.setattr(f, "emit_qif", lambda: "SENTINEL-QIF")

    class FakeEmitter:
        def parse(self, s: str): return [f]
        def emit(self, obj: "Iterable[IQuickenFile] | IQuickenFile") -> str:
            if hasattr(obj, "emit_qif"):
                return obj.emit_qif()
            return "\n".join(x.emit_qif() for x in obj)

    E = FakeEmitter()
    assert E.emit(f) == "SENTINEL-QIF"
    assert E.emit([f, f]) == "SENTINEL-QIF\nSENTINEL-QIF"