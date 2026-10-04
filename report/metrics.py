"""Every number in the LP report is a Metric computed here, in pandas. A metric carries its display string
and the exact source cells behind it, so any figure can be traced back to file + cell."""
import pandas as pd

KIND_USD, KIND_PCT, KIND_COUNT = "usd", "pct", "count"


def fmt_usd(v: float) -> str:
    a, sign = abs(v), "-" if v < 0 else ""
    if a >= 1e9:
        return f"{sign}${a / 1e9:.1f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.1f}M"
    if a >= 1e3:
        return f"{sign}${a / 1e3:.0f}K"
    return f"{sign}${a:.0f}"


def fmt(kind: str, v: float, signed: bool = False) -> str:
    if kind == KIND_USD:
        return fmt_usd(v)
    if kind == KIND_PCT:
        return f"{v:+.1f}%" if signed else f"{v:.1f}%"
    return f"{v:,.0f}"


def _src(facts: pd.DataFrame, ids: list[int]) -> list[dict]:
    f = facts.reset_index(drop=True)
    out = []
    for i in dict.fromkeys(ids):
        r = f.loc[i]
        out.append(dict(company=r.company, month=r.month, kpi=r.kpi, source_file=r.source_file, location=r.location,
                        raw_label=r.raw_label, raw_value=None if pd.isna(r.raw_value) else r.raw_value,
                        currency=r.currency, unit=r.unit, corrected=bool(r.corrected)))
    return out


def build_metrics(facts, ck, fund, dq, drift, month: str, prev: str, n_months_window: int) -> list[dict]:
    M = []

    def add(mid, label, value, kind, period, sources=(), formula="", signed=False):
        M.append(dict(id=mid, label=label, value=float(value), kind=kind, period=period, signed=signed,
                      display=fmt(kind, float(value), signed), sources=list(sources), formula=formula))

    g = lambda m, k: fund[(fund.month == m) & (fund.kpi == k)].iloc[0]  # noqa: E731
    names = {"revenue": ("Revenue", KIND_USD), "gross_margin_pct": ("Gross margin", KIND_PCT), "ebitda": ("EBITDA", KIND_USD),
             "ebitda_margin_pct": ("EBITDA margin", KIND_PCT), "cash": ("Cash", KIND_USD), "headcount": ("Headcount", KIND_COUNT),
             "arr": ("ARR", KIND_USD), "churn_pct": ("Churn (ARR-weighted)", KIND_PCT)}
    for k, (label, kind) in names.items():
        for m in (month, prev):
            r = g(m, k)
            if r.complete:
                ids = [i for _, _, fi in r.contributors for i in fi]
                add(f"fund.{k}.{m}", f"Fund {label} {m}", r.value, kind, m, _src(facts, ids), r.formula)
        a, b = g(month, k), g(prev, k)
        if k in ("revenue", "ebitda", "cash", "headcount", "arr") and a.complete and b.complete and b.value:
            ids = [i for r in (a, b) for _, _, fi in r.contributors for i in fi]
            add(f"fund.{k}.mom", f"Fund {label} change vs {prev}", (a.value / b.value - 1) * 100, KIND_PCT, month,
                _src(facts, ids), f"({month} / {prev} - 1) x 100", signed=True)
    ytd = fund[(fund.kpi == "revenue") & fund.complete & (fund.month <= month)]
    ids = [i for r in ytd.itertuples() for _, _, fi in r.contributors for i in fi]
    add("fund.revenue.window", f"Fund revenue, {len(ytd)}-month total to {month}", ytd.value.sum(), KIND_USD, month, _src(facts, ids), "sum of monthly fund revenue")
    rev = g(month, "revenue")
    movers = []
    for co, _, fi in rev.contributors:
        v = ck[(ck.company == co) & (ck.month == month)].set_index("kpi")
        add(f"co.{co}.revenue.{month}", f"{co} revenue {month}", v.loc["revenue", "value"], KIND_USD, month, _src(facts, fi))
        add(f"co.{co}.revenue_share", f"{co} share of fund revenue", v.loc["revenue", "value"] / rev.value * 100, KIND_PCT, month, _src(facts, fi))
        if "ebitda" in v.index and pd.notna(v.loc["ebitda", "value"]):
            ids = v.loc["revenue", "fact_ids"] + v.loc["ebitda", "fact_ids"]
            add(f"co.{co}.ebitda_margin", f"{co} EBITDA margin", v.loc["ebitda", "value"] / v.loc["revenue", "value"] * 100, KIND_PCT, month, _src(facts, ids))
        p = ck[(ck.company == co) & (ck.month == prev) & (ck.kpi == "revenue")]
        if len(p) and pd.notna(p.iloc[0].value) and p.iloc[0].value:
            ids = v.loc["revenue", "fact_ids"] + p.iloc[0].fact_ids
            add(f"co.{co}.revenue_mom", f"{co} revenue change vs {prev}", (v.loc["revenue", "value"] / p.iloc[0].value - 1) * 100, KIND_PCT, month,
                _src(facts, ids), signed=True)
            movers.append(v.loc["revenue", "value"] > p.iloc[0].value)
    add("n_companies", "Portfolio companies", len(rev.contributors), KIND_COUNT, month)
    add("n_months", "Months in window", n_months_window, KIND_COUNT, month)
    add("n_rev_up", "Companies with revenue up", sum(movers), KIND_COUNT, month)
    add("n_rev_down", "Companies with revenue down", len(movers) - sum(movers), KIND_COUNT, month)
    add("dq_open_fail", "Open data-quality failures", int(((dq.severity == "fail")).sum()), KIND_COUNT, month)
    add("dq_warn", "Data-quality warnings", int(((dq.severity == "warn")).sum()), KIND_COUNT, month)
    add("n_corrections", "Analyst corrections applied", int(facts.corrected.sum()), KIND_COUNT, month)
    add("n_drift_events", "Schema drift events", int((drift.event != "baseline").sum()), KIND_COUNT, month)
    return M
