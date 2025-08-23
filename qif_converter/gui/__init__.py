
# Tests import/monkeypatch these off `qif_converter.gui`
from qif_converter import qif_writer as mod  # e.g., tests monkeypatch gui.mod.parse_qif

# Re-export shared helpers used by tests (you already have these in your new split code)
from .helpers import (
    parse_date_maybe,
    filter_date_range,
    local_filter_by_payee,
    apply_multi_payee_filters,
)
from .csv_profiles import (
    write_csv_quicken_windows,
    write_csv_quicken_mac,
    WIN_HEADERS,
    MAC_HEADERS,
)

from .scaling import (
    _safe_float,
    detect_system_font_scale,
    apply_global_font_scaling,
)

__all__ = [
    #"App",
    "parse_date_maybe",
    "filter_date_range",
    "local_filter_by_payee",
    "apply_multi_payee_filters",
    "write_csv_quicken_windows",
    "write_csv_quicken_mac",
]

# Lazily expose App to avoid importing tkinter during package import
def __getattr__(name):
    if name == "App":
        from .app import App  # imported only when actually accessed
        return App
    raise AttributeError(name)