import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data_gen.generate import COMPANIES, MONTHS, MULT, PLANTED  # noqa: E402
from ingest.raw_cells import ingest_dir  # noqa: E402

FX = yaml.safe_load((ROOT / "config" / "fx.yaml").read_text())["rates_to_usd"]


@pytest.fixture(scope="module")
def cells():
    return ingest_dir(ROOT / "data" / "raw")


def test_all_files_ingested(cells):
    assert cells.source_file.nunique() == 30


def test_every_file_declares_currency_and_unit(cells):
    assert cells.currency.notna().all() and cells.unit.notna().all()
    per_co = cells.groupby("company")[["currency", "unit"]].nunique()
    assert (per_co == 1).all().all()  # one currency/unit per company


def test_column_order_actually_drifts(cells):
    orders = (cells.sort_values("column_index").groupby(["company", "source_file"])
              .raw_label.apply(tuple).reset_index())
    for co in COMPANIES:
        n_orders = orders[orders.company == co].raw_label.nunique()
        assert (n_orders > 1) == bool(COMPANIES[co]["reorder_months"] or COMPANIES[co].get("drift_label"))


def test_revenue_matches_ground_truth_except_planted(cells):
    truth = pd.read_csv(ROOT / "data" / "truth.csv")
    planted = {(c, MONTHS[i], k) for c, i, k, *_ in PLANTED}
    checked = 0
    for co, cfg in COMPANIES.items():
        label = cfg["labels"]["revenue"]
        for month in MONTHS:
            row = cells[(cells.company == co) & (cells.source_file.str.contains(month))
                        & (cells.raw_label == label)]
            assert len(row) == 1, (co, month)
            usd = row.raw_value.iloc[0] * MULT[cfg["unit"]] * FX[cfg["cur"]]
            t = truth[(truth.company == co) & (truth.month == month) & (truth.kpi == "revenue")].usd_value.iloc[0]
            if (co, month, "revenue") in planted:
                assert usd > 5 * t  # the 10x typo survived ingest, as it should
            else:
                assert usd == pytest.approx(t, rel=0.005), (co, month)
                checked += 1
    assert checked == 29


def test_provenance_present(cells):
    assert cells.location.str.len().gt(0).all()
    assert set(cells.location.str.extract(r"^(csv|p1|Report)")[0]) == {"csv", "p1", "Report"}
