"""
Campaign Performance Investigator
Professional Streamlit dashboard for portfolio/demo use.

Run:
    streamlit run src/dashboard.py
"""

import streamlit as st
import json
import sys
import os
from datetime import datetime

# -------------------------------------------------------------------
# PATH SETUP
# -------------------------------------------------------------------

sys.path.insert(0, os.path.dirname(__file__))

from sql_tool import SQLTool
from agent import investigate_campaign
from persistence import (
    save_investigation,
    load_investigation,
    set_review_decision,
)
from detect_underperformance import find_underperforming_campaigns


# -------------------------------------------------------------------
# PAGE CONFIGURATION
# -------------------------------------------------------------------

st.set_page_config(
    page_title="Campaign Performance Investigator",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)


# -------------------------------------------------------------------
# CUSTOM CSS
# -------------------------------------------------------------------

st.markdown(
    """
<style>
/* =========================
GLOBAL
========================= */
.stApp {
background-color: #0e1117;
}
.main {
background-color: #0e1117;
}
/* Reduce top padding */
.block-container {
padding-top: 2rem;
padding-bottom: 3rem;
max-width: 1400px;
}
/* =========================
SIDEBAR
========================= */
section[data-testid="stSidebar"] {
background-color: #11151c;
border-right: 1px solid #252b36;
}
section[data-testid="stSidebar"] .block-container {
padding-top: 2rem;
}
/* =========================
HEADER
========================= */
.brand-container {
padding: 0.5rem 0 1.5rem 0;
}
.brand-title {
font-size: 2rem;
font-weight: 700;
color: #f5f7fa;
margin-bottom: 0.2rem;
letter-spacing: -0.5px;
}
.brand-subtitle {
color: #8b95a5;
font-size: 0.95rem;
}
.eyebrow {
color: #6ea8fe;
font-size: 0.75rem;
font-weight: 700;
letter-spacing: 1.5px;
text-transform: uppercase;
margin-bottom: 0.35rem;
}
/* =========================
CAMPAIGN BANNER
========================= */
.campaign-banner {
background: linear-gradient(
135deg,
#171d27 0%,
#121720 100%
);
border: 1px solid #303846;
border-radius: 14px;
padding: 1.35rem 1.5rem;
margin-bottom: 1.2rem;
}
.campaign-name {
color: #f5f7fa;
font-size: 1.45rem;
font-weight: 650;
}
.campaign-description {
color: #8b95a5;
font-size: 0.9rem;
margin-top: 0.25rem;
}
.alert-pill {
display: inline-block;
background: rgba(255, 107, 107, 0.12);
border: 1px solid rgba(255, 107, 107, 0.30);
color: #ff8c8c;
padding: 0.35rem 0.7rem;
border-radius: 999px;
font-size: 0.72rem;
font-weight: 700;
letter-spacing: 0.5px;
margin-bottom: 0.6rem;
}
/* =========================
KPI CARDS
========================= */
.kpi-card {
background: #151a22;
border: 1px solid #29313d;
border-radius: 12px;
padding: 1.1rem 1.2rem;
min-height: 115px;
}
.kpi-label {
color: #8b95a5;
font-size: 0.78rem;
font-weight: 600;
text-transform: uppercase;
letter-spacing: 0.6px;
}
.kpi-value {
color: #f5f7fa;
font-size: 1.75rem;
font-weight: 700;
margin-top: 0.35rem;
}
.kpi-danger {
color: #ff8c8c;
}
.kpi-warning {
color: #f6c85f;
}
.kpi-success {
color: #6fd08c;
}
.kpi-note {
color: #6f7a8a;
font-size: 0.75rem;
margin-top: 0.25rem;
}
/* =========================
SECTION HEADERS
========================= */
.section-title {
color: #f5f7fa;
font-size: 1.15rem;
font-weight: 650;
margin-top: 1.5rem;
margin-bottom: 0.15rem;
}
.section-description {
color: #7f8998;
font-size: 0.82rem;
margin-bottom: 1rem;
}
/* =========================
FINDING CARD
========================= */
.finding-card {
background: linear-gradient(
135deg,
#18231f 0%,
#131b18 100%
);
border: 1px solid #315343;
border-radius: 14px;
padding: 1.5rem;
margin-top: 0.7rem;
}
.finding-label {
color: #6fd08c;
font-size: 0.72rem;
font-weight: 700;
letter-spacing: 1.3px;
text-transform: uppercase;
}
.finding-title {
color: #f5f7fa;
font-size: 1.2rem;
font-weight: 650;
margin-top: 0.45rem;
line-height: 1.5;
}
.finding-text {
color: #aeb7c4;
font-size: 0.9rem;
line-height: 1.65;
margin-top: 0.7rem;
}
/* =========================
CONFIDENCE
========================= */
.confidence-card {
background: #151a22;
border: 1px solid #29313d;
border-radius: 12px;
padding: 1.25rem;
}
.confidence-number {
color: #6fd08c;
font-size: 2.1rem;
font-weight: 750;
}
.confidence-label {
color: #8b95a5;
font-size: 0.75rem;
text-transform: uppercase;
letter-spacing: 0.8px;
}
.confidence-bar {
width: 100%;
height: 8px;
background: #252c36;
border-radius: 999px;
margin-top: 0.8rem;
overflow: hidden;
}
.confidence-fill {
height: 100%;
background: #6fd08c;
border-radius: 999px;
}
/* =========================
EVIDENCE CARDS
========================= */
.evidence-card {
background: #151a22;
border: 1px solid #29313d;
border-radius: 12px;
padding: 1rem;
min-height: 125px;
}
.evidence-label {
color: #7f8998;
font-size: 0.73rem;
text-transform: uppercase;
letter-spacing: 0.5px;
}
.evidence-value {
color: #f5f7fa;
font-size: 1.4rem;
font-weight: 700;
margin-top: 0.45rem;
}
.evidence-note {
color: #6fd08c;
font-size: 0.75rem;
margin-top: 0.3rem;
}
/* =========================
REASONING / TRACE
========================= */
.trace-step {
display: flex;
gap: 1rem;
padding: 0.9rem 0;
border-bottom: 1px solid #252b34;
}
.trace-number {
min-width: 30px;
height: 30px;
border-radius: 50%;
background: #1d2a3a;
color: #78aefc;
display: flex;
align-items: center;
justify-content: center;
font-size: 0.75rem;
font-weight: 700;
}
.trace-tool {
color: #f0f3f7;
font-weight: 600;
font-size: 0.88rem;
}
.trace-summary {
color: #7f8998;
font-size: 0.78rem;
margin-top: 0.2rem;
line-height: 1.5;
}
/* =========================
HUMAN REVIEW
========================= */
.review-card {
background: linear-gradient(
135deg,
#1b1f28 0%,
#151920 100%
);
border: 1px solid #394251;
border-radius: 14px;
padding: 1.4rem;
margin-top: 0.5rem;
}
.review-title {
color: #f5f7fa;
font-size: 1.05rem;
font-weight: 650;
}
.review-text {
color: #8b95a5;
font-size: 0.82rem;
line-height: 1.55;
margin-top: 0.4rem;
}
/* =========================
SAFETY CARD
========================= */
.safety-card {
background: rgba(110, 168, 254, 0.06);
border: 1px solid rgba(110, 168, 254, 0.18);
border-radius: 10px;
padding: 0.9rem 1rem;
margin-top: 1rem;
}
.safety-title {
color: #78aefc;
font-size: 0.78rem;
font-weight: 700;
}
.safety-text {
color: #7f8998;
font-size: 0.75rem;
line-height: 1.5;
margin-top: 0.25rem;
}
/* =========================
SIDEBAR CAMPAIGN BUTTONS
========================= */
.sidebar-label {
color: #7f8998;
font-size: 0.72rem;
font-weight: 700;
letter-spacing: 1px;
text-transform: uppercase;
}
/* =========================
FOOTER
========================= */
.footer {
text-align: center;
color: #555f6d;
font-size: 0.7rem;
margin-top: 3rem;
padding-top: 1.2rem;
border-top: 1px solid #202631;
}
</style>
""",
    unsafe_allow_html=True,
)


