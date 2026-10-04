import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data_gen.generate import COMPANIES, MONTHS  # noqa: E402
from drift.detect import detect  # noqa: E402
from ingest.raw_cells import ingest_dir  # noqa: E402
from mapping.confirm import apply  # noqa: E402
from mapping.llm import parse_answer  # noqa: E402
from mapping.matcher import load_synonyms, match  # noqa: E402
from mapping.resolve import resolve  # noqa: E402

HELDOUT = yaml.safe_load((ROOT / "tests" / "heldout_labels.yaml").read_text())


def test_heldout_no_wrong_auto_accept_and_shortlist_quality():
    syn, kpi_rows, hits = load_synonyms(), [r for r in HELDOUT if r["expect"]], 0
    for r in HELDOUT:
        c = match(r["label"], syn)
        if c.status == "auto":
            assert c.kpi == r["expect"], f"wrong auto-accept: {r['label']}"
        if r["expect"] is None:
            assert c.status != "auto", f"distractor auto-accepted: {r['label']}"
        else:
            hits += r["expect"] in [o[0] for o in c.options]
    assert hits / len(kpi_rows) >= 0.9


def test_percent_guard_keeps_margin_and_profit_apart():
    syn = load_synonyms()
    assert match("Gross Margin %", syn).kpi == "gross_margin_pct"
    assert match("Gross Profit", syn).kpi == "gross_profit"


@pytest.mark.parametrize("text,ok", [('{"kpi":"revenue","reason":"x"}', True), ('{"kpi":"none"}', True),
                                     ('{"kpi":"total_revenue"}', False), ("not json", False), ('{"reason":"x"}', False)])
def test_llm_answer_validation(text, ok):
    assert (parse_answer(text) is not None) == ok


def test_apply_rejects_non_canonical_kpi(tmp_path):
    with pytest.raises(ValueError):
        apply([dict(company="x", label="y", kpi="made_up", source="human")], tmp_path)


class StubResolver:
    def __init__(self, answer): self.answer, self.calls = answer, 0
    def resolve(self, label, siblings, options):
        self.calls += 1
        return self.answer


@pytest.fixture(scope="module")
def cells():
    return ingest_dir(ROOT / "data" / "raw")


def test_first_run_to_steady_state(cells, tmp_path):
    # Run 1: nothing approved yet -> everything pending, nothing treated as a KPI (fail closed)
    mapped, pending = resolve(cells, None, tmp_path)
    assert mapped.kpi.isna().all()  # no human approval yet -> no cell may carry a KPI
    assert set(mapped.map_status) == {"pending", "reserved"} and len(pending) == sum(len(c["labels"]) for c in COMPANIES.values()) + 1  # +1 = renamed churn label
    # Human bulk-approves near-exact matches
    autos = [p for p in pending if p["status"] == "auto"]
    apply([dict(company=p["company"], label=p["label"], kpi=p["suggestion"], source="auto-confirmed") for p in autos], tmp_path)
    # Run 2: only the genuinely ambiguous label remains; the LLM suggestion is attached
    stub = StubResolver(("churn_pct", "logo churn is a churn rate"))
    mapped, pending = resolve(cells, stub, tmp_path)
    assert [(p["company"], p["label"]) for p in pending] == [("pune_health", "Logo Churn")]
    assert pending[0]["suggestion"] == "churn_pct" and pending[0]["suggestion_source"] == "llm" and stub.calls == 1
    apply([dict(company="pune_health", label="Logo Churn", kpi="churn_pct", source="human")], tmp_path)
    # Run 3: steady state -> zero pending, zero LLM calls, mapping matches ground truth
    stub2 = StubResolver(("revenue", "should never be called"))
    mapped, pending = resolve(cells, stub2, tmp_path)
    assert pending == [] and stub2.calls == 0
    truth = {(co, l): k for co, c in COMPANIES.items() for k, l in c["labels"].items()}
    truth[("pune_health", "Logo Churn")] = "churn_pct"
    kpi_cells = mapped[mapped.map_status == "saved"].drop_duplicates(["company", "raw_label"])
    assert {(r.company, r.raw_label): r.kpi for r in kpi_cells.itertuples()} == truth
    assert set(mapped[mapped.raw_label == "Period"].map_status) == {"reserved"}


def test_invalid_llm_answer_falls_back_to_human(cells, tmp_path):
    _, pending = resolve(cells, StubResolver(None), tmp_path)
    logo = next(p for p in pending if p["label"] == "Logo Churn")
    assert logo["suggestion_source"] == "fuzzy" and logo["llm_reason"] is None


def test_drift_events(cells, tmp_path):
    mapped, pending = resolve(cells, None, tmp_path)
    apply([dict(company=p["company"], label=p["label"], kpi=p["suggestion"], source="t") for p in pending
           if p["suggestion"]], tmp_path)
    mapped, _ = resolve(cells, None, tmp_path)
    ev = detect(mapped)
    got = {(r.company, r.month) for r in ev[ev.event == "reordered"].itertuples()}
    exp = {(co, MONTHS[j]) for co, c in COMPANIES.items() for i in c["reorder_months"] for j in (i, i + 1) if j < len(MONTHS)}
    assert got == exp  # every shuffled month AND the month it reverts is flagged, nothing else
    ren = ev[ev.event == "renamed"]
    assert len(ren) == 1 and ren.iloc[0].company == "pune_health" and ren.iloc[0].month == "2026-03"
    assert "churn_pct" in ren.iloc[0].detail
    assert (ev.event == "baseline").sum() == 5 and not ev.event.isin(["added", "removed"]).any()
