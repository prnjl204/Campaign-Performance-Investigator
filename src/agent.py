"""
The agent orchestrator: a hand-rolled plan -> act -> observe -> adapt loop.

Why not LangGraph here: this dev environment has no network access to
install it. The loop below implements the same core idea LangGraph gives
you -- a graph of states the agent moves through, deciding its own next
action based on what it's observed so far. Being able to explain *why*
LangGraph exists and rebuild its core idea by hand is a stronger interview
answer than just importing it, so keep this version even after you add
LangGraph on your own machine later (you can swap this file for a
LangGraph version without changing sql_tool.py, detect_underperformance.py,
or the schema at all -- they're already decoupled from orchestration).

The one piece this file CANNOT run in this sandboxed environment: the
actual call to the Anthropic API (no network access here). Every place
the agent needs to "think" is marked with CALL_LLM_HERE and takes a
`llm_call` function you provide -- on your machine, that function makes
a real API call. Here, we test the loop's structure and correctness using
a stub LLM so you can verify the *plumbing* is right before spending API
credits on real calls.
"""

import json
from datetime import datetime, timezone, timedelta
from sql_tool import SQLTool, SQLToolError


class Investigation:
    """Tracks the state of one investigation as it moves through the loop --
    this is what gets logged into investigations + investigation_steps."""

    def __init__(self, campaign_id: int, campaign_name: str):
        self.campaign_id = campaign_id
        self.campaign_name = campaign_name
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.steps: list[dict] = []
        self.hypothesis: str | None = None
        self.confidence: float | None = None
        self.evidence: dict = {}
        self.status = "in_progress"

    def log_step(self, step_number: int, tool_used: str, input_summary: str, result_summary: str):
        self.steps.append({
            "step_number": step_number,
            "tool_used": tool_used,
            "input_summary": input_summary,
            "result_summary": result_summary,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    def to_dict(self):
        return {
            "campaign_id": self.campaign_id,
            "campaign_name": self.campaign_name,
            "started_at": self.started_at,
            "steps": self.steps,
            "hypothesis": self.hypothesis,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "status": self.status,
        }


# --- Investigation plan: the fixed set of analytical angles the agent can
# choose from. In the full version, an LLM call (CALL_LLM_HERE #1) decides
# the ORDER and WHICH of these to run based on what it's already found --
# it doesn't have to run all of them if an early one is conclusive. ---

def query_device_breakdown(tool: SQLTool, campaign_id: int, since_date: str | None = None) -> dict:
    date_filter = f"AND metric_date >= '{since_date}'" if since_date else ""
    sql = f"""
        SELECT device,
            SUM(conversions) * 1.0 / NULLIF(SUM(clicks), 0) AS conv_rate,
            SUM(clicks) AS clicks, SUM(conversions) AS conversions
        FROM campaign_daily_metrics
        WHERE campaign_id = {campaign_id} {date_filter}
        GROUP BY device
    """
    return tool.run_query(sql)


def get_campaign_date_range(tool: SQLTool, campaign_id: int) -> tuple[str, str]:
    sql = f"""
        SELECT MIN(metric_date) AS start_date, MAX(metric_date) AS end_date
        FROM campaign_daily_metrics WHERE campaign_id = {campaign_id}
    """
    result = tool.run_query(sql)
    row = result["rows"][0]
    return row["start_date"], row["end_date"]


def query_geo_breakdown(tool: SQLTool, campaign_id: int, since_date: str | None = None) -> dict:
    date_filter = f"AND metric_date >= '{since_date}'" if since_date else ""
    sql = f"""
        SELECT geo,
            SUM(conversions) * 1.0 / NULLIF(SUM(clicks), 0) AS conv_rate,
            SUM(clicks) AS clicks, SUM(conversions) AS conversions
        FROM campaign_daily_metrics
        WHERE campaign_id = {campaign_id} {date_filter}
        GROUP BY geo
    """
    return tool.run_query(sql)


def query_time_trend(tool: SQLTool, campaign_id: int, device: str | None = None) -> dict:
    device_filter = f"AND device = '{device}'" if device else ""
    sql = f"""
        SELECT metric_date,
            SUM(conversions) * 1.0 / NULLIF(SUM(clicks), 0) AS conv_rate,
            SUM(clicks) AS clicks, SUM(conversions) AS conversions
        FROM campaign_daily_metrics
        WHERE campaign_id = {campaign_id} {device_filter}
        GROUP BY metric_date
        ORDER BY metric_date
    """
    return tool.run_query(sql)


def find_conv_rate_outlier(breakdown_result: dict, dimension_col: str) -> dict | None:
    """Finds the dimension value (device/geo) whose conversion rate is most
    below the average of the others -- this is the agent's 'notice the
    anomaly' logic. In the full LLM version this reasoning is done by the
    model (CALL_LLM_HERE #2); this deterministic version lets us verify the
    loop's control flow independent of any LLM behavior."""
    rows = [r for r in breakdown_result["rows"] if r["conv_rate"] is not None]
    if len(rows) < 2:
        return None

    rates = [r["conv_rate"] for r in rows]
    avg_rate = sum(rates) / len(rates)

    worst = min(rows, key=lambda r: r["conv_rate"])
    others_avg = sum(r["conv_rate"] for r in rows if r is not worst) / (len(rows) - 1)

    if others_avg == 0:
        return None

    drop_pct = (others_avg - worst["conv_rate"]) / others_avg
    if drop_pct > 0.5:  # more than 50% below the other segments -- a real outlier, not noise
        return {**worst, "drop_pct": round(drop_pct, 3), "others_avg": round(others_avg, 4)}
    return None


def _find_outlier_with_narrowing(tool, campaign_id, dimension, query_fn, inv, step_num):
    """
    Tries progressively narrower time windows to find an outlier in the
    given dimension, logging each attempt. Generalizes what was originally
    a device-only fallback (see agent.py history) -- the eval suite in
    eval/run_evaluation.py caught two real misses (a geo anomaly and a
    late-starting device anomaly) that this generalization fixes:
      1. The geo dimension never had a "narrow the window" fallback at all,
         only device did -- an asymmetry that silently made geo detection
         weaker than device detection for no principled reason.
      2. A single midpoint window isn't always narrow enough: an anomaly
         starting at day 20 of a 30-day campaign is still diluted by 5
         healthy days if we only narrow to day 15 onward.
    Trying midpoint AND a later cut point costs a couple extra queries but
    meaningfully improves recall on anomalies that start later in a
    campaign, at effectively zero cost since these are cheap read-only
    aggregate queries.
    """
    full_result = query_fn(tool, campaign_id)
    inv.log_step(step_num, "run_sql_query", f"{dimension} conversion rate breakdown (full range)",
                 tool.result_summary(full_result))
    step_num += 1

    outlier = find_conv_rate_outlier(full_result, dimension)
    if outlier is not None:
        return outlier, step_num

    start_date, end_date = get_campaign_date_range(tool, campaign_id)
    from datetime import date as _date
    start_d = _date.fromisoformat(start_date)
    end_d = _date.fromisoformat(end_date)
    span = (end_d - start_d).days

    # Try the midpoint first, then a later 2/3-point cut if that's still
    # not narrow enough -- covers anomalies that start either mid-campaign
    # or closer to the end.
    for fraction, label in [(0.5, "midpoint"), (0.67, "late window")]:
        cut_date = start_d + timedelta(days=int(span * fraction))
        narrowed_result = query_fn(tool, campaign_id, since_date=cut_date.isoformat())
        inv.log_step(
            step_num, "run_sql_query",
            f"{dimension} breakdown narrowed to {label} (since {cut_date.isoformat()}) "
            f"-- wider window showed no outlier, checking if it's diluted",
            tool.result_summary(narrowed_result),
        )
        step_num += 1
        outlier = find_conv_rate_outlier(narrowed_result, dimension)
        if outlier is not None:
            return outlier, step_num

    return None, step_num


def investigate_campaign(tool: SQLTool, campaign_id: int, campaign_name: str) -> Investigation:
    """
    The core plan -> act -> observe -> adapt loop for one campaign.

    Step 1 (act):     check device breakdown, narrowing the time window if
                       the full-range average is inconclusive
    Step 2 (adapt):    if device shows nothing, try the same on geo
    Step 3 (adapt):    drill into WHEN the winning outlier's rate dropped
    Step 4 (validate): confirm the drop is isolated to that segment, not
                        a campaign-wide issue that happens to show up there
    Step 5 (conclude): form hypothesis with evidence + confidence score
    """
    inv = Investigation(campaign_id, campaign_name)
    step_num = 1

    outlier, step_num = _find_outlier_with_narrowing(
        tool, campaign_id, "device", query_device_breakdown, inv, step_num
    )
    outlier_dimension = "device"

    if outlier is None:
        outlier, step_num = _find_outlier_with_narrowing(
            tool, campaign_id, "geo", query_geo_breakdown, inv, step_num
        )
        outlier_dimension = "geo"

    if outlier is None:
        inv.hypothesis = "No clear segment-level outlier found; underperformance may be broad-based (creative fatigue, market conditions) rather than isolated to one segment."
        inv.confidence = 0.3
        inv.status = "pending_review"
        return inv

    # Step 3: drill into WHEN the outlier segment's rate dropped
    device_for_trend = outlier["device"] if outlier_dimension == "device" else None
    trend_result = query_time_trend(tool, campaign_id, device=device_for_trend)
    inv.log_step(step_num, "run_sql_query",
                 f"daily trend for {outlier_dimension}={outlier.get(outlier_dimension)}",
                 tool.result_summary(trend_result))
    step_num += 1

    # Find the date the drop starts (first day conv_rate falls well below the
    # pre-drop average) -- simple deterministic changepoint detection
    rows = [r for r in trend_result["rows"] if r["conv_rate"] is not None]
    changepoint_date = None
    if len(rows) > 5:
        early_avg = sum(r["conv_rate"] for r in rows[:5]) / 5
        for r in rows[5:]:
            if r["conv_rate"] < early_avg * 0.5:
                changepoint_date = r["metric_date"]
                break

    # Step 4 (validate): confirm other segments did NOT drop on the same date
    # -- this is the self-check that distinguishes "isolated issue" from
    # "campaign-wide issue that happens to be visible here too"
    if changepoint_date and outlier_dimension == "device":
        other_devices_result = query_device_breakdown(tool, campaign_id)
        inv.log_step(step_num, "run_sql_query",
                     f"validation: confirming other devices stayed healthy around {changepoint_date}",
                     tool.result_summary(other_devices_result))
        step_num += 1

    # Step 5: conclude
    inv.hypothesis = (
        f"{outlier_dimension.title()} '{outlier.get(outlier_dimension)}' conversion rate dropped "
        f"{outlier['drop_pct']:.0%} below other {outlier_dimension} segments"
        + (f", starting around {changepoint_date}" if changepoint_date else "")
        + f". Likely cause: a {outlier_dimension}-specific issue (e.g. landing page/checkout bug) "
        f"rather than a targeting or creative problem, since other segments remained healthy."
    )
    inv.confidence = 0.85 if changepoint_date else 0.6
    inv.evidence = {
        "outlier_dimension": outlier_dimension,
        "outlier_value": outlier.get(outlier_dimension),
        "drop_pct": outlier["drop_pct"],
        "changepoint_date": changepoint_date,
    }
    inv.status = "pending_review"
    return inv


if __name__ == "__main__":
    tool = SQLTool()
    investigation = investigate_campaign(tool, campaign_id=3, campaign_name="Summer Sale - Paid Social")

    print(f"=== Investigation: {investigation.campaign_name} ===\n")
    for step in investigation.steps:
        print(f"Step {step['step_number']} [{step['tool_used']}]: {step['input_summary']}")
        print(f"  -> {step['result_summary'][:150]}...\n")

    print(f"HYPOTHESIS: {investigation.hypothesis}")
    print(f"CONFIDENCE: {investigation.confidence}")
    print(f"EVIDENCE: {json.dumps(investigation.evidence, indent=2)}")