# -------------------------------------------------------------------
# INITIALIZE
# -------------------------------------------------------------------

tool = SQLTool()


# -------------------------------------------------------------------
# HELPER FUNCTIONS
# -------------------------------------------------------------------

def safe_float(value, default=0.0):
    """Safely convert a value to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def format_percent(value):
    """Format decimal as percentage."""
    return f"{safe_float(value) * 100:.1f}%"


def format_evidence_value(key, value):
    """Format evidence values for display."""

    if value is None:
        return "—"

    key_lower = key.lower()

    if isinstance(value, float):

        if "cvr" in key_lower or "rate" in key_lower or "pct" in key_lower:
            return f"{value * 100:.1f}%"

        if "confidence" in key_lower:
            return f"{value:.0%}"

        return f"{value:.4f}"

    return str(value)


def evidence_items(evidence):
    """Create human-readable evidence items."""

    if not isinstance(evidence, dict):
        return []

    items = []

    preferred_keys = [
        "outlier_dimension",
        "outlier_value",
        "drop_pct",
        "changepoint_date",
    ]

    for key in preferred_keys:
        if key in evidence:
            items.append((key, evidence[key]))

    # Add any remaining evidence fields
    for key, value in evidence.items():
        if key == "date_range":
            continue

        if not any(existing_key == key for existing_key, _ in items):
            items.append((key, value))

    return items


def pretty_key(key):
    """Convert technical key into readable label."""

    replacements = {
        "outlier_dimension": "Anomaly Dimension",
        "outlier_value": "Affected Segment",
        "drop_pct": "Conversion Rate Drop",
        "changepoint_date": "Detected Start Date",
    }

    if key in replacements:
        return replacements[key]

    return key.replace("_", " ").title()


# -------------------------------------------------------------------
# SIDEBAR
# -------------------------------------------------------------------

with st.sidebar:

    st.markdown(
        """
