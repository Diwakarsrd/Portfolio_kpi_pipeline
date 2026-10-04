# 2-minute demo video script (record with Loom / OBS)

| Time | On screen | Say |
|---|---|---|
| 0:00 | README top: architecture diagram + SYNTHETIC DATA line | "Five fictional portfolio companies send monthly reports in Excel, CSV and PDF, with different names, units, currencies and drifting columns." |
| 0:15 | Terminal: `python -m pipeline --llm off --out outputs/raw_run` -> BLOCKED, exit 3 | "Raw submissions contain five planted errors. The pipeline refuses to publish. Note the 20.3% churn it would otherwise have reported." |
| 0:35 | Streamlit, scenario = Raw -> Data quality tab | "Each exception points to the exact file and cell. A 10x typo, a broken subtotal, EBITDA above revenue, 45% churn, a blank cash cell." |
| 0:55 | Edit `config/dq_rules.yaml` (churn max 15 -> 60), rerun: churn exception disappears. Undo. | "Rules are YAML, so a finance person can change thresholds without touching code." |
| 1:10 | Scenario = After corrections -> Overview, then Companies -> trace a number | "After analyst corrections the run is FINAL in under a second. Any number traces to its source cell." |
| 1:30 | Commentary tab + PDF appendix | "The LLM writes placeholders, never numbers. Code fills them in, and every figure is re-verified against the data." |
| 1:45 | Results table in README + `python roi.py` | "Mapping, drift, DQ and reconciliation are all measured against ground truth. Manual cycle N minutes, pipeline M minutes." |
| 1:55 | Live URL | "Synthetic data, honest limits listed in the README." |
