from __future__ import annotations

from collections.abc import Iterable, Callable
from typing import overload

from quicken_helper.data_model.interfaces import IParserEmitter, IQuickenFile, QuickenFileType
from quicken_helper.data_model.q_wrapper import QuickenFile  # concrete (no cycle, model doesn't import us)


class QifFileParserEmitter(IParserEmitter[IQuickenFile]):
    """Parse text into IQuickenFile objects and emit them back to text."""
    file_format: QuickenFileType = QuickenFileType.QIF

    def __init__(self, make_file: Callable[[], IQuickenFile] | None = None):
        self._make_file = make_file or QuickenFile  # default factory

    # --- required by IParserEmitter ---

    def parse(self, unparsed_string: str) -> Iterable[IQuickenFile]:
        """Return an iterable of IQuickenFile parsed from `unparsed_string`."""
        # build the concrete file(s)
        f = self._make_file()
        # ...fill f.sections/tags/accounts/transactions here...
        f.emitter = (
            self  # set back-reference (safe: typed as IParserEmitter[IQuickenFile])
        )
        return [f]

    def emit(self, obj: Iterable[IQuickenFile] | IQuickenFile) -> str:
        def _one(x: IQuickenFile) -> str:
            return x.emit_qif()  # use the model’s own emission

        if isinstance(obj, str) or not isinstance(obj, Iterable):
            return _one(obj)  # type: ignore[arg-type]
        return "\n".join(_one(x) for x in obj)