<div class="brand-container">
<div class="eyebrow">AI Analytics</div>
<div class="brand-title">Investigator</div>
<div class="brand-subtitle">
Campaign root-cause analysis
</div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="sidebar-label">Flagged Campaigns</div>',
        unsafe_allow_html=True,
    )

    flagged = find_underperforming_campaigns(tool)

    if not flagged:

        st.info("No campaigns are currently above target CPA.")

    else:

        for campaign_item in flagged:

            overage = safe_float(campaign_item.get("overage_pct"))

            label = (
                f"{campaign_item['name']}  "
                f"·  +{overage:.0%}"
            )

            if st.button(
                label,
                key=f"investigate_{campaign_item['campaign_id']}",
                use_container_width=True,
            ):
                st.session_state["selected_campaign"] = campaign_item

    st.divider()

    st.markdown(
        """
<div class="safety-card">
<div class="safety-title">🛡 Human-in-the-loop</div>
<div class="safety-text">
The agent investigates and reports findings.
It cannot change campaign budgets, pause campaigns,
modify targeting, or contact anyone.
</div>
</div>
""",
        unsafe_allow_html=True,
    )


# -------------------------------------------------------------------
# HEADER
# -------------------------------------------------------------------

st.markdown(
    """
<div class="brand-container">
<div class="eyebrow">Marketing Intelligence · Root Cause Analysis</div>
<div class="brand-title">
Campaign Performance Investigator
</div>
<div class="brand-subtitle">
An AI agent that investigates why campaigns miss their
performance targets — with evidence, validation, and human review.
</div>
</div>
""",
    unsafe_allow_html=True,
)


# -------------------------------------------------------------------
# NO CAMPAIGN SELECTED
# -------------------------------------------------------------------

