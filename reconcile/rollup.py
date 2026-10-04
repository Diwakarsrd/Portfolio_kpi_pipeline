"""Fund-level rollup computed in pandas. Gross profit is derived (gross margin x revenue) for companies that
only report a margin, and that is recorded as derived. A fund figure is NEVER a partial sum: if any company
that normally reports a KPI is missing it in a month, the fund figure is blank and marked incomplete."""
import math

import pandas as pd

ADDITIVE = ["revenue", "gross_profit", "ebitda", "cash", "headcount", "arr"]


def company_kpis(facts: pd.DataFrame) -> pd.DataFrame:
    """Long table: company, month, kpi, value, derived, fact_ids (the cells it came from)."""
    f = facts.reset_index(drop=True).assign(fact_id=lambda d: d.index)
    rows = []
    for r in f.itertuples():
        rows.append(dict(company=r.company, month=r.month, kpi=r.kpi, value=r.value, derived=False, fact_ids=[r.fact_id]))
    have = {(r["company"], r["month"], r["kpi"]): r for r in rows}
    for (co, m, k), r in list(have.items()):
        if k == "gross_margin_pct" and (co, m, "gross_profit") not in have and (co, m, "revenue") in have:
            rev, gm = have[(co, m, "revenue")], r
            ok = pd.notna(rev["value"]) and pd.notna(gm["value"])
            rows.append(dict(company=co, month=m, kpi="gross_profit", derived=True,
                             value=rev["value"] * gm["value"] / 100 if ok else float("nan"),
                             fact_ids=rev["fact_ids"] + gm["fact_ids"]))
    return pd.DataFrame(rows)


def _expected(ck: pd.DataFrame, kpi: str) -> set[str]:
    return set(ck[ck.kpi == kpi].company)


def fund_rollup(ck: pd.DataFrame) -> pd.DataFrame:
    out, months = [], sorted(ck.month.unique())
    wide = {k: ck[ck.kpi == k].set_index(["company", "month"]) for k in ck.kpi.unique()}

    def contrib(kpi, m):
        exp = _expected(ck, kpi)
        d = wide[kpi].reset_index()
        d = d[d.month == m].set_index("company")
        ok = [c for c in sorted(exp) if c in d.index and pd.notna(d.loc[c, "value"])]
        return exp, ok, d

    for m in months:
        for k in ADDITIVE:
            exp, ok, d = contrib(k, m)
            done = len(ok) == len(exp) and len(exp) > 0
            out.append(dict(month=m, kpi=k, value=float(d.loc[ok, "value"].sum()) if done else float("nan"),
                            n_reporting=len(ok), n_expected=len(exp), complete=done, missing=",".join(sorted(exp - set(ok))),
                            contributors=[(c, float(d.loc[c, "value"]), d.loc[c, "fact_ids"]) for c in ok],
                            formula=f"sum of {len(exp)} companies" if len(exp) > 1 else "single company"))
        by = {r["kpi"]: r for r in out if r["month"] == m}
        for name, num, den, scale in [("gross_margin_pct", "gross_profit", "revenue", 100), ("ebitda_margin_pct", "ebitda", "revenue", 100)]:
            n, dn = by[num], by[den]
            done = n["complete"] and dn["complete"] and dn["value"] > 0
            out.append(dict(month=m, kpi=name, value=n["value"] / dn["value"] * scale if done else float("nan"), n_reporting=min(n["n_reporting"], dn["n_reporting"]),
                            n_expected=max(n["n_expected"], dn["n_expected"]), complete=done, missing=",".join(filter(None, [n["missing"], dn["missing"]])),
                            contributors=n["contributors"] + dn["contributors"], formula=f"fund {num} / fund {den}"))
        exp = _expected(ck, "churn_pct") & _expected(ck, "arr")
        _, okc, dc = contrib("churn_pct", m)
        _, oka, da = contrib("arr", m)
        both = [c for c in sorted(exp) if c in okc and c in oka]
        done = len(both) == len(exp) and len(exp) > 0
        w = sum(da.loc[c, "value"] for c in both)
        out.append(dict(month=m, kpi="churn_pct", complete=done, n_reporting=len(both), n_expected=len(exp), missing=",".join(sorted(set(exp) - set(both))),
                        value=sum(dc.loc[c, "value"] * da.loc[c, "value"] for c in both) / w if done and w else float("nan"),
                        contributors=[(c, float(dc.loc[c, "value"]), dc.loc[c, "fact_ids"] + da.loc[c, "fact_ids"]) for c in both],
                        formula="ARR-weighted average churn of SaaS companies"))
    return pd.DataFrame(out)
