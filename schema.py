"""Canonical KPI schema and the raw-cell record that carries provenance."""
from enum import Enum
from pydantic import BaseModel


class KPI(str, Enum):
    REVENUE = "revenue"
    COGS = "cogs"
    GROSS_PROFIT = "gross_profit"
    GROSS_MARGIN = "gross_margin_pct"
    EBITDA = "ebitda"
    CASH = "cash"
    HEADCOUNT = "headcount"
    ARR = "arr"
    CHURN = "churn_pct"


UNIT_MULTIPLIERS = {"units": 1, "thousands": 1e3, "lakhs": 1e5, "millions": 1e6, "crore": 1e7}


class RawCell(BaseModel):
    """One value from one source file, with enough info to trace it back."""
    company: str
    source_file: str
    location: str          # e.g. Report!C6, csv:row3:col4, p1:t0:r1c3
    column_index: int      # position in the header row (drives drift detection)
    raw_label: str
    raw_value: str | float | None
    currency: str | None   # parsed from the file own unit note
    unit: str | None
    period_label: str | None
