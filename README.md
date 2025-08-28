# QIF Converter & Category Normalizer

## Overview

QIF Converter is a Python application with a GUI for managing and normalizing financial data exported from Quicken and
similar platforms.  
It supports QIF parsing, Excel-based categorization, fuzzy-matching for transaction and category reconciliation, and
multiple output formats (QIF, CSV, Excel).

The tool is designed to help users align financial records with canonical category schemas (such as a MECE category set)
while maintaining control through manual adjustments.

---

## Features

### ✅ Transaction Handling

- Load QIF files with full support for splits, memos, and categories.
- Automatically match transactions with Excel-based reference data:
    - **Match by Amount (exact)**
    - **Match by Date (±3 days, penalized by distance)**
    - Prioritize exact-date matches.
- Manual review:
    - **Manually match** unmatched entries.
    - **Unmatch** incorrect pairs.
- Option to output **only matched items** with a checkbox.

### ✅ Category Normalization

- Extract categories directly from QIF transactions and Excel reference files.
- Deduplicate and sort categories alphabetically.
- Fuzzy auto-matching of category names between QIF and Excel (e.g., `"Utilities:Electric"` → `"Utilities: Electric"`).
- Manual override of auto-matches and ability to unmatch items.
- Write back the normalized categories into Excel (`Canonical MECE Category` column).

### ✅ Format Support

- **QIF**: legacy format for Quicken data import/export.
- **CSV**: flat or exploded (one row per split).
- **Excel**: enriched with categories and normalization.
- **QDX Probe**: experimental inspection of Quicken’s XML-based QDX files.
- **QFX**: acknowledged in documentation (OFX-based format used by banks).

### ✅ GUI Tabs

1. **QIF Conversion & Export**
    - Convert QIF to CSV, Excel, or back to QIF.
    - Apply payee filters, date ranges, and CSV profiles.
    - Overwrite protection with confirmation prompts.

2. **Transaction Matching**
    - Match QIF transactions with Excel records.
    - Apply MECE categories and item names from Excel.
    - Export updated QIF without overwriting source.

3. **Category Normalization**
    - Extract categories from QIF and Excel.
    - Fuzzy-match names automatically.
    - Manual match/unmatch controls.
    - Normalize and update Excel with canonical names.

4. **QDX Probe (Experimental)**
    - Inspect raw contents of `.QDX` files.
    - Detect zlib-compressed sections, embedded QIF, and XML fragments.
    - Display extracted strings and metadata.

---

## Recent Improvements (since v1.0)

- **GUI Enhancements**:
    - Added tab for transaction matching with Excel reference files.
    - Added tab for category normalization with fuzzy auto-matching.
    - Added checkbox option to export only matched transactions.
    - Added QDX probe tab for inspection of proprietary Quicken XML containers.

- **Testing & Reliability**:
    - Comprehensive unit tests for transaction matching, category normalization, filters, and GUI logic.
    - Dependency injection added for messageboxes → enables **headless testing** without Tkinter errors.
    - Over 40 tests, ~70% line coverage.

- **Documentation**:
    - Rewritten README with expanded format comparisons (QIF vs QFX vs QDX).
    - Step-by-step instructions for setup, running, and testing.

---

## Installation

### Requirements

- Python 3.9+
- Dependencies: `pandas`, `openpyxl`, `fuzzywuzzy`, `python-Levenshtein`, `tkinter`

### Setup

```bash
git clone https://github.com/yourusername/qif-converter.git
cd data_model-converter
pip install -r requirements.txt
```

### Running the GUI

```bash
python -m quicken_helper.gui_qif_runner
```

---

## Running Tests & Coverage

To run all tests:

```bash
pytest
```

To measure code coverage in **PyCharm**:

1. Right-click on the `tests/` folder.
2. Choose **Run with Coverage**.
3. Review the coverage report in PyCharm’s tool window.

From CLI:

```bash
pytest --cov=quicken_helper --cov-report=term-missing
```

---

## QIF vs QFX vs QDX

| Format  | Type                      | Usage                          | Notes                                |
|---------|---------------------------|--------------------------------|--------------------------------------|
| **QIF** | Text (line-based)         | Import/export in Quicken       | Legacy, flexible but inconsistent.   |
| **QFX** | OFX-based (XML)           | Bank downloads → Quicken       | Vendor-specific (Intuit) extensions. |
| **QDX** | Proprietary XML container | Internal Quicken file exchange | Can embed compressed QIF + metadata. |

---

## Roadmap

- Add support for **QFX parsing**.
- Improve **fuzzy match thresholds** with ML-based scoring.
- Extend coverage to >90% with integration tests.
- Package installer for Windows/macOS/Linux.

---

## License

MIT License.  
See [LICENSE](LICENSE) for details.
