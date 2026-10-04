"""End-to-end pipeline with per-stage timing and a fail-closed gate.

status:  FINAL           report produced
         BLOCKED_DQ      open data-quality failures (or a failed reconciliation): no LP report, exceptions listed
         NEEDS_MAPPING   unapproved column labels: a human must confirm them first
"""
import argparse
import json
import os
import sqlite3
import time
from pathlib import Path

import pandas as pd
import yaml

from drift.detect import detect
from ingest.raw_cells import ingest_dir
from mapping import store
from mapping.resolve import resolve
from normalize.normalize import load_corrections, load_fx, normalize
from quality.rules import load_rules, run_rules
from reconcile.checks import reconcile
from reconcile.rollup import company_kpis, fund_rollup
from report import commentary as C
from report.metrics import build_metrics
from report.pdf import render

ROOT = Path(__file__).resolve().parent


class _SafeResolver:
    """Wrap the LLM so a network or auth error never breaks the run: the label just goes to the human."""
    def __init__(self, inner): self.inner = inner
    def resolve(self, *a):
        try:
            return self.inner.resolve(*a)
        except Exception:
            return None


def run(raw_dir: Path, out_dir: Path, corrections: Path | None = None, llm: str = "auto", map_dir: Path = store.MAP_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    T, t0 = {}, time.perf_counter()

    def stage(name, fn):
        s = time.perf_counter(); r = fn(); T[name] = round(time.perf_counter() - s, 3); return r

    use_llm = llm != "off" and bool(os.environ.get("GROQ_API_KEY"))
    manifest = dict(status=None, llm_enabled=use_llm, timings_s=T)

    def finish(status, **kw):
        manifest.update(status=status, **kw)
        T["total"] = round(time.perf_counter() - t0, 3)
        (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
        return manifest

    cells = stage("ingest", lambda: ingest_dir(raw_dir))
    resolver = None
    if use_llm:
        from mapping.llm import GroqResolver
        resolver = _SafeResolver(GroqResolver())
    mapped, pending = stage("mapping", lambda: resolve(cells, resolver, map_dir))
    if pending:
        pd.DataFrame(pending).to_csv(out_dir / "pending_mappings.csv", index=False)
        return finish("NEEDS_MAPPING", pending_labels=len(pending), files=int(cells.source_file.nunique()))
    fx, companies = load_fx(), yaml.safe_load((ROOT / "config" / "companies.yaml").read_text())
    facts = stage("normalize", lambda: normalize(mapped, fx, companies, load_corrections(corrections)))
    drift = stage("drift", lambda: detect(mapped))
    dq = stage("quality", lambda: run_rules(facts, load_rules()))
    ck = company_kpis(facts); fund = fund_rollup(ck)
    recon = stage("reconcile", lambda: reconcile(facts, cells, ck, fund, fx))
    months = sorted(facts.month.unique()); month, prev = months[-1], months[-2]
    M = stage("metrics", lambda: build_metrics(facts, ck, fund, dq, drift, month, prev, len(months)))
    n_fail, recon_ok = int((dq.severity == "fail").sum()), bool(recon.passed.all())
    status = "FINAL" if n_fail == 0 and recon_ok else "BLOCKED_DQ"

    with sqlite3.connect(out_dir / "pipeline.db") as con:
        for name, df in [("raw_cells", cells), ("facts", facts), ("schema_drift", drift), ("dq_violations", dq), ("reconciliation", recon),
                         ("fund_rollup", fund.drop(columns=["contributors"]))]:
            df.to_sql(name, con, if_exists="replace", index=False)
    (out_dir / "metrics.json").write_text(json.dumps(M, indent=2, default=str))
    pd.DataFrame([dict(metric_id=m["id"], display=m["display"], **s) for m in M for s in m["sources"]]).to_csv(out_dir / "sources.csv", index=False)
    dq.to_csv(out_dir / "dq_exceptions.csv", index=False)
    info = dict(month=month, prev=prev, n_files=int(cells.source_file.nunique()), n_cells=len(cells), n_facts=len(facts), dq_fail=n_fail,
                dq_warn=int((dq.severity == "warn").sum()), corrections=int(facts.corrected.sum()), drift_events=int((drift.event != "baseline").sum()),
                reconciliation_passed=recon_ok)
    if status == "BLOCKED_DQ":
        return finish(status, **info)
    writer = C.GroqCommentary() if use_llm else None
    com = stage("commentary", lambda: C.generate(M, writer))
    (out_dir / "commentary.json").write_text(json.dumps(com, indent=2))
    stage("pdf", lambda: render(out_dir / "lp_report.pdf", M, fund, ck, dq, drift, recon, facts, com, month, "FINAL"))
    return finish(status, commentary_source=com["source"], figures_verified=len(com["check"]["verified"]), **info)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", type=Path, default=ROOT / "data" / "raw")
    ap.add_argument("--out", type=Path, default=ROOT / "outputs" / "corrected_run")
    ap.add_argument("--corrections", type=Path, default=None)
    ap.add_argument("--llm", choices=["auto", "off"], default="auto")
    a = ap.parse_args()
    m = run(a.raw, a.out, a.corrections, a.llm)
    print(json.dumps({k: v for k, v in m.items() if k != "timings_s"}, indent=2), "\ntimings:", m["timings_s"])
    raise SystemExit({"FINAL": 0, "BLOCKED_DQ": 3, "NEEDS_MAPPING": 2}[m["status"]])
