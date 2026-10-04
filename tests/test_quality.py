import pandas as pd
import pytest
import yaml

from data_gen.generate import PLANTED, MONTHS
from quality.rules import Rule, load_rules, run_rules

PLANTED_KEYS = {(c, MONTHS[i], k) for c, i, k, *_ in PLANTED}


def _hits(v):
    return {(r.company, r.month, k) for r in v.itertuples() for k in r.involved.split(",")}


def test_every_planted_error_is_caught_by_a_failing_rule(facts_raw):
    v = run_rules(facts_raw, load_rules())
    fails = v[v.severity == "fail"]
    assert PLANTED_KEYS <= _hits(fails)  # recall 5/5, at 'fail' severity


def test_no_violations_outside_the_planted_cells(facts_raw):
    v = run_rules(facts_raw, load_rules())
    stray = {(r.company, r.month) for r in v.itertuples()} - {(c, m) for c, m, _ in PLANTED_KEYS}
    assert stray == set(), f"false positives: {stray}"


def test_clean_after_corrections(facts_ok):
    assert run_rules(facts_ok, load_rules()).empty


def test_spike_that_snaps_back_blames_only_the_spike(facts_raw):
    v = run_rules(facts_raw, load_rules())
    g = v[(v.company == "gulf_logistics") & (v.rule_id == "revenue_mom")]
    assert list(g.month) == ["2026-04"]  # May's drop back to normal is NOT flagged


def test_violations_point_to_a_source_cell(facts_raw):
    v = run_rules(facts_raw, load_rules())
    assert v.source_file.notna().all() and v.location.notna().all()


def test_editing_a_threshold_in_yaml_changes_the_outcome(facts_raw, tmp_path):
    cfg = yaml.safe_load(open("config/dq_rules.yaml"))
    for r in cfg["rules"]:
        if r["id"] == "churn_plausible":
            r["max"] = 60
    p = tmp_path / "rules.yaml"; p.write_text(yaml.safe_dump(cfg))
    v = run_rules(facts_raw, load_rules(p))
    assert "churn_plausible" not in set(v.rule_id)


@pytest.mark.parametrize("patch,msg", [
    ({"kpi": "revenu"}, "unknown KPI 'revenu'"),
    ({"type": "magic"}, "type"),
    ({"severity": "fatal"}, "severity"),
    ({"max": None, "min": None}, "needs min and/or max"),
    ({"surprise": 1}, "surprise"),
])
def test_bad_yaml_gives_a_readable_error(tmp_path, patch, msg):
    rule = {"id": "r1", "type": "range", "severity": "fail", "kpi": "revenue", "min": 0, "message": "m"}
    rule.update(patch)
    p = tmp_path / "r.yaml"; p.write_text(yaml.safe_dump({"rules": [rule]}))
    with pytest.raises(ValueError, match=msg):
        load_rules(p)


def test_duplicate_rule_ids_rejected(tmp_path):
    r = {"id": "dup", "type": "range", "severity": "fail", "kpi": "revenue", "min": 0, "message": "m"}
    p = tmp_path / "r.yaml"; p.write_text(yaml.safe_dump({"rules": [r, r]}))
    with pytest.raises(ValueError, match="duplicate"):
        load_rules(p)


def test_mom_rule_on_synthetic_series():
    vals = [100, 100, 500, 100, 100]  # spike then back
    f = pd.DataFrame([dict(company="c", month=f"2026-0{i + 1}", kpi="revenue", value=v, source_file="f", location=f"A{i}", file_month=f"2026-0{i + 1}")
                      for i, v in enumerate(vals)])
    rule = Rule(id="m", type="mom_change", severity="warn", kpis=["revenue"], max_abs_pct=50, message="{value:+.0f}")
    assert list(run_rules(f, [rule]).month) == ["2026-03"]
    f.loc[2:, "value"] = [500, 500, 500]  # genuine step change: flagged once, not repeatedly
    assert list(run_rules(f, [rule]).month) == ["2026-03"]
