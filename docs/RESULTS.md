| Stage | Result | Notes |
|---|---|---|
| Ingest | 30 files (CSV / Excel with merged cells / PDF) -> 222 raw cells, each with file + cell location | all parsed; revenue cell matches ground truth for 29/30 (the 30th is the planted 10x typo) |
| Column mapping (shipped labels) | 33/33 labels mapped to the right KPI | 32 near-exact matches bulk-confirmed, 1 label approved by hand |
| Column mapping (held-out labels) | 23 unseen labels incl. 6 non-KPIs: 0 wrong auto-accepts, true KPI in top-3 for 17/17 | only 1/23 auto-accepted - fuzzy handles near-exact labels, the rest need LLM + human |
| Schema drift | 13/13 injected reorders detected, 0 false alarms, 1/1 rename detected | revert months are flagged too, by design |
| Normalization | 0/192 facts deviate from ground truth after corrections | before corrections 5 deviate: exactly the planted cells; tolerance = half the last digit each company reported |
| Data-quality rules | 5/5 planted errors caught at 'fail' severity; 0 stray company-months flagged | 7 violations in total; 0 after corrections |
| Reconciliation | 6/6 checks pass over 435 items | fund = sum of companies, every fact re-derived from its raw cell, no partial sums |
| Gate | raw submissions -> BLOCKED_DQ; after corrections -> FINAL | without the gate, fund churn would have shown 20.3%; correct value is 1.7% |
| LLM commentary check | 17 figures verified, 0 unmatched; correct figures accepted 40/40 | post-filter alone wrongly accepted 20/160 perturbed figures; in placeholder mode literal numbers typed by the LLM are rejected 80/80 |
| Pipeline runtime | 2.923s mean end-to-end over 5 runs (max 3.07s), 30 files | ingest 0.59s, reconcile 0.191s, pdf 0.921s |

Known limitation measured: the checker verifies that a figure exists in the data, not that it is attached to the right label. Swapping real fund-level dollar figures between labels was wrongly accepted in 70/70 cases. That is why the LLM writes metric placeholders instead of numbers: it can still pick the wrong metric id, but it can no longer invent, round or mistype a figure.

Manual baseline (Excel) and the speed-up are NOT measured here. See docs/MANUAL_BASELINE.md.
