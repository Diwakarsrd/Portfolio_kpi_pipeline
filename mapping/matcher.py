"""Deterministic first pass: rapidfuzz against a synonym vocabulary.

Guards against the classic fuzzy-match failures:
  * a label marked with % can only map to percentage KPIs (Gross Margin % vs Gross Profit)
  * auto-accept needs a clear gap to the best *different* KPI, not just a high score
"""
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

from schema import KPI

ROOT = Path(__file__).resolve().parents[1]
PCT_KPIS = {KPI.GROSS_MARGIN.value, KPI.CHURN.value}
AUTO_SCORE, AUTO_GAP, REVIEW_FLOOR = 95.0, 10.0, 40.0  # WRatio caps substring hits at 90, so 95 = near-exact only
RESERVED = {"period": "reserved"}  # structural columns, not KPIs


def load_synonyms(path: Path = ROOT / "config" / "synonyms.yaml") -> dict[str, list[str]]:
    return yaml.safe_load(path.read_text())


def normalize(label: str) -> str:
    s = label.lower().replace("&", "and")
    s = re.sub(r"[%()]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_pct(label: str) -> bool:
    return bool(re.search(r"%|\bpct\b|percent", label.lower()))


@dataclass
class Candidate:
    kpi: str | None
    score: float
    gap: float                 # lead over the best candidate of a different KPI
    status: str                # auto | ambiguous | unmapped | reserved
    options: list[tuple[str, float]]  # top distinct KPIs with scores (for LLM / human)


def match(label: str, synonyms: dict[str, list[str]]) -> Candidate:
    norm = normalize(label)
    if norm in RESERVED:
        return Candidate(None, 100.0, 100.0, "reserved", [])
    # One-directional guard: an explicit % restricts to percentage KPIs; an unmarked label may be either.
    pairs = [(normalize(s), k) for k, syns in synonyms.items() for s in syns
             if not is_pct(label) or k in PCT_KPIS]
    scored = process.extract(norm, [p[0] for p in pairs], scorer=fuzz.WRatio, limit=len(pairs))
    best: dict[str, float] = {}
    for _, score, idx in scored:
        k = pairs[idx][1]
        best[k] = max(best.get(k, 0.0), score)
    ranked = sorted(best.items(), key=lambda kv: -kv[1])
    if not ranked:
        return Candidate(None, 0.0, 0.0, "unmapped", [])
    (k1, s1), s2 = ranked[0], (ranked[1][1] if len(ranked) > 1 else 0.0)
    if s1 >= AUTO_SCORE and s1 - s2 >= AUTO_GAP:
        status = "auto"
    elif s1 >= REVIEW_FLOOR:
        status = "ambiguous"
    else:
        status = "unmapped"
    return Candidate(k1 if status != "unmapped" else None, s1, s1 - s2, status, ranked[:3])
