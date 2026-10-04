import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pdfplumber
import pytest

from pipeline import run

ROOT = Path(__file__).resolve().parents[1]
COUNT_IDS = ("n_", "dq_")


def test_raw_submissions_are_blocked_and_no_report_is_produced(run_raw):
    out, man = run_raw
    assert man["status"] == "BLOCKED_DQ" and man["dq_fail"] == 5 and man["reconciliation_passed"]
    assert not (out / "lp_report.pdf").exists() and not (out / "commentary.json").exists()
    exc = pd.read_csv(out / "dq_exceptions.csv")
    assert set(exc[exc.severity == "fail"].company) == {"gulf_logistics", "nimbus_cloud", "bharat_foods", "pune_health", "desert_solar"}


def test_corrected_run_produces_a_verified_report(run_ok):
    out, man = run_ok
    assert man["status"] == "FINAL" and man["dq_fail"] == 0 and man["corrections"] == 5 and man["commentary_source"] == "template"
    assert man["figures_verified"] >= 15 and man["timings_s"]["total"] < 10
    with pdfplumber.open(out / "lp_report.pdf") as pdf:
        text = "\n".join(p.extract_text() for p in pdf.pages)
    assert len(pdf.pages) >= 3 and "SYNTHETIC DATA" in text and "source index" in text and "[corrected]" in text


def test_unapproved_labels_stop_the_run(tmp_path):
    man = run(ROOT / "data" / "raw", tmp_path / "o", None, "off", map_dir=tmp_path / "empty_maps")
    assert man["status"] == "NEEDS_MAPPING" and man["pending_labels"] == 33
    assert len(pd.read_csv(tmp_path / "o" / "pending_mappings.csv")) == 33 and not (tmp_path / "o" / "pipeline.db").exists()


def test_every_number_links_to_a_real_source_cell(run_ok, metrics_ok):
    out, _ = run_ok
    for m in metrics_ok:
        if not m["id"].startswith(COUNT_IDS):
            assert m["sources"], f"{m['id']} has no source cells"
    src = pd.read_csv(out / "sources.csv")
    with sqlite3.connect(out / "pipeline.db") as con:
        raw = pd.read_sql("select source_file, location from raw_cells", con)
    merged = src.merge(raw, on=["source_file", "location"], how="left", indicator=True)
    assert (merged._merge == "both").all() and len(src) > 100


def test_fund_revenue_matches_independent_ground_truth_sum(metrics_ok, facts_ok):
    truth = pd.read_csv(ROOT / "data" / "truth.csv")
    exp = truth[(truth.month == "2026-06") & (truth.kpi == "revenue")].usd_value.sum()
    tol = sum(0.005 * r.multiplier * r.fx_rate * 1.001 for r in facts_ok[(facts_ok.month == "2026-06") & (facts_ok.kpi == "revenue")].itertuples())
    got = next(m for m in metrics_ok if m["id"] == "fund.revenue.2026-06")["value"]
    assert abs(got - exp) <= tol


def test_pipeline_is_deterministic(tmp_path):
    vals = []
    for i in range(2):
        run(ROOT / "data" / "raw", tmp_path / str(i), ROOT / "data" / "resubmissions.yaml", "off")
        vals.append([(m["id"], m["value"], m["display"]) for m in json.loads((tmp_path / str(i) / "metrics.json").read_text())])
    assert vals[0] == vals[1]


def test_cli_exit_codes(tmp_path):
    def cli(*args):
        return subprocess.run([sys.executable, "-m", "pipeline", "--llm", "off", "--out", str(tmp_path / "x"), *args], cwd=ROOT, capture_output=True, text=True).returncode
    assert cli() == 3
    assert cli("--corrections", "data/resubmissions.yaml") == 0
