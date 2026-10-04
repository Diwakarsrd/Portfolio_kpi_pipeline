import pandas as pd
import pytest

from normalize.normalize import normalize, parse_period

MONEY = {"revenue", "cogs", "gross_profit", "ebitda", "cash", "arr"}


@pytest.mark.parametrize("label,fye,expected", [
    ("Jan-2026", 12, "2026-01"), ("Jan 2026", 12, "2026-01"), ("2026-02", 12, "2026-02"), ("03/2026", 12, "2026-03"),
    ("FY26 M10", 3, "2026-01"), ("FY26 M12", 3, "2026-03"), ("FY27 M1", 3, "2026-04"), ("FY27 M3", 3, "2026-06"),
    ("FY26 M1", 3, "2025-04"), ("FY26 M12", 12, "2026-12")])
def test_parse_period(label, fye, expected):
    assert parse_period(label, fye) == expected


@pytest.mark.parametrize("bad", ["Q2 2026", "FY26 M13", "June", ""])
def test_parse_period_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_period(bad, 3)


def _tol(r):
    if r.kpi in MONEY:
        return 0.005 * r.multiplier * r.fx_rate * 1.001 + 1e-6  # half a unit of the last digit the company reported
    return 0.5 if r.kpi == "headcount" else 0.005 * 1.001


def _truth_errors(facts, truth):
    t = truth.set_index(["company", "month", "kpi"]).usd_value
    bad = []
    for r in facts.itertuples():
        exp = t.loc[(r.company, r.month, r.kpi)]
        if pd.isna(r.value) or abs(r.value - exp) > _tol(r):
            bad.append((r.company, r.month, r.kpi))
    return bad


def test_normalized_values_match_ground_truth_after_corrections(facts_ok):
    truth = pd.read_csv("data/truth.csv")
    assert len(facts_ok) == 192
    assert _truth_errors(facts_ok, truth) == []


def test_only_the_planted_cells_deviate_before_corrections(facts_raw):
    truth = pd.read_csv("data/truth.csv")
    assert sorted(_truth_errors(facts_raw, truth)) == sorted([
        ("gulf_logistics", "2026-04", "revenue"), ("nimbus_cloud", "2026-03", "gross_profit"), ("bharat_foods", "2026-05", "ebitda"),
        ("pune_health", "2026-06", "churn_pct"), ("desert_solar", "2026-02", "cash")])


def test_fiscal_year_company_aligns_to_calendar_months(facts_ok):
    assert sorted(facts_ok[facts_ok.company == "desert_solar"].month.unique()) == sorted(facts_ok[facts_ok.company == "nimbus_cloud"].month.unique())
    assert (facts_ok.month == facts_ok.file_month).all()


def test_corrections_keep_original_and_reason(facts_ok):
    c = facts_ok[facts_ok.corrected]
    assert len(c) == 5 and c.correction_reason.notna().all()
    gulf = c[(c.company == "gulf_logistics") & (c.kpi == "revenue")].iloc[0]
    assert gulf.original_native == pytest.approx(gulf.native_value * 10, rel=0.01)


def test_missing_unit_note_is_an_error_not_a_guess(mapped, fx, companies_cfg):
    bad = mapped.copy(); bad.loc[bad.company == "nimbus_cloud", "currency"] = None
    with pytest.raises(ValueError, match="refusing to guess"):
        normalize(bad, fx, companies_cfg)


def test_unknown_currency_is_an_error(mapped, fx, companies_cfg):
    bad = mapped.copy(); bad.loc[bad.company == "nimbus_cloud", "currency"] = "EUR"
    with pytest.raises(ValueError, match="fx.yaml"):
        normalize(bad, fx, companies_cfg)


def test_correction_that_matches_nothing_is_an_error(mapped, fx, companies_cfg):
    with pytest.raises(ValueError, match="match no cell"):
        normalize(mapped, fx, companies_cfg, [dict(company="nimbus_cloud", month="2026-01", kpi="arr_typo", corrected_value=1, reason="x")])
