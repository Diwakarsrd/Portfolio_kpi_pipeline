import pytest

from report.commentary import check_figures, extract_figures, generate, template_commentary


def test_template_text_passes_its_own_check(metrics_ok):
    r = check_figures(template_commentary(metrics_ok), metrics_ok)
    assert r["ok"] and len(r["verified"]) >= 15


def _m(metrics, mid):
    return next(m for m in metrics if m["id"] == mid)


def test_invented_number_is_rejected(metrics_ok):
    r = check_figures("Fund revenue was $9.9M this month.", metrics_ok)
    assert not r["ok"] and r["unmatched"] == ["$9.9M"]


def test_wrongly_rounded_number_is_rejected(metrics_ok):
    rev = _m(metrics_ok, "fund.revenue.2026-06")  # shown as $4.6M
    off = f"${rev['value'] / 1e6 + 0.12:.1f}M"
    assert not check_figures(f"Revenue was {off}.", metrics_ok)["ok"]
    assert check_figures(f"Revenue was {rev['display']}.", metrics_ok)["ok"]


def test_more_precision_than_the_data_supports_is_checked_against_the_data(metrics_ok):
    rev = _m(metrics_ok, "fund.revenue.2026-06")
    assert check_figures(f"Revenue was ${rev['value']:,.0f}.", metrics_ok)["ok"]            # exact dollars: fine
    assert not check_figures(f"Revenue was ${rev['value'] + 5000:,.0f}.", metrics_ok)["ok"]  # off by $5,000: rejected


def test_units_must_agree_with_the_metric_kind(metrics_ok):
    cash_pct = _m(metrics_ok, "fund.cash.2026-06")["value"] / 1e6
    assert not check_figures(f"Cash was {cash_pct:.1f}%.", metrics_ok)["ok"]      # a $ figure written as a percentage
    assert not check_figures("Headcount was $426.", metrics_ok)["ok"]            # a count written as dollars


def test_spelled_out_scales_and_signs(metrics_ok):
    rev = _m(metrics_ok, "fund.revenue.2026-06")
    assert check_figures(f"Revenue reached {rev['value'] / 1e6:.1f} million.", metrics_ok)["ok"]
    mom = _m(metrics_ok, "fund.revenue.mom")
    assert check_figures(f"It moved {mom['value']:+.1f}% versus last month.", metrics_ok)["ok"]


def test_years_periods_and_fiscal_labels_are_not_figures():
    toks = [f["token"] for f in extract_figures("In June 2026 (period 2026-06, FY26 M10, Q2) revenue was $4.6M and 12.5% of the total.")]
    assert toks == ["$4.6M", "12.5%"]


GOOD = ("- Fund revenue was {fund.revenue.2026-06}, {fund.revenue.mom} versus the prior month.\n"
        "- EBITDA margin was {fund.ebitda_margin_pct.2026-06} across {n_companies} companies.")


class Writer:
    def __init__(self, drafts): self.drafts, self.calls, self.feedback = list(drafts), 0, []
    def write(self, M, feedback=""):
        self.calls += 1; self.feedback.append(feedback)
        d = self.drafts.pop(0)
        if isinstance(d, Exception):
            raise d
        return d


def test_placeholders_are_substituted_with_verified_display_strings(metrics_ok):
    r = generate(metrics_ok, Writer([GOOD]))
    rev = _m(metrics_ok, "fund.revenue.2026-06")["display"]
    assert r["source"] == "llm" and rev in r["text"] and "{" not in r["text"] and r["check"]["ok"]


def test_llm_that_types_its_own_number_is_rejected_and_retried(metrics_ok):
    w = Writer(["- Revenue grew 27.3% and hit $8.8M.", GOOD])
    r = generate(metrics_ok, w)
    assert r["source"] == "llm" and w.calls == 2 and "27.3%" in w.feedback[1] and "$8.8M" in w.feedback[1]
    assert r["attempts"][0]["ok"] is False


def test_even_a_correct_literal_number_is_rejected_in_placeholder_mode(metrics_ok):
    rev = _m(metrics_ok, "fund.revenue.2026-06")["display"]
    r = generate(metrics_ok, Writer([f"- Revenue was {rev}."] * 3))
    assert r["source"] == "template"  # the LLM must not write figures at all, right or wrong


def test_unknown_placeholder_is_rejected(metrics_ok):
    w = Writer(["- Revenue was {fund.revenue.2031-01}.", GOOD])
    r = generate(metrics_ok, w)
    assert w.calls == 2 and "{fund.revenue.2031-01}" in w.feedback[1] and r["source"] == "llm"


def test_persistently_bad_llm_falls_back_to_the_template(metrics_ok):
    r = generate(metrics_ok, Writer(["- Revenue was $1.1M."] * 3))
    assert r["source"] == "template" and r["check"]["ok"]


def test_llm_outage_never_breaks_the_report(metrics_ok):
    r = generate(metrics_ok, Writer([TimeoutError("boom")]))
    assert r["source"] == "template" and r["attempts"][0]["ok"] is False


def test_every_published_commentary_is_machine_verified(metrics_ok):
    for w in [None, Writer([GOOD])]:
        assert generate(metrics_ok, w)["check"]["ok"]


def test_known_limitation_postfilter_cannot_catch_a_real_number_under_the_wrong_label(metrics_ok):
    """Documented, not fixed: check_figures only proves a number EXISTS. Placeholder mode narrows this to
    'LLM picked the wrong metric id', which the display-value hints in the prompt are meant to prevent."""
    cash = _m(metrics_ok, "fund.cash.2026-06")["display"]
    assert check_figures(f"Revenue was {cash}.", metrics_ok)["ok"]
