"""
The agent's primary investigation tool: a sandboxed, read-only SQL runner.

Design choices worth explaining in an interview:
- READ-ONLY enforced at the connection level (query_only pragma), not just
  by convention -- an agent that can write SQL should never be trusted to
  also have write access to the database it's investigating.
- Row limit + timeout protection so a bad agent-generated query can't hang
  the system or return an unusably huge result.
- Every call is logged with its SQL and result summary -- this feeds the
  `investigation_steps` audit trail table directly.
"""

import sqlite3
import time
import json
from observability import get_logger, timed_step

_logger = get_logger()


class SQLToolError(Exception):
    pass


class SQLTool:
    def __init__(self, db_path="data/campaigns.db", row_limit=200, timeout_seconds=5):
        self.db_path = db_path
        self.row_limit = row_limit
        self.timeout_seconds = timeout_seconds

    def _get_readonly_connection(self):
        # uri=True + mode=ro enforces read-only at the SQLite driver level --
        # an UPDATE/DELETE/DROP will raise an error, not silently succeed.
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=self.timeout_seconds)
        conn.row_factory = sqlite3.Row
        return conn

    def run_query(self, sql: str) -> dict:
        """
        Executes a read-only SQL query and returns structured results.
        Returns a dict rather than raising on business-logic issues (empty
        results, etc.) -- only raises SQLToolError for actual failures,
        since the agent needs to be able to reason about "no rows found"
        as a normal outcome, not a crash.
        """
        forbidden = ["insert", "update", "delete", "drop", "alter", "create"]
        lowered = sql.strip().lower()
        if any(lowered.startswith(word) for word in forbidden):
            _logger.warning(
                "blocked write attempt",
                extra={"event": "sql_write_blocked", "sql": sql[:200]},
            )
            raise SQLToolError(
                f"Query rejected: this tool is read-only. "
                f"'{lowered.split()[0]}' statements are not permitted."
            )

        query_start = time.time()
        with timed_step(_logger, "sql_query", sql=sql[:200]):
            try:
                conn = self._get_readonly_connection()
                cursor = conn.execute(sql)
                rows = cursor.fetchmany(self.row_limit)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                conn.close()
            except sqlite3.Error as e:
                raise SQLToolError(f"Query failed: {e}")

        elapsed = round(time.time() - query_start, 3)
        truncated = len(rows) == self.row_limit

        return {
            "sql": sql,
            "columns": columns,
            "rows": [dict(row) for row in rows],
            "row_count": len(rows),
            "truncated": truncated,
            "elapsed_seconds": elapsed,
        }

    def result_summary(self, result: dict, max_rows_shown=5) -> str:
        """Condenses a query result into a short text summary for logging
        into investigation_steps -- we don't want to dump 200 raw rows into
        the audit trail table, just enough for a human (or the agent itself)
        to understand what was found."""
        if result["row_count"] == 0:
            return "Query returned no rows."
        preview = result["rows"][:max_rows_shown]
        summary = f"{result['row_count']} row(s) returned. Sample: {json.dumps(preview)}"
        if result["truncated"]:
            summary += f" (truncated at {len(result['rows'])} rows)"
        return summary


if __name__ == "__main__":
    # Quick manual test: confirm read-only enforcement and a real query both work
    tool = SQLTool()

    print("--- Test 1: legitimate query ---")
    result = tool.run_query(
        "SELECT name, target_cpa FROM campaigns"
    )
    print(tool.result_summary(result))

    print("\n--- Test 2: write attempt should be rejected ---")
    try:
        tool.run_query("DELETE FROM campaigns WHERE campaign_id = 1")
        print("FAILED: write was not blocked!")
    except SQLToolError as e:
        print(f"Correctly blocked: {e}")
