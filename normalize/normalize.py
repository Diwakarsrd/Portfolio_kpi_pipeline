"""Turn mapped raw cells into canonical, comparable facts.

* period: parsed from the file CONTENT (calendar or fiscal), and compared with the file name later
* currency/unit: taken from the file's own note line; a file without one is an error, not a guess
* money -> USD via the fixed FX table; headcount and percentages are left as they are
* analyst corrections are applied to the native value, with the original and the reason retained
"""
import re
import sqlite3
from pathlib import Path

import pandas as pd
import yaml

from schema import KPI, UNIT_MULTIPLIERS

ROOT = Path(__file__).resolve().parents[1]
MONEY_KPIS = {KPI.REVENUE.value, KPI.COGS.value, KPI.GROSS_PROFIT.value, KPI.EBITDA.value, KPI.CASH.value, KPI.ARR.value}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_period(label: str, fiscal_year_end_month: int = 12) -> str:
    """'Jan-2026' | 'Jan 2026' | '2026-02' | '03/2026' | 'FY26 M10' -> 'YYYY-MM' (calendar month)."""
    s = label.strip()
    if m := re.fullmatch(r"(?i)FY(\d{2,4})\s*M(\d{1,2})", s):
        fy = int(m.group(1)) + (2000 if len(m.group(1)) == 2 else 0)
        n = int(m.group(2))
        if not 1 <= n <= 12:
            raise ValueError(f"bad fiscal month in {label!r}")
        idx = fiscal_year_end_month + n - 1
        return f"{fy - 1 + idx // 12:04d}-{idx % 12 + 1:02d}"
    if m := re.fullmatch(r"(?i)([a-z]{3})[a-z]*[\s-]+(\d{4})", s):
        return f"{int(m.group(2)):04d}-{MONTHS[m.group(1).lower()]:02d}"
    if m := re.fullmatch(r"(\d{4})-(\d{2})", s):
        return s
    if m := re.fullmatch(r"(\d{1,2})/(\d{4})", s):
        return f"{int(m.group(2)):04d}-{int(m.group(1)):02d}"
    raise ValueError(f"unrecognised period label {label!r}")


def load_fx(path: Path = ROOT / "config" / "fx.yaml") -> dict:
    return yaml.safe_load(path.read_text())


def load_corrections(path: Path | None) -> list[dict]:
    return yaml.safe_load(path.read_text()) if path and path.exists() else []


def normalize(mapped: pd.DataFrame, fx: dict, companies: dict, corrections: list[dict] | None = None) -> pd.DataFrame:
    rates = fx["rates_to_usd"]
    corr = {(c["company"], c["month"], c["kpi"]): c for c in (corrections or [])}
    used, rows = set(), []
    for r in mapped[mapped.kpi.notna()].itertuples():
        if pd.isna(r.currency) or pd.isna(r.unit):
            raise ValueError(f"{r.source_file}: no 'CURRENCY unit' note found - refusing to guess units")
        if r.currency not in rates:
            raise ValueError(f"{r.source_file}: currency {r.currency} missing from fx.yaml")
        fye = companies.get(r.company, {}).get("fiscal_year_end_month", 12)
        month = parse_period(r.period_label, fye)
        file_month = Path(r.source_file).stem
        native = None if pd.isna(r.raw_value) or isinstance(r.raw_value, str) else float(r.raw_value)
        orig, reason, corrected = native, None, False
        if (c := corr.get((r.company, file_month, r.kpi))):
            used.add((r.company, file_month, r.kpi))
            native, reason, corrected = float(c["corrected_value"]), c["reason"], True
        money = r.kpi in MONEY_KPIS
        mult = UNIT_MULTIPLIERS[r.unit] if money else 1.0
        rate = rates[r.currency] if money else 1.0
        rows.append(dict(company=r.company, month=month, file_month=file_month, kpi=r.kpi,
                         value=None if native is None else native * mult * rate,
                         native_value=native, currency=r.currency, unit=r.unit, multiplier=mult, fx_rate=rate,
                         source_file=r.source_file, location=r.location, raw_label=r.raw_label,
                         raw_value=r.raw_value, period_label=r.period_label,
                         corrected=corrected, original_native=orig if corrected else None, correction_reason=reason))
    if unused := set(corr) - used:
        raise ValueError(f"corrections that match no cell (typo?): {sorted(unused)}")
    return pd.DataFrame(rows)


def save(facts: pd.DataFrame, db_path: Path) -> None:
    with sqlite3.connect(db_path) as con:
        facts.to_sql("facts", con, if_exists="replace", index=False)
