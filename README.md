
# QIF → CSV Converter (Updated: filtering + QIF writer)

## What’s inside
- `qif_converter/qif_to_csv.py` — parser, CSV writers (flat/exploded), **payee filtering**, and `write_qif` + CLI
- `tests/test_qif_to_csv.py` — main parser/writer tests
- `tests/test_filters_and_qif_writer.py` — tests for filtering + QIF round-trip
- `pytest.ini` — tells PyCharm/pytest where tests live
- `requirements.txt` — test dependency

## Run tests
```bash
pip install -r requirements.txt
pytest -q
```

## CLI usage
```bash
# CSV out (flattened, default)
python -m qif_converter.qif_to_csv input.qif output.csv

# CSV out (exploded: one row per split)
python -m qif_converter.qif_to_csv input.qif output.csv --explode-splits

# Filter by payee (contains, case-insensitive)
python -m qif_converter.qif_to_csv input.qif filtered.csv --filter-payee Starbucks

# Exact, case-sensitive
python -m qif_converter.qif_to_csv input.qif out.csv --filter-payee "STARBUCKS 456" --match exact --case-sensitive

# Regex
python -m qif_converter.qif_to_csv input.qif dunkin.csv --filter-payee "dunkin( donuts)?" --match regex

# Emit filtered QIF instead of CSV
python -m qif_converter.qif_to_csv input.qif subset.qif --filter-payee Starbucks --emit qif
```
