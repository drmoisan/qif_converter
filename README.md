
# QIF → CSV Converter (v3: Multi-payee filters, glob, Quicken CSV profiles, date ranges)

## New in this version
- Multiple `--filter-payee` values with `--combine any|all`
- Match modes now include `glob` (`Star*`, `*bucks`)
- CSV profiles: `--csv-profile quicken-windows` and `--csv-profile quicken-mac`
- Date range filtering: `--date-from`, `--date-to` (accepts `mm/dd'yy`, `mm/dd/yyyy`, or `yyyy-mm-dd`)

## Examples
```bash
# Any Starbucks or Dunkin, case-insensitive, generic CSV
python -m qif_converter.qif_to_csv in.qif out.csv --filter-payee starbucks --filter-payee dunkin --combine any

# Both a Star* prefix and *456 suffix (glob, all)
python -m qif_converter.qif_to_csv in.qif out.csv --filter-payee "star*" --filter-payee "*456" --match glob --combine all

# Quicken Windows profile
python -m qif_converter.qif_to_csv in.qif win.csv --filter-payee starbucks --csv-profile quicken-windows

# Quicken Mac (Mint) profile
python -m qif_converter.qif_to_csv in.qif mac.csv --filter-payee starbucks --csv-profile quicken-mac

# Date range filter (inclusive)
python -m qif_converter.qif_to_csv in.qif out.csv --date-from "08/01'25" --date-to 2025-08-15
```

## Tests
```bash
pip install -r requirements.txt
pytest -q
```
