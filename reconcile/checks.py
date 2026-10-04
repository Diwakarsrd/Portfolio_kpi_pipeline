"""Reconciliation: the fund rollup must equal the sum of the companies, and every fact must trace to a raw cell
and reproduce from it using an independent recomputation (cells + fx.yaml, not the stored multipliers)."""
import math

import pandas as pd

from reconcile.rollup import ADDITIVE
from schema import UNIT_MULTIPLIERS

MONEY = {"revenue", "cogs", "gross_profit", "ebitda", "cash", "arr"}


def _row(name, passed, n, worst, detail=""):
    return dict(check=name, passed=bool(passed), n_checked=n, max_abs_diff=worst, detail=detail)


def reconcile(facts: pd.DataFrame, cells: pd.DataFrame, ck: pd.DataFrame, fund: pd.DataFrame, fx: dict) -> pd.DataFrame:
    res, f = [], facts.reset_index(drop=True)
    # 1. fund total == sum of companies, three independent ways (rollup, math.fsum of contributors, pivot)
    worst, n, bad = 0.0, 0, []
    for k in ADDITIVE:
        piv = ck[ck.kpi == k].pivot_table(index="month", columns="company", values="value", aggfunc="sum")
        for r in fund[(fund.kpi == k) & fund.complete].itertuples():
            a, b, c = r.value, math.fsum(v for _, v, _ in r.contributors), float(piv.loc[r.month].sum())
            d = max(abs(a - b), abs(a - c)); worst, n = max(worst, d), n + 1
            if d > 1e-6 * max(1.0, abs(a)):
                bad.append((k, r.month, a, b, c))
    res.append(_row("fund_total_equals_sum_of_companies", not bad, n, worst, f"{len(bad)} mismatches" if bad else ""))
    # 2. incomplete fund figures must be blank, never a partial sum
    inc = fund[~fund.complete]
    res.append(_row("no_partial_sums", inc.value.isna().all(), len(inc), 0.0, f"{len(inc)} fund cells blank because a company was missing"))
    # 3. margins recomputed from the pieces
    worst, n = 0.0, 0
    for m in fund.month.unique():
        g = fund[fund.month == m].set_index("kpi")
        for name, num in [("gross_margin_pct", "gross_profit"), ("ebitda_margin_pct", "ebitda")]:
            if g.loc[name, "complete"]:
                n += 1; worst = max(worst, abs(g.loc[name, "value"] - g.loc[num, "value"] / g.loc["revenue", "value"] * 100))
    res.append(_row("fund_margins_recomputed", worst < 1e-6, n, worst))
    # 4. every fact traces to exactly one raw cell and reproduces from it
    key = cells.set_index(["source_file", "location"])
    missing, worst, n = 0, 0.0, 0
    for r in f.itertuples():
        try:
            c = key.loc[(r.source_file, r.location)]
        except KeyError:
            missing += 1; continue
        n += 1
        if pd.isna(c.raw_value) or isinstance(c.raw_value, str):
            continue
        native = r.original_native if r.corrected else r.native_value
        exp = c.raw_value * (UNIT_MULTIPLIERS[c.unit] * fx["rates_to_usd"][c.currency] if r.kpi in MONEY else 1.0)
        shown = native * (UNIT_MULTIPLIERS[c.unit] * fx["rates_to_usd"][c.currency] if r.kpi in MONEY else 1.0)
        worst = max(worst, abs(exp - shown))
        if not r.corrected and pd.notna(r.value):
            worst = max(worst, abs(exp - r.value))
    res.append(_row("every_fact_traces_to_raw_cell", missing == 0, len(f), float(missing), f"{missing} facts without a source cell"))
    res.append(_row("facts_reproduce_from_raw_cells", worst < 1e-3, n, worst))
    # 5. fx coverage
    miss = set(f.currency) - set(fx["rates_to_usd"])
    res.append(_row("fx_table_covers_all_currencies", not miss, f.currency.nunique(), 0.0, f"missing: {sorted(miss)}" if miss else f"as of {fx['as_of']}"))
    return pd.DataFrame(res)
