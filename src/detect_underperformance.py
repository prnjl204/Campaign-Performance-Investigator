"""
Detection step: decides which campaigns are worth investigating.

Why a threshold, not a strict >: our own data exploration (Week 1) showed
a campaign barely over target (target 20.0 vs actual 20.11) is noise, not
a real problem. A strict ">" would flag it and waste an investigation on
nothing -- a >10% overage threshold filters that out while still catching
the real anomaly (23.30 vs 18.00, ~29% over).

This is a deliberately simple, transparent rule -- not ML-based -- because
the interesting agentic behavior happens in the *investigation* that
follows, not in the detection trigger. Keeping detection simple and
explainable is itself a defensible design choice to discuss in interviews.
"""

from sql_tool import SQLTool

OVERAGE_THRESHOLD = 0.10  # flag campaigns with actual CPA >10% over target


def find_underperforming_campaigns(tool: SQLTool) -> list[dict]:
    sql = """
        SELECT
            c.campaign_id,
            c.name,
            c.channel,
            c.target_cpa,
            SUM(m.spend) * 1.0 / NULLIF(SUM(m.conversions), 0) AS actual_cpa,
            SUM(m.conversions) AS total_conversions,
            SUM(m.spend) AS total_spend
        FROM campaigns c
        JOIN campaign_daily_metrics m ON m.campaign_id = c.campaign_id
        GROUP BY c.campaign_id, c.name, c.channel, c.target_cpa
    """
    result = tool.run_query(sql)

    flagged = []
    for row in result["rows"]:
        if row["actual_cpa"] is None:
            continue
        overage_pct = (row["actual_cpa"] - row["target_cpa"]) / row["target_cpa"]
        if overage_pct > OVERAGE_THRESHOLD:
            flagged.append({**row, "overage_pct": round(overage_pct, 3)})

    return flagged


if __name__ == "__main__":
    tool = SQLTool()
    flagged = find_underperforming_campaigns(tool)

    print(f"--- {len(flagged)} campaign(s) flagged for investigation (>{OVERAGE_THRESHOLD:.0%} over target CPA) ---")
    for c in flagged:
        print(
            f"[{c['campaign_id']}] {c['name']} ({c['channel']}): "
            f"target={c['target_cpa']}, actual={c['actual_cpa']:.2f}, "
            f"overage={c['overage_pct']:.1%}"
        )
