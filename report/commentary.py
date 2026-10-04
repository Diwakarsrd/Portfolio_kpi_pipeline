"""Commentary: the LLM may only REPHRASE pre-computed figures. It never computes. Every number in the text is
parsed back out and must match a metric (to the precision it is written at); otherwise the text is rejected."""
import json
import os
import re
import urllib.request

# --- number checking ---------------------------------------------------------------------------------------
TOKEN = re.compile(r"(?<![\w.])([-+\u2212\u2013]?)(\$?)(\d[\d,]*(?:\.\d+)?)\s?(%|[KMB](?![A-Za-z])|million\b|billion\b|thousand\b)?")
SCALE = {"K": 1e3, "M": 1e6, "B": 1e9, "million": 1e6, "billion": 1e9, "thousand": 1e3}
YEAR = re.compile(r"(?<![\w.$])20\d{2}(?![\d.,%]|\s?[KMB%])")


def extract_figures(text: str) -> list[dict]:
    clean = YEAR.sub(" ", re.sub(r"\b20\d{2}-\d{2}\b", " ", text))  # periods like 2026-06 and bare years are not figures
    out = []
    for m in TOKEN.finditer(clean):
        sign, dollar, num, suf = m.groups()
        dec = len(num.split(".")[1]) if "." in num else 0
        scale = SCALE.get(suf, 1.0)
        kind = "pct" if suf == "%" else ("usd" if dollar or suf in SCALE else "count")
        out.append(dict(token=m.group(0).strip(), value=float(num.replace(",", "")) * scale, tol=0.5 * 10 ** -dec * scale, kind=kind))
    return out


def check_figures(text: str, metrics: list[dict]) -> dict:
    figs, unmatched = [], []
    for f in extract_figures(text):
        hit = next((m for m in metrics if m["kind"] == f["kind"] and abs(abs(m["value"]) - f["value"]) <= f["tol"] * 1.0001 + 1e-9), None)
        (figs if hit else unmatched).append(dict(token=f["token"], metric_id=hit["id"] if hit else None))
    return dict(ok=not unmatched, verified=figs, unmatched=[u["token"] for u in unmatched])


PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_.\-]+)\}")


def fill_placeholders(text: str, M: list[dict]) -> tuple[str, list[str]]:
    """The LLM writes {metric_id}; code substitutes the display string. Returns (filled_text, problems).
    Problems: unknown metric ids, and any literal figure typed outside a placeholder."""
    by, problems = {m["id"]: m for m in M}, []
    literal = extract_figures(PLACEHOLDER.sub(" ", text))
    problems += [f["token"] for f in literal]
    def sub(m):
        if m.group(1) not in by:
            problems.append("{" + m.group(1) + "}")
            return m.group(0)
        return by[m.group(1)]["display"]
    return PLACEHOLDER.sub(sub, text), problems


# --- generation --------------------------------------------------------------------------------------------
def template_commentary(M: list[dict]) -> str:
    d = {m["id"]: m for m in M}
    k = lambda s: next(m for m in M if m["id"].startswith(s))  # noqa: E731
    rev, ebitda, cash = k("fund.revenue.20"), k("fund.ebitda.20"), k("fund.cash.20")
    top = max((m for m in M if m["id"].endswith(".revenue_share")), key=lambda m: m["value"])
    lines = [f"Across {d['n_companies']['display']} portfolio companies, fund revenue for {rev['period']} was {rev['display']}, "
             f"{d['fund.revenue.mom']['display']} versus the prior month.",
             f"Fund EBITDA was {ebitda['display']}, a margin of {k('fund.ebitda_margin_pct.20')['display']}, and gross margin was {k('fund.gross_margin_pct.20')['display']}.",
             f"Cash stood at {cash['display']} ({d['fund.cash.mom']['display']} versus the prior month) and headcount at {k('fund.headcount.20')['display']}.",
             f"{d['n_rev_up']['display']} companies grew revenue month-on-month and {d['n_rev_down']['display']} declined; "
             f"{top['label'].replace(' share of fund revenue', '').replace('_', ' ').title()} was the largest contributor at {top['display']} of fund revenue."]
    if "fund.arr.mom" in d:
        lines.append(f"SaaS holdings reported ARR of {k('fund.arr.20')['display']} ({d['fund.arr.mom']['display']} month-on-month) with ARR-weighted churn of {k('fund.churn_pct.20')['display']}.")
    lines.append(f"Over the {d['n_months']['display']}-month window, revenue totalled {d['fund.revenue.window']['display']}.")
    return "\n".join(f"- {s}" for s in lines)


class GroqCommentary:
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, model: str | None = None):
        self.key, self.model = os.environ["GROQ_API_KEY"], model or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    def write(self, M: list[dict], feedback: str = "") -> str:
        facts = "\n".join(f"- {{{m['id']}}} = {m['label']} ({m['display']})" for m in M if not m["id"].startswith("dq_") and m["id"] != "n_months")
        prompt = ("Write 5-6 short bullet points of commentary for an LP board report.\n"
                  "RULES: every figure MUST be written as its placeholder in curly braces, exactly as listed, e.g. {fund.revenue.2026-06}. "
                  "NEVER type a digit yourself. Do not calculate or combine figures. Use the value in brackets only to choose wording "
                  "(up/down). No predictions. Plain bullets starting with '- '.\n\n" + facts
                  + (f"\n\nYour previous draft was rejected because of: {feedback}. Fix that." if feedback else ""))
        body = json.dumps({"model": self.model, "temperature": 0.2, "messages": [
            {"role": "system", "content": "You are a careful financial writer. You only restate provided figures."},
            {"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request(self.URL, body, {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)["choices"][0]["message"]["content"].strip()


def generate(M: list[dict], writer=None, retries: int = 2) -> dict:
    """Try the LLM up to retries+1 times; fall back to the deterministic template. Always returns checked text."""
    attempts, feedback = [], ""
    for _ in range(retries + 1 if writer else 0):
        try:
            text = writer.write(M, feedback)
        except Exception as e:  # network / auth / rate limit: fall back, never crash the pipeline
            attempts.append(dict(source="llm", ok=False, error=f"{type(e).__name__}: {e}"[:200]))
            break
        text, problems = fill_placeholders(text, M)
        if problems:
            attempts.append(dict(source="llm", ok=False, unmatched=problems))
            feedback = ", ".join(problems)
            continue
        res = check_figures(text, M)  # defence in depth: substituted text must still verify
        attempts.append(dict(source="llm", ok=res["ok"], unmatched=res["unmatched"]))
        if res["ok"]:
            return dict(text=text, source="llm", check=res, attempts=attempts)
        feedback = ", ".join(res["unmatched"])
    text = template_commentary(M)
    return dict(text=text, source="template", check=check_figures(text, M), attempts=attempts)
