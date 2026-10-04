"""Orchestrate: saved mapping -> fuzzy -> LLM suggestion -> human queue. Fails closed: a label with no
human-approved mapping stays unmapped and is listed as pending; nothing downstream may treat it as a KPI."""
from pathlib import Path

import pandas as pd

from mapping import store
from mapping.llm import Resolver
from mapping.matcher import load_synonyms, match


def resolve(cells: pd.DataFrame, resolver: Resolver | None = None, map_dir: Path = store.MAP_DIR,
            synonyms: dict | None = None) -> tuple[pd.DataFrame, list[dict]]:
    synonyms = synonyms or load_synonyms()
    out, pending = cells.copy(), []
    out["kpi"], out["map_status"] = None, "pending"
    for company, grp in cells.groupby("company"):
        saved = store.load(company, map_dir)
        for label in grp.raw_label.unique():
            idx = out.index[(out.company == company) & (out.raw_label == label)]
            if label in saved:
                out.loc[idx, ["kpi", "map_status"]] = [saved[label]["kpi"], "saved"]
                continue
            first_file = grp[grp.raw_label == label].source_file.iloc[0]
            siblings = grp[grp.source_file == first_file].raw_label.tolist()
            cand = match(label, synonyms)
            if cand.status == "reserved":  # structural column (Period): never a KPI, never prompts
                out.loc[idx, ["kpi", "map_status"]] = [None, "reserved"]
                continue
            item = dict(company=company, label=label, status=cand.status, suggestion=cand.kpi,
                        score=round(cand.score, 1), options=[o[0] for o in cand.options],
                        llm_reason=None, suggestion_source="fuzzy")
            if cand.status in ("ambiguous", "unmapped") and resolver is not None:
                ans = resolver.resolve(label, siblings, item["options"] or [])
                if ans is not None:  # invalid / failed answers fall through to the human untouched
                    item.update(suggestion=None if ans[0] == "none" else ans[0],
                                llm_reason=ans[1], suggestion_source="llm")
            pending.append(item)
    store.save_pending(pending) if map_dir == store.MAP_DIR else None
    return out, pending
