"""Streamlit front end for the portfolio KPI pipeline. SYNTHETIC DATA."""
import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
RUNS = {"After analyst corrections": ROOT / "outputs" / "corrected_run", "Raw submissions (errors present)": ROOT / "outputs" / "raw_run"}
st.set_page_config(page_title="Portfolio KPI Reporting", layout="wide")


@st.cache_data(show_spinner="Running pipeline...")
def load(run_dir: str):
    d = Path(run_dir)
    if not (d / "manifest.json").exists():  # first start on a fresh deploy: build the outputs once
        from pipeline import run
        corr = ROOT / "data" / "resubmissions.yaml" if d.name == "corrected_run" else None
        run(ROOT / "data" / "raw", d, corr, llm="off")
    man = json.loads((d / "manifest.json").read_text())
    out = dict(man=man, metrics=[], dq=pd.DataFrame(), recon=pd.DataFrame(), drift=pd.DataFrame(), facts=pd.DataFrame(), fund=pd.DataFrame(),
               com=None, sources=pd.DataFrame())
    if (d / "pipeline.db").exists():
        with sqlite3.connect(d / "pipeline.db") as con:
            for k, t in [("dq", "dq_violations"), ("recon", "reconciliation"), ("drift", "schema_drift"), ("facts", "facts"), ("fund", "fund_rollup")]:
                out[k] = pd.read_sql(f"select * from {t}", con)
        out["metrics"] = json.loads((d / "metrics.json").read_text())
        out["sources"] = pd.read_csv(d / "sources.csv")
    if (d / "commentary.json").exists():
        out["com"] = json.loads((d / "commentary.json").read_text())
    return out


st.title("Portfolio KPI Reporting")
st.warning("SYNTHETIC DATA - five fictional portfolio companies. Nothing here is real financial information.")
scenario = st.sidebar.radio("Scenario", list(RUNS))
st.sidebar.caption("Raw submissions contain 5 planted errors. The pipeline must block the report. After analyst corrections it produces the final report.")
D = load(str(RUNS[scenario]))
man, status = D["man"], D["man"]["status"]

if status == "FINAL":
    st.success(f"FINAL - report for {man['month']} produced in {man['timings_s']['total']}s | {man['corrections']} corrections applied | {man['dq_warn']} warnings")
elif status == "BLOCKED_DQ":
    st.error(f"BLOCKED - {man['dq_fail']} open data-quality failures. No LP report is produced until they are fixed or corrected.")
else:
    st.error(f"NEEDS MAPPING - {man.get('pending_labels')} column labels need human confirmation.")

tabs = st.tabs(["Overview", "Companies", "Data quality", "Commentary and sources", "Pipeline"])
M = {m["id"]: m for m in D["metrics"]}

with tabs[0]:
    if status != "FINAL":
        st.info("Switch the scenario in the sidebar to see the corrected, final report. Exceptions are listed under Data quality.")
    else:
        mo = man["month"]
        cols = st.columns(4)
        for col, (k, label) in zip(cols * 2, [("revenue", "Revenue"), ("ebitda", "EBITDA"), ("cash", "Cash"), ("arr", "ARR"), ("headcount", "Headcount"),
                                              ("gross_margin_pct", "Gross margin"), ("ebitda_margin_pct", "EBITDA margin"), ("churn_pct", "Churn")]):
            m = M.get(f"fund.{k}.{mo}")
            col.metric(label, m["display"], M.get(f"fund.{k}.mom", {}).get("display"))
        f = D["fund"][D["fund"].complete.astype(bool)]
        c1, c2 = st.columns(2)
        c1.subheader("Fund revenue and EBITDA (USD)")
        c1.bar_chart(f[f.kpi == "revenue"].set_index("month").value)
        c1.line_chart(f[f.kpi == "ebitda"].set_index("month").value)
        c2.subheader(f"Revenue by company, {mo} (USD)")
        r = D["facts"][(D["facts"].month == mo) & (D["facts"].kpi == "revenue")].set_index("company").value
        c2.bar_chart(r)
        pdf = Path(RUNS[scenario]) / "lp_report.pdf"
        if pdf.exists():
            st.download_button("Download LP report (PDF)", pdf.read_bytes(), "lp_report.pdf", "application/pdf")

with tabs[1]:
    f = D["facts"]
    if f.empty:
        st.info("No facts yet: mappings need confirmation.")
    else:
        month = st.selectbox("Month", sorted(f.month.unique(), reverse=True))
        wide = f[f.month == month].pivot(index="company", columns="kpi", values="value")
        st.dataframe(wide, width="stretch")
        st.subheader("Trace a number to its source cell")
        c = st.columns(3)
        co = c[0].selectbox("Company", sorted(f.company.unique()))
        kp = c[1].selectbox("KPI", sorted(f[f.company == co].kpi.unique()))
        mo2 = c[2].selectbox("Month ", sorted(f.month.unique()), index=len(f.month.unique()) - 1)
        row = f[(f.company == co) & (f.kpi == kp) & (f.month == mo2)]
        st.dataframe(row[["source_file", "location", "raw_label", "raw_value", "currency", "unit", "fx_rate", "value", "corrected", "original_native", "correction_reason"]].astype(str).T,
                     width="stretch")

with tabs[2]:
    st.subheader("Data-quality exceptions")
    st.dataframe(D["dq"][["severity", "rule_id", "company", "month", "involved", "message", "source_file", "location"]] if len(D["dq"]) else D["dq"], width="stretch")
    st.subheader("Reconciliation")
    st.dataframe(D["recon"], width="stretch")
    st.subheader("Schema drift log")
    st.dataframe(D["drift"][D["drift"].event != "baseline"] if len(D["drift"]) else D["drift"], width="stretch")
    if len(D["facts"]) and D["facts"].corrected.astype(bool).any():
        st.subheader("Analyst corrections")
        st.dataframe(D["facts"][D["facts"].corrected.astype(bool)][["company", "month", "kpi", "original_native", "native_value", "correction_reason"]], width="stretch")

with tabs[3]:
    com = D["com"]
    if not com:
        st.info("No commentary: the report is blocked.")
    else:
        st.markdown(com["text"])
        n = len(com["check"]["verified"])
        st.caption(f"Written by {com['source']}. {n} figures matched to computed metrics; {len(com['check']['unmatched'])} unmatched. The LLM never does arithmetic.")
        st.dataframe(pd.DataFrame(com["check"]["verified"]), width="stretch")
        mid = st.selectbox("Metric", list(M))
        st.write(f"**{M[mid]['label']}** = {M[mid]['display']}  \n{M[mid]['formula']}")
        st.dataframe(D["sources"][D["sources"].metric_id == mid], width="stretch")

with tabs[4]:
    st.subheader("Stage timings (seconds)")
    st.bar_chart(pd.Series({k: v for k, v in man["timings_s"].items() if k != "total"}))
    st.json({k: v for k, v in man.items() if k != "timings_s"})
