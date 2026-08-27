"""
Vector memory / RAG layer: lets the agent ask "have we seen a pattern like
this before?" by embedding each finalized investigation's hypothesis text
and retrieving the most similar past ones via cosine similarity.

IMPORTANT HONEST NOTE ON THE EMBEDDING METHOD:
This uses TF-IDF (scikit-learn), not a real semantic embedding model, because
this sandbox has no network access to call an embedding API (Voyage AI,
OpenAI, etc). TF-IDF matches on shared vocabulary ("mobile", "conversion",
"checkout") rather than true semantic meaning -- it will correctly find
"mobile conversion collapse" investigations as similar to each other, but
won't understand that "checkout page bug" and "purchase flow broken" mean
almost the same thing if they share few words.

This is a legitimate MVP choice to say out loud in an interview: it's fully
explainable, has zero external dependencies, and costs nothing to run --
but you should describe the upgrade path too: swap `_embed_texts()` below
for a call to a real embedding API, and everything else in this file
(storage, retrieval, cosine similarity) stays the same. That's the value of
having designed this behind a small interface in the first place.
"""

import json
import sqlite3
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def _embed_texts(texts: list[str]) -> np.ndarray:
    """
    Turns a list of texts into vectors. Swap this function's body for a real
    embedding API call (e.g. Voyage AI's client.embed(texts)) to upgrade to
    true semantic search -- nothing else in this file needs to change.
    """
    vectorizer = TfidfVectorizer(stop_words="english", max_features=200)
    matrix = vectorizer.fit_transform(texts)
    return matrix.toarray()


def store_investigation_embedding(investigation_id: int, text: str, db_path="data/campaigns.db"):
    """
    Embeds and stores one investigation's text. Note: because TF-IDF vectors
    are only meaningful relative to a fixed vocabulary, we re-embed ALL past
    investigations together each time rather than embedding one in isolation
    -- this is a real limitation of TF-IDF vs. real embedding models (which
    embed each text independently). Worth mentioning as a known trade-off.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        existing = conn.execute(
            "SELECT investigation_id, embedded_text FROM investigation_embeddings"
        ).fetchall()

        all_ids = [row["investigation_id"] for row in existing] + [investigation_id]
        all_texts = [row["embedded_text"] for row in existing] + [text]

        embeddings = _embed_texts(all_texts)

        conn.execute("DELETE FROM investigation_embeddings")
        for inv_id, txt, vec in zip(all_ids, all_texts, embeddings):
            conn.execute(
                "INSERT INTO investigation_embeddings (investigation_id, embedding_json, embedded_text) "
                "VALUES (?, ?, ?)",
                (inv_id, json.dumps(vec.tolist()), txt),
            )
        conn.commit()
    finally:
        conn.close()


def find_similar_past_investigations(query_text: str, top_k: int = 3, db_path="data/campaigns.db",
                                       exclude_investigation_id: int | None = None) -> list[dict]:
    """
    Finds the top_k most similar past investigations to query_text.
    Returns empty list if there's no memory yet -- the agent should treat
    "no similar cases found" as a normal, valid outcome, not an error.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT e.investigation_id, e.embedded_text, e.embedding_json,
                   i.hypothesis, i.confidence, i.status
            FROM investigation_embeddings e
            JOIN investigations i ON i.investigation_id = e.investigation_id
            """
        ).fetchall()
    finally:
        conn.close()

    candidates = [r for r in rows if r["investigation_id"] != exclude_investigation_id]
    if not candidates:
        return []

    # Re-embed query alongside stored texts so they share the same TF-IDF
    # vocabulary space -- a real embedding model wouldn't need this step.
    all_texts = [c["embedded_text"] for c in candidates] + [query_text]
    embeddings = _embed_texts(all_texts)
    query_vec = embeddings[-1].reshape(1, -1)
    candidate_vecs = embeddings[:-1]

    similarities = cosine_similarity(query_vec, candidate_vecs)[0]

    ranked = sorted(zip(candidates, similarities), key=lambda pair: pair[1], reverse=True)

    results = []
    for candidate, score in ranked[:top_k]:
        results.append({
            "investigation_id": candidate["investigation_id"],
            "hypothesis": candidate["hypothesis"],
            "confidence": candidate["confidence"],
            "status": candidate["status"],
            "similarity": round(float(score), 3),
        })
    return results


if __name__ == "__main__":
    from sql_tool import SQLTool
    from agent import investigate_campaign
    from persistence import save_investigation

    tool = SQLTool()

    # Simulate memory building up: save a few past investigations with
    # varied hypotheses so retrieval has something meaningful to distinguish.
    past_hypotheses = [
        "Mobile conversion rate dropped sharply starting mid-month due to a checkout page bug on mobile devices only.",
        "Overall CTR declined due to creative fatigue after three weeks of the same ad creative running.",
        "Geo segment TX underperformed due to a regional competitor promotion during the same window.",
    ]

    for i, hyp in enumerate(past_hypotheses, start=1):
        conn = sqlite3.connect("data/campaigns.db")
        cur = conn.execute(
            "INSERT INTO investigations (campaign_id, started_at, hypothesis, confidence, status) "
            "VALUES (1, '2026-05-01T00:00:00', ?, 0.8, 'approved')",
            (hyp,),
        )
        inv_id = cur.lastrowid
        conn.commit()
        conn.close()
        store_investigation_embedding(inv_id, hyp)

    # Now run a REAL investigation on campaign 3 and see if memory correctly
    # surfaces the "mobile checkout bug" past case as most similar -- this is
    # the actual functional test of whether retrieval works, not just whether
    # the code runs without errors.
    investigation = investigate_campaign(tool, campaign_id=3, campaign_name="Summer Sale - Paid Social")
    new_inv_id = save_investigation(investigation)
    store_investigation_embedding(new_inv_id, investigation.hypothesis)

    print(f"New investigation hypothesis:\n  {investigation.hypothesis}\n")
    print("Most similar past investigations:")
    similar = find_similar_past_investigations(investigation.hypothesis, top_k=3,
                                                 exclude_investigation_id=new_inv_id)
    for s in similar:
        print(f"  [{s['similarity']:.2f}] (#{s['investigation_id']}) {s['hypothesis']}")
