"""
Generates synthetic-but-realistic campaign performance data.

Design choice: campaign 3 ("Summer Sale - Paid Social") has a DELIBERATE,
FINDABLE root cause injected into it -- a mobile conversion rate collapse
starting on a specific date, while desktop stays healthy. Everything else
(impressions, clicks, spend) looks normal on the surface. This lets us
later write an evaluation test: "did the agent correctly isolate the
mobile conversion issue, not just notice overall underperformance?"

This is what turns the project from a toy into something with a real
ground-truth evaluation story for interviews.
"""

import sqlite3
import random
import os
from datetime import date, timedelta

random.seed(42)  # reproducible data -- important for a consistent demo

DB_PATH = "data/campaigns.db"
SCHEMA_PATH = "src/schema.sql"

DEVICES = ["mobile", "desktop", "tablet"]
GEOS = ["CA", "NY", "TX", "FL", "IL"]
SEGMENTS = ["new_visitors", "returning", "loyal"]


def build_schema(conn):
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())


def daterange(start, end):
    days = (end - start).days
    for i in range(days + 1):
        yield start + timedelta(days=i)


def insert_campaign(conn, name, channel, start, end, budget, target_cpa, target_ctr):
    cur = conn.execute(
        "INSERT INTO campaigns (name, channel, start_date, end_date, budget, target_cpa, target_ctr) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, channel, start.isoformat(), end.isoformat(), budget, target_cpa, target_ctr),
    )
    return cur.lastrowid


def _probabilistic_round(x):
    """Rounds x to an int, using the fractional part as a probability.
    Prevents systematic downward bias when x is small (e.g. 0.84 clicks
    of conversion rate) -- plain int() truncation would round that to 0
    every time and quietly distort the whole dataset."""
    floor = int(x)
    return floor + 1 if random.random() < (x - floor) else floor


def generate_healthy_day(base_impressions, base_ctr, base_conv_rate, avg_cpc):
    """Normal day with small random noise -- no anomaly."""
    impressions = _probabilistic_round(base_impressions * random.uniform(0.9, 1.1))
    clicks = _probabilistic_round(impressions * base_ctr * random.uniform(0.85, 1.15))
    conversions = _probabilistic_round(clicks * base_conv_rate * random.uniform(0.8, 1.2))
    spend = round(clicks * avg_cpc * random.uniform(0.9, 1.1), 2)
    return impressions, clicks, conversions, spend


def populate_metrics(conn, campaign_id, start, end, anomaly_start=None,
                      anomaly_device=None, anomaly_conv_multiplier=1.0):
    """
    Generates daily rows split across device/geo/segment.
    If anomaly_start is set, conversions for `anomaly_device` collapse
    by `anomaly_conv_multiplier` from that date onward -- everything else
    (impressions, clicks, spend) stays normal, which is what makes this a
    realistic, non-obvious root cause to find.
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
                    if is_anomalous_day and device == anomaly_device:
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


def main():
    # Defensive: don't assume data/ already exists. sqlite3.connect() will
    # NOT create parent directories on its own -- it just fails with an
    # unhelpful "unable to open database file" error. This matters most in
    # a fresh container/volume where nothing has run yet.
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    build_schema(conn)

    # Idempotency guard: CREATE TABLE IF NOT EXISTS (in schema.sql) means
    # re-running this script against an existing database does NOT clear
    # old rows -- it would silently INSERT a second copy of every campaign
    # on top of the first. I found this the hard way: running this script
    # twice without deleting the .db file first produced 6 campaigns
    # instead of 3, with duplicate campaign_ids for the same names. Rather
    # than force a destructive DROP TABLE (which would also wipe real
    # investigation history on a genuine container restart -- the wrong
    # behavior there), the safe fix is to simply refuse to reseed a
    # database that already has data.
    existing_count = conn.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0]
    if existing_count > 0:
        print(f"Database already contains {existing_count} campaign(s) -- skipping reseed. "
              f"Delete {DB_PATH} first if you want a fresh dataset.")
        conn.close()
        return

    # Campaign 1: healthy campaign, no anomaly (control case)
    c1_start, c1_end = date(2026, 6, 1), date(2026, 6, 30)
    c1_id = insert_campaign(conn, "Spring Refresh - Email", "Email", c1_start, c1_end,
                             budget=15000, target_cpa=25, target_ctr=0.04)
    populate_metrics(conn, c1_id, c1_start, c1_end)

    # Campaign 2: healthy campaign, different channel (control case)
    c2_start, c2_end = date(2026, 6, 1), date(2026, 6, 30)
    c2_id = insert_campaign(conn, "Brand Awareness - Paid Search", "Paid Search", c2_start, c2_end,
                             budget=30000, target_cpa=20, target_ctr=0.05)
    populate_metrics(conn, c2_id, c2_start, c2_end)

    # Campaign 3: THE ANOMALY -- mobile conversion rate collapses on June 15
    # while desktop/tablet stay normal. This is the ground-truth test case.
    c3_start, c3_end = date(2026, 6, 1), date(2026, 6, 30)
    c3_id = insert_campaign(conn, "Summer Sale - Paid Social", "Paid Social", c3_start, c3_end,
                             budget=25000, target_cpa=18, target_ctr=0.045)
    populate_metrics(conn, c3_id, c3_start, c3_end,
                      anomaly_start=date(2026, 6, 15),
                      anomaly_device="mobile",
                      anomaly_conv_multiplier=0.15)  # ~85% conversion collapse on mobile only

    conn.commit()

    # Sanity check: print row counts
    for table in ["campaigns", "campaign_daily_metrics"]:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table}: {count} rows")

    conn.close()


if __name__ == "__main__":
    main()
