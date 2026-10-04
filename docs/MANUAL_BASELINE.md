# Manual baseline - you must measure this yourself

The headline metric is **manual minutes vs pipeline minutes for the same cycle**. I cannot measure the manual side for you, and an estimate would be fabricated, so `roi.py` refuses to run without your number.

## Protocol (do it once, honestly)
1. Use the generated June 2026 files in `data/raw/*/2026-06.*` (5 files). Do NOT look at the pipeline output first.
2. Open a blank Excel workbook as your template. Start a stopwatch.
3. Do the whole cycle by hand: open each file, find each KPI under its company's own label, convert thousands/millions/lakhs/crore, convert AED and INR to USD with `config/fx.yaml`, align the fiscal period for Desert Solar, paste into the template, check EBITDA <= revenue and revenue - COGS = gross profit, build the fund totals with formulas, compute margins, write 5-6 lines of commentary, make one chart.
4. If you hit an error (you will: the data has planted ones), time the investigation too. That is real cycle time.
5. Stop the stopwatch when you have a report you would send.
6. Write `data/manual_timing.json`:
   `{"manual_minutes": <your number>, "exception_review_minutes": <minutes you need to resolve the pipeline's exceptions>, "mapping_confirmation_minutes": <one-time>}`
7. Run `python roi.py`.

## How to quote it
"One reporting cycle for 5 companies took N minutes by hand and M minutes with the pipeline (including my review of its exceptions). Synthetic data, one person." Do not extrapolate to real funds. The honest scaling argument is: manual effort grows with companies x months, pipeline effort grows with the number of NEW labels and exceptions.
