# Campaign Performance Investigator

An agent that investigates *why* a marketing campaign is underperforming —
not a chatbot, not a dashboard. Given a campaign that's over its target
CPA, it plans an investigation, queries the data itself, adapts its
approach when an initial query is inconclusive, validates its own
conclusion, and hands a marketing analyst an evidence-backed hypothesis to
approve — it never changes spend, pauses a campaign, or contacts anyone
on its own.

Built as a portfolio project to demonstrate agentic AI system design for
Data Analyst / AI Engineer roles: multi-step planning, tool selection,
self-validation, vector memory (RAG), structured logging, and a real
evaluation suite with a measured accuracy result — not just "it worked
when I tried it."

## The problem it solves

Marketing/analytics teams routinely burn analyst hours manually
drilling into "why did this campaign underperform" — checking device
breakdowns, geo breakdowns, time trends, one query at a time. This agent
automates *the investigation*, not the decision: it does the tedious
multi-step SQL digging and hands a human a ranked hypothesis with
evidence, so the analyst's time goes to judgment, not query-writing.

## Architecture

```
flowchart TD
    A[Underperforming campaign flagged] --> B[Agent: check device breakdown]
    B --> C{Outlier found?}
    C -- No, full range inconclusive --> D[Narrow time window and retry]
    D --> C
    C -- Still no --> E[Agent: check geo breakdown]
    E --> C
    C -- Yes --> F[Drill into WHEN the drop started]
    F --> G[Validate: confirm other segments stayed healthy]
    G --> H[Check vector memory: similar past investigations?]
    H --> I[Form hypothesis + confidence score]
    I --> J[Save to investigations table]
    J --> K[Human review: Approve / Reject]
    K -.no automatic action.-> L((Done))
```

## What makes this genuinely agentic (not just a script)

- **Plans multi-step**: decides which dimension to check first, and
whether to keep digging based on what it finds
- **Adapts to inconclusive results**: when a full-range average hides an
anomaly (diluted by healthy days before the issue started), it narrows
the time window and retries — this exact gap was found and fixed via
the evaluation suite (see `eval/EVALUATION_REPORT.md`)
- **Chooses between tools**: device breakdown, geo breakdown, time trend,
and vector memory search are all available; which ones get used depends
on what earlier steps found
- **Validates its own conclusion** before finalizing, rather than
reporting the first pattern it notices
- **Uses memory**: retrieves similar past investigations via a vector
store, so recurring patterns get recognized instead of re-investigated
from scratch
- **Human-in-the-loop by design**: the agent's only possible outputs are
a report and a database write to its own findings table — it has no
code path that can change a campaign, spend, or notify anyone

## Tech stack

| Layer               | Technology                                                  | Why                                                                                                                                                                       |
| -------------------- | ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Data                 | SQLite (schema in `src/schema.sql`)                          | Real multi-table relational data — campaigns, daily metrics, investigations, audit trail, embeddings                                                                     |
| Agent orchestration  | Hand-rolled Python state machine (`src/agent.py`)             | No network access in dev sandbox to install LangGraph — this implements the same plan/act/observe/adapt idea directly; `src/agent_gemini.py` has a real Gemini function-calling version to run with API access |
| LLM integration      | Google Gemini API, function calling (`src/agent_gemini.py`)   | Real model-driven investigation instead of fixed rules                                                                                                                    |
| Memory / RAG         | TF-IDF + cosine similarity (`src/memory.py`)                  | Fully local, zero-dependency vector search; swap `_embed_texts()` for a real embedding API to upgrade                                                                    |
| Dashboard            | Streamlit (`src/dashboard.py`)                                | Shows the live investigation trace + human approval flow                                                                                                                  |
| Observability        | Structured JSON logging (`src/observability.py`)              | Every SQL query timed and logged, separate from the business-record audit trail                                                                                          |
| Deployment           | Docker + docker-compose                                       | Self-seeding container, persistent named volume for the database                                                                                                         |
| Evaluation           | Custom eval harness (`eval/`)                                 | 8 synthetic ground-truth scenarios, scored for dimension/value accuracy and false positive rate                                                                          |

## Evaluation results

**100% dimension accuracy, 100% exact-value accuracy, 0 false positives,
0 false negatives** across 8 synthetic ground-truth scenarios (device and
geo anomalies of varying severity, plus healthy controls).

The first run scored 75% — full details on the bug that caused it, the
fix, and known limitations are in **`eval/EVALUATION_REPORT.md`**. That
file is worth reading before an interview: it documents a real gap found
by testing, not just a final number.

**The Gemini-driven agent has also been run end-to-end** against the
seeded demo data. Given a campaign flagged as over target CPA, it
independently planned and executed an 8-step investigation — checking
the campaign date range, device breakdown, geo breakdown, overall time
trend, then per-device time trends, and finally a device breakdown
filtered to the second half of the month — before producing a hypothesis:
a mobile-specific conversion-rate collapse (from ~6.0% to ~1.0%) starting
on a specific date, with desktop and tablet performance staying stable
throughout. It returned this with a 0.98 confidence score and the
supporting evidence numbers, matching the anomaly planted in the seed
data.

## Project structure

```
campaign-investigator/
├── src/
│   ├── schema.sql                  # 5-table schema
│   ├── generate_seed_data.py       # synthetic demo data w/ planted anomaly
│   ├── sql_tool.py                 # read-only, audited SQL execution tool
│   ├── detect_underperformance.py  # flags campaigns over target CPA
│   ├── agent.py                    # deterministic investigation loop
│   ├── agent_gemini.py             # real Gemini function-calling version
│   ├── persistence.py              # saves/loads investigations + human review
│   ├── memory.py                   # vector memory / RAG over past investigations
│   ├── observability.py            # structured JSON logging
│   └── dashboard.py                # Streamlit UI
├── eval/
│   ├── generate_eval_dataset.py    # independent ground-truth test scenarios
│   ├── run_evaluation.py           # scores agent against ground truth
│   └── EVALUATION_REPORT.md        # results + honest limitations
├── data/campaigns.db               # demo database (auto-generated if missing)
├── Dockerfile / docker-compose.yml / entrypoint.sh
└── requirements.txt
```

## Running it

**Quickest (Docker):**

```
docker compose up --build
```

Open `http://localhost:8501`.

**Locally:**

```
pip install -r requirements.txt
python src/generate_seed_data.py    # only needed once
streamlit run src/dashboard.py
```

**Run the evaluation suite:**

```
python eval/generate_eval_dataset.py
python eval/run_evaluation.py
```

**Run the real LLM-driven agent** (needs a Gemini API key):

```
export GEMINI_API_KEY=your_key_here   # PowerShell: $env:GEMINI_API_KEY="your_key_here"
python src/agent_gemini.py
```

## What I'd build next

- Multi-dimensional anomaly detection (e.g. mobile *and* a specific geo
together)
- Real embedding-based memory (Voyage AI or OpenAI)
- Slack/email drafting for approved findings (still requiring a human
send action, never automatic)
- Run `agent_gemini.py` through the full eval suite (not just the one
scenario above) to directly quantify what real reasoning adds over
fixed heuristics
