import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ingest.raw_cells import ingest_dir  # noqa: E402
from mapping.resolve import resolve  # noqa: E402
from normalize.normalize import load_corrections, load_fx, normalize  # noqa: E402
from pipeline import run  # noqa: E402


@pytest.fixture(scope="session")
def cells():
    return ingest_dir(ROOT / "data" / "raw")


@pytest.fixture(scope="session")
def mapped(cells):
    m, pending = resolve(cells, None)  # shipped, approved mappings
    assert pending == [], "shipped mappings should cover every label (run scripts/bootstrap_mappings.py)"
    return m


@pytest.fixture(scope="session")
def fx():
    return load_fx()


@pytest.fixture(scope="session")
def companies_cfg():
    return yaml.safe_load((ROOT / "config" / "companies.yaml").read_text())


@pytest.fixture(scope="session")
def facts_raw(mapped, fx, companies_cfg):
    return normalize(mapped, fx, companies_cfg, None)


@pytest.fixture(scope="session")
def facts_ok(mapped, fx, companies_cfg):
    return normalize(mapped, fx, companies_cfg, load_corrections(ROOT / "data" / "resubmissions.yaml"))


@pytest.fixture(scope="session")
def run_raw(tmp_path_factory):
    out = tmp_path_factory.mktemp("raw_run")
    return out, run(ROOT / "data" / "raw", out, None, llm="off")


@pytest.fixture(scope="session")
def run_ok(tmp_path_factory):
    out = tmp_path_factory.mktemp("ok_run")
    return out, run(ROOT / "data" / "raw", out, ROOT / "data" / "resubmissions.yaml", llm="off")


@pytest.fixture(scope="session")
def metrics_ok(run_ok):
    return json.loads((run_ok[0] / "metrics.json").read_text())
