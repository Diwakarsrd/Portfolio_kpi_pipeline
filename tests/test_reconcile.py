import math

import pytest

from reconcile.checks import reconcile
from reconcile.rollup import company_kpis, fund_rollup


@pytest.fixture(scope="module")
def parts(facts_ok):
    ck = company_kpis(facts_ok)
    return ck, fund_rollup(ck)


def test_all_reconciliation_checks_pass(facts_ok, cells, fx, parts):
    r = reconcile(facts_ok, cells, *parts, fx)
    assert r.passed.all() and len(r) == 6
    assert r.set_index("check").loc["fund_total_equals_sum_of_companies", "n_checked"] >= 30


def test_fund_equals_sum_of_companies_directly(parts):
    ck, fund = parts
    for k in ["revenue", "ebitda", "cash", "headcount", "arr"]:
        for m, g in ck[ck.kpi == k].groupby("month"):
            assert fund[(fund.kpi == k) & (fund.month == m)].value.iloc[0] == pytest.approx(math.fsum(g.value))


def test_derived_gross_profit_is_marked_and_correct(facts_ok, parts):
    ck, _ = parts
    d = ck[(ck.kpi == "gross_profit") & ck.derived]
    assert set(d.company) == {"bharat_foods", "pune_health"}  # companies that only report a margin
    r = d.iloc[0]
    rev = ck[(ck.company == r.company) & (ck.month == r.month) & (ck.kpi == "revenue")].value.iloc[0]
    gm = ck[(ck.company == r.company) & (ck.month == r.month) & (ck.kpi == "gross_margin_pct")].value.iloc[0]
    assert r.value == pytest.approx(rev * gm / 100) and len(r.fact_ids) == 2


def test_missing_company_value_blanks_the_fund_figure_never_partial(facts_raw):
    ck = company_kpis(facts_raw)
    fund = fund_rollup(ck)
    row = fund[(fund.kpi == "cash") & (fund.month == "2026-02")].iloc[0]
    assert not row.complete and math.isnan(row.value) and row.missing == "desert_solar" and row.n_reporting == 4
    assert fund[(fund.kpi == "cash") & (fund.month == "2026-03")].complete.iloc[0]  # other months unaffected


def test_tampered_fund_total_is_detected(facts_ok, cells, fx, parts):
    ck, fund = parts
    bad = fund.copy(); i = bad.index[(bad.kpi == "revenue") & (bad.month == "2026-06")][0]
    bad.loc[i, "value"] += 1000.0
    r = reconcile(facts_ok, cells, ck, bad, fx).set_index("check")
    assert not r.loc["fund_total_equals_sum_of_companies", "passed"]


def test_tampered_fact_no_longer_reproduces_from_raw(facts_ok, cells, fx, parts):
    ck, fund = parts
    bad = facts_ok.copy(); i = bad.index[(~bad.corrected) & (bad.kpi == "revenue")][0]
    bad.loc[i, "value"] *= 1.5
    r = reconcile(bad, cells, ck, fund, fx).set_index("check")
    assert not r.loc["facts_reproduce_from_raw_cells", "passed"]


def test_fact_with_no_source_cell_is_detected(facts_ok, cells, fx, parts):
    ck, fund = parts
    bad = facts_ok.copy(); bad.loc[bad.index[0], "location"] = "Z99"
    assert not reconcile(bad, cells, ck, fund, fx).set_index("check").loc["every_fact_traces_to_raw_cell", "passed"]
