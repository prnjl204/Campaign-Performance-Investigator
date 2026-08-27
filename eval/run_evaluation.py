"""
Runs the agent against every scenario in eval/scenarios.json and scores it
against the known ground truth.

METRICS COMPUTED:
- Dimension accuracy: did the agent correctly identify WHICH dimension
  (device vs geo) the anomaly was in? (For healthy scenarios: did it
  correctly report low confidence / no dimension, rather than inventing one?)
- Value accuracy: given the right dimension, did it name the right specific
  value (e.g. "mobile" not "desktop")?
- False positive rate: on healthy campaigns, did the agent's confidence
  stay appropriately low (below 0.5), rather than confidently reporting a
  fake anomaly?

WHY THIS MATTERS FOR YOUR INTERVIEW STORY: "I ran it once and it worked"
is an anecdote. "8 test scenarios, 100% dimension accuracy, 0 false
positives" is a number you can defend under follow-up questions.
"""

import sys
import os
import json
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from sql_tool import SQLTool  # noqa: E402
from agent import investigate_campaign  # noqa: E402

# The observability layer (correctly) logs every SQL query at INFO level --
# useful for the dashboard/production use, but 8 investigations x ~5 queries
# each would flood this batch report with noise. Raising the threshold here
# doesn't change logging behavior anywhere else in the codebase.
logging.getLogger("campaign_investigator").setLevel(logging.WARNING)

SCENARIOS_PATH = os.path.join(os.path.dirname(__file__), "scenarios.json")
EVAL_DB_PATH = os.path.join(os.path.dirname(__file__), "eval_campaigns.db")

FALSE_POSITIVE_CONFIDENCE_THRESHOLD = 0.5


def run_evaluation():
    with open(SCENARIOS_PATH) as f:
        scenarios = json.load(f)

    tool = SQLTool(db_path=EVAL_DB_PATH)

    results = []
    for scenario in scenarios:
        investigation = investigate_campaign(
            tool, scenario["campaign_id"], scenario["name"]
        )

        predicted_dimension = investigation.evidence.get("outlier_dimension")
        predicted_value = investigation.evidence.get("outlier_value")
        is_healthy_scenario = scenario["ground_truth_dimension"] is None

        if is_healthy_scenario:
            # Correct = agent did NOT confidently claim a specific anomaly
            dimension_correct = investigation.confidence < FALSE_POSITIVE_CONFIDENCE_THRESHOLD
            value_correct = dimension_correct  # same judgment for healthy cases
        else:
            dimension_correct = predicted_dimension == scenario["ground_truth_dimension"]
            value_correct = dimension_correct and predicted_value == scenario["ground_truth_value"]

        results.append({
            "campaign_id": scenario["campaign_id"],
            "name": scenario["name"],
            "ground_truth": f"{scenario['ground_truth_dimension']}={scenario['ground_truth_value']}"
                             if not is_healthy_scenario else "healthy",
            "predicted": f"{predicted_dimension}={predicted_value}" if predicted_dimension else "no anomaly found",
            "confidence": investigation.confidence,
            "dimension_correct": dimension_correct,
            "value_correct": value_correct,
            "is_healthy_scenario": is_healthy_scenario,
        })

    return results


def print_report(results):
    print(f"{'Campaign':32} {'Ground Truth':16} {'Predicted':16} {'Conf':6} {'Correct'}")
    print("-" * 90)
    for r in results:
        mark = "✓" if r["value_correct"] else "✗"
        print(f"{r['name']:32} {r['ground_truth']:16} {r['predicted']:16} "
              f"{r['confidence']:.2f}   {mark}")

    n = len(results)
    dimension_acc = sum(r["dimension_correct"] for r in results) / n
    value_acc = sum(r["value_correct"] for r in results) / n

    healthy_results = [r for r in results if r["is_healthy_scenario"]]
    anomaly_results = [r for r in results if not r["is_healthy_scenario"]]

    false_positives = sum(1 for r in healthy_results if not r["dimension_correct"])
    false_negatives = sum(1 for r in anomaly_results if not r["dimension_correct"])

    print("-" * 90)
    print(f"Dimension accuracy (overall): {dimension_acc:.0%} ({sum(r['dimension_correct'] for r in results)}/{n})")
    print(f"Exact value accuracy (overall): {value_acc:.0%} ({sum(r['value_correct'] for r in results)}/{n})")
    print(f"False positives (healthy campaigns flagged as anomalous): {false_positives}/{len(healthy_results)}")
    print(f"False negatives (real anomalies missed): {false_negatives}/{len(anomaly_results)}")


if __name__ == "__main__":
    results = run_evaluation()
    print_report(results)
