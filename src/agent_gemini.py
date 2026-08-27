"""
Gemini version of the LLM-driven agent -- an alternative to agent_llm.py
for anyone who wants to run this on Gemini's free tier instead of paying
for Anthropic API credits.

RUN THIS ON YOUR OWN MACHINE, not in this sandbox -- same limitation as
agent_llm.py: no network access here to install google-genai or call the
API. The logic below mirrors agent_llm.py's structure exactly (same tools,
same system prompt, same investigation flow) so the two are easy to
compare side by side in an interview -- "I built this against two
different providers to see how portable the design was" is a genuinely
good thing to be able to say.

SETUP (on your machine):
    pip install google-genai
    Get a free API key at https://aistudio.google.com/apikey
    export GEMINI_API_KEY=your_key_here
    python src/agent_gemini.py

A NOTE ON THE MODEL NAME: this is currently set to "gemini-3.6-flash".
I originally shipped this with "gemini-2.5-flash", which was deprecated
for new users shortly after -- confirmed by an actual test run against
the live API, which returned a 404 naming "gemini-3.6-flash" as the
replacement. Google ships new Gemini versions frequently; if you hit a
"model not found" error again in the future, check
https://ai.google.dev/gemini-api/docs/models for the current free-tier
flash model name and update the constant below -- everything else in
this file is unaffected by which specific model you use.

WHAT TO CHECK WHEN YOU RUN THIS (same questions as agent_llm.py, so you
can compare the two providers' behavior on the identical task):
1. Does it choose to check device breakdown first?
2. Does it notice the full-range average is inconclusive and narrow the
   time window on its own?
3. How does its final hypothesis wording compare to Claude's version and
   to agent.py's templated one?
"""

import os
import json
from google import genai
from google.genai import types
from sql_tool import SQLTool
from agent import (
    Investigation, query_device_breakdown, query_geo_breakdown,
    query_time_trend, get_campaign_date_range,
)

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
MODEL = "gemini-3.6-flash"  # confirmed free-tier eligible via Google AI Studio
# (rate-limited; free tier usage may be used by Google to improve their
# products, per their docs -- fine for a portfolio demo, worth knowing if
# you ever point this at real customer data). gemini-2.5-flash was
# deprecated for new users; check ai.google.dev/gemini-api/docs/models if
# this name also becomes outdated later.

# Same five tools as agent_llm.py, translated to Gemini's FunctionDeclaration
# format (parameters_json_schema instead of Anthropic's input_schema --
# functionally the same JSON Schema underneath).
TOOL_DECLARATIONS = [
    types.FunctionDeclaration(
        name="query_device_breakdown",
        description="Get conversion rate broken down by device (mobile/desktop/tablet) for this campaign, optionally restricted to dates on or after since_date.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "since_date": {"type": "string", "description": "Optional ISO date (YYYY-MM-DD) to restrict the query to recent data only."}
            },
        },
    ),
    types.FunctionDeclaration(
        name="query_geo_breakdown",
        description="Get conversion rate broken down by geography for this campaign.",
        parameters_json_schema={"type": "object", "properties": {}},
    ),
    types.FunctionDeclaration(
        name="query_time_trend",
        description="Get the daily conversion rate trend for this campaign, optionally filtered to one device.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "Optional device to filter to, e.g. 'mobile'."}
            },
        },
    ),
    types.FunctionDeclaration(
        name="get_campaign_date_range",
        description="Get the start and end date of data available for this campaign.",
        parameters_json_schema={"type": "object", "properties": {}},
    ),
    types.FunctionDeclaration(
        name="conclude_investigation",
        description="Call this when you have enough evidence to state a final hypothesis. This ends the investigation.",
        parameters_json_schema={
            "type": "object",
            "properties": {
                "hypothesis": {"type": "string", "description": "Your conclusion, written for a marketing analyst -- what happened, when, and why you believe it."},
                "confidence": {"type": "number", "description": "0.0 to 1.0"},
                "evidence": {"type": "object", "description": "Key structured facts backing the hypothesis."},
            },
            "required": ["hypothesis", "confidence", "evidence"],
        },
    ),
]

TOOL = types.Tool(function_declarations=TOOL_DECLARATIONS)

