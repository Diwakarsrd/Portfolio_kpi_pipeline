"""Saved, human-approved mappings (one JSON per company, per label) and the pending-review queue.
Approved files live in config/mappings/ so they can be committed and reviewed like code."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_DIR = ROOT / "config" / "mappings"
PENDING = ROOT / "data" / "pending_mappings.json"


def load(company: str, map_dir: Path = MAP_DIR) -> dict[str, dict]:
    p = map_dir / f"{company}.json"
    return json.loads(p.read_text())["labels"] if p.exists() else {}


def approve(company: str, label: str, kpi: str | None, source: str, map_dir: Path = MAP_DIR) -> None:
    """kpi=None records 'ignore this column' so it never prompts again."""
    map_dir.mkdir(parents=True, exist_ok=True)
    labels = load(company, map_dir)
    labels[label] = {"kpi": kpi, "source": source,
                     "confirmed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (map_dir / f"{company}.json").write_text(
        json.dumps({"company": company, "labels": dict(sorted(labels.items()))}, indent=2))


def save_pending(items: list[dict], path: Path = PENDING) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2))


def load_pending(path: Path = PENDING) -> list[dict]:
    return json.loads(path.read_text()) if path.exists() else []
