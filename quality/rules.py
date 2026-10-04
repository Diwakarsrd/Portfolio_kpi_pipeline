"""YAML-defined data-quality rules, validated on load and evaluated with pandas.

Each violation records WHICH cell caused it (source file + location) so it can be traced and fixed.
Multi-KPI rules list every KPI involved, since a failed tie only proves that one of them is wrong.
"""
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from schema import KPI

ROOT = Path(__file__).resolve().parents[1]
KPI_IDS = {k.value for k in KPI}


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["not_null", "range", "ratio_range", "lte", "sum_ties", "mom_change", "period_match"]
    severity: Literal["fail", "warn"]
    message: str
    kpis: list[str] | None = None
    kpi: str | None = None
    min: float | None = None
    max: float | None = None
    left: str | None = None
    right: str | None = None
    numerator: str | None = None
    denominator: str | None = None
    a: str | None = None
    minus: str | None = None
    equals: str | None = None
    tolerance_pct: float = 0.0
    max_abs_pct: float | None = None

    @field_validator("kpis", "kpi", "left", "right", "numerator", "denominator", "a", "minus", "equals", mode="before")
    @classmethod
    def _known_kpis(cls, v):
        for k in (v if isinstance(v, list) else [v]):
            if k is not None and k not in KPI_IDS:
                raise ValueError(f"unknown KPI {k!r}. Valid: {', '.join(sorted(KPI_IDS))}")
        return v

    @model_validator(mode="after")
    def _required_fields(self):
        need = {"not_null": ["kpis"], "range": ["kpi"], "ratio_range": ["numerator", "denominator"],
                "lte": ["left", "right"], "sum_ties": ["a", "minus", "equals"],
                "mom_change": ["kpis", "max_abs_pct"], "period_match": []}[self.type]
        if miss := [f for f in need if getattr(self, f) is None]:
            raise ValueError(f"rule type '{self.type}' needs: {', '.join(miss)}")
        if self.type == "range" and self.min is None and self.max is None:
            raise ValueError("rule type 'range' needs min and/or max")
        return self


def load_rules(path: Path = ROOT / "config" / "dq_rules.yaml") -> list[Rule]:
    raw = yaml.safe_load(Path(path).read_text())
    rules, errors = [], []
    for i, r in enumerate(raw.get("rules", []), 1):
        try:
            rules.append(Rule(**r))
        except ValidationError as e:
            msgs = "; ".join(f"{'.'.join(map(str, x['loc'])) or 'rule'}: {x['msg']}" for x in e.errors())
            errors.append(f"rule #{i} ({r.get('id', '?')}): {msgs}")
    if errors:
        raise ValueError("dq_rules.yaml has problems:\n  " + "\n  ".join(errors))
    if len({r.id for r in rules}) != len(rules):
        raise ValueError("dq_rules.yaml: duplicate rule ids")
    return rules


def _v(rule, company, month, kpi, value, detail, involved, row=None):
    fmt = _SafeDict(company=company, month=month, kpi=kpi, value=value if value is not None else float("nan"), detail=detail)
    try:
        msg = rule.message.format_map(fmt)
    except (ValueError, TypeError):
        msg = rule.message
    return dict(rule_id=rule.id, severity=rule.severity, company=company, month=month, kpi=kpi, involved=",".join(involved),
                message=msg, value=value, source_file=None if row is None else row.source_file,
                location=None if row is None else row.location)


def _get(facts):
    return {(r.company, r.month, r.kpi): r for r in facts.itertuples()}


def run_rules(facts: pd.DataFrame, rules: list[Rule]) -> pd.DataFrame:
    idx, out = _get(facts), []
    months = sorted(facts.month.unique())
    present = lambda r: r is not None and pd.notna(r.value)  # noqa: E731
    for rule in rules:
        t = rule.type
        if t == "not_null":
            for co, g in facts.groupby("company"):
                for k in [k for k in rule.kpis if k in set(g.kpi)]:
                    for m in sorted(g.month.unique()):
                        r = idx.get((co, m, k))
                        if not present(r):
                            out.append(_v(rule, co, m, k, None, "", [k], r))
        elif t == "range":
            for r in facts[facts.kpi == rule.kpi].itertuples():
                if pd.notna(r.value) and ((rule.min is not None and r.value < rule.min) or (rule.max is not None and r.value > rule.max)):
                    out.append(_v(rule, r.company, r.month, r.kpi, r.value, "", [r.kpi], r))
        elif t == "ratio_range":
            for (co, m, k), n in idx.items():
                d = idx.get((co, m, rule.denominator))
                if k == rule.numerator and present(n) and present(d) and d.value > 0:
                    ratio = n.value / d.value
                    if (rule.min is not None and ratio < rule.min) or (rule.max is not None and ratio > rule.max):
                        out.append(_v(rule, co, m, k, ratio, "", [rule.numerator, rule.denominator], n))
        elif t == "lte":
            for (co, m, k), a in idx.items():
                b = idx.get((co, m, rule.right))
                if k == rule.left and present(a) and present(b) and a.value > b.value * (1 + rule.tolerance_pct / 100):
                    out.append(_v(rule, co, m, k, a.value, f"{a.value:,.0f} vs {b.value:,.0f}", [rule.left, rule.right], a))
        elif t == "sum_ties":
            for (co, m, k), a in idx.items():
                b, c = idx.get((co, m, rule.minus)), idx.get((co, m, rule.equals))
                if k == rule.a and present(a) and present(b) and present(c):
                    gap = a.value - b.value - c.value
                    if abs(gap) > abs(a.value) * rule.tolerance_pct / 100:
                        out.append(_v(rule, co, m, rule.equals, c.value, f"off by {gap:,.0f} USD ({gap / a.value:+.1%} of {rule.a})",
                                      [rule.a, rule.minus, rule.equals], c))
        elif t == "mom_change":
            for co in facts.company.unique():
                for k in rule.kpis:
                    ser = [(m, idx.get((co, m, k))) for m in months if present(idx.get((co, m, k)))]
                    flagged = {}
                    for (m0, r0), (m1, r1) in zip(ser, ser[1:]):
                        if r0.value:
                            pct = (r1.value / r0.value - 1) * 100
                            if abs(pct) > rule.max_abs_pct:
                                flagged[m1] = pct
                    # a one-month spike that snaps back makes the NEXT month look wrong too; blame only the spike
                    order = [m for m, _ in ser]
                    for m in list(flagged):
                        i = order.index(m)
                        if i + 1 < len(order) and order[i + 1] in flagged and i >= 1:
                            before, after = ser[i - 1][1].value, ser[i + 1][1].value
                            if before and abs(after / before - 1) * 100 <= rule.max_abs_pct / 2:
                                del flagged[order[i + 1]]
                    for m, pct in flagged.items():
                        out.append(_v(rule, co, m, k, pct, "", [k], idx[(co, m, k)]))
        elif t == "period_match":
            seen = set()
            for r in facts.itertuples():
                if r.month != r.file_month and (r.company, r.source_file) not in seen:
                    seen.add((r.company, r.source_file))
                    out.append(_v(rule, r.company, r.file_month, r.kpi, None, f"{r.month} vs file {r.file_month}", [r.kpi], r))
    cols = ["rule_id", "severity", "company", "month", "kpi", "involved", "message", "value", "source_file", "location"]
    return pd.DataFrame(out, columns=cols)