# Identical wording to agent_llm.py's SYSTEM_PROMPT -- kept in sync
# deliberately so any behavior difference we observe comes from the model,
# not from an accidentally different prompt.
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


def execute_tool_call(tool_name: str, tool_args: dict, sql_tool: SQLTool, campaign_id: int) -> dict:
    """Identical dispatch logic to agent_llm.py's version -- same tools,
    same underlying SQL functions, just called from a different SDK's
    function-call representation."""
    if tool_name == "query_device_breakdown":
        result = query_device_breakdown(sql_tool, campaign_id, since_date=tool_args.get("since_date"))
    elif tool_name == "query_geo_breakdown":
        result = query_geo_breakdown(sql_tool, campaign_id)
    elif tool_name == "query_time_trend":
        result = query_time_trend(sql_tool, campaign_id, device=tool_args.get("device"))
    elif tool_name == "get_campaign_date_range":
        start, end = get_campaign_date_range(sql_tool, campaign_id)
        result = {"rows": [{"start_date": start, "end_date": end}], "row_count": 1, "truncated": False}
    else:
        raise ValueError(f"Unknown tool: {tool_name}")
    return result


def investigate_campaign_with_gemini(sql_tool: SQLTool, campaign_id: int, campaign_name: str,
                                       max_turns: int = 8) -> Investigation:
    inv = Investigation(campaign_id, campaign_name)
    step_num = 1

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(
                text=f"Investigate why campaign '{campaign_name}' (campaign_id={campaign_id}) "
                     f"is underperforming its target CPA. Use your tools to find out why."
            )],
        )
    ]

    for turn in range(max_turns):
        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[TOOL],
            ),
        )

        function_calls = response.function_calls
        if not function_calls:
            break  # model responded with plain text instead of a tool call -- treat as done

        # Preserve the model's own turn (including its function call parts)
        # in the conversation history before appending our responses to it --
        # Gemini's API expects the full back-and-forth, same as Anthropic's.
        contents.append(response.candidates[0].content)

        function_response_parts = []
        for call in function_calls:
            if call.name == "conclude_investigation":
                inv.hypothesis = call.args["hypothesis"]
                inv.confidence = call.args["confidence"]
                inv.evidence = call.args["evidence"]
                inv.status = "pending_review"
                return inv

            result = execute_tool_call(call.name, dict(call.args), sql_tool, campaign_id)
            summary = sql_tool.result_summary(result) if "rows" in result else json.dumps(result)
            inv.log_step(step_num, call.name, json.dumps(dict(call.args)), summary)
            step_num += 1

            function_response_parts.append(
                types.Part.from_function_response(
                    name=call.name,
                    response={"result": result.get("rows", result)},
                )
            )

        # NOTE: role='tool' does NOT work here, despite some Google docs
        # examples showing it -- confirmed by an actual 400 error against
        # the live API ("Role 'tool' is not supported... use USER").
        # Gemini expects function responses to come back with role='user',
        # unlike Anthropic's API (agent_llm.py), which does use a distinct
        # tool-result content type. This is exactly the kind of provider-
        # specific quirk that's easy to miss from docs alone.
        contents.append(types.Content(role="user", parts=function_response_parts))

    # Loop ended without the model calling conclude_investigation
    inv.hypothesis = "Investigation did not reach a conclusion within the turn limit."
    inv.confidence = 0.0
    inv.status = "pending_review"
    return inv


if __name__ == "__main__":
    if not os.environ.get("GEMINI_API_KEY"):
        print("Set GEMINI_API_KEY before running this file (get a free key at "
              "https://aistudio.google.com/apikey). This script cannot run in "
              "the sandbox that generated it -- no network access there.")
        raise SystemExit(1)

    tool = SQLTool()
    investigation = investigate_campaign_with_gemini(tool, campaign_id=3, campaign_name="Summer Sale - Paid Social")

    print(f"=== Gemini-driven investigation: {investigation.campaign_name} ===\n")
    for step in investigation.steps:
        print(f"Step {step['step_number']} [{step['tool_used']}]: {step['input_summary']}")
        print(f"  -> {step['result_summary'][:150]}...\n")

    print(f"HYPOTHESIS: {investigation.hypothesis}")
    print(f"CONFIDENCE: {investigation.confidence}")
    print(f"EVIDENCE: {json.dumps(investigation.evidence, indent=2)}")
