"""
Generates a SEPARATE evaluation database (eval/eval_campaigns.db) with
multiple synthetic campaigns, each with a KNOWN ground truth, recorded in
eval/scenarios.json.

Kept deliberately separate from data/campaigns.db (the demo database used
by the dashboard) for two reasons:
1. We don't want to clutter the demo dataset with 10 synthetic test
   campaigns that would confuse someone clicking through the dashboard.
2. Evaluation data should be regeneratable/disposable independent of the
   "real" demo data someone might have started customizing.

SCENARIO DESIGN: this deliberately includes GEO-based anomalies, not just
device-based ones. Every real test we've run on the agent so far used a
device anomaly (mobile). agent.py has a fallback code path that checks geo
ONLY when no device-level outlier is found -- that path has never actually
executed against real data until this eval suite runs. Including geo
scenarios here isn't just "more thorough," it's the first real test of
code that's been sitting untested in the agent's logic.
"""

import sys
import os
import json
import sqlite3
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from generate_seed_data import (  # noqa: E402
    daterange, insert_campaign, generate_healthy_day, _probabilistic_round,
)

EVAL_DB_PATH = os.path.join(os.path.dirname(__file__), "eval_campaigns.db")
SCENARIOS_PATH = os.path.join(os.path.dirname(__file__), "scenarios.json")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "src", "schema.sql")

DEVICES = ["mobile", "desktop", "tablet"]
GEOS = ["CA", "NY", "TX", "FL", "IL"]
SEGMENTS = ["new_visitors", "returning", "loyal"]

import random
random.seed(123)  # different seed from the main demo dataset, deliberately


def build_schema(conn):
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())


def populate_metrics_generic(conn, campaign_id, start, end,
                               anomaly_dimension=None, anomaly_value=None,
                               anomaly_start=None, anomaly_conv_multiplier=1.0):
    """
    Like generate_seed_data.populate_metrics, but generalized to inject an
    anomaly into EITHER the device OR geo dimension -- the original only
    supported device. This is what lets us generate geo-based test cases.
    """
    base_impressions_per_cell = 400
    base_ctr = 0.035
    base_conv_rate = 0.06
    avg_cpc = 1.20

    rows = []
    for day in daterange(start, end):
        for device in DEVICES:
            for geo in GEOS:
                for segment in SEGMENTS:
                    impressions, clicks, conversions, spend = generate_healthy_day(
                        base_impressions_per_cell, base_ctr, base_conv_rate, avg_cpc
                    )

                    is_anomalous_day = anomaly_start and day >= anomaly_start
                    dimension_value = device if anomaly_dimension == "device" else geo
                    if is_anomalous_day and anomaly_dimension and dimension_value == anomaly_value:
                        conversions = max(0, _probabilistic_round(conversions * anomaly_conv_multiplier))

                    rows.append((
                        campaign_id, day.isoformat(), device, geo, segment,
                        impressions, clicks, conversions, spend
                    ))

    conn.executemany(
        "INSERT INTO campaign_daily_metrics "
        "(campaign_id, metric_date, device, geo, segment, impressions, clicks, conversions, spend) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


# Each scenario: (name, channel, anomaly_dimension or None, anomaly_value,
#                  changepoint_day_offset, conv_multiplier)
# changepoint_day_offset is days after campaign start -- kept >= 8 so the
# agent's changepoint detection (which needs 5 "early" days as a baseline)
# always has enough pre-anomaly data to work with, regardless of scenario.
SCENARIOS = [
    ("Eval - Device Mobile Severe",   "Paid Social",  "device", "mobile",  15, 0.10),
    ("Eval - Device Desktop Severe",  "Paid Search",  "device", "desktop", 10, 0.15),
    ("Eval - Device Tablet Moderate", "Paid Social",  "device", "tablet",  20, 0.35),
    ("Eval - Geo TX Severe",          "Paid Search",  "geo",    "TX",      12, 0.10),
    ("Eval - Geo CA Moderate",        "Email",        "geo",    "CA",      18, 0.30),
    ("Eval - Geo FL Severe Early",    "Paid Social",  "geo",    "FL",      8,  0.05),
    ("Eval - Healthy Control A",      "Email",        None,     None,      None, 1.0),
    ("Eval - Healthy Control B",      "Paid Search",  None,     None,      None, 1.0),
]


def main():
    os.makedirs(os.path.dirname(EVAL_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(EVAL_DB_PATH)
    build_schema(conn)

    manifest = []
    campaign_start = date(2026, 6, 1)
    campaign_end = date(2026, 6, 30)

    for name, channel, dimension, value, changepoint_offset, multiplier in SCENARIOS:
        campaign_id = insert_campaign(
            conn, name, channel, campaign_start, campaign_end,
            budget=20000, target_cpa=20, target_ctr=0.04,
        )

        anomaly_start = (campaign_start + timedelta(days=changepoint_offset)) if changepoint_offset else None

        populate_metrics_generic(
            conn, campaign_id, campaign_start, campaign_end,
            anomaly_dimension=dimension, anomaly_value=value,
            anomaly_start=anomaly_start, anomaly_conv_multiplier=multiplier,
        )

        manifest.append({
            "campaign_id": campaign_id,
            "name": name,
            "ground_truth_dimension": dimension,   # None for healthy scenarios
            "ground_truth_value": value,
            "ground_truth_changepoint": anomaly_start.isoformat() if anomaly_start else None,
        })

    conn.commit()
    conn.close()

    with open(SCENARIOS_PATH, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated {len(manifest)} evaluation scenarios into {EVAL_DB_PATH}")
    print(f"Ground truth manifest written to {SCENARIOS_PATH}")
    for m in manifest:
        truth = f"{m['ground_truth_dimension']}={m['ground_truth_value']}" if m['ground_truth_dimension'] else "healthy (no anomaly)"
        print(f"  [{m['campaign_id']}] {m['name']:32} ground truth: {truth}")


if __name__ == "__main__":
    main()
