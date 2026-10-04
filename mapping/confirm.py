"""Human confirmation. `--accept-auto` bulk-approves near-exact fuzzy matches (first-run convenience);
everything else is asked one by one. Approved labels are saved and never asked again."""
import argparse
from pathlib import Path

from mapping import store
from schema import KPI

VALID = {k.value for k in KPI}


def apply(decisions: list[dict], map_dir: Path = store.MAP_DIR) -> int:
    """decisions: {company, label, kpi (id or None=ignore), source}. Rejects ids outside the schema."""
    for d in decisions:
        if d["kpi"] is not None and d["kpi"] not in VALID:
            raise ValueError(f"{d['kpi']!r} is not a canonical KPI")
        store.approve(d["company"], d["label"], d["kpi"], d["source"], map_dir)
    return len(decisions)


def interactive(items: list[dict], map_dir: Path = store.MAP_DIR) -> int:
    done = []
    for it in items:
        print(f"\n[{it['company']}] {it['label']!r}  suggestion={it['suggestion']} ({it['suggestion_source']}, "
              f"score {it['score']})  options={it['options']}" + (f"\n  LLM: {it['llm_reason']}" if it["llm_reason"] else ""))
        ans = input("  kpi id / Enter=accept suggestion / n=ignore column / s=skip: ").strip().lower()
        if ans == "s":
            continue
        kpi = it["suggestion"] if ans == "" else (None if ans == "n" else ans)
        done.append(dict(company=it["company"], label=it["label"], kpi=kpi, source="human"))
    return apply(done, map_dir)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--accept-auto", action="store_true")
    a = ap.parse_args()
    pend = store.load_pending()
    auto = [p for p in pend if p["status"] == "auto"]
    if a.accept_auto:
        apply([dict(company=p["company"], label=p["label"], kpi=p["suggestion"], source="auto-confirmed")
               for p in auto], store.MAP_DIR)
        print(f"approved {len(auto)} near-exact matches")
    rest = [p for p in pend if p["status"] != "auto"]
    if rest:
        interactive(rest)
