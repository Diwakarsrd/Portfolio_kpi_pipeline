"""LP / board report as PDF. Every KPI row carries a source reference [S#] that resolves in the appendix
to the exact file and cell(s) behind the number."""
import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle  # noqa: E402

nice = lambda co: co.replace("_", " ").title()  # noqa: E731
SS = getSampleStyleSheet()
SMALL = ParagraphStyle("small", parent=SS["Normal"], fontSize=7, leading=9)
CELL = ParagraphStyle("cell", parent=SS["Normal"], fontSize=8, leading=10)


def _charts(fund, ck, month, tmp: Path):
    f = fund[fund.complete & fund.kpi.isin(["revenue", "ebitda"])].pivot(index="month", columns="kpi", values="value")
    fig, ax = plt.subplots(figsize=(6.2, 2.4))
    ax.bar(f.index, f["revenue"] / 1e6, color="#9fb7d6", label="Revenue")
    ax.plot(f.index, f["ebitda"] / 1e6, color="#1f3b63", marker="o", label="EBITDA")
    ax.set_ylabel("USD m"); ax.set_ylim(0, f["revenue"].max() / 1e6 * 1.3); ax.legend(frameon=False, fontsize=8, loc="upper left", ncol=2); ax.tick_params(labelsize=8)
    ax.spines[["top", "right"]].set_visible(False); fig.tight_layout()
    p1 = tmp / "trend.png"; fig.savefig(p1, dpi=160); plt.close(fig)
    c = ck[(ck.month == month) & (ck.kpi == "revenue")].sort_values("value")
    fig, ax = plt.subplots(figsize=(6.2, 2.2))
    ax.barh([nice(x) for x in c.company], c.value / 1e6, color="#1f3b63")
    ax.set_xlabel(f"Revenue {month}, USD m"); ax.tick_params(labelsize=8)
    ax.spines[["top", "right"]].set_visible(False); fig.tight_layout()
    p2 = tmp / "companies.png"; fig.savefig(p2, dpi=160); plt.close(fig)
    return p1, p2


