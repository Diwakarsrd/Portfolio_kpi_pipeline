"""ROI headline. The MANUAL time must be measured by a person (see docs/MANUAL_BASELINE.md); it is never estimated here.

data/manual_timing.json:
  {"manual_minutes": 95, "exception_review_minutes": 6, "mapping_confirmation_minutes": 10}
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
tf = ROOT / "data" / "manual_timing.json"
if not tf.exists():
    sys.exit("No data/manual_timing.json yet. Do one reporting cycle by hand with a stopwatch first (docs/MANUAL_BASELINE.md).")
t = json.loads(tf.read_text())
man = json.loads((ROOT / "outputs" / "corrected_run" / "manifest.json").read_text())
pipe_s = man["timings_s"]["total"]
review = t.get("exception_review_minutes", 0)
auto_min = pipe_s / 60 + review
print(f"Manual cycle (measured by you):            {t['manual_minutes']:.1f} min")
print(f"Pipeline compute:                          {pipe_s:.2f} s")
print(f"+ human review of DQ exceptions per cycle: {review:.1f} min")
print(f"Pipeline cycle, all-in:                    {auto_min:.1f} min  ->  {t['manual_minutes'] / auto_min:.1f}x faster, {t['manual_minutes'] - auto_min:.0f} min saved per cycle")
if t.get("mapping_confirmation_minutes"):
    be = t["mapping_confirmation_minutes"] / max(t["manual_minutes"] - auto_min, 1e-9)
    print(f"One-time mapping confirmation: {t['mapping_confirmation_minutes']:.0f} min (pays back after {be:.1f} cycles)")
print("Caveat: 5 synthetic companies, one machine, one person. Say exactly that when you quote the number.")
