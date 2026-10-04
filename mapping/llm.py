"""LLM fallback for ambiguous labels. The model can only choose from a fixed list; its answer is
validated, and it is only ever a *suggestion* that a human confirms. It never writes the mapping."""
import json
import os
import urllib.request
from typing import Protocol

from schema import KPI

KPI_HELP = {
    "revenue": "total sales / turnover for the month", "cogs": "direct cost of goods or services sold",
    "gross_profit": "revenue minus COGS, an amount", "gross_margin_pct": "gross profit as a percentage of revenue",
    "ebitda": "earnings before interest, tax, depreciation, amortisation (operating profit before D&A)",
    "cash": "closing cash and bank balance", "headcount": "number of employees at period end",
    "arr": "annual recurring revenue (SaaS)", "churn_pct": "customer/logo churn rate, percentage",
}
VALID = {k.value for k in KPI} | {"none"}


class Resolver(Protocol):
    def resolve(self, label: str, siblings: list[str], options: list[str]) -> tuple[str, str] | None: ...


def parse_answer(text: str) -> tuple[str, str] | None:
    """Return (kpi_or_none, reason) only if the answer is valid JSON with an allowed kpi id."""
    try:
        d = json.loads(text)
        kpi = str(d["kpi"]).strip().lower()
        return (kpi, str(d.get("reason", ""))[:200]) if kpi in VALID else None
    except (ValueError, KeyError, TypeError):
        return None


class GroqResolver:
    """OpenAI-compatible chat call to Groq. Needs GROQ_API_KEY. Temperature 0, JSON mode."""
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, model: str | None = None):
        self.key = os.environ["GROQ_API_KEY"]
        self.model = model or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    def resolve(self, label, siblings, options):
        prompt = (f"Column header: {label!r}\nOther headers in the same report: {siblings}\n"
                  f"Most likely candidates: {options}\n\nCanonical KPIs:\n"
                  + "\n".join(f"- {k}: {v}" for k, v in KPI_HELP.items())
                  + "\n\nReply with JSON {\"kpi\": <id or \"none\">, \"reason\": <one sentence>}. "
                    "Use \"none\" if the header is not one of these KPIs (e.g. net income, capex, opex).")
        body = json.dumps({"model": self.model, "temperature": 0, "response_format": {"type": "json_object"},
                           "messages": [{"role": "system", "content": "You map financial report headers to a fixed KPI list."},
                                        {"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(self.URL, body, {"Authorization": f"Bearer {self.key}",
                                                      "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return parse_answer(json.load(r)["choices"][0]["message"]["content"])