def render(path: Path, M: list[dict], fund, ck, dq, drift, recon, facts, commentary: dict, month: str, status: str) -> list[dict]:
    by = {m["id"]: m for m in M}
    index, tag = [], {}

    def ref(mid):
        if mid not in by:
            return ""
        if mid not in tag:
            tag[mid] = f"S{len(tag) + 1}"
            index.append(by[mid])
        return tag[mid]

    story = [Paragraph(f"Portfolio KPI Report - {month}", SS["Title"]),
             Paragraph("<font color='#b00020'><b>SYNTHETIC DATA - for demonstration only. Companies, figures and files are fictional.</b></font>", SS["Normal"]),
             Paragraph(f"Status: <b>{status}</b> | reporting currency USD | FX fixed table | corrections applied: {by['n_corrections']['display']} | "
                       f"warnings: {by['dq_warn']['display']} | schema drift events: {by['n_drift_events']['display']}", SMALL), Spacer(1, 6 * mm)]
    rows = [["KPI (fund level)", month, "vs prior month", "Source"]]
    for k, label in [("revenue", "Revenue"), ("gross_margin_pct", "Gross margin"), ("ebitda", "EBITDA"), ("ebitda_margin_pct", "EBITDA margin"),
                     ("cash", "Cash"), ("headcount", "Headcount"), ("arr", "ARR"), ("churn_pct", "Churn (ARR-weighted)")]:
        m = by.get(f"fund.{k}.{month}")
        if m:
            rows.append([label, m["display"], by.get(f"fund.{k}.mom", {}).get("display", "-"), ref(m["id"])])
    t = Table(rows, colWidths=[55 * mm, 35 * mm, 40 * mm, 20 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b63")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                           ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6fa")])]))
    story += [t, Spacer(1, 5 * mm)]
    with tempfile.TemporaryDirectory() as td:
        p1, p2 = _charts(fund, ck, month, Path(td))
        story += [Image(str(p1), width=160 * mm, height=62 * mm), Image(str(p2), width=160 * mm, height=57 * mm)]
        story += [Spacer(1, 4 * mm), Paragraph("Portfolio companies", SS["Heading3"])]
        cos = sorted({m["id"].split(".")[1] for m in M if m["id"].startswith("co.")})
        rows = [["Company", "Revenue", "Share of fund", "Revenue vs prior", "EBITDA margin", "Source"]]
        for co in cos:
            g = lambda s: by.get(f"co.{co}.{s}", {}).get("display", "-")  # noqa: E731
            rows.append([nice(co), g(f"revenue.{month}"), g("revenue_share"), g("revenue_mom"), g("ebitda_margin"), ref(f"co.{co}.revenue.{month}")])
        t = Table(rows, colWidths=[38 * mm, 28 * mm, 28 * mm, 32 * mm, 30 * mm, 15 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b63")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey)]))
        story += [t, Spacer(1, 5 * mm), Paragraph("Commentary", SS["Heading3"])]
        for line in commentary["text"].splitlines():
            story.append(Paragraph(line.lstrip("- ").strip() and "&bull; " + line.lstrip("- ").strip(), CELL))
        n = len(commentary["check"]["verified"])
        story += [Paragraph(f"<i>Written by: {commentary['source']}. {n} figures in this text were each matched to a computed metric; "
                            f"unmatched figures: {len(commentary['check']['unmatched'])}. The LLM never calculates; all numbers come from pandas.</i>", SMALL), Spacer(1, 6 * mm)]
        story.append(Paragraph("Data quality, corrections and reconciliation", SS["Heading3"]))
        rows = [["Reconciliation check", "Result", "Items", "Max diff"]] + [[c.check.replace("_", " "), "PASS" if c.passed else "FAIL", str(c.n_checked), f"{c.max_abs_diff:.2g}"] for c in recon.itertuples()]
        t = Table(rows, colWidths=[85 * mm, 20 * mm, 20 * mm, 25 * mm]); t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey)]))
        story += [t, Spacer(1, 3 * mm)]
        corr = facts[facts.corrected]
        if len(corr):
            rows = [["Correction", "Original", "Corrected", "Reason"]] + [[Paragraph(f"{nice(r.company)} {r.month} {r.kpi}", CELL),
                    "blank" if r.original_native is None or r.original_native != r.original_native else f"{r.original_native:,.2f}", f"{r.native_value:,.2f}",
                    Paragraph(r.correction_reason, CELL)] for r in corr.itertuples()]
            t = Table(rows, colWidths=[55 * mm, 22 * mm, 22 * mm, 60 * mm]); t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey)]))
            story += [Paragraph("Analyst corrections (original value kept in the data)", CELL), t, Spacer(1, 3 * mm)]
        story.append(Paragraph(f"Schema drift log: {by['n_drift_events']['display']} events (column reorders / renames) detected across companies and handled by saved mappings.", CELL))
        story += [PageBreak(), Paragraph("Appendix - source index", SS["Heading3"]),
                  Paragraph("Each reference resolves to the raw file and cell(s). Full lineage for every metric: sources.csv.", SMALL), Spacer(1, 2 * mm)]
        rows = [["Ref", "Figure", "Source cells (file : location = raw label, raw value)"]]
        for m in index:
            cells = "<br/>".join(f"{Path(s['source_file']).parent.name}/{Path(s['source_file']).name} : {s['location']} = {s['raw_label']}, {s['raw_value']}" + (" [corrected]" if s["corrected"] else "")
                                 for s in m["sources"][:6]) + (f"<br/>... and {len(m['sources']) - 6} more" if len(m["sources"]) > 6 else "")
            rows.append([tag[m["id"]], Paragraph(f"{m['label']}<br/><b>{m['display']}</b>", SMALL), Paragraph(cells, SMALL)])
        t = Table(rows, colWidths=[12 * mm, 50 * mm, 108 * mm], repeatRows=1)
        t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("FONTSIZE", (0, 0), (-1, -1), 7), ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey)]))
        story.append(t)

        def footer(c, d):
            c.saveState(); c.setFont("Helvetica", 7); c.setFillColor(colors.grey)
            c.drawString(20 * mm, 10 * mm, "Synthetic data - demonstration only | numbers computed in pandas | commentary figures machine-verified"); c.drawRightString(190 * mm, 10 * mm, f"page {d.page}"); c.restoreState()
        SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=15 * mm, bottomMargin=18 * mm).build(story, onFirstPage=footer, onLaterPages=footer)
    return index
