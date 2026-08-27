"""
Persistence layer: saves an Investigation object into the
investigations + investigation_steps tables.

This is a separate module from agent.py on purpose -- the agent's
reasoning logic shouldn't need to know about database write mechanics,
and the persistence logic shouldn't need to know how hypotheses are
formed. Keeping these decoupled is what let us test agent.py entirely
in-memory (fast, no DB writes during development) and only add
persistence once the reasoning logic was verified correct.

Note: this is the ONE place in the whole project that writes to the
database -- everywhere else (sql_tool.py) is strictly read-only. That
asymmetry is intentional and worth calling out in an interview: the
agent's investigation tools can never modify the data they're
analyzing, only the separate results tables.
"""

import sqlite3
from agent import Investigation


def get_write_connection(db_path="data/campaigns.db"):
    # Deliberately a NORMAL (non-read-only) connection, used only here --
    # everywhere else in the codebase uses SQLTool's read-only connection.
    return sqlite3.connect(db_path)


def save_investigation(investigation: Investigation, db_path="data/campaigns.db") -> int:
    conn = get_write_connection(db_path)
    try:
        import json
        cursor = conn.execute(
            """
            INSERT INTO investigations
                (campaign_id, started_at, hypothesis, evidence_json, confidence, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                investigation.campaign_id,
                investigation.started_at,
                investigation.hypothesis,
                json.dumps(investigation.evidence),
                investigation.confidence,
                investigation.status,
            ),
        )
        investigation_id = cursor.lastrowid

        for step in investigation.steps:
            conn.execute(
                """
                INSERT INTO investigation_steps
                    (investigation_id, step_number, tool_used, input_summary, result_summary, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    investigation_id,
                    step["step_number"],
                    step["tool_used"],
                    step["input_summary"],
                    step["result_summary"],
                    step["created_at"],
                ),
            )

        conn.commit()
        return investigation_id
    finally:
        conn.close()


def load_investigation(investigation_id: int, db_path="data/campaigns.db") -> dict:
    """Reads a saved investigation back out, joined with its steps --
    this is what the review dashboard (Week 3) will call."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        inv_row = conn.execute(
            "SELECT * FROM investigations WHERE investigation_id = ?", (investigation_id,)
        ).fetchone()
        if inv_row is None:
            raise ValueError(f"No investigation found with id {investigation_id}")

        steps = conn.execute(
            "SELECT * FROM investigation_steps WHERE investigation_id = ? ORDER BY step_number",
            (investigation_id,),
        ).fetchall()

        result = dict(inv_row)
        result["steps"] = [dict(s) for s in steps]
        return result
    finally:
        conn.close()


def set_review_decision(investigation_id: int, status: str, reviewed_by: str, db_path="data/campaigns.db"):
    """Human-in-the-loop approval step. status must be 'approved' or 'rejected' --
    this is the ONLY function in the entire codebase that lets a human record
    a decision, and it never triggers any downstream action itself (no email,
    no spend change) -- that's a deliberate scope boundary for this project."""
    if status not in ("approved", "rejected"):
        raise ValueError("status must be 'approved' or 'rejected'")

    from datetime import datetime, timezone
    conn = get_write_connection(db_path)
    try:
        conn.execute(
            """
            UPDATE investigations
            SET status = ?, reviewed_by = ?, reviewed_at = ?
            WHERE investigation_id = ?
            """,
            (status, reviewed_by, datetime.now(timezone.utc).isoformat(), investigation_id),
        )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    from sql_tool import SQLTool
    from agent import investigate_campaign

    tool = SQLTool()
    investigation = investigate_campaign(tool, campaign_id=3, campaign_name="Summer Sale - Paid Social")

    inv_id = save_investigation(investigation)
    print(f"Saved investigation #{inv_id}")

    loaded = load_investigation(inv_id)
    print(f"\nLoaded back from DB:")
    print(f"  Hypothesis: {loaded['hypothesis']}")
    print(f"  Confidence: {loaded['confidence']}")
    print(f"  Status: {loaded['status']}")
    print(f"  Steps saved: {len(loaded['steps'])}")

    set_review_decision(inv_id, "approved", reviewed_by="demo_analyst")
    reloaded = load_investigation(inv_id)
    print(f"\nAfter human review: status={reloaded['status']}, reviewed_by={reloaded['reviewed_by']}")
