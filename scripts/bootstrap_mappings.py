"""One-time setup: create the approved mappings shipped in config/mappings/.

Near-exact fuzzy matches are approved in bulk (source 'auto-confirmed'); the single ambiguous label
('Logo Churn') is approved manually (source 'human'). In real use a person runs mapping.confirm instead."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingest.raw_cells import ingest_dir  # noqa: E402
from mapping.confirm import apply  # noqa: E402
from mapping.resolve import resolve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
_, pending = resolve(ingest_dir(ROOT / "data" / "raw"), None)
decisions = []
for p in pending:
    if p["status"] == "auto":
        decisions.append(dict(company=p["company"], label=p["label"], kpi=p["suggestion"], source="auto-confirmed"))
    elif (p["company"], p["label"]) == ("pune_health", "Logo Churn"):
        decisions.append(dict(company=p["company"], label=p["label"], kpi="churn_pct", source="human"))
    else:
        print("needs a human:", p["company"], p["label"], p["options"])
print("approved", apply(decisions), "of", len(pending))
