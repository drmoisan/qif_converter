from __future__ import annotations

import io
from pathlib import Path


class MemFS:
    """
    Minimal in-memory FS that can be used by monkeypatching both builtins.open
    and Path.open. Files are addressed by str(path). Supports text mode only.
    Use scheme 'MEM://' for clarity, e.g., Path('MEM://in.qif').
    """
    def __init__(self):
        self._files: dict[str, str] = {}

    def _normalize(self, p: Path | str) -> str:
        # Accept Path or str; store by string form
        s = str(p)
        # Normalize single slash after scheme so both 'MEM://x' and 'MEM:/x' work
        if s.startswith("MEM:/") and not s.startswith("MEM://"):
            s = "MEM://" + s[len("MEM:/"):]
        return s

    def write(self, p: Path | str, text: str) -> None:
        self._files[self._normalize(p)] = text

    def read(self, p: Path | str) -> str:
        key = self._normalize(p)
        if key not in self._files:
            raise FileNotFoundError(key)
        return self._files[key]

    # Builtins/open-compatible function
    def open_builtin(self, file, mode="r", *args, **kwargs):
        # Only text mode for the tests
        path = self._normalize(file)
        if "b" in mode:
            raise ValueError("MemFS only supports text mode")
        if "r" in mode:
            data = self.read(path)
            return io.StringIO(data)
        elif "w" in mode or "x" in mode or "a" in mode:
            # start with existing (for append) or empty
            initial = self._files.get(path, "") if "a" in mode else ""
            buf = io.StringIO(initial)

            def _close_and_store():
                self._files[path] = buf.getvalue()
            # Hook close() to persist back into MemFS
            orig_close = buf.close
            def close():
                _close_and_store()
                orig_close()
            buf.close = close  # type: ignore[assignment]
            return buf
        else:
            raise ValueError(f"Unsupported mode: {mode}")

    # Path.open-compatible method
    def open_path(self, self_path: Path, mode="r", *args, **kwargs):
        return self.open_builtin(self_path, mode, *args, **kwargs)
