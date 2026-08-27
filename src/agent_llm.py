"""
LLM integration layer -- RUN THIS ON YOUR OWN MACHINE, not in this sandbox.

This sandbox has no network access, so I couldn't call the Anthropic API to
test this file. The logic mirrors agent.py's deterministic version exactly
(same steps, same order) so you can diff the two and see precisely what
changes when you swap rules for reasoning: the "narrow to recent window"
decision, the outlier judgment, and the final hypothesis are now made by
the model instead of a fixed threshold.

SETUP (on your machine):
    pip install anthropic
    export ANTHROPIC_API_KEY=your_key_here
    python src/agent_llm.py

WHAT TO CHECK WHEN YOU RUN THIS:
1. Does the model choose to check device breakdown first (like our rule
   version did), or does it reason differently? Either is fine -- the
   point is that it's making a genuine choice, not that it matches our
   rules exactly.
2. Does it correctly notice the full-range average is inconclusive and
   decide to narrow the time window on its own, without being told to?
   This is the single best moment to screen-record for a demo.
3. Compare its final hypothesis wording to agent.py's templated one --
   the LLM version should read like an analyst wrote it.
"""

import os
import json
from anthropic import Anthropic
from sql_tool import SQLTool
from agent import (
    Investigation, query_device_breakdown, query_geo_breakdown,
    query_time_trend, get_campaign_date_range,
)

client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
MODEL = "claude-sonnet-4-5"  # swap for whichever current model you have access to

# Tool definitions the model can choose to call -- function calling / tool use,
# one of the core skills this whole project exists to demonstrate.
TOOLS = [
    {
        "name": "query_device_breakdown",
        "description": "Get conversion rate broken down by device (mobile/desktop/tablet) for this campaign, optionally restricted to dates on or after since_date.",
        "input_schema": {
            "type": "object",
            "properties": {
                "since_date": {"type": "string", "description": "Optional ISO date (YYYY-MM-DD) to restrict the query to recent data only."}
            },
        },
    },
    {
        "name": "query_geo_breakdown",
        "description": "Get conversion rate broken down by geography for this campaign.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "query_time_trend",
        "description": "Get the daily conversion rate trend for this campaign, optionally filtered to one device.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "Optional device to filter to, e.g. 'mobile'."}
            },
        },
    },
    {
        "name": "get_campaign_date_range",
        "description": "Get the start and end date of data available for this campaign.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "conclude_investigation",
        "description": "Call this when you have enough evidence to state a final hypothesis. This ends the investigation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hypothesis": {"type": "string", "description": "Your conclusion, written for a marketing analyst -- what happened, when, and why you believe it."},
                "confidence": {"type": "number", "description": "0.0 to 1.0"},
                "evidence": {"type": "object", "description": "Key structured facts backing the hypothesis."},
            },
            "required": ["hypothesis", "confidence", "evidence"],
        },
    },
]

SYSTEM_PROMPT = """You are a marketing analytics investigator agent. You are given \
an underperforming campaign and must find WHY it's underperforming by querying \
its data. You have tools to break down performance by device, geography, and time.

Investigate like a careful analyst:
- Start broad, then narrow based on what you find.
- If an aggregate view looks inconclusive, consider whether averaging over the \
full campaign period could be hiding a change that started partway through -- \
try narrowing the date range before concluding there's no pattern.
- Before concluding, validate your hypothesis with one more targeted query \
if possible (e.g. confirm other segments stayed healthy during the anomaly window).
- Only call conclude_investigation once you have real evidence. Assign confidence \
honestly -- a vague or unconfirmed finding should get a lower score, not be dressed \
up as certain.
- You do not have permission to change anything about the campaign. You only \
investigate and report."""


def execute_tool_call(tool_name: str, tool_input: dict, sql_tool: SQLTool, campaign_id: int) -> dict:
    """Dispatches a model-requested tool call to the actual SQL functions,
    and logs it for the investigation_steps audit trail."""
    if tool_name == "query_device_breakdown":
        result = query_device_breakdown(sql_tool, campaign_id, since_date=tool_input.get("since_date"))
    elif tool_name == "query_geo_breakdown":
        result = query_geo_breakdown(sql_tool, campaign_id)
    elif tool_name == "query_time_trend":
        result = query_time_trend(sql_tool, campaign_id, device=tool_input.get("device"))
    elif tool_name == "get_campaign_date_range":
        start, end = get_campaign_date_range(sql_tool, campaign_id)
        result = {"rows": [{"start_date": start, "end_date": end}], "row_count": 1, "truncated": False}
    else:
        raise ValueError(f"Unknown tool: {tool_name}")
    return result


def investigate_campaign_with_llm(sql_tool: SQLTool, campaign_id: int, campaign_name: str,
                                    max_turns: int = 8) -> Investigation:
    inv = Investigation(campaign_id, campaign_name)
    step_num = 1

    messages = [{
        "role": "user",
        "content": f"Investigate why campaign '{campaign_name}' (campaign_id={campaign_id}) "
                    f"is underperforming its target CPA. Use your tools to find out why."
    }]

    for turn in range(max_turns):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            break  # model responded with plain text instead of a tool call -- treat as done

        tool_results = []
        for block in tool_use_blocks:
            if block.name == "conclude_investigation":
                inv.hypothesis = block.input["hypothesis"]
                inv.confidence = block.input["confidence"]
                inv.evidence = block.input["evidence"]
                inv.status = "pending_review"
                return inv

            result = execute_tool_call(block.name, block.input, sql_tool, campaign_id)
            summary = sql_tool.result_summary(result) if "rows" in result else json.dumps(result)
            inv.log_step(step_num, block.name, json.dumps(block.input), summary)
            step_num += 1

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result.get("rows", result)),
            })

        messages.append({"role": "user", "content": tool_results})

    # Loop ended without the model calling conclude_investigation -- this is a
    # real failure mode worth handling explicitly rather than silently, since
    # it's the kind of thing that happens in production agent systems.
    inv.hypothesis = "Investigation did not reach a conclusion within the turn limit."
    inv.confidence = 0.0
    inv.status = "pending_review"
    return inv


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Set ANTHROPIC_API_KEY before running this file. This script cannot "
              "run in the sandbox that generated it -- no network access there.")
        raise SystemExit(1)

    tool = SQLTool()
    investigation = investigate_campaign_with_llm(tool, campaign_id=3, campaign_name="Summer Sale - Paid Social")

    print(f"=== LLM-driven investigation: {investigation.campaign_name} ===\n")
    for step in investigation.steps:
        print(f"Step {step['step_number']} [{step['tool_used']}]: {step['input_summary']}")
        print(f"  -> {step['result_summary'][:150]}...\n")

    print(f"HYPOTHESIS: {investigation.hypothesis}")
    print(f"CONFIDENCE: {investigation.confidence}")
    print(f"EVIDENCE: {json.dumps(investigation.evidence, indent=2)}")