if "selected_campaign" not in st.session_state:

    st.markdown(
        """
<div class="campaign-banner">
<div class="alert-pill">ACTION REQUIRED</div>
<div class="campaign-name">
Select an underperforming campaign
</div>
<div class="campaign-description">
Choose a flagged campaign from the sidebar to begin
an agent-led root-cause investigation.
</div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.stop()


# -------------------------------------------------------------------
# SELECTED CAMPAIGN
# -------------------------------------------------------------------

campaign = st.session_state["selected_campaign"]

target_cpa = safe_float(campaign.get("target_cpa"))
actual_cpa = safe_float(campaign.get("actual_cpa"))
overage_pct = safe_float(campaign.get("overage_pct"))
conversions = int(safe_float(campaign.get("total_conversions")))


# -------------------------------------------------------------------
# CAMPAIGN BANNER
# -------------------------------------------------------------------

st.markdown(
    f"""
<div class="campaign-banner">
<div class="alert-pill">⚠ UNDERPERFORMING</div>
<div class="campaign-name">
{campaign['name']}
</div>
<div class="campaign-description">
Campaign ID {campaign['campaign_id']}
· Investigation triggered because actual CPA exceeds target.
</div>
</div>
""",
    unsafe_allow_html=True,
)


# -------------------------------------------------------------------
# KPI CARDS
# -------------------------------------------------------------------

k1, k2, k3, k4 = st.columns(4)

with k1:
    st.markdown(
        f"""
<div class="kpi-card">
<div class="kpi-label">Target CPA</div>
<div class="kpi-value">${target_cpa:.2f}</div>
<div class="kpi-note">Performance target</div>
</div>
""",
        unsafe_allow_html=True,
    )

with k2:
    st.markdown(
        f"""
<div class="kpi-card">
<div class="kpi-label">Actual CPA</div>
<div class="kpi-value kpi-danger">${actual_cpa:.2f}</div>
<div class="kpi-note">Current performance</div>
</div>
""",
        unsafe_allow_html=True,
    )

with k3:
    st.markdown(
        f"""
<div class="kpi-card">
<div class="kpi-label">CPA Overage</div>
<div class="kpi-value kpi-danger">+{overage_pct:.0%}</div>
<div class="kpi-note">Above target</div>
</div>
""",
        unsafe_allow_html=True,
    )

with k4:
    st.markdown(
        f"""
<div class="kpi-card">
<div class="kpi-label">Conversions</div>
<div class="kpi-value">{conversions:,}</div>
<div class="kpi-note">Attributed conversions</div>
</div>
""",
        unsafe_allow_html=True,
    )


# -------------------------------------------------------------------
# RUN INVESTIGATION
# -------------------------------------------------------------------

st.markdown(
    """
<div class="section-title">Investigation Control</div>
<div class="section-description">
Let the agent query campaign data, investigate anomalies,
validate findings, and produce an evidence-backed hypothesis.
</div>
""",
    unsafe_allow_html=True,
)

run_col1, run_col2 = st.columns([1, 4])

with run_col1:

    run_clicked = st.button(
        "▶  Run Investigation",
        type="primary",
        use_container_width=True,
    )

if run_clicked:

    progress = st.progress(0)

    status = st.empty()

    try:

        status.info("Agent is starting the investigation...")
        progress.progress(10)

        investigation = investigate_campaign(
            tool,
            campaign["campaign_id"],
            campaign["name"],
        )

        progress.progress(80)

        status.info("Saving investigation results...")

        inv_id = save_investigation(investigation)

        progress.progress(100)

        st.session_state["last_investigation_id"] = inv_id

        status.success("Investigation completed successfully.")

        st.rerun()

    except Exception as error:

        progress.empty()

        st.error(
            f"Investigation failed: {error}"
        )

        st.stop()


# -------------------------------------------------------------------
# INVESTIGATION RESULTS
# -------------------------------------------------------------------

if "last_investigation_id" not in st.session_state:

    st.markdown(
        """
<div class="safety-card">
<div class="safety-title">
Ready to investigate
</div>
<div class="safety-text">
Start the investigation to see the agent's reasoning trace,
supporting evidence, confidence score, and final hypothesis.
</div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.stop()


# -------------------------------------------------------------------
# LOAD INVESTIGATION
# -------------------------------------------------------------------

inv = load_investigation(
    st.session_state["last_investigation_id"]
)

if not inv:

    st.error("Unable to load the investigation.")

    st.stop()


# -------------------------------------------------------------------
# INVESTIGATION TRACE
# -------------------------------------------------------------------

st.markdown(
    """
<div class="section-title">Agent Investigation Trace</div>
<div class="section-description">
A transparent record of the steps the agent took to investigate
the campaign's underperformance.
</div>
""",
    unsafe_allow_html=True,
)


steps = inv.get("steps", [])

if steps:

    trace_html = ""

    for step in steps:

        step_number = step.get("step_number", "?")
        tool_used = step.get("tool_used", "Unknown tool")
        input_summary = step.get("input_summary", "")
        result_summary = step.get("result_summary", "")

        trace_html += f"""
<div class="trace-step">
<div class="trace-number">
{step_number}
</div>
<div>
<div class="trace-tool">
✓ {tool_used}
</div>
<div class="trace-summary">
{input_summary[:180]}
</div>
</div>
</div>
"""

    st.markdown(
        trace_html,
        unsafe_allow_html=True,
    )

    # Detailed tool results
    with st.expander("View detailed investigation results"):

        for step in steps:

            st.markdown(
                f"**Step {step.get('step_number')} — "
                f"{step.get('tool_used', 'Unknown')}**"
            )

            st.caption(
                step.get("input_summary", "")
            )

            st.code(
                step.get("result_summary", ""),
                language="text",
            )

else:

    st.info("No investigation steps were recorded.")


# -------------------------------------------------------------------
# CONCLUSION SECTION
# -------------------------------------------------------------------

st.markdown(
    """
<div class="section-title">Primary Finding</div>
<div class="section-description">
The agent's current best explanation, based on the evidence
collected during the investigation.
</div>
""",
    unsafe_allow_html=True,
)


confidence = safe_float(inv.get("confidence"))

if confidence >= 0.8:
    confidence_label = "High confidence"
elif confidence >= 0.6:
    confidence_label = "Moderate confidence"
else:
    confidence_label = "Low confidence"


hypothesis = inv.get(
    "hypothesis",
    "No hypothesis was generated."
)


st.markdown(
    f"""
<div class="finding-card">
<div class="finding-label">
🔎 Agent Hypothesis
</div>
<div class="finding-title">
{hypothesis}
</div>
<div class="finding-text">
This is an evidence-backed hypothesis, not an automatic
business decision. A human analyst should review the evidence
before taking action.
</div>
</div>
""",
    unsafe_allow_html=True,
)


# -------------------------------------------------------------------
# CONFIDENCE
# -------------------------------------------------------------------

confidence_col, spacer = st.columns([1, 2])

with confidence_col:

    st.markdown(
        f"""
<div class="confidence-card">
<div class="confidence-label">
Agent confidence
</div>
<div class="confidence-number">
{confidence:.0%}
</div>
<div style="color:#8b95a5;font-size:0.78rem;">
{confidence_label}
</div>
<div class="confidence-bar">
<div
class="confidence-fill"
style="width:{max(0, min(100, confidence * 100))}%;">
</div>
</div>
</div>
""",
        unsafe_allow_html=True,
    )


# -------------------------------------------------------------------
# EVIDENCE
# -------------------------------------------------------------------

st.markdown(
    """
<div class="section-title">Supporting Evidence</div>
<div class="section-description">
Key observations used by the agent to support its hypothesis.
</div>
""",
    unsafe_allow_html=True,
)


evidence = {}

if inv.get("evidence_json"):

    try:

        evidence = json.loads(
            inv["evidence_json"]
        )

    except (json.JSONDecodeError, TypeError):

        evidence = {}


items = evidence_items(evidence)


if items:

    # Display first 6 pieces of evidence as cards
    display_items = items[:6]

    columns = st.columns(
        min(len(display_items), 3)
    )

    for index, (key, value) in enumerate(display_items):

        with columns[index % len(columns)]:

            formatted_value = format_evidence_value(
                key,
                value,
            )

            note = ""

            if "post" in key.lower():

                note = "Post-anomaly period"

            elif "pre" in key.lower():

                note = "Baseline period"

            elif "drop" in key.lower():

                note = "Magnitude of the anomaly"

            elif "desktop" in key.lower():

                note = "Comparison segment"

            elif "tablet" in key.lower():

                note = "Comparison segment"

            elif "changepoint" in key.lower():

                note = "When the drop started"

            elif key.lower() == "outlier_dimension":

                note = "Where the issue was found"

            elif key.lower() == "outlier_value":

                note = "Specific segment affected"

            st.markdown(
                f"""
<div class="evidence-card">
<div class="evidence-label">
{pretty_key(key)}
</div>
<div class="evidence-value">
{formatted_value}
</div>
<div class="evidence-note">
{note}
</div>
</div>
""",
                unsafe_allow_html=True,
            )


    # Full evidence
    with st.expander("View complete structured evidence"):

        st.json(evidence)

else:

    st.info(
        "No structured evidence was stored for this investigation."
    )


# -------------------------------------------------------------------
# ANALYST INTERPRETATION
# -------------------------------------------------------------------

st.markdown(
    """
<div class="section-title">Why This Finding Matters</div>
<div class="section-description">
Separate the evidence from the hypothesis so analysts can
understand what is known versus what is inferred.
</div>
""",
    unsafe_allow_html=True,
)


st.markdown(
    f"""
<div class="finding-card">
<div class="finding-label">
Evidence → Interpretation
</div>
<div class="finding-text">
<strong style="color:#f5f7fa;">
What the agent observed:
</strong>
The investigation identified a measurable performance
difference across campaign segments and investigated the
timing of that change.
<br><br>
<strong style="color:#f5f7fa;">
What the agent inferred:
</strong>
The strongest explanation is the hypothesis shown above.
<br><br>
<strong style="color:#f5f7fa;">
What remains uncertain:
</strong>
The agent does not have direct access to website,
engineering, creative, or external operational systems,
so the underlying root cause still requires human validation.
</div>
</div>
""",
    unsafe_allow_html=True,
)


# -------------------------------------------------------------------
# HUMAN REVIEW
# -------------------------------------------------------------------

st.markdown(
    """
<div class="section-title">Human Review</div>
<div class="section-description">
The agent recommends. The analyst decides.
</div>
""",
    unsafe_allow_html=True,
)


status = inv.get("status", "pending_review")


if status == "pending_review":

    st.markdown(
        """
<div class="review-card">
<div class="review-title">
👤 Analyst approval required
</div>
<div class="review-text">
Review the investigation trace, evidence, and hypothesis.
Approving this finding only records the analyst's decision.
No campaign settings, budgets, targeting, or spend are changed.
</div>
</div>
""",
        unsafe_allow_html=True,
    )

    reviewer = st.text_input(
        "Reviewer name",
        value="analyst",
    )

    approve_col, reject_col = st.columns(2)

    with approve_col:

        if st.button(
            "✅  Approve Finding",
            type="primary",
            use_container_width=True,
        ):

            set_review_decision(
                inv["investigation_id"],
                "approved",
                reviewer,
            )

            st.success(
                "Finding approved and recorded. "
                "No automatic campaign action was taken."
            )

            st.rerun()

    with reject_col:

        if st.button(
            "↩  Reject / Needs More Investigation",
            use_container_width=True,
        ):

            set_review_decision(
                inv["investigation_id"],
                "rejected",
                reviewer,
            )

            st.warning(
                "Finding rejected and recorded for follow-up."
            )

            st.rerun()

else:

    review_status = status.upper()

    st.markdown(
        f"""
<div class="review-card">
<div class="review-title">
Review completed
</div>
<div class="review-text">
Status:
<strong style="color:#f5f7fa;">
{review_status}
</strong>
<br>
Reviewer:
<strong style="color:#f5f7fa;">
{inv.get("reviewed_by", "Unknown")}
</strong>
<br>
Reviewed at:
<strong style="color:#f5f7fa;">
{inv.get("reviewed_at", "Unknown")}
</strong>
</div>
</div>
""",
        unsafe_allow_html=True,
    )


# -------------------------------------------------------------------
# SAFETY BOUNDARY
# -------------------------------------------------------------------

st.markdown(
    """
<div class="safety-card">
<div class="safety-title">
🛡 System safety boundary
</div>
<div class="safety-text">
This system is intentionally read-only with respect to
campaign operations. The agent can analyze data, generate
findings, save investigations, and request human review.
It cannot pause campaigns, change budgets, modify targeting,
launch ads, or contact external users automatically.
</div>
</div>
""",
    unsafe_allow_html=True,
)


# -------------------------------------------------------------------
# FOOTER
# -------------------------------------------------------------------

st.markdown(
    """
<div class="footer">
Campaign Performance Investigator · Agentic Analytics Demo
· Evidence-backed investigation · Human-in-the-loop
</div>
""",
    unsafe_allow_html=True,
)
