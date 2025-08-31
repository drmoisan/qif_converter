from __future__ import annotations

import inspect
import io
from collections.abc import Iterable
from dataclasses import field
from typing import cast, TYPE_CHECKING

if TYPE_CHECKING:
    from ..interfaces.i_parser_emitter import IParserEmitter

from ..interfaces import (
    HasEmitQifWithHeader,
    IAccount,
    ICategory,
    IQuickenFile,
    ITag,
    ITransaction,
    QuickenSections,
)
from .q_account import QAccount


def _emit_qif_text(item: object, with_header: bool) -> str:
    """
    Best-effort emitter to tolerate various shapes of 'emit' methods:
      - emit_qif(with_header: bool) -> str
      - emit_qif() -> str
      - emit_qif_text(with_header: bool) -> str
      - to_qif(with_header: bool) -> str
      - emit(with_header: bool) -> str
    Also tolerates implementations that return None but accept 'out' to write.
    Raises AttributeError if nothing workable is found.
    """
    # Try a few common method names in priority order
    for name in ("emit_qif", "emit_qif_text", "to_qif", "emit"):
        if not hasattr(item, name):
            continue
        func = getattr(item, name)
        try:
            sig = inspect.signature(func)
        except (TypeError, ValueError):
            # Builtins or callables without signatures — try simple call paths
            try:
                return func(with_header=with_header)  # type: ignore[call-arg]
            except TypeError:
                try:
                    return func()  # type: ignore[misc, call-arg]
                except AttributeError:
                    continue

        params = sig.parameters
        # Prefer keyword with_header if available
        try:
            if "with_header" in params:
                res = func(with_header=with_header)  # type: ignore[call-arg]
            else:
                # If function takes at least one positional arg, try positional
                # Else call with no args
                # (we don't attempt to pass arbitrary params — keep it simple/robust)
                if any(
                    p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
                    for p in params.values()
                ):
                    try:
                        res = func(with_header)  # type: ignore[call-arg]
                    except TypeError:
                        res = func()  # type: ignore[misc, call-arg]
                else:
                    res = func()  # type: ignore[misc, call-arg]
        except TypeError:
            # One more attempt: maybe it wants an 'out' TextIO
            try:
                buf = io.StringIO()
                if "out" in params and "with_header" in params:
                    func(out=buf, with_header=with_header)  # type: ignore[call-arg]
                elif "out" in params:
                    func(out=buf)  # type: ignore[call-arg]
                else:
                    continue
                res = buf.getvalue()
            except Exception:
                continue

        if res is None:
            # Implementations that write to an internal buffer and return None:
            # try calling with an 'out' buffer as a final fallback.
            try:
                buf = io.StringIO()
                if "out" in params:
                    if "with_header" in params:
                        func(out=buf, with_header=with_header)  # type: ignore[call-arg]
                    else:
                        func(out=buf)  # type: ignore[call-arg]
                    return buf.getvalue()
            except Exception:
                pass
            # If still None, treat as empty string
            return ""
        return str(res)

    raise AttributeError(
        "Item does not implement an emit method compatible with emit_section()."
    )


class QuickenFile(IQuickenFile):
    """
    Represents a complete QIF file, including header and multiple transactions.
    """

    def __init__(self):
        self.sections: QuickenSections = QuickenSections.NONE
        self.tags: list[ITag] = []
        self.categories: list[ICategory] = []
        self.accounts: list[IAccount] = []
        self.transactions: list[ITransaction] = []
        self.emitter: "IParserEmitter[IQuickenFile] | None" = None

    def emit_section(self, xs: Iterable[HasEmitQifWithHeader]) -> str:
        # texts_iter = map(lambda x: x[1].emit_qif(with_header=(x[0] == 0)), enumerate(xs))
        # return "\n".join(texts_iter)
        texts: list[str] = []
        for i, item in enumerate(xs):
            txt = _emit_qif_text(item, with_header=(i == 0))
            # Guard against None or non-string returns
            texts.append("" if txt is None else str(txt))
        return "\n".join(texts)

    def emit_transactions(self) -> str:
        """
        Returns the QIF representation of all transactions in this file.
        """
        if not self.transactions:
            return ""
        current_account: IAccount = field(default_factory=QAccount)

        texts: list[str] = []
        for i, item in enumerate(self.transactions):
            if item.account != current_account:
                current_account = item.account
                txt = item.emit_qif(with_account=True, with_type=True)
            else:
                txt = item.emit_qif(with_account=False, with_type=False)
            texts.append("" if txt is None else str(txt))
        return "\n".join(texts)

    def emit_qif(self) -> str:
        """
        Returns the complete QIF file content as a string.
        """
        if self.sections == QuickenSections.NONE:
            raise ValueError("No section specified for QIF file.")
        lines = []

        if self.sections.has_flag(QuickenSections.TAGS):
            lines.append(self.emit_section(self.tags))
        if self.sections.has_flag(QuickenSections.CATEGORIES):
            lines.append(self.emit_section(self.categories))
        if self.sections.has_flag(QuickenSections.ACCOUNTS):
            lines.append(
                self.emit_section(cast(list[HasEmitQifWithHeader], self.accounts))
            )
        if self.sections.has_flag(QuickenSections.TRANSACTIONS):
            lines.append(
                self.emit_section(cast(list[HasEmitQifWithHeader], self.transactions))
            )
        return "\n".join(lines)  # Ensure file ends with newline
