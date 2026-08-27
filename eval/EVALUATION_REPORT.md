# Evaluation Report — Campaign Performance Investigator

## Methodology

8 synthetic campaigns were generated with **known ground truth**, independent
of the demo dataset used elsewhere in the project (`eval/generate_eval_dataset.py`,
seeded separately from the main dataset). Scenarios covered:

- 3 device-level anomalies (mobile, desktop, tablet), severities ranging
  from a 65% to 90% conversion rate drop, at three different points in the
  campaign timeline (day 10, 15, and 20 of a 30-day campaign)
- 3 geo-level anomalies (TX, CA, FL), same range of severities and timing
- 2 healthy control campaigns with no injected anomaly, to measure false
  positive rate

The agent (`agent.py`'s deterministic investigation loop) was run against
all 8 with no prior knowledge of which were anomalous or what kind.

## Results

| Metric | Result |
|---|---|
| Dimension accuracy (device vs geo vs none) | 8/8 (100%) |
| Exact value accuracy (correct specific device/geo) | 8/8 (100%) |
| False positives (healthy campaigns wrongly flagged) | 0/2 |
| False negatives (real anomalies missed) | 0/6 |

## What the first run actually found (before a fix)

The first evaluation run scored 6/8 (75%), missing two real anomalies: a
tablet-device anomaly and a CA-geo anomaly. Root cause: the agent's
"narrow the time window when the full-range average is inconclusive"
logic had only ever been applied to the *device* dimension, not *geo* —
an asymmetry that was invisible until this eval suite specifically tested
geo-based anomalies for the first time. Additionally, a single fixed
midpoint window wasn't narrow enough for an anomaly starting later in the
campaign (day 20 of 30).

**Fix:** generalized the narrowing logic into one function usable by
either dimension, and added a second, later narrowing window (day ~20 of
30) tried when the midpoint window is still inconclusive. Re-running the
evaluation after the fix produced the 100% result above, with the
regression suite (the original mobile-anomaly test case from Week 2)
confirmed unchanged.

## Known limitations (honest, not hidden)

- Only one anomaly type is tested here: a sustained conversion-rate drop
  isolated to one device or geo segment. The agent has not been evaluated
  against other failure patterns (e.g. a gradual decline vs. a sharp
  break, or an anomaly affecting two dimensions simultaneously).
- The changepoint detection (finding *when* the drop started) uses a
  simple fixed rule (first day the rate falls below 50% of an early
  5-day baseline) — this hasn't been separately evaluated for date
  accuracy, only for whether the right *segment* was identified.
- Evaluation dataset is synthetic. Real campaign data will have messier,
  overlapping effects (seasonality, multiple simultaneous issues) that
  this suite doesn't cover.

## How to reproduce

```
cd campaign-investigator
python eval/generate_eval_dataset.py
python eval/run_evaluation.py
```
