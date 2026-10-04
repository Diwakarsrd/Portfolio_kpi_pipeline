"""Schema drift per company per month: added / removed / renamed / reordered columns vs the prior month.
A 'rename' = a label disappeared and a new one appeared that maps to the SAME canonical KPI."""
import sqlite3
from pathlib import Path

import pandas as pd


def detect(mapped: pd.DataFrame) -> pd.DataFrame:
    events = []
    d = mapped.assign(month=mapped.source_file.map(lambda p: Path(p).stem))
    for company, grp in d.groupby("company"):
        prev_order, prev_kpi = None, {}
        for month, g in sorted(grp.groupby("month")):
            order = g.sort_values("column_index").raw_label.tolist()
            kpi = dict(zip(g.raw_label, g.kpi))
            if prev_order is None:
                events.append((company, month, "baseline", f"{len(order)} columns"))
            else:
                added, removed = set(order) - set(prev_order), set(prev_order) - set(order)
                for r in sorted(removed):
                    twin = next((a for a in sorted(added) if kpi.get(a) and kpi[a] == prev_kpi.get(r)), None)
                    if twin:
                        events.append((company, month, "renamed", f"{r!r} -> {twin!r} (both = {kpi[twin]})"))
                        added.discard(twin)
                    else:
                        events.append((company, month, "removed", repr(r)))
                events += [(company, month, "added", repr(a)) for a in sorted(added)]
                common_prev = [x for x in prev_order if x in order]
                common_now = [x for x in order if x in prev_order]
                if common_prev != common_now:
                    events.append((company, month, "reordered", f"{prev_order} -> {order}"))
            prev_order, prev_kpi = order, kpi
    return pd.DataFrame(events, columns=["company", "month", "event", "detail"])


def save(df: pd.DataFrame, db_path: Path) -> None:
    with sqlite3.connect(db_path) as con:
        df.to_sql("schema_drift", con, if_exists="replace", index=False)
