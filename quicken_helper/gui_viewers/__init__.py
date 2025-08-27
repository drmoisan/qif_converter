
# Tests import/monkeypatch these off `quicken_helper.gui_viewers`

# Re-export shared helpers used by tests (you already have these in your new split code)
from .csv_profiles import (
    write_csv_quicken_mac,
    write_csv_quicken_windows,
)
from .helpers import (
    apply_multi_payee_filters,
    filter_date_range,
    local_filter_by_payee,
    parse_date_maybe,
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