-- Campaign Performance Investigator: Core Schema

-- One row per marketing campaign
CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    channel         TEXT NOT NULL,          -- e.g. 'Paid Search', 'Paid Social', 'Email'
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    budget          REAL NOT NULL,
    target_cpa      REAL NOT NULL,          -- target cost-per-acquisition, used to flag underperformance
    target_ctr      REAL NOT NULL           -- target click-through rate
);

-- Daily performance broken down by device + geo + audience segment
-- This granularity is what lets the agent "drill down" during its investigation
CREATE TABLE IF NOT EXISTS campaign_daily_metrics (
    metric_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id     INTEGER NOT NULL REFERENCES campaigns(campaign_id),
    metric_date     TEXT NOT NULL,
    device          TEXT NOT NULL,          -- 'mobile', 'desktop', 'tablet'
    geo             TEXT NOT NULL,          -- region/state code
    segment         TEXT NOT NULL,          -- audience segment, e.g. 'new_visitors', 'returning'
    impressions     INTEGER NOT NULL,
    clicks          INTEGER NOT NULL,
    conversions     INTEGER NOT NULL,
    spend           REAL NOT NULL
);

-- One row per agent investigation into an underperforming campaign
CREATE TABLE IF NOT EXISTS investigations (
    investigation_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id          INTEGER NOT NULL REFERENCES campaigns(campaign_id),
    started_at           TEXT NOT NULL,
    hypothesis           TEXT,
    evidence_json         TEXT,             -- structured evidence supporting the hypothesis
    confidence            REAL,             -- 0.0 - 1.0
    status                TEXT DEFAULT 'pending_review',  -- pending_review, approved, rejected
    reviewed_by           TEXT,
    reviewed_at           TEXT
);

-- Every tool call the agent makes during one investigation
-- This table is what makes the agent's reasoning demonstrable/auditable
CREATE TABLE IF NOT EXISTS investigation_steps (
    step_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id    INTEGER NOT NULL REFERENCES investigations(investigation_id),
    step_number         INTEGER NOT NULL,
    tool_used           TEXT NOT NULL,      -- e.g. 'run_sql_query', 'search_past_investigations'
    input_summary        TEXT,              -- what the agent asked/queried
    result_summary        TEXT,             -- what it found, condensed
    created_at            TEXT NOT NULL
);

-- Vector memory: one embedding per finalized investigation, used to retrieve
-- similar past investigations when a new one is being conducted. Storing
-- vectors as JSON in SQLite is a deliberate MVP choice -- fine at this scale,
-- with a clear upgrade path to a dedicated vector DB (Chroma/Pinecone) if
-- the number of investigations grows large enough that linear scan is slow.
CREATE TABLE IF NOT EXISTS investigation_embeddings (
    investigation_id    INTEGER PRIMARY KEY REFERENCES investigations(investigation_id),
    embedding_json       TEXT NOT NULL,     -- JSON array of floats
    embedded_text         TEXT NOT NULL     -- the text that was embedded, for debugging/display
);
