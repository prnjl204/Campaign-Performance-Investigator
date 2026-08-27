"""
Observability layer: structured (JSON) logging for the agent system.

WHY THIS IS SEPARATE FROM investigation_steps (in persistence.py):
investigation_steps answers "what did the agent conclude and how" -- it's
a permanent business record, read by humans in the dashboard.
This module answers "is the system healthy right now" -- did a query time
out, how long did each step take, did a tool call raise an exception. This
is what you'd wire into Datadog/CloudWatch/ELK in a real deployment. The
two are easy to conflate when you're building solo, but production systems
keep them separate because they have different audiences (a reviewing
analyst vs. an on-call engineer) and different retention needs (keep
investigations forever, roll over logs after 30 days).

WHY JSON LOGS SPECIFICALLY: plain text logs ("Query took 0.4s") are fine
for a human staring at a terminal, but observability platforms parse
structured fields (duration_ms, investigation_id, tool_name) to let you
query "show me every tool call over 2 seconds" or build a dashboard panel.
That query is trivial against JSON logs and painful against plain text.
"""

import logging
import json
import time
import sys
from contextlib import contextmanager
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Renders each log record as one JSON object per line (a common
    convention called 'JSON Lines' / ndjson) -- this is the format most
    log aggregation tools expect for easy parsing."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        # Any extra fields passed via logger.info(..., extra={...}) get
        # merged in -- this is how we attach investigation_id, tool_name,
        # duration_ms, etc. without changing the message string itself.
        standard_fields = set(logging.LogRecord(
            "", 0, "", 0, "", (), None
        ).__dict__.keys())
        extra_fields = {
            k: v for k, v in record.__dict__.items()
            if k not in standard_fields and k not in ("message", "asctime")
        }
        payload.update(extra_fields)
        return json.dumps(payload)


def get_logger(name: str = "campaign_investigator") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # avoid adding duplicate handlers if called more than once

    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    return logger


@contextmanager
def timed_step(logger: logging.Logger, event: str, **context):
    """
    Wraps a block of code, logging its start, successful completion (with
    duration), or failure (with the exception) -- all as structured fields.

    Usage:
        with timed_step(logger, "sql_query", investigation_id=5, tool="run_sql_query"):
            result = tool.run_query(sql)

    This single helper is what gets wrapped around every tool call in the
    agent loop, so every step automatically gets timed and logged the same
    way without repeating boilerplate at each call site.
    """
    start = time.time()
    logger.info(f"{event} started", extra={"event": event, "status": "started", **context})
    try:
        yield
    except Exception as e:
        duration_ms = round((time.time() - start) * 1000, 1)
        logger.error(
            f"{event} failed: {e}",
            extra={"event": event, "status": "failed", "duration_ms": duration_ms,
                   "error": str(e), **context},
        )
        raise
    else:
        duration_ms = round((time.time() - start) * 1000, 1)
        logger.info(
            f"{event} completed",
            extra={"event": event, "status": "completed", "duration_ms": duration_ms, **context},
        )


if __name__ == "__main__":
    # Demonstrates all three outcomes: success, and a caught failure
    logger = get_logger()

    print("--- Test 1: successful timed step ---", file=sys.stderr)
    with timed_step(logger, "sql_query", investigation_id=1, tool="run_sql_query"):
        time.sleep(0.05)  # simulate work

    print("--- Test 2: failed timed step (exception should be logged, then re-raised) ---", file=sys.stderr)
    try:
        with timed_step(logger, "sql_query", investigation_id=1, tool="run_sql_query"):
            raise ValueError("simulated failure for testing")
    except ValueError:
        print("--- Confirmed: exception was re-raised after logging, not swallowed ---", file=sys.stderr)
