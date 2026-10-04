"""Read messy CSV / Excel / PDF reports into a flat table of RawCells.

Every value keeps its source file and cell location, so any number in the final
report can be traced back. Units and currency are read from the file's OWN note
line (never guessed), and the header row is found structurally: it is the row
just above the first row that contains several numbers.
"""
import csv
import re
import sqlite3
from pathlib import Path

import openpyxl
import pandas as pd
import pdfplumber

from schema import RawCell

NOTE_RE = re.compile(r"\b(USD|AED|INR)\s+(thousands|millions|lakhs|crore)\b", re.I)
NUM_RE = re.compile(r"^\(?-?\d[\d,]*\.?\d*\)?%?$")

Grid = list[list[tuple[object, str]]]  # rows of (value, location)


def parse_number(v):
    """Return float for numeric-looking values, else None. Handles 1,234.5 / (12) / 3%."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not NUM_RE.match(s):
        return None
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()").replace(",", "").rstrip("%")
    return -float(s) if neg else float(s)


def _is_data_row(row) -> bool:
    return sum(parse_number(v) is not None for v, _ in row) >= 3


def _extract(company: str, source_file: str, grid: Grid, note_text: str) -> list[RawCell]:
    data_idx = next((i for i, r in enumerate(grid) if _is_data_row(r)), None)
    if data_idx is None or data_idx == 0:
        raise ValueError(f"{source_file}: could not locate a header/data row pair")
    header, data = grid[data_idx - 1], grid[data_idx]
    m = NOTE_RE.search(note_text)
    currency, unit = (m.group(1).upper(), m.group(2).lower()) if m else (None, None)
    period = next((str(v) for (h, _), (v, _) in zip(header, data)
                   if str(h).strip().lower() == "period"), None)
    cells = []
    for c, ((h, _), (v, loc)) in enumerate(zip(header, data)):
        if h is None or str(h).strip() == "":
            continue
        num = parse_number(v)
        raw = num if num is not None else (None if v in (None, "") else str(v))
        cells.append(RawCell(company=company, source_file=source_file, location=loc,
                             column_index=c, raw_label=str(h).strip(), raw_value=raw,
                             currency=currency, unit=unit, period_label=period))
    return cells


def read_csv(path: Path, company: str) -> list[RawCell]:
    grid, notes = [], []
    for n, line in enumerate(path.read_text().splitlines(), start=1):
        if line.startswith("#"):
            notes.append(line)
            continue
        row = next(csv.reader([line]))
        grid.append([(v, f"csv:row{n}:col{c + 1}") for c, v in enumerate(row)])
    return _extract(company, str(path), grid, " ".join(notes))


def read_xlsx(path: Path, company: str) -> list[RawCell]:
    ws = openpyxl.load_workbook(path, data_only=True).active
    grid, notes = [], []
    for row in ws.iter_rows():
        # merged ranges only hold their value in the top-left cell; the rest are None
        grid.append([(c.value, f"{ws.title}!{c.coordinate}") for c in row])
        notes += [c.value for c in row if isinstance(c.value, str)]
    return _extract(company, str(path), grid, " ".join(notes))


def read_pdf(path: Path, company: str) -> list[RawCell]:
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        note_text = page.extract_text() or ""
        tables = page.extract_tables()
    if not tables:
        raise ValueError(f"{path}: no table found (scanned PDF? OCR not implemented)")
    grid = [[(v, f"p1:t0:r{r}c{c}") for c, v in enumerate(row)] for r, row in enumerate(tables[0])]
    return _extract(company, str(path), grid, note_text)


READERS = {".csv": read_csv, ".xlsx": read_xlsx, ".pdf": read_pdf}


def ingest_dir(raw_dir: Path) -> pd.DataFrame:
    cells: list[RawCell] = []
    for f in sorted(raw_dir.glob("*/*")):
        if f.suffix.lower() in READERS:
            cells += READERS[f.suffix.lower()](f, f.parent.name)
    return pd.DataFrame([c.model_dump() for c in cells])


def save(df: pd.DataFrame, db_path: Path) -> None:
    with sqlite3.connect(db_path) as con:
        df.to_sql("raw_cells", con, if_exists="replace", index=False)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    df = ingest_dir(root / "data" / "raw")
    save(df, root / "data" / "pipeline.db")
    print(f"{df.source_file.nunique()} files -> {len(df)} raw cells")
