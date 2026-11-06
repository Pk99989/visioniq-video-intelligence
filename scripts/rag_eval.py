#!/usr/bin/env python3
"""RAG evaluation (Phase 4): 50+ questions over the three sample
videos, measured for two retrieval configs side by side.

- baseline: DB scan only (QDRANT_URL empty), no reranker — the v0.3.x
  behaviour (Qdrant was write-only).
- new: Qdrant read path (live server) + cross-encoder reranker when
  the model is available.

Metrics (all defined in the report):
- Recall@1 / Recall@5: share of positive questions whose expected
  video + timestamp (±2 s) is at rank 1 / in the top 5.
- Precision@5: share of top-5 hits that are correct.
- MRR: mean reciprocal rank of the first correct hit (0 if none).
- Mean retrieval latency (ms).
- Faithfulness: share of answers whose citations all resolve to real
  stored frames (validate_citations).
- Relevance: positives whose answer contains an expected keyword;
  negatives correctly answered with "No video evidence".
- Negatives correct: share of negative questions the system refuses
  (no hits above the agent's 0.45 floor).

Corpus: the three sample videos, processed once with the configured
VLM (default Ollama/moondream — real captions; set VLM_PROVIDER=
fallback for detection-tier captions). Embeddings: hash by default,
fastembed with EMBEDDING_PROVIDER=fastembed.

Usage:
    cd backend && python ../scripts/rag_eval.py
    # reranker on: RERANKER_MODEL=Xenova/ms-marco-MiniLM-L-6-v2 python ../scripts/rag_eval.py
    # Qdrant for the "new" run: QDRANT_URL=http://localhost:6333 python ../scripts/rag_eval.py
Writes docs/benchmarks/rag-eval-<date>.md.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("SYNC_PROCESSING", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/rag-eval/test.db")
os.environ.setdefault("STORAGE_DIR", "/tmp/rag-eval/storage")
os.environ.setdefault("JWT_SECRET", "rag-eval-secret")
os.environ.setdefault("EMBEDDING_PROVIDER", os.environ.get("EMBEDDING_PROVIDER", "hash"))
os.environ.setdefault("VLM_PROVIDER", os.environ.get("VLM_PROVIDER", "ollama"))
os.environ.setdefault("VLM_MODEL", os.environ.get("VLM_MODEL", "moondream"))
os.environ.setdefault("VLM_BASE_URL", "http://localhost:11434/v1")
os.environ.setdefault("VLM_TIMEOUT_SECONDS", "300")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

REPO = Path(__file__).resolve().parent.parent
YOUR_FILES = Path.home() / "workspace" / "your_files"
VIDEOS = {
    "bus": YOUR_FILES / "sample-video-bus.mp4",
    "moving": YOUR_FILES / "sample-video-moving.mp4",
    "advanced": YOUR_FILES / "sample-video-advanced.mp4",
}
DATASET = REPO / "backend" / "tests" / "data" / "rag_eval.jsonl"
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")


def _load_dataset():
    return [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]


def _build_corpus(client, headers):
    """Upload the three videos; return {name: video_id}. Fails loudly
    if the configured VLM produced no real captions (a silent
    fallback would measure the wrong corpus) or if Qdrant is
    unreachable when the new config needs it."""
    from app.database import SessionLocal
    from app.models import Caption

    ids = {}
    for name, path in VIDEOS.items():
        with open(path, "rb") as f:
            r = client.post("/api/v1/videos/upload", headers=headers,
                            data={"title": f"eval-{name}"},
                            files={"file": (f"{name}.mp4", f, "video/mp4")})
        assert r.status_code == 201 and r.json()["status"] == "ready", r.text
        ids[name] = r.json()["id"]
        print(f"  corpus {name}: video {ids[name]} ready", flush=True)
    db = SessionLocal()
    providers = {}
    for cap in db.query(Caption).filter(Caption.video_id.in_(ids.values())).all():
        providers[cap.provider] = providers.get(cap.provider, 0) + 1
    db.close()
    print(f"  caption providers in corpus: {providers}")
    if os.environ["VLM_PROVIDER"] == "ollama" and "ollama" not in providers:
        raise SystemExit(
            "ERROR: VLM_PROVIDER=ollama but no caption has provider 'ollama' — "
            "Ollama is unreachable and the corpus fell back to templates. "
            "Start Ollama first, then re-run.")
    return ids, providers


def _is_correct(hit, item, video_ids):
    return (hit["video_id"] == video_ids[item["video"]]
            and abs(hit["timestamp_seconds"] - item["timestamp"]) <= 2.0)


def _run_config(db, user_id, video_ids, items, use_qdrant, use_rerank, label):
    from app.config import settings
    from app.services import agent
    from app.services.retrieval import search_frames, validate_citations

    settings.QDRANT_URL = QDRANT_URL if use_qdrant else ""
    settings.RERANKER_MODEL = RERANKER_MODEL if use_rerank else ""
    positives = [i for i in items if i["type"] == "positive"]
    negatives = [i for i in items if i["type"] == "negative"]
    r1 = r5 = prec_sum = mrr_sum = 0
    latencies = []
    faithful = 0
    relevant_pos = 0
    negatives_ok = 0
    details = []
    for item in items:
        t0 = time.perf_counter()
        hits = search_frames(db, item["question"], top_k=5, user_id=user_id,
                             rerank=use_rerank)
        latencies.append((time.perf_counter() - t0) * 1000)
        result = agent.answer_question(db, item["question"], user_id=user_id)
        cites_ok = validate_citations(db, result.get("citations") or []) == (result.get("citations") or [])
        if cites_ok:
            faithful += 1
        answer = (result.get("answer") or "").lower()
        if item["type"] == "positive":
            correct_ranks = [i + 1 for i, h in enumerate(hits)
                             if _is_correct(h, item, video_ids)]
            if 1 in correct_ranks:
                r1 += 1
            if correct_ranks:
                r5 += 1
                mrr_sum += 1.0 / correct_ranks[0]
            prec_sum += (sum(1 for h in hits if _is_correct(h, item, video_ids))
                         / max(len(hits), 1))
            if any(kw.lower() in answer for kw in item["expected_keywords"]):
                relevant_pos += 1
        else:
            # Correct refusal: no hits above the agent floor, or the
            # agent says it has no evidence.
            if not hits or "no video evidence" in answer:
                negatives_ok += 1
        details.append({"id": item["id"], "type": item["type"],
                        "top1": hits[0]["score"] if hits else None,
                        "answer_start": (result.get("answer") or "")[:120]})
    n_pos = max(len(positives), 1)
    return {
        "config": label,
        "recall_at_1": round(r1 / n_pos, 2),
        "recall_at_5": round(r5 / n_pos, 2),
        "precision_at_5": round(prec_sum / n_pos, 2),
        "mrr": round(mrr_sum / n_pos, 2),
        "mean_latency_ms": round(sum(latencies) / len(latencies), 1),
        "faithfulness": round(faithful / len(items), 2),
        "relevance_positives": round(relevant_pos / n_pos, 2),
        "negatives_correct": round(negatives_ok / max(len(negatives), 1), 2),
        "n_questions": len(items), "n_positive": len(positives),
        "n_negative": len(negatives),
    }


def main():
    for p in ("/tmp/rag-eval/test.db", "/tmp/rag-eval/storage"):
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.exists(p):
            os.remove(p)
    from fastapi.testclient import TestClient  # noqa: E402

    from app.database import SessionLocal  # noqa: E402
    from app.main import app  # noqa: E402
    from app.models import User  # noqa: E402

    items = _load_dataset()
    print(f"Dataset: {len(items)} questions "
          f"({sum(1 for i in items if i['type'] == 'positive')} positive, "
          f"{sum(1 for i in items if i['type'] == 'negative')} negative)")
    client = TestClient(app, raise_server_exceptions=False)
    client.post("/api/v1/auth/register",
                json={"email": "eval@test.com", "password": "password123"})
    r = client.post("/api/v1/auth/login",
                    json={"email": "eval@test.com", "password": "password123"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    print("Building corpus (VLM captions, this takes a few minutes on CPU)...")
    t0 = time.monotonic()
    video_ids, providers = _build_corpus(client, headers)
    print(f"Corpus ready in {time.monotonic() - t0:.0f}s: {video_ids}")

    db = SessionLocal()
    user_id = db.query(User).filter_by(email="eval@test.com").first().id

    print("Running A: baseline (DB scan, no reranker)...")
    results = {}
    results["A: DB scan, no rerank"] = _run_config(
        db, user_id, video_ids, items, use_qdrant=False, use_rerank=False,
        label="A: DB scan, no rerank")
    print("Running B: DB scan + reranker...")
    results["B: DB scan + rerank"] = _run_config(
        db, user_id, video_ids, items, use_qdrant=False, use_rerank=True,
        label="B: DB scan + rerank")
    # The "new" run needs a live Qdrant: without it, search silently
    # falls back to the DB scan and the comparison is meaningless.
    # urllib, not httpx: httpx chokes on this VM's bracketed IPv6
    # NO_PROXY entries (InvalidURL: Invalid port ':1]').
    import urllib.request as _urlopen
    try:
        with _urlopen.urlopen(QDRANT_URL.rstrip("/") + "/", timeout=5) as resp:
            resp.read()
    except Exception as exc:
        raise SystemExit(f"ERROR: Qdrant unreachable at {QDRANT_URL} ({exc}) — "
                         "start Qdrant first, then re-run.") from exc
    print("Running C: Qdrant read path, no reranker...")
    results["C: Qdrant, no rerank"] = _run_config(
        db, user_id, video_ids, items, use_qdrant=True, use_rerank=False,
        label="C: Qdrant, no rerank")
    print("Running D: Qdrant read path + reranker...")
    results["D: Qdrant + rerank"] = _run_config(
        db, user_id, video_ids, items, use_qdrant=True, use_rerank=True,
        label="D: Qdrant + rerank")
    db.close()

    date = time.strftime("%Y-%m-%d")
    out = REPO / "docs" / "benchmarks" / f"rag-eval-{date}.md"
    first = next(iter(results.values()))
    lines = [
        f"# RAG evaluation — {date}",
        "",
        f"Dataset: `backend/tests/data/rag_eval.jsonl` — {len(items)} questions "
        f"({first['n_positive']} positive, {first['n_negative']} negative) "
        "over the three sample videos (bus 10 s, moving traffic 15 s, "
        f"advanced 15 s, 2 scenes). Corpus captions by provider: {providers} "
        f"(VLM model {os.environ['VLM_MODEL']} via Ollama). Embeddings: "
        f"{os.environ['EMBEDDING_PROVIDER']}. Correct hit = right video and "
        "timestamp within ±2 s.",
        "",
        "| Metric | A: DB scan | B: DB + rerank | C: Qdrant | D: Qdrant + rerank |",
        "|---|---|---|---|---|",
    ]
    keys = ("recall_at_1", "recall_at_5", "precision_at_5", "mrr",
            "mean_latency_ms", "faithfulness", "relevance_positives",
            "negatives_correct")
    for key in keys:
        row = " | ".join(str(results[label][key]) for label in results)
        lines.append(f"| {key} | {row} |")
    lines += [
        "",
        "Definitions: faithfulness = share of answers whose citations all "
        "resolve to real stored frames. Relevance (positives) = share of "
        "answers containing an expected keyword. Negatives correct = share "
        "of negative questions refused with no evidence. A vs C isolates "
        "the Qdrant read path; A vs B and C vs D isolate the reranker.",
        "",
        "Full JSON:",
        "```json",
        json.dumps(results, indent=2),
        "```",
        "",
    ]
    out.write_text("\n".join(lines))
    print(f"\nWrote {out}")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
